from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
import rasterio


def _error(code: str, title: str, message: str, *, next_actions: list[str] | None = None, **diagnostics: Any) -> dict[str, Any]:
    return {
        "error_code": code,
        "error_title": title,
        "user_message": message,
        "next_actions": next_actions or [],
        "diagnostics": diagnostics,
    }


def first_error(errors: list[dict[str, Any]]) -> dict[str, Any] | None:
    return errors[0] if errors else None


def merge_next_actions(errors: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for error in errors:
        for action in error.get("next_actions") or []:
            if action not in actions:
                actions.append(str(action))
    return actions


def validation_diagnostics(errors: list[dict[str, Any]]) -> dict[str, Any]:
    return {"validation_errors": errors}


def validate_dataset_exists(manager: Any, dataset_name: str) -> list[dict[str, Any]]:
    if not str(dataset_name or "").strip():
        return [
            _error(
                "DATASET_REQUIRED",
                "缺少数据集",
                "请先指定要使用的数据集。",
                next_actions=["上传或导入数据后再运行工具。", "如果工作区已有数据，请明确数据集名称。"],
            )
        ]
    try:
        manager.get(dataset_name)
    except Exception as exc:
        names = []
        try:
            names = manager.list_dataset_names()
        except Exception:
            pass
        return [
            _error(
                "DATASET_NOT_FOUND",
                "数据集不存在",
                f"未找到数据集 {dataset_name}。",
                next_actions=["检查数据集名称是否拼写正确。", "先上传或导入需要处理的数据。"],
                available_datasets=names,
                technical_detail=str(exc),
            )
        ]
    return []


def _columns_for_record(manager: Any, dataset_name: str) -> list[str]:
    record = manager.get(dataset_name)
    if record.data_type == "table":
        return [str(col) for col in manager.get_table(dataset_name).columns]
    if record.data_type == "vector":
        return [str(col) for col in manager.get_vector(dataset_name).columns]
    return []


def validate_required_fields(manager: Any, dataset_name: str, fields: list[str]) -> list[dict[str, Any]]:
    requested = [str(field).strip() for field in fields if str(field or "").strip()]
    if not requested:
        return []
    try:
        available = _columns_for_record(manager, dataset_name)
    except Exception as exc:
        return [
            _error(
                "FIELD_VALIDATION_FAILED",
                "字段校验失败",
                "无法读取数据字段。",
                next_actions=["先检查数据集是否可读。"],
                technical_detail=str(exc),
            )
        ]
    missing = [field for field in requested if field not in available]
    if not missing:
        return []
    return [
        _error(
            "FIELD_NOT_FOUND",
            "字段不存在",
            f"未找到字段 {', '.join(missing)}。",
            next_actions=["从可用字段中选择一个字段。", "如果需要该指标，请先计算或连接生成对应字段。"],
            missing_fields=missing,
            available_fields=available,
        )
    ]


def validate_crs(manager: Any, dataset_name: str, *, required: bool = True) -> list[dict[str, Any]]:
    if not required:
        return []
    try:
        record = manager.get(dataset_name)
        crs = record.meta.get("crs") if isinstance(record.meta, dict) else None
    except Exception as exc:
        return [
            _error(
                "CRS_VALIDATION_FAILED",
                "坐标系校验失败",
                "无法读取数据集坐标系信息。",
                next_actions=["先确认数据集已经成功加载。"],
                technical_detail=str(exc),
            )
        ]
    if crs:
        return []
    return [
        _error(
            "CRS_REQUIRED",
            "缺少坐标系",
            f"数据集 {dataset_name} 缺少 CRS，无法可靠执行空间分析或制图。",
            next_actions=["为数据补充正确 CRS 后重试。", "如果是 Shapefile，请上传包含 .prj 的完整文件。"],
        )
    ]


def validate_geometry_type(manager: Any, dataset_name: str, allowed: list[str]) -> list[dict[str, Any]]:
    try:
        record = manager.get(dataset_name)
        geom_types = record.meta.get("geometry_types") if isinstance(record.meta, dict) else []
    except Exception as exc:
        return [
            _error(
                "GEOMETRY_VALIDATION_FAILED",
                "几何类型校验失败",
                "无法读取几何类型。",
                next_actions=["先确认矢量数据可读。"],
                technical_detail=str(exc),
            )
        ]
    allowed_set = {str(item) for item in allowed}
    actual = {str(item) for item in geom_types or []}
    if actual and actual.issubset(allowed_set):
        return []
    return [
        _error(
            "GEOMETRY_TYPE_UNSUPPORTED",
            "几何类型不支持",
            f"当前几何类型 {sorted(actual)} 不满足工具要求。",
            next_actions=["请使用符合要求的几何类型，或先转换数据。"],
            required_geometry=sorted(allowed_set),
            actual_geometry=sorted(actual),
        )
    ]


def validate_numeric_fields(manager: Any, dataset_name: str, fields: list[str]) -> list[dict[str, Any]]:
    requested = [str(field).strip() for field in fields if str(field or "").strip()]
    if not requested:
        return []
    try:
        record = manager.get(dataset_name)
        if record.data_type == "vector":
            df = pd.DataFrame(manager.get_vector(dataset_name).drop(columns=["geometry"], errors="ignore"))
        else:
            df = manager.get_table(dataset_name)
    except Exception as exc:
        return [
            _error(
                "NUMERIC_FIELD_VALIDATION_FAILED",
                "数值字段校验失败",
                "无法读取数据表。",
                next_actions=["先确认数据集类型和字段是否正确。"],
                technical_detail=str(exc),
            )
        ]
    invalid = []
    for field in requested:
        numeric = pd.to_numeric(df[field], errors="coerce") if field in df.columns else pd.Series(dtype=float)
        if int(numeric.notna().sum()) == 0:
            invalid.append(field)
    if not invalid:
        return []
    return [
        _error(
            "NUMERIC_FIELD_REQUIRED",
            "字段不是可用数值字段",
            f"字段 {', '.join(invalid)} 没有可用数值，不能用于制图或建模。",
            next_actions=["选择数值字段。", "先清洗或转换字段为数值类型。"],
            invalid_fields=invalid,
        )
    ]


def validate_output_path(root: Path, output_name: str, *, allowed_suffixes: set[str] | None = None) -> list[dict[str, Any]]:
    name = str(output_name or "").strip()
    if not name:
        return []
    if Path(name).name != name or re.search(r"[\\/]", name):
        return [
            _error(
                "OUTPUT_PATH_UNSAFE",
                "输出路径不安全",
                "输出名称不能包含目录或路径分隔符。",
                next_actions=["只提供简单文件名或结果名前缀。"],
            )
        ]
    suffixes = allowed_suffixes or set()
    if suffixes and Path(name).suffix and Path(name).suffix.lower() not in suffixes:
        return [
            _error(
                "OUTPUT_SUFFIX_UNSUPPORTED",
                "输出格式不支持",
                f"输出后缀必须是 {sorted(suffixes)} 之一。",
                next_actions=["修改输出名称后缀或只提供无后缀前缀。"],
            )
        ]
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return [
            _error(
                "OUTPUT_DIRECTORY_UNAVAILABLE",
                "输出目录不可用",
                "无法访问输出目录。",
                next_actions=["检查工作区权限和磁盘状态。"],
                technical_detail=str(exc),
            )
        ]
    return []


def validate_output_file_path(root: Path, output_path: str, *, allowed_suffixes: set[str] | None = None) -> list[dict[str, Any]]:
    raw = str(output_path or "").strip()
    if not raw:
        return []
    suffixes = allowed_suffixes or set()
    suffix = Path(raw).suffix.lower()
    if suffixes and suffix and suffix not in suffixes:
        return [
            _error(
                "OUTPUT_SUFFIX_UNSUPPORTED",
                "输出格式不支持",
                f"输出文件后缀必须是 {sorted(suffixes)} 之一。",
                next_actions=["修改输出文件后缀，或选择受支持的导出格式。"],
            )
        ]
    root_resolved = Path(root).resolve()
    candidate = Path(raw)
    target = candidate.resolve() if candidate.is_absolute() else (root_resolved / candidate).resolve()
    try:
        target.relative_to(root_resolved)
    except Exception:
        return [
            _error(
                "OUTPUT_PATH_UNSAFE",
                "输出路径不安全",
                "输出路径必须位于当前用户工作区内，不能写入工作区外部位置。",
                next_actions=["使用工作区内的相对路径，例如 exports/result.csv。"],
            )
        ]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return [
            _error(
                "OUTPUT_DIRECTORY_UNAVAILABLE",
                "输出目录不可用",
                "无法访问输出目录。",
                next_actions=["检查工作区权限和磁盘状态。"],
                technical_detail=str(exc),
            )
        ]
    return []


def validate_model_target(manager: Any, dataset_name: str, target_col: str) -> list[dict[str, Any]]:
    target = str(target_col or "").strip()
    if not target:
        return [
            _error(
                "TARGET_FIELD_MISSING",
                "缺少目标变量",
                "请指定要预测的目标变量字段。",
                next_actions=["从数值字段中选择一个目标变量。", "如果不确定，先运行数据描述或缺失值检查。"],
            )
        ]
    return validate_required_fields(manager, dataset_name, [target]) + validate_numeric_fields(manager, dataset_name, [target])


def validate_raster_readable(manager: Any, dataset_name: str) -> list[dict[str, Any]]:
    try:
        path = manager.get_raster_path(dataset_name)
        with rasterio.open(path) as src:
            if src.count < 1:
                raise ValueError("raster has no bands")
    except Exception as exc:
        return [
            _error(
                "RASTER_NOT_READABLE",
                "栅格不可读",
                f"数据集 {dataset_name} 不是可读栅格。",
                next_actions=["确认栅格文件存在且格式受支持。"],
                technical_detail=str(exc),
            )
        ]
    return []


def validate_vector_readable(manager: Any, dataset_name: str) -> list[dict[str, Any]]:
    try:
        gdf = manager.get_vector(dataset_name)
        if "geometry" not in gdf.columns:
            raise ValueError("missing geometry column")
    except Exception as exc:
        return [
            _error(
                "VECTOR_NOT_READABLE",
                "矢量不可读",
                f"数据集 {dataset_name} 不是可读矢量。",
                next_actions=["确认矢量文件完整，Shapefile 需包含必要配套文件。"],
                technical_detail=str(exc),
            )
        ]
    return []
