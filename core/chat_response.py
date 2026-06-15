from __future__ import annotations

from typing import Any, Iterable

from .artifacts import public_artifact_payload
from .response_postprocess import dedupe_assistant_reply, repair_mojibake_text
from .task_outcome_advisor import build_task_outcome, format_task_outcome_markdown


def _message_artifacts(service: Any, result: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        artifact = item
        artifact_id = str(item.get("artifact_id") or "")
        if artifact_id:
            try:
                artifact = service.manager.get_artifact(artifact_id) or item
            except Exception:
                artifact = item
        try:
            public = public_artifact_payload(artifact, workdir=service.manager.workdir)
        except Exception:
            continue
        key = str(public.get("artifact_id") or public.get("download_url") or public.get("filename") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(public)
    return out


def _assistant_message_meta(service: Any, result: dict[str, Any], meta_keys: Iterable[str]) -> dict[str, Any]:
    meta = {key: result.get(key) for key in meta_keys if result.get(key) is not None}
    artifacts = _message_artifacts(service, result)
    if artifacts:
        meta["artifacts"] = artifacts
    if isinstance(result.get("tool_results"), list):
        meta["tool_results"] = result["tool_results"]
    if isinstance(result.get("workflow_summary"), dict):
        meta["workflow_summary"] = result["workflow_summary"]
    if isinstance(result.get("action_required"), dict):
        meta["action_required"] = result["action_required"]
    meta.setdefault("message_format", "markdown")
    meta.setdefault("text", str(result.get("reply") or ""))
    meta.setdefault("markdown", str(result.get("reply") or ""))
    meta.setdefault("code_blocks", [])
    return meta


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
    action_type = str((result.get("action_required") or {}).get("type") or "")
    suppress_outcome = action_type in {"clarification_required", "login_required"}
    if outcome_text and not is_status_query and not suppress_outcome and "任务结果分析：" not in reply:
        reply = f"{reply.rstrip()}\n{outcome_text}"
    reply = dedupe_assistant_reply(repair_mojibake_text(reply))
    assistant_meta = _assistant_message_meta(service, result, meta_keys)
    service.manager.database.add_message(service.current_session_id, "assistant", reply, meta=assistant_meta)
    public_result = {
        key: result[key]
        for key in ("job", "scene_job", "tile_job", "action_required", "artifacts")
        if result.get(key) is not None
    }
    return attach_chat_state(
        service,
        {
            **public_result,
            "reply": reply,
            "model": result.get("model"),
            "reason": result.get("reason"),
            "task_outcome": task_outcome,
        },
    )
