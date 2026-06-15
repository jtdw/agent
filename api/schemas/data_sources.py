from __future__ import annotations

from pydantic import BaseModel, Field


class GSCloudLoginStartIn(BaseModel):
    timeout_seconds: int = Field(default=300, ge=30, le=900)


class GSCloudLoginCompleteIn(BaseModel):
    login_session_id: str = Field(min_length=1, max_length=120, pattern=r"^login_[A-Za-z0-9_-]+$")
