from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: str = Field(..., description="user or assistant")
    content: str = Field(..., description="Message content")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Chat(Document):
    user_id: str = Field(..., description="User ID who owns this chat")
    title: str = Field(default="", max_length=100, description="Auto-generated title")
    messages: list[ChatMessage] = Field(default_factory=list)
    linked_entry_id: Optional[str] = Field(
        default=None,
        description="Journal entry ID if opened from [T-5]",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "chats"
        indexes = [
            "user_id",
            [("user_id", 1), ("created_at", -1)],
        ]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "title": "Discussion about work stress",
                "messages": [
                    {"role": "user", "content": "I've been feeling stressed at work", "created_at": "2024-01-15T10:30:00Z"},
                    {"role": "assistant", "content": "Tell me more about what's causing the stress...", "created_at": "2024-01-15T10:30:05Z"},
                ],
                "linked_entry_id": None,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:05Z",
            }
        }
    )
