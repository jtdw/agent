from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class PaymentIn(BaseModel):
    user_id: str
    plan: Literal["pro", "team"] = "pro"
