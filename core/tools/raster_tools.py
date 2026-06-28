from __future__ import annotations

import ast
import json
import warnings
from typing import Any

from core.tools import raster_helpers as _helpers

RASTER_TOOL_NAMES = {
    'raster_basic_stats',
    'raster_covariate_quality_check',
    'build_temporal_covariate_composite',
    'raster_zonal_stats',
    'clip_raster_by_vector',
    'raster_mosaic',
    'dem_terrain_derivatives',
    'raster_reproject',
    'raster_algebra',
    'extract_raster_values_to_points',
    'batch_register_points_to_rasters',
}

_LEGACY_DEPENDENCIES = (
    'Any',
    'ArtifactInfo',
    'MemoryFile',
    'Path',
    '_artifact_safe_name',
    '_dataset_map_kind',
    '_extract_date_from_name',
    '_geometry_to_sample_point',
    '_map_layer_id',
    '_map_ready_outputs',
    '_parse_columns',
    '_sample_raster_to_geometries',
    '_save_json_artifact',
    '_spatial_meta_for_record',
    '_tool_error_from_validation',
    '_tool_internal_error',
    '_validate_columns',
    'contextlib',
    'mask',
    'np',
    'pd',
    'raster_merge',
    'rasterio',
    're',
    'tool',
    'tool_result_error',
    'tool_result_ok',
    'uuid4',
    'validate_crs',
    'validate_dataset_exists',
    'validate_geometry_type',
    'validate_output_path',
    'validate_raster_readable',
    'validate_vector_readable',
)

for _name in _LEGACY_DEPENDENCIES:
    globals()[_name] = getattr(_helpers, _name)


_RASTER_ALGEBRA_NP_FUNCTIONS = {
    "where",
    "clip",
    "log",
    "log1p",
    "sqrt",
    "abs",
    "minimum",
    "maximum",
    "sin",
    "cos",
    "tan",
}

_COVARIATE_TYPE_DEFAULT_RANGES: dict[str, tuple[float | None, float | None]] = {
    "ndvi": (-1.0, 1.0),
    "evi": (-1.0, 1.0),
    "lst_celsius": (-80.0, 80.0),
    "lst_kelvin": (180.0, 350.0),
    "precipitation_mm": (0.0, None),
}

_CATEGORICAL_COVARIATE_TYPES = {"categorical", "landcover", "land_use", "soil_type"}

_TEMPORAL_COMPOSITE_DEFAULT_METHODS = {
    "ndvi": "max",
    "evi": "max",
    "lst_celsius": "median",
    "lst_kelvin": "median",
    "precipitation_mm": "sum",
    "generic": "median",
}

_TEMPORAL_COMPOSITE_METHODS = {"max", "median", "mean", "sum", "min"}


