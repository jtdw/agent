from __future__ import annotations

import re
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
    derived_tokens = ("slope", "aspect", "tpi", "tri")
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


def _raster_temporal_dates(manager: Any, raster_name: str) -> set[str]:
    dates: set[str] = set()
    try:
        import rasterio

        with rasterio.open(manager.get_raster_path(raster_name)) as src:
            for description in src.descriptions or ():
                date_value = _date_from_temporal_text(str(description or ""))
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
    if "ndvi" in lower:
        return "ndvi"
    if "evi" in lower:
        return "evi"
    if "lst" in lower:
        return "lst_celsius"
    if "precip" in lower or "rain" in lower:
        return "precipitation_mm"
    return "generic"


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

    temporal_rasters = _temporal_raster_names(manager, rasters)
    temporal_alignment: dict[str, Any] = {}
    temporal_composites: dict[str, str] = {}
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

        selected_time_range = temporal_alignment.get("selected_time_range") if isinstance(temporal_alignment.get("selected_time_range"), dict) else {}
        for raster_name in temporal_rasters:
            composite_args = {
                "raster_names": raster_name,
                "output_name": f"{prefix}_{_safe_name(raster_name)}_composite",
                "covariate_type": _covariate_type_for_raster(raster_name),
                "start_date": str(selected_time_range.get("start") or ""),
                "end_date": str(selected_time_range.get("end") or ""),
            }
            composite_result = _invoke(tool_map, "build_temporal_covariate_composite", composite_args)
            steps.append(_step("build_temporal_covariate_composite", composite_args, composite_result))
            artifacts.extend([item for item in composite_result.get("artifacts", []) if isinstance(item, dict)])
            if not composite_result.get("ok"):
                return tool_result_error(
                    "run_stm_soil_moisture_xgboost_workflow",
                    inputs=composite_args,
                    error_code=str(composite_result.get("error_code") or "TEMPORAL_COMPOSITE_FAILED"),
                    error_title="STM workflow failed",
                    user_message=str(composite_result.get("user_message") or "Failed to build a temporal raster composite for aligned station dates."),
                    diagnostics={"steps": steps, "temporal_alignment": temporal_alignment},
                    next_actions=[str(item) for item in composite_result.get("next_actions", []) if str(item).strip()],
                ).to_dict()
            composite_dataset = str(composite_result.get("outputs", {}).get("result_dataset") or "")
            if composite_dataset:
                temporal_composites[raster_name] = composite_dataset

    feature_rasters = [temporal_composites.get(raster_name, raster_name) for raster_name in rasters]
    for raster_name in list(rasters):
        if not _is_dem_like_raster(manager, raster_name):
            continue
        derivative_args = {
            "dem_name": raster_name,
            "output_prefix": f"{prefix}_{_safe_name(raster_name)}",
            "derivatives": "slope,aspect",
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
                user_message=str(derivative_result.get("user_message") or "Failed to derive slope and aspect from DEM."),
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
    feature_cols = [field for field in ["lon", "lat", "elevation_m", *raster_fields] if field]
    if not raster_fields:
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
                "steps": steps,
            },
            artifacts=artifacts,
            summary="Raster sampling completed but did not add usable feature fields.",
            next_actions=["Check raster overlap with station points, CRS, NoData values, and raster band selection."],
        ).to_dict()

    model_dataset = feature_dataset
    model_feature_cols = list(feature_cols)
    aspect_fields = [field for field in raster_fields if "aspect" in field.lower()]
    if _as_bool(encode_aspect_circular) and aspect_fields:
        try:
            feature_record = manager.get(feature_dataset)
            if feature_record.data_type == "table":
                model_df = manager.get_table(feature_dataset)
            elif feature_record.data_type == "vector":
                model_df = pd.DataFrame(manager.get_vector(feature_dataset).drop(columns=["geometry"], errors="ignore"))
            else:
                raise TypeError(f"{feature_dataset} is not a table or vector dataset")
            added_fields: list[str] = []
            for field in aspect_fields:
                values = pd.to_numeric(model_df[field], errors="coerce")
                radians = np.deg2rad(values)
                sin_field = f"{field}_sin"
                cos_field = f"{field}_cos"
                model_df[sin_field] = np.sin(radians)
                model_df[cos_field] = np.cos(radians)
                added_fields.extend([sin_field, cos_field])
            model_dataset = manager.put_table(f"{prefix}_model_features", model_df)
            model_feature_cols = [
                field
                for field in feature_cols
                if field not in set(aspect_fields)
            ] + added_fields
            steps.append(
                {
                    "tool_name": "engineer_aspect_circular_features",
                    "args": {
                        "dataset_name": feature_dataset,
                        "aspect_fields": ",".join(aspect_fields),
                        "output_name": f"{prefix}_model_features",
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
            "raster_features": feature_rasters,
            "row_count": row_count,
            "temporal_alignment": temporal_alignment,
            "temporal_composites": temporal_composites,
            "model_result": xgb_result,
            "steps": steps,
        },
        artifacts=artifacts,
        summary="Completed STM station training table, point conversion, raster feature sampling, and XGBoost modeling.",
        diagnostics={"step_count": len(steps), "raster_count": len(feature_rasters), "minimum_samples": min_samples},
        next_actions=["Review model metrics, feature importance, and prediction artifacts before using the model for interpretation."],
    ).to_dict()
