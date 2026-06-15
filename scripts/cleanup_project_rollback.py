"""Rollback a cleanup migration from moved_files_manifest.json."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_manifest(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def rollback_migration(manifest_path: Path) -> None:
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") == "rolled_back":
        raise RuntimeError("Migration is already rolled back")

    project_root = Path(manifest["project_root"]).resolve()
    for entry in reversed(manifest.get("entries", [])):
        if entry.get("status") != "moved":
            continue
        source = Path(entry["source"])
        destination = Path(entry["destination"])
        if source.exists():
            raise FileExistsError(f"Rollback source collision: {source}")
        if not destination.exists():
            raise FileNotFoundError(f"Archived item missing: {destination}")
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))
        entry["status"] = "restored"
        entry["restored_at"] = _now()
        _write_manifest(manifest_path, manifest)

    requirements = manifest.get("requirements_change") or {}
    backup = Path(requirements.get("backup") or "")
    target = project_root / "requirements.txt"
    if requirements.get("status") in {"updated", "unchanged"}:
        if not backup.exists():
            raise FileNotFoundError(f"Requirements backup missing: {backup}")
        shutil.copy2(backup, target)
        requirements["status"] = "restored"
        requirements["restored_at"] = _now()

    manifest["status"] = "rolled_back"
    manifest["rolled_back_at"] = _now()
    _write_manifest(manifest_path, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    rollback_migration(args.manifest)
    print(f"Rollback completed from {args.manifest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
