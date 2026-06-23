from __future__ import annotations

from typing import Any

import pandas as pd


_ID_TOKENS = ("id", "uuid", "code", "name")
_TARGET_TOKENS = ("target", "label", "yield", "cover", "class", "score", "value", "soil_moisture")
_TIME_TOKENS = ("date", "time", "day", "month", "year")
_LON_NAMES = {"lon", "lng", "longitude", "x"}
_LAT_NAMES = {"lat", "latitude", "y"}


def _jsonable_number(value: Any) -> float | int | None:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (int, float)):
        return value
    return None


def _field_summary(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = max(1, int(len(df)))
    for col in df.columns:
        series = df[col]
        item: dict[str, Any] = {
            "name": str(col),
            "dtype": str(series.dtype),
            "missing_rate": float(series.isna().sum() / total),
            "unique_count": int(series.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(series):
            stats = series.describe()
            item["stats"] = {
                "min": _jsonable_number(stats.get("min")),
                "max": _jsonable_number(stats.get("max")),
                "mean": _jsonable_number(stats.get("mean")),
                "std": _jsonable_number(stats.get("std")),
            }
        rows.append(item)
    return rows


def _coordinate_fields(fields: list[str]) -> tuple[str, str]:
    lowered = {field.lower(): field for field in fields}
    lon = next((lowered[name] for name in _LON_NAMES if name in lowered), "")
    lat = next((lowered[name] for name in _LAT_NAMES if name in lowered), "")
    return lon, lat


def _time_field(df: pd.DataFrame) -> str:
    for col in df.columns:
        lowered = str(col).lower()
        if not any(token in lowered for token in _TIME_TOKENS):
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        if parsed.notna().sum() >= max(2, int(len(df) * 0.5)):
            return str(col)
    return ""


def _target_candidates(df: pd.DataFrame) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    total = max(1, int(len(df)))
    for col in df.columns:
        name = str(col)
        lowered = name.lower()
        if lowered in _LON_NAMES or lowered in _LAT_NAMES or any(token == lowered or lowered.endswith(f"_{token}") for token in _ID_TOKENS):
            continue
        unique_count = int(df[col].nunique(dropna=True))
        missing_rate = float(df[col].isna().sum() / total)
        if missing_rate > 0.5 or unique_count <= 1:
            continue
        score = 0.0
        if pd.api.types.is_numeric_dtype(df[col]):
            score += 0.45
        if any(token in lowered for token in _TARGET_TOKENS):
            score += 0.5
        if unique_count <= 20 and not pd.api.types.is_float_dtype(df[col]):
            score += 0.2
        if score > 0:
            task_hint = "classification" if unique_count <= 20 and not pd.api.types.is_float_dtype(df[col]) else "regression"
            candidates.append({"field": name, "score": round(score, 3), "task_hint": task_hint, "unique_count": unique_count})
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _feature_candidates(df: pd.DataFrame, target_fields: set[str]) -> list[str]:
    features: list[str] = []
    for col in df.columns:
        name = str(col)
        lowered = name.lower()
        if name in target_fields:
            continue
        if any(token == lowered or lowered.endswith(f"_{token}") for token in _ID_TOKENS):
            continue
        if (
            pd.api.types.is_numeric_dtype(df[col])
            or pd.api.types.is_bool_dtype(df[col])
            or pd.api.types.is_object_dtype(df[col])
            or isinstance(df[col].dtype, pd.CategoricalDtype)
        ):
            features.append(name)
    return features


def build_modeling_profile(df: pd.DataFrame, *, dataset_name: str = "", data_type: str = "") -> dict[str, Any]:
    """Build a desensitized modeling profile for local rules or an LLM advisor.

    The profile intentionally excludes raw rows, raw coordinates, filesystem paths,
    and artifact identifiers. It is safe to pass to a model advisor after API-key
    and policy checks.
    """

    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    fields = [str(col) for col in df.columns]
    lon_col, lat_col = _coordinate_fields(fields)
    time_col = _time_field(df)
    target_candidates = _target_candidates(df)
    target_fields = {str(target_candidates[0]["field"])} if target_candidates else set()
    return {
        "dataset_name": str(dataset_name or ""),
        "data_type": str(data_type or ""),
        "sample_count": int(len(df)),
        "field_count": int(len(fields)),
        "fields": _field_summary(df),
        "target_candidates": target_candidates,
        "feature_candidates": _feature_candidates(df, target_fields),
        "spatial": {
            "is_spatial": bool(lon_col and lat_col) or str(data_type or "").lower() == "vector",
            "lon_col": lon_col,
            "lat_col": lat_col,
            "has_geometry": str(data_type or "").lower() == "vector",
        },
        "temporal": {
            "is_temporal": bool(time_col),
            "time_col": time_col,
        },
        "contains_raw_rows": False,
        "privacy": {
            "raw_rows_included": False,
            "raw_coordinates_included": False,
            "paths_included": False,
        },
    }
