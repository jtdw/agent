from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Any


LOADABLE_EXTS = {".shp", ".geojson", ".gpkg", ".json", ".kml", ".tif", ".tiff", ".img", ".csv", ".xlsx", ".xls", ".docx", ".txt", ".md"}
RASTER_EXTS = {".tif", ".tiff", ".img"}
SHAPE_SIDE_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix"}
PRIORITY_EXTS = [".shp", ".tif", ".tiff", ".img", ".zip", ".geojson", ".gpkg", ".csv", ".xlsx", ".xls", ".docx", ".txt", ".md"]


def zip_manifest(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path, "r") as archive:
        return [
            {
                "name": item.filename,
                "suffix": Path(item.filename).suffix.lower(),
                "file_size": int(item.file_size),
                "compress_size": int(item.compress_size),
                "is_dir": item.is_dir(),
            }
            for item in archive.infolist()
        ]


def _safe_target(root: Path, member_name: str) -> Path:
    raw = str(member_name or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError("empty zip member")
    member = Path(raw)
    if member.is_absolute():
        raise ValueError(f"unsafe zip member path: {member_name}")
    target = (root / member).resolve(strict=False)
    try:
        target.relative_to(root.resolve(strict=False))
    except Exception as exc:
        raise ValueError(f"unsafe zip member path: {member_name}") from exc
    return target


def select_loadable_members(manifest: list[dict[str, Any]], *, allowed_exts: set[str] | None = None, max_datasets: int = 1) -> list[str]:
    allowed = allowed_exts or LOADABLE_EXTS
    files = [item for item in manifest if not item.get("is_dir") and str(item.get("suffix") or "").lower() in allowed]
    selected: list[str] = []
    by_name = {str(item.get("name") or ""): item for item in files}
    by_stem: dict[str, list[str]] = {}
    for item in files:
        name = str(item.get("name") or "")
        p = Path(name)
        key = str(p.with_suffix("")).replace("\\", "/").lower()
        by_stem.setdefault(key, []).append(name)

    for ext in PRIORITY_EXTS:
        if ext not in allowed:
            continue
        for item in files:
            name = str(item.get("name") or "")
            if Path(name).suffix.lower() != ext:
                continue
            if ext == ".shp":
                key = str(Path(name).with_suffix("")).replace("\\", "/").lower()
                for sibling in sorted(by_stem.get(key, [])):
                    if Path(sibling).suffix.lower() in SHAPE_SIDE_EXTS and sibling not in selected:
                        selected.append(sibling)
            elif name not in selected:
                selected.append(name)
            dataset_count = sum(1 for member in selected if Path(member).suffix.lower() in {".shp", ".tif", ".tiff", ".img", ".zip", ".geojson", ".gpkg", ".csv", ".xlsx", ".xls", ".docx", ".txt", ".md"})
            if dataset_count >= max_datasets:
                return [member for member in selected if member in by_name]
    return [member for member in selected if member in by_name]


def extract_zip_members(path: Path, output_dir: Path, members: list[str], *, clean: bool = True) -> list[Path]:
    root = output_dir.resolve(strict=False)
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    wanted = set(members)
    with zipfile.ZipFile(path, "r") as archive:
        info_by_name = {item.filename: item for item in archive.infolist()}
        for name in members:
            info = info_by_name.get(name)
            if info is None or info.is_dir():
                continue
            mode = info.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                raise ValueError(f"unsafe zip symlink: {info.filename}")
            target = _safe_target(root, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target)
    return extracted


def extract_loadable_members(path: Path, output_dir: Path, *, allowed_exts: set[str] | None = None, max_datasets: int = 1, clean: bool = True) -> tuple[list[Path], list[dict[str, Any]], list[str]]:
    manifest = zip_manifest(path)
    members = select_loadable_members(manifest, allowed_exts=allowed_exts, max_datasets=max_datasets)
    extracted = extract_zip_members(path, output_dir, members, clean=clean) if members else []
    return extracted, manifest, members
