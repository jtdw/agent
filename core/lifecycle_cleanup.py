from __future__ import annotations

from pathlib import Path
from typing import Any

from core.capability_config import CapabilityConfigStore
from core.durable_jobs import DurableJobStore


def cleanup_session_private_state(
    user_id: str,
    session_id: str,
    *,
    capability_root: Path | None = None,
    durable_job_db: Path | None = None,
) -> dict[str, Any]:
    """Clean private, session-scoped state without touching system config."""

    clean_user = str(user_id or "").strip()
    clean_session = str(session_id or "").strip()
    hard_deleted_private_knowledge: list[str] = []
    if clean_session:
        store = CapabilityConfigStore(capability_root)
        hard_deleted_private_knowledge = store.hard_delete_session_private(clean_user, clean_session)

    hard_deleted_durable_jobs: list[str] = []
    if clean_session:
        jobs = DurableJobStore(durable_job_db)
        hard_deleted_durable_jobs = jobs.hard_delete_session_jobs(clean_user, clean_session)

    return {
        "ok": True,
        "user_id": clean_user,
        "session_id": clean_session,
        "hard_deleted_private_knowledge": hard_deleted_private_knowledge,
        "hard_deleted_durable_jobs": hard_deleted_durable_jobs,
        "disabled_private_knowledge": hard_deleted_private_knowledge,
        "cancelled_jobs": hard_deleted_durable_jobs,
        "anonymous_statistics": {
            "private_knowledge_deleted_count": len(hard_deleted_private_knowledge),
            "durable_jobs_deleted_count": len(hard_deleted_durable_jobs),
        },
    }
