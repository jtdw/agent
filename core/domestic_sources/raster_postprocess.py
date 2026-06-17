from __future__ import annotations

import contextlib
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.mask import mask
from rasterio.merge import merge as raster_merge
from rasterio.vrt import WarpedVRT

from ..archive_utils import safe_extract_zip
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
    crs_mismatch = any(item["crs"] != first["crs"] for item in metas[1:])
    for item in metas[1:]:
        keys = ("count", "dtype") if crs_mismatch else ("crs", "count", "dtype", "xres", "yres")
        for key in keys:
            if item[key] != first[key]:
                return False, f"incompatible_{key}", {"rasters": metas}

    total_area = sum(float(item["area"]) for item in metas)
    overlap_area = 0.0
    if not crs_mismatch:
        for index, left in enumerate(metas):
            for right in metas[index + 1 :]:
                overlap_area += _intersection_area(left["bounds"], right["bounds"])
    overlap_ratio = overlap_area / total_area if total_area > 0 else 0.0
    if overlap_ratio > 0.20:
        return False, "overlapping_rasters", {"overlap_ratio": round(overlap_ratio, 6), "rasters": metas}
    diagnostics = {"overlap_ratio": round(overlap_ratio, 6), "rasters": metas}
    if crs_mismatch:
        diagnostics["reprojected_to_crs"] = first["crs"]
    return True, "", diagnostics


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


def _map_layer_id(dataset_name: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_]+", "_", str(dataset_name or "").strip()).strip("_").lower()
    return f"dataset_{clean or 'layer'}"


def _download_raster_meta(meta: dict[str, Any], dataset_name: str) -> dict[str, Any]:
    enriched = dict(meta)
    enriched.update(
        {
            "map_ready": True,
            "map_layer_id": _map_layer_id(dataset_name),
            "layer_kind": enriched.get("layer_kind") or "dem",
            "source_tool": enriched.get("source_tool") or "download_postprocess",
        }
    )
    return enriched


def _mark_dataset_map_ready(manager: DataManager, dataset_name: str) -> None:
    try:
        record = manager.get(dataset_name)
        record.meta = _download_raster_meta(record.meta or {}, dataset_name)
        manager._sync_dataset_to_database(dataset_name, auto_synced=True)
    except Exception:
        pass


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
        raw_sources = [stack.enter_context(rasterio.open(manager.get_raster_path(name))) for name in raster_names]
        reference = raw_sources[0]
        reference_dtype = reference.dtypes[0]
        nodata = reference.nodata if reference.nodata is not None else _default_nodata_for_dtype(reference_dtype)
        sources = [reference]
        for source in raw_sources[1:]:
            if source.crs != reference.crs:
                sources.append(stack.enter_context(WarpedVRT(source, crs=reference.crs, nodata=nodata, src_nodata=source.nodata)))
            else:
                sources.append(source)
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
        meta=_download_raster_meta({
            "crs": str(profile.get("crs")) if profile.get("crs") else None,
            "width": int(profile.get("width") or 0),
            "height": int(profile.get("height") or 0),
            "count": int(profile.get("count") or 0),
            "dtype": str(profile.get("dtype") or reference_dtype),
            "nodata": profile.get("nodata"),
            "source_rasters": raster_names,
            "clip_vector": clip_vector,
        }, output_stem),
    )
    _mark_dataset_map_ready(manager, stored_name)
    return stored_name, str(output_path)


def _package_final_raster(manager: DataManager, raster_path: str, output_name: str) -> str:
    source = Path(raster_path)
    if not source.exists() or not source.is_file():
        return ""
    package_stem = _safe_stem(Path(output_name or source.stem).stem)
    package_path = manager.derived_dir / f"{package_stem}.zip"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, source.name)
        for sidecar in source.parent.glob(f"{source.stem}.*"):
            if sidecar.resolve() == source.resolve() or sidecar.resolve() == package_path.resolve():
                continue
            archive.write(sidecar, sidecar.name)
    return str(package_path)


