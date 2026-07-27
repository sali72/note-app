from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import ConfigDict, Field


class Tag(Document):
    user_id: str = Field(..., description="User ID who owns this tag")
    name: str = Field(..., description="Normalized tag name (lowercased, stripped)")
    usage_count: int = Field(default=1, ge=0, description="Number of journals using this tag")
    color: Optional[str] = Field(default=None, description="Optional hex color for the tag (e.g. #e74c3c)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "tags"
        indexes = [
            [("user_id", 1), ("name", 1)],
            [("user_id", 1), ("name", "text")],
        ]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "name": "personal",
                "usage_count": 5,
                "created_at": "2024-01-15T10:30:00Z",
            }
        }
    )
