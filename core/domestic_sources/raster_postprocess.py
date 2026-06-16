from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.mask import mask
from rasterio.merge import merge as raster_merge

from ..data_manager import DataManager


def _result_dataset_names(result: dict[str, Any]) -> list[str]:
    names = [str(name).strip() for name in result.get("dataset_names") or [] if str(name or "").strip()]
    dataset_name = str(result.get("dataset_name") or "").strip()
    if dataset_name and dataset_name not in names:
        names.insert(0, dataset_name)
    return names


def _raster_dataset_names(manager: DataManager, names: list[str]) -> list[str]:
    rasters: list[str] = []
    for name in names:
        try:
            record = manager.get(name)
        except Exception:
            continue
        if record.data_type == "raster":
            rasters.append(name)
    return rasters


def _bounds_area(bounds: Any) -> float:
    return max(0.0, float(bounds.right) - float(bounds.left)) * max(0.0, float(bounds.top) - float(bounds.bottom))


def _intersection_area(left: Any, right: Any) -> float:
    minx = max(float(left.left), float(right.left))
    maxx = min(float(left.right), float(right.right))
    miny = max(float(left.bottom), float(right.bottom))
    maxy = min(float(left.top), float(right.top))
    return max(0.0, maxx - minx) * max(0.0, maxy - miny)


def _compatible_raster_group(manager: DataManager, raster_names: list[str]) -> tuple[bool, str, dict[str, Any]]:
    metas: list[dict[str, Any]] = []
    for name in raster_names:
        with rasterio.open(manager.get_raster_path(name)) as src:
            metas.append(
                {
                    "name": name,
                    "crs": str(src.crs) if src.crs else "",
                    "count": int(src.count),
                    "dtype": str(src.dtypes[0]) if src.dtypes else "",
                    "xres": round(abs(float(src.transform.a)), 12),
                    "yres": round(abs(float(src.transform.e)), 12),
                    "bounds": src.bounds,
                    "area": _bounds_area(src.bounds),
                }
            )
    if not metas:
        return False, "no_raster_metadata", {}

    first = metas[0]
    for item in metas[1:]:
        for key in ("crs", "count", "dtype", "xres", "yres"):
            if item[key] != first[key]:
                return False, f"incompatible_{key}", {"rasters": metas}

    total_area = sum(float(item["area"]) for item in metas)
    overlap_area = 0.0
    for index, left in enumerate(metas):
        for right in metas[index + 1 :]:
            overlap_area += _intersection_area(left["bounds"], right["bounds"])
    overlap_ratio = overlap_area / total_area if total_area > 0 else 0.0
    if overlap_ratio > 0.20:
        return False, "overlapping_rasters", {"overlap_ratio": round(overlap_ratio, 6), "rasters": metas}
    return True, "", {"overlap_ratio": round(overlap_ratio, 6), "rasters": metas}


def _existing_clip_vector(manager: DataManager, clip_vector: str) -> str:
    name = str(clip_vector or "").strip()
    if not name:
        return ""
    try:
        record = manager.get(name)
    except Exception:
        return ""
    return name if record.data_type == "vector" else ""


