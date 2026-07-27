from datetime import datetime, timezone
from typing import Optional

from beanie import PydanticObjectId

from app.auth.db.models import RefreshToken
from app.core.logging import get_logger

logger = get_logger(__name__)


class SessionRepository:
    """Repository for MongoDB persistence of persistent refresh token sessions."""

    model = RefreshToken

    async def create_refresh_token(
        self,
        user_id: PydanticObjectId,
        token_hash: str,
        family_id: str,
        expires_at: datetime,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> RefreshToken:
        refresh_doc = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            last_used_at=datetime.now(timezone.utc),
        )
        await refresh_doc.insert()
        return refresh_doc

    async def find_refresh_token_by_hash(
        self,
        token_hash: str,
    ) -> Optional[RefreshToken]:
        return await RefreshToken.find_one({"token_hash": token_hash})

    async def revoke_refresh_token(
        self,
        token_id: PydanticObjectId,
    ) -> None:
        token_doc = await RefreshToken.get(token_id)
        if token_doc:
            token_doc.is_revoked = True
            await token_doc.save()

    async def revoke_token_family(
        self,
        family_id: str,
    ) -> int:
        result = await RefreshToken.find({"family_id": family_id}).update(
            {"$set": {"is_revoked": True}}
        )
        return getattr(result, "modified_count", 0)

    async def revoke_all_user_tokens(
        self,
        user_id: PydanticObjectId,
    ) -> int:
        result = await RefreshToken.find({"user_id": user_id}).update(
            {"$set": {"is_revoked": True}}
        )
        return getattr(result, "modified_count", 0)

    async def find_active_sessions_by_user(
        self,
        user_id: PydanticObjectId,
    ) -> list[RefreshToken]:
        """Find active (non-revoked & non-expired) refresh tokens for user grouped by family_id.
        Returns the latest token document per family_id.
        """
        now = datetime.now(timezone.utc)
        tokens = (
            await RefreshToken.find(
                {
                    "user_id": user_id,
                    "is_revoked": False,
                    "expires_at": {"$gt": now},
                }
            )
            .sort("-last_used_at")
            .to_list()
        )

        seen_families: set[str] = set()
        unique_sessions: list[RefreshToken] = []
        for token in tokens:
            if token.family_id not in seen_families:
                seen_families.add(token.family_id)
                unique_sessions.append(token)
        return unique_sessions

    async def revoke_all_other_families(
        self,
        user_id: PydanticObjectId,
        current_family_id: str,
    ) -> int:
        result = await RefreshToken.find(
            {
                "user_id": user_id,
                "family_id": {"$ne": current_family_id},
                "is_revoked": False,
            }
        ).update({"$set": {"is_revoked": True}})
        return getattr(result, "modified_count", 0)
