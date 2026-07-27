import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.auth.api.schemas.session import SessionResponse
from app.auth.config import AuthModuleConfig
from app.auth.db.models import User
from app.auth.db.session_repository import SessionRepository
from app.auth.services.token_blacklist import TokenBlacklistService
from app.auth.services.token_service import TokenService
from app.auth.services.user_agent_service import parse_user_agent
from app.core.logging import get_logger

logger = get_logger(__name__)


class SessionService:
    """Service for managing user session lifecycles, token rotation (RTR), and Redis blacklisting."""

    def __init__(
        self,
        session_repository: SessionRepository,
        token_service: TokenService,
        token_blacklist: TokenBlacklistService,
        config: AuthModuleConfig,
    ):
        self.repository = session_repository
        self.token_service = token_service
        self.token_blacklist = token_blacklist
        self.config = config

    async def create_session_tokens(
        self,
        user: User,
        family_id: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> tuple[str, str]:
        """Create a fresh access + refresh token pair for a user session.

        If `family_id` is provided, the refresh token continues the family chain (RTR).
        Otherwise, a new family UUID is generated (new login session).
        """
        token_family = family_id or str(uuid.uuid4())
        access_token = self.token_service.generate_access_token(user, family_id=token_family)

        raw_refresh_token = secrets.token_urlsafe(64)
        token_hash = self.token_service.hash_token(raw_refresh_token)

        expires_at = datetime.now(timezone.utc) + timedelta(
            days=self.config.refresh_token_expire_days
        )

        await self.repository.create_refresh_token(
            user_id=user.id,
            token_hash=token_hash,
            family_id=token_family,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return access_token, raw_refresh_token

    async def get_user_sessions(
        self, user: User, current_access_token: Optional[str]
    ) -> list[SessionResponse]:
        """Retrieve active sessions for user, marking is_current for requesting device."""
        current_family_id: Optional[str] = None
        if current_access_token:
            try:
                payload = self.token_service.jwt_service.decode_token(current_access_token)
                current_family_id = payload.get("fam")
            except Exception:
                pass

        active_tokens = await self.repository.find_active_sessions_by_user(user.id)
        sessions: list[SessionResponse] = []

        for token_doc in active_tokens:
            device_name, browser, os_name = parse_user_agent(token_doc.user_agent)
            is_current = (
                token_doc.family_id == current_family_id
                if current_family_id
                else False
            )
            sessions.append(
                SessionResponse(
                    family_id=token_doc.family_id,
                    device_name=device_name,
                    browser=browser,
                    os=os_name,
                    ip_address=token_doc.ip_address,
                    created_at=token_doc.created_at,
                    last_used_at=token_doc.last_used_at,
                    is_current=is_current,
                )
            )

        # Pin current device to top
        sessions.sort(key=lambda s: s.is_current, reverse=True)
        return sessions

    async def revoke_session(self, user: User, family_id: str) -> None:
        """Revoke a specific session family for the user instantly."""
        await self.repository.revoke_token_family(family_id)
        ttl = self.config.access_token_expire_minutes * 60
        await self.token_blacklist.blacklist(f"fam:{family_id}", ttl)

    async def revoke_other_sessions(
        self, user: User, current_access_token: Optional[str]
    ) -> int:
        """Revoke all active session families for user except current family instantly."""
        if not current_access_token:
            raise ValueError("Current access token missing")
        try:
            payload = self.token_service.jwt_service.decode_token(current_access_token)
            current_family_id = payload.get("fam")
        except Exception:
            raise ValueError("Invalid access token")

        if not current_family_id:
            raise ValueError("Current session family identifier missing")

        active_tokens = await self.repository.find_active_sessions_by_user(user.id)
        ttl = self.config.access_token_expire_minutes * 60
        for token_doc in active_tokens:
            if token_doc.family_id != current_family_id:
                await self.token_blacklist.blacklist(f"fam:{token_doc.family_id}", ttl)

        return await self.repository.revoke_all_other_families(
            user_id=user.id, current_family_id=current_family_id
        )
