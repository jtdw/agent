from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.commercial.login_jobs import read_gscloud_login_job, start_gscloud_login_process
from core.commercial.service import CommercialService
from core.domestic_sources.gscloud_adapter import gscloud_user_state_path
from core.domestic_sources.gscloud_reliability import inspect_storage_state


class GSCloudAccountService:
    def __init__(self, commercial: CommercialService):
        self.commercial = commercial

    def state_path(self, user_id: str) -> Path:
        return gscloud_user_state_path(self.commercial.workdir, user_id, "gscloud")

    def status(self, user_id: str) -> dict[str, Any]:
        registered_path = self.commercial.get_user_storage_state_path(user_id, "gscloud")
        state_path = Path(registered_path) if registered_path else self.state_path(user_id)
        health = inspect_storage_state(state_path)
        logged_in = bool(registered_path and health.get("ok"))
        return {
            "provider": "gscloud",
            "logged_in": logged_in,
            "account_mode": "own",
            "last_checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at": None,
            "masked_account": None,
            "storage_state_exists": state_path.exists(),
            "health_status": "healthy" if logged_in else str(health.get("reason") or "login_required"),
            "user_message": "地理空间数据云账号已登录。" if logged_in else "需要登录地理空间数据云账号。",
        }

    def start_login(self, user_id: str, *, timeout_seconds: int = 300) -> dict[str, Any]:
        login_job = start_gscloud_login_process(
            workdir=self.commercial.workdir,
            subject_type="customer",
            subject_id=user_id,
            state_path=self.state_path(user_id),
            timeout_seconds=timeout_seconds,
            headless=False,
        )
        return {
            "provider": "gscloud",
            "login_session_id": str(login_job.get("login_job_id") or ""),
            "state": str(login_job.get("state") or "STARTING"),
            "user_message": str(login_job.get("message") or "已打开地理空间数据云登录窗口。"),
            "poll_interval_ms": 2000,
        }

    def complete_login(self, user_id: str, login_session_id: str) -> dict[str, Any]:
        login_job = read_gscloud_login_job(self.commercial.workdir, login_session_id)
        if str(login_job.get("subject_type") or "customer") != "customer" or str(login_job.get("subject_id") or "") != user_id:
            raise PermissionError("无权访问其他用户的数据源登录会话。")

        state = str(login_job.get("state") or "")
        state_path = self.state_path(user_id)
        health = inspect_storage_state(state_path)
        if state == "COMPLETED" and health.get("ok"):
            self.commercial.set_user_credential_storage_state(user_id, "gscloud", str(state_path))
            waiting_jobs = [
                job
                for job in self.commercial.list_jobs(user_id=user_id, limit=100)
                if job.get("source_key") == "gscloud" and job.get("status") == "waiting_login"
            ]
            return {
                **self.status(user_id),
                "login_session_id": login_session_id,
                "login_state": state,
                "pending": False,
                "waiting_jobs": waiting_jobs,
            }

        if state not in {"COMPLETED", "FAILED", "CANCELLED"}:
            pending = self.status(user_id)
            pending.update(
                {
                    "logged_in": False,
                    "health_status": "login_in_progress",
                    "user_message": "请在地理空间数据云官方页面完成登录，系统确认成功后会自动关闭窗口。",
                }
            )
            return {
                **pending,
                "login_session_id": login_session_id,
                "login_state": state,
                "pending": True,
            }

        return {
            **self.status(user_id),
            "login_session_id": login_session_id,
            "login_state": state,
            "pending": False,
        }

    def logout(self, user_id: str) -> dict[str, Any]:
        self.commercial.clear_user_storage_state(user_id, "gscloud")
        return self.status(user_id)
