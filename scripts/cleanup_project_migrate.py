"""Execute the approved cleanup migration without permanently deleting files."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _load_dry_run_module():
    path = Path(__file__).with_name("cleanup_project_dry_run.py")
    spec = importlib.util.spec_from_file_location("cleanup_project_dry_run_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load dry-run plan: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _remove_streamlit_requirement(project_root: Path, batch_root: Path) -> dict:
    requirements = project_root / "requirements.txt"
    backup = batch_root / "backups" / "requirements.txt"
    if not requirements.exists():
        return {"status": "missing", "source": str(requirements), "backup": str(backup)}
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(requirements, backup)
    original = requirements.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    retained = [line for line in lines if not line.strip().lower().startswith("streamlit")]
    if retained != lines:
        requirements.write_text("".join(retained), encoding="utf-8")
        status = "updated"
    else:
        status = "unchanged"
    return {"status": status, "source": str(requirements), "backup": str(backup)}


def _existing_parent(path: Path) -> Path:
    current = path.resolve(strict=False)
    while not current.exists():
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(f"No existing parent found for {path}")
        current = parent
    return current


def execute_migration(
    project_root: Path,
    batch_root: Path,
    *,
    only_sources: set[Path] | None = None,
) -> Path:
    project_root = project_root.resolve()
    batch_root = batch_root.resolve(strict=False)
    if batch_root.exists():
        raise FileExistsError(f"Batch destination already exists: {batch_root}")
    if _under(batch_root, project_root):
        raise ValueError("Batch destination must be outside the project root")
    if project_root.drive.lower() != batch_root.drive.lower():
        raise ValueError("Source and archive must be on the same drive to preserve move semantics")

    dry_run = _load_dry_run_module()
    planned = [item for item in dry_run.build_plan(project_root, batch_root) if item.move]
    if only_sources is not None:
        planned = [item for item in planned if item.source in only_sources]

    entries: list[dict] = []
    for item in planned:
        source = (project_root / item.source).resolve(strict=False)
        destination = (batch_root / item.source).resolve(strict=False)
        if not _under(source, project_root):
            raise ValueError(f"Source escapes project root: {item.source}")
        if not _under(destination, batch_root):
            raise ValueError(f"Destination escapes batch root: {item.source}")
        if destination.exists():
            raise FileExistsError(f"Destination collision: {destination}")
        exists = source.exists()
        entries.append(
            {
                "source": str(source),
                "relative_path": str(item.source),
                "destination": str(destination),
                "category": item.category,
                "reason": item.reason,
                "sensitive": bool(item.sensitive),
                "bytes": _path_size(source) if exists else 0,
                "status": "planned" if exists else "missing",
                "planned_at": _now(),
            }
        )

    usage = shutil.disk_usage(_existing_parent(batch_root.parent))
    required = sum(entry["bytes"] for entry in entries if entry["status"] == "planned")
    if usage.free < required:
        raise OSError(f"Insufficient archive disk space: required={required}, free={usage.free}")

    batch_root.mkdir(parents=True, exist_ok=False)
    manifest_path = batch_root / "moved_files_manifest.json"
    manifest = {
        "schema_version": 1,
        "status": "planned",
        "project_root": str(project_root),
        "batch_root": str(batch_root),
        "created_at": _now(),
        "requirements_change": {"status": "pending"},
        "entries": entries,
    }
    _write_manifest(manifest_path, manifest)

    try:
        for entry in manifest["entries"]:
            if entry["status"] != "planned":
                continue
            source = Path(entry["source"])
            destination = Path(entry["destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            entry["status"] = "moved"
            entry["moved_at"] = _now()
            _write_manifest(manifest_path, manifest)

        manifest["requirements_change"] = _remove_streamlit_requirement(project_root, batch_root)
        manifest["requirements_change"]["updated_at"] = _now()
        manifest["status"] = "completed"
        manifest["completed_at"] = _now()
        _write_manifest(manifest_path, manifest)
        return manifest_path
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failed_at"] = _now()
        manifest["error_type"] = type(exc).__name__
        manifest["error"] = str(exc)
        _write_manifest(manifest_path, manifest)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--archive-root", type=Path, default=Path(r"E:\agent\test"))
    parser.add_argument("--timestamp", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Move only this relative source path. Can be provided multiple times.",
    )
    args = parser.parse_args()
    batch = args.archive_root / args.project_root.resolve().name / args.timestamp
    only_sources = {Path(item) for item in args.only} if args.only else None
    manifest = execute_migration(args.project_root, batch, only_sources=only_sources)
    print(f"Migration completed. Manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
