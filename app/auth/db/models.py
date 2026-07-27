from datetime import datetime, timezone
from typing import Optional
from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field, EmailStr


class UserPreferences(BaseModel):
    """User preferences for theme and writing settings."""
    mode: str = "system"
    accent: str = "amber"
    fontStyle: str = "serif"
    fontSize: str = "medium"


class RefreshToken(Document):
    """RefreshToken document model for persistent session storage and rotation."""
    
    user_id: PydanticObjectId = Field(...)
    token_hash: str = Field(...)
    family_id: str = Field(...)  # Token family identifier for reuse detection
    is_revoked: bool = Field(default=False)
    user_agent: Optional[str] = Field(default=None)
    ip_address: Optional[str] = Field(default=None)
    last_used_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(...)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "refresh_tokens"
        indexes = [
            "token_hash",
            "user_id",
            "family_id",
            [("expires_at", 1)],  # TTL index: auto-deletes expired records from MongoDB
        ]


class User(Document):
    """User document model for MongoDB."""
    
    email: EmailStr = Field(..., unique=True, max_length=255)
    hashed_password: Optional[str] = Field(default=None)
    google_id: Optional[str] = Field(default=None)
    
    # User metadata
    role: str = Field(default="user")
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)
    
    # Email verification
    verification_token: Optional[str] = Field(default=None)
    verification_token_expires_at: Optional[datetime] = Field(default=None)

    # Preferences
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    
    # Feedback trigger flags (at most once per trigger)
    feedback_triggers: dict[str, bool] = Field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: Optional[datetime] = None
    login_count: int = Field(default=0)
    
    class Settings:
        name = "users"
        indexes = [
            "email",
            "created_at",
            "verification_token",
            [("email", 1)],
        ]
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "is_active": True,
                "is_verified": False
            }
        }
    
    def update_last_login(self) -> None:
        """Update the last login timestamp."""
        self.last_login = datetime.now(timezone.utc)
        self.login_count += 1
