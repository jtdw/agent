from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS commercial_users (
    user_id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',
    plan_expires_at TEXT,
    password_hash TEXT NOT NULL DEFAULT '',
    last_login_at TEXT,
    login_failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    own_daily_quota INTEGER NOT NULL DEFAULT 3,
    platform_monthly_quota INTEGER NOT NULL DEFAULT 0,
    platform_monthly_used INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_credentials (
    credential_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    credential_type TEXT NOT NULL DEFAULT 'username_password',
    encrypted_username TEXT,
    encrypted_password TEXT,
    storage_state_path TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, source_key, credential_type),
    FOREIGN KEY(user_id) REFERENCES commercial_users(user_id)
);

CREATE TABLE IF NOT EXISTS platform_accounts (
    account_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    label TEXT NOT NULL,
    encrypted_username TEXT,
    encrypted_password TEXT,
    storage_state_path TEXT,
    daily_limit INTEGER NOT NULL DEFAULT 50,
    used_today INTEGER NOT NULL DEFAULT 0,
    monthly_limit INTEGER NOT NULL DEFAULT 1000,
    used_month INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS download_jobs (
    job_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    chat_session_id TEXT NOT NULL DEFAULT '',
    source_key TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    region TEXT,
    start_date TEXT,
    end_date TEXT,
    account_mode TEXT NOT NULL,
    account_id TEXT,
    request_text TEXT,
    direct_url TEXT,
    local_file_path TEXT,
    output_name TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT 'queued',
    result_json TEXT,
    failure_diagnostic_json TEXT,
    artifact_quality_json TEXT,
    output_path TEXT,
    zip_path TEXT,
    error_message TEXT,
    charged INTEGER NOT NULL DEFAULT 0,
    quota_reserved INTEGER NOT NULL DEFAULT 0,
    retried_from_job_id TEXT,
    canceled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(user_id) REFERENCES commercial_users(user_id)
);

CREATE TABLE IF NOT EXISTS quota_ledger (
    ledger_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    job_id TEXT,
    change_value INTEGER NOT NULL,
    quota_type TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES commercial_users(user_id)
);

CREATE TABLE IF NOT EXISTS login_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    FOREIGN KEY(user_id) REFERENCES commercial_users(user_id)
);

CREATE TABLE IF NOT EXISTS payment_orders (
    order_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    plan TEXT NOT NULL,
    amount_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CNY',
    platform_quota INTEGER NOT NULL DEFAULT 0,
    days INTEGER NOT NULL DEFAULT 30,
    provider TEXT NOT NULL DEFAULT 'mock',
    status TEXT NOT NULL DEFAULT 'pending',
    external_order_id TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    paid_at TEXT,
    FOREIGN KEY(user_id) REFERENCES commercial_users(user_id)
);

CREATE TABLE IF NOT EXISTS payment_records (
    payment_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'manual',
    amount_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CNY',
    plan TEXT NOT NULL,
    platform_quota INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'paid',
    external_order_id TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES commercial_users(user_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT,
    action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    resource_type TEXT,
    resource_id TEXT,
    ip_address TEXT,
    user_agent TEXT,
    detail_json TEXT,
    created_at TEXT NOT NULL
);
"""


COMMERCIAL_USER_MIGRATIONS = {
    "password_hash": "ALTER TABLE commercial_users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''",
    "last_login_at": "ALTER TABLE commercial_users ADD COLUMN last_login_at TEXT",
    "login_failed_count": "ALTER TABLE commercial_users ADD COLUMN login_failed_count INTEGER NOT NULL DEFAULT 0",
    "locked_until": "ALTER TABLE commercial_users ADD COLUMN locked_until TEXT",
}


DOWNLOAD_JOB_MIGRATIONS = {
    "chat_session_id": "ALTER TABLE download_jobs ADD COLUMN chat_session_id TEXT NOT NULL DEFAULT ''",
    "quota_reserved": "ALTER TABLE download_jobs ADD COLUMN quota_reserved INTEGER NOT NULL DEFAULT 0",
    "retried_from_job_id": "ALTER TABLE download_jobs ADD COLUMN retried_from_job_id TEXT",
    "canceled_at": "ALTER TABLE download_jobs ADD COLUMN canceled_at TEXT",
    "failure_diagnostic_json": "ALTER TABLE download_jobs ADD COLUMN failure_diagnostic_json TEXT",
    "artifact_quality_json": "ALTER TABLE download_jobs ADD COLUMN artifact_quality_json TEXT",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def future_days(days: int) -> str:
    return (datetime.now() + timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")


class CommercialDB:
    def __init__(self, workdir: Path):
        self.workdir = Path(workdir)
        self.db_path = self.workdir / "commercial.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(commercial_users)").fetchall()}
            for col, sql in COMMERCIAL_USER_MIGRATIONS.items():
                if col not in existing_cols:
                    conn.execute(sql)
            job_cols = {row[1] for row in conn.execute("PRAGMA table_info(download_jobs)").fetchall()}
            for col, sql in DOWNLOAD_JOB_MIGRATIONS.items():
                if col not in job_cols:
                    conn.execute(sql)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, tuple(params))

    def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def insert_dict(self, table: str, data: dict[str, Any]) -> None:
        keys = list(data.keys())
        placeholders = ", ".join(["?"] * len(keys))
        cols = ", ".join(keys)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        self.execute(sql, [data[k] for k in keys])

    def update_dict(self, table: str, data: dict[str, Any], where: str, params: Iterable[Any]) -> None:
        keys = list(data.keys())
        sets = ", ".join([f"{k}=?" for k in keys])
        sql = f"UPDATE {table} SET {sets} WHERE {where}"
        self.execute(sql, [data[k] for k in keys] + list(params))


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def json_loads(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text
