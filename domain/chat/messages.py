from __future__ import annotations

from typing import Any, TypedDict


class ChatMessagePayload(TypedDict, total=False):
    role: str
    content: str
    meta: dict[str, Any]
    artifacts: list[dict[str, Any]]
    action_required: dict[str, Any]
