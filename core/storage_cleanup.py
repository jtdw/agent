from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any


CONFIRM_TEXT = "删除历史缓存"
PRESERVED_DIR_NAMES = {"capability_config", "local_library"}
UPLOAD_DUPLICATE_EXTS = {".tif", ".tiff", ".img", ".zip", ".csv", ".xlsx", ".xls", ".geojson", ".gpkg", ".shp"}


def _safe_id(path: Path, category: str) -> str:
    raw = f"{category}:{path.resolve(strict=False)}"
    return "cleanup_" + hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _dir_stats(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return 1, path.stat().st_size
        except OSError:
            return 1, 0
    files = 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            files += 1
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return files, total


def _candidate(root: Path, path: Path, *, category: str, reason: str, kind: str | None = None) -> dict[str, Any]:
    files, size = _dir_stats(path)
    return {
        "candidate_id": _safe_id(path, category),
        "category": category,
        "path": str(path),
        "kind": kind or ("directory" if path.is_dir() else "file"),
        "file_count": files,
        "size_bytes": size,
        "safe_to_delete": True,
        "reason": reason,
    }


def _normalize_reference(root: Path, value: str) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    candidates: set[Path] = set()
    raw = Path(text)
    if raw.is_absolute():
        candidates.add(raw)
    else:
        candidates.add(root / raw)
        if text.replace("\\", "/").startswith("workspace/"):
            candidates.add(root.parent / raw)
    normalized = set()
    for item in candidates:
        try:
            normalized.add(str(item.resolve(strict=False)).lower())
        except Exception:
            pass
    return normalized


def _iter_db_text_values(db_path: Path) -> list[str]:
    values: list[str] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception:
        return values
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (table,) in rows:
            if str(table).startswith("sqlite_"):
                continue
            try:
                columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
            except Exception:
                continue
            text_cols = [str(col[1]) for col in columns if str(col[2] or "").upper() in {"TEXT", ""}]
            for col in text_cols:
                lowered = col.lower()
                if not any(token in lowered for token in ("path", "json", "dataset", "artifact", "file", "output", "zip", "local")):
                    continue
                try:
                    for (value,) in conn.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL"):
                        if value is not None:
                            values.append(str(value))
                except Exception:
                    continue
    finally:
        conn.close()
    return values


def referenced_paths(root: Path) -> set[str]:
    root = Path(root)
    refs: set[str] = set()
    for db_path in root.rglob("*.db"):
        for value in _iter_db_text_values(db_path):
            refs.update(_normalize_reference(root, value))
            if "{" in value or "[" in value:
                try:
                    parsed = json.loads(value)
                except Exception:
                    parsed = None
                stack = [parsed]
                while stack:
                    item = stack.pop()
                    if isinstance(item, dict):
                        stack.extend(item.values())
                    elif isinstance(item, list):
                        stack.extend(item)
                    elif isinstance(item, str):
                        refs.update(_normalize_reference(root, item))
    return refs


def _is_referenced(path: Path, refs: set[str]) -> bool:
    try:
        resolved = str(path.resolve(strict=False)).lower()
    except Exception:
        return False
    if resolved in refs:
        return True
    for ref in refs:
        try:
            if ref and (resolved.startswith(ref + "\\") or resolved.startswith(ref + "/")):
                return True
        except Exception:
            continue
    return False


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preview_candidates(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for preview_dir in root.rglob("map_previews"):
        if not preview_dir.is_dir() or preview_dir.name in PRESERVED_DIR_NAMES:
            continue
        for path in preview_dir.glob("*.png"):
            if path.is_file():
                out.append(_candidate(root, path, category="preview_cache", reason="地图预览缓存，可按需重新生成。"))
    return out


def _postprocess_cache_candidates(root: Path, refs: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in root.rglob("download_postprocess_extracts"):
        if path.is_dir() and not _is_referenced(path, refs):
            out.append(_candidate(root, path, category="download_postprocess_extract_cache", reason="下载后处理解压缓存，新链路会按需选择性解压。"))
    return out


def _timestamped_batch_candidates(root: Path, refs: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pattern = re.compile(r"_gscloud_batch_20\d{6}_\d{6}$")
    for path in root.rglob("*"):
        if path.is_dir() and pattern.search(path.name) and not _is_referenced(path, refs):
            out.append(_candidate(root, path, category="timestamped_gscloud_batch_cache", reason="旧版 GSCloud 批处理时间戳目录，已由稳定目录替代。"))
    return out


def _duplicate_upload_candidates(root: Path, refs: set[str]) -> list[dict[str, Any]]:
    uploads = [p for p in root.rglob("uploads") if p.is_dir()]
    by_size: dict[int, list[Path]] = {}
    for upload_dir in uploads:
        for path in upload_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in UPLOAD_DUPLICATE_EXTS:
                continue
            try:
                by_size.setdefault(path.stat().st_size, []).append(path)
            except OSError:
                continue
    out: list[dict[str, Any]] = []
    for paths in by_size.values():
        if len(paths) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for path in paths:
            try:
                by_hash.setdefault(_hash_file(path), []).append(path)
            except OSError:
                continue
        for group in by_hash.values():
            if len(group) < 2:
                continue
            referenced = [p for p in group if _is_referenced(p, refs)]
            keep = referenced[0] if referenced else sorted(group, key=lambda p: p.stat().st_mtime, reverse=True)[0]
            for path in group:
                if path == keep or _is_referenced(path, refs):
                    continue
                out.append(_candidate(root, path, category="unreferenced_duplicate_upload", reason=f"与 {keep.name} 内容相同，且未被数据库引用。"))
    return out


def scan_storage_cleanup_candidates(root: Path) -> dict[str, Any]:
    root = Path(root).resolve(strict=False)
    refs = referenced_paths(root)
    candidates: list[dict[str, Any]] = []
    candidates.extend(_preview_candidates(root))
    candidates.extend(_postprocess_cache_candidates(root, refs))
    candidates.extend(_timestamped_batch_candidates(root, refs))
    candidates.extend(_duplicate_upload_candidates(root, refs))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in candidates:
        if item["candidate_id"] in seen:
            continue
        seen.add(item["candidate_id"])
        unique.append(item)
    unique.sort(key=lambda item: (str(item["category"]), str(item["path"])))
    return {
        "schema_version": "storage-cleanup-scan/v1",
        "root": str(root),
        "candidates": unique,
        "total_candidates": len(unique),
        "total_size_bytes": sum(int(item.get("size_bytes") or 0) for item in unique),
        "referenced_path_count": len(refs),
    }


def _delete_candidate_path(root: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(candidate.get("path") or ""))
    resolved_root = root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except Exception as exc:
        raise PermissionError(f"refusing to delete outside workspace: {resolved}") from exc
    if resolved == resolved_root:
        raise PermissionError("refusing to delete workspace root")
    files, size = _dir_stats(resolved)
    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()
    return {"candidate_id": candidate["candidate_id"], "path": str(resolved), "files": files, "bytes": size}


def cleanup_storage_candidates(root: Path, *, candidate_ids: list[str], confirm_text: str) -> dict[str, Any]:
    if str(confirm_text or "").strip() != CONFIRM_TEXT:
        raise ValueError(f"确认文本不匹配，请输入：{CONFIRM_TEXT}")
    scan = scan_storage_cleanup_candidates(root)
    wanted = set(str(item) for item in candidate_ids)
    candidates = [item for item in scan["candidates"] if item["candidate_id"] in wanted and item.get("safe_to_delete")]
    deleted: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in candidates:
        try:
            deleted.append(_delete_candidate_path(Path(root), item))
        except Exception as exc:
            errors.append(f"{item.get('path')}: {exc}")
    return {
        "ok": not errors,
        "schema_version": "storage-cleanup-delete/v1",
        "deleted": deleted,
        "errors": errors,
        "deleted_count": len(deleted),
        "freed_bytes": sum(int(item.get("bytes") or 0) for item in deleted),
    }
