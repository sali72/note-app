from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import BaseModel, ConfigDict, Field


class FeedbackContext(BaseModel):
    entry_count: int = 0
    days_since_signup: int = 0
    current_view: Optional[str] = None
    locale: str = ""
    session_entry_count: int = 0


class Feedback(Document):
    user_id: str = Field(..., description="User ID who submitted feedback")
    variant: str = Field(..., description="'full' or 'short'")
    trigger: str = Field(..., description="'button', 'session_nudge', or 'exit_intent'")
    answers: dict[str, object] = Field(default_factory=dict)
    context: FeedbackContext = Field(default_factory=FeedbackContext)
    questionnaire_version: str = Field(default="1.0", description="Version of the question set")
    app_version: str = Field(default="", description="App version at submission time, set server-side")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "feedback"
        indexes = [
            "user_id",
            "variant",
            "trigger",
            [("user_id", 1)],
            [("created_at", -1)],
        ]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "variant": "full",
                "trigger": "button",
                "answers": {"usage_frequency": "Daily", "overall_feel": 4},
                "context": {"entry_count": 12, "days_since_signup": 30, "current_view": "journal"},
            }
        }
    )