def _validate_raster_algebra_ast(parsed: ast.Expression, *, variables: set[str]) -> None:
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Tuple,
        ast.List,
        ast.Attribute,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
    )
    forbidden_nodes = (
        ast.Subscript,
        ast.Lambda,
        ast.IfExp,
        ast.Dict,
        ast.Set,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.Await,
        ast.Yield,
        ast.NamedExpr,
    )
    for node in ast.walk(parsed):
        if isinstance(node, forbidden_nodes):
            raise ValueError("栅格表达式不允许下标、lambda、推导式或复杂 Python 语法。")
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"栅格表达式包含不支持的元素: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in variables and node.id != "np":
            raise ValueError(f"栅格表达式引用了未声明的变量: {node.id}")
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or node.value.id != "np" or node.attr not in _RASTER_ALGEBRA_NP_FUNCTIONS:
                raise ValueError(f"栅格表达式只允许白名单 NumPy 函数: np.{node.attr}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Attribute):
                raise ValueError("栅格表达式只允许调用白名单 NumPy 函数。")
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "np" or node.func.attr not in _RASTER_ALGEBRA_NP_FUNCTIONS:
                raise ValueError(f"栅格表达式只允许调用白名单 NumPy 函数: np.{node.func.attr}")

def _parse_expected_ranges(value: str) -> dict[str, tuple[float | None, float | None]]:
    ranges: dict[str, tuple[float | None, float | None]] = {}
    for item in str(value or "").replace(";", ",").split(","):
        token = item.strip()
        if not token:
            continue
        if "=" not in token or ":" not in token:
            raise ValueError(f"expected range must use raster=min:max: {token}")
        name, raw_range = token.split("=", 1)
        lower, upper = raw_range.split(":", 1)
        clean_name = name.strip()
        if not clean_name:
            raise ValueError(f"expected range is missing raster name: {token}")
        ranges[clean_name] = (float(lower), float(upper))
    return ranges


def _normalize_covariate_type(value: str) -> str:
    return str(value or "generic").strip().lower() or "generic"


def _coerce_category(value: float) -> int | float:
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else numeric


def _parse_expected_categories(value: str) -> set[int | float]:
    categories: set[int | float] = set()
    for item in str(value or "").replace(";", ",").split(","):
        token = item.strip()
        if not token:
            continue
        categories.add(_coerce_category(float(token)))
    return categories


def _default_temporal_composite_method(covariate_type: str, method: str) -> str:
    clean_method = str(method or "").strip().lower()
    if clean_method:
        return clean_method
    return _TEMPORAL_COMPOSITE_DEFAULT_METHODS.get(covariate_type, "median")


def _raster_grid_signature(src: Any) -> dict[str, Any]:
    return {
        "width": int(src.width),
        "height": int(src.height),
        "crs": str(src.crs) if src.crs else "",
        "transform": tuple(float(value) for value in src.transform[:6]),
    }


def _same_raster_grid(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("width") == right.get("width")
        and left.get("height") == right.get("height")
        and left.get("crs") == right.get("crs")
        and np.allclose(left.get("transform") or (), right.get("transform") or (), rtol=0.0, atol=1e-9)
    )


def build_raster_tools(manager: Any, *, legacy_tools: list[Any] | None = None) -> list[Any]:

    def _default_nodata_for_dtype(dtype: str) -> float | int:
        raster_dtype = np.dtype(dtype)
        if np.issubdtype(raster_dtype, np.floating):
            return np.nan
        if np.issubdtype(raster_dtype, np.unsignedinteger):
            return 0
        return -9999


    def _write_raster_dataset_like(source_path: Path, output_name: str, data: np.ndarray, *, source_tool: str, meta_updates: dict[str, Any] | None = None) -> tuple[str, Path, dict[str, Any]]:
        output_stem = Path(output_name).stem if Path(output_name).suffix else output_name
        output_path = manager.derived_dir / f"{_artifact_safe_name(output_stem)}.tif"
        with rasterio.open(source_path) as src:
            profile = src.profile.copy()
            profile.update(count=1, dtype="float32", nodata=-9999.0)
            with rasterio.open(output_path, "w", **profile) as dst:
                arr = np.asarray(data, dtype="float32")
                arr = np.where(np.isfinite(arr), arr, -9999.0).astype("float32")
                dst.write(arr, 1)
        meta = {
            **(meta_updates or {}),
            "crs": str(profile.get("crs")) if profile.get("crs") else None,
            "width": int(profile.get("width") or 0),
            "height": int(profile.get("height") or 0),
            "count": 1,
            "dtype": "float32",
            "nodata": -9999.0,
            "map_ready": True,
            "map_layer_id": _map_layer_id(output_stem),
            "layer_kind": _dataset_map_kind(output_stem, "raster"),
            "source_tool": source_tool,
        }
        stored_name = manager.put_raster_path(output_stem, output_path, meta=meta)
        spatial_meta = _spatial_meta_for_record(manager, stored_name, artifact_id=f"raster_{uuid4().hex[:10]}", source_tool=source_tool)
        return stored_name, output_path, spatial_meta


    @tool
    def raster_basic_stats(dataset_name: str, band: int = 1) -> str:
        """统计栅格某一波段的最小值、最大值、均值、标准差和有效像元数。"""
        inputs = {"dataset_name": dataset_name, "band": band}
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        if not errors:
            errors.extend(validate_raster_readable(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("raster_basic_stats", inputs, errors)
        try:
            band_value = int(band)
        except Exception:
            return tool_result_error(
                "raster_basic_stats",
                inputs=inputs,
                error_code="RASTER_BAND_INVALID",
                error_title="Invalid raster band",
                user_message="Band must be an integer starting from 1.",
                diagnostics={"band": band},
                next_actions=["Use band=1 for a single-band raster, or choose a valid band number."],
            ).to_json()
        try:
            raster_path = manager.get_raster_path(dataset_name)
            with rasterio.open(raster_path) as src:
                if band_value < 1 or band_value > src.count:
                    return tool_result_error(
                        "raster_basic_stats",
                        inputs=inputs,
                        error_code="RASTER_BAND_OUT_OF_RANGE",
                        error_title="Raster band out of range",
                        user_message=f"Dataset {dataset_name} has {src.count} band(s); band {band_value} cannot be read.",
                        diagnostics={"band": band_value, "band_count": int(src.count)},
                        next_actions=["Choose a band number between 1 and the raster band count."],
                    ).to_json()
                arr = src.read(band_value, masked=True)
                valid = arr.compressed()
                if valid.size == 0:
                    return tool_result_error(
                        "raster_basic_stats",
                        inputs=inputs,
                        error_code="RASTER_BAND_EMPTY",
                        error_title="Raster band has no valid pixels",
                        user_message=f"Band {band_value} of {dataset_name} has no valid pixels to summarize.",
                        diagnostics={"band": band_value},
                        next_actions=["Check NoData settings or choose another band/raster."],
                    ).to_json()
                result = {
                    "dataset": dataset_name,
                    "band": band_value,
                    "min": float(valid.min()),
                    "max": float(valid.max()),
                    "mean": float(valid.mean()),
                    "std": float(valid.std()),
                    "valid_count": int(valid.size),
                    "crs": str(src.crs) if src.crs else None,
                    "bounds": tuple(src.bounds),
                }
                manager.log_operation("栅格统计", f"{dataset_name} band {band_value}", "analysis")
                return tool_result_ok(
                    "raster_basic_stats",
                    inputs=inputs,
                    outputs=result,
                    summary=f"Calculated raster statistics for {dataset_name} band {band_value}.",
                    diagnostics={"path": str(raster_path), "band_count": int(src.count), "shape": [int(src.height), int(src.width)]},
                    next_actions=["Use these statistics for quality checks, threshold selection, or map interpretation."],
                ).to_json()
        except Exception as exc:
            return _tool_internal_error("raster_basic_stats", inputs, exc)


    @tool
    def raster_covariate_quality_check(
        raster_names: str,
        output_name: str,
        band: int = 1,
        min_valid_ratio: float = 0.6,
        expected_ranges: str = "",
        covariate_type: str = "generic",
        expected_categories: str = "",
    ) -> str:
        """Check daily raster covariates such as NDVI/LST for NoData coverage and value-range issues before modeling."""
        inputs = {
            "raster_names": raster_names,
            "output_name": output_name,
            "band": band,
            "min_valid_ratio": min_valid_ratio,
            "expected_ranges": expected_ranges,
            "covariate_type": covariate_type,
            "expected_categories": expected_categories,
        }
        raster_list = _parse_columns(raster_names)
        if not raster_list:
            return tool_result_error(
                "raster_covariate_quality_check",
                inputs=inputs,
                error_code="RASTER_INPUT_REQUIRED",
                error_title="Missing raster inputs",
                user_message="At least one raster dataset is required for covariate quality checking.",
                diagnostics={},
                next_actions=["Provide one or more raster dataset names separated by commas."],
            ).to_json()
        try:
            band_value = int(band)
            threshold = float(min_valid_ratio)
            range_rules = _parse_expected_ranges(expected_ranges)
            clean_covariate_type = _normalize_covariate_type(covariate_type)
            category_rules = _parse_expected_categories(expected_categories)
        except Exception as exc:
            return tool_result_error(
                "raster_covariate_quality_check",
                inputs=inputs,
                error_code="COVARIATE_QA_ARGS_INVALID",
                error_title="Invalid covariate QA arguments",
                user_message=str(exc),
                diagnostics={"band": band, "min_valid_ratio": min_valid_ratio, "expected_ranges": expected_ranges, "expected_categories": expected_categories},
                next_actions=["Use band as an integer, min_valid_ratio between 0 and 1, expected_ranges like ndvi=-1:1, and expected_categories like 1,2,3."],
            ).to_json()
        if not 0 <= threshold <= 1:
            return tool_result_error(
                "raster_covariate_quality_check",
                inputs=inputs,
                error_code="VALID_RATIO_THRESHOLD_INVALID",
                error_title="Invalid valid-ratio threshold",
                user_message="min_valid_ratio must be between 0 and 1.",
                diagnostics={"min_valid_ratio": min_valid_ratio},
                next_actions=["Use a threshold such as 0.6 for rough screening or 0.8 for stricter daily covariates."],
            ).to_json()
        errors: list[dict[str, Any]] = []
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        for raster_name in raster_list:
            errors.extend(validate_dataset_exists(manager, raster_name))
        if not errors:
            for raster_name in raster_list:
                errors.extend(validate_raster_readable(manager, raster_name))
        if errors:
            return _tool_error_from_validation("raster_covariate_quality_check", inputs, errors)

        try:
            summaries: list[dict[str, Any]] = []
            warnings: list[str] = []
            for raster_name in raster_list:
                raster_path = manager.get_raster_path(raster_name)
                with rasterio.open(raster_path) as src:
                    if band_value < 1 or band_value > src.count:
                        return tool_result_error(
                            "raster_covariate_quality_check",
                            inputs=inputs,
                            error_code="RASTER_BAND_OUT_OF_RANGE",
                            error_title="Raster band out of range",
                            user_message=f"Raster {raster_name} has {src.count} band(s); band {band_value} cannot be read.",
                            diagnostics={"raster": raster_name, "band": band_value, "band_count": int(src.count)},
                            next_actions=["Choose a band number between 1 and the raster band count."],
                        ).to_json()
                    arr = src.read(band_value, masked=True)
                    total_pixels = int(src.width * src.height)
                    valid = np.ma.array(arr).compressed().astype("float64")
                    valid_pixels = int(valid.size)
                    nodata_pixels = int(total_pixels - valid_pixels)
                    valid_ratio = float(valid_pixels / total_pixels) if total_pixels else 0.0
                    missing_ratio = float(nodata_pixels / total_pixels) if total_pixels else 1.0
                    data_model = "categorical" if clean_covariate_type in _CATEGORICAL_COVARIATE_TYPES else "continuous"
                    lower, upper = range_rules.get(raster_name, _COVARIATE_TYPE_DEFAULT_RANGES.get(clean_covariate_type, (None, None)))
                    out_of_range_pixels = 0
                    unexpected_category_pixels = 0
                    unexpected_categories: list[int | float] = []
                    unique_values: list[int | float] = []
                    if valid_pixels and data_model == "categorical":
                        unique_values = sorted({_coerce_category(value) for value in np.unique(valid).tolist()})
                        if category_rules:
                            unexpected_categories = [value for value in unique_values if value not in category_rules]
                            unexpected_category_pixels = int(np.count_nonzero([_coerce_category(value) not in category_rules for value in valid]))
                    elif valid_pixels:
                        below = (valid < float(lower)) if lower is not None else np.zeros(valid.shape, dtype=bool)
                        above = (valid > float(upper)) if upper is not None else np.zeros(valid.shape, dtype=bool)
                        out_of_range_pixels = int(np.count_nonzero(below | above))
                    quality = "ok"
                    reasons: list[str] = []
                    if valid_ratio < threshold:
                        quality = "failed"
                        reasons.append("valid_ratio_below_threshold")
                    if out_of_range_pixels > 0:
                        quality = "failed"
                        reasons.append("values_outside_expected_range")
                    if unexpected_category_pixels > 0:
                        quality = "failed"
                        reasons.append("unexpected_categories")
                    if quality == "ok" and nodata_pixels > 0:
                        quality = "warning"
                        reasons.append("nodata_present")
                    if quality != "ok":
                        warnings.append(f"{raster_name}: {', '.join(reasons)}")
                    summaries.append(
                        {
                            "raster_name": raster_name,
                            "covariate_type": clean_covariate_type,
                            "data_model": data_model,
                            "band": band_value,
                            "quality": quality,
                            "reasons": reasons,
                            "total_pixels": total_pixels,
                            "valid_pixels": valid_pixels,
                            "nodata_pixels": nodata_pixels,
                            "valid_ratio": valid_ratio,
                            "missing_ratio": missing_ratio,
                            "out_of_range_pixels": out_of_range_pixels,
                            "unexpected_category_pixels": unexpected_category_pixels,
                            "unexpected_categories": unexpected_categories,
                            "unique_class_count": int(len(unique_values)) if data_model == "categorical" else 0,
                            "expected_min": lower,
                            "expected_max": upper,
                            "min": float(np.nanmin(valid)) if valid_pixels else None,
                            "mean": float(np.nanmean(valid)) if valid_pixels else None,
                            "max": float(np.nanmax(valid)) if valid_pixels else None,
                            "crs": str(src.crs) if src.crs else "",
                            "width": int(src.width),
                            "height": int(src.height),
                            "nodata": float(src.nodata) if src.nodata is not None else None,
                        }
                    )
            if any(item["quality"] == "failed" for item in summaries):
                overall_quality = "failed"
            elif any(item["quality"] == "warning" for item in summaries):
                overall_quality = "warning"
            else:
                overall_quality = "ok"
            table_rows = []
            for item in summaries:
                row = dict(item)
                row["reasons"] = ",".join(str(reason) for reason in item.get("reasons", []))
                row["unexpected_categories"] = ",".join(str(value) for value in item.get("unexpected_categories", []))
                table_rows.append(row)
            summary_dataset = manager.put_table(output_name, pd.DataFrame(table_rows))
            summary_path = manager.derived_dir / f"{_artifact_safe_name(output_name)}_covariate_quality_summary.json"
            summary_payload = {
                "overall_quality": overall_quality,
                "min_valid_ratio": threshold,
                "covariate_type": clean_covariate_type,
                "expected_categories": sorted(category_rules),
                "raster_count": int(len(summaries)),
                "rasters": summaries,
                "recommended_workflow": "Use temporal compositing or gap filling before modeling when quality is warning or failed.",
            }
            summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            artifact = manager.register_artifact(
                path=str(summary_path),
                type="summary",
                title=f"{output_name} covariate quality summary",
                description="Daily raster covariate NoData and value-range QA summary.",
                quality_status=overall_quality,
                preview_available=True,
                dataset_id=summary_dataset,
                source_tool="raster_covariate_quality_check",
            )
            return tool_result_ok(
                "raster_covariate_quality_check",
                inputs=inputs,
                outputs={
                    "summary_dataset": summary_dataset,
                    "overall_quality": overall_quality,
                    "raster_count": int(len(summaries)),
                    "summary_path": str(summary_path),
                },
                artifacts=[artifact],
                tables=[{"table_id": summary_dataset, "title": summary_dataset}],
                summary=f"Checked {len(summaries)} raster covariate(s); overall quality is {overall_quality}.",
                diagnostics={"rasters": summaries, "min_valid_ratio": threshold, "covariate_type": clean_covariate_type},
                warnings=warnings,
                next_actions=[
                    "Use temporal compositing for daily NDVI/LST rasters with low valid coverage.",
                    "Run gap filling before XGBoost prediction when NoData or out-of-range pixels are present.",
                    "Keep valid-mask and fill-method diagnostics for downstream uncertainty analysis.",
                ],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("raster_covariate_quality_check", inputs, exc)


    @tool
    def build_temporal_covariate_composite(
        raster_names: str,
        output_name: str,
        covariate_type: str = "generic",
        method: str = "",
        band: int = 1,
        min_observations: int = 1,
        band_selection: str = "auto",
    ) -> str:
        """Build a same-grid temporal composite for daily raster covariates before modeling."""
        inputs = {
            "raster_names": raster_names,
            "output_name": output_name,
            "covariate_type": covariate_type,
            "method": method,
            "band": band,
            "min_observations": min_observations,
            "band_selection": band_selection,
        }
        raster_list = _parse_columns(raster_names)
        if not raster_list:
            return tool_result_error(
                "build_temporal_covariate_composite",
                inputs=inputs,
                error_code="RASTER_INPUT_REQUIRED",
                error_title="Missing raster inputs",
                user_message="At least one raster dataset is required for temporal compositing.",
                diagnostics={},
                next_actions=["Provide loaded raster dataset names separated by commas."],
            ).to_json()
        try:
            clean_covariate_type = _normalize_covariate_type(covariate_type)
            clean_method = _default_temporal_composite_method(clean_covariate_type, method)
            band_value = int(band)
            min_obs = int(min_observations)
            clean_band_selection = str(band_selection or "auto").strip().lower()
        except Exception as exc:
            return tool_result_error(
                "build_temporal_covariate_composite",
                inputs=inputs,
                error_code="TEMPORAL_COMPOSITE_ARGS_INVALID",
                error_title="Invalid temporal composite arguments",
                user_message=str(exc),
                diagnostics={"band": band, "min_observations": min_observations, "method": method},
                next_actions=["Use integer band/min_observations values and a supported composite method."],
            ).to_json()
        if clean_band_selection not in {"auto", "single", "all"}:
            return tool_result_error(
                "build_temporal_covariate_composite",
                inputs=inputs,
                error_code="BAND_SELECTION_UNSUPPORTED",
                error_title="Unsupported band selection",
                user_message="band_selection must be auto, single, or all.",
                diagnostics={"band_selection": band_selection},
                next_actions=["Use auto for daily multi-band rasters, single to read one band, or all to force all bands from one raster."],
            ).to_json()
        if clean_covariate_type in _CATEGORICAL_COVARIATE_TYPES:
            return tool_result_error(
                "build_temporal_covariate_composite",
                inputs=inputs,
                error_code="CATEGORICAL_COMPOSITE_UNSUPPORTED",
                error_title="Categorical temporal composite is not supported yet",
                user_message="Categorical rasters such as landcover need a mode or priority-rule composite, not continuous statistics.",
                diagnostics={"covariate_type": clean_covariate_type},
                next_actions=["Use this tool for continuous covariates such as NDVI, LST, and precipitation; handle categorical rasters with a dedicated mode workflow."],
            ).to_json()
        if clean_method not in _TEMPORAL_COMPOSITE_METHODS:
            return tool_result_error(
                "build_temporal_covariate_composite",
                inputs=inputs,
                error_code="TEMPORAL_COMPOSITE_METHOD_UNSUPPORTED",
                error_title="Unsupported composite method",
                user_message=f"Composite method must be one of: {', '.join(sorted(_TEMPORAL_COMPOSITE_METHODS))}.",
                diagnostics={"method": clean_method},
                next_actions=["Use max for NDVI/EVI, median for LST, sum for precipitation, or specify mean/min explicitly."],
            ).to_json()
        if min_obs < 1:
            return tool_result_error(
                "build_temporal_covariate_composite",
                inputs=inputs,
                error_code="MIN_OBSERVATIONS_INVALID",
                error_title="Invalid minimum observation count",
                user_message="min_observations must be at least 1.",
                diagnostics={"min_observations": min_observations},
                next_actions=["Use min_observations=1 for a permissive composite or a larger value for stricter quality control."],
            ).to_json()

        errors: list[dict[str, Any]] = []
        errors.extend(validate_output_path(manager.derived_dir, output_name, allowed_suffixes={".tif", ".tiff"}))
        for raster_name in raster_list:
            errors.extend(validate_dataset_exists(manager, raster_name))
        if not errors:
            for raster_name in raster_list:
                errors.extend(validate_raster_readable(manager, raster_name))
        if errors:
            return _tool_error_from_validation("build_temporal_covariate_composite", inputs, errors)

        try:
            arrays: list[np.ndarray] = []
            source_summaries: list[dict[str, Any]] = []
            source_bands: list[dict[str, Any]] = []
            reference_grid: dict[str, Any] | None = None
            first_path: Path | None = None
            input_layout = "multiple_single_band"
            for raster_name in raster_list:
                raster_path = manager.get_raster_path(raster_name)
                if first_path is None:
                    first_path = Path(raster_path)
                with rasterio.open(raster_path) as src:
                    use_all_bands = len(raster_list) == 1 and src.count > 1 and clean_band_selection in {"auto", "all"}
                    band_indexes = list(range(1, src.count + 1)) if use_all_bands else [band_value]
                    if use_all_bands:
                        input_layout = "single_multiband"
                    if any(index < 1 or index > src.count for index in band_indexes):
                        return tool_result_error(
                            "build_temporal_covariate_composite",
                            inputs=inputs,
                            error_code="RASTER_BAND_OUT_OF_RANGE",
                            error_title="Raster band out of range",
                            user_message=f"Raster {raster_name} has {src.count} band(s); band {band_value} cannot be read.",
                            diagnostics={"raster": raster_name, "band": band_value, "band_count": int(src.count)},
                            next_actions=["Choose a band number between 1 and the raster band count."],
                        ).to_json()
                    grid = _raster_grid_signature(src)
                    if reference_grid is None:
                        reference_grid = grid
                    elif not _same_raster_grid(reference_grid, grid):
                        return tool_result_error(
                            "build_temporal_covariate_composite",
                            inputs=inputs,
                            error_code="RASTER_GRID_MISMATCH",
                            error_title="Temporal rasters are not aligned",
                            user_message="All temporal composite inputs must have the same CRS, transform, width, and height.",
                            diagnostics={"reference": reference_grid, "mismatched_raster": raster_name, "mismatched_grid": grid},
                            next_actions=["Reproject/resample rasters to a common grid before running the temporal composite."],
                        ).to_json()
                    raster_valid_pixels = 0
                    for band_index in band_indexes:
                        band_arr = src.read(band_index, masked=True)
                        values = np.asarray(np.ma.array(band_arr).filled(np.nan), dtype="float32")
                        arrays.append(values)
                        band_valid_pixels = int(np.count_nonzero(np.isfinite(values)))
                        raster_valid_pixels += band_valid_pixels
                        source_bands.append(
                            {
                                "raster_name": raster_name,
                                "band": int(band_index),
                                "description": str(src.descriptions[band_index - 1] or ""),
                                "valid_pixels": band_valid_pixels,
                                "total_pixels": int(values.size),
                            }
                        )
                    source_summaries.append(
                        {
                            "raster_name": raster_name,
                            "path": str(raster_path),
                            "band_count": int(len(band_indexes)),
                            "valid_pixels": raster_valid_pixels,
                            "total_pixels": int(src.width * src.height * len(band_indexes)),
                            "crs": grid["crs"],
                            "width": grid["width"],
                            "height": grid["height"],
                        }
                    )

            stack = np.stack(arrays).astype("float32")
            valid_observation_count = np.count_nonzero(np.isfinite(stack), axis=0).astype("int16")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                if clean_method == "max":
                    composite = np.nanmax(stack, axis=0)
                elif clean_method == "median":
                    composite = np.nanmedian(stack, axis=0)
                elif clean_method == "mean":
                    composite = np.nanmean(stack, axis=0)
                elif clean_method == "sum":
                    composite = np.nansum(stack, axis=0)
                else:
                    composite = np.nanmin(stack, axis=0)
            composite = np.asarray(composite, dtype="float32")
            composite = np.where(valid_observation_count >= min_obs, composite, np.nan).astype("float32")
            valid_pixels = int(np.count_nonzero(np.isfinite(composite)))
            all_missing_pixels = int(np.count_nonzero(valid_observation_count == 0))
            below_min_observation_pixels = int(np.count_nonzero(valid_observation_count < min_obs))
            valid_values = composite[np.isfinite(composite)]
            statistics = {
                "min": float(valid_values.min()) if valid_values.size else None,
                "max": float(valid_values.max()) if valid_values.size else None,
                "mean": float(valid_values.mean()) if valid_values.size else None,
                "valid_count": valid_pixels,
            }
            stored_name, output_path, _ = _write_raster_dataset_like(
                first_path or manager.get_raster_path(raster_list[0]),
                output_name,
                composite,
                source_tool="build_temporal_covariate_composite",
                meta_updates={
                    "source_rasters": raster_list,
                    "source_band_count": int(len(arrays)),
                    "input_layout": input_layout,
                    "covariate_type": clean_covariate_type,
                    "composite_method": clean_method,
                    "min_observations": min_obs,
                },
            )
            summary_path = manager.derived_dir / f"{_artifact_safe_name(stored_name)}_temporal_composite_summary.json"
            summary_payload = {
                "result_dataset": stored_name,
                "covariate_type": clean_covariate_type,
                "method": clean_method,
                "band": band_value,
                "band_selection": clean_band_selection,
                "min_observations": min_obs,
                "source_raster_count": int(len(raster_list)),
                "source_band_count": int(len(arrays)),
                "input_layout": input_layout,
                "valid_pixel_count": valid_pixels,
                "all_missing_pixel_count": all_missing_pixels,
                "below_min_observation_pixels": below_min_observation_pixels,
                "statistics": statistics,
                "valid_observation_count": {
                    "min": int(valid_observation_count.min()) if valid_observation_count.size else 0,
                    "max": int(valid_observation_count.max()) if valid_observation_count.size else 0,
                    "mean": float(valid_observation_count.mean()) if valid_observation_count.size else 0.0,
                },
                "source_rasters": source_summaries,
                "source_bands": source_bands,
            }
            summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            summary_artifact = manager.register_artifact(
                path=str(summary_path),
                type="summary",
                title=f"{stored_name} temporal composite summary",
                description="Temporal raster covariate composite diagnostics.",
                quality_status="ok",
                preview_available=True,
                dataset_id=stored_name,
                source_tool="build_temporal_covariate_composite",
            )
            return tool_result_ok(
                "build_temporal_covariate_composite",
                inputs=inputs,
                outputs={
                    **_map_ready_outputs(manager, stored_name, source_tool="build_temporal_covariate_composite"),
                    "path": str(output_path),
                    "summary_path": str(summary_path),
                    "method": clean_method,
                    "covariate_type": clean_covariate_type,
                    "source_raster_count": int(len(raster_list)),
                    "source_band_count": int(len(arrays)),
                    "input_layout": input_layout,
                    "valid_pixel_count": valid_pixels,
                    "all_missing_pixel_count": all_missing_pixels,
                    "below_min_observation_pixels": below_min_observation_pixels,
                    "statistics": statistics,
                },
                artifacts=[
                    ArtifactInfo(f"raster:{output_path.name}", str(output_path), "raster", f"{stored_name} temporal composite", "", "created", False),
                    summary_artifact,
                ],
                map_layers=[{"layer_id": _map_layer_id(stored_name), "name": stored_name, "dataset_name": stored_name, "type": "raster"}],
                summary=f"Built {clean_method} temporal composite {stored_name} from {len(raster_list)} raster(s).",
                diagnostics={
                    "source_rasters": source_summaries,
                    "source_bands": source_bands,
                    "method": clean_method,
                    "covariate_type": clean_covariate_type,
                    "valid_observation_count": summary_payload["valid_observation_count"],
                    "reference_grid": reference_grid or {},
                    "min_observations": min_obs,
                },
                next_actions=[
                    "Run raster_covariate_quality_check on the composite before modeling.",
                    "Use the composite raster as an XGBoost covariate when daily rasters contain gaps.",
                    "Keep the summary artifact with model evidence and uncertainty diagnostics.",
                ],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("build_temporal_covariate_composite", inputs, exc)


    @tool
    def raster_zonal_stats(raster_name: str, polygon_name: str, output_name: str, stat: str = "mean", band: int = 1, field_name: str = "") -> str:
        """按面图层统计栅格值，并把统计结果写回面图层。"""
        inputs = {
            "raster_name": raster_name,
            "polygon_name": polygon_name,
            "output_name": output_name,
            "stat": stat,
            "band": band,
            "field_name": field_name,
        }
        allowed_stats = {"mean", "sum", "min", "max", "median", "count"}
        if stat not in allowed_stats:
            return tool_result_error(
                "raster_zonal_stats",
                inputs=inputs,
                error_code="STAT_UNSUPPORTED",
                error_title="统计方式不支持",
                user_message=f"stat 必须是 {', '.join(sorted(allowed_stats))} 之一。",
                diagnostics={"allowed": sorted(allowed_stats), "received": stat},
                next_actions=["请选择一种受支持的统计方式后重试。"],
            ).to_json()
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, raster_name))
        errors.extend(validate_dataset_exists(manager, polygon_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_raster_readable(manager, raster_name))
            errors.extend(validate_vector_readable(manager, polygon_name))
            errors.extend(validate_crs(manager, raster_name))
            errors.extend(validate_crs(manager, polygon_name))
            errors.extend(validate_geometry_type(manager, polygon_name, ["Polygon", "MultiPolygon"]))
        if errors:
            return _tool_error_from_validation("raster_zonal_stats", inputs, errors)
        try:
            raster_path = manager.get_raster_path(raster_name)
            polygons = manager.get_vector(polygon_name)
            out_field = field_name or f"raster_{stat}"
            result = polygons.copy()
            values: list[float | int | None] = []
            with rasterio.open(raster_path) as src:
                if band < 1 or band > src.count:
                    return tool_result_error(
                        "raster_zonal_stats",
                        inputs=inputs,
                        error_code="RASTER_BAND_OUT_OF_RANGE",
                        error_title="波段编号超出范围",
                        user_message=f"数据 {raster_name} 只有 {src.count} 个波段，不能读取第 {band} 个波段。",
                        diagnostics={"band": band, "band_count": int(src.count)},
                        next_actions=["请选择 1 到波段总数之间的 band 参数后重试。"],
                    ).to_json()
                zones = polygons.to_crs(src.crs) if polygons.crs and src.crs and polygons.crs != src.crs else polygons
                for geom in zones.geometry:
                    if geom is None or geom.is_empty:
                        values.append(None)
                        continue
                    try:
                        data, _ = mask(src, [geom], crop=True, indexes=band, filled=False)
                    except ValueError:
                        values.append(None)
                        continue
                    valid = np.ma.array(data).compressed()
                    if valid.size == 0:
                        values.append(None)
                    elif stat == "mean":
                        values.append(float(np.mean(valid)))
                    elif stat == "sum":
                        values.append(float(np.sum(valid)))
                    elif stat == "min":
                        values.append(float(np.min(valid)))
                    elif stat == "max":
                        values.append(float(np.max(valid)))
                    elif stat == "median":
                        values.append(float(np.median(valid)))
                    else:
                        values.append(int(valid.size))
            result[out_field] = values
            saved_name = manager.put_vector(output_name, result)
            record = manager.get(saved_name)
            manager.log_operation("栅格分区统计", f"{raster_name} by {polygon_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "raster_zonal_stats",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(result)),
                    "path": str(record.path),
                    "fields_added": [out_field],
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{raster_name} zonal {stat} by {polygon_name}",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"已按 {polygon_name} 统计 {raster_name} 的 {stat} 值，输出 {saved_name}，新增字段 {out_field}。",
                diagnostics={
                    "polygon_count": int(len(polygons)),
                    "non_null_count": int(pd.Series(values).notna().sum()),
                    "stat": stat,
                    "band": int(band),
                },
                next_actions=["可继续对分区统计字段制图、排序检查异常区域，或导出结果。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("raster_zonal_stats", inputs, exc)


    @tool
    def clip_raster_by_vector(raster_name: str, vector_name: str, output_name: str) -> str:
        """使用矢量边界裁剪栅格，并保存为新的 tif 文件。"""
        inputs = {"raster_name": raster_name, "vector_name": vector_name, "output_name": output_name}
        errors = []
        errors.extend(validate_dataset_exists(manager, raster_name))
        errors.extend(validate_dataset_exists(manager, vector_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name, allowed_suffixes={".tif", ".tiff"}))
        if not errors:
            errors.extend(validate_raster_readable(manager, raster_name))
            errors.extend(validate_vector_readable(manager, vector_name))
            errors.extend(validate_crs(manager, raster_name))
            errors.extend(validate_crs(manager, vector_name))
        if errors:
            return _tool_error_from_validation("clip_raster_by_vector", inputs, errors)
        try:
            raster_path = manager.get_raster_path(raster_name)
            gdf = manager.get_vector(vector_name)
            output_stem = output_name
            if Path(output_stem).suffix.lower() in {".tif", ".tiff"}:
                output_stem = Path(output_stem).stem
            output_path = manager.derived_dir / f"{output_stem}.tif"

            with rasterio.open(raster_path) as src:
                if gdf.crs and src.crs and gdf.crs != src.crs:
                    gdf = gdf.to_crs(src.crs)
                geoms = [geom.__geo_interface__ for geom in gdf.geometry if geom is not None]
                if not geoms:
                    return tool_result_error(
                        "clip_raster_by_vector",
                        inputs=inputs,
                        error_code="GEOMETRY_REQUIRED",
                        error_title="缺少裁剪几何",
                        user_message="裁剪图层没有可用几何。",
                        diagnostics={"vector_name": vector_name},
                        next_actions=["检查边界图层是否为空或几何是否有效。"],
                    ).to_json()
                out_image, out_transform = mask(src, geoms, crop=True)
                out_meta = src.meta.copy()
                out_meta.update({"height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
                with rasterio.open(output_path, "w", **out_meta) as dest:
                    dest.write(out_image)

            serializable_meta = {
                **{k: v for k, v in out_meta.items() if k not in {"crs", "transform"}},
                "crs": str(out_meta.get("crs")) if out_meta.get("crs") else None,
                "transform": tuple(out_meta.get("transform")) if out_meta.get("transform") is not None else None,
            }
            stored_name = manager.put_raster_path(output_stem, output_path, meta=serializable_meta)
            manager.log_operation("栅格裁剪", f"{raster_name} by {vector_name} -> {stored_name}", "analysis")
            return tool_result_ok(
                "clip_raster_by_vector",
                inputs=inputs,
                outputs={"result_dataset": stored_name, "path": str(output_path), "width": int(serializable_meta.get("width") or 0), "height": int(serializable_meta.get("height") or 0)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"raster_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="raster",
                        title=f"{stored_name} clipped raster",
                        description=f"{raster_name} 按 {vector_name} 裁剪后的栅格。",
                        quality_status="created",
                        preview_available=False,
                    )
                ],
                summary=f"栅格裁剪完成，结果数据集 {stored_name}。",
                diagnostics={"source_raster": raster_name, "clip_vector": vector_name, "crs": serializable_meta.get("crs")},
                next_actions=["检查裁剪后的栅格范围和像元值。", "可继续制图或提取到点图层。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("clip_raster_by_vector", inputs, exc)
        raster_path = manager.get_raster_path(raster_name)
        gdf = manager.get_vector(vector_name)
        output_path = manager.derived_dir / f"{output_name}.tif"

        with rasterio.open(raster_path) as src:
            if gdf.crs and src.crs and gdf.crs != src.crs:
                gdf = gdf.to_crs(src.crs)
            geoms = [geom.__geo_interface__ for geom in gdf.geometry if geom is not None]
            out_image, out_transform = mask(src, geoms, crop=True)
            out_meta = src.meta.copy()
            out_meta.update({"height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
            with rasterio.open(output_path, "w", **out_meta) as dest:
                dest.write(out_image)

        stored_name = manager.put_raster_path(output_name, output_path, meta=out_meta)
        manager.log_operation("栅格裁剪", f"{raster_name} by {vector_name} -> {stored_name}", "analysis")
        return f"裁剪完成，结果栅格: {stored_name}，保存路径: {output_path}"


    @tool
    def raster_mosaic(raster_names: str, output_name: str, vector_name: str = "", method: str = "first") -> str:
        """Merge multiple raster tiles into one GeoTIFF, optionally clipping the mosaic by a vector boundary."""
        inputs = {"raster_names": raster_names, "output_name": output_name, "vector_name": vector_name, "method": method}
        raster_list = [item.strip() for item in re.split(r"[,;\s]+", str(raster_names or "")) if item.strip()]
        errors: list[dict[str, Any]] = []
        if not raster_list:
            errors.append({"error_code": "RASTER_INPUTS_REQUIRED", "error_title": "Raster inputs required", "user_message": "Provide at least one raster dataset name to mosaic.", "diagnostics": {}, "next_actions": ["Use raster_names such as dem_tile_1,dem_tile_2."]})
        for dataset_name in raster_list:
            errors.extend(validate_dataset_exists(manager, dataset_name))
            errors.extend(validate_raster_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
        if str(vector_name or "").strip():
            errors.extend(validate_dataset_exists(manager, vector_name))
            if not errors:
                errors.extend(validate_vector_readable(manager, vector_name))
                errors.extend(validate_crs(manager, vector_name))
                errors.extend(validate_geometry_type(manager, vector_name, ["Polygon", "MultiPolygon"]))
        errors.extend(validate_output_path(manager.derived_dir, output_name, allowed_suffixes={".tif", ".tiff"}))
        if method not in {"first", "last", "min", "max", "sum", "count"}:
            errors.append({"error_code": "RASTER_MOSAIC_METHOD_UNSUPPORTED", "error_title": "Unsupported mosaic method", "user_message": "method must be one of first,last,min,max,sum,count.", "diagnostics": {"received": method}, "next_actions": ["Use method='first' for DEM tiles."]})
        if errors:
            return _tool_error_from_validation("raster_mosaic", inputs, errors)
        try:
            output_stem = Path(output_name).stem if Path(output_name).suffix.lower() in {".tif", ".tiff"} else output_name
            output_path = manager.derived_dir / f"{_artifact_safe_name(output_stem)}.tif"
            with contextlib.ExitStack() as stack:
                sources = [stack.enter_context(rasterio.open(manager.get_raster_path(name))) for name in raster_list]
                reference = sources[0]
                reference_dtype = reference.dtypes[0]
                nodata = reference.nodata if reference.nodata is not None else _default_nodata_for_dtype(reference_dtype)
                mosaic, mosaic_transform = raster_merge(sources, nodata=nodata, method=method)
                profile = reference.profile.copy()
                profile.update(height=int(mosaic.shape[1]), width=int(mosaic.shape[2]), count=int(mosaic.shape[0]), transform=mosaic_transform, nodata=nodata, dtype=str(reference_dtype))
                output_data = mosaic
                if str(vector_name or "").strip():
                    gdf = manager.get_vector(vector_name)
                    if gdf.crs and reference.crs and gdf.crs != reference.crs:
                        gdf = gdf.to_crs(reference.crs)
                    geoms = [geom.__geo_interface__ for geom in gdf.geometry if geom is not None and not geom.is_empty]
                    if not geoms:
                        return tool_result_error("raster_mosaic", inputs=inputs, error_code="GEOMETRY_REQUIRED", error_title="Clip geometry required", user_message=f"Vector dataset {vector_name} has no usable geometry for clipping.").to_json()
                    with MemoryFile() as memfile:
                        with memfile.open(**profile) as dataset:
                            dataset.write(mosaic)
                            output_data, clipped_transform = mask(dataset, geoms, crop=True, nodata=nodata)
                    profile.update(height=int(output_data.shape[1]), width=int(output_data.shape[2]), transform=clipped_transform)
                with rasterio.open(output_path, "w", **profile) as dst:
                    dst.write(output_data.astype(reference_dtype, copy=False))
            meta = {"crs": str(profile.get("crs")) if profile.get("crs") else None, "source_rasters": raster_list, "clip_vector": vector_name or "", "map_ready": True, "map_layer_id": _map_layer_id(output_stem), "layer_kind": _dataset_map_kind(output_stem, "raster"), "source_tool": "raster_mosaic"}
            stored_name = manager.put_raster_path(output_stem, output_path, meta=meta)
            return tool_result_ok(
                "raster_mosaic",
                inputs=inputs,
                outputs={**_map_ready_outputs(manager, stored_name, source_tool="raster_mosaic"), "path": str(output_path), "width": int(profile.get("width") or 0), "height": int(profile.get("height") or 0)},
                artifacts=[ArtifactInfo(f"raster:{output_path.name}", str(output_path), "raster", f"{stored_name} raster mosaic", f"Mosaic generated from {len(raster_list)} raster tile(s).", "created", False)],
                summary=f"Merged {len(raster_list)} raster tile(s) into {stored_name}.",
                diagnostics={"source_rasters": raster_list, "clip_vector": vector_name or "", "dtype": str(profile.get("dtype")), "nodata": profile.get("nodata"), "method": method},
                next_actions=["Inspect the mosaic on the map, export it, or continue with terrain/statistical analysis."],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("raster_mosaic", inputs, exc)


    @tool
    def dem_terrain_derivatives(dem_name: str, output_prefix: str, derivatives: str = "slope,aspect,terrain", slope_units: str = "degree") -> str:
        """Create DEM derivatives such as slope, aspect, terrain factor, TPI, or TRI rasters."""
        inputs = {"dem_name": dem_name, "output_prefix": output_prefix, "derivatives": derivatives, "slope_units": slope_units}
        errors = validate_dataset_exists(manager, dem_name) + validate_output_path(manager.derived_dir, output_prefix)
        if not errors:
            errors.extend(validate_raster_readable(manager, dem_name))
            errors.extend(validate_crs(manager, dem_name))
        requested = [item.strip().lower() for item in str(derivatives or "").split(",") if item.strip()] or ["slope", "aspect", "terrain"]
        invalid = [item for item in requested if item not in {"slope", "aspect", "terrain", "tpi", "tri"}]
        units = str(slope_units or "degree").strip().lower()
        if units not in {"degree", "percent"}:
            return tool_result_error(
                "dem_terrain_derivatives",
                inputs=inputs,
                error_code="SLOPE_UNITS_UNSUPPORTED",
                error_title="坡度单位不支持",
                user_message="slope_units 必须是 degree 或 percent。",
                diagnostics={"allowed": ["degree", "percent"], "received": slope_units},
                next_actions=["请在 TaskPlan 中明确 slope_units=degree 或 slope_units=percent。"],
            ).to_json()
        if invalid:
            return tool_result_error("dem_terrain_derivatives", inputs=inputs, error_code="DEM_DERIVATIVE_UNSUPPORTED", error_title="Unsupported DEM derivative", user_message=f"Unsupported derivatives: {', '.join(invalid)}.").to_json()
        if errors:
            return _tool_error_from_validation("dem_terrain_derivatives", inputs, errors)
        try:
            raster_path = manager.get_raster_path(dem_name)
            with rasterio.open(raster_path) as src:
                if src.crs and src.crs.is_geographic:
                    return tool_result_error(
                        "dem_terrain_derivatives",
                        inputs=inputs,
                        error_code="DEM_PROJECTED_CRS_REQUIRED",
                        error_title="DEM 需要投影坐标系",
                        user_message="不能直接对地理坐标 CRS 的 DEM 计算平面坡度。请先通过已验证计划重投影到米制投影坐标系，或确认目标投影。",
                        diagnostics={"source_crs": str(src.crs)},
                        next_actions=["先执行 raster_reproject 到合适的投影 CRS，再计算坡度坡向。"],
                    ).to_json()
                band = src.read(1, masked=True).astype("float32")
                arr = np.asarray(band.filled(np.nan), dtype="float32")
                xres = abs(float(src.transform.a)) or 1.0
                yres = abs(float(src.transform.e)) or 1.0
            gy, gx = np.gradient(arr, yres, xres)
            slope_rise_run = np.sqrt(gx * gx + gy * gy)
            slope = np.degrees(np.arctan(slope_rise_run)) if units == "degree" else slope_rise_run * 100.0
            aspect = (np.degrees(np.arctan2(-gx, gy)) + 360.0) % 360.0
            aspect = np.where(np.isclose(slope_rise_run, 0.0) | ~np.isfinite(slope_rise_run), np.nan, aspect)
            padded = np.pad(arr, 1, mode="edge")
            neighborhood_mean = sum(padded[y:y + arr.shape[0], x:x + arr.shape[1]] for y in range(3) for x in range(3)) / 9.0
            tpi = arr - neighborhood_mean
            tri = np.sqrt(gx * gx + gy * gy)
            arrays = {"slope": slope, "aspect": aspect, "terrain": tpi, "tpi": tpi, "tri": tri}
            datasets: list[str] = []
            artifacts: list[ArtifactInfo] = []
            statistics: dict[str, dict[str, float | int | None]] = {}
            for derivative in requested:
                suffix = "terrain" if derivative == "tpi" else derivative
                values = np.asarray(arrays[derivative], dtype="float32")
                valid = values[np.isfinite(values)]
                statistics[derivative] = {
                    "min": float(valid.min()) if valid.size else None,
                    "max": float(valid.max()) if valid.size else None,
                    "mean": float(valid.mean()) if valid.size else None,
                    "valid_count": int(valid.size),
                }
                stored_name, output_path, _ = _write_raster_dataset_like(
                    raster_path,
                    f"{output_prefix}_{suffix}",
                    values,
                    source_tool="dem_terrain_derivatives",
                    meta_updates={"source_dem": dem_name, "derivative": derivative, "slope_units": units, "aspect_flat_value": "NoData"},
                )
                datasets.append(stored_name)
                artifacts.append(ArtifactInfo(f"raster:{output_path.name}", str(output_path), "raster", f"{stored_name} DEM derivative", f"{derivative} derived from DEM {dem_name}.", "created", False))
            map_layers = [{"layer_id": _map_layer_id(name), "name": name, "dataset_name": name, "type": "raster"} for name in datasets]
            return tool_result_ok(
                "dem_terrain_derivatives",
                inputs=inputs,
                outputs={
                    "datasets": datasets,
                    "derivatives": requested,
                    "slope_units": units,
                    "aspect_range": [0, 360],
                    "aspect_flat_value": "NoData",
                    "statistics": statistics,
                    "map_ready": True,
                    "map_layer_ids": [_map_layer_id(name) for name in datasets],
                },
                artifacts=artifacts,
                map_layers=map_layers,
                diagnostics={"source_dem": dem_name, "slope_units": units, "nodata": -9999.0},
                summary=f"Created DEM derivative datasets: {', '.join(datasets)}.",
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("dem_terrain_derivatives", inputs, exc)


    @tool
    def raster_reproject(raster_name: str, target_crs: str, output_name: str, resampling: str = "bilinear", target_resolution: str = "") -> str:
        """Reproject a raster dataset and register the output as a map-ready GeoTIFF."""
        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject

        inputs = {"raster_name": raster_name, "target_crs": target_crs, "output_name": output_name, "resampling": resampling, "target_resolution": target_resolution}
        errors = validate_dataset_exists(manager, raster_name) + validate_output_path(manager.derived_dir, output_name, allowed_suffixes={".tif", ".tiff"})
        if not errors:
            errors.extend(validate_raster_readable(manager, raster_name))
            errors.extend(validate_crs(manager, raster_name))
        resolution_value: tuple[float, float] | None = None
        if str(target_resolution or "").strip():
            parts = [item.strip() for item in re.split(r"[,xX\s]+", str(target_resolution or "")) if item.strip()]
            if len(parts) == 1:
                parts = [parts[0], parts[0]]
            try:
                parsed_resolution = (float(parts[0]), float(parts[1]))
                if parsed_resolution[0] <= 0 or parsed_resolution[1] <= 0:
                    raise ValueError("target resolution must be positive")
                resolution_value = parsed_resolution
            except Exception:
                return tool_result_error(
                    "raster_reproject",
                    inputs=inputs,
                    error_code="TARGET_RESOLUTION_INVALID",
                    error_title="目标分辨率非法",
                    user_message="target_resolution 必须是正数，格式可以是 '30' 或 '30,30'，单位为目标 CRS 的坐标单位。",
                    diagnostics={"target_resolution": target_resolution},
                    next_actions=["请在 TaskPlan 中使用正数目标分辨率，或留空以保留 calculate_default_transform 的默认输出分辨率。"],
                ).to_json()
        if errors:
            return _tool_error_from_validation("raster_reproject", inputs, errors)
        try:
            source_path = manager.get_raster_path(raster_name)
            output_stem = Path(output_name).stem if Path(output_name).suffix else output_name
            output_path = manager.derived_dir / f"{_artifact_safe_name(output_stem)}.tif"
            resampling_name = str(resampling or "bilinear").strip().lower()
            if not hasattr(Resampling, resampling_name):
                return tool_result_error(
                    "raster_reproject",
                    inputs=inputs,
                    error_code="RESAMPLING_UNSUPPORTED",
                    error_title="重采样方法不支持",
                    user_message="resampling 必须是 rasterio 支持的方法，例如 nearest、bilinear、cubic 或 average。",
                    diagnostics={"resampling": resampling},
                    next_actions=["请选择 nearest、bilinear、cubic 或 average 后重试。"],
                ).to_json()
            mode = getattr(Resampling, resampling_name)
            with rasterio.open(source_path) as src:
                source_resolution = [abs(float(src.transform.a)), abs(float(src.transform.e))]
                kwargs: dict[str, Any] = {}
                if resolution_value is not None:
                    kwargs["resolution"] = resolution_value
                transform, width, height = calculate_default_transform(src.crs, target_crs, src.width, src.height, *src.bounds, **kwargs)
                profile = src.profile.copy()
                profile.update(crs=target_crs, transform=transform, width=width, height=height)
                with rasterio.open(output_path, "w", **profile) as dst:
                    for index in range(1, src.count + 1):
                        reproject(source=rasterio.band(src, index), destination=rasterio.band(dst, index), src_transform=src.transform, src_crs=src.crs, dst_transform=transform, dst_crs=target_crs, resampling=mode)
            target_res = [abs(float(transform.a)), abs(float(transform.e))]
            transform_values = [float(value) for value in tuple(transform)]
            stored_name = manager.put_raster_path(
                output_stem,
                output_path,
                meta={
                    "crs": target_crs,
                    "source_raster": raster_name,
                    "resampling": resampling_name,
                    "source_resolution": source_resolution,
                    "target_resolution": target_res,
                    "target_transform": transform_values,
                    "map_ready": True,
                    "map_layer_id": _map_layer_id(output_stem),
                    "layer_kind": _dataset_map_kind(output_stem, "raster"),
                    "source_tool": "raster_reproject",
                },
            )
            diagnostics = {
                "source_crs": str(src.crs),
                "target_crs": target_crs,
                "source_resolution": source_resolution,
                "target_resolution": target_res,
                "target_resolution_units": "target_crs_units",
                "target_transform": transform_values,
                "width": int(width),
                "height": int(height),
                "resampling": resampling_name,
                "target_resolution_requested": list(resolution_value) if resolution_value is not None else None,
            }
            return tool_result_ok(
                "raster_reproject",
                inputs=inputs,
                outputs={**_map_ready_outputs(manager, stored_name, source_tool="raster_reproject"), "path": str(output_path), "target_crs": target_crs, "target_resolution": target_res, "resampling": resampling_name, "target_transform": transform_values},
                artifacts=[ArtifactInfo(f"raster:{output_path.name}", str(output_path), "raster", f"{stored_name} reprojected raster", "", "created", False)],
                map_layers=[{"layer_id": _map_layer_id(stored_name), "name": stored_name, "dataset_name": stored_name, "type": "raster"}],
                diagnostics=diagnostics,
                summary=f"Reprojected raster {raster_name} to {target_crs} as {stored_name}.",
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("raster_reproject", inputs, exc)


    @tool
    def raster_algebra(expression: str, input_rasters: str, output_name: str) -> str:
        """Evaluate a restricted NumPy expression over aligned raster bands."""
        import ast

        inputs = {"expression": expression, "input_rasters": input_rasters, "output_name": output_name}
        mapping: dict[str, str] = {}
        for item in str(input_rasters or "").split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                if key.strip() and value.strip():
                    mapping[key.strip()] = value.strip()
        errors = []
        if not mapping:
            errors.append({"error_code": "RASTER_INPUTS_REQUIRED", "error_title": "Raster inputs required", "user_message": "Provide input_rasters such as ndvi=ndvi_dataset.", "diagnostics": {}, "next_actions": ["Map expression variables to raster dataset names."]})
        for dataset_name in mapping.values():
            errors.extend(validate_dataset_exists(manager, dataset_name))
            errors.extend(validate_raster_readable(manager, dataset_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name, allowed_suffixes={".tif", ".tiff"}))
        if errors:
            return _tool_error_from_validation("raster_algebra", inputs, errors)
        try:
            parsed = ast.parse(expression, mode="eval")
            _validate_raster_algebra_ast(parsed, variables=set(mapping))
            first_dataset = next(iter(mapping.values()))
            first_path = manager.get_raster_path(first_dataset)
            with rasterio.open(first_path) as reference:
                shape = (reference.height, reference.width)
                reference_crs = str(reference.crs) if reference.crs else ""
                reference_transform = tuple(reference.transform)
                reference_res = (abs(float(reference.transform.a)), abs(float(reference.transform.e)))
            arrays: dict[str, np.ndarray] = {}
            for variable, dataset_name in mapping.items():
                with rasterio.open(manager.get_raster_path(dataset_name)) as src:
                    if (src.height, src.width) != shape:
                        return tool_result_error(
                            "raster_algebra",
                            inputs=inputs,
                            error_code="RASTER_ALIGNMENT_MISMATCH",
                            error_title="栅格未对齐",
                            user_message="所有输入栅格必须具有相同宽高、CRS、分辨率和网格变换后才能进行栅格计算。",
                            diagnostics={"variable": variable, "dataset": dataset_name, "reason": "shape_mismatch"},
                            next_actions=["先使用 raster_reproject/重采样将栅格对齐，再执行栅格计算。"],
                        ).to_json()
                    if (str(src.crs) if src.crs else "") != reference_crs or tuple(src.transform) != reference_transform:
                        return tool_result_error(
                            "raster_algebra",
                            inputs=inputs,
                            error_code="RASTER_ALIGNMENT_MISMATCH",
                            error_title="栅格未对齐",
                            user_message="所有输入栅格必须具有相同 CRS、分辨率和网格变换后才能进行栅格计算。",
                            diagnostics={
                                "variable": variable,
                                "dataset": dataset_name,
                                "reference_crs": reference_crs,
                                "input_crs": str(src.crs) if src.crs else "",
                                "reference_resolution": reference_res,
                                "input_resolution": (abs(float(src.transform.a)), abs(float(src.transform.e))),
                            },
                            next_actions=["先重投影或重采样对齐输入栅格。"],
                        ).to_json()
                    band = src.read(1, masked=True).astype("float32")
                    arrays[variable] = np.asarray(band.filled(np.nan), dtype="float32")
            safe_np = type("SafeNumpy", (), {name: getattr(np, name) for name in sorted(_RASTER_ALGEBRA_NP_FUNCTIONS)})
            result = eval(compile(parsed, "<raster_algebra>", "eval"), {"__builtins__": {}, "np": safe_np}, arrays)
            result_arr = np.asarray(result, dtype="float32")
            valid = result_arr[np.isfinite(result_arr)]
            statistics = {
                "min": float(valid.min()) if valid.size else None,
                "max": float(valid.max()) if valid.size else None,
                "mean": float(valid.mean()) if valid.size else None,
                "std": float(valid.std()) if valid.size else None,
                "valid_count": int(valid.size),
            }
            stored_name, output_path, _ = _write_raster_dataset_like(first_path, output_name, result_arr, source_tool="raster_algebra", meta_updates={"expression": expression, "input_rasters": mapping})
            return tool_result_ok(
                "raster_algebra",
                inputs=inputs,
                outputs={**_map_ready_outputs(manager, stored_name, source_tool="raster_algebra"), "path": str(output_path), "expression": expression, "input_rasters": mapping, "statistics": statistics},
                artifacts=[ArtifactInfo(f"raster:{output_path.name}", str(output_path), "raster", f"{stored_name} raster algebra", "", "created", False)],
                map_layers=[{"layer_id": _map_layer_id(stored_name), "name": stored_name, "dataset_name": stored_name, "type": "raster"}],
                diagnostics={"reference_crs": reference_crs, "reference_resolution": reference_res, "variables": sorted(mapping)},
                summary=f"Created raster algebra output {stored_name}.",
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("raster_algebra", inputs, exc)


    @tool
    def extract_raster_values_to_points(point_name: str, raster_name: str, output_name: str, field_name: str = "raster_val", band: int = 1, method: str = "nearest") -> str:
        """将栅格像元值提取到点图层属性表中，适合站点-栅格匹配、样点验证和建模前特征抽取。"""
        inputs = {"point_name": point_name, "raster_name": raster_name, "output_name": output_name, "field_name": field_name, "band": band, "method": method}
        errors = []
        errors.extend(validate_dataset_exists(manager, point_name))
        errors.extend(validate_dataset_exists(manager, raster_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, point_name))
            errors.extend(validate_raster_readable(manager, raster_name))
            errors.extend(validate_crs(manager, point_name))
            errors.extend(validate_geometry_type(manager, point_name, ["Point"]))
        if not str(field_name or "").strip():
            errors.append(
                {
                    "error_code": "OUTPUT_FIELD_REQUIRED",
                    "error_title": "缺少输出字段",
                    "user_message": "请指定用于保存栅格值的输出字段名。",
                    "next_actions": ["提供 field_name，例如 raster_val。"],
                    "diagnostics": {},
                }
            )
        sample_method = str(method or "nearest").strip().lower()
        if sample_method not in {"nearest", "bilinear"}:
            errors.append(
                {
                    "error_code": "RASTER_SAMPLING_METHOD_UNSUPPORTED",
                    "error_title": "采样方法不支持",
                    "user_message": "method 必须是 nearest 或 bilinear。",
                    "next_actions": ["请在 TaskPlan 中明确 method=nearest 或 method=bilinear。"],
                    "diagnostics": {"allowed": ["nearest", "bilinear"], "received": method},
                }
            )
        if errors:
            return _tool_error_from_validation("extract_raster_values_to_points", inputs, errors)
        try:
            points = manager.get_vector(point_name)
            raster_path = manager.get_raster_path(raster_name)

            with rasterio.open(raster_path) as src:
                if band < 1 or band > src.count:
                    return tool_result_error(
                        "extract_raster_values_to_points",
                        inputs=inputs,
                        error_code="RASTER_BAND_OUT_OF_RANGE",
                        error_title="栅格波段不存在",
                        user_message=f"请求的波段 {band} 不在栅格波段范围内。",
                        diagnostics={"band": band, "band_count": src.count},
                        next_actions=["选择 1 到栅格波段数之间的 band。"],
                    ).to_json()
                pts = points.copy()
                if pts.crs and src.crs and pts.crs != src.crs:
                    pts = pts.to_crs(src.crs)
                coords = [(geom.x, geom.y) for geom in pts.geometry if geom is not None]
                if sample_method == "nearest":
                    values = [val[0] if len(val) else None for val in src.sample(coords, indexes=band)]
                else:
                    data = src.read(band, masked=True).astype("float32")
                    values = []
                    for x, y in coords:
                        row, col = src.index(x, y)
                        if row < 0 or col < 0 or row >= src.height - 1 or col >= src.width - 1:
                            values.append(np.nan)
                            continue
                        x0, y0 = src.xy(row, col)
                        dx = min(1.0, max(0.0, abs((x - x0) / (src.transform.a or 1.0))))
                        dy = min(1.0, max(0.0, abs((y - y0) / (src.transform.e or -1.0))))
                        window = np.ma.array(data[row : row + 2, col : col + 2]).astype("float32")
                        if window.count() == 0:
                            values.append(np.nan)
                        else:
                            filled = window.filled(np.nan)
                            values.append(float((filled[0, 0] * (1 - dx) * (1 - dy)) + (filled[0, 1] * dx * (1 - dy)) + (filled[1, 0] * (1 - dx) * dy) + (filled[1, 1] * dx * dy)))
                result = points.copy()
                result[field_name] = values

            saved_name = manager.put_vector(output_name, result)
            output_path = manager.get(saved_name).path
            artifact = manager.register_artifact(
                path=str(output_path),
                type="dataset",
                title=f"{saved_name} raster sampled points",
                description=f"点图层 {point_name} 提取栅格 {raster_name} 后的结果。",
                quality_status="ok",
                preview_available=True,
                dataset_id=saved_name,
                source_tool="extract_raster_values_to_points",
            )
            manager.log_operation("栅格抽样到点", f"{raster_name} -> {point_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "extract_raster_values_to_points",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(result)), "field_name": field_name, "path": str(output_path), "method": sample_method},
                artifacts=[artifact],
                map_layers=[{"layer_id": _map_layer_id(saved_name), "name": saved_name, "dataset_name": saved_name, "type": "vector"}],
                tables=[{"table_id": saved_name, "title": saved_name, "dataset_name": saved_name}],
                summary=f"栅格值提取完成，结果数据集 {saved_name}，字段 {field_name}。",
                diagnostics={"sample_count": int(len(values)), "missing_count": int(pd.Series(values).isna().sum()), "band": int(band), "raster": raster_name, "method": sample_method},
                next_actions=["检查提取字段的缺失值和异常值。", "可继续用于建模或专题制图。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("extract_raster_values_to_points", inputs, exc)
        points = manager.get_vector(point_name)
        raster_path = manager.get_raster_path(raster_name)

        with rasterio.open(raster_path) as src:
            pts = points.copy()
            if pts.crs and src.crs and pts.crs != src.crs:
                pts = pts.to_crs(src.crs)
            coords = [(geom.x, geom.y) for geom in pts.geometry if geom is not None]
            values = [val[0] if len(val) else None for val in src.sample(coords, indexes=band)]
            result = points.copy()
            result[field_name] = values

        saved_name = manager.put_vector(output_name, result)
        manager.log_operation("栅格抽样到点", f"{raster_name} -> {point_name} -> {saved_name}", "analysis")
        return f"栅格值提取完成，结果: {saved_name}，字段: {field_name}，保存路径: {manager.get(saved_name).path}"


    @tool
    def batch_register_points_to_rasters(
        point_name: str,
        raster_names: str,
        output_name: str,
        id_cols: str = "",
        output_mode: str = "long",
        value_field_prefix: str = "raster",
        band: int = 1,
        parse_date: bool = True,
        date_regex: str = r"(20\d{2}[01]\d[0-3]\d|20\d{2}-\d{2}-\d{2})",
    ) -> str:
        """对一个站点点图层批量提取多个栅格的像元值，生成长表或宽表，适合批量站点—栅格配准、时间序列建模和验证样本构建。"""
        inputs = {
            "point_name": point_name,
            "raster_names": raster_names,
            "output_name": output_name,
            "id_cols": id_cols,
            "output_mode": output_mode,
            "value_field_prefix": value_field_prefix,
            "band": band,
            "parse_date": parse_date,
            "date_regex": date_regex,
        }
        mode = output_mode.strip().lower()
        if mode not in {"long", "wide"}:
            return tool_result_error(
                "batch_register_points_to_rasters",
                inputs=inputs,
                error_code="OUTPUT_MODE_UNSUPPORTED",
                error_title="Unsupported output mode",
                user_message="output_mode must be either long or wide.",
                diagnostics={"allowed": ["long", "wide"], "received": output_mode},
                next_actions=["Use output_mode='long' for modeling tables or output_mode='wide' to append one field per raster."],
            ).to_json()
        try:
            band_value = int(band)
        except Exception:
            return tool_result_error(
                "batch_register_points_to_rasters",
                inputs=inputs,
                error_code="RASTER_BAND_INVALID",
                error_title="Invalid raster band",
                user_message="Band must be an integer starting from 1.",
                diagnostics={"band": band},
                next_actions=["Use band=1 for single-band rasters."],
            ).to_json()
        errors: list[dict[str, Any]] = []
        raster_list = _parse_columns(raster_names)
        if not raster_list:
            return tool_result_error(
                "batch_register_points_to_rasters",
                inputs=inputs,
                error_code="RASTER_INPUT_REQUIRED",
                error_title="Missing raster inputs",
                user_message="At least one raster dataset is required.",
                diagnostics={},
                next_actions=["Provide one or more raster dataset names separated by commas."],
            ).to_json()
        errors.extend(validate_dataset_exists(manager, point_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        for raster_name in raster_list:
            errors.extend(validate_dataset_exists(manager, raster_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, point_name))
            errors.extend(validate_crs(manager, point_name))
            for raster_name in raster_list:
                errors.extend(validate_raster_readable(manager, raster_name))
        if errors:
            return _tool_error_from_validation("batch_register_points_to_rasters", inputs, errors)

        try:
            points = manager.get_vector(point_name)
            id_list = _parse_columns(id_cols) if id_cols.strip() else [col for col in points.columns if col != "geometry"]
            try:
                _validate_columns(points.drop(columns=["geometry"], errors="ignore"), [col for col in id_list if col != "geometry"])
            except Exception:
                available = [str(col) for col in points.drop(columns=["geometry"], errors="ignore").columns]
                missing_ids = [col for col in id_list if col != "geometry" and col not in available]
                return tool_result_error(
                    "batch_register_points_to_rasters",
                    inputs=inputs,
                    error_code="FIELD_NOT_FOUND",
                    error_title="ID field not found",
                    user_message="One or more id_cols fields do not exist in the point dataset.",
                    diagnostics={"missing_fields": missing_ids, "available_fields": available},
                    next_actions=["Choose id_cols from the point dataset fields, or leave id_cols empty to use all attributes."],
                ).to_json()

            if mode == "wide":
                result = points.copy()
                added_fields: list[str] = []
                for raster_name in raster_list:
                    raster_path = manager.get_raster_path(raster_name)
                    with rasterio.open(raster_path) as src:
                        if band_value < 1 or band_value > src.count:
                            return tool_result_error(
                                "batch_register_points_to_rasters",
                                inputs=inputs,
                                error_code="RASTER_BAND_OUT_OF_RANGE",
                                error_title="Raster band out of range",
                                user_message=f"Raster {raster_name} has {src.count} band(s); band {band_value} cannot be read.",
                                diagnostics={"raster": raster_name, "band": band_value, "band_count": int(src.count)},
                                next_actions=["Choose a band number between 1 and the raster band count."],
                            ).to_json()
                    field_name = f"{value_field_prefix}_{_artifact_safe_name(raster_name)}"
                    result[field_name] = _sample_raster_to_geometries(points, raster_path, band=band_value)
                    added_fields.append(field_name)
                saved_name = manager.put_vector(output_name, result)
                record = manager.get(saved_name)
                summary_path = _save_json_artifact(
                    manager,
                    f"{output_name}_batch_register_summary",
                    {
                        "point_dataset": point_name,
                        "rasters": raster_list,
                        "output_mode": mode,
                        "fields": added_fields,
                        "band": band_value,
                    },
                )
                manager.log_operation("批量站点-栅格配准", f"{point_name} x {len(raster_list)} rasters -> {saved_name}", "analysis")
                return tool_result_ok(
                    "batch_register_points_to_rasters",
                    inputs=inputs,
                    outputs={
                        "result_dataset": saved_name,
                        "output_mode": mode,
                        "feature_count": int(len(result)),
                        "raster_count": int(len(raster_list)),
                        "fields": added_fields,
                        "summary_path": str(summary_path),
                        "path": str(record.path),
                    },
                    artifacts=[
                        ArtifactInfo(f"dataset:{saved_name}", str(record.path), "dataset", saved_name, "Raster values appended to point layer.", "ok", True),
                        ArtifactInfo(f"file:{Path(summary_path).name}", str(summary_path), "file", Path(summary_path).name, "Batch raster registration summary.", "ok", False),
                    ],
                    summary=f"Registered {len(raster_list)} raster(s) to point layer {point_name} as wide dataset {saved_name}.",
                    diagnostics={"point_count": int(len(points)), "raster_names": raster_list, "band": band_value},
                    next_actions=["Inspect added raster value fields, then continue modeling, mapping, or export."],
                ).to_json()

            base_attrs = points.drop(columns=["geometry"], errors="ignore").copy()
            if not id_list:
                base_attrs["point_index"] = np.arange(len(base_attrs))
                id_list = ["point_index"]
            missing_ids = [col for col in id_list if col not in base_attrs.columns]
            if missing_ids:
                return tool_result_error(
                    "batch_register_points_to_rasters",
                    inputs=inputs,
                    error_code="FIELD_NOT_FOUND",
                    error_title="ID field not found",
                    user_message="One or more id_cols fields do not exist in the point dataset.",
                    diagnostics={"missing_fields": missing_ids, "available_fields": [str(col) for col in base_attrs.columns]},
                    next_actions=["Choose id_cols from the point dataset fields, or leave id_cols empty to create point_index."],
                ).to_json()
            geom_points = points.geometry.apply(_geometry_to_sample_point)
            base_attrs["point_x"] = geom_points.apply(lambda g: float(g.x) if g is not None and not g.is_empty else np.nan)
            base_attrs["point_y"] = geom_points.apply(lambda g: float(g.y) if g is not None and not g.is_empty else np.nan)

            rows: list[pd.DataFrame] = []
            for raster_name in raster_list:
                raster_path = manager.get_raster_path(raster_name)
                with rasterio.open(raster_path) as src:
                    if band_value < 1 or band_value > src.count:
                        return tool_result_error(
                            "batch_register_points_to_rasters",
                            inputs=inputs,
                            error_code="RASTER_BAND_OUT_OF_RANGE",
                            error_title="Raster band out of range",
                            user_message=f"Raster {raster_name} has {src.count} band(s); band {band_value} cannot be read.",
                            diagnostics={"raster": raster_name, "band": band_value, "band_count": int(src.count)},
                            next_actions=["Choose a band number between 1 and the raster band count."],
                        ).to_json()
                sampled = _sample_raster_to_geometries(points, raster_path, band=band_value)
                frame = base_attrs[id_list + ["point_x", "point_y"]].copy()
                frame["raster_name"] = raster_name
                frame["band"] = band_value
                frame["sample_value"] = sampled.values
                if parse_date:
                    frame["raster_date"] = _extract_date_from_name(raster_name, date_regex)
                rows.append(frame)

            long_df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=id_list + ["point_x", "point_y", "raster_name", "band", "sample_value", "raster_date"])
            saved_name = manager.put_table(output_name, long_df)
            record = manager.get(saved_name)
            summary_path = _save_json_artifact(
                manager,
                f"{output_name}_batch_register_summary",
                {
                    "point_dataset": point_name,
                    "rasters": raster_list,
                    "output_mode": mode,
                    "row_count": int(len(long_df)),
                    "value_field": "sample_value",
                    "parsed_dates": bool(parse_date),
                    "band": band_value,
                },
            )
            manager.log_operation("批量站点-栅格配准", f"{point_name} x {len(raster_list)} rasters -> {saved_name}", "analysis")
            return tool_result_ok(
                "batch_register_points_to_rasters",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "output_mode": mode,
                    "row_count": int(len(long_df)),
                    "raster_count": int(len(raster_list)),
                    "value_field": "sample_value",
                    "summary_path": str(summary_path),
                    "path": str(record.path),
                },
                artifacts=[
                    ArtifactInfo(f"dataset:{saved_name}", str(record.path), "dataset", saved_name, "Long table of sampled raster values.", "ok", True),
                    ArtifactInfo(f"file:{Path(summary_path).name}", str(summary_path), "file", Path(summary_path).name, "Batch raster registration summary.", "ok", False),
                ],
                summary=f"Registered {len(raster_list)} raster(s) to {len(points)} point(s) as long table {saved_name}.",
                diagnostics={"point_count": int(len(points)), "raster_names": raster_list, "band": band_value, "parsed_dates": bool(parse_date)},
                next_actions=["Use the long table for modeling, quality checks, or export."],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("batch_register_points_to_rasters", inputs, exc)


    return [
        raster_basic_stats,
        raster_covariate_quality_check,
        build_temporal_covariate_composite,
        raster_zonal_stats,
        clip_raster_by_vector,
        raster_mosaic,
        dem_terrain_derivatives,
        raster_reproject,
        raster_algebra,
        extract_raster_values_to_points,
        batch_register_points_to_rasters,
    ]
