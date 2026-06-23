from __future__ import annotations

import json
import queue
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


TASK_PROGRESS_EVENT_SCHEMA_VERSION = "task-progress-event/v1"
EVENT_KINDS = {"task_status", "task_progress", "task_result", "model_token", "model_complete", "warning", "error"}
TASK_EVENT_STATUSES = {"planning", "awaiting_confirmation", "queued", "running", "waiting_login", "paused", "succeeded", "failed", "cancelled"}
_TRANSIENT_LOCK = Lock()
_TRANSIENT_VERSION = 1_000_000_000


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class TaskProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["task-progress-event/v1"] = TASK_PROGRESS_EVENT_SCHEMA_VERSION
    event_id: str
    version: int
    kind: Literal["task_status", "task_progress", "task_result", "model_token", "model_complete", "warning", "error"]
    task_id: str = ""
    job_id: str = ""
    message_id: str = ""
    status: str = ""
    progress: int | None = None
    current_step: str = ""
    message: str = ""
    delta: str = ""
    management_view: dict[str, Any] = Field(default_factory=dict)
    presentation_result: dict[str, Any] = Field(default_factory=dict)
    task_update: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class RealtimeEventHub:
    """In-memory, scoped fan-out for transient model-token events.

    Token chunks intentionally do not enter the persistent job event journal.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: dict[tuple[str, str], set[Any]] = {}

    def subscribe(self, *, user_id: str, session_id: str) -> queue.Queue[dict[str, Any]]:
        channel: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=512)
        key = (str(user_id or ""), str(session_id or ""))
        with self._lock:
            self._subscribers.setdefault(key, set()).add(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            for key in list(self._subscribers):
                subscribers = self._subscribers[key]
                subscribers.discard(channel)
                if not subscribers:
                    self._subscribers.pop(key, None)

    def publish(
        self,
        *,
        user_id: str,
        session_id: str,
        kind: str,
        task_id: str = "",
        message_id: str = "",
        status: str = "",
        message: str = "",
        delta: str = "",
        management_view: dict[str, Any] | None = None,
        presentation_result: dict[str, Any] | None = None,
        task_update: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        global _TRANSIENT_VERSION
        if str(kind or "") not in EVENT_KINDS:
            raise ValueError(f"unsupported transient event kind: {kind}")
        with _TRANSIENT_LOCK:
            _TRANSIENT_VERSION += 1
            version = _TRANSIENT_VERSION
        event = TaskProgressEvent(
            event_id=f"evt_stream_{uuid4().hex}",
            version=version,
            kind=str(kind),
            task_id=str(task_id or ""),
            message_id=str(message_id or ""),
            status=str(status or ""),
            message=str(message or "")[:1200],
            delta=str(delta or "")[:2000],
            management_view=_as_dict(management_view),
            presentation_result=_as_dict(presentation_result),
            task_update=_as_dict(task_update),
            created_at=_now(),
        ).model_dump(mode="json")
        key = (str(user_id or ""), str(session_id or ""))
        with self._lock:
            subscribers = list(self._subscribers.get(key, set()))
        for channel in subscribers:
            try:
                channel.put_nowait(event)
            except queue.Full:
                continue
        return event

    def publish_model_token(self, *, user_id: str, session_id: str, task_id: str, delta: str, message_id: str = "") -> dict[str, Any]:
        return self.publish(
            user_id=user_id,
            session_id=session_id,
            kind="model_token",
            task_id=task_id,
            message_id=message_id,
            delta=delta,
        )


GLOBAL_REALTIME_EVENT_HUB = RealtimeEventHub()


class TaskEventStore:
    """Bounded, user/session-scoped event journal backed by the durable-job SQLite DB."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

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
                CREATE TABLE IF NOT EXISTS task_progress_events (
                    version INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    job_id TEXT,
                    message_id TEXT,
                    kind TEXT NOT NULL,
                    status TEXT,
                    progress INTEGER,
                    current_step TEXT,
                    message TEXT,
                    delta TEXT,
                    management_view_json TEXT,
                    presentation_result_json TEXT,
                    task_update_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_progress_events_scope ON task_progress_events(user_id, session_id, version)")
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(task_progress_events)").fetchall()}
            if "task_update_json" not in columns:
                conn.execute("ALTER TABLE task_progress_events ADD COLUMN task_update_json TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_event_checkpoints (
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    checkpoint_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    PRIMARY KEY (user_id, session_id, checkpoint_key)
                )
                """
            )

    def append(
        self,
        *,
        user_id: str,
        session_id: str,
        kind: str,
        task_id: str = "",
        job_id: str = "",
        message_id: str = "",
        status: str = "",
        progress: int | None = None,
        current_step: str = "",
        message: str = "",
        delta: str = "",
        management_view: dict[str, Any] | None = None,
        presentation_result: dict[str, Any] | None = None,
        task_update: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_kind = str(kind or "").strip()
        if clean_kind not in EVENT_KINDS:
            raise ValueError(f"unsupported task event kind: {kind}")
        clean_status = str(status or "").strip()
        if clean_status and clean_status not in TASK_EVENT_STATUSES:
            raise ValueError(f"unsupported task event status: {status}")
        value = None if progress is None else max(0, min(100, int(progress)))
        record = {
            "event_id": f"evt_{uuid4().hex}",
            "user_id": str(user_id or ""),
            "session_id": str(session_id or ""),
            "task_id": str(task_id or ""),
            "job_id": str(job_id or ""),
            "message_id": str(message_id or ""),
            "kind": clean_kind,
            "status": clean_status,
            "progress": value,
            "current_step": str(current_step or "")[:240],
            "message": str(message or "")[:1200],
            "delta": str(delta or "")[:2000],
            "management_view_json": json.dumps(_as_dict(management_view), ensure_ascii=False),
            "presentation_result_json": json.dumps(_as_dict(presentation_result), ensure_ascii=False),
            "task_update_json": json.dumps(_as_dict(task_update), ensure_ascii=False),
            "created_at": _now(),
        }
        with self._connect() as conn:
            columns = list(record)
            cursor = conn.execute(
                f"INSERT INTO task_progress_events ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})",
                [record[column] for column in columns],
            )
            record["version"] = int(cursor.lastrowid)
        return self._row_to_event(record, include_scope=True)

    def _row_to_event(self, row: dict[str, Any], *, include_scope: bool) -> dict[str, Any]:
        event = {
            "schema_version": TASK_PROGRESS_EVENT_SCHEMA_VERSION,
            "event_id": str(row.get("event_id") or ""),
            "version": int(row.get("version") or 0),
            "kind": str(row.get("kind") or "task_status"),
            "task_id": str(row.get("task_id") or ""),
            "job_id": str(row.get("job_id") or ""),
            "message_id": str(row.get("message_id") or ""),
            "status": str(row.get("status") or ""),
            "progress": row.get("progress"),
            "current_step": str(row.get("current_step") or ""),
            "message": str(row.get("message") or ""),
            "delta": str(row.get("delta") or ""),
            "management_view": _loads(row.get("management_view_json")),
            "presentation_result": _loads(row.get("presentation_result_json")),
            "task_update": _loads(row.get("task_update_json")),
            "created_at": str(row.get("created_at") or ""),
        }
        TaskProgressEvent.model_validate(event)
        if include_scope:
            event["user_id"] = str(row.get("user_id") or "")
            event["session_id"] = str(row.get("session_id") or "")
        return event

    def append_if_changed(self, *, checkpoint_key: str, fingerprint: str, **event: Any) -> dict[str, Any] | None:
        user_id = str(event.get("user_id") or "")
        session_id = str(event.get("session_id") or "")
        key = str(checkpoint_key or "")
        if not key:
            raise ValueError("checkpoint_key is required")
        with self._connect() as conn:
            current = conn.execute(
                "SELECT fingerprint FROM task_event_checkpoints WHERE user_id=? AND session_id=? AND checkpoint_key=?",
                [user_id, session_id, key],
            ).fetchone()
            if current and str(current[0]) == str(fingerprint):
                return None
        created = self.append(**event)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO task_event_checkpoints (user_id, session_id, checkpoint_key, fingerprint) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id, session_id, checkpoint_key) DO UPDATE SET fingerprint=excluded.fingerprint",
                [user_id, session_id, key, str(fingerprint)],
            )
        return created

    def list_events(self, *, user_id: str, session_id: str, after_version: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_progress_events
                WHERE user_id=? AND session_id=? AND version>?
                ORDER BY version ASC LIMIT ?
                """,
                [str(user_id or ""), str(session_id or ""), max(0, int(after_version or 0)), max(1, min(1000, int(limit or 200)))],
            ).fetchall()
        return [self._row_to_event(dict(row), include_scope=True) for row in rows]

    def public_events(self, *, user_id: str, session_id: str, after_version: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        events = self.list_events(user_id=user_id, session_id=session_id, after_version=after_version, limit=limit)
        return [{key: value for key, value in event.items() if key not in {"user_id", "session_id"}} for event in events]

    def delete_session_events(self, *, user_id: str, session_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM task_progress_events WHERE user_id=? AND session_id=?",
                [str(user_id or ""), str(session_id or "")],
            )
            conn.execute(
                "DELETE FROM task_event_checkpoints WHERE user_id=? AND session_id=?",
                [str(user_id or ""), str(session_id or "")],
            )
        return int(cursor.rowcount or 0)
