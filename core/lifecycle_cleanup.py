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
    disabled_private_knowledge: list[str] = []
    if clean_session:
        store = CapabilityConfigStore(capability_root)
        for item in store.list_resources("knowledge", include_disabled=True):
            if str(item.get("session_id") or "") != clean_session:
                continue
            if clean_user and str(item.get("owner_user_id") or "") not in {"", clean_user}:
                continue
            if str(item.get("scope") or "").lower() not in {"private", "session", "user"}:
                continue
            knowledge_id = str(item.get("knowledge_id") or "")
            if knowledge_id and item.get("status") != "disabled":
                store.set_status("knowledge", knowledge_id, "disabled")
                disabled_private_knowledge.append(knowledge_id)

    cancelled_jobs: list[str] = []
    if clean_session:
        jobs = DurableJobStore(durable_job_db)
        cancelled_jobs = jobs.cancel_session_jobs(clean_user, clean_session, reason="Session deleted.")

    return {
        "ok": True,
        "user_id": clean_user,
        "session_id": clean_session,
        "disabled_private_knowledge": disabled_private_knowledge,
        "cancelled_jobs": cancelled_jobs,
    }
