from __future__ import annotations

from enum import StrEnum
from typing import Any, Iterable


class ChatActionType(StrEnum):
    CLARIFICATION_REQUIRED = "clarification_required"
    LOGIN_REQUIRED = "login_required"
    RESUME_DOWNLOAD = "resume_download"
    CANCEL_TASK = "cancel_task"


def _unique_strings(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def clarification_action(
    missing_parameters: Iterable[str],
    *,
    recommended_defaults: dict[str, Any] | None = None,
    options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "type": ChatActionType.CLARIFICATION_REQUIRED.value,
        "missing_parameters": _unique_strings(missing_parameters),
        "recommended_defaults": dict(recommended_defaults or {}),
        "options": [dict(item) for item in options or [] if isinstance(item, dict)],
    }


def login_required_action(*, provider: str, job_id: str) -> dict[str, str]:
    return {
        "type": ChatActionType.LOGIN_REQUIRED.value,
        "provider": str(provider).strip(),
        "job_id": str(job_id).strip(),
    }


def resume_download_action(*, job_id: str) -> dict[str, str]:
    return {"type": ChatActionType.RESUME_DOWNLOAD.value, "job_id": str(job_id).strip()}


def cancel_task_action(*, job_id: str) -> dict[str, str]:
    return {"type": ChatActionType.CANCEL_TASK.value, "job_id": str(job_id).strip()}


def normalize_action(action: Any) -> dict[str, Any] | None:
    if not isinstance(action, dict):
        return None
    action_type = str(action.get("type") or "").strip()
    if action_type == ChatActionType.CLARIFICATION_REQUIRED.value:
        return clarification_action(
            action.get("missing_parameters") or [],
            recommended_defaults=action.get("recommended_defaults") if isinstance(action.get("recommended_defaults"), dict) else {},
            options=action.get("options") if isinstance(action.get("options"), list) else [],
        )
    if action_type == ChatActionType.LOGIN_REQUIRED.value:
        return login_required_action(provider=action.get("provider") or "", job_id=action.get("job_id") or "")
    if action_type == ChatActionType.RESUME_DOWNLOAD.value:
        return resume_download_action(job_id=action.get("job_id") or "")
    if action_type == ChatActionType.CANCEL_TASK.value:
        return cancel_task_action(job_id=action.get("job_id") or "")
    return None
