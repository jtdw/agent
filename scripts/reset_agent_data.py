from __future__ import annotations

import argparse
import gc
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any


CORE_DIRS = ("uploads", "plots", "derived", "temp", "exports")
USER_DATA_DIRS = (
    "anonymous",
    "users",
    "domestic_downloads",
    "domestic_auth",
    "resource_index",
    "gscloud_download_verification",
)
RECREATE_DIRS = ("uploads", "plots", "derived", "temp", "exports")
WORKSPACE_DB_NAMES = ("workspace.db",)
COMMERCIAL_DB_NAMES = ("commercial.db",)
CATEGORY_CHOICES = {"uploads", "downloads", "results", "auth", "temp", "exports", "chats", "jobs"}


def _resolve_workdir(value: str = "") -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return (Path.cwd() / "workspace").resolve()


def _assert_workspace_path(workdir: Path, target: Path) -> Path:
    resolved = target.resolve(strict=False)
    root = workdir.resolve(strict=False)
    if resolved == root:
        return resolved
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"refuse to remove path outside workspace: {resolved}") from exc
    return resolved


def _add_path(plan: dict[str, Any], workdir: Path, target: Path) -> None:
    resolved = _assert_workspace_path(workdir, target)
    key = str(resolved).lower()
    if key not in plan["_seen"]:
        plan["_seen"].add(key)
        plan["paths"].append(str(resolved))


def _iter_user_workspaces(workdir: Path) -> list[Path]:
    roots = []
    users_dir = workdir / "users"
    if users_dir.exists():
        roots.extend([item for item in users_dir.iterdir() if item.is_dir()])
    anonymous = workdir / "anonymous"
    if anonymous.exists():
        roots.append(anonymous)
    return roots


def build_reset_plan(workdir: Path, mode: str, categories: set[str] | None = None) -> dict[str, Any]:
    workdir = workdir.resolve(strict=False)
    categories = categories or set()
    plan: dict[str, Any] = {
        "workdir": str(workdir),
        "mode": mode,
        "paths": [],
        "db_actions": [],
        "_seen": set(),
    }

    if mode == "full":
        for name in (*CORE_DIRS, *USER_DATA_DIRS, *WORKSPACE_DB_NAMES, *COMMERCIAL_DB_NAMES):
            _add_path(plan, workdir, workdir / name)
        for user_root in _iter_user_workspaces(workdir):
            _add_path(plan, workdir, user_root)
        plan["db_actions"].append({"database": str(workdir / "commercial.db"), "action": "delete_database"})
        return {k: v for k, v in plan.items() if k != "_seen"}

    if mode == "keep-accounts":
        categories = {"uploads", "downloads", "results", "auth", "temp", "exports", "chats", "jobs"}

    def add_category(category: str) -> None:
        if category == "uploads":
            _add_path(plan, workdir, workdir / "uploads")
            for user_root in _iter_user_workspaces(workdir):
                _add_path(plan, workdir, user_root / "uploads")
        elif category == "downloads":
            for name in ("domestic_downloads", "resource_index", "gscloud_download_verification"):
                _add_path(plan, workdir, workdir / name)
            for user_root in _iter_user_workspaces(workdir):
                _add_path(plan, workdir, user_root / "downloads")
        elif category == "results":
            for name in ("plots", "derived"):
                _add_path(plan, workdir, workdir / name)
                for user_root in _iter_user_workspaces(workdir):
                    _add_path(plan, workdir, user_root / name)
            _add_path(plan, workdir, workdir / "workspace.db")
        elif category == "auth":
            for name in ("domestic_auth",):
                _add_path(plan, workdir, workdir / name)
            for user_root in _iter_user_workspaces(workdir):
                _add_path(plan, workdir, user_root / "domestic_auth")
        elif category == "temp":
            _add_path(plan, workdir, workdir / "temp")
            for user_root in _iter_user_workspaces(workdir):
                _add_path(plan, workdir, user_root / "temp")
        elif category == "exports":
            _add_path(plan, workdir, workdir / "exports")
            for user_root in _iter_user_workspaces(workdir):
                _add_path(plan, workdir, user_root / "exports")
        elif category == "chats":
            _add_path(plan, workdir, workdir / "workspace.db")
            plan["db_actions"].append({"database": str(workdir / "workspace.db"), "action": "clear_chats"})
        elif category == "jobs":
            plan["db_actions"].append({"database": str(workdir / "commercial.db"), "action": "clear_jobs"})

    for category in sorted(categories):
        add_category(category)

    if mode == "keep-accounts":
        plan["db_actions"].append({"database": str(workdir / "commercial.db"), "action": "keep_commercial_users_only"})

    return {k: v for k, v in plan.items() if k != "_seen"}


