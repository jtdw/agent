from __future__ import annotations

from pathlib import Path
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
        if ":/" in value or ":\\" in value:
            return "[redacted-path]"
    return value


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
            return result

        return guard(run)

    @router.get("/storage-cleanup/scan")
    def admin_storage_cleanup_scan(request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return scan_storage_cleanup_candidates(current_workdir())

        return guard(run)

    @router.post("/storage-cleanup/delete")
    def admin_storage_cleanup_delete(body: AdminStorageCleanupIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return cleanup_storage_candidates(current_workdir(), candidate_ids=body.candidate_ids, confirm_text=body.confirm_text)

        return guard(run)

    return router
