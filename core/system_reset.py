from __future__ import annotations

import os
import shutil
import gc
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .capability_config import CapabilityConfigStore
from .commercial.service import CommercialService


ResetMode = Literal["keep_accounts", "full_reset"]
KEEP_ACCOUNTS_CONFIRM = "清除用户数据"
FULL_RESET_CONFIRM = "全部删除"
PRESERVED_WORKSPACE_ENTRIES = {"capability_config", "local_library"}


@dataclass
class DeleteSummary:
    files: int = 0
    directories: int = 0
    bytes: int = 0
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "directories": self.directories,
            "bytes": self.bytes,
            "errors": self.errors or [],
        }


def _dir_size(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    if not path.exists():
        return files, total
    for item in path.rglob("*"):
        if item.is_file():
            files += 1
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return files, total


def _safe_child(root: Path, path: Path) -> Path:
    resolved_root = root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except Exception as exc:
        raise PermissionError(f"refusing to delete outside workspace: {resolved}") from exc
    if resolved == resolved_root:
        raise PermissionError("refusing to delete workspace root directly")
    return resolved


def _delete_path(root: Path, path: Path, summary: DeleteSummary) -> None:
    target = _safe_child(root, path)
    if not target.exists():
        return
    if target.is_dir():
        files, total = _dir_size(target)
        for attempt in range(5):
            try:
                shutil.rmtree(target)
                break
            except PermissionError:
                if attempt >= 4:
                    raise
                gc.collect()
                time.sleep(0.15 * (attempt + 1))
        summary.files += files
        summary.bytes += total
        summary.directories += 1
        return
    size = 0
    try:
        size = target.stat().st_size
    except OSError:
        pass
    for attempt in range(5):
        try:
            target.unlink()
            break
        except PermissionError:
            if attempt >= 4:
                raise
            gc.collect()
            time.sleep(0.15 * (attempt + 1))
    summary.files += 1
    summary.bytes += size


def _snapshot_commercial_users(service: CommercialService) -> list[dict[str, Any]]:
    try:
        return service.db.fetch_all("SELECT * FROM commercial_users")
    except Exception:
        return []


def _restore_commercial_users(service: CommercialService, users: list[dict[str, Any]]) -> int:
    restored = 0
    for user in users:
        if not user.get("user_id") or not user.get("email"):
            continue
        try:
            service.db.insert_dict("commercial_users", dict(user))
            restored += 1
        except Exception:
            continue
    return restored


def _clear_private_capability_runtime(root: Path) -> dict[str, Any]:
    store = CapabilityConfigStore(root / "capability_config")
    removed_private_items: list[str] = []
    knowledge_path = store.root / "knowledge.json"
    if knowledge_path.exists():
        data = store._read("knowledge")
        items = data.get("items") if isinstance(data.get("items"), dict) else {}
        history = data.get("history") if isinstance(data.get("history"), dict) else {}
        for item_id, item in list(items.items()):
            item_dict = item if isinstance(item, dict) else {}
            scope = str(item_dict.get("scope") or item_dict.get("permission") or "").lower()
            if item_dict.get("session_id") or item_dict.get("owner_user_id") or scope in {"private", "session", "user"}:
                removed_private_items.append(str(item_id))
                items.pop(item_id, None)
                history.pop(item_id, None)
        data["items"] = items
        data["history"] = history
        store._write("knowledge", data)
    removed_index_dirs: list[str] = []
    for folder_name in ("knowledge_index", "knowledge_chunks", "retrieval_cache", "vector_index"):
        path = store.root / folder_name
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
            removed_index_dirs.append(folder_name)
    return {"private_knowledge_items": removed_private_items, "index_dirs": removed_index_dirs}


def reset_system_workspace(
    *,
    workdir: Path,
    commercial_service: CommercialService,
    mode: ResetMode,
    confirm_text: str,
) -> dict[str, Any]:
    mode = str(mode or "").strip()  # type: ignore[assignment]
    expected = KEEP_ACCOUNTS_CONFIRM if mode == "keep_accounts" else FULL_RESET_CONFIRM if mode == "full_reset" else ""
    if not expected:
        raise ValueError("unsupported reset mode")
    if str(confirm_text or "").strip() != expected:
        raise ValueError(f"确认文本不匹配，请输入：{expected}")

    root = Path(workdir).resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    preserved_users = _snapshot_commercial_users(commercial_service) if mode == "keep_accounts" else []
    capability_cleanup = _clear_private_capability_runtime(root)
    gc.collect()

    summary = DeleteSummary(errors=[])
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.name in PRESERVED_WORKSPACE_ENTRIES:
            continue
        try:
            _delete_path(root, child, summary)
        except Exception as exc:
            summary.errors = summary.errors or []
            summary.errors.append(f"{child.name}: {exc}")

    for folder in ("uploads", "plots", "derived", "temp"):
        (root / folder).mkdir(parents=True, exist_ok=True)

    new_commercial = CommercialService(root)
    restored_users = _restore_commercial_users(new_commercial, preserved_users) if mode == "keep_accounts" else 0
    try:
        new_commercial.db.insert_dict(
            "audit_events",
            {
                "event_id": f"admin_reset_{os.urandom(6).hex()}",
                "user_id": "",
                "action": "admin.system_reset",
                "status": "ok" if not summary.errors else "partial",
                "resource_type": "workspace",
                "resource_id": mode,
                "ip_address": "",
                "user_agent": "",
                "detail_json": "{}",
                "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
    except Exception:
        pass
    return {
        "ok": not bool(summary.errors),
        "mode": mode,
        "deleted": summary.to_dict(),
        "preserved": {
            "workspace_entries": sorted(PRESERVED_WORKSPACE_ENTRIES),
            "accounts": restored_users,
            "capability_config": (root / "capability_config").exists(),
        },
        "capability_cleanup": capability_cleanup,
        "commercial_service": new_commercial,
    }
