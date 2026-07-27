from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SessionResponse(BaseModel):
    """Schema representing an active device session."""
    
    family_id: str = Field(..., description="Unique session family identifier")
    device_name: str = Field(..., description="Human-readable device/browser name")
    browser: str = Field(..., description="Browser name")
    os: str = Field(..., description="Operating System")
    ip_address: Optional[str] = Field(default=None, description="Last known IP address")
    created_at: datetime = Field(..., description="Session creation timestamp")
    last_used_at: datetime = Field(..., description="Session last active timestamp")
    is_current: bool = Field(default=False, description="Whether this session is the current requesting device")


class SessionListResponse(BaseModel):
    """Schema representing the list of active user sessions."""
    
    sessions: list[SessionResponse] = Field(default_factory=list)
    total_count: int = Field(..., description="Total active sessions count")
