import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.auth.config import AuthModuleConfig
from app.auth.db.models import User
from app.core.services.jwt_service import JWTService


class TokenService:
    """Service for JWT token generation and SHA-256 token hashing."""

    def __init__(self, jwt_service: JWTService, config: AuthModuleConfig):
        self.jwt_service = jwt_service
        self.config = config

    def hash_token(self, token: str) -> str:
        """Compute SHA256 hex digest of a raw token string."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def generate_access_token(
        self, user: User, family_id: Optional[str] = None
    ) -> str:
        """Create a signed JWT access token for the given user, embedding family_id if provided."""
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
