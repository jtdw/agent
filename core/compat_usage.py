from __future__ import annotations

import sqlite3
from datetime import datetime
import os
from pathlib import Path
from typing import Any


COMPAT_USAGE_SCHEMA_VERSION = "compat-usage/v1"
TRACKED_COMPAT_FIELDS = {
    "user_facing_result_fallback_used",
    "deprecated_raw_job_api_used",
    "legacy_download_url_used",
    "prevalidated_executor_used",
    "include_raw",
    "legacy_api_used",
    "direct_command_legacy_api_used",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_db_path() -> Path:
    return Path.cwd() / "workspace" / "compat_usage.db"


def normalize_actor_type(value: str = "", *, caller: str = "") -> str:
    explicit = str(value or "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("PYTEST_CURRENT_TEST"):
        return "automated_test"
    lowered = str(caller or "").lower()
    if "testclient" in lowered or "pytest" in lowered or "playwright" in lowered:
        return "automated_test"
    return "trial_user"


class CompatibilityUsageStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compat_usage_counters (
                    field TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0,
                    first_used_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    last_source TEXT NOT NULL DEFAULT '',
                    last_caller TEXT NOT NULL DEFAULT '',
                    last_request_id TEXT NOT NULL DEFAULT '',
                    actor_type TEXT NOT NULL DEFAULT 'trial_user'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compat_usage_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    field TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    caller TEXT NOT NULL DEFAULT '',
                    request_id TEXT NOT NULL DEFAULT '',
                    actor_type TEXT NOT NULL DEFAULT 'trial_user',
                    used_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compat_usage_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            now = _now()
            conn.execute(
                "INSERT OR IGNORE INTO compat_usage_meta(key, value) VALUES('schema_version', ?)",
                (COMPAT_USAGE_SCHEMA_VERSION,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO compat_usage_meta(key, value) VALUES('observation_started_at', ?)",
                (now,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO compat_usage_meta(key, value) VALUES('effective_request_count', '0')"
            )
            for table in ("compat_usage_counters", "compat_usage_events"):
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if "actor_type" not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN actor_type TEXT NOT NULL DEFAULT 'trial_user'")

    def record(self, field: str, *, source: str = "", caller: str = "", request_id: str = "", actor_type: str = "") -> None:
        clean_field = str(field or "").strip()
        if clean_field not in TRACKED_COMPAT_FIELDS:
            return
        now = _now()
        clean_actor_type = normalize_actor_type(actor_type, caller=caller)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO compat_usage_counters(field, count, first_used_at, last_used_at, last_source, last_caller, last_request_id, actor_type)
                VALUES(?, 1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(field) DO UPDATE SET
                    count = count + 1,
                    last_used_at = excluded.last_used_at,
                    last_source = excluded.last_source,
                    last_caller = excluded.last_caller,
                    last_request_id = excluded.last_request_id,
                    actor_type = excluded.actor_type
                """,
                (clean_field, now, now, str(source or "")[:300], str(caller or "")[:200], str(request_id or "")[:120], clean_actor_type),
            )
            conn.execute(
                "INSERT INTO compat_usage_events(field, source, caller, request_id, actor_type, used_at) VALUES(?, ?, ?, ?, ?, ?)",
                (clean_field, str(source or "")[:300], str(caller or "")[:200], str(request_id or "")[:120], clean_actor_type, now),
            )

    def record_effective_request(self, *, source: str = "", actor_type: str = "") -> None:
        clean_actor_type = normalize_actor_type(actor_type)
        with self._connect() as conn:
            current = conn.execute(
                "SELECT value FROM compat_usage_meta WHERE key='effective_request_count'"
            ).fetchone()
            value = int(current["value"] if current else "0") + 1
            conn.execute(
                "INSERT OR REPLACE INTO compat_usage_meta(key, value) VALUES('effective_request_count', ?)",
                (str(value),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO compat_usage_meta(key, value) VALUES('last_effective_request_source', ?)",
                (str(source or "")[:300],),
            )
            current_actor = conn.execute(
                "SELECT value FROM compat_usage_meta WHERE key=?",
                (f"effective_request_count:{clean_actor_type}",),
            ).fetchone()
            actor_value = int(current_actor["value"] if current_actor else "0") + 1
            conn.execute(
                "INSERT OR REPLACE INTO compat_usage_meta(key, value) VALUES(?, ?)",
                (f"effective_request_count:{clean_actor_type}", str(actor_value)),
            )

    def report(self, *, exclude_actor_types: set[str] | None = None) -> dict[str, Any]:
        excluded = {str(item).strip().lower() for item in (exclude_actor_types or set()) if str(item).strip()}
        with self._connect() as conn:
            meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM compat_usage_meta")}
            if excluded:
                placeholders = ",".join("?" for _ in excluded)
                rows = conn.execute(
                    f"""
                    SELECT
                        field,
                        COUNT(*) AS count,
                        MIN(used_at) AS first_used_at,
                        MAX(used_at) AS last_used_at
                    FROM compat_usage_events
                    WHERE actor_type NOT IN ({placeholders})
                    GROUP BY field
                    ORDER BY field
                    """,
                    tuple(excluded),
                ).fetchall()
                latest_rows = {
                    row["field"]: row
                    for row in conn.execute(
                        f"""
                        SELECT e.*
                        FROM compat_usage_events e
                        JOIN (
                            SELECT field, MAX(used_at) AS last_used_at
                            FROM compat_usage_events
                            WHERE actor_type NOT IN ({placeholders})
                            GROUP BY field
                        ) latest ON latest.field = e.field AND latest.last_used_at = e.used_at
                        """,
                        tuple(excluded),
                    ).fetchall()
                }
            else:
                rows = conn.execute("SELECT * FROM compat_usage_counters ORDER BY field").fetchall()
                latest_rows = {row["field"]: row for row in rows}
        counters = {
            field: {
                "count": 0,
                "first_used_at": "",
                "last_used_at": "",
                "last_source": "",
                "last_caller": "",
                "last_request_id": "",
                "actor_type": "",
            }
            for field in sorted(TRACKED_COMPAT_FIELDS)
        }
        for row in rows:
            latest = latest_rows.get(row["field"], row)
            counters[row["field"]] = {
                "count": int(row["count"] or 0),
                "first_used_at": row["first_used_at"],
                "last_used_at": row["last_used_at"],
                "last_source": latest["source"] if "source" in latest.keys() else latest["last_source"],
                "last_caller": latest["caller"] if "caller" in latest.keys() else latest["last_caller"],
                "last_request_id": latest["request_id"] if "request_id" in latest.keys() else latest["last_request_id"],
                "actor_type": latest["actor_type"],
            }
        effective_count = int(meta.get("effective_request_count") or 0)
        if excluded:
            effective_count = sum(
                int(value or 0)
                for key, value in meta.items()
                if key.startswith("effective_request_count:") and key.split(":", 1)[1] not in excluded
            )
        return {
            "schema_version": COMPAT_USAGE_SCHEMA_VERSION,
            "observation_started_at": meta.get("observation_started_at", ""),
            "generated_at": _now(),
            "effective_request_count": effective_count,
            "last_effective_request_source": meta.get("last_effective_request_source", ""),
            "excluded_actor_types": sorted(excluded),
            "counters": counters,
        }


def record_compat_usage_from_payload(payload: dict[str, Any], *, source: str = "", caller: str = "", request_id: str = "", actor_type: str = "", db_path: Path | None = None) -> None:
    store = CompatibilityUsageStore(db_path)
    for field in TRACKED_COMPAT_FIELDS:
        if bool(payload.get(field)):
            store.record(field, source=source, caller=caller, request_id=request_id, actor_type=actor_type)
