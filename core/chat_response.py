from __future__ import annotations

from typing import Any, Iterable

from .task_outcome_advisor import build_task_outcome, format_task_outcome_markdown


def attach_chat_state(service: Any, result: dict[str, Any]) -> dict[str, Any]:
    if "task_outcome" not in result:
        result = {**result, "task_outcome": build_task_outcome("general", result, dashboard=service.dashboard())}
    return {
        **result,
        "messages": service.current_messages(),
        "sessions": service.list_sessions(),
        "current_session_id": service.current_session_id,
    }


def build_chat_response(
    service: Any,
    *,
    user_prompt: str,
    result: dict[str, Any],
    meta_keys: Iterable[str] = ("model", "reason"),
) -> dict[str, Any]:
    if not service.current_session_id:
        service.current_session_id = service._ensure_session()
    if not service.current_messages():
        service.manager.database.rename_conversation(service.current_session_id, service._default_title(user_prompt))

    service.manager.database.add_message(service.current_session_id, "user", user_prompt)
    reason = str(result.get("reason") or "")
    task_type = "download" if any(key in result for key in ("job", "scene_job", "tile_job")) else "analysis"
    task_outcome = build_task_outcome(task_type, result, dashboard=service.dashboard())
    reply = str(result.get("reply") or "")
    outcome_text = format_task_outcome_markdown(task_outcome)
    is_status_query = reason in {"download_status", "commercial_download_status"} or reason.endswith("_status")
    if outcome_text and not is_status_query and "任务结果分析：" not in reply:
        reply = f"{reply.rstrip()}\n{outcome_text}"
    assistant_meta = {key: result.get(key) for key in meta_keys if result.get(key) is not None}
    service.manager.database.add_message(service.current_session_id, "assistant", reply, meta=assistant_meta)
    return attach_chat_state(
        service,
        {
            "reply": reply,
            "model": result.get("model"),
            "reason": result.get("reason"),
            "task_outcome": task_outcome,
        },
    )
