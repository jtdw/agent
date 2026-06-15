"""Compatibility exports for the centralized download domain model."""

from domain.downloads.models import STATUS_METADATA, decorate_job_record, failure_diagnostic, status_message
from domain.downloads.policies import ACTIVE_STATUSES, RETRYABLE_STATUSES, TERMINAL_STATUSES
from domain.downloads.status import DownloadJobStatus, normalize_status, storage_status

__all__ = [
    "ACTIVE_STATUSES",
    "DownloadJobStatus",
    "RETRYABLE_STATUSES",
    "STATUS_METADATA",
    "TERMINAL_STATUSES",
    "decorate_job_record",
    "failure_diagnostic",
    "normalize_status",
    "status_message",
    "storage_status",
]
