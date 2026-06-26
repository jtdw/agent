from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


WORKFLOW_CACHE_SCHEMA_VERSION = "workflow-cache/v1"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def _key(*, user_id: str, session_id: str, namespace: str, key_parts: dict[str, Any]) -> str:
    raw = _json(
        {
            "user_id": str(user_id or ""),
            "session_id": str(session_id or ""),
            "namespace": str(namespace or ""),
            "key_parts": key_parts,
        }
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class WorkflowCache:
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
                CREATE TABLE IF NOT EXISTS workflow_cache (
                    cache_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    key_parts_json TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_cache_scope ON workflow_cache(user_id, session_id, namespace)")

    def set(
        self,
        *,
        user_id: str,
        session_id: str,
        namespace: str,
        key_parts: dict[str, Any],
        value: dict[str, Any],
        ttl_seconds: int,
    ) -> dict[str, Any]:
        now = time.time()
        cache_key = _key(user_id=user_id, session_id=session_id, namespace=namespace, key_parts=key_parts)
        record = {
            "cache_key": cache_key,
            "user_id": str(user_id or ""),
            "session_id": str(session_id or ""),
            "namespace": str(namespace or ""),
            "key_parts_json": _json(key_parts),
            "value_json": _json(value),
            "created_at": now,
            "expires_at": now + max(1, int(ttl_seconds or 1)),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_cache (cache_key, user_id, session_id, namespace, key_parts_json, value_json, created_at, expires_at)
                VALUES (:cache_key, :user_id, :session_id, :namespace, :key_parts_json, :value_json, :created_at, :expires_at)
                ON CONFLICT(cache_key) DO UPDATE SET
                    user_id=excluded.user_id,
                    session_id=excluded.session_id,
                    namespace=excluded.namespace,
                    key_parts_json=excluded.key_parts_json,
                    value_json=excluded.value_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
                """,
                record,
            )
        return {"schema_version": WORKFLOW_CACHE_SCHEMA_VERSION, "cache_key": cache_key, "expires_at": record["expires_at"]}

    def get(self, *, user_id: str, session_id: str, namespace: str, key_parts: dict[str, Any]) -> dict[str, Any] | None:
        cache_key = _key(user_id=user_id, session_id=session_id, namespace=namespace, key_parts=key_parts)
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM workflow_cache
                WHERE cache_key=? AND user_id=? AND session_id=? AND namespace=?
                """,
                [cache_key, str(user_id or ""), str(session_id or ""), str(namespace or "")],
            ).fetchone()
            if row and float(row["expires_at"] or 0) <= now:
                conn.execute("DELETE FROM workflow_cache WHERE cache_key=?", [cache_key])
                return None
        if not row:
            return None
        try:
            value = json.loads(str(row["value_json"] or "{}"))
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def prune_expired(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM workflow_cache WHERE expires_at<=?", [time.time()])
        return int(cursor.rowcount or 0)
