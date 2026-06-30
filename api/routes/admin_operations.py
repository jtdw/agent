from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from api.schemas.admin_capabilities import CapabilityStatusIn
from api.schemas.admin_operations import AdminStorageCleanupIn, AdminSystemResetIn, DatasetAvailabilityScanIn


SENSITIVE_DIAGNOSTIC_KEYS = {
    "absolute_path",
    "api_key",
    "cookie",
    "env",
    "password",
    "path",
    "prompt",
    "secret",
    "storage_state",
    "storage_state_path",
    "technical_detail",
    "token",
    "workspace_dir",
}
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/][^\s'\"<>]+|/(?:tmp|home|var|etc|root|Users)/[^\s'\"<>]+)", re.IGNORECASE)


def _looks_like_private_path(value: Any) -> bool:
    return bool(PRIVATE_PATH_RE.search(str(value or "")))


def _require_admin(require_capability_admin: Callable[[Request], None], request: Request) -> None:
    try:
        require_capability_admin(request)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _sanitize_agent_runtime_diagnostics(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            clean_key = str(key or "")
            lowered = clean_key.lower()
            if lowered != "environment" and any(token in lowered for token in SENSITIVE_DIAGNOSTIC_KEYS):
                continue
            sanitized[clean_key] = _sanitize_agent_runtime_diagnostics(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_agent_runtime_diagnostics(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(token in lowered for token in ("token", "cookie", ".env", "storage_state")):
            return "[redacted]"
        if _looks_like_private_path(value):
            return "[redacted-path]"
    return value


def _safe_storage_label(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text:
        name = Path(text.replace("\\", "/")).name
        if name:
            return name[:120]
    return str(fallback or "cleanup-candidate")[:120]


def _public_storage_cleanup_scan(payload: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for item in payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or item.get("id") or "").strip()
        if not candidate_id:
            continue
        candidates.append(
            {
                "candidate_id": candidate_id,
                "category": str(item.get("category") or ""),
                "label": _safe_storage_label(item.get("path") or item.get("label"), candidate_id),
                "kind": str(item.get("kind") or ""),
                "file_count": item.get("file_count"),
                "size_bytes": item.get("size_bytes"),
                "safe_to_delete": bool(item.get("safe_to_delete")),
                "reason": str(item.get("reason") or "")[:240],
            }
        )
    return {
        "schema_version": str(payload.get("schema_version") or "storage-cleanup-scan/v1"),
        "candidates": candidates,
        "total_candidates": int(payload.get("total_candidates") or len(candidates)),
        "total_size_bytes": int(payload.get("total_size_bytes") or 0),
        "referenced_path_count": int(payload.get("referenced_path_count") or 0),
    }


def _public_storage_cleanup_delete(payload: dict[str, Any]) -> dict[str, Any]:
    deleted: list[dict[str, Any]] = []
    for item in payload.get("deleted", []) if isinstance(payload.get("deleted"), list) else []:
        if isinstance(item, dict):
            candidate_id = str(item.get("candidate_id") or item.get("id") or "").strip()
            if not candidate_id:
                continue
            deleted.append(
                {
                    "candidate_id": candidate_id,
                    "label": _safe_storage_label(item.get("path") or item.get("label"), candidate_id),
                    "files": item.get("files"),
                    "bytes": item.get("bytes"),
                }
            )
        elif str(item or "").strip():
            candidate_id = str(item).strip()
            deleted.append({"candidate_id": candidate_id, "label": candidate_id})
    raw_errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    errors = []
    for error in raw_errors:
        text = str(error or "").strip()
        if not text:
            continue
        errors.append("[redacted-path]" if _looks_like_private_path(text) else text[:240])
    return {
        "ok": bool(payload.get("ok", not errors)),
        "schema_version": str(payload.get("schema_version") or "storage-cleanup-delete/v1"),
        "deleted": deleted,
        "errors": errors,
        "deleted_count": int(payload.get("deleted_count") or len(deleted)),
        "freed_bytes": int(payload.get("freed_bytes") or 0),
    }


def _redact_path_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "[redacted-path]" if _looks_like_private_path(text) else text[:240]


def _public_system_reset_result(payload: dict[str, Any]) -> dict[str, Any]:
    deleted = payload.get("deleted") if isinstance(payload.get("deleted"), dict) else {}
    preserved = payload.get("preserved") if isinstance(payload.get("preserved"), dict) else {}
    capability_cleanup = payload.get("capability_cleanup") if isinstance(payload.get("capability_cleanup"), dict) else {}
    errors = [
        redacted
        for redacted in (_redact_path_text(item) for item in (deleted.get("errors") if isinstance(deleted.get("errors"), list) else []))
        if redacted
    ]
    return {
        "ok": bool(payload.get("ok", not errors)),
        "mode": str(payload.get("mode") or ""),
        "deleted": {
            "files": int(deleted.get("files") or 0),
            "directories": int(deleted.get("directories") or 0),
            "bytes": int(deleted.get("bytes") or 0),
            "errors": errors,
        },
        "preserved": {
            "workspace_entries": preserved.get("workspace_entries") if isinstance(preserved.get("workspace_entries"), list) else [],
            "accounts": int(preserved.get("accounts") or 0),
            "capability_config": bool(preserved.get("capability_config")),
        },
        "capability_cleanup": {
            "private_knowledge_items": capability_cleanup.get("private_knowledge_items") if isinstance(capability_cleanup.get("private_knowledge_items"), list) else [],
            "index_dirs": capability_cleanup.get("index_dirs") if isinstance(capability_cleanup.get("index_dirs"), list) else [],
        },
    }


def create_admin_operations_router(
    *,
    dataset_availability_store: Callable[[], Any],
    compatibility_usage_store: Callable[[], Any],
    trial_monitoring_store: Callable[[], Any],
    require_capability_admin: Callable[[Request], None],
    scan_dataset_availability: Callable[..., dict[str, Any]],
    reset_system_workspace: Callable[..., dict[str, Any]],
    get_commercial_service: Callable[[], Any],
    set_commercial_service: Callable[[Any], None],
    clear_workspace_services: Callable[[], None],
    ensure_base_dirs: Callable[[], None],
    scan_storage_cleanup_candidates: Callable[[Path], dict[str, Any]],
    cleanup_storage_candidates: Callable[..., dict[str, Any]],
    agent_runtime_diagnostics: Callable[[], dict[str, Any]],
    agent_runtime_rag_readiness: Callable[[], dict[str, Any]] | None = None,
    agent_runtime_exposure: Callable[[], dict[str, Any]] | None = None,
    workdir: str | Path | Callable[[], str | Path],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin-operations"])

    def current_workdir() -> Path:
        value = workdir() if callable(workdir) else workdir
        return Path(value)

    @router.get("/dataset-availability")
    def list_dataset_availability_profiles(request: Request, include_inactive: bool = False):
        def run():
            _require_admin(require_capability_admin, request)
            return {
                "schema_version": "dataset-availability-profile/v1",
                "items": dataset_availability_store().list_profiles(include_inactive=include_inactive),
            }

        return guard(run)

    @router.post("/dataset-availability")
    def upsert_dataset_availability_profile(body: dict[str, Any], request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return {
                "ok": True,
                "schema_version": "dataset-availability-profile/v1",
                "item": dataset_availability_store().upsert_profile(body),
            }

        return guard(run)

    @router.post("/dataset-availability/{product_id}/status")
    def update_dataset_availability_status(product_id: str, body: CapabilityStatusIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return {
                "ok": True,
                "schema_version": "dataset-availability-profile/v1",
                "item": dataset_availability_store().set_status(product_id, body.status, actor=body.actor, summary=body.summary),
            }

        return guard(run)

    @router.post("/dataset-availability/{product_id}/scan")
    def scan_dataset_availability_profile(product_id: str, body: DatasetAvailabilityScanIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            draft = scan_dataset_availability(product_id, scan_method=body.scan_method, actor=body.actor, summary=body.summary)
            return {
                "ok": True,
                "schema_version": "dataset-availability-profile/v1",
                "item": dataset_availability_store().upsert_profile(draft),
            }

        return guard(run)

    @router.get("/compat-usage/report")
    def compatibility_usage_report(request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return compatibility_usage_store().report(exclude_actor_types={"automated_test"})

        return guard(run)

    @router.get("/trial-monitoring/report")
    def trial_monitoring_report(request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return trial_monitoring_store().report(exclude_actor_types={"automated_test"})

        return guard(run)

    @router.get("/agent-runtime/diagnostics")
    def admin_agent_runtime_diagnostics(request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return _sanitize_agent_runtime_diagnostics(agent_runtime_diagnostics())

        return guard(run)

    @router.get("/agent-runtime/exposure")
    def admin_agent_runtime_exposure(request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            if agent_runtime_exposure is None:
                return {
                    "schema_version": "agent-runtime-exposure-policy/v1",
                    "eligible_for_user_exposure": False,
                    "recommendation": "do_not_expose_users",
                    "reasons": ["exposure_policy_unavailable"],
                }
            return _sanitize_agent_runtime_diagnostics(agent_runtime_exposure())

        return guard(run)

    @router.get("/agent-runtime/rag-readiness")
    def admin_agent_runtime_rag_readiness(request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            if agent_runtime_rag_readiness is None:
                return {
                    "schema_version": "agent-runtime-rag-readiness/v1",
                    "mode": "read_only_no_embedding",
                    "status": "unavailable",
                    "operations": {"embedding_calls_performed": 0, "rebuild_available": False},
                }
            return _sanitize_agent_runtime_diagnostics(agent_runtime_rag_readiness())

        return guard(run)

    @router.post("/system-reset")
    def admin_system_reset(body: AdminSystemResetIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            clear_workspace_services()
            result = reset_system_workspace(
                workdir=current_workdir(),
                commercial_service=get_commercial_service(),
                mode=body.mode,
                confirm_text=body.confirm_text,
            )
            set_commercial_service(result.pop("commercial_service"))
            ensure_base_dirs()
            return _public_system_reset_result(result)

        return guard(run)

    @router.get("/storage-cleanup/scan")
    def admin_storage_cleanup_scan(request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return _public_storage_cleanup_scan(scan_storage_cleanup_candidates(current_workdir()))

        return guard(run)

    @router.post("/storage-cleanup/delete")
    def admin_storage_cleanup_delete(body: AdminStorageCleanupIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return _public_storage_cleanup_delete(cleanup_storage_candidates(current_workdir(), candidate_ids=body.candidate_ids, confirm_text=body.confirm_text))

        return guard(run)

    return router
