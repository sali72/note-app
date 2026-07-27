import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from beanie import PydanticObjectId

from app.auth.config import AuthModuleConfig
from app.auth.db.models import User
from app.auth.db.repository import UserRepository
from app.auth.services.token_blacklist import TokenBlacklistService
from app.core.exceptions import DuplicateDocumentException, RepositoryException
from app.core.logging import get_logger
from app.core.services.email_service import EmailService
from app.core.services.jwt_service import JWTService
from app.core.services.password_service import PasswordService

logger = get_logger(__name__)


class AuthFacade:
    """
    Facade for authentication business logic and orchestration.
    Coordinates between repository, JWT service, password service, email service,
    and token blacklist.
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
                raise ValueError("An account with this email already exists")

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
            raise ValueError("An account with this email already exists")
        except RepositoryException:
            logger.error("user_registration_failed", email=email)
            raise

    async def login(self, email: str, password: str) -> tuple[str, User]:
        """
        Authenticate user with email + password and return a JWT.

        Raises:
            ValueError: If credentials are invalid or the account is
                        Google-only.
        """
        user = await self.repository.find_by_email(email)
        if not user:
            raise ValueError("Invalid email or password")

        # Google-only accounts have no password — redirect the user
        if user.hashed_password is None:
            raise ValueError(
                "This account uses Google Sign-In. "
                "Please sign in with Google."
            )

        if not self.password_service.verify_password(password, user.hashed_password):
            raise ValueError("Invalid email or password")

        if not user.is_active:
            raise ValueError("Account is deactivated")

        if self.config.email_verification_required and not user.is_verified:
            raise ValueError("Please verify your email before logging in")

        await self.repository.update_last_login(user.id)
        access_token = self._generate_token(user)
        return access_token, user

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

    def _generate_token(self, user: User) -> str:
        """Create a signed JWT for the given user."""
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "type": "access",
            "jti": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=self.config.access_token_expire_minutes),
        }
        return self.jwt_service.encode_token(token_data)

    async def verify_token(self, token: str) -> Optional[User]:
        """
        Decode and verify a JWT, checking the Redis blacklist.

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

    async def logout(self, token: str) -> None:
        """Blacklist the JWT so it cannot be used again.

        Best-effort: if the token is already expired or invalid we still
        succeed — the caller should clear the cookie regardless.
        """
        try:
            payload = self.jwt_service.decode_token(token)
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                now = datetime.now(timezone.utc)
                expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
                ttl = max(int((expires_at - now).total_seconds()), 0)
                await self.token_blacklist.blacklist(jti, ttl)
        except Exception:
            logger.warning("logout_token_blacklist_failed")

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


