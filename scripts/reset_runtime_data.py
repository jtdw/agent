"""Reset generated runtime data while preserving accounts and GSCloud login state."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNTIME_PATHS = (
    "anonymous",
    "users",
    "derived",
    "plots",
    "temp",
    "uploads",
    "exports",
    "domestic_downloads",
    "gscloud_download_verification",
    "verification",
    "local_library",
)
WORKSPACE_TABLES = (
    "pipeline_steps",
    "pipeline_runs",
    "conversation_messages",
    "conversation_state",
    "conversations",
    "model_results",
    "artifacts",
    "document_store",
    "dataset_catalog",
    "operation_logs",
    "app_state",
)
COMMERCIAL_RESET_TABLES = ("download_jobs", "audit_events")
TEST_ACCOUNT_PREFIXES = ("audit.", "e2e.", "playwright.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_preserved_auth_file(path: Path, excluded_user_ids: set[str] | None = None) -> bool:
    name = path.name.lower()
    if any(user_id.lower() in name for user_id in excluded_user_ids or set()):
        return False
    return path.is_file() and path.suffix.lower() == ".json" and ("storage_state" in name or "cookie" in name)


def build_runtime_reset_plan(project_root: Path) -> dict[str, Any]:
    project = project_root.resolve()
    workspace = project / "workspace"
    preserved = []
    auth_root = workspace / "domestic_auth"
    if auth_root.exists():
        for path in sorted(auth_root.rglob("*")):
            if _is_preserved_auth_file(path):
                preserved.append(str(path.relative_to(project)))
    return {
        "project_root": str(project),
        "workspace_root": str(workspace),
        "preserve": {
            "commercial_tables": [
                "commercial_users",
                "source_credentials",
                "platform_accounts",
                "quota_ledger",
                "login_sessions",
                "payment_orders",
                "payment_records",
            ],
            "auth_files": preserved,
            "commercial_secret_key": str((workspace / "commercial_secret.key").relative_to(project)),
        },
        "reset": {
            "commercial_tables": list(COMMERCIAL_RESET_TABLES),
            "workspace_tables": list(WORKSPACE_TABLES),
            "runtime_paths": [str(Path("workspace") / name) for name in RUNTIME_PATHS],
            "domestic_auth_non_login_state": True,
        },
    }


def _backup_file(source: Path, destination: Path) -> None:
    if not source.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _clear_tables(db_path: Path, tables: tuple[str, ...]) -> dict[str, int]:
    if not db_path.exists():
        return {}
    counts: dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.execute("PRAGMA foreign_keys=OFF")
        for table in tables:
            if table not in existing:
                continue
            counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            conn.execute(f'DELETE FROM "{table}"')
        if "quota_ledger" in existing and "download_jobs" in tables:
            conn.execute("UPDATE quota_ledger SET job_id=NULL WHERE job_id IS NOT NULL")
        conn.commit()
    return counts


def _delete_test_accounts(db_path: Path) -> tuple[list[str], int]:
    if not db_path.exists():
        return [], 0
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT user_id, email FROM commercial_users").fetchall()
        user_ids = [
            str(user_id)
            for user_id, email in rows
            if str(email or "").strip().lower().startswith(TEST_ACCOUNT_PREFIXES)
        ]
        for user_id in user_ids:
            for table in ("source_credentials", "quota_ledger", "login_sessions", "payment_orders", "payment_records"):
                conn.execute(f'DELETE FROM "{table}" WHERE user_id=?', [user_id])
            conn.execute("DELETE FROM commercial_users WHERE user_id=?", [user_id])
        conn.commit()
    return user_ids, len(user_ids)


def _move_runtime_path(source: Path, project: Path, backup: Path, moved: list[dict[str, Any]]) -> None:
    if not source.exists():
        return
    if not _under(source, project):
        raise ValueError(f"Runtime path escapes project root: {source}")
    relative = source.relative_to(project)
    destination = backup / "runtime" / relative
    if destination.exists():
        raise FileExistsError(f"Backup collision: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    moved.append({"path": str(relative), "backup": str(destination.relative_to(backup))})


def _backup_and_clean_auth(
    project: Path,
    backup: Path,
    preserved: list[dict[str, Any]],
    moved: list[dict[str, Any]],
    excluded_user_ids: set[str],
) -> None:
    auth_root = project / "workspace" / "domestic_auth"
    if not auth_root.exists():
        return
    for path in sorted((item for item in auth_root.rglob("*") if item.is_file()), reverse=True):
        relative = path.relative_to(project)
        if _is_preserved_auth_file(path, excluded_user_ids):
            backup_path = backup / "preserved_auth" / relative
            _backup_file(path, backup_path)
            preserved.append({"path": str(relative), "sha256": _sha256(path), "bytes": path.stat().st_size})
            continue
        destination = backup / "runtime" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        moved.append({"path": str(relative), "backup": str(destination.relative_to(backup))})
    for directory in sorted((item for item in auth_root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def execute_runtime_reset(project_root: Path, backup_root: Path) -> Path:
    project = project_root.resolve()
    backup = backup_root.resolve(strict=False)
    if backup.exists():
        raise FileExistsError(f"Backup destination already exists: {backup}")
    if _under(backup, project):
        raise ValueError("Backup destination must be outside the project root")
    workspace = project / "workspace"
    backup.mkdir(parents=True, exist_ok=False)

    plan = build_runtime_reset_plan(project)
    moved: list[dict[str, Any]] = []
    preserved_auth: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {"schema_version": 1, "status": "running", "created_at": _now(), "plan": plan}
    manifest_path = backup / "runtime_reset_manifest.json"

    try:
        commercial_db = workspace / "commercial.db"
        workspace_db = workspace / "workspace.db"
        _backup_file(commercial_db, backup / "commercial.db")
        _backup_file(workspace_db, backup / "workspace.db")
        _backup_file(workspace / "commercial_secret.key", backup / "commercial_secret.key")

        commercial_counts = _clear_tables(commercial_db, COMMERCIAL_RESET_TABLES)
        deleted_test_user_ids, deleted_test_accounts = _delete_test_accounts(commercial_db)
        workspace_counts = _clear_tables(workspace_db, WORKSPACE_TABLES)
        for name in RUNTIME_PATHS:
            _move_runtime_path(workspace / name, project, backup, moved)
        _backup_and_clean_auth(project, backup, preserved_auth, moved, set(deleted_test_user_ids))

        manifest.update(
            {
                "status": "completed",
                "completed_at": _now(),
                "deleted_rows": {"commercial": commercial_counts, "workspace": workspace_counts},
                "deleted_test_accounts": deleted_test_accounts,
                "moved_paths": moved,
                "preserved_auth": preserved_auth,
            }
        )
    except Exception as exc:
        manifest.update({"status": "failed", "failed_at": _now(), "error_type": type(exc).__name__, "error": str(exc)})
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        raise

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan = build_runtime_reset_plan(args.project_root)
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    backup = args.backup_root or Path(r"E:\agent\test") / args.project_root.resolve().name / f"runtime-reset-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(execute_runtime_reset(args.project_root, backup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
