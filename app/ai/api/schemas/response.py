from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class MirrorReflectionResponse(BaseModel):
    """Response model for mirror reflection."""
    
    reflection: str = Field(..., description="Generated reflection text")
    mode: str = Field(..., description="Reflection mode used")
    available_modes: list[str] = Field(..., description="Available reflection modes")
    error: Optional[str] = Field(None, description="Error message if generation failed")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reflection": "Your recent entries show a beautiful journey toward self-acceptance...",
                "mode": "emotional",
                "available_modes": ["emotional", "cognitive", "behavioral", "relational"],
                "error": None
            }
        }
    )
