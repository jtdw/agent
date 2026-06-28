from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import geopandas as gpd
import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import reproject

from core.data_manager import DataManager
from core.tool_contracts import ToolResult, tool_result_error, tool_result_ok


SENSITIVE_TOKENS = {".env", "secret", "secrets", "cookies", "storage_state", "workspace.db", "commercial_secret"}
AUTO_FEATURES = {"lon", "lat", "day_of_year", "month", "year"}


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", str(value or "").strip()).strip("._-")
    return clean or f"raster_prediction_{uuid4().hex[:8]}"


def _map_layer_id(dataset_name: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_]+", "_", str(dataset_name or "").strip()).strip("_").lower()
    return f"dataset_{clean or 'layer'}"


def _artifact(path: Path, type_: str, title: str, *, dataset_name: str = "", meta: dict[str, Any] | None = None) -> dict[str, Any]:
    merged_meta = dict(meta or {})
    if dataset_name:
        merged_meta.update({"dataset_name": dataset_name, "map_ready": type_ == "raster", "map_layer_id": _map_layer_id(dataset_name)})
    return {
        "artifact_id": f"artifact_{uuid4().hex[:10]}",
        "path": str(path),
        "type": type_,
        "title": title,
        "quality_status": "generated",
        "preview_available": type_ in {"raster", "png", "summary"},
        "mime_type": {"raster": "image/tiff", "png": "image/png", "summary": "application/json"}.get(type_, "application/octet-stream"),
        "source_tool": "predict_xgboost_raster_map",
        "meta": merged_meta,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    return value


def _blocked_sensitive(inputs: dict[str, Any]) -> str:
    for key, value in inputs.items():
        text = str(value or "").lower()
        if any(token in text for token in SENSITIVE_TOKENS):
            return key
    return ""


def _parse_feature_rasters(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in re.split(r"[,;\n]+", str(value or "")):
        token = item.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"feature raster mapping must use feature=dataset: {token}")
        feature, dataset = [part.strip() for part in token.split("=", 1)]
        if not feature or not dataset:
            raise ValueError(f"feature raster mapping is incomplete: {token}")
        result[feature] = dataset
    return result


def _resolve_model_path(manager: DataManager, model_path: str) -> Path:
    if not str(model_path or "").strip():
        raise ValueError("model_path is required")
    raw = Path(str(model_path).strip())
    candidate = raw if raw.is_absolute() else manager.workdir / raw
    resolved = candidate.resolve(strict=False)
    workdir = manager.workdir.resolve()
    if not (resolved == workdir or resolved.is_relative_to(workdir)):
        raise PermissionError("model_path must be inside the current workspace")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"model file not found: {resolved}")
    return resolved


def _parse_representative_date(value: str) -> date:
    if not str(value or "").strip():
        return date.today()
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


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


def _load_boundary_mask(manager: DataManager, boundary_name: str, reference: rasterio.io.DatasetReader) -> np.ndarray:
    if not str(boundary_name or "").strip():
        return np.ones((reference.height, reference.width), dtype=bool)
    boundary = manager.get_vector(boundary_name).copy()
    if boundary.empty or "geometry" not in boundary:
        raise ValueError(f"boundary dataset has no usable geometry: {boundary_name}")
    if boundary.crs is None:
        raise ValueError(f"boundary dataset has no CRS: {boundary_name}")
    if reference.crs is None:
        raise ValueError("reference raster has no CRS")
    boundary = boundary.to_crs(reference.crs)
    return geometry_mask(
        list(boundary.geometry),
        out_shape=(reference.height, reference.width),
        transform=reference.transform,
        invert=True,
        all_touched=False,
    )