RASTER_FILE_EXTS = {".tif", ".tiff", ".img"}


def _extract_zip_rasters(manager: DataManager, path: Path, paths: list[Path], *, depth: int = 0) -> None:
    if depth > 2 or not zipfile.is_zipfile(path):
        return
    stem = _safe_stem(path.stem)
    target = manager.derived_dir / "download_postprocess_extracts" / stem
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "r") as archive:
        safe_extract_zip(archive, target)
    for candidate in sorted(target.rglob("*")):
        if not candidate.is_file():
            continue
        suffix = candidate.suffix.lower()
        if suffix in RASTER_FILE_EXTS:
            resolved = candidate.resolve()
            if resolved not in paths and not any(existing.name.lower() == resolved.name.lower() for existing in paths):
                paths.append(resolved)
        elif suffix == ".zip":
            _extract_zip_rasters(manager, candidate, paths, depth=depth + 1)


def _candidate_download_paths(manager: DataManager, result: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []

    def add(value: Any) -> None:
        if not value:
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                add(item)
            return
        path = Path(str(value))
        if not path.exists() or not path.is_file():
            return
        suffix = path.suffix.lower()
        if suffix in RASTER_FILE_EXTS:
            resolved = path.resolve()
            if resolved not in paths and not any(existing.name.lower() == resolved.name.lower() for existing in paths):
                paths.append(resolved)
        elif suffix == ".zip":
            _extract_zip_rasters(manager, path, paths)

    for key in ("final_output_path", "output_path", "path", "downloaded_path", "downloads", "zip_path", "package_path"):
        add(result.get(key))
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    for item in meta.get("items") or []:
        if isinstance(item, dict):
            add(item.get("candidate"))
            add(item.get("file"))
    return paths


def _ensure_raster_datasets_from_paths(manager: DataManager, result: dict[str, Any], *, output_name: str) -> list[str]:
    names = _result_dataset_names(result)
    known = set(names)
    known_paths: dict[Path, str] = {}
    for name in names:
        try:
            record = manager.get(name)
            if record.data_type == "raster":
                known_paths[Path(manager.get_raster_path(name)).resolve()] = name
        except Exception:
            continue
    stem = _safe_stem(Path(output_name or "downloaded_raster").stem)
    for index, path in enumerate(_candidate_download_paths(manager, result), start=1):
        existing_name = known_paths.get(path.resolve())
        if existing_name:
            if existing_name not in known:
                known.add(existing_name)
                names.append(existing_name)
            _mark_dataset_map_ready(manager, existing_name)
            continue
        try:
            dataset_name = manager.load_path(str(path), name=f"{stem}_{index:03d}")
        except Exception:
            continue
        if dataset_name not in known:
            known.add(dataset_name)
            names.append(dataset_name)
        known_paths[path.resolve()] = dataset_name
        _mark_dataset_map_ready(manager, dataset_name)
    if names:
        result["dataset_names"] = names
        result.setdefault("dataset_name", names[0])
    return names


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
    if isinstance(existing, dict) and existing.get("action") in {"mosaicked", "mosaicked_and_clipped", "single_raster", "skipped", "failed"}:
        return result

    dataset_names = _ensure_raster_datasets_from_paths(manager, result, output_name=output_name)
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
        package_path = _package_final_raster(manager, path, output_name)
        if package_path:
            result["zip_path"] = package_path
            result["package_path"] = package_path
        _mark_dataset_map_ready(manager, name)
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
    package_path = _package_final_raster(manager, final_path, output_stem)
    if package_path:
        result["zip_path"] = package_path
        result["package_path"] = package_path
    result["raster_standardization"] = {
        "action": "mosaicked_and_clipped" if clip_name else "mosaicked",
        "source_datasets": raster_names,
        "input_raster_count": len(raster_names),
        "clip_vector": clip_name,
        "diagnostics": diagnostics,
    }
    return result
