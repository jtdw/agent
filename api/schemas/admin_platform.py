from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AdminPlatformAccountIn(BaseModel):
    source_key: str = "gscloud"
    username: str = ""
    password: str = ""
    label: str = ""
    daily_limit: int = 50
    monthly_limit: int = 1000


class AdminPlatformLoginIn(BaseModel):
    timeout_seconds: int = 300
    headless: bool = False


class AdminPlatformStatusIn(BaseModel):
    status: Literal["active", "disabled"] = "disabled"
