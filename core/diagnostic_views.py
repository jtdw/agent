from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


DiagnosticLevel = Literal["info", "warning", "error"]


class DiagnosticEventView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "diagnostic-event-view/v1"
    timestamp: str = ""
    phase: str = ""
    level: DiagnosticLevel = "info"
    summary: str = ""
    error_code: str = ""
    next_action: str = ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_text(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    forbidden = (
        "cookie",
        "token",
        "authorization",
        "storage_state",
        "user_id",
        "session_id",
        "traceback",
        "request headers",
        "workspace\\",
        "workspace/",
        ":\\",
        "/users/",
        "\\users\\",
    )
    if any(marker in text.lower() for marker in forbidden):
        return ""
    return text[:limit]


def diagnostic_event_view(raw: dict[str, Any], *, default_phase: str = "") -> dict[str, Any]:
    item = _as_dict(raw)
    failure = _as_dict(item.get("failure_diagnostic"))
    raw_level = str(item.get("level") or item.get("severity") or item.get("status") or "").strip().lower()
    if raw_level in {"failed", "failure", "error", "exception"} or item.get("error_message") or failure:
        level: DiagnosticLevel = "error"
    elif raw_level in {"warning", "warn", "blocked"}:
        level = "warning"
    else:
        level = "info"
    phase = _clean_text(item.get("phase") or item.get("stage") or item.get("step") or default_phase, 100)
    summary = (
        _clean_text(item.get("summary"), 220)
        or _clean_text(item.get("message"), 220)
        or _clean_text(failure.get("user_message"), 220)
        or _clean_text(item.get("status"), 120)
        or phase
        or "事件已记录"
    )
    payload = DiagnosticEventView(
        timestamp=_clean_text(item.get("timestamp") or item.get("updated_at") or item.get("created_at") or item.get("time"), 80),
        phase=phase,
        level=level,
        summary=summary,
        error_code=_clean_text(item.get("error_code") or failure.get("code"), 80),
        next_action=_clean_text(item.get("next_action") or failure.get("next_action"), 180),
    )
    return payload.model_dump(mode="json")


def diagnostic_event_views(items: list[Any], *, default_phase: str = "") -> list[dict[str, Any]]:
    return [diagnostic_event_view(item, default_phase=default_phase) for item in items if isinstance(item, dict)]
