from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AskIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    user_id: str = ""
    session_id: str = ""
    session_token: str = ""
    task_id: str = ""
    frontend_context: dict = Field(default_factory=dict)


class ChatConfirmIn(BaseModel):
    confirmation_id: str = Field(min_length=1, max_length=200)
    confirmation_prompt: str = Field(default="", max_length=4000)
    user_id: str = ""
    session_id: str = ""
    session_token: str = ""
    task_id: str = ""
    frontend_context: dict = Field(default_factory=dict)


class ChatSessionIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    title: str = ""
    interaction_mode: Literal["chat_only", "tool_enabled"] | None = None


class ChatRetryIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    message_id: int
    content: str = Field(min_length=1, max_length=12000)


class ChatModelIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    model: str = Field(min_length=1, max_length=120)


class ChatCancelIn(BaseModel):
    user_id: str = ""
    task_id: str = Field(min_length=1, max_length=120)
    reason: str = ""
