from __future__ import annotations

from pydantic import BaseModel


class LocalLibraryImportIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    item_ids: list[str] = []
