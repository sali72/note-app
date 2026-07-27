import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from beanie import PydanticObjectId

from app.auth.api.schemas.session import SessionResponse
from app.auth.config import AuthModuleConfig
from app.auth.db.models import User
from app.auth.db.repository import UserRepository
from app.auth.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    SessionNotFoundError,
    TokenRevokedError,
    UserAlreadyExistsError,
)
from app.auth.services.token_blacklist import TokenBlacklistService
from app.auth.services.user_agent_service import parse_user_agent
from app.core.exceptions import DuplicateDocumentException, RepositoryException
from app.core.logging import get_logger
from app.core.services.email_service import EmailService
from app.core.services.jwt_service import JWTService
from app.core.services.password_service import PasswordService

logger = get_logger(__name__)


from app.auth.services.session_service import SessionService
from app.auth.services.token_service import TokenService


class AuthFacade:
    """
    Facade for authentication business logic and orchestration.
    Coordinates between repository, token service, session service, password service,
    email service, and token blacklist.
    """

    def __init__(
        self,
        repository: UserRepository,
        jwt_service: JWTService,
        password_service: PasswordService,
        email_service: EmailService,
        token_blacklist: TokenBlacklistService,
        config: AuthModuleConfig,
    ):
        self.repository = repository
        self.jwt_service = jwt_service
        self.password_service = password_service
        self.email_service = email_service
        self.token_blacklist = token_blacklist
        self.config = config
        self.token_service = TokenService(jwt_service=jwt_service, config=config)
        self.session_service = SessionService(
            session_repository=repository._session_repo,
            token_service=self.token_service,
            token_blacklist=token_blacklist,
            config=config,
        )

    async def register(self, email: str, password: str) -> User:
        """
        Register a new user.

        Args:
            email: User email address
            password: Plain text password

        Returns:
            Created user

        Raises:
            ValueError: If validation fails or email already exists
            RepositoryException: If database operation fails
        """
        try:
            # Check if email already exists
            if await self.repository.email_exists(email):
                raise UserAlreadyExistsError("An account with this email already exists")

            # Hash password
            hashed_password = self.password_service.hash_password(password)

            # Create user
            user = await self.repository.create(
                email=email.lower(), hashed_password=hashed_password
            )

            if self.config.email_verification_required:
                token, _ = await self.repository.store_verification_token(
                    user.id,
                    expires_in_hours=self.config.verification_token_expire_hours,
                )
                self.email_service.send_verification_email(email, token)
            else:
                await self.repository.clear_verification_token(user.id)

            logger.info("user_registered", user_id=str(user.id), email=email)
            return user
        except DuplicateDocumentException:
            # Race condition: email was created between check and insert
            logger.warning("user_registration_race_condition", email=email)
            raise UserAlreadyExistsError("An account with this email already exists")
        except RepositoryException:
            logger.error("user_registration_failed", email=email)
            raise

    def _hash_token(self, token: str) -> str:
        """Compute SHA256 hex digest of a raw refresh token."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _generate_token(self, user: User, family_id: Optional[str] = None) -> str:
        """Create a signed JWT for the given user, embedding family_id if provided."""
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "type": "access",
            "jti": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=self.config.access_token_expire_minutes),
        }
        if family_id:
            token_data["fam"] = family_id
        return self.jwt_service.encode_token(token_data)

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
        access_token = self._generate_token(user, family_id=token_family)

        raw_refresh_token = secrets.token_urlsafe(64)
        token_hash = self._hash_token(raw_refresh_token)

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

    async def login(
        self,
        email: str,
        password: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> tuple[str, str, User]:
        """
        Authenticate user with email + password and return (access_token, refresh_token, user).
        """
        user = await self.repository.find_by_email(email)
        if not user:
            raise InvalidCredentialsError("Invalid email or password")

        # Google-only accounts have no password — redirect the user
        if user.hashed_password is None:
            raise InvalidCredentialsError(
                "This account uses Google Sign-In. "
                "Please sign in with Google."
            )

        if not self.password_service.verify_password(password, user.hashed_password):
            raise InvalidCredentialsError("Invalid email or password")

        if not user.is_active:
            raise InvalidCredentialsError("Account is deactivated")

        if self.config.email_verification_required and not user.is_verified:
            raise InvalidCredentialsError("Please verify your email before logging in")

        await self.repository.update_last_login(user.id)
        access_token, refresh_token = await self.create_session_tokens(
            user, user_agent=user_agent, ip_address=ip_address
        )
        return access_token, refresh_token, user

    async def refresh_access_token(
        self,
        raw_refresh_token: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> tuple[str, str, User]:
        """Validate an incoming refresh token, rotate it, and return new access + refresh tokens.

        Implements Refresh Token Rotation (RTR) and Reuse Detection:
        If a revoked token is reused, all active tokens in its family are immediately revoked!
        """
        token_hash = self._hash_token(raw_refresh_token)
        token_doc = await self.repository.find_refresh_token_by_hash(token_hash)

        if not token_doc:
            raise InvalidTokenError("Invalid refresh token")

        now = datetime.now(timezone.utc)
        exp = token_doc.expires_at.replace(tzinfo=timezone.utc) if token_doc.expires_at.tzinfo is None else token_doc.expires_at
        if exp < now:
            raise InvalidTokenError("Refresh token expired")

        if token_doc.is_revoked:
            # REUSE ATTACK DETECTED!
            # Revoke all tokens in this family to protect the user
            await self.repository.revoke_token_family(token_doc.family_id)
            logger.warning(
                "refresh_token_reuse_detected",
                family_id=token_doc.family_id,
                user_id=str(token_doc.user_id),
            )
            raise TokenRevokedError("Revoked refresh token reuse detected")

        # Revoke the used refresh token
        await self.repository.revoke_refresh_token(token_doc.id)

        # Get user
        user = await self.get_user_by_id(str(token_doc.user_id))
        if not user or not user.is_active:
            raise InvalidCredentialsError("User account is inactive or not found")

        # Use updated user_agent and ip_address if provided, else fallback to token_doc values
        ua = user_agent if user_agent else token_doc.user_agent
        ip = ip_address if ip_address else token_doc.ip_address

        # Issue new token pair preserving the same family_id
        new_access_token, new_refresh_token = await self.create_session_tokens(
            user=user,
            family_id=token_doc.family_id,
            user_agent=ua,
            ip_address=ip,
        )
        return new_access_token, new_refresh_token, user

    async def get_user_sessions(
        self, user: User, current_access_token: Optional[str]
    ) -> list[SessionResponse]:
        """Retrieve active sessions for user, marking is_current for requesting device."""
        return await self.session_service.get_user_sessions(
            user=user, current_access_token=current_access_token
        )

    async def revoke_session(self, user: User, family_id: str) -> None:
        """Revoke a specific session family for the user instantly."""
        await self.session_service.revoke_session(user=user, family_id=family_id)

    async def revoke_other_sessions(
        self, user: User, current_access_token: Optional[str]
    ) -> int:
        """Revoke all active session families for user except current family instantly."""
        return await self.session_service.revoke_other_sessions(
            user=user, current_access_token=current_access_token
        )

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Get user by ID.

        Args:
            user_id: User ID string

        Returns:
            User or None if not found
        """
        try:
            obj_id = PydanticObjectId(user_id)
        except Exception as e:
            logger.warning("invalid_user_id", user_id=user_id, error=str(e))
            return None

        return await self.repository.find_by_id(obj_id)

    async def verify_token(self, token: str) -> Optional[User]:
        """
        Decode and verify a JWT, checking the Redis blacklist for JTI and Family ID.

        Returns:
            User if the token is valid and not blacklisted, else ``None``.
        """
        try:
            payload = self.jwt_service.decode_token(token)

            # Reject blacklisted tokens (immediate logout)
            jti = payload.get("jti")
            if jti and await self.token_blacklist.is_blacklisted(jti):
                logger.info("token_blacklisted", jti=jti)
                return None

            # Reject blacklisted session families (instant remote revocation)
            fam = payload.get("fam")
            if fam and await self.token_blacklist.is_blacklisted(f"fam:{fam}"):
                logger.info("session_family_blacklisted", family_id=fam)
                return None

            user_id = payload.get("sub")
            if not user_id:
                return None

            user = await self.get_user_by_id(user_id)
            return user
        except Exception as e:
            logger.warning("verify_token_failed", error=str(e))
            return None

    async def find_or_create_google_user(
        self, google_id: str, email: str
    ) -> User:
        """Find an existing user by Google ID or email, or create a new one.

        1. Match by ``google_id`` → return existing linked user.
        2. Match by ``email`` → link Google account, mark verified, return.
        3. Neither → create a new user with ``google_id`` + verified email.
        """
        # 1 – Already linked
        user = await self.repository.find_by_google_id(google_id)
        if user:
            await self.repository.update_last_login(user.id)
            return user

        # 2 – Link by email
        user = await self.repository.find_by_email(email)
        if user:
            if not user.is_verified and user.hashed_password is not None:
                # Prevent Pre-Account Takeover: clear password if unverified
                await self.repository.update_password(user.id, None)

            user = await self.repository.link_google_account(user.id, google_id)
            if not user:
                raise ValueError("Failed to link Google account")
            await self.repository.update_last_login(user.id)
            logger.info(
                "google_account_linked",
                user_id=str(user.id),
                email=email,
                google_id=google_id,
            )
            return user

        # 3 – Create
        user = await self.repository.create(
            email=email,
            google_id=google_id,
            is_verified=True,
        )
        await self.repository.update_last_login(user.id)
        logger.info(
            "google_user_created",
            user_id=str(user.id),
            email=email,
            google_id=google_id,
        )
        return user

    async def logout(
        self, token: Optional[str] = None, raw_refresh_token: Optional[str] = None
    ) -> None:
        """Blacklist the access token JWT and revoke the refresh token session family in MongoDB.

        Best-effort: if either token is expired or invalid we still succeed.
        """
        if token:
            try:
                payload = self.jwt_service.decode_token(token)
                jti = payload.get("jti")
                exp = payload.get("exp")
                family_id = payload.get("fam")

                if jti and exp:
                    now = datetime.now(timezone.utc)
                    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
                    ttl = max(int((expires_at - now).total_seconds()), 0)
                    await self.token_blacklist.blacklist(jti, ttl)

                if family_id:
                    await self.repository.revoke_token_family(family_id)
            except Exception as e:
                logger.warning("logout_token_blacklist_failed", error=str(e))

        if raw_refresh_token:
            try:
                token_hash = self._hash_token(raw_refresh_token)
                token_doc = await self.repository.find_refresh_token_by_hash(token_hash)
                if token_doc:
                    await self.repository.revoke_token_family(token_doc.family_id)
            except Exception as e:
                logger.warning("logout_refresh_token_revoke_failed", error=str(e))

    async def update_preferences(self, user_id: str, preferences: dict) -> User:
        """
        Update user preferences (partial update, merges with existing).

        Args:
            user_id: User ID string
            preferences: Dictionary of preference fields to update

        Returns:
            Updated user

        Raises:
            ValueError: If user not found
        """
        try:
            obj_id = PydanticObjectId(user_id)
        except Exception as e:
            logger.warning("invalid_user_id", user_id=user_id, error=str(e))
            raise ValueError("Invalid user ID")

        user = await self.repository.find_by_id(obj_id)
        if not user:
            raise ValueError("User not found")

        current = user.preferences.model_dump() if user.preferences else {}
        current.update(preferences)

        updated = await self.repository.update_preferences(obj_id, current)
        if not updated:
            raise ValueError("Failed to update preferences")

        return updated

    async def verify_email(self, token: str) -> User:
        """
        Verify a user's email address using a verification token.

        Args:
            token: Verification token

        Returns:
            Verified user

        Raises:
            ValueError: If token is invalid or expired
        """
        user = await self.repository.find_by_verification_token(token)
        if not user:
            raise ValueError("Invalid verification token")

        if user.verification_token_expires_at and user.verification_token_expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise ValueError("Verification token has expired")

        updated = await self.repository.clear_verification_token(user.id)
        if not updated:
            raise ValueError("Failed to verify email")

        logger.info("email_verified", user_id=str(user.id), email=user.email)
        return updated

    async def resend_verification(self, email: str) -> None:
        """
        Resend verification email.

        Args:
            email: User email address

        Raises:
            ValueError: If user not found or already verified
        """
        user = await self.repository.find_by_email(email)
        if not user:
            raise ValueError("No account found with this email")

        if user.is_verified:
            raise ValueError("Email is already verified")

        token, _ = await self.repository.store_verification_token(
            user.id,
            expires_in_hours=self.config.verification_token_expire_hours,
        )
        self.email_service.send_verification_email(email, token)

        logger.info("verification_resent", user_id=str(user.id), email=email)

    async def reset_password(self, email: str) -> bool:
        """
        Initiate password reset process.

        Args:
            email: User email address

        Returns:
            True (always returns True to prevent email enumeration)

        Note:
            In production, this should:
            1. Generate a secure reset token
            2. Store token with expiration in database
            3. Send email with reset link
            4. Implement /reset-password/{token} endpoint to complete reset

            For now, this is a placeholder that logs the request.
        """
        # Check if user exists
        user = await self.repository.find_by_email(email)

        if user:
            logger.info("password_reset_requested", email=email, user_id=str(user.id))
            # In production: Generate token, store it, send email
            # Example:
            # reset_token = secrets.token_urlsafe(32)
            # await self.repository.store_reset_token(user.id, reset_token, expires_in=3600)
            # await email_service.send_reset_email(email, reset_token)
        else:
            logger.info("password_reset_requested_unknown_email", email=email)

        # Always return True to prevent email enumeration
        return True


