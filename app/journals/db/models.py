from datetime import datetime, timezone
from typing import Optional
import re
from beanie import Document
from pydantic import ConfigDict, Field, field_validator


class Journal(Document):
    """Journal document model for MongoDB."""

    user_id: str = Field(..., description="User ID who owns this journal")
    title: Optional[str] = Field(default=None, max_length=200)
    content: str = Field(..., max_length=50000)
    tags: list[str] = Field(default_factory=list)
    rumination_index: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Real-time rumination signal (0-1). >= 0.70 triggers grounding in chat."
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        if len(v) > 20:
            raise ValueError("Maximum 20 tags allowed")
        for tag in v:
            if len(tag) > 50:
                raise ValueError(f"Tag exceeds maximum length of 50 characters: '{tag[:30]}...'")
            if not re.match(r'^[\w\s-]+$', tag):
                raise ValueError(
                    f"Tag '{tag}' contains invalid characters. "
                    "Only letters, numbers, spaces, underscores, and hyphens are allowed."
                )
        return v

    class Settings:
        name = "journals"
        indexes = [
            "user_id",
            "created_at",
            "tags",
            [("user_id", 1), ("created_at", -1)],
            [("user_id", 1), ("tags", 1)],
        ]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "title": "My First Journal Entry",
                "content": "Today was a great day for reflection...",
                "tags": ["personal", "reflection"]
            }
        }
    )
