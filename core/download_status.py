from __future__ import annotations

from enum import StrEnum
from typing import Any


class DownloadJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_LOGIN = "waiting_login"
    WAITING_PARAMETERS = "waiting_parameters"
    READY_TO_START = "ready_to_start"
    WAITING_MANUAL = "waiting_manual"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_STATUSES = {DownloadJobStatus.COMPLETED, DownloadJobStatus.FAILED, DownloadJobStatus.CANCELED}
ACTIVE_STATUSES = {DownloadJobStatus.QUEUED, DownloadJobStatus.READY_TO_START, DownloadJobStatus.RUNNING, DownloadJobStatus.WAITING_LOGIN, DownloadJobStatus.WAITING_PARAMETERS, DownloadJobStatus.WAITING_MANUAL}
RETRYABLE_STATUSES = {DownloadJobStatus.FAILED, DownloadJobStatus.CANCELED, DownloadJobStatus.WAITING_LOGIN, DownloadJobStatus.WAITING_PARAMETERS, DownloadJobStatus.WAITING_MANUAL}


STATUS_METADATA: dict[str, dict[str, str]] = {
    "queued": {"label": "Queued", "message": "The download job is queued."},
    "running": {"label": "Running", "message": "The download job is running."},
    "waiting_login": {"label": "Login required", "message": "The data source login state is missing or expired."},
    "waiting_parameters": {"label": "Parameters required", "message": "The download job is waiting for required parameters."},
    "ready_to_start": {"label": "Ready", "message": "The download job is ready to start."},
    "waiting_manual": {"label": "Needs attention", "message": "The job needs manual action before it can continue."},
    "completed": {"label": "Completed", "message": "The download job completed and the result was validated."},
    "failed": {"label": "Failed", "message": "The download job failed."},
    "canceled": {"label": "Canceled", "message": "The download job was canceled."},
}


def normalize_status(value: str | None) -> DownloadJobStatus:
    key = str(value or "").strip().lower()
    for status in DownloadJobStatus:
        if status.value == key:
            return status
    return DownloadJobStatus.QUEUED


def failure_diagnostic(error: str | Exception, *, code: str = "download_failed", title: str = "Download failed", next_action: str = "inspect_logs") -> dict[str, str]:
    text = str(error or "").strip()
    lower = text.lower()
    if "timeout" in lower or "timed out" in lower:
        code = "download_timeout"
        title = "Download timed out"
        next_action = "retry_or_check_source"
    elif "login" in lower or "cookie" in lower or "storage_state" in lower:
        code = "login_required"
        title = "Login state required"
        next_action = "relogin"
    elif "invalid" in lower or "corrupt" in lower or "empty" in lower or "zip" in lower:
        code = "invalid_artifact"
        title = "Downloaded file is invalid"
        next_action = "retry_download"
    return {
        "code": code,
        "title": title,
        "user_message": text[:500] or STATUS_METADATA["failed"]["message"],
        "next_action": next_action,
    }


def status_message(status: str | DownloadJobStatus, error_message: str = "") -> str:
    normalized = normalize_status(str(status))
    if normalized == DownloadJobStatus.FAILED and error_message:
        return str(error_message)
    return STATUS_METADATA[normalized.value]["message"]


def decorate_job_record(row: dict[str, Any], json_loads) -> dict[str, Any]:
    status = normalize_status(str(row.get("status") or ""))
    row["status"] = status.value
    row["state"] = {
        DownloadJobStatus.QUEUED: "ready_to_start",
        DownloadJobStatus.COMPLETED: "success",
        DownloadJobStatus.CANCELED: "cancelled",
    }.get(status, status.value)
    row["status_label"] = STATUS_METADATA[status.value]["label"]
    row["message"] = status_message(status, str(row.get("error_message") or ""))

    result = json_loads(row.get("result_json"))
    row["result"] = result

    failure = json_loads(row.get("failure_diagnostic_json"))
    if isinstance(failure, dict):
        row["failure_diagnostic"] = failure
    elif status == DownloadJobStatus.FAILED:
        row["failure_diagnostic"] = failure_diagnostic(row.get("error_message") or "Download failed")

    quality = json_loads(row.get("artifact_quality_json"))
    if isinstance(quality, list):
        row["artifact_quality"] = quality
    elif isinstance(result, dict) and isinstance(result.get("artifact_quality"), list):
        row["artifact_quality"] = result["artifact_quality"]
    return row
