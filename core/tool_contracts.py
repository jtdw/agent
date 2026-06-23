from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


CANONICAL_STATUSES = {"succeeded", "failed", "running", "awaiting_confirmation", "blocked"}
SUCCESS_STATUSES = {"succeeded"}
NON_TERMINAL_STATUSES = {"running", "awaiting_confirmation"}
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/][^\s`'\"<>]+|workspace[\\/][^\s`'\"<>]+)", re.IGNORECASE)
SENSITIVE_TOKENS = ("storage_state", "cookie", "password", "secret", "token")


@dataclass
class ToolPrecondition:
    name: str
    required_inputs: list[str] = field(default_factory=list)
    required_dataset_type: str = ""
    required_fields: list[str] = field(default_factory=list)
    required_crs: str = ""
    required_geometry: str = ""
    optional_inputs: list[str] = field(default_factory=list)
    validation_errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactInfo:
    artifact_id: str
    path: str
    type: str
    title: str
    description: str = ""
    quality_status: str = "unchecked"
    preview_available: bool = False
    created_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolResult:
    ok: bool
    tool_name: str
    task_id: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    error_code: str = ""
    error_title: str = ""
    user_message: str = ""
    technical_detail: str = ""
    status: str = ""
    success: bool | None = None
    map_layers: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    execution_id: str = ""
    plan_id: str = ""
    workflow_id: str = ""
    step_id: str = ""
    input_asset_ids: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: _now())
    finished_at: str = ""

    def __post_init__(self) -> None:
        if self.status not in CANONICAL_STATUSES:
            self.status = "succeeded" if bool(self.ok) else "failed"
        if self.success is None:
            self.success = self.status in SUCCESS_STATUSES
        self.ok = bool(self.success)
        if not self.execution_id:
            self.execution_id = self.task_id or _new_task_id(self.tool_name or "tool")
        if not self.finished_at and self.status not in NON_TERMINAL_STATUSES:
            self.finished_at = _now()
        if self.status in {"failed", "blocked"} and not self.errors:
            self.errors = [
                {
                    "code": self.error_code or ("TOOL_BLOCKED" if self.status == "blocked" else "TOOL_FAILED"),
                    "title": self.error_title or "",
                    "message": self.user_message or self.technical_detail or "",
                }
            ]

    def to_dict(self) -> dict[str, Any]:
        return normalize_tool_result(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_task_id(tool_name: str) -> str:
    return f"{tool_name}_{uuid4().hex[:10]}"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe_mixed(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    output: list[Any] = []
    for item in items:
        try:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            key = str(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _clean_text(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    text = PATH_RE.sub("[internal_path]", text)
    for token in SENSITIVE_TOKENS:
        text = re.sub(token, "[redacted]", text, flags=re.IGNORECASE)
    return text[:limit]


def _coerce_status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in CANONICAL_STATUSES:
        return status
    if status in {"success", "successful", "complete", "completed", "ok"}:
        return "succeeded"
    if status in {"failure", "error", "exception"}:
        return "failed"
    if status in {"needs_confirmation", "confirmation_required", "requires_confirmation", "waiting_login"}:
        return "awaiting_confirmation"
    if status in {"skipped", "denied"}:
        return "blocked"
    return "succeeded" if bool(payload.get("ok") or payload.get("success")) else "failed"


def _artifact_dicts(items: list[ArtifactInfo | dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        if isinstance(item, ArtifactInfo):
            out.append(item.to_dict())
        elif isinstance(item, dict):
            out.append(dict(item))
    return out


def _normalize_artifacts(items: Any, warnings: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _as_list(items):
        if not isinstance(item, dict):
            continue
        artifact = dict(item)
        path = str(artifact.get("path") or artifact.get("absolute_path") or "")
        if path:
            exists = Path(path).exists()
            artifact.setdefault("status", "available" if exists else "missing")
            if not exists:
                warnings.append(f"Artifact is missing: {Path(path).name}")
        else:
            artifact.setdefault("status", "unresolved")
        out.append(artifact)
    return out


def _normalize_errors(payload: dict[str, Any], status: str) -> list[dict[str, Any]]:
    errors = [item for item in _as_list(payload.get("errors")) if isinstance(item, dict)]
    if errors:
        return [
            {
                "code": str(item.get("code") or item.get("error_code") or payload.get("error_code") or "TOOL_FAILED"),
                "title": str(item.get("title") or item.get("error_title") or payload.get("error_title") or ""),
                "message": _clean_text(item.get("message") or item.get("user_message") or item.get("detail") or ""),
            }
            for item in errors
        ]
    if status in {"failed", "blocked"} or payload.get("error_code") or payload.get("user_message"):
        return [
            {
                "code": str(payload.get("error_code") or ("TOOL_BLOCKED" if status == "blocked" else "TOOL_FAILED")),
                "title": str(payload.get("error_title") or ""),
                "message": _clean_text(payload.get("user_message") or payload.get("technical_detail") or payload.get("error_message") or ""),
            }
        ]
    return []


def normalize_tool_result(
    value: Any,
    *,
    tool_name: str = "",
    plan_id: str = "",
    workflow_id: str = "",
    step_id: str = "",
) -> dict[str, Any]:
    if isinstance(value, ToolResult):
        payload = asdict(value)
    elif isinstance(value, dict):
        payload = dict(value)
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("ToolResult JSON is invalid") from exc
        if not isinstance(parsed, dict):
            raise ValueError("ToolResult JSON must decode to an object")
        payload = parsed
    else:
        raise TypeError("Unsupported ToolResult payload")

    resolved_tool = str(payload.get("tool_name") or tool_name or "").strip()
    if not resolved_tool:
        raise ValueError("ToolResult requires tool_name")

    status = _coerce_status(payload)
    success = status in SUCCESS_STATUSES
    task_id = str(payload.get("task_id") or payload.get("execution_id") or _new_task_id(resolved_tool))
    warnings = [item for item in _as_list(payload.get("warnings")) if str(item).strip()]
    artifacts = _normalize_artifacts(payload.get("artifacts"), warnings)
    errors = _normalize_errors(payload, status)
    error_code = str(payload.get("error_code") or (_as_dict(errors[0]).get("code") if errors else ""))
    error_title = str(payload.get("error_title") or (_as_dict(errors[0]).get("title") if errors else ""))
    user_message = _clean_text(payload.get("user_message") or (_as_dict(errors[0]).get("message") if errors else ""), limit=800)
    diagnostics = _as_dict(payload.get("diagnostics"))
    technical_detail = _clean_text(payload.get("technical_detail") or "", limit=1000)
    finished_at = str(payload.get("finished_at") or "")
    if not finished_at and status not in NON_TERMINAL_STATUSES:
        finished_at = _now()

    normalized = {
        "ok": success,
        "success": success,
        "status": status,
        "tool_name": resolved_tool,
        "task_id": task_id,
        "execution_id": str(payload.get("execution_id") or task_id),
        "plan_id": str(payload.get("plan_id") or plan_id or ""),
        "workflow_id": str(payload.get("workflow_id") or workflow_id or ""),
        "step_id": str(payload.get("step_id") or step_id or ""),
        "input_asset_ids": [str(item) for item in _as_list(payload.get("input_asset_ids")) if str(item).strip()],
        "started_at": str(payload.get("started_at") or _now()),
        "finished_at": finished_at,
        "inputs": _as_dict(payload.get("inputs")),
        "outputs": _as_dict(payload.get("outputs")),
        "artifacts": artifacts,
        "map_layers": [item for item in _as_list(payload.get("map_layers")) if isinstance(item, dict)],
        "tables": [item for item in _as_list(payload.get("tables")) if isinstance(item, dict)],
        "images": [item for item in _as_list(payload.get("images")) if isinstance(item, dict)],
        "summary": str(payload.get("summary") or ""),
        "diagnostics": diagnostics,
        "warnings": _dedupe_mixed(warnings),
        "errors": errors,
        "next_actions": [str(item) for item in _as_list(payload.get("next_actions")) if str(item).strip()],
        "error_code": error_code,
        "error_title": error_title,
        "user_message": user_message,
        "technical_detail": technical_detail,
    }
    return normalized


def _make_result(
    tool_name: str,
    status: str,
    *,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    artifacts: list[ArtifactInfo | dict[str, Any]] | None = None,
    map_layers: list[dict[str, Any]] | None = None,
    tables: list[dict[str, Any]] | None = None,
    images: list[dict[str, Any]] | None = None,
    summary: str = "",
    diagnostics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    error_code: str = "",
    error_title: str = "",
    user_message: str = "",
    technical_detail: str = "",
    task_id: str | None = None,
    plan_id: str = "",
    workflow_id: str = "",
    step_id: str = "",
    input_asset_ids: list[str] | None = None,
) -> ToolResult:
    success = status in SUCCESS_STATUSES
    return ToolResult(
        ok=success,
        success=success,
        status=status,
        tool_name=tool_name,
        task_id=task_id or _new_task_id(tool_name),
        inputs=inputs or {},
        outputs=outputs or {},
        artifacts=_artifact_dicts(artifacts),
        map_layers=[item for item in (map_layers or []) if isinstance(item, dict)],
        tables=[item for item in (tables or []) if isinstance(item, dict)],
        images=[item for item in (images or []) if isinstance(item, dict)],
        summary=summary,
        diagnostics=diagnostics or {},
        warnings=warnings or [],
        next_actions=next_actions or [],
        error_code=error_code,
        error_title=error_title,
        user_message=user_message,
        technical_detail=technical_detail,
        plan_id=plan_id,
        workflow_id=workflow_id,
        step_id=step_id,
        input_asset_ids=input_asset_ids or [],
    )


def tool_result_ok(
    tool_name: str,
    *,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    artifacts: list[ArtifactInfo | dict[str, Any]] | None = None,
    map_layers: list[dict[str, Any]] | None = None,
    tables: list[dict[str, Any]] | None = None,
    images: list[dict[str, Any]] | None = None,
    summary: str = "",
    diagnostics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    task_id: str | None = None,
    **trace: Any,
) -> ToolResult:
    return _make_result(
        tool_name,
        "succeeded",
        inputs=inputs,
        outputs=outputs,
        artifacts=artifacts,
        map_layers=map_layers,
        tables=tables,
        images=images,
        summary=summary,
        diagnostics=diagnostics,
        warnings=warnings,
        next_actions=next_actions,
        task_id=task_id,
        plan_id=str(trace.get("plan_id") or ""),
        workflow_id=str(trace.get("workflow_id") or ""),
        step_id=str(trace.get("step_id") or ""),
        input_asset_ids=trace.get("input_asset_ids") if isinstance(trace.get("input_asset_ids"), list) else None,
    )


def tool_result_error(
    tool_name: str,
    *,
    inputs: dict[str, Any] | None = None,
    error_code: str = "TOOL_PRECONDITION_FAILED",
    error_title: str = "Tool precondition failed",
    user_message: str = "The tool is missing required inputs.",
    technical_detail: str = "",
    diagnostics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    task_id: str | None = None,
    **trace: Any,
) -> ToolResult:
    return _make_result(
        tool_name,
        "failed",
        inputs=inputs,
        error_code=error_code,
        error_title=error_title,
        user_message=user_message,
        technical_detail=technical_detail,
        diagnostics=diagnostics,
        warnings=warnings,
        next_actions=next_actions,
        task_id=task_id,
        plan_id=str(trace.get("plan_id") or ""),
        workflow_id=str(trace.get("workflow_id") or ""),
        step_id=str(trace.get("step_id") or ""),
        input_asset_ids=trace.get("input_asset_ids") if isinstance(trace.get("input_asset_ids"), list) else None,
    )


def tool_result_running(tool_name: str, **kwargs: Any) -> ToolResult:
    return _make_result(tool_name, "running", **kwargs)


def tool_result_awaiting_confirmation(
    tool_name: str,
    *,
    error_code: str = "CONFIRMATION_REQUIRED",
    error_title: str = "Confirmation required",
    user_message: str = "User confirmation is required before continuing.",
    **kwargs: Any,
) -> ToolResult:
    return _make_result(tool_name, "awaiting_confirmation", error_code=error_code, error_title=error_title, user_message=user_message, **kwargs)


def tool_result_blocked(
    tool_name: str,
    *,
    error_code: str = "TOOL_BLOCKED",
    error_title: str = "Tool blocked",
    user_message: str = "The tool cannot continue until the blocking condition is resolved.",
    **kwargs: Any,
) -> ToolResult:
    return _make_result(tool_name, "blocked", error_code=error_code, error_title=error_title, user_message=user_message, **kwargs)


def parse_tool_result(value: Any) -> dict[str, Any] | None:
    try:
        if isinstance(value, dict):
            has_legacy = {"ok", "tool_name", "task_id", "inputs", "outputs", "artifacts"}.issubset(value)
            has_canonical = {"status", "tool_name", "outputs", "artifacts"}.issubset(value)
            if not has_legacy and not has_canonical:
                return None
        return normalize_tool_result(value)
    except Exception:
        return None


def is_tool_result_success(result: dict[str, Any]) -> bool:
    status = str(_as_dict(result).get("status") or "").lower()
    if status:
        return status in SUCCESS_STATUSES
    return bool(_as_dict(result).get("ok"))


def workflow_step_to_tool_result(step: Any) -> dict[str, Any]:
    data = step.to_dict() if hasattr(step, "to_dict") else _as_dict(step)
    result = _as_dict(data.get("tool_result"))
    return normalize_tool_result(
        result or {
            "status": "running" if str(data.get("status") or "") in {"pending", "running"} else "blocked",
            "tool_name": data.get("tool_name") or "workflow_step",
            "task_id": str(data.get("step_id") or _new_task_id("workflow_step")),
            "inputs": _as_dict(data.get("validated_tool_args")),
            "outputs": {},
            "artifacts": [],
        },
        tool_name=str(data.get("tool_name") or "workflow_step"),
        workflow_id=str(data.get("workflow_id") or ""),
        step_id=str(data.get("step_id") or ""),
    )


def aggregate_tool_results(results: list[Any], *, tool_name: str = "tool_executor", workflow_id: str = "", plan_id: str = "") -> dict[str, Any]:
    normalized = [normalize_tool_result(item, workflow_id=workflow_id, plan_id=plan_id) for item in results if item is not None]
    artifacts: list[dict[str, Any]] = []
    warnings: list[Any] = []
    errors: list[dict[str, Any]] = []
    next_actions: list[str] = []
    for item in normalized:
        artifacts.extend(_as_list(item.get("artifacts")))
        warnings.extend(w for w in _as_list(item.get("warnings")) if str(w).strip())
        errors.extend(error for error in _as_list(item.get("errors")) if isinstance(error, dict))
        next_actions.extend(str(action) for action in _as_list(item.get("next_actions")) if str(action).strip())
    failed = next((item for item in normalized if str(item.get("status")) in {"failed", "blocked"}), None)
    running = next((item for item in normalized if str(item.get("status")) == "running"), None)
    awaiting = next((item for item in normalized if str(item.get("status")) == "awaiting_confirmation"), None)
    status = "failed" if failed and failed.get("status") == "failed" else "blocked" if failed else "awaiting_confirmation" if awaiting else "running" if running else "succeeded"
    source = failed or awaiting or running or {}
    payload = {
        "status": status,
        "tool_name": tool_name,
        "task_id": _new_task_id(tool_name),
        "inputs": {"executed_tools": [item.get("tool_name") for item in normalized]},
        "outputs": {"tool_results": normalized, "executed_tools": [item.get("tool_name") for item in normalized]},
        "artifacts": artifacts,
        "summary": "Executed deterministic GIS tool plan." if status == "succeeded" else "Deterministic GIS tool plan did not complete successfully.",
        "diagnostics": {"tool_count": len(normalized), "failed_tool": source.get("tool_name") or ""},
        "warnings": _dedupe_mixed(warnings),
        "errors": errors,
        "next_actions": list(dict.fromkeys(next_actions)),
        "error_code": str(source.get("error_code") or ""),
        "error_title": str(source.get("error_title") or ""),
        "user_message": str(source.get("user_message") or ""),
        "plan_id": plan_id,
        "workflow_id": workflow_id,
    }
    return normalize_tool_result(payload)


def _download_artifacts(job: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    result = _as_dict(job.get("result"))
    for item in _as_list(result.get("artifacts")) + _as_list(result.get("artifact_refs")):
        artifact = _as_dict(item)
        artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or "").strip()
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "path": str(artifact.get("path") or ""),
                "type": str(artifact.get("type") or artifact.get("kind") or "download"),
                "title": str(artifact.get("title") or artifact.get("name") or artifact_id),
                "description": str(artifact.get("description") or f"Download job {job.get('job_id') or ''} artifact"),
                "quality_status": str(artifact.get("quality_status") or "ok"),
                "preview_available": bool(artifact.get("preview_available", False)),
            }
        )
    for key in ("zip_path", "output_path"):
        raw = str(job.get(key) or "").strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        path = Path(raw)
        if not path.exists() or not path.is_file():
            continue
        artifacts.append(
            {
                "artifact_id": f"download:{job.get('job_id') or path.name}:{key}",
                "path": str(path),
                "type": "download_package" if key == "zip_path" else str(job.get("resource_type") or "download"),
                "title": path.name,
                "description": f"Download job {job.get('job_id') or ''} {key}",
                "quality_status": "ok",
                "preview_available": False,
            }
        )
    return artifacts


def _public_job_summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(job.get("job_id") or ""),
        "status": str(job.get("status") or job.get("state") or ""),
        "stage": str(job.get("stage") or ""),
        "progress": job.get("progress", 0),
        "source_key": str(job.get("source_key") or ""),
        "resource_type": str(job.get("resource_type") or ""),
        "region": str(job.get("region") or ""),
        "start_date": str(job.get("start_date") or ""),
        "end_date": str(job.get("end_date") or ""),
        "account_mode": str(job.get("account_mode") or ""),
        "output_name": str(job.get("output_name") or ""),
        "updated_at": str(job.get("updated_at") or ""),
        "finished_at": str(job.get("finished_at") or ""),
    }


def _public_subjob_summary(job: dict[str, Any] | None, id_key: str) -> dict[str, Any]:
    if not isinstance(job, dict):
        return {}
    return {
        id_key: str(job.get(id_key) or ""),
        "job_id": str(job.get("job_id") or ""),
        "state": str(job.get("state") or job.get("status") or ""),
        "message": _clean_text(job.get("message") or "", limit=500),
        "product_key": str(job.get("product_key") or ""),
        "updated_at": str(job.get("updated_at") or ""),
        "pages_scanned": job.get("pages_scanned"),
        "candidate_count": job.get("candidate_count"),
        "selected_count": job.get("selected_count"),
        "downloaded_count": job.get("downloaded_count"),
    }


def _download_error(job: dict[str, Any], status: str) -> tuple[str, str, str]:
    failure = _as_dict(job.get("failure_diagnostic"))
    code = str(failure.get("code") or "")
    title = str(failure.get("title") or "")
    message = _clean_text(failure.get("user_message") or job.get("message") or job.get("error_message") or "")
    if status == "awaiting_confirmation":
        return "LOGIN_REQUIRED", title or "Login required", message or "The data source login state is missing or expired."
    if status == "blocked":
        return (code.upper() if code else "DOWNLOAD_BLOCKED"), title or "Download blocked", message or "The download job needs manual action before it can continue."
    if status == "failed":
        return (code.upper() if code else "DOWNLOAD_FAILED"), title or "Download failed", message or "The download job failed."
    return "", "", ""


def download_job_to_tool_result(job: dict[str, Any], *, scene_job: dict[str, Any] | None = None, tile_job: dict[str, Any] | None = None) -> dict[str, Any]:
    row = _as_dict(job)
    raw_status = str(row.get("status") or row.get("state") or "").strip().lower()
    scene_state = str(_as_dict(scene_job).get("state") or "").strip().lower()
    tile_state = str(_as_dict(tile_job).get("state") or "").strip().lower()
    if raw_status in {"completed", "succeeded", "success"}:
        status = "succeeded"
    elif raw_status in {"waiting_login", "needs_login", "login_required"}:
        status = "awaiting_confirmation"
    elif raw_status in {"waiting_manual", "blocked", "permission_denied"}:
        status = "blocked"
    elif raw_status in {"failed", "canceled", "cancelled"} or scene_state == "failed" or tile_state == "failed":
        status = "failed"
    elif raw_status in {"queued", "running"} or scene_state in {"starting", "scanning", "downloading", "packaging"} or tile_state in {"starting", "planning", "running", "downloading"}:
        status = "running"
    else:
        status = "running"
    error_code, error_title, user_message = _download_error(row, status)
    diagnostics = {
        "job": _public_job_summary(row),
        "scene_job": _public_subjob_summary(scene_job, "scene_job_id"),
        "tile_job": _public_subjob_summary(tile_job, "tile_job_id"),
        "artifact_quality": [item for item in _as_list(row.get("artifact_quality")) if isinstance(item, dict)],
    }
    next_actions = []
    if status == "awaiting_confirmation":
        next_actions.append("Refresh the data source login state, then retry the download job.")
    elif status == "blocked":
        next_actions.append("Resolve the blocking condition, then retry or resubmit the download job.")
    elif status == "running":
        next_actions.append("Poll the download job status until it reaches a terminal state.")
    elif status == "failed":
        next_actions.append("Review the safe failure diagnostic, then retry the job after fixing the cause.")
    payload = {
        "status": status,
        "tool_name": "download_job",
        "task_id": str(row.get("job_id") or _new_task_id("download_job")),
        "inputs": {
            "source_key": row.get("source_key"),
            "resource_type": row.get("resource_type"),
            "region": row.get("region"),
            "start_date": row.get("start_date"),
            "end_date": row.get("end_date"),
        },
        "outputs": {
            "job_id": row.get("job_id"),
            "source_key": row.get("source_key"),
            "resource_type": row.get("resource_type"),
            "status": row.get("status"),
            "progress": row.get("progress"),
        },
        "artifacts": _download_artifacts(row),
        "summary": f"Download job {row.get('job_id') or ''} is {status}.",
        "diagnostics": diagnostics,
        "next_actions": next_actions,
        "error_code": error_code,
        "error_title": error_title,
        "user_message": user_message,
        "started_at": str(row.get("created_at") or _now()),
        "finished_at": str(row.get("finished_at") or ""),
    }
    return normalize_tool_result(payload)
