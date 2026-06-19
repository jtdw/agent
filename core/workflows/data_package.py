from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


SENSITIVE_NAME_TOKENS = (
    ".env",
    "cookie",
    "cookies",
    "storage_state",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "credentials",
)

LON_NAMES = {"lon", "lng", "longitude", "x", "经度", "经度字段"}
LAT_NAMES = {"lat", "latitude", "y", "纬度", "纬度字段"}
TIME_TOKENS = ("date", "time", "year", "month", "day", "日期", "时间", "年份", "月份")
TARGET_TOKENS = (
    "soil_moisture",
    "moisture",
    "water_content",
    "target",
    "label",
    "sm",
    "土壤水分",
    "含水量",
    "目标",
)
MODEL_GOAL_TOKENS = ("预测", "回归", "建模", "模型", "xgboost", "xgb", "predict", "regression", "model")
MAP_GOAL_TOKENS = ("制图", "出图", "地图", "可视化", "map", "plot")
CLIP_GOAL_TOKENS = ("裁剪", "clip")
STATS_GOAL_TOKENS = ("统计", "zonal", "分区")


def _safe_name(value: str) -> str:
    stem = Path(str(value or "dataset")).stem
    cleaned = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", stem).strip("._-")
    return cleaned or "dataset"


def _is_sensitive_member(name: str) -> bool:
    lowered = str(name or "").replace("\\", "/").lower()
    parts = [part for part in lowered.split("/") if part]
    return any(token in lowered for token in SENSITIVE_NAME_TOKENS) or any(part.endswith((".log", ".sqlite", ".db")) for part in parts)


def _archive_members(path: Path) -> list[str]:
    if path.suffix.lower() != ".zip" or not path.exists():
        return []
    try:
        with zipfile.ZipFile(path, "r") as archive:
            return [str(name) for name in archive.namelist()]
    except Exception:
        return []


