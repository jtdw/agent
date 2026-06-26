from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas.admin_platform import AdminPlatformAccountIn, AdminPlatformLoginIn, AdminPlatformStatusIn


def _require_admin(require_capability_admin: Callable[[Request], None], request: Request) -> None:
    try:
        require_capability_admin(request)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def create_admin_platform_router(
    *,
    commercial_service: Callable[[], Any],
    require_capability_admin: Callable[[Request], None],
    inspect_storage_state: Callable[[str], dict[str, Any]],
    gscloud_platform_state_path: Callable[[Path, str, str], Path | str],
    start_gscloud_login_process: Callable[..., dict[str, Any]],
    workdir: str | Path | Callable[[], str | Path],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/platform-accounts", tags=["admin-platform-accounts"])

    def current_workdir() -> Path:
        value = workdir() if callable(workdir) else workdir
        return Path(value)

    def service() -> Any:
        return commercial_service()

    def platform_account_with_health(account: dict[str, Any]) -> dict[str, Any]:
        account_id = str((account or {}).get("account_id") or "")
        private: dict[str, Any] = {}
        try:
            private = service().get_platform_account_private(account_id)
        except Exception:
            private = {}
        public = service()._platform_public(private) if private else dict(account or {})
        health = inspect_storage_state(str(private.get("storage_state_path") or ""))
        public["login_health"] = health
        public["has_storage_state"] = bool(private.get("storage_state_path"))
        public.pop("storage_state_path", None)
        public.pop("password", None)
        public.pop("encrypted_password", None)
        return public

    @router.get("")
    def list_admin_platform_accounts(request: Request, source_key: str = Query(default="gscloud"), include_inactive: bool = Query(default=True)):
        def run():
            _require_admin(require_capability_admin, request)
            accounts = service().list_platform_accounts(source_key=source_key, include_inactive=include_inactive)
            return {
                "schema_version": "platform-account-management/v1",
                "accounts": [platform_account_with_health(item) for item in accounts],
            }

        return guard(run)

    @router.post("")
    def upsert_admin_platform_account(body: AdminPlatformAccountIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            account = service().upsert_platform_account(
                source_key=body.source_key,
                username=body.username,
                password=body.password,
                label=body.label,
                daily_limit=body.daily_limit,
                monthly_limit=body.monthly_limit,
            )
            service().write_audit_event(
                action="admin.platform_account.upsert",
                status="ok",
                resource_type="platform_account",
                resource_id=str(account.get("account_id") or ""),
                detail={"source_key": body.source_key, "label": body.label or body.source_key},
            )
            return {"ok": True, "account": platform_account_with_health(account)}

        return guard(run)

    @router.post("/{account_id}/login")
    def start_admin_platform_login(account_id: str, body: AdminPlatformLoginIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            account = service().get_platform_account_private(account_id)
            source_key = str(account.get("source_key") or "gscloud").strip().lower()
            if source_key != "gscloud":
                raise ValueError("Current login window only supports GSCloud platform accounts.")
            state_path = gscloud_platform_state_path(current_workdir(), account_id, source_key)
            login_job = start_gscloud_login_process(
                workdir=current_workdir(),
                subject_type="platform_account",
                subject_id=account_id,
                state_path=state_path,
                timeout_seconds=body.timeout_seconds,
                headless=body.headless,
            )
            service().write_audit_event(
                action="admin.platform_account.login_started",
                status="ok",
                resource_type="platform_account",
                resource_id=account_id,
                detail={"source_key": source_key, "login_job_id": login_job.get("login_job_id")},
            )
            safe_job = {
                "login_job_id": login_job.get("login_job_id"),
                "state": login_job.get("state"),
                "message": login_job.get("message"),
                "timeout_seconds": login_job.get("timeout_seconds"),
                "created_at": login_job.get("created_at"),
                "updated_at": login_job.get("updated_at"),
            }
            return {"ok": True, "login_job": safe_job, "account": platform_account_with_health(service().get_platform_account_private(account_id))}

        return guard(run)

    @router.get("/{account_id}/health")
    def check_admin_platform_login_health(account_id: str, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            account = service().get_platform_account_private(account_id)
            health = inspect_storage_state(str(account.get("storage_state_path") or ""))
            service().write_audit_event(
                action="admin.platform_account.login_health",
                status="ok" if health.get("ok") else "warning",
                resource_type="platform_account",
                resource_id=account_id,
                detail={"source_key": account.get("source_key"), "ok": bool(health.get("ok")), "reason": health.get("reason")},
            )
            return {"ok": True, "account_id": account_id, "login_health": health}

        return guard(run)

    @router.post("/{account_id}/status")
    def update_admin_platform_account_status(account_id: str, body: AdminPlatformStatusIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            account = service().set_platform_account_status(account_id, body.status)
            service().write_audit_event(
                action="admin.platform_account.status",
                status="ok",
                resource_type="platform_account",
                resource_id=account_id,
                detail={"status": body.status, "source_key": account.get("source_key")},
            )
            return {"ok": True, "account": platform_account_with_health(account)}

        return guard(run)

    return router
