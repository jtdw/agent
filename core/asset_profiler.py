from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from core.ml.modeling_profile import build_modeling_profile
from core.workflow_cache import WorkflowCache


def _safe_stat(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except Exception:
        return {"file_name": path.name, "size_bytes": 0}
    return {"file_name": path.name, "size_bytes": int(stat.st_size)}


def _path_mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except Exception:
        return 0


def _profile_cache(manager: Any) -> WorkflowCache | None:
    try:
        cache_path = Path(str(getattr(manager, "temp_dir", "") or getattr(manager, "workdir", ""))) / "workflow_cache.db"
        return WorkflowCache(cache_path)
    except Exception:
        return None


def _profile_cache_key(record: Any, path: Path, stat_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset": str(getattr(record, "name", "")),
        "data_type": str(getattr(record, "data_type", "")),
        "path": str(path.resolve(strict=False)),
        "size_bytes": int(stat_payload.get("size_bytes") or 0),
        "mtime_ns": _path_mtime_ns(path),
    }


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def _time_range(df: pd.DataFrame) -> dict[str, str]:
    for col in df.columns:
        name = str(col).lower()
        if not any(token in name for token in ("date", "time", "day", "month", "year", "日期", "时间")):
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        parsed = parsed.dropna()
        if parsed.empty:
            continue
        return {
            "field": str(col),
            "start": parsed.min().date().isoformat(),
            "end": parsed.max().date().isoformat(),
        }
    return {}


def _role_inference_from_fields(fields: list[str]) -> dict[str, Any]:
    lowered = {field.lower(): field for field in fields}
    evidence: list[str] = []
    roles: list[str] = []
    lon = next((lowered[key] for key in lowered if key in {"lon", "lng", "longitude", "x"}), "")
    lat = next((lowered[key] for key in lowered if key in {"lat", "latitude", "y"}), "")
    if lon and lat:
        roles.append("coordinate_table")
        evidence.extend([lon, lat])
    if any("soil" in key and "moisture" in key for key in lowered):
        roles.append("soil_moisture_observations")
        evidence.extend([field for key, field in lowered.items() if "soil" in key and "moisture" in key])
    if any(key in {"ndvi", "evi", "lst", "dem"} for key in lowered):
        roles.append("remote_sensing_features")
        evidence.extend([field for key, field in lowered.items() if key in {"ndvi", "evi", "lst", "dem"}])
    return {
        "basis": "metadata_only",
        "roles": list(dict.fromkeys(roles)),
        "evidence": list(dict.fromkeys(evidence)),
    }


def _date_from_text(value: str) -> str:
    match = re.search(r"((?:19|20)\d{2})[_-]?(\d{2})[_-]?(\d{2})", str(value or ""))
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _raster_file_profile(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    try:
        import rasterio

        with rasterio.open(path) as src:
            band_count = int(src.count)
            temporal_bands = []
            dates = []
            for index, description in enumerate(src.descriptions or (), start=1):
                date_value = _date_from_text(str(description or ""))
                item = {"band": int(index), "description": str(description or ""), "date": date_value}
                if date_value:
                    dates.append(date_value)
                temporal_bands.append(item)
            payload: dict[str, Any] = {
                "width": int(src.width),
                "height": int(src.height),
                "band_count": band_count,
                "crs": str(src.crs) if src.crs else meta.get("crs"),
                "dtype": str(src.dtypes[0]) if src.dtypes else meta.get("dtype"),
                "nodata": src.nodata if src.nodata is not None else meta.get("nodata"),
            }
            if temporal_bands:
                payload["temporal_bands"] = temporal_bands
                payload["temporal_band_count"] = int(len([item for item in temporal_bands if item.get("date")]))
            if dates:
                payload["time_range"] = {"field": "raster_band_description", "start": min(dates), "end": max(dates)}
            return payload
    except Exception:
        return {}


def _profile_table(record: Any) -> dict[str, Any]:
    df = record.object_ref
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    fields = [str(col) for col in df.columns]
    sample = df.head(3).where(pd.notna(df.head(3)), None).to_dict(orient="records")
    return {
        "row_count": int(len(df)),
        "fields": fields,
        "field_types": {str(col): str(dtype) for col, dtype in df.dtypes.items()},
        "numeric_fields": [str(col) for col in df.select_dtypes(include="number").columns],
        "sample_rows": [{key: _jsonable(value) for key, value in row.items()} for row in sample],
        "time_range": _time_range(df),
        "role_inference": _role_inference_from_fields(fields),
        "modeling_profile": build_modeling_profile(df, dataset_name=str(getattr(record, "name", "")), data_type="table"),
    }


def _profile_vector(record: Any) -> dict[str, Any]:
    gdf = record.object_ref
    fields = [str(col) for col in getattr(gdf, "columns", [])]
    meta = dict(getattr(record, "meta", {}) or {})
    return {
        "feature_count": int(meta.get("rows") or len(gdf) if hasattr(gdf, "__len__") else 0),
        "fields": fields or [str(col) for col in meta.get("columns", [])],
        "geometry_types": meta.get("geometry_types") or [],
        "crs": meta.get("crs"),
        "bounds": meta.get("bounds"),
        "role_inference": _role_inference_from_fields(fields),
        "modeling_profile": build_modeling_profile(pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore")), dataset_name=str(getattr(record, "name", "")), data_type="vector"),
    }


def _profile_raster(record: Any) -> dict[str, Any]:
    meta = dict(getattr(record, "meta", {}) or {})
    file_profile = _raster_file_profile(Path(str(getattr(record, "path", ""))), meta)
    meta = {**meta, **{key: value for key, value in file_profile.items() if key not in {"time_range", "temporal_bands", "temporal_band_count"}}}
    width = meta.get("width")
    height = meta.get("height")
    bounds = meta.get("bounds")
    resolution = None
    if bounds and width and height:
        try:
            left, bottom, right, top = [float(v) for v in bounds]
            resolution = [abs((right - left) / float(width)), abs((top - bottom) / float(height))]
        except Exception:
            resolution = None
    profile = {
        "width": width,
        "height": height,
        "band_count": meta.get("count"),
        "crs": meta.get("crs"),
        "bounds": bounds,
        "resolution": resolution,
        "dtype": meta.get("dtype"),
        "nodata": meta.get("nodata"),
        "role_inference": {"basis": "metadata_only", "roles": ["raster"], "evidence": ["raster_metadata"]},
    }
    if "band_count" in file_profile:
        profile["band_count"] = file_profile["band_count"]
    if "time_range" in file_profile:
        profile["time_range"] = file_profile["time_range"]
    if "temporal_bands" in file_profile:
        profile["temporal_bands"] = file_profile["temporal_bands"]
        profile["temporal_band_count"] = file_profile.get("temporal_band_count", 0)
    return profile


def _profile_archive(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            members = [
                {"name": item.filename, "size": item.file_size}
                for item in zf.infolist()[:50]
                if not item.is_dir()
            ]
    except Exception:
        members = []
    return {
        "archive_members": members,
        "role_inference": {"basis": "metadata_only", "roles": ["archive"], "evidence": [item["name"] for item in members[:10]]},
    }


def profile_dataset(manager: Any, dataset_name: str) -> dict[str, Any]:
    record = manager.get(dataset_name)
    path = Path(str(record.path))
    stat_payload = _safe_stat(path)
    cache = _profile_cache(manager)
    cache_key = _profile_cache_key(record, path, stat_payload)
    if cache:
        cached = cache.get(
            user_id=str(getattr(manager, "current_user_id", "") or ""),
            session_id=str(getattr(manager, "current_session_id", "") or ""),
            namespace="dataset_profile",
            key_parts=cache_key,
        )
        if cached:
            return cached
    profile: dict[str, Any] = {
        "name": record.name,
        "data_type": record.data_type,
        "path": str(record.path),
        **stat_payload,
    }
    data_type = str(record.data_type or "").lower()
    if data_type == "table":
        profile.update(_profile_table(record))
    elif data_type == "vector":
        profile.update(_profile_vector(record))
    elif data_type == "raster":
        profile.update(_profile_raster(record))
    elif path.suffix.lower() == ".zip":
        profile.update(_profile_archive(path))
    else:
        profile.setdefault("role_inference", {"basis": "metadata_only", "roles": [], "evidence": []})
    if cache:
        cache.set(
            user_id=str(getattr(manager, "current_user_id", "") or ""),
            session_id=str(getattr(manager, "current_session_id", "") or ""),
            namespace="dataset_profile",
            key_parts=cache_key,
            value=profile,
            ttl_seconds=600,
        )
    return profile