def _safe_stem(value: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", str(value or "").strip()).strip("._-")
    return clean or "downloaded_raster"


def _default_nodata_for_dtype(dtype: str) -> float | int:
    raster_dtype = np.dtype(dtype)
    if np.issubdtype(raster_dtype, np.floating):
        return np.nan
    if np.issubdtype(raster_dtype, np.unsignedinteger):
        return 0
    return -9999


def _write_mosaic(
    manager: DataManager,
    raster_names: list[str],
    *,
    output_name: str,
    clip_vector: str = "",
) -> tuple[str, str]:
    output_stem = _safe_stem(Path(output_name or "downloaded_raster").stem)
    output_path = manager.derived_dir / f"{output_stem}.tif"
    with contextlib.ExitStack() as stack:
        sources = [stack.enter_context(rasterio.open(manager.get_raster_path(name))) for name in raster_names]
        reference = sources[0]
        reference_dtype = reference.dtypes[0]
        nodata = reference.nodata if reference.nodata is not None else _default_nodata_for_dtype(reference_dtype)
        mosaic, mosaic_transform = raster_merge(sources, nodata=nodata, method="first")
        profile = reference.profile.copy()
        profile.update(
            height=int(mosaic.shape[1]),
            width=int(mosaic.shape[2]),
            count=int(mosaic.shape[0]),
            transform=mosaic_transform,
            nodata=nodata,
            dtype=str(reference_dtype),
        )
        output_data = mosaic
        if clip_vector:
            gdf = manager.get_vector(clip_vector)
            if gdf.crs and reference.crs and gdf.crs != reference.crs:
                gdf = gdf.to_crs(reference.crs)
            geoms = [geom.__geo_interface__ for geom in gdf.geometry if geom is not None and not geom.is_empty]
            if not geoms:
                raise ValueError(f"Clip vector {clip_vector} has no usable geometry.")
            with MemoryFile() as memfile:
                with memfile.open(**profile) as dataset:
                    dataset.write(mosaic)
                    output_data, clipped_transform = mask(dataset, geoms, crop=True, nodata=nodata)
            profile.update(height=int(output_data.shape[1]), width=int(output_data.shape[2]), transform=clipped_transform)

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(output_data.astype(reference_dtype, copy=False))

    stored_name = manager.put_raster_path(
        output_stem,
        output_path,
        meta={
            "crs": str(profile.get("crs")) if profile.get("crs") else None,
            "width": int(profile.get("width") or 0),
            "height": int(profile.get("height") or 0),
            "count": int(profile.get("count") or 0),
            "dtype": str(profile.get("dtype") or reference_dtype),
            "nodata": profile.get("nodata"),
            "source_rasters": raster_names,
            "clip_vector": clip_vector,
        },
    )
    return stored_name, str(output_path)


def standardize_raster_download_result(
    manager: DataManager,
    result: dict[str, Any],
    *,
    output_name: str,
    clip_vector: str = "",
    fail_on_mosaic_error: bool = False,
) -> dict[str, Any]:
    """Promote downloaded raster tiles to a final mosaic when they are clearly tile parts.

    This function is intentionally conservative: adjacent compatible rasters are
    mosaicked, but strongly overlapping rasters are treated as separate scenes or
    time steps and left unchanged.
    """

    existing = result.get("raster_standardization")
    if isinstance(existing, dict) and existing.get("action") in {"mosaicked", "single_raster", "skipped", "failed"}:
        return result

    dataset_names = _result_dataset_names(result)
    if dataset_names and not result.get("dataset_names"):
        result["dataset_names"] = dataset_names
    raster_names = _raster_dataset_names(manager, dataset_names)
    if not raster_names:
        result["raster_standardization"] = {"action": "skipped", "reason": "no_raster_datasets"}
        return result
    if len(raster_names) == 1:
        name = raster_names[0]
        path = str(manager.get_raster_path(name))
        result.setdefault("dataset_name", name)
        result.setdefault("path", path)
        result.setdefault("output_path", path)
        result["final_dataset_name"] = name
        result["final_output_path"] = path
        result["raster_standardization"] = {"action": "single_raster", "dataset_name": name, "path": path}
        return result

    compatible, reason, diagnostics = _compatible_raster_group(manager, raster_names)
    if not compatible:
        result.setdefault("dataset_name", raster_names[0])
        result["raster_standardization"] = {"action": "skipped", "reason": reason, "diagnostics": diagnostics}
        return result

    output_stem = Path(output_name or "downloaded_raster").stem
    clip_name = _existing_clip_vector(manager, clip_vector)
    try:
        final_dataset, final_path = _write_mosaic(
            manager,
            raster_names,
            output_name=f"{output_stem}_mosaic",
            clip_vector=clip_name,
        )
    except Exception as exc:
        message = str(exc)
        if fail_on_mosaic_error:
            raise RuntimeError(message)
        result["mosaic_error"] = message
        result["raster_standardization"] = {"action": "failed", "reason": "mosaic_failed", "diagnostics": diagnostics}
        return result

    result["mosaic_dataset_name"] = final_dataset
    result["mosaic_path"] = final_path
    result["dataset_name"] = final_dataset
    result["final_dataset_name"] = final_dataset
    result["path"] = final_path
    result["output_path"] = final_path
    result["final_output_path"] = final_path
    result["raster_standardization"] = {
        "action": "mosaicked",
        "source_datasets": raster_names,
        "clip_vector": clip_name,
        "diagnostics": diagnostics,
    }
    return result
