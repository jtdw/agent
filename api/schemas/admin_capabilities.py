from __future__ import annotations

from pydantic import BaseModel


class CapabilityStatusIn(BaseModel):
    status: str = "pending_review"
    actor: str = ""
    summary: str = ""


class CapabilityRollbackIn(BaseModel):
    version: str
    actor: str = ""
    summary: str = ""
