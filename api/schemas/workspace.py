from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ExportIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    mode: Literal["latest", "all"] = "all"


class ArtifactDeleteIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    artifact_id: str = ""
