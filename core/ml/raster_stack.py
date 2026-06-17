from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from core.data_manager import DataManager


@dataclass
class RasterStack:
    feature_names: list[str]
    stack: np.ndarray
    valid_mask: np.ndarray
    profile: dict[str, Any]
    transform: Any
    crs: Any
    target: np.ndarray | None = None


def _resampling(value: str) -> Resampling:
    return {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
        "average": Resampling.average,
    }.get(str(value or "").lower(), Resampling.bilinear)


def _read_aligned(path: Path, reference: rasterio.io.DatasetReader, *, resampling: Resampling) -> tuple[np.ndarray, np.ndarray]:
    with rasterio.open(path) as src:
        destination = np.full((reference.height, reference.width), np.nan, dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=reference.transform,
            dst_crs=reference.crs,
            dst_nodata=np.nan,
            resampling=resampling,
        )
        valid = np.isfinite(destination)
        if src.nodata is not None:
            valid &= ~np.isclose(destination, float(src.nodata))
        return destination, valid


def build_raster_stack(
    manager: DataManager,
    raster_names: list[str],
    *,
    target_raster_name: str = "",
    raster_resampling: str = "bilinear",
    max_prediction_pixels: int = 5_000_000,
) -> RasterStack:
    if not raster_names:
        raise ValueError("At least one feature raster is required")
    reference_name = target_raster_name or raster_names[0]
    reference_path = manager.get_raster_path(reference_name)
    with rasterio.open(reference_path) as reference:
        total_pixels = int(reference.width * reference.height)
        if max_prediction_pixels > 0 and total_pixels > max_prediction_pixels:
            raise RuntimeError(f"RASTER_TOO_LARGE:{total_pixels}:{max_prediction_pixels}")
        arrays: list[np.ndarray] = []
        masks: list[np.ndarray] = []
        names: list[str] = []
        for raster_name in raster_names:
            arr, valid = _read_aligned(manager.get_raster_path(raster_name), reference, resampling=_resampling(raster_resampling))
            arrays.append(arr)
            masks.append(valid)
            names.append(raster_name)
        target_arr: np.ndarray | None = None
        if target_raster_name:
            target_arr, target_valid = _read_aligned(manager.get_raster_path(target_raster_name), reference, resampling=Resampling.nearest)
            masks.append(target_valid)
        valid_mask = np.logical_and.reduce(masks) if masks else np.zeros((reference.height, reference.width), dtype=bool)
        profile = dict(reference.profile)
        profile.update(driver="GTiff", count=1, dtype="float32", nodata=-9999.0, compress="deflate")
        return RasterStack(
            feature_names=names,
            stack=np.stack(arrays, axis=0).astype("float32"),
            valid_mask=valid_mask,
            profile=profile,
            transform=reference.transform,
            crs=reference.crs,
            target=target_arr.astype("float32") if target_arr is not None else None,
        )


def stack_training_frame(stack: RasterStack, *, max_training_samples: int = 200_000, random_state: int = 42) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if stack.target is None:
        raise ValueError("Target raster is required for raster stack training")
    rows, cols = np.where(stack.valid_mask)
    if rows.size == 0:
        raise ValueError("No valid aligned pixels are available for training")
    x = stack.stack[:, rows, cols].T
    y = stack.target[rows, cols]
    valid = np.isfinite(x).all(axis=1) & np.isfinite(y)
    x = x[valid]
    y = y[valid]
    diagnostics: dict[str, Any] = {"valid_pixels": int(len(y)), "sampled": False}
    if len(y) > max_training_samples:
        rng = np.random.default_rng(random_state)
        idx = rng.choice(len(y), size=max_training_samples, replace=False)
        x = x[idx]
        y = y[idx]
        diagnostics.update({"sampled": True, "sample_size": int(max_training_samples), "available_samples": int(len(valid))})
    return x, y, diagnostics


def write_prediction_raster(path: Path, stack: RasterStack, prediction: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = np.full(stack.valid_mask.shape, -9999.0, dtype="float32")
    rows, cols = np.where(stack.valid_mask)
    out[rows, cols] = prediction.astype("float32")
    with rasterio.open(path, "w", **stack.profile) as dst:
        dst.write(out, 1)
    return path
