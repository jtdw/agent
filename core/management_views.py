from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ManagementStatus = Literal["succeeded", "failed", "running", "awaiting_confirmation", "blocked", "canceled"]
ManagementAction = Literal["retry", "cancel", "login_required", "view_artifacts", "add_to_map"]


class ManagementRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    title: str = ""
    type: str = ""


class ManagementLayerRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_id: str
    name: str = ""


class DownloadManagementView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "download-management-view/v1"
    task_id: str
    status: ManagementStatus
    progress: float = Field(0.0, ge=0.0, le=100.0)
    display_title: str = ""
    source_name: str = ""
    artifact_refs: list[ManagementRef] = Field(default_factory=list)
    map_layer_refs: list[ManagementLayerRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str = ""
    error_title: str = ""
    user_message: str = ""
    available_actions: list[ManagementAction] = Field(default_factory=list)
    action_state: dict[str, str] = Field(default_factory=dict)
    updated_at: str = ""


TaskManagementView = DownloadManagementView


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    forbidden = (
        "workspace\\",
        "workspace/",
        ":\\",
        "/users/",
        "\\users\\",
        "session_",
        "user_id",
        "session_id",
        "Traceback",
        "storage_state",
        "cookie",
        "token",
    )
    if any(marker.lower() in text.lower() for marker in forbidden):
        return ""
    return text[:limit]


def _status(job: dict[str, Any], tool_result: dict[str, Any]) -> ManagementStatus:
    tool_status = str(tool_result.get("status") or "").strip()
    if tool_status in {"succeeded", "failed", "running", "awaiting_confirmation", "blocked"}:
        return tool_status  # type: ignore[return-value]
    raw = str(job.get("status") or job.get("state") or "").strip().lower()
    if raw in {"completed", "success", "succeeded"}:
        return "succeeded"
    if raw in {"failed"}:
        return "failed"
    if raw in {"canceled", "cancelled"}:
        return "canceled"
    if raw in {"waiting_login", "needs_login", "login_required"}:
        return "awaiting_confirmation"
    if raw in {"waiting_manual", "blocked", "permission_denied"}:
        return "blocked"
    return "running"


def _progress(job: dict[str, Any], status: str) -> float:
    value = job.get("progress")
    try:
        progress = float(value)
    except (TypeError, ValueError):
        progress = 100.0 if status == "succeeded" else 0.0
    return max(0.0, min(100.0, progress))


def _artifact_refs(tool_result: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _as_list(tool_result.get("artifacts")):
        artifact = _as_dict(item)
        artifact_id = _clean_text(artifact.get("artifact_id") or artifact.get("id"), 120)
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        refs.append(
            {
                "artifact_id": artifact_id,
                "title": _clean_text(artifact.get("title") or artifact.get("filename") or artifact.get("name"), 120),
                "type": _clean_text(artifact.get("type") or artifact.get("kind"), 60),
            }
        )
    return refs


def _layer_refs(tool_result: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _as_list(tool_result.get("map_layers")):
        layer = _as_dict(item)
        layer_id = _clean_text(layer.get("layer_id") or layer.get("id"), 120)
        if not layer_id or layer_id in seen:
            continue
        seen.add(layer_id)
        refs.append({"layer_id": layer_id, "name": _clean_text(layer.get("name"), 120)})
    return refs


def _actions(status: str, artifact_refs: list[dict[str, str]], layer_refs: list[dict[str, str]]) -> list[ManagementAction]:
    actions: list[ManagementAction] = []
    if status in {"running", "awaiting_confirmation", "blocked"}:
        actions.append("cancel")
    if status == "awaiting_confirmation":
        actions.append("login_required")
    if status in {"failed", "blocked", "canceled", "awaiting_confirmation"}:
        actions.append("retry")
    if artifact_refs:
        actions.append("view_artifacts")
    if layer_refs:
        actions.append("add_to_map")
    return list(dict.fromkeys(actions))


def _action_state(job: dict[str, Any], status: str) -> dict[str, str]:
    state = {
        "stage": _clean_text(job.get("stage"), 80),
        "state": status,
    }
    for key in (
        "pages_scanned",
        "candidate_count",
        "selected_count",
        "downloaded_count",
        "current_scene",
        "scan_stop_reason",
    ):
        value = _clean_text(job.get(key), 100)
        if value:
            state[key] = value
    return state


def download_job_to_management_view(job: dict[str, Any], *, tool_result: dict[str, Any] | None = None) -> dict[str, Any]:
    row = _as_dict(job)
    result = _as_dict(tool_result)
    status = _status(row, result)
    artifacts = _artifact_refs(result)
    layers = _layer_refs(result)
    errors = [_as_dict(item) for item in _as_list(result.get("errors")) if isinstance(item, dict)]
    first_error = errors[0] if errors else {}
    warnings = [_clean_text(item, 180) for item in _as_list(result.get("warnings")) if _clean_text(item, 180)]
    quality = _as_list(row.get("artifact_quality"))
    if quality:
        warnings.append("成果文件已完成基础检查" if all(_as_dict(item).get("ok") is not False for item in quality) else "部分成果文件未通过基础检查")
    title = (
        _clean_text(row.get("output_name"), 120)
        or _clean_text(row.get("region"), 80)
        or _clean_text(row.get("resource_type"), 80)
        or _clean_text(row.get("job_id"), 80)
    )
    source_bits = [_clean_text(row.get("source_key"), 60), _clean_text(row.get("resource_type"), 80), _clean_text(row.get("region"), 80)]
    action_state = _action_state(row, status)
    failure_diagnostic = row.get("failure_diagnostic")
    failure_message = _as_dict(failure_diagnostic).get("user_message") if isinstance(failure_diagnostic, dict) else ""
    user_message = result.get("user_message") or first_error.get("message") or failure_message
    payload = DownloadManagementView(
        task_id=_clean_text(row.get("job_id") or result.get("task_id"), 120),
        status=status,
        progress=_progress(row, status),
        display_title=title,
        source_name=" / ".join(item for item in source_bits if item),
        artifact_refs=artifacts,
        map_layer_refs=layers,
        warnings=warnings,
        error_code=_clean_text(result.get("error_code") or first_error.get("code"), 80),
        error_title=_clean_text(result.get("error_title") or first_error.get("title"), 120),
        user_message=_clean_text(user_message, 220),
        available_actions=_actions(status, artifacts, layers),
        action_state=action_state,
        updated_at=_clean_text(row.get("updated_at") or row.get("finished_at"), 80),
    )
    return payload.model_dump(mode="json")
