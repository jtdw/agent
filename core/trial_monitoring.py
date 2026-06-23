from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from core.compat_usage import normalize_actor_type


TRIAL_MONITORING_SCHEMA_VERSION = "trial-monitoring/v1"
TRACKED_METRICS = {
    "planner_success",
    "planner_clarification",
    "validator_blocked",
    "tool_succeeded",
    "tool_failed",
    "download_failed",
    "worker_cancelled",
    "worker_recovered",
    "artifact_registration_failed",
    "compat_layer_used",
}
ALERT_REASON_CODES = {
    "CROSS_SESSION_ACCESS": "P0",
    "WRONG_DOWNLOAD_AREA": "P0",
    "PLANNER_BYPASS": "P0",
    "FAKE_ARTIFACT": "P0",
    "PERMISSION_ERROR": "P1",
    "CANCELLED_TASK_WROTE_OUTPUT": "P0",
}
SENSITIVE_KEYS = {"token", "cookie", "authorization", "storage_state", "user_id", "session_id", "path", "prompt"}
PATH_RE = re.compile(r"[A-Za-z]:\\[^\s,'\"}]+|/(?:workspace|tmp|var|home|users)/[^\s,'\"}]+", re.IGNORECASE)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS:
                cleaned[key_text] = "[redacted]"
            else:
                cleaned[key_text] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:20]]
    if isinstance(value, str):
        return PATH_RE.sub("[redacted_path]", value)[:500]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:300]


class TrialMonitoringStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
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
                CREATE TABLE IF NOT EXISTS trial_metric_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '',
                    reason_code TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT '',
                    actor_type TEXT NOT NULL DEFAULT 'trial_user',
                    source TEXT NOT NULL DEFAULT '',
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trial_monitoring_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO trial_monitoring_meta(key, value) VALUES('schema_version', ?)",
                (TRIAL_MONITORING_SCHEMA_VERSION,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO trial_monitoring_meta(key, value) VALUES('observation_started_at', ?)",
                (_now(),),
            )

    def record_metric(
        self,
        metric_name: str,
        *,
        status: str = "",
        reason_code: str = "",
        actor_type: str = "",
        severity: str = "",
        source: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        name = str(metric_name or "").strip()
        if name not in TRACKED_METRICS:
            return
        code = str(reason_code or "").strip().upper()
        clean_severity = str(severity or ALERT_REASON_CODES.get(code, "")).strip().upper()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trial_metric_events(metric_name, status, reason_code, severity, actor_type, source, detail_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    str(status or "")[:80],
                    code[:120],
                    clean_severity[:20],
                    normalize_actor_type(actor_type),
                    str(source or "")[:200],
                    json.dumps(_sanitize(detail or {}), ensure_ascii=False, sort_keys=True),
                    _now(),
                ),
            )

    def report(self, *, exclude_actor_types: set[str] | None = None) -> dict[str, Any]:
        excluded = {str(item).strip().lower() for item in (exclude_actor_types or set()) if str(item).strip()}
        with self._connect() as conn:
            meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM trial_monitoring_meta")}
            if excluded:
                placeholders = ",".join("?" for _ in excluded)
                rows = conn.execute(
                    f"SELECT metric_name, COUNT(*) AS count FROM trial_metric_events WHERE actor_type NOT IN ({placeholders}) GROUP BY metric_name",
                    tuple(excluded),
                ).fetchall()
                alert_rows = conn.execute(
                    f"SELECT severity, COUNT(*) AS count FROM trial_metric_events WHERE actor_type NOT IN ({placeholders}) AND severity != '' GROUP BY severity",
                    tuple(excluded),
                ).fetchall()
            else:
                rows = conn.execute("SELECT metric_name, COUNT(*) AS count FROM trial_metric_events GROUP BY metric_name").fetchall()
                alert_rows = conn.execute("SELECT severity, COUNT(*) AS count FROM trial_metric_events WHERE severity != '' GROUP BY severity").fetchall()
        return {
            "schema_version": TRIAL_MONITORING_SCHEMA_VERSION,
            "observation_started_at": meta.get("observation_started_at", ""),
            "generated_at": _now(),
            "excluded_actor_types": sorted(excluded),
            "metrics": {row["metric_name"]: {"count": int(row["count"] or 0)} for row in rows},
            "alerts": {row["severity"]: int(row["count"] or 0) for row in alert_rows},
        }