def _write_prediction_png(path: Path, prediction: np.ndarray, nodata: float, boundary: gpd.GeoDataFrame | None, profile: dict[str, Any], title: str) -> None:
    plot_arr = np.where(np.isclose(prediction, nodata), np.nan, prediction)
    transform = profile["transform"]
    width = int(profile["width"])
    height = int(profile["height"])
    extent = [transform.c, transform.c + width * transform.a, transform.f + height * transform.e, transform.f]
    fig, ax = plt.subplots(figsize=(8, 6), dpi=160)
    im = ax.imshow(plot_arr, extent=extent, origin="upper", cmap="viridis")
    if boundary is not None and not boundary.empty:
        boundary.boundary.plot(ax=ax, edgecolor="black", linewidth=0.8)
    ax.set_title(title)
    ax.set_xlabel(f"X ({profile.get('crs') or ''})")
    ax.set_ylabel(f"Y ({profile.get('crs') or ''})")
    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Predicted value")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def run_xgboost_raster_prediction(
    manager: DataManager,
    *,
    model_path: str,
    feature_rasters: str,
    output_name: str,
    boundary_name: str = "",
    target_raster_name: str = "",
    representative_date: str = "",
    max_prediction_pixels: int = 5_000_000,
    raster_resampling: str = "bilinear",
    chunk_size: int = 250_000,
) -> ToolResult:
    inputs = {
        "model_path": model_path,
        "feature_rasters": feature_rasters,
        "output_name": output_name,
        "boundary_name": boundary_name,
        "target_raster_name": target_raster_name,
        "representative_date": representative_date,
        "max_prediction_pixels": max_prediction_pixels,
        "raster_resampling": raster_resampling,
        "chunk_size": chunk_size,
    }
    blocked = _blocked_sensitive(inputs)
    if blocked:
        return tool_result_error(
            "predict_xgboost_raster_map",
            inputs=inputs,
            error_code="SENSITIVE_PATH_BLOCKED",
            error_title="Sensitive path blocked",
            user_message="输入包含敏感路径或文件名，已拒绝读取。",
            diagnostics={"blocked_input": blocked},
        )
    try:
        safe_output = _safe_name(output_name)
        model_file = _resolve_model_path(manager, model_path)
        feature_map = _parse_feature_rasters(feature_rasters)
        if not feature_map:
            raise ValueError("feature_rasters is required")
        bundle = joblib.load(model_file)
        pipeline = bundle.get("pipeline")
        model_features = [str(item) for item in bundle.get("features") or []]
        target = str(bundle.get("target") or "prediction")
        if pipeline is None or not callable(getattr(pipeline, "predict", None)):
            raise ValueError("model bundle must contain a pipeline with predict()")
        missing = [feature for feature in model_features if feature not in feature_map and feature not in AUTO_FEATURES]
        if missing:
            return tool_result_error(
                "predict_xgboost_raster_map",
                inputs=inputs,
                error_code="FEATURE_RASTER_MISSING",
                error_title="Feature rasters are incomplete",
                user_message="模型需要的部分特征没有对应的栅格输入。",
                diagnostics={"missing_features": missing, "model_features": model_features, "provided": sorted(feature_map)},
                next_actions=["用 feature_rasters 提供 feature=dataset 映射，例如 dem_elevation=dem。"],
            )

        rep_date = _parse_representative_date(representative_date)
        first_feature = next(feature for feature in model_features if feature in feature_map)
        reference_name = str(target_raster_name or "").strip() or feature_map[first_feature]
        reference_path = manager.get_raster_path(reference_name)
        arrays: dict[str, np.ndarray] = {}
        masks: list[np.ndarray] = []
        boundary_for_plot: gpd.GeoDataFrame | None = None
        with rasterio.open(reference_path) as reference:
            total_pixels = int(reference.width * reference.height)
            if max_prediction_pixels > 0 and total_pixels > int(max_prediction_pixels):
                return tool_result_error(
                    "predict_xgboost_raster_map",
                    inputs=inputs,
                    error_code="RASTER_TOO_LARGE",
                    error_title="Raster is too large",
                    user_message="参考栅格像元数超过 max_prediction_pixels 限制。",
                    diagnostics={"total_pixels": total_pixels, "max_prediction_pixels": int(max_prediction_pixels)},
                    next_actions=["提高 max_prediction_pixels，或先裁剪到研究区。"],
                )
            for feature, raster_name in feature_map.items():
                arr, valid = _read_aligned(manager.get_raster_path(raster_name), reference, resampling=_resampling(raster_resampling))
                arrays[feature] = arr
                masks.append(valid)
            boundary_mask = _load_boundary_mask(manager, boundary_name, reference)
            masks.append(boundary_mask)
            valid_mask = np.logical_and.reduce(masks)
            if not np.any(valid_mask):
                raise ValueError("no valid pixels are available for prediction")
            if boundary_name:
                boundary_for_plot = manager.get_vector(boundary_name).to_crs(reference.crs)
            profile = dict(reference.profile)
            profile.update(driver="GTiff", count=1, dtype="float32", nodata=-9999.0, compress="deflate")
            rows, cols = np.where(valid_mask)
            if reference.crs is None:
                raise ValueError("reference raster has no CRS")
            transformer = Transformer.from_crs(reference.crs, "EPSG:4326", always_xy=True)
            prediction = np.full(valid_mask.shape, -9999.0, dtype="float32")
            pred_parts: list[np.ndarray] = []
            for start in range(0, int(rows.size), max(1, int(chunk_size))):
                end = min(start + max(1, int(chunk_size)), int(rows.size))
                rr = rows[start:end]
                cc = cols[start:end]
                xs = reference.transform.c + (cc + 0.5) * reference.transform.a + (rr + 0.5) * reference.transform.b
                ys = reference.transform.f + (cc + 0.5) * reference.transform.d + (rr + 0.5) * reference.transform.e
                lon, lat = transformer.transform(xs, ys)
                frame_data: dict[str, Any] = {
                    feature: arrays[feature][rr, cc] for feature in model_features if feature in arrays
                }
                frame_data.update(
                    {
                        "lon": lon,
                        "lat": lat,
                        "day_of_year": np.full(end - start, rep_date.timetuple().tm_yday, dtype="int16"),
                        "month": np.full(end - start, rep_date.month, dtype="int8"),
                        "year": np.full(end - start, rep_date.year, dtype="int16"),
                    }
                )
                pred_frame = pd.DataFrame(frame_data)[model_features]
                pred = np.asarray(pipeline.predict(pred_frame), dtype="float32")
                prediction[rr, cc] = pred
                pred_parts.append(pred)

        values = np.concatenate(pred_parts)
        output_path = manager.derived_dir / f"{safe_output}.tif"
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(prediction, 1)
            dst.update_tags(
                source_tool="predict_xgboost_raster_map",
                model=str(model_file.name),
                target=target,
                representative_date=rep_date.isoformat(),
            )
        png_path = manager.plot_dir / f"{safe_output}.png"
        _write_prediction_png(png_path, prediction, -9999.0, boundary_for_plot, profile, f"{safe_output} XGBoost Raster Prediction")

        summary_payload = {
            "overall_ok": True,
            "output_tif": str(output_path),
            "output_png": str(png_path),
            "model_path": str(model_file),
            "target": target,
            "features": model_features,
            "feature_rasters": feature_map,
            "boundary_name": boundary_name,
            "target_raster_name": str(target_raster_name or "").strip(),
            "reference_raster": reference_name,
            "reference_source": "target_raster_name" if str(target_raster_name or "").strip() else "first_model_feature",
            "representative_date": rep_date.isoformat(),
            "crs": str(profile.get("crs") or ""),
            "width": int(profile["width"]),
            "height": int(profile["height"]),
            "valid_prediction_pixels": int(rows.size),
            "prediction_stats": {
                "min": float(np.nanmin(values)),
                "mean": float(np.nanmean(values)),
                "median": float(np.nanmedian(values)),
                "max": float(np.nanmax(values)),
            },
            "limitations": ["代表日期只进入时间特征；若 LST/NDVI 不是同日产品，输出应视为协变量快照预测图。"],
        }
        summary_path = manager.derived_dir / f"{safe_output}_summary.json"
        summary_path.write_text(json.dumps(_json_safe(summary_payload), ensure_ascii=False, indent=2), encoding="utf-8")
        dataset_name = manager.put_raster_path(
            safe_output,
            output_path,
            meta={
                "crs": str(profile.get("crs") or ""),
                "width": int(profile["width"]),
                "height": int(profile["height"]),
                "source_tool": "predict_xgboost_raster_map",
                "layer_kind": "prediction",
                "map_ready": True,
                "map_layer_id": _map_layer_id(safe_output),
                "target": target,
                "representative_date": rep_date.isoformat(),
                "target_raster_name": str(target_raster_name or "").strip(),
                "reference_raster": reference_name,
            },
        )
        artifacts = [
            _artifact(output_path, "raster", f"{safe_output}.tif", dataset_name=dataset_name, meta={"layer_kind": "prediction"}),
            _artifact(png_path, "png", f"{safe_output}.png"),
            _artifact(summary_path, "summary", f"{safe_output}_summary.json"),
        ]
        registered_artifacts = [manager.register_artifact(**artifact) for artifact in artifacts]
        return tool_result_ok(
            "predict_xgboost_raster_map",
            inputs=inputs,
            outputs={
                "result_dataset": dataset_name,
                "path": str(output_path),
                "preview_path": str(png_path),
                "summary_path": str(summary_path),
                "target": target,
                "features": model_features,
                "target_raster_name": str(target_raster_name or "").strip(),
                "reference_raster": reference_name,
                "representative_date": rep_date.isoformat(),
                "valid_prediction_pixels": int(rows.size),
                "map_layer_id": _map_layer_id(dataset_name),
            },
            artifacts=registered_artifacts,
            map_layers=[{"layer_id": _map_layer_id(dataset_name), "name": dataset_name, "dataset_name": dataset_name, "type": "raster"}],
            images=[{"path": str(png_path), "title": f"{safe_output}.png"}],
            summary=f"已生成 XGBoost 全域栅格预测：{dataset_name}，有效像元 {int(rows.size)}。",
            diagnostics=summary_payload,
            warnings=summary_payload["limitations"],
            next_actions=["在地图中检查预测栅格范围和 NoData 掩膜。", "如需严格逐日产品，请换用同日或同月的 LST/NDVI 栅格重新预测。"],
        )
    except PermissionError as exc:
        return tool_result_error(
            "predict_xgboost_raster_map",
            inputs=inputs,
            error_code="MODEL_PATH_OUTSIDE_WORKSPACE",
            error_title="Model path is outside workspace",
            user_message=str(exc),
        )
    except FileNotFoundError as exc:
        return tool_result_error("predict_xgboost_raster_map", inputs=inputs, error_code="MODEL_NOT_FOUND", error_title="Model not found", user_message=str(exc))
    except Exception as exc:
        return tool_result_error(
            "predict_xgboost_raster_map",
            inputs=inputs,
            error_code="RASTER_PREDICTION_FAILED",
            error_title="Raster prediction failed",
            user_message=str(exc),
        )
