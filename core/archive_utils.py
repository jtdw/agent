from __future__ import annotations

import zipfile
from pathlib import Path


def safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    root = target_dir.resolve()
    for member in zf.infolist():
        mode = member.external_attr >> 16
        if mode & 0o170000 == 0o120000:
            raise ValueError(f"Unsafe zip symlink: {member.filename}")
        target = (root / member.filename).resolve()
        try:
            target.relative_to(root)
        except Exception:
            raise ValueError(f"Unsafe zip member path: {member.filename}")
    zf.extractall(root)
