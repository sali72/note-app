import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from beanie import PydanticObjectId
from beanie.odm.queries.update import UpdateResponse
from pymongo.errors import PyMongoError, DuplicateKeyError

from app.auth.db.models import User, RefreshToken
from app.core.exceptions import RepositoryException, DuplicateDocumentException
from app.core.logging import get_logger

logger = get_logger(__name__)


class UserRepository:
    """Repository for user data access operations."""

    def __init__(self):
        self.model = User

    async def create(
        self,
        email: str,
        hashed_password: Optional[str] = None,
        google_id: Optional[str] = None,
        is_verified: bool = False,
    ) -> User:
        try:
            user = User(
                email=email.lower(),
                hashed_password=hashed_password,
                google_id=google_id,
                is_verified=is_verified,
            )
            await user.insert()
            logger.info("user_created", user_id=str(user.id), email=email)
            return user
        except DuplicateKeyError:
            logger.warning("user_duplicate_email", email=email)
            raise DuplicateDocumentException("User", "email", email)
        except PyMongoError as e:
            logger.error("user_create_failed", error=str(e), email=email)
            raise RepositoryException(
                f"Failed to create user: {str(e)}",
                details={"email": email, "error": str(e)}
            )

    async def find_by_email(
        self,
        email: str,
    ) -> Optional[User]:
        try:
            return await self.model.find_one({"email": email.lower()})
        except PyMongoError as e:
            logger.error("user_find_by_email_failed", error=str(e), email=email)
            raise RepositoryException(
                f"Failed to find user by email: {str(e)}",
                details={"email": email, "error": str(e)}
            )

    async def find_by_google_id(
        self,
        google_id: str,
    ) -> Optional[User]:
        try:
            return await self.model.find_one({"google_id": google_id})
        except PyMongoError as e:
            logger.error("user_find_by_google_id_failed", error=str(e), google_id=google_id)
            raise RepositoryException(
                f"Failed to find user by google_id: {str(e)}",
                details={"google_id": google_id, "error": str(e)}
            )

    async def link_google_account(
        self,
        user_id: PydanticObjectId,
        google_id: str,
    ) -> Optional[User]:
        try:
            user = await self.model.find_one({"_id": user_id}).update(
                {"$set": {
                    "google_id": google_id,
                    "is_verified": True,
                    "updated_at": datetime.now(timezone.utc),
                }},
                response_type=UpdateResponse.NEW_DOCUMENT,
            )
            if user:
                logger.info("google_account_linked", user_id=str(user_id), google_id=google_id)
            return user
        except PyMongoError as e:
            logger.error("google_account_link_failed", error=str(e), user_id=str(user_id))
            raise RepositoryException(
                f"Failed to link Google account: {str(e)}",
                details={"user_id": str(user_id), "error": str(e)}
            )

    async def mark_verified(
        self,
        user_id: PydanticObjectId,
    ) -> Optional[User]:
        try:
            user = await self.model.find_one({"_id": user_id}).update(
                {"$set": {
                    "is_verified": True,
                    "verification_token": None,
                    "verification_token_expires_at": None,
                    "updated_at": datetime.now(timezone.utc),
                }},
                response_type=UpdateResponse.NEW_DOCUMENT,
            )
            if user:
                logger.info("user_marked_verified", user_id=str(user_id))
            return user
        except PyMongoError as e:
            logger.error("user_mark_verified_failed", error=str(e), user_id=str(user_id))
            raise RepositoryException(
                f"Failed to mark user verified: {str(e)}",
                details={"user_id": str(user_id), "error": str(e)}
            )

    async def find_by_id(
        self,
        user_id: PydanticObjectId,
    ) -> Optional[User]:
        try:
            return await self.model.find_one({"_id": user_id})
        except PyMongoError as e:
            logger.error("user_find_by_id_failed", error=str(e), user_id=str(user_id))
            raise RepositoryException(
                f"Failed to find user by ID: {str(e)}",
                details={"user_id": str(user_id), "error": str(e)}
            )

    async def update_password(
        self,
        user_id: PydanticObjectId,
        hashed_password: Optional[str],
    ) -> Optional[User]:
        try:
            user = await self.model.find_one({"_id": user_id}).update(
                {"$set": {
                    "hashed_password": hashed_password,
                    "updated_at": datetime.now(timezone.utc),
                }},
                response_type=UpdateResponse.NEW_DOCUMENT,
            )
            if user:
                logger.info("user_password_updated", user_id=str(user_id))
            return user
        except PyMongoError as e:
            logger.error("user_password_update_failed", error=str(e), user_id=str(user_id))
            raise RepositoryException(
                f"Failed to update password: {str(e)}",
                details={"user_id": str(user_id), "error": str(e)}
            )

    async def update_last_login(
        self,
        user_id: PydanticObjectId,
    ) -> bool:
        try:
            user = await self.find_by_id(user_id)
            if not user:
                return False

            user.update_last_login()
            await user.save()
            logger.debug("user_last_login_updated", user_id=str(user_id))
            return True
        except PyMongoError as e:
            logger.error("user_last_login_update_failed", error=str(e), user_id=str(user_id))
            raise RepositoryException(
                f"Failed to update last login: {str(e)}",
                details={"user_id": str(user_id), "error": str(e)}
            )

    async def update_preferences(
        self,
        user_id: PydanticObjectId,
        preferences: dict,
    ) -> Optional[User]:
        try:
            user = await self.model.find_one({"_id": user_id}).update(
                {"$set": {"preferences": preferences, "updated_at": datetime.now(timezone.utc)}},
                response_type=UpdateResponse.NEW_DOCUMENT,
            )
            if user:
                logger.info("user_preferences_updated", user_id=str(user_id))
            return user
        except PyMongoError as e:
            logger.error("user_preferences_update_failed", error=str(e), user_id=str(user_id))
            raise RepositoryException(
                f"Failed to update preferences: {str(e)}",
                details={"user_id": str(user_id), "error": str(e)}
            )

    async def email_exists(
        self,
        email: str,
    ) -> bool:
        user = await self.find_by_email(email)
        return user is not None

    async def store_verification_token(
        self,
        user_id: PydanticObjectId,
        expires_in_hours: int = 24,
    ) -> tuple[str, User]:
        token = secrets.token_urlsafe(32)
        user = await self.model.find_one({"_id": user_id}).update(
            {"$set": {
                "verification_token": token,
                "verification_token_expires_at": datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
                "updated_at": datetime.now(timezone.utc),
            }},
            response_type=UpdateResponse.NEW_DOCUMENT,
        )
        if not user:
            raise ValueError("User not found")
        return token, user

    async def find_by_verification_token(
        self,
        token: str,
    ) -> Optional[User]:
        try:
            return await self.model.find_one({"verification_token": token})
        except PyMongoError as e:
            logger.error("user_find_by_token_failed", error=str(e))
            raise RepositoryException(
                f"Failed to find user by verification token: {str(e)}",
                details={"error": str(e)}
            )

    async def clear_verification_token(
        self,
        user_id: PydanticObjectId,
    ) -> Optional[User]:
        return await self.model.find_one({"_id": user_id}).update(
            {"$set": {
                "verification_token": None,
                "verification_token_expires_at": None,
                "is_verified": True,
                "updated_at": datetime.now(timezone.utc),
            }},
            response_type=UpdateResponse.NEW_DOCUMENT,
        )

    # ------------------------------------------------------------------
    # Refresh Token persistence & rotation methods
    # ------------------------------------------------------------------

    async def create_refresh_token(
        self,
        user_id: PydanticObjectId,
        token_hash: str,
        family_id: str,
        expires_at: datetime,
    ) -> RefreshToken:
        refresh_doc = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
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
