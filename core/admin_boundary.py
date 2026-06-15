from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from .data_manager import DataManager


ADMIN_ZIP_NAMES = {
    "china_admin_province_city_county_shp.zip",
    "china_admin_boundary.zip",
    "china_admin_county_2023.zip",
}

REGION_ALIASES: dict[str, list[str]] = {
    "四川": ["四川", "四川省", "Sichuan"],
    "四川省": ["四川", "四川省", "Sichuan"],
    "sichuan": ["四川", "四川省", "Sichuan"],
    "成都": ["成都", "成都市", "Chengdu"],
    "成都市": ["成都", "成都市", "Chengdu"],
    "chengdu": ["成都", "成都市", "Chengdu"],
}


def _shared_workdir(workdir: Path) -> Path:
    path = Path(workdir)
    if path.parent.name == "users":
        return path.parent.parent
    if path.name == "anonymous":
        return path.parent
    return path


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    root = target_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            mode = member.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                raise ValueError(f"Unsafe admin boundary zip symlink: {member.filename}")
            target = (root / member.filename).resolve()
            try:
                target.relative_to(root)
            except Exception as exc:
                raise ValueError(f"行政区划压缩包包含不安全路径: {member.filename}") from exc
        zf.extractall(root)


def _candidate_admin_archives(manager: DataManager) -> list[Path]:
    project_root = Path(__file__).resolve().parents[1]
    shared = _shared_workdir(manager.workdir)
    roots = [
        manager.workdir / "local_library" / "data" / "administrative",
        shared / "local_library" / "data" / "administrative",
        project_root / "local_library" / "data" / "administrative",
    ]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*.zip"):
            if path.name in ADMIN_ZIP_NAMES or "admin" in path.name.lower() or "行政" in path.name:
                if path not in found:
                    found.append(path)
    return found


def _cache_dir(manager: DataManager, archive: Path) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", archive.stem).strip("._-") or "admin_boundary"
    return manager.temp_dir / "local_admin_boundaries" / safe


def _aliases(region: str) -> list[str]:
    key = str(region or "").strip()
    if not key or key in {"当前研究区", "current_region"}:
        return []
    values = REGION_ALIASES.get(key) or REGION_ALIASES.get(key.lower())
    if values:
        return values
    trimmed = re.sub(r"(特别行政区|自治区|自治州|自治县|自治旗|地区|盟|省|市|县|区|旗)$", "", key)
    values = [key]
    if trimmed and trimmed != key:
        values.append(trimmed)
    if key == trimmed:
        values.extend([f"{key}省", f"{key}市", f"{key}县", f"{key}区"])
    return list(dict.fromkeys(values))


def _text_match_mask(gdf: gpd.GeoDataFrame, aliases: list[str]) -> pd.Series:
    mask = pd.Series(False, index=gdf.index)
    text_cols = [
        c for c in gdf.columns
        if c != gdf.geometry.name and pd.api.types.is_string_dtype(gdf[c].dtype)
    ]
    preferred_name_cols = [
        c for c in (
            "地名", "县级", "地级", "省级", "曾用名",
            "ENG_NAME", "NAME_3", "NAME_2", "NAME_1",
        )
        if c in text_cols
    ]
    normalized_aliases = {str(alias).strip().casefold() for alias in aliases if str(alias).strip()}
    for col in preferred_name_cols:
        values = gdf[col].astype(str).str.strip().str.casefold()
        mask = mask | values.isin(normalized_aliases)
    if bool(mask.any()):
        return mask

    for col in text_cols:
        values = gdf[col].astype(str)
        for alias in aliases:
            mask = mask | values.str.contains(re.escape(alias), case=False, na=False)
    return mask


def _score_candidate(shp: Path, gdf: gpd.GeoDataFrame, selected: gpd.GeoDataFrame, region: str) -> int:
    path_text = str(shp).lower()
    geom_types = {str(x).lower() for x in selected.geometry.geom_type.dropna().unique()}
    score = 0
    if any("polygon" in item for item in geom_types):
        score += 100
    else:
        score -= 200
    if "region" in path_text:
        score += 60
    if "res2" in path_text or "city" in path_text:
        score += 40
    if "res1" in path_text or "province" in path_text:
        score += 30
    if len(gdf) <= 500:
        score += 15
    if "成都" in region or region.lower() == "chengdu":
        if any(str(v) in {"成都市", "成都", "Chengdu"} for v in selected.drop(columns=["geometry"], errors="ignore").astype(str).to_numpy().ravel()):
            score += 40
    if "四川" in region or region.lower() == "sichuan":
        if any(str(v) in {"四川", "四川省", "Sichuan"} for v in selected.drop(columns=["geometry"], errors="ignore").astype(str).to_numpy().ravel()):
            score += 40
    return score


def extract_local_admin_boundary(manager: DataManager, region: str) -> tuple[gpd.GeoDataFrame | None, str, str]:
    """Find and register a local-library administrative boundary for region.

    This is used as a deterministic fallback before GSCloud tile planning. It
    converts the matched boundary to EPSG:4326 and stores it in the workspace so
    later tasks can reuse the same dataset by name.
    """
    aliases = _aliases(region)
    if not aliases:
        return None, "", ""

    best: tuple[int, Path, gpd.GeoDataFrame] | None = None
    for archive in _candidate_admin_archives(manager):
        target = _cache_dir(manager, archive)
        marker = target / ".extracted"
        if not marker.exists():
            target.mkdir(parents=True, exist_ok=True)
            _safe_extract_zip(archive, target)
            marker.write_text(str(archive), encoding="utf-8")

        for shp in target.rglob("*.shp"):
            try:
                gdf = gpd.read_file(shp)
            except Exception:
                continue
            if gdf.empty or "geometry" not in gdf:
                continue
            mask = _text_match_mask(gdf, aliases)
            if not bool(mask.any()):
                continue
            selected = gdf.loc[mask].copy()
            score = _score_candidate(shp, gdf, selected, str(region or ""))
            if best is None or score > best[0]:
                best = (score, shp, selected)

    if best is None:
        return None, "", ""

    _, shp, selected = best
    if selected.crs is None:
        selected = selected.set_crs("EPSG:4326", allow_override=True)
    else:
        selected = selected.to_crs("EPSG:4326")
    selected = selected[selected.geometry.notna() & ~selected.geometry.is_empty].copy()
    if selected.empty:
        return None, "", ""

    name_base = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", str(region or "region")).strip("_") or "region"
    dataset_name = manager.put_vector(f"{name_base}_boundary", selected, filename=f"{name_base}_boundary.geojson")
    manager.log_operation(
        "从本地行政区划提取边界",
        f"{region} -> {dataset_name} | source={shp.name} | features={len(selected)}",
        "local_library",
    )
    return selected, dataset_name, "local_library_admin_boundary"
