from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class AuthIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class ValidateIn(BaseModel):
    session_id: str
    session_token: str
