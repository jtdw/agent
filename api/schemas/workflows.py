from __future__ import annotations

from pydantic import BaseModel


class WorkflowIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    run_now: bool = True
