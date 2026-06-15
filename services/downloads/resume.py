from __future__ import annotations

from typing import Any, Callable

from core.commercial.service import CommercialService
from domain.chat.actions import clarification_action, login_required_action
from services.data_sources.gscloud_accounts import GSCloudAccountService


class DownloadResumeService:
    RESUMABLE_STATUSES = {
        "waiting_login",
        "waiting_manual",
        "waiting_parameters",
        "ready_to_start",
        "queued",
    }

    def __init__(
        self,
        commercial: CommercialService,
        accounts: GSCloudAccountService,
        start_download: Callable[..., dict[str, Any]],
    ):
        self.commercial = commercial
        self.accounts = accounts
        self.start_download = start_download

    def resume(self, user_id: str, job_id: str) -> dict[str, Any]:
        job = self.commercial.get_job(job_id)
        if str(job.get("user_id") or "") != str(user_id or ""):
            raise PermissionError("无权访问其他用户的下载任务。")
        if job.get("status") not in self.RESUMABLE_STATUSES:
            raise ValueError(f"当前状态不能恢复: {job.get('status')}")

        region = str(job.get("region") or "").strip()
        if not region:
            self.commercial._update_job(job_id, status="waiting_parameters", stage="needs_region")
            return {
                "job": self.commercial.get_job(job_id),
                "auto_supported": True,
                "auto_started": False,
                "reason": "clarification_required",
                "action_required": clarification_action(
                    ["region"],
                    recommended_defaults={"resolution": "30m", "format": "GeoTIFF", "clip_to_region": True},
                ),
            }

        if not self.accounts.status(user_id).get("logged_in"):
            self.commercial._update_job(job_id, status="waiting_login", stage="needs_gscloud_login_state")
            return {
                "job": self.commercial.get_job(job_id),
                "auto_supported": True,
                "auto_started": False,
                "reason": "login_required",
                "action_required": login_required_action(provider="gscloud", job_id=job_id),
            }

        auto = self.start_download(job, region=region)
        return {"job": self.commercial.get_job(job_id), **auto}
