from __future__ import annotations

from .status import DownloadJobStatus, normalize_status


TERMINAL_STATUSES = {
    DownloadJobStatus.SUCCESS,
    DownloadJobStatus.FAILED,
    DownloadJobStatus.CANCELLED,
}
ACTIVE_STATUSES = {
    DownloadJobStatus.QUEUED,
    DownloadJobStatus.READY_TO_START,
    DownloadJobStatus.RUNNING,
    DownloadJobStatus.WAITING_LOGIN,
    DownloadJobStatus.WAITING_PARAMETERS,
    DownloadJobStatus.WAITING_MANUAL,
}
RETRYABLE_STATUSES = {
    DownloadJobStatus.FAILED,
    DownloadJobStatus.CANCELLED,
    DownloadJobStatus.WAITING_LOGIN,
    DownloadJobStatus.WAITING_PARAMETERS,
    DownloadJobStatus.WAITING_MANUAL,
}


def is_terminal(value: str | DownloadJobStatus | None) -> bool:
    return normalize_status(value) in TERMINAL_STATUSES


def is_active(value: str | DownloadJobStatus | None) -> bool:
    return normalize_status(value) in ACTIVE_STATUSES


def is_retryable(value: str | DownloadJobStatus | None) -> bool:
    return normalize_status(value) in RETRYABLE_STATUSES
