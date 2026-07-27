from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import BaseModel, ConfigDict, Field


class UserModelStats(BaseModel):
    totalEntries: int = 0
    totalWords: int = 0
    lastUpdatedEntryCount: int = 0


class UserModelBaseline(BaseModel):
    emotionalTone: str = ""
    thinkingStyle: str = ""
    selfFocus: str = ""
    confidence: float = 0.0


class PatternItem(BaseModel):
    description: str = ""
    evidence: str = ""


class UserModel(Document):
    user_id: str = Field(..., description="User ID this model belongs to")
    version: int = 1
    updatedAt: Optional[datetime] = None
    stats: UserModelStats = Field(default_factory=UserModelStats)
    baseline: UserModelBaseline = Field(default_factory=UserModelBaseline)
    patterns: list[PatternItem] = Field(default_factory=list)
    activeThemes: list[str] = Field(default_factory=list)
    conversationGuidelines: list[str] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "user_models"
        indexes = ["user_id"]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "version": 1,
                "stats": {"totalEntries": 0, "totalWords": 0, "lastUpdatedEntryCount": 0},
                "baseline": {
                    "emotionalTone": "",
                    "thinkingStyle": "",
                    "selfFocus": "",
                    "confidence": 0.0
                },
                "patterns": [],
                "activeThemes": [],
                "conversationGuidelines": []
            }
        }
    )
