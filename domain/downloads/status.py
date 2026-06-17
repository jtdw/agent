from __future__ import annotations

from enum import StrEnum


class DownloadJobStatus(StrEnum):
    WAITING_PARAMETERS = "waiting_parameters"
    WAITING_LOGIN = "waiting_login"
    READY_TO_START = "ready_to_start"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_MANUAL = "waiting_manual"

    COMPLETED = "success"
    CANCELED = "cancelled"


_ALIASES = {
    "completed": DownloadJobStatus.SUCCESS,
    "complete": DownloadJobStatus.SUCCESS,
    "succeeded": DownloadJobStatus.SUCCESS,
    "canceled": DownloadJobStatus.CANCELLED,
    "cancelled": DownloadJobStatus.CANCELLED,
}

_STORAGE_VALUES = {
    DownloadJobStatus.SUCCESS: "completed",
    DownloadJobStatus.CANCELLED: "canceled",
}


def normalize_status(value: str | DownloadJobStatus | None) -> DownloadJobStatus:
    if isinstance(value, DownloadJobStatus):
        return value
    key = str(value or "").strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    try:
        return DownloadJobStatus(key)
    except ValueError:
        return DownloadJobStatus.QUEUED


def storage_status(value: str | DownloadJobStatus | None) -> str:
    normalized = normalize_status(value)
    return _STORAGE_VALUES.get(normalized, normalized.value)
