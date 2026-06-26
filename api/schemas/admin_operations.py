from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DatasetAvailabilityScanIn(BaseModel):
    scan_method: str = "catalog_metadata"
    actor: str = ""
    summary: str = ""


class AdminSystemResetIn(BaseModel):
    mode: Literal["keep_accounts", "full_reset"]
    confirm_text: str = ""


class AdminStorageCleanupIn(BaseModel):
    candidate_ids: list[str] = []
    confirm_text: str = ""
