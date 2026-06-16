from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask
from shapely.geometry import Point

from core.data_manager import DataManager


def parse_name_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def raster_feature_name(dataset_name: str, suffix: str = "") -> str:
    clean = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(dataset_name or "raster")).strip("_")
    return f"{clean}_{suffix}" if suffix else clean or "raster"


def samples_as_geodataframe(
    manager: DataManager,
    dataset_name: str,
    *,
    x_col: str = "",
    y_col: str = "",
) -> gpd.GeoDataFrame:
    record = manager.get(dataset_name)
    if record.data_type == "vector":
        return manager.get_vector(dataset_name)
    if record.data_type != "table":
        raise TypeError(f"{dataset_name} must be a table or vector sample dataset")
    df = manager.get_table(dataset_name)
    x_name = x_col or next((c for c in df.columns if str(c).lower() in {"lon", "lng", "long", "longitude", "x"}), "")
    y_name = y_col or next((c for c in df.columns if str(c).lower() in {"lat", "latitude", "y"}), "")
    if not x_name or not y_name:
        raise ValueError("Point samples need lon/lat columns or vector geometry")
    geometry = [Point(float(x), float(y)) if pd.notna(x) and pd.notna(y) else None for x, y in zip(df[x_name], df[y_name])]
    return gpd.GeoDataFrame(df.copy(), geometry=geometry, crs="EPSG:4326")


def _point_values(gdf: gpd.GeoDataFrame, raster_path: Path) -> list[float | None]:
    with rasterio.open(raster_path) as src:
        work = gdf
        if work.crs and src.crs and str(work.crs) != str(src.crs):
            work = work.to_crs(src.crs)
        coords = [(geom.x, geom.y) if geom is not None and not geom.is_empty else (np.nan, np.nan) for geom in work.geometry]
        values: list[float | None] = []
        for sample in src.sample(coords, masked=True):
            value = sample[0]
            if np.ma.is_masked(value):
                values.append(None)
            else:
                raw = float(value)
                values.append(None if src.nodata is not None and np.isclose(raw, src.nodata) else raw)
        return values


def _mode(values: np.ndarray) -> float | None:
    flat = values[np.isfinite(values)]
    if flat.size == 0:
        return None
    counts = Counter(flat.tolist())
    return float(counts.most_common(1)[0][0])


def _polygon_stats(gdf: gpd.GeoDataFrame, raster_path: Path, base_name: str) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, float | None]] = []
    with rasterio.open(raster_path) as src:
        work = gdf
        if work.crs and src.crs and str(work.crs) != str(src.crs):
            work = work.to_crs(src.crs)
        for geom in work.geometry:
            if geom is None or geom.is_empty:
                rows.append({})
                continue
            try:
                arr, _ = mask(src, [geom], crop=True, filled=False)
            except ValueError:
                rows.append({})
                continue
            band = np.ma.asarray(arr[0]).astype("float64")
            data = np.asarray(band.filled(np.nan), dtype="float64")
            if src.nodata is not None:
                data = np.where(np.isclose(data, src.nodata), np.nan, data)
            valid = data[np.isfinite(data)]
            if valid.size == 0:
                rows.append({})
            else:
                rows.append(
                    {
                        f"{base_name}_mean": float(np.nanmean(valid)),
                        f"{base_name}_median": float(np.nanmedian(valid)),
                        f"{base_name}_mode": _mode(valid),
                    }
                )
    columns = [f"{base_name}_mean", f"{base_name}_median", f"{base_name}_mode"]
    return pd.DataFrame(rows, columns=columns), columns


def extract_raster_features(
    manager: DataManager,
    sample_dataset_name: str,
    raster_names: list[str],
    *,
    x_col: str = "",
    y_col: str = "",
) -> tuple[gpd.GeoDataFrame, list[str], dict[str, Any]]:
    gdf = samples_as_geodataframe(manager, sample_dataset_name, x_col=x_col, y_col=y_col)
    result = gdf.copy()
    feature_cols: list[str] = []
    stats: dict[str, Any] = {"raster_features": []}
    geom_types = set(str(v) for v in result.geometry.geom_type.dropna().unique())
    point_like = geom_types.issubset({"Point", "MultiPoint"})
    for raster_name in raster_names:
        path = manager.get_raster_path(raster_name)
        base = raster_feature_name(raster_name)
        if point_like:
            col = base
            result[col] = _point_values(result, path)
            feature_cols.append(col)
            stats["raster_features"].append({"raster": raster_name, "columns": [col], "method": "point_sample"})
        else:
            stat_df, cols = _polygon_stats(result, path, base)
            for col in cols:
                result[col] = stat_df[col].values
            feature_cols.extend(cols)
            stats["raster_features"].append({"raster": raster_name, "columns": cols, "method": "zonal_mean_median_mode"})
    return result, feature_cols, stats