def _normalize_field(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _matching_fields(columns: list[str], names: set[str] = frozenset(), tokens: tuple[str, ...] = ()) -> list[str]:
    matched: list[str] = []
    for col in columns:
        norm = _normalize_field(col)
        if norm in names or any(token.lower() in norm for token in tokens):
            matched.append(col)
    return matched


def _dataframe_profile(df: pd.DataFrame) -> dict[str, Any]:
    columns = [str(col) for col in df.columns]
    numeric_fields = [str(col) for col in df.select_dtypes(include="number").columns]
    x_candidates = _matching_fields(columns, LON_NAMES)
    y_candidates = _matching_fields(columns, LAT_NAMES)
    time_candidates = _matching_fields(columns, tokens=TIME_TOKENS)
    preferred_targets = [
        field
        for field in _matching_fields(columns, tokens=TARGET_TOKENS)
        if field in numeric_fields and field not in set(x_candidates + y_candidates)
    ]
    target_candidates = preferred_targets or [
        field for field in numeric_fields if field not in set(x_candidates + y_candidates)
    ][:8]
    missing = []
    for col in columns:
        series = df[col]
        missing.append(
            {
                "field": col,
                "missing_count": int(series.isna().sum()),
                "missing_ratio": float(series.isna().mean()) if len(series) else 0.0,
            }
        )
    return {
        "columns": columns,
        "numeric_fields": numeric_fields,
        "x_candidates": x_candidates,
        "y_candidates": y_candidates,
        "time_candidates": time_candidates,
        "target_candidates": target_candidates,
        "missing_values": missing,
    }


def profile_dataset(manager: Any, dataset_name: str) -> dict[str, Any]:
    record = manager.get(dataset_name)
    meta = dict(record.meta or {})
    profile: dict[str, Any] = {
        "name": record.name,
        "data_type": record.data_type,
        "path": str(record.path),
        "meta": meta,
        "columns": list(meta.get("columns") or []),
        "numeric_fields": [],
        "x_candidates": [],
        "y_candidates": [],
        "time_candidates": [],
        "target_candidates": [],
    }
    if record.data_type == "table":
        profile.update(_dataframe_profile(manager.get_table(dataset_name)))
    elif record.data_type == "vector":
        gdf = manager.get_vector(dataset_name)
        profile.update(_dataframe_profile(gdf.drop(columns=["geometry"], errors="ignore")))
        profile["geometry_types"] = list(meta.get("geometry_types") or [])
        profile["crs"] = meta.get("crs")
        profile["bounds"] = meta.get("bounds")
    elif record.data_type == "raster":
        profile.update(
            {
                "crs": meta.get("crs"),
                "bounds": meta.get("bounds"),
                "width": meta.get("width"),
                "height": meta.get("height"),
                "nodata": meta.get("nodata"),
                "dtype": meta.get("dtype"),
            }
        )
    elif record.data_type == "document":
        profile["preview"] = str(meta.get("preview") or "")[:200]
    return profile


def build_data_package_profiles(manager: Any, dataset_names: list[str] | None = None) -> list[dict[str, Any]]:
    names = dataset_names or manager.list_dataset_names()
    profiles: list[dict[str, Any]] = []
    for name in names:
        try:
            profiles.append(profile_dataset(manager, str(name)))
        except Exception as exc:
            profiles.append({"name": str(name), "data_type": "unknown", "error": str(exc)})
    return profiles


def _goal_has(goal: str, tokens: tuple[str, ...]) -> bool:
    text = str(goal or "").lower()
    return any(token.lower() in text for token in tokens)


def _pick_primary_observation(profiles: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [item for item in profiles if item.get("data_type") in {"table", "vector"}]
    candidates.sort(
        key=lambda item: (
            bool(item.get("target_candidates")),
            bool(item.get("x_candidates") and item.get("y_candidates")) or item.get("data_type") == "vector",
            len(item.get("numeric_fields") or []),
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _feature_fields(profile: dict[str, Any], target_col: str) -> list[str]:
    blocked = {target_col, *(profile.get("x_candidates") or []), *(profile.get("y_candidates") or [])}
    return [field for field in profile.get("numeric_fields") or [] if field not in blocked]


def plan_data_package_analysis(profiles: list[dict[str, Any]], user_goal: str = "") -> dict[str, Any]:
    rasters = [item for item in profiles if item.get("data_type") == "raster"]
    vectors = [item for item in profiles if item.get("data_type") == "vector"]
    tables = [item for item in profiles if item.get("data_type") == "table"]
    primary = _pick_primary_observation(profiles)
    goal = str(user_goal or "")

    if _goal_has(goal, MODEL_GOAL_TOKENS) or (primary and primary.get("target_candidates")):
        if not primary:
            return {
                "intent": "modeling",
                "status": "needs_data",
                "missing_inputs": ["table_or_point_dataset"],
                "recommended_tools": ["ingest_data_package", "list_datasets"],
                "workflow_steps": [],
            }
        target_col = str((primary.get("target_candidates") or [""])[0])
        raster_names = [str(item.get("name")) for item in rasters]
        primary_name = str(primary.get("name") or "")
        steps: list[dict[str, Any]] = []
        point_dataset = primary_name
        if primary.get("data_type") == "table" and primary.get("x_candidates") and primary.get("y_candidates"):
            point_dataset = f"{_safe_name(primary_name)}_points"
            steps.append(
                {
                    "tool_name": "table_to_points",
                    "args": {
                        "dataset_name": primary_name,
                        "x_col": primary["x_candidates"][0],
                        "y_col": primary["y_candidates"][0],
                        "crs": "EPSG:4326",
                        "output_name": point_dataset,
                    },
                }
            )
        training_dataset = primary_name
        if raster_names and point_dataset:
            training_dataset = f"{_safe_name(primary_name)}_raster_features"
            steps.append(
                {
                    "tool_name": "batch_register_points_to_rasters",
                    "args": {
                        "point_name": point_dataset,
                        "raster_names": ",".join(raster_names),
                        "output_name": training_dataset,
                        "output_mode": "wide",
                        "value_field_prefix": "raster",
                    },
                }
            )
        feature_fields = _feature_fields(primary, target_col)
        if raster_names:
            feature_fields.extend([f"raster_{_safe_name(name)}" for name in raster_names])
        if not feature_fields:
            feature_fields = [field for field in primary.get("numeric_fields") or [] if field != target_col]
        steps.append(
            {
                "tool_name": "generic_xgboost_workflow",
                "args": {
                    "dataset_name": training_dataset,
                    "target_col": target_col,
                    "feature_cols": ",".join(feature_fields),
                    "output_name": f"{_safe_name(target_col)}_xgb",
                    "task_type": "regression",
                },
            }
        )
        missing: list[str] = []
        if not target_col:
            missing.append("target_col")
        if primary.get("data_type") == "table" and not (primary.get("x_candidates") and primary.get("y_candidates")) and rasters:
            missing.append("coordinate_fields")
        return {
            "intent": "modeling",
            "status": "ready" if not missing else "needs_params",
            "primary_dataset": primary_name,
            "target_col": target_col,
            "feature_cols": feature_fields,
            "raster_features": raster_names,
            "missing_inputs": missing,
            "recommended_tools": ["profile_missing_values", "batch_register_points_to_rasters", "generic_xgboost_workflow"],
            "workflow_steps": steps,
            "explanation": "Use observed table/point data as labels, optionally sample raster features, then train XGBoost.",
        }

    if _goal_has(goal, CLIP_GOAL_TOKENS) and rasters and vectors:
        return {
            "intent": "clip",
            "status": "ready",
            "primary_dataset": rasters[0]["name"],
            "boundary_dataset": vectors[0]["name"],
            "recommended_tools": ["clip_raster_by_vector"],
            "workflow_steps": [
                {
                    "tool_name": "clip_raster_by_vector",
                    "args": {
                        "raster_name": rasters[0]["name"],
                        "vector_name": vectors[0]["name"],
                        "output_name": f"{_safe_name(rasters[0]['name'])}_clipped",
                    },
                }
            ],
        }

    if _goal_has(goal, STATS_GOAL_TOKENS) and rasters and vectors:
        return {
            "intent": "zonal_statistics",
            "status": "ready",
            "recommended_tools": ["raster_zonal_stats"],
            "workflow_steps": [
                {
                    "tool_name": "raster_zonal_stats",
                    "args": {
                        "raster_name": rasters[0]["name"],
                        "polygon_name": vectors[0]["name"],
                        "output_name": f"{_safe_name(rasters[0]['name'])}_zonal_stats",
                    },
                }
            ],
        }

    if _goal_has(goal, MAP_GOAL_TOKENS):
        dataset = (vectors or rasters or tables or [{}])[0].get("name", "")
        return {
            "intent": "map_generation",
            "status": "ready" if dataset else "needs_data",
            "primary_dataset": dataset,
            "recommended_tools": ["plot_dataset"],
            "workflow_steps": [{"tool_name": "plot_dataset", "args": {"dataset_name": dataset, "output_name": f"{_safe_name(dataset)}_map"}}] if dataset else [],
        }

    return {
        "intent": "data_understanding",
        "status": "ready" if profiles else "needs_data",
        "primary_dataset": (primary or (profiles[0] if profiles else {})).get("name", ""),
        "recommended_tools": ["describe_dataset", "profile_missing_values", "detect_coordinate_fields"],
        "workflow_steps": [
            {"tool_name": "describe_dataset", "args": {"dataset_name": item["name"]}}
            for item in profiles[:5]
            if item.get("name")
        ],
        "explanation": "Profile the uploaded datasets before choosing modeling, clipping, statistics, or mapping tools.",
    }


def ingest_data_package(manager: Any, archive_path: str, user_goal: str = "", output_prefix: str = "") -> dict[str, Any]:
    path = Path(archive_path)
    members = _archive_members(path)
    sensitive_members = [name for name in members if _is_sensitive_member(name)]
    candidates = manager.inspect_zip_datasets(str(path))
    safe_candidates = [item for item in candidates if not _is_sensitive_member(str(item.get("member") or item.get("name") or ""))]
    loaded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    loaded_names: list[str] = []
    prefix = _safe_name(output_prefix or path.stem)
    for item in safe_candidates:
        member = str(item.get("member") or "")
        if not member:
            continue
        dataset_name = _safe_name(f"{prefix}_{Path(member).stem}")
        try:
            loaded_name = manager.load_path(str(path), name=dataset_name, original_filename=Path(member).name, zip_member=member)
            record = manager.get(loaded_name)
            loaded_names.append(loaded_name)
            loaded.append(
                {
                    "name": loaded_name,
                    "data_type": record.data_type,
                    "member": member,
                    "path": str(record.path),
                }
            )
        except Exception as exc:
            failed.append({"member": member, "error": str(exc)})
    profiles = build_data_package_profiles(manager, loaded_names)
    plan = plan_data_package_analysis(profiles, user_goal)
    result = {
        "ok": bool(loaded) and not failed,
        "archive_path": str(path),
        "loaded_count": len(loaded),
        "failed_count": len(failed),
        "loaded_datasets": loaded,
        "failed_members": failed,
        "skipped_members": sensitive_members,
        "profiles": profiles,
        "analysis_plan": plan,
    }
    try:
        manager.log_operation("数据包入库", f"{path.name} | loaded={len(loaded)} failed={len(failed)}", "upload")
    except Exception:
        pass
    return result


def format_ingest_message(result: dict[str, Any]) -> str:
    loaded = result.get("loaded_datasets") or []
    plan = result.get("analysis_plan") or {}
    lines = [
        f"数据包入库完成：已加载 {len(loaded)} 个数据集。",
    ]
    if loaded:
        lines.append("已识别数据：")
        for item in loaded[:12]:
            lines.append(f"- {item.get('name')}（{item.get('data_type')}）")
    if result.get("skipped_members"):
        lines.append(f"已跳过敏感或非分析文件：{', '.join(result['skipped_members'][:8])}")
    if result.get("failed_members"):
        lines.append(f"有 {len(result['failed_members'])} 个候选文件未能入库，请查看数据包画像。")
    if plan:
        lines.append(f"推荐分析方向：{plan.get('intent')}，状态：{plan.get('status')}")
        tools = plan.get("recommended_tools") or []
        if tools:
            lines.append(f"推荐工具链：{', '.join(tools)}")
    return "\n".join(lines)


def dumps_result(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