def _remove_path_once(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_dir():
        shutil.rmtree(path)
        return "removed_dir"
    path.unlink()
    return "removed_file"


def _remove_path(path: Path) -> str:
    last_error: Exception | None = None
    for _ in range(5):
        try:
            return _remove_path_once(path)
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            time.sleep(0.3)
    raise PermissionError(f"{last_error}。如果后端服务正在运行，请先停止后端再清理。")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _delete_from_existing(conn: sqlite3.Connection, tables: list[str]) -> list[str]:
    cleared: list[str] = []
    for table in tables:
        if _table_exists(conn, table):
            conn.execute(f'DELETE FROM "{table}"')
            cleared.append(table)
    return cleared


def _run_db_action(action: dict[str, str]) -> dict[str, Any]:
    db_path = Path(action["database"])
    if not db_path.exists():
        return {"database": str(db_path), "action": action["action"], "status": "missing"}
    with sqlite3.connect(db_path) as conn:
        if action["action"] == "clear_chats":
            cleared = _delete_from_existing(conn, ["conversation_state", "conversation_messages", "conversations"])
        elif action["action"] == "clear_jobs":
            cleared = _delete_from_existing(conn, ["audit_events", "quota_ledger", "download_jobs", "login_sessions"])
        elif action["action"] == "keep_commercial_users_only":
            cleared = _delete_from_existing(
                conn,
                [
                    "audit_events",
                    "payment_records",
                    "payment_orders",
                    "quota_ledger",
                    "download_jobs",
                    "login_sessions",
                    "source_credentials",
                    "platform_accounts",
                ],
            )
            if _table_exists(conn, "commercial_users"):
                conn.execute(
                    """
                    UPDATE commercial_users
                    SET platform_monthly_used=0,
                        login_failed_count=0,
                        locked_until=NULL,
                        last_login_at=NULL,
                        updated_at=datetime('now')
                    """
                )
        else:
            cleared = []
        return {"database": str(db_path), "action": action["action"], "status": "ok", "cleared": cleared}


def _recreate_base_dirs(workdir: Path) -> None:
    for name in RECREATE_DIRS:
        (workdir / name).mkdir(parents=True, exist_ok=True)


def reset_agent_data(workdir: Path, mode: str, categories: set[str] | None = None, yes: bool = False) -> dict[str, Any]:
    plan = build_reset_plan(workdir, mode, categories)
    if not yes:
        return {"ok": True, "dry_run": True, "plan": plan, "message": "dry-run only; add --yes to delete data"}

    removed: list[dict[str, str]] = []
    for item in plan["paths"]:
        path = _assert_workspace_path(workdir, Path(item))
        removed.append({"path": str(path), "status": _remove_path(path)})

    db_results = [_run_db_action(action) for action in plan["db_actions"] if action.get("action") != "delete_database"]
    _recreate_base_dirs(workdir)
    return {"ok": True, "dry_run": False, "plan": plan, "removed": removed, "db_results": db_results}


def _parse_categories(value: str) -> set[str]:
    out = {item.strip().lower() for item in str(value or "").split(",") if item.strip()}
    unknown = out - CATEGORY_CHOICES
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown categories: {', '.join(sorted(unknown))}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete GIS Agent user/runtime data.")
    parser.add_argument("--workdir", default="", help="workspace root, defaults to ./workspace")
    parser.add_argument("--mode", choices=["full", "keep-accounts", "custom"], default="keep-accounts")
    parser.add_argument("--categories", type=_parse_categories, default=set(), help="custom categories, comma separated")
    parser.add_argument("--yes", action="store_true", help="actually delete; default is dry-run")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()

    categories = args.categories if args.mode == "custom" else None
    result = reset_agent_data(_resolve_workdir(args.workdir), args.mode, categories, yes=args.yes)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"mode: {result['plan']['mode']}")
        print(f"workdir: {result['plan']['workdir']}")
        print(f"dry_run: {result['dry_run']}")
        for path in result["plan"]["paths"]:
            print(f"- {path}")
        if result["dry_run"]:
            print("add --yes to delete data")


if __name__ == "__main__":
    main()
