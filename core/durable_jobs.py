from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.tool_contracts import normalize_tool_result
from core.realtime_events import TaskEventStore


DURABLE_JOB_SCHEMA_VERSION = "durable-job-store/v1"
JOB_STATUSES = {
    "queued",
    "running",
    "awaiting_confirmation",
    "waiting_login",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
}
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "expired"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_db_path() -> Path:
    return Path.cwd() / "workspace" / "durable_jobs.db"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _loads(text: str | None) -> Any:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _elapsed_ms(started_at: str, *, now: datetime | None = None) -> int:
    if not started_at:
        return 0
    try:
        started = datetime.fromisoformat(str(started_at))
    except Exception:
        return 0
    current = now or datetime.now()
    return max(0, int((current - started).total_seconds() * 1000))


def _tool_status(job_status: str) -> str:
    if job_status == "succeeded":
        return "succeeded"
    if job_status in {"queued", "running", "waiting_login"}:
        return "running" if job_status in {"queued", "running"} else "awaiting_confirmation"
    if job_status == "awaiting_confirmation":
        return "awaiting_confirmation"
    if job_status in {"cancelled", "expired"}:
        return "blocked"
    return "failed"


def _error_code(job_status: str, code: str = "") -> str:
    if code:
        return code
    return {
        "cancelled": "JOB_CANCELLED",
        "expired": "JOB_EXPIRED",
        "failed": "JOB_FAILED",
        "waiting_login": "LOGIN_REQUIRED",
        "awaiting_confirmation": "CONFIRMATION_REQUIRED",
    }.get(job_status, "")


class DurableJobStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self.events = TaskEventStore(self.db_path)

    def _publish_job_event(self, job: dict[str, Any]) -> None:
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        raw_status = str(job.get("status") or "")
        status = {
            "expired": "failed",
        }.get(raw_status, raw_status)
        if status not in {"queued", "running", "awaiting_confirmation", "waiting_login", "succeeded", "failed", "cancelled"}:
            return
        kind = "task_progress" if status == "running" and int(job.get("progress") or 0) not in {0, 100} else "task_status"
        if status == "succeeded":
            kind = "task_result"
        elif status == "failed":
            kind = "error"
        elif status == "cancelled":
            kind = "warning"
        phase = str(job.get("phase") or status or "")
        current_step = str(job.get("current_step") or job.get("job_type") or "")
        heartbeat_at = _now()
        started_at = str(job.get("started_at") or job.get("created_at") or "")
        elapsed_ms = _elapsed_ms(started_at)
        timeout_reason = str(job.get("timeout_reason") or "")
        message = str(job.get("error_message") or "")
        if not message:
            message = {
                "queued": "任务已排队，等待后台执行。",
                "running": "任务正在执行。",
                "awaiting_confirmation": "任务正在等待确认。",
                "waiting_login": "任务正在等待完成登录。",
                "succeeded": "任务已完成，正在整理结果。",
                "failed": "任务执行失败。",
                "cancelled": "任务已取消。",
            }.get(status, "任务状态已更新。")
        task_update = {
            "interaction_type": "tool_task",
            "task_card": {
                "status": status,
                "progress": int(job.get("progress") or 0),
                "current_step": current_step,
                "phase": phase,
                "elapsed_ms": elapsed_ms,
                "heartbeat_at": heartbeat_at,
                "started_at": started_at,
                "timeout_reason": timeout_reason,
            },
            "status": status,
            "progress": int(job.get("progress") or 0),
            "phase": phase,
            "current_step": current_step,
            "elapsed_ms": elapsed_ms,
            "heartbeat_at": heartbeat_at,
            "started_at": started_at,
            "timeout_reason": timeout_reason,
        }
        self.events.append(
            user_id=str(job.get("user_id") or ""),
            session_id=str(job.get("session_id") or ""),
            task_id=str(context.get("chat_task_id") or job.get("job_id") or ""),
            job_id=str(job.get("job_id") or ""),
            kind=kind,
            status=status,
            progress=int(job.get("progress") or 0),
            phase=phase,
            current_step=current_step,
            heartbeat_at=heartbeat_at,
            started_at=started_at,
            elapsed_ms=elapsed_ms,
            timeout_reason=timeout_reason,
            message=message,
            management_view={
                "task_id": str(job.get("job_id") or ""),
                "job_id": str(job.get("job_id") or ""),
                "status": status,
                "progress": int(job.get("progress") or 0),
                "current_step": current_step,
                "phase": phase,
                "updated_at": str(job.get("updated_at") or ""),
                "timeout_reason": timeout_reason,
                "available_actions": ["cancel"] if status in ACTIVE_STATUSES else (["retry"] if status == "failed" else []),
            },
            task_update=task_update,
        )

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_jobs (
                    job_id TEXT PRIMARY KEY,
                    plan_id TEXT,
                    user_id TEXT,
                    session_id TEXT,
                    project_id TEXT,
                    job_type TEXT NOT NULL,
                    idempotency_key TEXT,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    phase TEXT,
                    current_step TEXT,
                    heartbeat_at TEXT,
                    timeout_reason TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    next_retry_at TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    payload_json TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    cancelled_at TEXT,
                    expires_at TEXT
                )
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_durable_jobs_idempotency ON durable_jobs(idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key != ''")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_durable_jobs_session ON durable_jobs(user_id, session_id)")
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(durable_jobs)").fetchall()}
            for name, definition in {
                "phase": "TEXT",
                "current_step": "TEXT",
                "heartbeat_at": "TEXT",
                "timeout_reason": "TEXT",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE durable_jobs ADD COLUMN {name} {definition}")

    def _row_to_job(self, row: dict[str, Any]) -> dict[str, Any]:
        job = dict(row)
        job["payload"] = _loads(job.pop("payload_json", ""))
        job["result"] = _loads(job.pop("result_json", ""))
        job["schema_version"] = DURABLE_JOB_SCHEMA_VERSION
        job["tool_result"] = self.to_tool_result(job)
        return job

    def submit_job(
        self,
        *,
        plan_id: str = "",
        user_id: str = "",
        session_id: str = "",
        project_id: str = "",
        job_type: str,
        idempotency_key: str = "",
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        expires_in_hours: int = 24,
    ) -> dict[str, Any]:
        clean_key = str(idempotency_key or "").strip()
        if clean_key:
            existing = self._fetch_one("SELECT * FROM durable_jobs WHERE idempotency_key=?", [clean_key])
            if existing:
                return self._row_to_job(existing)
        ts = _now()
        job_id = f"durable_{uuid4().hex[:12]}"
        data = {
            "job_id": job_id,
            "plan_id": plan_id,
            "user_id": user_id,
            "session_id": session_id,
            "project_id": project_id,
            "job_type": job_type,
            "idempotency_key": clean_key,
            "status": "queued",
            "progress": 0,
            "phase": "queued",
            "current_step": "任务已进入后台队列",
            "heartbeat_at": ts,
            "timeout_reason": "",
            "attempt_count": 0,
            "max_attempts": max(1, int(max_attempts or 1)),
            "next_retry_at": "",
            "error_code": "",
            "error_message": "",
            "payload_json": _json(payload or {}),
            "result_json": "",
            "created_at": ts,
            "updated_at": ts,
            "started_at": "",
            "finished_at": "",
            "cancelled_at": "",
            "expires_at": (datetime.now() + timedelta(hours=max(1, int(expires_in_hours or 1)))).isoformat(timespec="seconds"),
        }
        with self._connect() as conn:
            keys = list(data.keys())
            conn.execute(
                f"INSERT INTO durable_jobs ({', '.join(keys)}) VALUES ({', '.join(['?'] * len(keys))})",
                [data[key] for key in keys],
            )
        job = self.get_job(job_id)
        self._publish_job_event(job)
        return job

    def _fetch_one(self, sql: str, params: list[Any]) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _fetch_all(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self._fetch_one("SELECT * FROM durable_jobs WHERE job_id=?", [str(job_id or "")])
        if not row:
            raise FileNotFoundError(f"durable job not found: {job_id}")
        return self._row_to_job(row)

    def list_jobs(
        self,
        *,
        user_id: str = "",
        session_id: str = "",
        statuses: list[str] | None = None,
        job_type: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id:
            clauses.append("user_id=?")
            params.append(str(user_id))
        if session_id:
            clauses.append("session_id=?")
            params.append(str(session_id))
        if job_type:
            clauses.append("job_type=?")
            params.append(str(job_type))
        clean_statuses = [str(item).strip() for item in (statuses or []) if str(item).strip()]
        if clean_statuses:
            clauses.append(f"status IN ({', '.join(['?'] * len(clean_statuses))})")
            params.extend(clean_statuses)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._fetch_all(
            f"SELECT * FROM durable_jobs {where} ORDER BY created_at ASC LIMIT ?",
            [*params, max(1, int(limit or 1))],
        )
        return [self._row_to_job(row) for row in rows]

    def next_queued_job(self, *, job_type: str = "") -> dict[str, Any] | None:
        clauses = ["status='queued'"]
        params: list[Any] = []
        if job_type:
            clauses.append("job_type=?")
            params.append(str(job_type))
        row = self._fetch_one(
            f"SELECT * FROM durable_jobs WHERE {' AND '.join(clauses)} ORDER BY created_at ASC LIMIT 1",
            params,
        )
        return self._row_to_job(row) if row else None

    def count_active_jobs(self, *, user_id: str = "", session_id: str = "", job_type: str = "") -> int:
        clauses = ["status IN ('queued','running')"]
        params: list[Any] = []
        if user_id:
            clauses.append("user_id=?")
            params.append(str(user_id))
        if session_id:
            clauses.append("session_id=?")
            params.append(str(session_id))
        if job_type:
            clauses.append("job_type=?")
            params.append(str(job_type))
        row = self._fetch_one(f"SELECT COUNT(*) AS count FROM durable_jobs WHERE {' AND '.join(clauses)}", params)
        return int((row or {}).get("count") or 0)

    def update_status(
        self,
        job_id: str,
        status: str,
        *,
        progress: int | None = None,
        error_code: str = "",
        error_message: str = "",
        phase: str = "",
        current_step: str = "",
        timeout_reason: str = "",
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = str(status or "").strip().lower()
        if normalized not in JOB_STATUSES:
            raise ValueError(f"unsupported durable job status: {status}")
        update: dict[str, Any] = {"status": normalized, "updated_at": _now()}
        if progress is not None:
            update["progress"] = max(0, min(100, int(progress)))
        update["heartbeat_at"] = _now()
        if phase:
            update["phase"] = str(phase or "")[:120]
        else:
            update["phase"] = normalized
        if current_step:
            update["current_step"] = str(current_step or "")[:240]
        elif normalized in {"queued", "running"}:
            update["current_step"] = str(self.get_job(job_id).get("current_step") or "")
        if timeout_reason:
            update["timeout_reason"] = str(timeout_reason or "")[:500]
        if normalized == "running":
            current = self.get_job(job_id)
            update["started_at"] = str(current.get("started_at") or _now())
        if normalized in TERMINAL_STATUSES:
            update["finished_at"] = _now()
        if error_code:
            update["error_code"] = error_code
        if error_message:
            update["error_message"] = error_message
        if result is not None:
            update["result_json"] = _json(result)
        self._update(job_id, update)
        job = self.get_job(job_id)
        self._publish_job_event(job)
        return job

    def _update(self, job_id: str, fields: dict[str, Any]) -> None:
        keys = list(fields.keys())
        with self._connect() as conn:
            conn.execute(
                f"UPDATE durable_jobs SET {', '.join([key + '=?' for key in keys])} WHERE job_id=?",
                [fields[key] for key in keys] + [job_id],
            )

    def cancel_job(self, job_id: str, *, user_id: str = "", reason: str = "") -> dict[str, Any]:
        job = self.get_job(job_id)
        if user_id and str(job.get("user_id") or "") != str(user_id):
            raise PermissionError("durable job belongs to another user")
        if job.get("status") in TERMINAL_STATUSES:
            return job
        self._update(
            job_id,
            {
                "status": "cancelled",
                "progress": 100,
                "error_code": "JOB_CANCELLED",
                "error_message": reason or "Job was cancelled.",
                "cancelled_at": _now(),
                "finished_at": _now(),
                "updated_at": _now(),
            },
        )
        updated = self.get_job(job_id)
        self._publish_job_event(updated)
        return updated

    def schedule_retry(self, job_id: str, *, error_code: str, error_message: str = "", base_delay_seconds: int = 30) -> dict[str, Any]:
        job = self.get_job(job_id)
        attempts = int(job.get("attempt_count") or 0) + 1
        if attempts >= int(job.get("max_attempts") or 1):
            return self.update_status(job_id, "failed", progress=100, error_code=error_code, error_message=error_message)
        delay = max(1, int(base_delay_seconds)) * (2 ** max(0, attempts - 1))
        self._update(
            job_id,
            {
                "status": "awaiting_confirmation",
                "attempt_count": attempts,
                "next_retry_at": (datetime.now() + timedelta(seconds=delay)).isoformat(timespec="seconds"),
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": _now(),
            },
        )
        updated = self.get_job(job_id)
        self._publish_job_event(updated)
        return updated

    def recover_interrupted_jobs(self) -> dict[str, Any]:
        rows = self._fetch_all("SELECT * FROM durable_jobs WHERE status IN ('queued','running')", [])
        recovered: list[str] = []
        for row in rows:
            self._update(
                row["job_id"],
                {
                    "status": "awaiting_confirmation",
                    "error_code": "JOB_RECOVERED_AFTER_RESTART",
                    "error_message": "Service restarted before the job completed. Please retry or confirm continuation.",
                    "updated_at": _now(),
                },
            )
            recovered.append(row["job_id"])
            self._publish_job_event(self.get_job(row["job_id"]))
        return {"count": len(recovered), "job_ids": recovered}

    def cancel_session_jobs(self, user_id: str, session_id: str, *, reason: str = "Session deleted.") -> list[str]:
        rows = self._fetch_all(
            "SELECT * FROM durable_jobs WHERE user_id=? AND session_id=? AND status NOT IN ('succeeded','failed','cancelled','expired')",
            [str(user_id or ""), str(session_id or "")],
        )
        cancelled: list[str] = []
        for row in rows:
            self.cancel_job(row["job_id"], user_id=user_id, reason=reason)
            cancelled.append(row["job_id"])
        return cancelled

    def hard_delete_session_jobs(self, user_id: str, session_id: str) -> list[str]:
        clean_user = str(user_id or "").strip()
        clean_session = str(session_id or "").strip()
        if not clean_session:
            return []
        params: list[Any] = [clean_session]
        where = "session_id=?"
        if clean_user:
            where += " AND user_id=?"
            params.append(clean_user)
        rows = self._fetch_all(f"SELECT job_id FROM durable_jobs WHERE {where}", params)
        deleted = [str(row.get("job_id") or "") for row in rows if row.get("job_id")]
        with self._connect() as conn:
            conn.execute(f"DELETE FROM durable_jobs WHERE {where}", params)
        self.events.delete_session_events(user_id=clean_user, session_id=clean_session)
        self._remove_checkpoint_files(clean_session)
        return deleted

    def _remove_checkpoint_files(self, session_id: str) -> list[str]:
        clean = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(session_id or "")).strip("._")
        if not clean:
            return []
        removed: list[str] = []
        for folder_name in ("durable_checkpoints", "task_checkpoints", "job_logs"):
            root = self.db_path.parent / folder_name
            if not root.exists():
                continue
            for path in sorted(root.rglob(f"*{clean}*"), reverse=True):
                try:
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        for child in sorted(path.rglob("*"), reverse=True):
                            if child.is_file():
                                child.unlink()
                            elif child.is_dir():
                                child.rmdir()
                        path.rmdir()
                    removed.append(str(path))
                except Exception:
                    continue
        return removed

    def to_tool_result(self, job: dict[str, Any]) -> dict[str, Any]:
        status = str(job.get("status") or "")
        payload = {
            "tool_name": str(job.get("job_type") or "durable_job"),
            "status": _tool_status(status),
            "success": status == "succeeded",
            "outputs": {
                "job_id": job.get("job_id"),
                "durable_status": status,
                "progress": job.get("progress"),
                "result": job.get("result") if isinstance(job.get("result"), dict) else {},
            },
            "diagnostics": {
                "plan_id": job.get("plan_id"),
                "attempt_count": job.get("attempt_count"),
                "max_attempts": job.get("max_attempts"),
                "next_retry_at": job.get("next_retry_at"),
            },
            "error_code": _error_code(status, str(job.get("error_code") or "")),
            "error_title": "Job cancelled" if status == "cancelled" else "",
            "user_message": str(job.get("error_message") or ""),
            "execution_id": job.get("job_id"),
            "plan_id": job.get("plan_id"),
            "started_at": job.get("started_at") or job.get("created_at") or "",
            "finished_at": job.get("finished_at") or "",
        }
        return normalize_tool_result(payload, tool_name=str(job.get("job_type") or "durable_job"))
