from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


class WorkspaceDatabase:
    """Lightweight SQLite workspace database for datasets, chats, and derived results."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dataset_catalog (
                    dataset_name TEXT PRIMARY KEY,
                    data_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sql_table TEXT,
                    row_count INTEGER,
                    auto_synced INTEGER NOT NULL DEFAULT 0,
                    meta_json TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document_store (
                    dataset_name TEXT PRIMARY KEY,
                    title TEXT,
                    path TEXT NOT NULL,
                    text_content TEXT,
                    meta_json TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    pipeline_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_type TEXT,
                    source_value TEXT,
                    output_prefix TEXT,
                    summary_json TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS pipeline_steps (
                    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_order INTEGER NOT NULL,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_summary TEXT,
                    output_summary TEXT,
                    detail_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES pipeline_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS operation_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT,
                    category TEXT NOT NULL DEFAULT 'info'
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    meta_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES conversations(session_id)
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _set_state(self, key: str, value: str) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state (state_key, state_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value,
                    updated_at=excluded.updated_at
                """,
                (key, value, now),
            )

    def _get_state(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT state_value FROM app_state WHERE state_key = ?", (key,)).fetchone()
        return row[0] if row else None

    def safe_table_name(self, name: str, prefix: str = "ds") -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", (name or "dataset").strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_") or "dataset"
        return f"{prefix}_{cleaned.lower()}"

    def _upsert_catalog(
        self,
        dataset_name: str,
        data_type: str,
        path: str,
        sql_table: str | None,
        row_count: int | None,
        auto_synced: bool,
        meta: dict[str, Any] | None,
    ) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dataset_catalog (dataset_name, data_type, path, sql_table, row_count, auto_synced, meta_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_name) DO UPDATE SET
                    data_type=excluded.data_type,
                    path=excluded.path,
                    sql_table=excluded.sql_table,
                    row_count=excluded.row_count,
                    auto_synced=excluded.auto_synced,
                    meta_json=excluded.meta_json,
                    updated_at=excluded.updated_at
                """,
                (
                    dataset_name,
                    data_type,
                    path,
                    sql_table,
                    row_count,
                    1 if auto_synced else 0,
                    json.dumps(meta or {}, ensure_ascii=False),
                    now,
                ),
            )

    def _replace_table(self, sql_table: str, df: pd.DataFrame) -> int:
        clean_df = df.copy()
        for col in clean_df.columns:
            if pd.api.types.is_datetime64_any_dtype(clean_df[col]):
                clean_df[col] = clean_df[col].astype(str)
        with self._connect() as conn:
            clean_df.to_sql(sql_table, conn, if_exists="replace", index=False)
        return int(len(clean_df))

    def drop_dataset(self, dataset_name: str) -> None:
        info = self.dataset_info(dataset_name)
        with self._connect() as conn:
            if info and info.get("sql_table"):
                conn.execute(f'DROP TABLE IF EXISTS "{info["sql_table"]}"')
            conn.execute("DELETE FROM dataset_catalog WHERE dataset_name = ?", (dataset_name,))
            conn.execute("DELETE FROM document_store WHERE dataset_name = ?", (dataset_name,))

    def sync_table(
        self,
        dataset_name: str,
        path: str,
        df: pd.DataFrame,
        meta: dict[str, Any] | None = None,
        auto_synced: bool = True,
    ) -> dict[str, Any]:
        sql_table = self.safe_table_name(dataset_name, prefix="tbl")
        row_count = self._replace_table(sql_table, df)
        self._upsert_catalog(dataset_name, "table", path, sql_table, row_count, auto_synced, meta)
        return {"dataset_name": dataset_name, "sql_table": sql_table, "row_count": row_count, "data_type": "table"}

    def sync_vector(
        self,
        dataset_name: str,
        path: str,
        gdf: Any,
        meta: dict[str, Any] | None = None,
        auto_synced: bool = True,
    ) -> dict[str, Any]:
        df = pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore")).copy()
        if hasattr(gdf, "geometry"):
            try:
                df["geometry_wkt"] = gdf.geometry.apply(lambda geom: geom.wkt if geom is not None else None)
            except Exception:
                pass
            try:
                if getattr(gdf.geometry, "geom_type", None) is not None and not gdf.empty:
                    point_mask = gdf.geometry.geom_type.eq("Point")
                    if bool(point_mask.any()):
                        df.loc[point_mask, "x"] = gdf.loc[point_mask, "geometry"].x
                        df.loc[point_mask, "y"] = gdf.loc[point_mask, "geometry"].y
            except Exception:
                pass
        sql_table = self.safe_table_name(dataset_name, prefix="vec")
        row_count = self._replace_table(sql_table, df)
        self._upsert_catalog(dataset_name, "vector", path, sql_table, row_count, auto_synced, meta)
        return {"dataset_name": dataset_name, "sql_table": sql_table, "row_count": row_count, "data_type": "vector"}

    def sync_document(
        self,
        dataset_name: str,
        path: str,
        text: str,
        meta: dict[str, Any] | None = None,
        auto_synced: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO document_store (dataset_name, title, path, text_content, meta_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_name) DO UPDATE SET
                    title=excluded.title,
                    path=excluded.path,
                    text_content=excluded.text_content,
                    meta_json=excluded.meta_json,
                    updated_at=excluded.updated_at
                """,
                (dataset_name, dataset_name, path, text, json.dumps(meta or {}, ensure_ascii=False), now),
            )
        self._upsert_catalog(dataset_name, "document", path, "document_store", 1, auto_synced, meta)
        return {"dataset_name": dataset_name, "sql_table": "document_store", "row_count": 1, "data_type": "document"}

    def register_raster(
        self,
        dataset_name: str,
        path: str,
        meta: dict[str, Any] | None = None,
        auto_synced: bool = True,
    ) -> dict[str, Any]:
        self._upsert_catalog(dataset_name, "raster", path, None, None, auto_synced, meta)
        return {"dataset_name": dataset_name, "sql_table": None, "row_count": None, "data_type": "raster"}

    def list_catalog(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT dataset_name, data_type, path, sql_table, row_count, auto_synced, updated_at FROM dataset_catalog ORDER BY updated_at DESC, dataset_name"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sql_tables(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                name = row[0]
                count = None
                try:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                except Exception:
                    count = None
                out.append({"name": name, "row_count": count})
        return out

    def dataset_info(self, dataset_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT dataset_name, data_type, path, sql_table, row_count, auto_synced, meta_json, updated_at FROM dataset_catalog WHERE dataset_name = ?",
                (dataset_name,),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["meta"] = json.loads(payload.pop("meta_json") or "{}")
        return payload

    def query(self, sql: str) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn)

    def log_operation(self, title: str, detail: str = "", category: str = "info") -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO operation_logs (created_at, title, detail, category) VALUES (?, ?, ?, ?)",
                (now, title, detail, category),
            )

    def list_operations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT created_at, title, detail, category FROM operation_logs ORDER BY log_id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            {"time": row["created_at"], "title": row["title"], "detail": row["detail"], "category": row["category"]}
            for row in rows
        ]

    def create_conversation(self, session_id: str, title: str) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO conversations (session_id, title, created_at, updated_at) VALUES (?, COALESCE((SELECT title FROM conversations WHERE session_id = ?), ?), COALESCE((SELECT created_at FROM conversations WHERE session_id = ?), ?), ?)",
                (session_id, session_id, title, session_id, now, now),
            )
        self.set_current_conversation_id(session_id)

    def touch_conversation(self, session_id: str) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE session_id = ?", (now, session_id))

    def rename_conversation(self, session_id: str, title: str) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE session_id = ?", (title, now, session_id))

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_current_conversation_id(self) -> str | None:
        return self._get_state("current_conversation_id")

    def set_current_conversation_id(self, session_id: str) -> None:
        self._set_state("current_conversation_id", session_id)
        self.touch_conversation(session_id)

    def add_message(self, session_id: str, role: str, content: str, meta: dict[str, Any] | None = None) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversation_messages (session_id, role, content, meta_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, json.dumps(meta or {}, ensure_ascii=False), now),
            )
        self.touch_conversation(session_id)

    def update_message(self, message_id: int, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT message_id, session_id, role FROM conversation_messages WHERE message_id = ?",
                (int(message_id),),
            ).fetchone()
            if not row:
                raise ValueError(f"未找到消息：{message_id}")
            conn.execute(
                "UPDATE conversation_messages SET content = ?, meta_json = ?, created_at = ? WHERE message_id = ?",
                (content, json.dumps(meta or {}, ensure_ascii=False), now, int(message_id)),
            )
        self.touch_conversation(row["session_id"])
        return {"message_id": row["message_id"], "session_id": row["session_id"], "role": row["role"]}

    def delete_messages_after(self, session_id: str, message_id: int, include_self: bool = False) -> None:
        op = ">=" if include_self else ">"
        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM conversation_messages WHERE session_id = ? AND message_id {op} ?",
                (session_id, int(message_id)),
            )
        self.touch_conversation(session_id)

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT message_id, session_id, role, content, meta_json, created_at FROM conversation_messages WHERE session_id = ? ORDER BY message_id ASC",
                (session_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            payload["meta"] = json.loads(payload.pop("meta_json") or "{}")
            out.append(payload)
        return out

    def clear_conversation_messages(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM conversation_messages WHERE session_id = ?", (session_id,))
        self.touch_conversation(session_id)

    def delete_conversation(self, session_id: str) -> None:
        current = self.get_current_conversation_id()
        with self._connect() as conn:
            conn.execute("DELETE FROM conversation_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
        if current == session_id:
            self._set_state("current_conversation_id", "")

    def start_pipeline_run(
        self,
        run_id: str,
        pipeline_name: str,
        source_type: str,
        source_value: str,
        output_prefix: str,
        summary: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pipeline_runs (run_id, pipeline_name, status, source_type, source_value, output_prefix, summary_json, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT finished_at FROM pipeline_runs WHERE run_id = ?), NULL))
                """,
                (run_id, pipeline_name, "running", source_type, source_value, output_prefix, json.dumps(summary or {}, ensure_ascii=False), now, run_id),
            )

    def add_pipeline_step(
        self,
        run_id: str,
        step_order: int,
        step_name: str,
        status: str,
        input_summary: str = "",
        output_summary: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline_steps (run_id, step_order, step_name, status, input_summary, output_summary, detail_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, int(step_order), step_name, status, input_summary, output_summary, json.dumps(detail or {}, ensure_ascii=False), now),
            )

    def finish_pipeline_run(self, run_id: str, status: str, summary: dict[str, Any] | None = None) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, summary_json = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (status, json.dumps(summary or {}, ensure_ascii=False), now, run_id),
            )

    def list_pipeline_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, pipeline_name, status, source_type, source_value, output_prefix, summary_json, started_at, finished_at
                FROM pipeline_runs
                ORDER BY started_at DESC, run_id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            payload["summary"] = json.loads(payload.pop("summary_json") or "{}")
            out.append(payload)
        return out

    def pipeline_run_detail(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            run_row = conn.execute(
                """
                SELECT run_id, pipeline_name, status, source_type, source_value, output_prefix, summary_json, started_at, finished_at
                FROM pipeline_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if not run_row:
                return None
            step_rows = conn.execute(
                """
                SELECT step_id, run_id, step_order, step_name, status, input_summary, output_summary, detail_json, created_at
                FROM pipeline_steps WHERE run_id = ? ORDER BY step_order ASC, step_id ASC
                """,
                (run_id,),
            ).fetchall()
        payload = dict(run_row)
        payload["summary"] = json.loads(payload.pop("summary_json") or "{}")
        payload["steps"] = []
        for row in step_rows:
            item = dict(row)
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
            payload["steps"].append(item)
        return payload

    def status(self) -> dict[str, Any]:
        catalog = self.list_catalog()
        tables = self.list_sql_tables()
        runs = self.list_pipeline_runs(limit=8)
        latest = self.pipeline_run_detail(runs[0]["run_id"]) if runs else None
        return {
            "db_path": str(self.db_path),
            "catalog_count": len(catalog),
            "sql_table_count": len(tables),
            "pipeline_run_count": len(runs),
            "conversation_count": len(self.list_conversations()),
            "catalog_preview": catalog[:12],
            "sql_tables_preview": tables[:12],
            "pipeline_runs_preview": runs,
            "latest_pipeline": latest,
        }
