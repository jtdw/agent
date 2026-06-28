from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.ismn_adapter import find_local_ismn_archives
from core.tool_contracts import parse_tool_result, tool_result_error, tool_result_ok


def _safe_name(value: str) -> str:
    from core.workflows.data_package import _safe_name as package_safe_name

    return package_safe_name(value)


def _parse_names(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _visible_raster_names(manager: Any, raster_names: str = "") -> list[str]:
    explicit = _parse_names(raster_names)
    if explicit:
        return explicit
    names: list[str] = []
    for item in manager.list_datasets():
        if str(item.get("type") or "") == "raster" and item.get("name"):
            names.append(str(item["name"]))
    return names


def _is_dem_like_raster(manager: Any, raster_name: str) -> bool:
    name = str(raster_name or "")
    if not name:
        return False
    lower_name = name.lower()
    derived_tokens = ("slope", "aspect", "tpi", "tri", "twi")
    if any(token in lower_name for token in derived_tokens):
        return False

    text_parts = [name]
    try:
        record = manager.get(name)
        text_parts.append(str(getattr(record, "path", "") or ""))
        meta = getattr(record, "meta", {}) or {}
        if str(meta.get("derivative") or "").strip():
            return False
        for key in ("variable", "dataset_type", "source", "product", "title", "description", "layer_kind"):
            if key in meta:
                text_parts.append(str(meta.get(key) or ""))
    except Exception:
        pass

    haystack = " ".join(text_parts).lower()
    dem_tokens = (
        "dem",
        "elevation",
        "elev",
        "srtm",
        "aster",
        "alos",
        "aw3d",
        "高程",
        "数字高程",
    )
    return any(token in haystack for token in dem_tokens)


def _append_unique(values: list[str], candidates: list[str]) -> list[str]:
    seen = set(values)
    for candidate in candidates:
        if candidate and candidate not in seen:
            values.append(candidate)
            seen.add(candidate)
    return values


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return True


def _date_from_temporal_text(value: str) -> str:
    match = re.search(r"((?:19|20)\d{2})[_-]?(\d{2})[_-]?(\d{2})", str(value or ""))
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _date_from_netcdf_time_value(value: Any, units: str) -> str:
    raw = str(value or "").strip()
    unit_text = str(units or "").strip()
    if not raw or not unit_text:
        return ""
    match = re.search(r"days\s+since\s+(\d{4}-\d{2}-\d{2})(?:[ T]\d{2}:\d{2}:\d{2})?", unit_text, flags=re.IGNORECASE)
    if not match:
        return ""
    base = pd.to_datetime(match.group(1), errors="coerce")
    if pd.isna(base):
        return ""
    try:
        offset_days = float(raw)
    except Exception:
        return ""
    return (base + pd.to_timedelta(offset_days, unit="D")).strftime("%Y-%m-%d")


def _date_from_raster_band(src: Any, raster_name: str, band_index: int) -> str:
    description = ""
    try:
        description = str((src.descriptions or [])[int(band_index) - 1] or "")
    except Exception:
        description = ""
    date_value = _date_from_temporal_text(description)
    if date_value:
        return date_value
    try:
        band_tags = src.tags(int(band_index))
        time_value = band_tags.get("NETCDF_DIM_time") or band_tags.get("time")
        units = src.tags().get("time#units") or band_tags.get("time#units") or ""
        date_value = _date_from_netcdf_time_value(time_value, units)
        if date_value:
            return date_value
    except Exception:
        pass
    return _date_from_temporal_text(raster_name)


def _raster_temporal_dates(manager: Any, raster_name: str) -> set[str]:
    dates: set[str] = set()
    try:
        import rasterio

        with rasterio.open(manager.get_raster_path(raster_name)) as src:
            for band_index in range(1, src.count + 1):
                date_value = _date_from_raster_band(src, raster_name, band_index)
                if date_value:
                    dates.add(date_value)
    except Exception:
        return dates
    if not dates:
        date_value = _date_from_temporal_text(raster_name)
        if date_value:
            dates.add(date_value)
    return dates


def _temporal_raster_names(manager: Any, raster_names: list[str]) -> list[str]:
    return [name for name in raster_names if _raster_temporal_dates(manager, name)]


def _covariate_type_for_raster(raster_name: str) -> str:
    lower = str(raster_name or "").lower()
    tokens = {token for token in re.split(r"[^a-z0-9]+", lower) if token}
    if "ndvi" in lower:
        return "ndvi"
    if "evi" in lower:
        return "evi"
    if "lst" in lower:
        return "lst_celsius"
    if "precip" in lower or "rain" in lower or tokens.intersection({"prep", "prcp", "rainfall"}):
        return "precipitation_mm"
    return "generic"


def _is_landcover_like_raster(manager: Any, raster_name: str) -> bool:
    parts = [str(raster_name or "")]
    try:
        record = manager.get(raster_name)
        meta = getattr(record, "meta", {}) or {}
        parts.append(str(getattr(record, "path", "") or ""))
        for key in ("variable", "dataset_type", "source", "product", "title", "description", "layer_kind", "covariate_type"):
            if key in meta:
                parts.append(str(meta.get(key) or ""))
    except Exception:
        pass
    text = " ".join(parts).lower()
    return any(token in text for token in ("lulc", "landcover", "land_cover", "landuse", "land_use", "lc_type"))


def _parse_observation_dates(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    return parsed.dt.normalize()


def _temporal_specs_for_raster(raster_name: str) -> list[dict[str, Any]]:
    covariate_type = _covariate_type_for_raster(raster_name)
    safe = _safe_name(raster_name)
    if covariate_type == "precipitation_mm":
        return [
            {"field": f"raster_{safe}_sum_{window}d", "mode": "sum", "days_before": window - 1, "days_after": 0}
            for window in (3, 7, 14, 30)
        ]
    if covariate_type in {"ndvi", "evi"}:
        return [{"field": f"raster_{safe}_window_max_7d", "mode": "max", "days_before": 3, "days_after": 3}]
    if covariate_type in {"lst_celsius", "lst_kelvin"}:
        return [{"field": f"raster_{safe}_window_median_7d", "mode": "median", "days_before": 3, "days_after": 3}]
    return [{"field": f"raster_{safe}_window_median_7d", "mode": "median", "days_before": 3, "days_after": 3}]


def _raster_sample_field(raster_name: str) -> str:
    return f"raster_{_safe_name(raster_name)}"


def _representative_prediction_date(*, requested: str = "", temporal_alignment: dict[str, Any] | None = None, year: str = "") -> str:
    requested_date = pd.to_datetime(str(requested or "").strip(), errors="coerce")
    if not pd.isna(requested_date):
        return requested_date.strftime("%Y-%m-%d")
    selected_range = (temporal_alignment or {}).get("selected_time_range") if isinstance(temporal_alignment, dict) else {}
    if isinstance(selected_range, dict):
        end_date = pd.to_datetime(str(selected_range.get("end") or "").strip(), errors="coerce")
        if not pd.isna(end_date):
            return end_date.strftime("%Y-%m-%d")
    year_text = str(year or "").strip()
    if re.fullmatch(r"\d{4}", year_text):
        return f"{year_text}-07-01"
    return "2019-07-01"


def _model_artifact_path(result: dict[str, Any]) -> str:
    for artifact in result.get("artifacts", []) or []:
        if isinstance(artifact, dict) and artifact.get("type") == "model" and str(artifact.get("path") or "").strip():
            return str(artifact.get("path"))
    for path in result.get("outputs", {}).get("generated_files", []) or []:
        text = str(path or "")
        if text.endswith("_model.joblib"):
            return text
    return ""


def _prediction_feature_mapping(
    manager: Any,
    *,
    model_feature_cols: list[str],
    feature_rasters: list[str],
    temporal_rasters: list[str],
) -> tuple[dict[str, str], list[str]]:
    model_features = {str(field) for field in model_feature_cols}
    mapping: dict[str, str] = {}
    warnings: list[str] = []
    dem_candidates: list[str] = []
    for raster_name in feature_rasters:
        field = _raster_sample_field(raster_name)
        if field in model_features:
            mapping[field] = raster_name
        if _is_dem_like_raster(manager, raster_name):
            dem_candidates.append(raster_name)
    if "elevation_m" in model_features and dem_candidates:
        mapping["elevation_m"] = dem_candidates[0]
    for raster_name in temporal_rasters:
        for spec in _temporal_specs_for_raster(raster_name):
            field = str(spec.get("field") or "")
            if field in model_features and field not in mapping:
                warnings.append(field)
    return mapping, warnings


def _build_temporal_prediction_feature_rasters(
    tool_map: dict[str, Any],
    manager: Any,
    *,
    temporal_rasters: list[str],
    model_feature_cols: list[str],
    representative_date: str,
    output_prefix: str,
    boundary_dataset: str = "",
    steps: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, str]:
    model_features = {str(field) for field in model_feature_cols}
    rep_date = pd.to_datetime(representative_date, errors="coerce")
    if pd.isna(rep_date):
        return {}
    mapping: dict[str, str] = {}
    for raster_name in temporal_rasters:
        composite_source = raster_name
        if str(boundary_dataset or "").strip():
            clip_args = {
                "raster_name": raster_name,
                "vector_name": boundary_dataset,
                "output_name": f"{output_prefix}_{_safe_name(raster_name)}_prediction_clip",
            }
            clip_result = _invoke(tool_map, "clip_raster_by_vector", clip_args)
            steps.append(_step("clip_raster_by_vector", clip_args, clip_result))
            artifacts.extend([item for item in clip_result.get("artifacts", []) if isinstance(item, dict)])
            if clip_result.get("ok"):
                composite_source = str(clip_result.get("outputs", {}).get("result_dataset") or raster_name)
        covariate_type = _covariate_type_for_raster(raster_name)
        for spec in _temporal_specs_for_raster(raster_name):
            field = str(spec.get("field") or "")
            if field not in model_features:
                continue
            start_date = (rep_date - timedelta(days=int(spec.get("days_before") or 0))).strftime("%Y-%m-%d")
            end_date = (rep_date + timedelta(days=int(spec.get("days_after") or 0))).strftime("%Y-%m-%d")
            composite_args = {
                "raster_names": composite_source,
                "output_name": f"{output_prefix}_{_safe_name(field)}_prediction_feature",
                "covariate_type": covariate_type,
                "method": str(spec.get("mode") or ""),
                "band_selection": "auto",
                "start_date": start_date,
                "end_date": end_date,
            }
            composite_result = _invoke(tool_map, "build_temporal_covariate_composite", composite_args)
            steps.append(_step("build_temporal_covariate_composite", composite_args, composite_result))
            artifacts.extend([item for item in composite_result.get("artifacts", []) if isinstance(item, dict)])
            if composite_result.get("ok"):
                dataset_name = str(composite_result.get("outputs", {}).get("result_dataset") or "")
                if dataset_name:
                    mapping[field] = dataset_name
    return mapping


def _aggregate_temporal_values(values: list[float], mode: str) -> float:
    arr = np.asarray(values, dtype="float64")
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    if mode == "sum":
        return float(np.sum(arr))
    if mode == "max":
        return float(np.max(arr))
    if mode == "min":
        return float(np.min(arr))
    if mode == "mean":
        return float(np.mean(arr))
    return float(np.median(arr))


def _raster_band_scale_offset(src: Any, band: int = 1) -> tuple[float, float]:
    index = max(0, int(band or 1) - 1)
    scale = 1.0
    offset = 0.0
    try:
        if index < len(src.scales) and src.scales[index] is not None:
            scale = float(src.scales[index])
    except Exception:
        scale = 1.0
    try:
        if index < len(src.offsets) and src.offsets[index] is not None:
            offset = float(src.offsets[index])
    except Exception:
        offset = 0.0
    try:
        tags = src.tags(int(band or 1))
        if "scale_factor" in tags:
            scale = float(tags["scale_factor"])
        if "add_offset" in tags:
            offset = float(tags["add_offset"])
    except Exception:
        pass
    return scale, offset


def _apply_raster_scale_offset(value: Any, scale: float, offset: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        return float("nan")
    if not np.isfinite(numeric):
        return float("nan")
    return float(numeric * float(scale) + float(offset))


def _extract_temporal_station_covariates(
    manager: Any,
    *,
    training_dataset: str,
    temporal_rasters: list[str],
    output_name: str,
) -> dict[str, Any]:
    try:
        import rasterio
        from rasterio.warp import transform as transform_coords

        training_df = manager.get_table(training_dataset).copy()
        required = {"lon", "lat", "date"}
        missing = sorted(required - set(training_df.columns))
        if missing:
            return tool_result_error(
                "extract_temporal_station_covariates",
                inputs={"training_dataset": training_dataset, "temporal_rasters": temporal_rasters, "output_name": output_name},
                error_code="TEMPORAL_STATION_COLUMNS_MISSING",
                error_title="Missing station temporal columns",
                user_message="Temporal station feature extraction requires lon, lat, and date columns.",
                diagnostics={"missing_fields": missing, "available_fields": [str(col) for col in training_df.columns]},
                next_actions=["Convert station observations with lon/lat/date fields before running STM temporal covariate extraction."],
            ).to_dict()

        obs_dates = _parse_observation_dates(training_df["date"])
        lon = pd.to_numeric(training_df["lon"], errors="coerce")
        lat = pd.to_numeric(training_df["lat"], errors="coerce")
        temporal_fields: list[str] = []
        raster_summaries: list[dict[str, Any]] = []
        for raster_name in temporal_rasters:
            specs = _temporal_specs_for_raster(raster_name)
            for spec in specs:
                training_df[spec["field"]] = np.nan
                temporal_fields.append(str(spec["field"]))

            raster_path = manager.get_raster_path(raster_name)
            with rasterio.open(raster_path) as src:
                xs = lon.to_numpy(dtype="float64", na_value=np.nan)
                ys = lat.to_numpy(dtype="float64", na_value=np.nan)
                valid_xy = np.isfinite(xs) & np.isfinite(ys)
                sample_x = xs.copy()
                sample_y = ys.copy()
                if src.crs and str(src.crs) != "EPSG:4326" and bool(valid_xy.any()):
                    tx, ty = transform_coords("EPSG:4326", src.crs, xs[valid_xy].tolist(), ys[valid_xy].tolist())
                    sample_x[valid_xy] = tx
                    sample_y[valid_xy] = ty
                coord_index_by_row = np.full(len(training_df), -1, dtype="int64")
                coord_lookup: dict[tuple[float, float], int] = {}
                coords: list[tuple[float, float]] = []
                for row_index, (x, y) in enumerate(zip(sample_x, sample_y)):
                    if not valid_xy[row_index] or not np.isfinite(x) or not np.isfinite(y):
                        continue
                    coord = (float(x), float(y))
                    sample_index = coord_lookup.get(coord)
                    if sample_index is None:
                        sample_index = len(coords)
                        coord_lookup[coord] = sample_index
                        coords.append(coord)
                    coord_index_by_row[row_index] = sample_index

                band_samples: list[dict[str, Any]] = []
                for band_index in range(1, src.count + 1):
                    band_date_text = _date_from_raster_band(src, raster_name, band_index)
                    band_date = pd.to_datetime(band_date_text, errors="coerce")
                    if pd.isna(band_date):
                        continue
                    scale, offset = _raster_band_scale_offset(src, band_index)
                    values: list[float] = []
                    for sampled in src.sample(coords, indexes=band_index):
                        value = float(sampled[0]) if len(sampled) else float("nan")
                        if src.nodata is not None and np.isclose(value, float(src.nodata), equal_nan=False):
                            value = float("nan")
                        values.append(_apply_raster_scale_offset(value, scale, offset))
                    band_samples.append({"date": band_date.normalize(), "band": band_index, "values": values})

                for row_index, obs_date in enumerate(obs_dates):
                    if pd.isna(obs_date):
                        continue
                    for spec in specs:
                        start_date = obs_date - timedelta(days=int(spec["days_before"]))
                        end_date = obs_date + timedelta(days=int(spec["days_after"]))
                        sample_index = int(coord_index_by_row[row_index])
                        values = [
                            float(item["values"][sample_index]) if sample_index >= 0 else float("nan")
                            for item in band_samples
                            if start_date <= item["date"] <= end_date
                        ]
                        training_df.at[row_index, spec["field"]] = _aggregate_temporal_values(values, str(spec["mode"]))

            raster_summaries.append(
                {
                    "raster_name": raster_name,
                    "covariate_type": _covariate_type_for_raster(raster_name),
                    "fields": [str(spec["field"]) for spec in specs],
                    "band_count": int(len(band_samples)) if "band_samples" in locals() else 0,
                    "unique_sample_point_count": int(len(coords)) if "coords" in locals() else 0,
                }
            )

        saved_name = manager.put_table(output_name, training_df)
        missing_by_field = {field: int(pd.to_numeric(training_df[field], errors="coerce").isna().sum()) for field in temporal_fields}
        return tool_result_ok(
            "extract_temporal_station_covariates",
            inputs={"training_dataset": training_dataset, "temporal_rasters": temporal_rasters, "output_name": output_name},
            outputs={
                "result_dataset": saved_name,
                "row_count": int(len(training_df)),
                "temporal_feature_cols": temporal_fields,
                "temporal_rasters": raster_summaries,
                "missing_by_field": missing_by_field,
            },
            summary=f"Extracted observation-window temporal covariates for {len(training_df)} station row(s).",
            diagnostics={"temporal_rasters": raster_summaries, "missing_by_field": missing_by_field},
        ).to_dict()
    except Exception as exc:
        return tool_result_error(
            "extract_temporal_station_covariates",
            inputs={"training_dataset": training_dataset, "temporal_rasters": temporal_rasters, "output_name": output_name},
            error_code="TEMPORAL_STATION_FEATURES_FAILED",
            error_title="Temporal station feature extraction failed",
            user_message="Failed to sample temporal raster bands around station observation dates.",
            technical_detail=f"{type(exc).__name__}: {exc}",
            next_actions=["Check raster band dates, CRS, NoData values, and station lon/lat/date fields."],
        ).to_dict()


def resolve_default_station_archive(manager: Any) -> Path | None:
    workdir = Path(getattr(manager, "workdir", "") or ".")
    roots: list[Path] = []
    for attr in ("upload_dir", "derived_dir"):
        value = getattr(manager, attr, None)
        if value:
            roots.append(Path(value))
    roots.extend(
        [
            workdir / "local_library" / "data" / "ismn",
            workdir.parent / "local_library" / "data" / "ismn",
            Path.cwd() / "local_library" / "data" / "ismn",
        ]
    )
    archives = find_local_ismn_archives(*roots)
    return archives[0] if archives else None


def _tool_map(manager: Any) -> dict[str, Any]:
    from core.tools.registry import build_tools

    return {tool.name: tool for tool in build_tools(manager)}


def _invoke(tool_map: dict[str, Any], tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = tool_map.get(tool_name)
    if tool is None:
        return tool_result_error(
            tool_name,
            inputs=args,
            error_code="TOOL_NOT_REGISTERED",
            error_title="Tool not registered",
            user_message=f"Required workflow tool is not registered: {tool_name}.",
        ).to_dict()
    try:
        parsed = parse_tool_result(tool.invoke(args))
    except Exception as exc:
        return tool_result_error(
            tool_name,
            inputs=args,
            error_code="TOOL_EXECUTION_EXCEPTION",
            error_title="Tool execution failed",
            user_message=f"Workflow step {tool_name} failed before returning a result.",
            technical_detail=f"{type(exc).__name__}: {exc}",
        ).to_dict()
    if parsed is None:
        return tool_result_error(
            tool_name,
            inputs=args,
            error_code="INVALID_TOOL_RESULT",
            error_title="Invalid tool result",
            user_message=f"Workflow step {tool_name} did not return a structured result.",
        ).to_dict()
    return parsed


def _step(tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "args": args,
        "ok": bool(result.get("ok")),
        "outputs": result.get("outputs") if isinstance(result.get("outputs"), dict) else {},
        "error_code": result.get("error_code", ""),
        "user_message": result.get("user_message", ""),
    }


def _dataset_frame(manager: Any, dataset_name: str) -> pd.DataFrame:
    record = manager.get(dataset_name)
    if record.data_type == "table":
        return manager.get_table(dataset_name)
    if record.data_type == "vector":
        return pd.DataFrame(manager.get_vector(dataset_name).drop(columns=["geometry"], errors="ignore"))
    raise TypeError(f"{dataset_name} is not a table or vector dataset")


def _vector_dataset_exists(manager: Any, dataset_name: str) -> bool:
    try:
        return bool(dataset_name) and manager.get(dataset_name).data_type == "vector"
    except Exception:
        return False


def _is_shandianhe_query(value: str) -> bool:
    text = str(value or "").strip().lower()
    return "shandian" in text or "\u95ea\u7535\u6cb3" in str(value or "")


def _infer_study_area_query(*, archive_path: str, raster_names: str, output_prefix: str) -> str:
    text = " ".join([str(archive_path or ""), str(raster_names or ""), str(output_prefix or "")])
    if _is_shandianhe_query(text):
        return "shandianhe"
    return ""


def _load_shandianhe_boundary(manager: Any) -> dict[str, Any]:
    if _vector_dataset_exists(manager, "shandianhe_basin_boundary"):
        return {
            "status": "resolved",
            "boundary_dataset": "shandianhe_basin_boundary",
            "area_source": "workspace",
            "resolution_method": "existing_dataset",
            "study_area": "shandianhe",
        }

    try:
        from core.domestic_sources.gscloud_adapter import _extract_local_shandian_boundary

        _, dataset_name, source = _extract_local_shandian_boundary(manager, "shandianhe")
        if dataset_name and _vector_dataset_exists(manager, dataset_name):
            return {
                "status": "resolved",
                "boundary_dataset": dataset_name,
                "area_source": source or "local_library_boundary",
                "resolution_method": "local_library_boundary_asset",
                "study_area": "shandianhe",
            }
    except Exception as exc:
        last_error = f"{type(exc).__name__}: {exc}"
    else:
        last_error = ""

    try:
        dataset_name = manager.load_path("lib_shandianhe_basin_boundary_full", name="shandianhe_basin_boundary")
        if _vector_dataset_exists(manager, dataset_name):
            return {
                "status": "resolved",
                "boundary_dataset": dataset_name,
                "area_source": "local_library",
                "resolution_method": "local_library_manifest_item",
                "study_area": "shandianhe",
            }
    except Exception as exc:
        last_error = last_error or f"{type(exc).__name__}: {exc}"

    return {
        "status": "unsupported",
        "study_area": "shandianhe",
        "reason": "known_area_boundary_not_available",
        "technical_detail": last_error,
    }


def _resolve_study_area_boundary(
    manager: Any,
    *,
    boundary_name: str = "",
    study_area: str = "",
    archive_path: str = "",
    raster_names: str = "",
    output_prefix: str = "",
) -> dict[str, Any]:
    explicit_boundary = str(boundary_name or "").strip()
    if explicit_boundary:
        if _vector_dataset_exists(manager, explicit_boundary):
            return {
                "status": "resolved",
                "boundary_dataset": explicit_boundary,
                "area_source": "workspace",
                "resolution_method": "explicit_boundary_name",
                "study_area": str(study_area or explicit_boundary),
            }
        return {
            "status": "invalid_boundary",
            "boundary_dataset": explicit_boundary,
            "reason": "boundary_dataset_not_found_or_not_vector",
        }

    query = str(study_area or "").strip()
    inferred = False
    if not query:
        query = _infer_study_area_query(archive_path=archive_path, raster_names=raster_names, output_prefix=output_prefix)
        inferred = bool(query)
    if not query:
        return {
            "status": "missing",
            "reason": "study_area_not_provided",
            "supported_local_areas": ["china_admin_province_city_county", "shandianhe_basin"],
        }

    if _is_shandianhe_query(query):
        resolved = _load_shandianhe_boundary(manager)
        resolved["requested_study_area"] = query
        resolved["inferred"] = inferred
        return resolved

    try:
        from core.admin_boundary import extract_local_admin_boundary
        from core.area_resolver import resolve_area_candidates

        candidates = resolve_area_candidates(query, limit=3, manager=manager)
        for candidate in candidates:
            dataset_name = str(candidate.get("dataset_name") or candidate.get("geometry_asset_id") or "")
            if dataset_name and _vector_dataset_exists(manager, dataset_name):
                return {
                    "status": "resolved",
                    "boundary_dataset": dataset_name,
                    "area_source": str(candidate.get("area_source") or "local_admin_boundary"),
                    "resolution_method": str(candidate.get("resolution_method") or "area_resolver"),
                    "study_area": str(candidate.get("name") or query),
                    "requested_study_area": query,
                    "inferred": inferred,
                    "candidate": candidate,
                }
        _, dataset_name, source = extract_local_admin_boundary(manager, query)
        if dataset_name and _vector_dataset_exists(manager, dataset_name):
            return {
                "status": "resolved",
                "boundary_dataset": dataset_name,
                "area_source": source or "local_admin_boundary",
                "resolution_method": "local_admin_boundary",
                "study_area": query,
                "requested_study_area": query,
                "inferred": inferred,
            }
    except Exception as exc:
        return {
            "status": "unsupported",
            "requested_study_area": query,
            "reason": "area_resolution_failed",
            "technical_detail": f"{type(exc).__name__}: {exc}",
        }

    return {
        "status": "unsupported",
        "requested_study_area": query,
        "reason": "study_area_not_in_local_library",
        "supported_local_areas": ["china_admin_province_city_county", "shandianhe_basin"],
    }


def _filter_training_by_boundary(
    manager: Any,
    *,
    training_dataset: str,
    boundary_dataset: str,
    output_name: str,
) -> dict[str, Any]:
    try:
        import geopandas as gpd

        training_df = manager.get_table(training_dataset)
        boundary = manager.get_vector(boundary_dataset).copy()
        lon = pd.to_numeric(training_df.get("lon"), errors="coerce")
        lat = pd.to_numeric(training_df.get("lat"), errors="coerce")
        valid_xy = lon.notna() & lat.notna()
        points = gpd.GeoDataFrame(
            training_df.copy(),
            geometry=gpd.points_from_xy(lon.fillna(0), lat.fillna(0)),
            crs="EPSG:4326",
        )
        if boundary.crs is None:
            boundary = boundary.set_crs("EPSG:4326", allow_override=True)
        else:
            boundary = boundary.to_crs("EPSG:4326")
        boundary = boundary[boundary.geometry.notna() & ~boundary.geometry.is_empty].copy()
        if boundary.empty:
            return tool_result_error(
                "prepare_study_area_training_samples",
                inputs={"training_dataset": training_dataset, "boundary_dataset": boundary_dataset, "output_name": output_name},
                error_code="EMPTY_STUDY_AREA_BOUNDARY",
                error_title="Study area boundary is empty",
                user_message="The selected study-area boundary has no usable geometry.",
                next_actions=["Upload a valid polygon boundary or choose a supported local-library area."],
            ).to_dict()
        union_geom = boundary.geometry.union_all() if hasattr(boundary.geometry, "union_all") else boundary.geometry.unary_union
        inside_mask = valid_xy & points.geometry.intersects(union_geom)
        filtered_df = training_df.loc[inside_mask].reset_index(drop=True)
        removed_df = training_df.loc[~inside_mask].copy()
        saved_name = manager.put_table(output_name, filtered_df)
        removed_stations = sorted({str(item) for item in removed_df.get("station_id", pd.Series(dtype=str)).dropna().unique()})
        return tool_result_ok(
            "prepare_study_area_training_samples",
            inputs={"training_dataset": training_dataset, "boundary_dataset": boundary_dataset, "output_name": output_name},
            outputs={
                "result_dataset": saved_name,
                "boundary_dataset": boundary_dataset,
                "row_count": int(len(filtered_df)),
                "removed_row_count": int(len(removed_df)),
                "removed_station_count": int(len(removed_stations)),
                "removed_stations": removed_stations,
                "filter_method": "study_area_boundary",
                "boundary_bounds": [float(v) for v in boundary.total_bounds],
            },
            summary=f"Filtered station samples by study-area boundary: kept {len(filtered_df)} row(s), removed {len(removed_df)} row(s).",
            diagnostics={"source_training_dataset": training_dataset},
        ).to_dict()
    except Exception as exc:
        return tool_result_error(
            "prepare_study_area_training_samples",
            inputs={"training_dataset": training_dataset, "boundary_dataset": boundary_dataset, "output_name": output_name},
            error_code="STUDY_AREA_FILTER_FAILED",
            error_title="Study area filtering failed",
            user_message="Failed to filter station samples by the selected study-area boundary.",
            technical_detail=f"{type(exc).__name__}: {exc}",
            next_actions=["Check that the station table has lon/lat columns and the boundary is a valid vector polygon dataset."],
        ).to_dict()


def _unified_training_filter(
    manager: Any,
    *,
    training_dataset: str,
    coverage_dataset: str,
    raster_fields: list[str],
    output_name: str,
) -> dict[str, Any]:
    training_df = manager.get_table(training_dataset)
    coverage_df = _dataset_frame(manager, coverage_dataset)
    if len(training_df) != len(coverage_df):
        return tool_result_error(
            "prepare_unified_training_samples",
            inputs={"training_dataset": training_dataset, "coverage_dataset": coverage_dataset, "output_name": output_name},
            error_code="UNIFIED_SAMPLE_ROW_MISMATCH",
            error_title="Unified preprocessing failed",
            user_message="Coverage sampling rows did not match the station training table rows.",
            diagnostics={"training_rows": int(len(training_df)), "coverage_rows": int(len(coverage_df))},
        ).to_dict()

    valid_mask = pd.Series(True, index=training_df.index)
    required_fields: list[str] = []
    mask_fields: list[str] = []
    for field in raster_fields:
        if field not in coverage_df.columns:
            continue
        lower = field.lower()
        required_fields.append(field)
        values = pd.to_numeric(coverage_df[field], errors="coerce")
        valid_mask &= values.notna()
        if any(token in lower for token in ("lulc", "landcover", "land_cover", "lc_type")):
            valid_mask &= values.ne(0)
            mask_fields.append(field)

    filtered_df = training_df.loc[valid_mask].reset_index(drop=True)
    removed_df = training_df.loc[~valid_mask].copy()
    saved_name = manager.put_table(output_name, filtered_df)
    removed_stations = sorted({str(item) for item in removed_df.get("station_id", pd.Series(dtype=str)).dropna().unique()})
    return tool_result_ok(
        "prepare_unified_training_samples",
        inputs={"training_dataset": training_dataset, "coverage_dataset": coverage_dataset, "output_name": output_name},
        outputs={
            "result_dataset": saved_name,
            "row_count": int(len(filtered_df)),
            "removed_row_count": int(len(removed_df)),
            "removed_station_count": int(len(removed_stations)),
            "removed_stations": removed_stations,
            "required_raster_fields": required_fields,
            "mask_raster_fields": mask_fields,
            "filter_method": "raster_coverage_and_mask",
        },
        summary=f"Prepared unified training samples: kept {len(filtered_df)} row(s), removed {len(removed_df)} row(s).",
        diagnostics={"coverage_dataset": coverage_dataset},
    ).to_dict()


def _categorical_raster_feature_fields(manager: Any, feature_rasters: list[str], raster_fields: list[str]) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    for raster_name in feature_rasters:
        if not _is_landcover_like_raster(manager, raster_name):
            continue
        safe = _safe_name(raster_name).lower()
        for field in raster_fields:
            lower = field.lower()
            if lower == f"raster_{safe}" or lower.startswith(f"raster_{safe}_"):
                if field not in seen:
                    fields.append(field)
                    seen.add(field)
    for field in raster_fields:
        lower = field.lower()
        if any(token in lower for token in ("lulc", "landcover", "land_cover", "landuse", "land_use", "lc_type")) and field not in seen:
            fields.append(field)
            seen.add(field)
    return fields


def _read_model_feature_dataset(manager: Any, dataset_name: str) -> tuple[pd.DataFrame, Any | None, str]:
    record = manager.get(dataset_name)
    if record.data_type == "vector":
        gdf = manager.get_vector(dataset_name)
        return gdf.copy(), gdf.geometry.copy(), "vector"
    if record.data_type == "table":
        return manager.get_table(dataset_name), None, "table"
    raise TypeError(f"{dataset_name} is not a table or vector dataset")


def _save_model_feature_dataset(manager: Any, output_name: str, frame: pd.DataFrame, geometry: Any | None, data_type: str) -> str:
    if data_type == "vector" and geometry is not None:
        import geopandas as gpd

        gdf = gpd.GeoDataFrame(frame.copy(), geometry=geometry, crs=getattr(geometry, "crs", None))
        return manager.put_vector(output_name, gdf, filename=f"{_safe_name(output_name)}.geojson")
    return manager.put_table(output_name, frame)


def run_stm_soil_moisture_xgboost_workflow(
    manager: Any,
    *,
    archive_path: str,
    raster_names: str = "",
    preferred_depth: str = "0.050000",
    year: str = "2019",
    output_prefix: str = "stm_soil_moisture",
    aggregate: str = "daily",
    min_samples: int = 8,
    encode_aspect_circular: bool = True,
    boundary_name: str = "",
    study_area: str = "",
    representative_date: str = "",
) -> dict[str, Any]:
    """Run the conditional STM -> point -> raster feature -> XGBoost workflow."""
    resolved_archive = Path(archive_path) if str(archive_path or "").strip() else resolve_default_station_archive(manager)
    if resolved_archive is None:
        return tool_result_error(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs={"archive_path": archive_path, "raster_names": raster_names, "output_prefix": output_prefix},
            error_code="ISMN_ARCHIVE_NOT_FOUND",
            error_title="ISMN archive not found",
            user_message="No local ISMN archive was provided and no default archive was found in uploads, derived, or local_library/data/ismn.",
            next_actions=["Upload an official ISMN zip archive or place it under local_library/data/ismn."],
        ).to_dict()
    archive_path = str(resolved_archive)
    prefix = _safe_name(output_prefix or Path(archive_path).stem)
    tool_map = _tool_map(manager)
    steps: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    convert_args = {
        "archive_path": archive_path,
        "preferred_depth": preferred_depth,
        "year": year,
        "output_name": f"{prefix}_training",
        "aggregate": aggregate,
    }
    convert_result = _invoke(tool_map, "convert_stm_station_archive_to_training_table", convert_args)
    steps.append(_step("convert_stm_station_archive_to_training_table", convert_args, convert_result))
    artifacts.extend([item for item in convert_result.get("artifacts", []) if isinstance(item, dict)])
    if not convert_result.get("ok"):
        return tool_result_error(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs=convert_args,
            error_code=str(convert_result.get("error_code") or "STM_CONVERSION_FAILED"),
            error_title="STM workflow failed",
            user_message=str(convert_result.get("user_message") or "Failed to convert STM station data."),
            diagnostics={"steps": steps},
            next_actions=[str(item) for item in convert_result.get("next_actions", []) if str(item).strip()],
        ).to_dict()

    training_dataset = str(convert_result.get("outputs", {}).get("result_dataset") or "")
    target_col = str(convert_result.get("outputs", {}).get("target_col") or ("soil_moisture_mean" if aggregate == "daily" else "soil_moisture"))
    row_count = int(convert_result.get("outputs", {}).get("row_count") or 0)
    rasters = _visible_raster_names(manager, raster_names)
    if not rasters:
        return tool_result_ok(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs={"archive_path": archive_path, "raster_names": raster_names, "output_prefix": output_prefix},
            outputs={
                "status": "needs_raster_features",
                "source_archive": archive_path,
                "training_dataset": training_dataset,
                "target_col": target_col,
                "row_count": row_count,
                "raster_features": [],
                "steps": steps,
            },
            artifacts=artifacts,
            summary="Converted STM station observations to a training table. Raster feature data is required before XGBoost modeling.",
            diagnostics={"minimum_samples": min_samples, "available_rasters": []},
            next_actions=[
                "Upload or download DEM, NDVI, LST, climate, soil, or other raster feature datasets.",
                "Run this workflow again after raster datasets appear in the workspace.",
            ],
        ).to_dict()
    if row_count < int(min_samples):
        return tool_result_ok(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs={"archive_path": archive_path, "raster_names": ",".join(rasters), "output_prefix": output_prefix},
            outputs={
                "status": "needs_more_samples",
                "source_archive": archive_path,
                "training_dataset": training_dataset,
                "target_col": target_col,
                "row_count": row_count,
                "raster_features": rasters,
                "steps": steps,
            },
            artifacts=artifacts,
            summary="Converted STM station observations, but there are too few valid samples for XGBoost.",
            diagnostics={"minimum_samples": min_samples},
            next_actions=["Use a wider year range, hourly aggregate mode, or additional station data."],
        ).to_dict()

    study_area_resolution = _resolve_study_area_boundary(
        manager,
        boundary_name=boundary_name,
        study_area=study_area,
        archive_path=archive_path,
        raster_names=",".join(rasters),
        output_prefix=output_prefix,
    )
    if study_area_resolution.get("status") == "missing":
        return tool_result_ok(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs={
                "archive_path": archive_path,
                "raster_names": ",".join(rasters),
                "output_prefix": output_prefix,
                "boundary_name": boundary_name,
                "study_area": study_area,
            },
            outputs={
                "status": "needs_study_area",
                "source_archive": archive_path,
                "training_dataset": training_dataset,
                "target_col": target_col,
                "row_count": row_count,
                "raster_features": rasters,
                "study_area_resolution": study_area_resolution,
                "steps": steps,
            },
            artifacts=artifacts,
            summary="Station and raster inputs are ready, but the workflow needs a study area before spatial filtering and modeling.",
            diagnostics={"minimum_samples": min_samples},
            next_actions=[
                "Specify a China province/city/county name that exists in the local admin boundary library.",
                "Specify shandianhe for the local Shandianhe basin boundary.",
                "Upload a polygon boundary and pass its dataset name as boundary_name for other regions.",
            ],
        ).to_dict()
    if study_area_resolution.get("status") == "unsupported":
        return tool_result_ok(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs={
                "archive_path": archive_path,
                "raster_names": ",".join(rasters),
                "output_prefix": output_prefix,
                "boundary_name": boundary_name,
                "study_area": study_area,
            },
            outputs={
                "status": "needs_boundary_upload",
                "source_archive": archive_path,
                "training_dataset": training_dataset,
                "target_col": target_col,
                "row_count": row_count,
                "raster_features": rasters,
                "study_area_resolution": study_area_resolution,
                "steps": steps,
            },
            artifacts=artifacts,
            summary="The requested study area is not available in the local boundary library.",
            diagnostics={"minimum_samples": min_samples},
            next_actions=["Upload a polygon boundary for this study area, then run the workflow again with boundary_name."],
        ).to_dict()
    if study_area_resolution.get("status") == "invalid_boundary":
        return tool_result_error(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs={"boundary_name": boundary_name, "study_area": study_area},
            error_code="STUDY_AREA_BOUNDARY_NOT_FOUND",
            error_title="Study area boundary not found",
            user_message="The provided boundary_name is not a registered vector dataset.",
            diagnostics={"study_area_resolution": study_area_resolution},
            next_actions=["Upload or register a polygon boundary dataset, or use a supported local-library area."],
        ).to_dict()

    temporal_rasters = _temporal_raster_names(manager, rasters)
    temporal_alignment: dict[str, Any] = {}
    temporal_composites: dict[str, str] = {}
    temporal_feature_cols: list[str] = []
    temporal_feature_summary: dict[str, Any] = {}
    if temporal_rasters:
        align_args = {
            "station_dataset": training_dataset,
            "raster_names": ",".join(temporal_rasters),
            "output_name": f"{prefix}_aligned_training",
            "date_col": "date",
            "station_col": "station_id",
            "min_observations_per_station": 1,
        }
        align_result = _invoke(tool_map, "align_station_raster_time_window", align_args)
        steps.append(_step("align_station_raster_time_window", align_args, align_result))
        artifacts.extend([item for item in align_result.get("artifacts", []) if isinstance(item, dict)])
        if not align_result.get("ok"):
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs=align_args,
                error_code=str(align_result.get("error_code") or "TEMPORAL_ALIGNMENT_FAILED"),
                error_title="STM workflow failed",
                user_message=str(align_result.get("user_message") or "Failed to align station observations with temporal raster bands."),
                diagnostics={"steps": steps, "temporal_rasters": temporal_rasters},
                next_actions=[str(item) for item in align_result.get("next_actions", []) if str(item).strip()],
            ).to_dict()
        temporal_alignment = dict(align_result.get("outputs") or {})
        training_dataset = str(temporal_alignment.get("result_dataset") or training_dataset)
        row_count = int(temporal_alignment.get("row_count") or row_count)
        if row_count < int(min_samples):
            return tool_result_ok(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs={"archive_path": archive_path, "raster_names": ",".join(rasters), "output_prefix": output_prefix},
                outputs={
                    "status": "needs_more_samples_after_temporal_alignment",
                    "source_archive": archive_path,
                    "training_dataset": training_dataset,
                    "target_col": target_col,
                    "row_count": row_count,
                    "raster_features": rasters,
                    "temporal_alignment": temporal_alignment,
                    "steps": steps,
                },
                artifacts=artifacts,
                summary="Station-raster temporal alignment succeeded, but too few aligned samples remain for XGBoost.",
                diagnostics={"minimum_samples": min_samples, "temporal_rasters": temporal_rasters},
                next_actions=["Use a wider overlapping date range, more station observations, or additional temporal rasters."],
            ).to_dict()

    study_area_filter: dict[str, Any] = {}
    boundary_dataset = str(study_area_resolution.get("boundary_dataset") or "")
    if boundary_dataset:
        study_area_filter_result = _filter_training_by_boundary(
            manager,
            training_dataset=training_dataset,
            boundary_dataset=boundary_dataset,
            output_name=f"{prefix}_study_area_training",
        )
        steps.append(
            _step(
                "prepare_study_area_training_samples",
                {"training_dataset": training_dataset, "boundary_dataset": boundary_dataset, "output_name": f"{prefix}_study_area_training"},
                study_area_filter_result,
            )
        )
        artifacts.extend([item for item in study_area_filter_result.get("artifacts", []) if isinstance(item, dict)])
        if not study_area_filter_result.get("ok"):
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs={"training_dataset": training_dataset, "boundary_dataset": boundary_dataset, "output_prefix": output_prefix},
                error_code=str(study_area_filter_result.get("error_code") or "STUDY_AREA_FILTER_FAILED"),
                error_title="STM workflow failed",
                user_message=str(study_area_filter_result.get("user_message") or "Failed to filter station samples by study area."),
                diagnostics={"steps": steps, "study_area_resolution": study_area_resolution},
                next_actions=[str(item) for item in study_area_filter_result.get("next_actions", []) if str(item).strip()],
            ).to_dict()
        study_area_filter = dict(study_area_filter_result.get("outputs") or {})
        training_dataset = str(study_area_filter.get("result_dataset") or training_dataset)
        row_count = int(study_area_filter.get("row_count") or 0)
        if row_count < int(min_samples):
            return tool_result_ok(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs={"archive_path": archive_path, "raster_names": ",".join(rasters), "output_prefix": output_prefix},
                outputs={
                    "status": "needs_more_samples_after_study_area_filter",
                    "source_archive": archive_path,
                    "training_dataset": training_dataset,
                    "target_col": target_col,
                    "row_count": row_count,
                    "raster_features": rasters,
                    "temporal_alignment": temporal_alignment,
                    "temporal_composites": temporal_composites,
                    "study_area_resolution": study_area_resolution,
                    "study_area_filter": study_area_filter,
                    "steps": steps,
                },
                artifacts=artifacts,
                summary="Study-area boundary filtering succeeded, but too few samples remain for XGBoost.",
                diagnostics={"minimum_samples": min_samples},
                next_actions=["Use a larger study area, more station observations, or inspect whether station coordinates match the boundary."],
            ).to_dict()

    if temporal_rasters:
        temporal_result = _extract_temporal_station_covariates(
            manager,
            training_dataset=training_dataset,
            temporal_rasters=temporal_rasters,
            output_name=f"{prefix}_temporal_training",
        )
        steps.append(
            _step(
                "extract_temporal_station_covariates",
                {"training_dataset": training_dataset, "temporal_rasters": ",".join(temporal_rasters), "output_name": f"{prefix}_temporal_training"},
                temporal_result,
            )
        )
        artifacts.extend([item for item in temporal_result.get("artifacts", []) if isinstance(item, dict)])
        if not temporal_result.get("ok"):
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs={"training_dataset": training_dataset, "temporal_rasters": temporal_rasters, "output_prefix": output_prefix},
                error_code=str(temporal_result.get("error_code") or "TEMPORAL_STATION_FEATURES_FAILED"),
                error_title="STM workflow failed",
                user_message=str(temporal_result.get("user_message") or "Failed to extract temporal station covariates."),
                diagnostics={"steps": steps, "temporal_alignment": temporal_alignment},
                next_actions=[str(item) for item in temporal_result.get("next_actions", []) if str(item).strip()],
            ).to_dict()
        temporal_feature_summary = dict(temporal_result.get("outputs") or {})
        temporal_feature_cols = [str(item) for item in temporal_feature_summary.get("temporal_feature_cols") or [] if str(item).strip()]
        training_dataset = str(temporal_feature_summary.get("result_dataset") or training_dataset)
        row_count = int(temporal_feature_summary.get("row_count") or row_count)

    feature_rasters = [raster_name for raster_name in rasters if raster_name not in set(temporal_rasters)]
    if feature_rasters:
        coverage_point_args = {
            "dataset_name": training_dataset,
            "x_col": "lon",
            "y_col": "lat",
            "crs": "EPSG:4326",
            "output_name": f"{prefix}_coverage_points",
        }
        coverage_point_result = _invoke(tool_map, "table_to_points", coverage_point_args)
        steps.append(_step("table_to_points", coverage_point_args, coverage_point_result))
        artifacts.extend([item for item in coverage_point_result.get("artifacts", []) if isinstance(item, dict)])
        if not coverage_point_result.get("ok"):
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs=coverage_point_args,
                error_code=str(coverage_point_result.get("error_code") or "POINT_CONVERSION_FAILED"),
                error_title="STM workflow failed",
                user_message=str(coverage_point_result.get("user_message") or "Failed to convert unified preprocessing table to points."),
                diagnostics={"steps": steps},
            ).to_dict()
        coverage_point_dataset = str(coverage_point_result.get("outputs", {}).get("result_dataset") or "")

        coverage_args = {
            "point_name": coverage_point_dataset,
            "raster_names": ",".join(feature_rasters),
            "output_name": f"{prefix}_coverage_samples",
            "id_cols": "",
            "output_mode": "wide",
            "value_field_prefix": "raster",
        }
        coverage_result = _invoke(tool_map, "batch_register_points_to_rasters", coverage_args)
        steps.append(_step("batch_register_points_to_rasters", coverage_args, coverage_result))
        artifacts.extend([item for item in coverage_result.get("artifacts", []) if isinstance(item, dict)])
        if not coverage_result.get("ok"):
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs=coverage_args,
                error_code=str(coverage_result.get("error_code") or "UNIFIED_COVERAGE_SAMPLING_FAILED"),
                error_title="STM workflow failed",
                user_message=str(coverage_result.get("user_message") or "Failed to sample base rasters for unified preprocessing."),
                diagnostics={"steps": steps},
                next_actions=[str(item) for item in coverage_result.get("next_actions", []) if str(item).strip()],
            ).to_dict()
        coverage_dataset = str(coverage_result.get("outputs", {}).get("result_dataset") or "")
        coverage_fields = [str(item) for item in coverage_result.get("outputs", {}).get("fields") or [] if str(item).strip()]
        unified_result = _unified_training_filter(
            manager,
            training_dataset=training_dataset,
            coverage_dataset=coverage_dataset,
            raster_fields=coverage_fields,
            output_name=f"{prefix}_unified_training",
        )
        steps.append(_step("prepare_unified_training_samples", {"training_dataset": training_dataset, "coverage_dataset": coverage_dataset, "output_name": f"{prefix}_unified_training"}, unified_result))
        artifacts.extend([item for item in unified_result.get("artifacts", []) if isinstance(item, dict)])
        if not unified_result.get("ok"):
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs={"training_dataset": training_dataset, "coverage_dataset": coverage_dataset, "output_prefix": output_prefix},
                error_code=str(unified_result.get("error_code") or "UNIFIED_PREPROCESSING_FAILED"),
                error_title="STM workflow failed",
                user_message=str(unified_result.get("user_message") or "Failed to prepare unified training samples before deriving features."),
                diagnostics={"steps": steps},
                next_actions=[str(item) for item in unified_result.get("next_actions", []) if str(item).strip()],
            ).to_dict()
        unified_outputs = dict(unified_result.get("outputs") or {})
    else:
        training_dataset = manager.put_table(f"{prefix}_unified_training", manager.get_table(training_dataset))
        unified_outputs = {
            "result_dataset": training_dataset,
            "row_count": int(row_count),
            "removed_row_count": 0,
            "removed_station_count": 0,
            "removed_stations": [],
            "required_raster_fields": [],
            "mask_raster_fields": [],
            "filter_method": "temporal_station_features_only",
        }
    if study_area_filter:
        unified_outputs["filter_method"] = "study_area_boundary"
        unified_outputs["boundary_dataset"] = boundary_dataset
        unified_outputs["study_area_resolution"] = study_area_resolution
        unified_outputs["study_area_filter"] = study_area_filter
        unified_outputs["raster_filter"] = {
            "removed_row_count": int(unified_outputs.get("removed_row_count") or 0),
            "removed_station_count": int(unified_outputs.get("removed_station_count") or 0),
            "removed_stations": list(unified_outputs.get("removed_stations") or []),
            "required_raster_fields": list(unified_outputs.get("required_raster_fields") or []),
            "mask_raster_fields": list(unified_outputs.get("mask_raster_fields") or []),
        }
        unified_outputs["total_removed_row_count"] = int(study_area_filter.get("removed_row_count") or 0) + int(unified_outputs.get("removed_row_count") or 0)
        unified_outputs["total_removed_station_count"] = len(
            set(study_area_filter.get("removed_stations") or []) | set(unified_outputs.get("removed_stations") or [])
        )
    training_dataset = str(unified_outputs.get("result_dataset") or training_dataset)
    row_count = int(unified_outputs.get("row_count") or 0)
    if row_count < int(min_samples):
        return tool_result_ok(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs={"archive_path": archive_path, "raster_names": ",".join(feature_rasters), "output_prefix": output_prefix},
            outputs={
                "status": "needs_more_samples_after_unified_preprocessing",
                "source_archive": archive_path,
                "training_dataset": training_dataset,
                "target_col": target_col,
                "row_count": row_count,
                "raster_features": feature_rasters,
                "temporal_alignment": temporal_alignment,
                "temporal_composites": temporal_composites,
                "temporal_feature_cols": temporal_feature_cols,
                "temporal_feature_summary": temporal_feature_summary,
                "study_area_resolution": study_area_resolution,
                "unified_preprocessing": unified_outputs,
                "steps": steps,
            },
            artifacts=artifacts,
            summary="Unified preprocessing succeeded, but too few valid samples remain for XGBoost.",
            diagnostics={"minimum_samples": min_samples},
            next_actions=["Relax the spatial mask, use more stations, or inspect raster coverage and NoData values."],
        ).to_dict()

    for raster_name in list(rasters):
        if not _is_dem_like_raster(manager, raster_name):
            continue
        derivative_args = {
            "dem_name": raster_name,
            "output_prefix": f"{prefix}_{_safe_name(raster_name)}",
            "derivatives": "slope,tpi,twi",
        }
        derivative_result = _invoke(tool_map, "dem_terrain_derivatives", derivative_args)
        steps.append(_step("dem_terrain_derivatives", derivative_args, derivative_result))
        artifacts.extend([item for item in derivative_result.get("artifacts", []) if isinstance(item, dict)])
        if not derivative_result.get("ok"):
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs=derivative_args,
                error_code=str(derivative_result.get("error_code") or "DEM_TERRAIN_DERIVATIVE_FAILED"),
                error_title="STM workflow failed",
                user_message=str(derivative_result.get("user_message") or "Failed to derive DEM-only terrain factors from DEM."),
                diagnostics={"steps": steps, "source_dem": raster_name},
                next_actions=[str(item) for item in derivative_result.get("next_actions", []) if str(item).strip()],
            ).to_dict()
        derived_datasets = [
            str(item)
            for item in derivative_result.get("outputs", {}).get("datasets", [])
            if str(item).strip()
        ]
        _append_unique(feature_rasters, derived_datasets)

    point_args = {
        "dataset_name": training_dataset,
        "x_col": "lon",
        "y_col": "lat",
        "crs": "EPSG:4326",
        "output_name": f"{prefix}_points",
    }
    point_result = _invoke(tool_map, "table_to_points", point_args)
    steps.append(_step("table_to_points", point_args, point_result))
    artifacts.extend([item for item in point_result.get("artifacts", []) if isinstance(item, dict)])
    if not point_result.get("ok"):
        return tool_result_error(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs=point_args,
            error_code=str(point_result.get("error_code") or "POINT_CONVERSION_FAILED"),
            error_title="STM workflow failed",
            user_message=str(point_result.get("user_message") or "Failed to convert training table to points."),
            diagnostics={"steps": steps},
        ).to_dict()
    point_dataset = str(point_result.get("outputs", {}).get("result_dataset") or "")

    raster_fields: list[str] = []
    if feature_rasters:
        feature_args = {
            "point_name": point_dataset,
            "raster_names": ",".join(feature_rasters),
            "output_name": f"{prefix}_features",
            "id_cols": "",
            "output_mode": "wide",
            "value_field_prefix": "raster",
        }
        feature_result = _invoke(tool_map, "batch_register_points_to_rasters", feature_args)
        steps.append(_step("batch_register_points_to_rasters", feature_args, feature_result))
        artifacts.extend([item for item in feature_result.get("artifacts", []) if isinstance(item, dict)])
        if not feature_result.get("ok"):
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs=feature_args,
                error_code=str(feature_result.get("error_code") or "RASTER_FEATURE_EXTRACTION_FAILED"),
                error_title="STM workflow failed",
                user_message=str(feature_result.get("user_message") or "Failed to sample raster features at station points."),
                diagnostics={"steps": steps},
                next_actions=[str(item) for item in feature_result.get("next_actions", []) if str(item).strip()],
            ).to_dict()
        feature_dataset = str(feature_result.get("outputs", {}).get("result_dataset") or "")
        raster_fields = [str(item) for item in feature_result.get("outputs", {}).get("fields") or [] if str(item).strip()]
    else:
        feature_dataset = point_dataset
    feature_cols = [field for field in ["lon", "lat", "elevation_m", *temporal_feature_cols, *raster_fields] if field]
    if not raster_fields and not temporal_feature_cols:
        return tool_result_ok(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs={"archive_path": archive_path, "raster_names": ",".join(feature_rasters), "output_prefix": output_prefix},
            outputs={
                "status": "needs_raster_features",
                "source_archive": archive_path,
                "training_dataset": training_dataset,
                "point_dataset": point_dataset,
                "feature_dataset": feature_dataset,
                "target_col": target_col,
                "row_count": row_count,
                "raster_features": feature_rasters,
                "temporal_feature_cols": temporal_feature_cols,
                "steps": steps,
            },
            artifacts=artifacts,
            summary="Raster sampling completed but did not add usable feature fields.",
            next_actions=["Check raster overlap with station points, CRS, NoData values, and raster band selection."],
        ).to_dict()

    model_dataset = feature_dataset
    model_feature_cols = list(feature_cols)
    categorical_feature_cols = _categorical_raster_feature_fields(manager, feature_rasters, raster_fields)
    if categorical_feature_cols:
        try:
            model_df, geometry, model_data_type = _read_model_feature_dataset(manager, model_dataset)
            for field in categorical_feature_cols:
                values = pd.to_numeric(model_df[field], errors="coerce")
                encoded = values.round().astype("Int64").astype("string").astype(object)
                model_df[field] = encoded.where(values.notna(), np.nan)
            model_dataset = _save_model_feature_dataset(manager, f"{prefix}_model_features", model_df, geometry, model_data_type)
            steps.append(
                {
                    "tool_name": "encode_categorical_raster_features",
                    "args": {
                        "dataset_name": feature_dataset,
                        "categorical_fields": ",".join(categorical_feature_cols),
                        "output_name": f"{prefix}_model_features",
                    },
                    "ok": True,
                    "outputs": {
                        "result_dataset": model_dataset,
                        "categorical_fields": categorical_feature_cols,
                    },
                    "error_code": "",
                    "user_message": "",
                }
            )
        except Exception as exc:
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs={"dataset_name": feature_dataset, "categorical_fields": categorical_feature_cols, "output_prefix": output_prefix},
                error_code="CATEGORICAL_RASTER_FEATURES_FAILED",
                error_title="STM workflow failed",
                user_message="Failed to convert categorical raster fields before XGBoost modeling.",
                technical_detail=f"{type(exc).__name__}: {exc}",
                diagnostics={"steps": steps, "feature_cols": feature_cols},
                next_actions=["Inspect LULC/landcover sampled values and rerun with valid categorical raster fields."],
            ).to_dict()

    aspect_fields = [field for field in raster_fields if "aspect" in field.lower()]
    if _as_bool(encode_aspect_circular) and aspect_fields:
        try:
            model_df, geometry, model_data_type = _read_model_feature_dataset(manager, model_dataset)
            added_fields: list[str] = []
            for field in aspect_fields:
                values = pd.to_numeric(model_df[field], errors="coerce")
                radians = np.deg2rad(values)
                sin_field = f"{field}_sin"
                cos_field = f"{field}_cos"
                model_df[sin_field] = np.sin(radians)
                model_df[cos_field] = np.cos(radians)
                added_fields.extend([sin_field, cos_field])
            model_feature_cols = [
                field
                for field in feature_cols
                if field not in set(aspect_fields)
            ] + added_fields
            aspect_output_name = f"{prefix}_model_features_aspect" if model_dataset != feature_dataset else f"{prefix}_model_features"
            model_dataset = _save_model_feature_dataset(manager, aspect_output_name, model_df, geometry, model_data_type)
            steps.append(
                {
                    "tool_name": "engineer_aspect_circular_features",
                    "args": {
                        "dataset_name": model_dataset,
                        "aspect_fields": ",".join(aspect_fields),
                        "output_name": aspect_output_name,
                    },
                    "ok": True,
                    "outputs": {
                        "result_dataset": model_dataset,
                        "aspect_fields": aspect_fields,
                        "added_fields": added_fields,
                    },
                    "error_code": "",
                    "user_message": "",
                }
            )
        except Exception as exc:
            return tool_result_error(
                "run_stm_soil_moisture_xgboost_workflow",
                inputs={"dataset_name": feature_dataset, "aspect_fields": aspect_fields, "output_prefix": output_prefix},
                error_code="ASPECT_CIRCULAR_FEATURES_FAILED",
                error_title="STM workflow failed",
                user_message="Failed to convert aspect fields into circular sin/cos features.",
                technical_detail=f"{type(exc).__name__}: {exc}",
                diagnostics={"steps": steps, "feature_cols": feature_cols},
                next_actions=["Disable encode_aspect_circular or inspect the sampled aspect columns for nonnumeric values."],
            ).to_dict()

    xgb_args = {
        "dataset_name": model_dataset,
        "target_col": target_col,
        "feature_cols": ",".join(model_feature_cols),
        "output_name": f"{prefix}_xgb",
        "task_type": "regression",
    }
    xgb_result = _invoke(tool_map, "generic_xgboost_workflow", xgb_args)
    steps.append(_step("generic_xgboost_workflow", xgb_args, xgb_result))
    artifacts.extend([item for item in xgb_result.get("artifacts", []) if isinstance(item, dict)])
    if not xgb_result.get("ok"):
        return tool_result_error(
            "run_stm_soil_moisture_xgboost_workflow",
            inputs=xgb_args,
            error_code=str(xgb_result.get("error_code") or "XGBOOST_WORKFLOW_FAILED"),
            error_title="STM workflow failed",
            user_message=str(xgb_result.get("user_message") or "XGBoost modeling failed."),
            diagnostics={"steps": steps, "feature_cols": model_feature_cols},
            next_actions=[str(item) for item in xgb_result.get("next_actions", []) if str(item).strip()],
        ).to_dict()

    prediction_result: dict[str, Any] = {
        "ok": False,
        "status": "skipped",
        "reason": "prediction_feature_mapping_incomplete",
    }
    prediction_map_layers: list[dict[str, Any]] = []
    prediction_images: list[dict[str, Any]] = []
    prediction_date = _representative_prediction_date(
        requested=representative_date,
        temporal_alignment=temporal_alignment,
        year=year,
    )
    prediction_mapping, temporal_missing = _prediction_feature_mapping(
        manager,
        model_feature_cols=model_feature_cols,
        feature_rasters=feature_rasters,
        temporal_rasters=temporal_rasters,
    )
    if temporal_missing:
        temporal_mapping = _build_temporal_prediction_feature_rasters(
            tool_map,
            manager,
            temporal_rasters=temporal_rasters,
            model_feature_cols=model_feature_cols,
            representative_date=prediction_date,
            output_prefix=prefix,
            boundary_dataset=boundary_dataset,
            steps=steps,
            artifacts=artifacts,
        )
        prediction_mapping.update(temporal_mapping)
    auto_features = {"lon", "lat", "day_of_year", "month", "year"}
    missing_prediction_features = [
        field for field in model_feature_cols if field not in prediction_mapping and field not in auto_features
    ]
    model_path = _model_artifact_path(xgb_result)
    if model_path and not missing_prediction_features:
        prediction_args = {
            "model_path": model_path,
            "feature_rasters": ",".join(f"{feature}={dataset}" for feature, dataset in prediction_mapping.items()),
            "output_name": f"{prefix}_prediction",
            "boundary_name": boundary_dataset,
            "representative_date": prediction_date,
        }
        prediction_result = _invoke(tool_map, "predict_xgboost_raster_map", prediction_args)
        steps.append(_step("predict_xgboost_raster_map", prediction_args, prediction_result))
        artifacts.extend([item for item in prediction_result.get("artifacts", []) if isinstance(item, dict)])
        prediction_map_layers = [item for item in prediction_result.get("map_layers", []) if isinstance(item, dict)]
        prediction_images = [item for item in prediction_result.get("images", []) if isinstance(item, dict)]
    else:
        prediction_result = {
            "ok": False,
            "status": "skipped",
            "reason": "prediction_feature_mapping_incomplete" if model_path else "model_artifact_missing",
            "outputs": {
                "representative_date": prediction_date,
                "feature_rasters": prediction_mapping,
                "missing_features": missing_prediction_features,
                "model_path_found": bool(model_path),
            },
        }

    prediction_outputs = prediction_result.get("outputs", {}) if isinstance(prediction_result, dict) else {}
    return tool_result_ok(
        "run_stm_soil_moisture_xgboost_workflow",
        inputs={"archive_path": archive_path, "raster_names": ",".join(feature_rasters), "output_prefix": output_prefix},
        outputs={
            "status": "modeled",
            "source_archive": archive_path,
            "training_dataset": training_dataset,
            "point_dataset": point_dataset,
            "feature_dataset": feature_dataset,
            "model_dataset": model_dataset,
            "target_col": target_col,
            "feature_cols": feature_cols,
            "model_feature_cols": model_feature_cols,
            "temporal_feature_cols": temporal_feature_cols,
            "temporal_feature_summary": temporal_feature_summary,
            "categorical_feature_cols": categorical_feature_cols,
            "raster_features": feature_rasters,
            "row_count": row_count,
            "temporal_alignment": temporal_alignment,
            "temporal_composites": temporal_composites,
            "study_area_resolution": study_area_resolution,
            "unified_preprocessing": unified_outputs,
            "model_result": xgb_result,
            "prediction_status": "mapped" if prediction_result.get("ok") else str(prediction_result.get("reason") or prediction_result.get("status") or "skipped"),
            "prediction_result": prediction_result,
            "prediction_raster": str(prediction_outputs.get("result_dataset") or ""),
            "prediction_preview": str(prediction_outputs.get("preview_path") or ""),
            "prediction_summary": str(prediction_outputs.get("summary_path") or ""),
            "prediction_representative_date": prediction_date,
            "steps": steps,
        },
        artifacts=artifacts,
        map_layers=prediction_map_layers,
        images=prediction_images,
        summary="Completed STM station training table, point conversion, raster feature sampling, and XGBoost modeling.",
        diagnostics={"step_count": len(steps), "raster_count": len(feature_rasters), "minimum_samples": min_samples},
        next_actions=["Review model metrics, feature importance, and prediction maps before using the model for interpretation."],
    ).to_dict()
