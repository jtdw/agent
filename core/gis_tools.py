from __future__ import annotations

import contextlib
import difflib
import io
import json
import math
import os
import re
import shutil
import warnings
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import pyogrio
import rasterio
import torch
from langchain.tools import tool
from matplotlib import font_manager as fm
from matplotlib import pyplot as plt
from pyproj import CRS
from scipy.optimize import minimize
from rasterio.io import MemoryFile
from rasterio.mask import mask
from rasterio.merge import merge as raster_merge
from rasterio.plot import show as raster_show
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GroupKFold
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

try:
    from xgboost import XGBRegressor
except Exception:
    XGBRegressor = None

from .data_manager import DataManager
from .model_results import generate_model_result_id
from .resource_tools import build_resource_tools
from .tool_contracts import ArtifactInfo, parse_tool_result, tool_result_error, tool_result_ok
from .tool_preconditions import (
    first_error,
    merge_next_actions,
    validate_crs,
    validate_dataset_exists,
    validate_geometry_type,
    validate_model_target,
    validate_numeric_fields,
    validate_output_file_path,
    validate_output_path,
    validate_raster_readable,
    validate_required_fields,
    validate_vector_readable,
    validation_diagnostics,
)


matplotlib.use("Agg")
torch.set_num_threads(1)
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass


VISUAL_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
LON_NAMES = {"lon", "lng", "long", "longitude", "经度", "x", "coord_x", "point_x"}
LAT_NAMES = {"lat", "latitude", "纬度", "y", "coord_y", "point_y"}
SEASON_MAP = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM", 6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}


def _map_layer_id(dataset_name: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_]+", "_", str(dataset_name or "").strip()).strip("_").lower()
    return f"dataset_{clean or 'layer'}"


def _dataset_map_kind(name: str, data_type: str) -> str:
    text = str(name or "").lower()
    if any(token in text for token in ["ndvi", "evi", "vegetation"]):
        return "vegetation"
    if any(token in text for token in ["soil", "moisture", "sm", "prediction", "result"]):
        return "soil"
    if any(token in text for token in ["dem", "elevation", "srtm", "aster", "terrain", "slope", "aspect"]):
        return "dem"
    if any(token in text for token in ["boundary", "region", "aoi", "basin", "admin"]):
        return "boundary"
    return "boundary" if data_type == "vector" else "dem"


def _spatial_meta_for_record(manager: DataManager, dataset_name: str, *, artifact_id: str = "", source_tool: str = "") -> dict[str, Any]:
    record = manager.get(dataset_name)
    meta = dict(record.meta or {})
    if record.data_type == "raster":
        try:
            with rasterio.open(manager.get_raster_path(dataset_name)) as src:
                meta.update(
                    {
                        "crs": str(src.crs) if src.crs else "",
                        "width": int(src.width),
                        "height": int(src.height),
                        "band_count": int(src.count),
                        "dtype": str(src.dtypes[0]) if src.dtypes else "",
                        "nodata": src.nodata,
                    }
                )
        except Exception:
            pass
    elif record.data_type == "vector":
        try:
            gdf = manager.get_vector(dataset_name)
            meta.update(
                {
                    "crs": str(gdf.crs) if gdf.crs else "",
                    "feature_count": int(len(gdf)),
                    "bounds": [float(v) for v in (gdf.to_crs("EPSG:4326") if gdf.crs else gdf).total_bounds.tolist()] if len(gdf) else [],
                }
            )
        except Exception:
            pass
    meta.update(
        {
            "map_ready": record.data_type in {"vector", "raster"},
            "dataset_name": dataset_name,
            "map_layer_id": _map_layer_id(dataset_name),
            "layer_kind": _dataset_map_kind(dataset_name, record.data_type),
            "artifact_id": artifact_id,
            "source_tool": source_tool,
        }
    )
    return meta


def _map_ready_outputs(manager: DataManager, dataset_name: str, *, source_tool: str = "") -> dict[str, Any]:
    meta = _spatial_meta_for_record(manager, dataset_name, source_tool=source_tool)
    return {
        "result_dataset": dataset_name,
        "dataset_name": dataset_name,
        "map_ready": bool(meta.get("map_ready")),
        "map_layer_id": meta.get("map_layer_id"),
        "spatial_meta": meta,
    }


def _configure_matplotlib_fonts() -> str | None:
    candidates = [
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "WenQuanYi Zen Hei",
        "Arial Unicode MS",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    plt.rcParams["axes.unicode_minus"] = False
    warnings.filterwarnings("ignore", message=r"Glyph .* missing from font", category=UserWarning)
    return None


_ACTIVE_FONT = _configure_matplotlib_fonts()


def _safe_map_title(title: str) -> str:
    if _ACTIVE_FONT or not title:
        return title
    try:
        title.encode("ascii")
        return title
    except UnicodeEncodeError:
        return "Map Output"


def _json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _tool_error_from_validation(tool_name: str, inputs: dict[str, Any], errors: list[dict[str, Any]]) -> str:
    first = first_error(errors) or {}
    return tool_result_error(
        tool_name,
        inputs=inputs,
        error_code=str(first.get("error_code") or "TOOL_PRECONDITION_FAILED"),
        error_title=str(first.get("error_title") or "工具前置条件不满足"),
        user_message=str(first.get("user_message") or "工具执行前缺少必要条件。"),
        diagnostics=validation_diagnostics(errors),
        next_actions=merge_next_actions(errors),
        technical_detail=str(first.get("diagnostics", {}).get("technical_detail") or ""),
    ).to_json()


def _tool_internal_error(tool_name: str, inputs: dict[str, Any], exc: Exception) -> str:
    return tool_result_error(
        tool_name,
        inputs=inputs,
        error_code="INTERNAL_TOOL_ERROR",
        error_title="工具执行失败",
        user_message="工具执行过程中出现未预期错误，已保留技术细节供排查。",
        diagnostics={"exception_type": type(exc).__name__},
        next_actions=["检查输入数据、字段、坐标系和输出名称后重试。"],
        technical_detail=f"{type(exc).__name__}: {exc}",
    ).to_json()


def _estimate_projected_gdf(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, str]:
    if gdf.crs is None:
        raise ValueError("该矢量图层没有 CRS，无法可靠进行距离、面积或长度分析。请先补充坐标系。")
    if gdf.crs.is_projected:
        return gdf, str(gdf.crs)
    utm_crs = gdf.estimate_utm_crs()
    if utm_crs is None:
        raise ValueError("无法自动估计投影坐标系，建议先重投影后再进行距离/面积分析。")
    return gdf.to_crs(utm_crs), str(utm_crs)


def _align_crs(left: gpd.GeoDataFrame, right: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    if left.crs and right.crs and left.crs != right.crs:
        right = right.to_crs(left.crs)
    return left, right


def _coerce_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _infer_coordinate_candidates(df: pd.DataFrame) -> dict[str, list[dict[str, str | float]]]:
    lon_candidates: list[dict[str, str | float]] = []
    lat_candidates: list[dict[str, str | float]] = []

    for col in df.columns:
        col_str = str(col)
        lowered = col_str.strip().lower()
        numeric = _coerce_numeric_series(df[col])
        valid_ratio = float(numeric.notna().mean()) if len(df) else 0.0
        if valid_ratio < 0.6:
            continue

        item = {"field": col_str, "numeric_ratio": round(valid_ratio, 3)}
        if lowered in LON_NAMES or any(token in lowered for token in ("lon", "lng", "long", "经度")):
            lon_candidates.append(item)
        if lowered in LAT_NAMES or any(token in lowered for token in ("lat", "纬度")):
            lat_candidates.append(item)
        if lowered == "x":
            lon_candidates.append(item)
        if lowered == "y":
            lat_candidates.append(item)

    return {
        "x_candidates": lon_candidates,
        "y_candidates": lat_candidates,
    }


def _prepare_join_frame(record_name: str, manager: DataManager) -> tuple[pd.DataFrame | gpd.GeoDataFrame, str]:
    record = manager.get(record_name)
    if record.data_type == "vector":
        gdf = manager.get_vector(record_name)
        return gdf.copy(), "vector"
    if record.data_type == "table":
        return manager.get_table(record_name), "table"
    raise TypeError(f"{record_name} 不是表格或矢量数据，无法做属性连接。")


def _parse_columns(columns_text: str) -> list[str]:
    items = [item.strip() for item in re.split(r"[,;，\s]+", columns_text or "") if item.strip()]
    if not items:
        raise ValueError("请至少提供一个字段名，多个字段可用逗号分隔。")
    return items


def _normalize_column_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def _resolve_existing_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    available = [str(col) for col in df.columns]
    normalized_available = {_normalize_column_key(col): col for col in available}
    resolved: list[str] = []

    for requested in columns:
        if requested in df.columns:
            resolved.append(requested)
            continue

        normalized_requested = _normalize_column_key(requested)
        if normalized_requested in normalized_available:
            resolved.append(normalized_available[normalized_requested])
            continue

        prefix_matches = [col for col in available if _normalize_column_key(col).startswith(normalized_requested) or normalized_requested.startswith(_normalize_column_key(col))]
        if len(prefix_matches) == 1:
            resolved.append(prefix_matches[0])
            continue

        close_matches = difflib.get_close_matches(
            normalized_requested,
            [_normalize_column_key(col) for col in available],
            n=1,
            cutoff=0.75,
        )
        if close_matches:
            resolved.append(normalized_available[close_matches[0]])
            continue

        raise ValueError(f"字段不存在: {requested}。可用字段: {available}")

    return resolved


def _infer_observed_column(
    df: pd.DataFrame,
    explicit_observed: str = "",
    predicted_cols: list[str] | None = None,
    target_hint: str = "",
) -> str:
    predicted_cols = [str(col) for col in (predicted_cols or [])]
    if explicit_observed.strip():
        return _resolve_existing_columns(df, [explicit_observed.strip()])[0]

    available = [str(col) for col in df.columns]
    normalized_map = {_normalize_column_key(col): col for col in available}
    blocked = {_normalize_column_key(col) for col in predicted_cols}

    direct_candidates = [
        target_hint,
        "sm_obs",
        "observed",
        "obs",
        "observation",
        "actual",
        "truth",
        "ground_truth",
        "reference",
        "ref",
        "target",
        "label",
        "measured",
        "measurement",
        "y",
    ]
    for candidate in direct_candidates:
        if not str(candidate).strip():
            continue
        normalized = _normalize_column_key(str(candidate))
        resolved = normalized_map.get(normalized)
        if resolved and normalized not in blocked:
            return resolved

    keyword_hits: list[str] = []
    keywords = ["obs", "observ", "actual", "truth", "reference", "target", "label", "measur", "groundtruth", "groundtruth"]
    for col in available:
        normalized = _normalize_column_key(col)
        if normalized in blocked:
            continue
        if any(word in normalized for word in keywords):
            keyword_hits.append(col)
    if len(keyword_hits) == 1:
        return keyword_hits[0]

    numeric_candidates: list[str] = []
    for col in available:
        normalized = _normalize_column_key(col)
        if normalized in blocked or normalized == "geometry":
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        if series.notna().sum() > 0:
            numeric_candidates.append(col)

    prioritized_numeric = [
        col for col in numeric_candidates
        if any(word in _normalize_column_key(col) for word in ["obs", "observ", "actual", "truth", "reference", "target", "label", "measur"])
    ]
    if len(prioritized_numeric) == 1:
        return prioritized_numeric[0]

    if target_hint.strip():
        try:
            resolved_hint = _resolve_existing_columns(df, [target_hint.strip()])[0]
            if _normalize_column_key(resolved_hint) not in blocked:
                return resolved_hint
        except Exception:
            pass

    candidate_preview = prioritized_numeric[:8] or numeric_candidates[:8] or available[:8]
    raise ValueError(
        "无法自动识别 observed_col。请显式提供 observed_col，"
        f"或使用这些候选字段之一: {candidate_preview}"
    )


def _parse_int_list(text: str, default: list[int]) -> list[int]:
    if not text.strip():
        return default
    values = []
    for item in re.split(r"[,;，\s]+", text.strip()):
        if not item:
            continue
        values.append(int(item))
    return values or default


def _validate_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise ValueError(f"以下字段不存在: {missing}。可用字段: {list(df.columns)}")


def _heading_like_lines(text: str, max_items: int = 30) -> list[str]:
    patterns = [
        re.compile(r"^\d+(?:\.\d+)*[、.\s].+"),
        re.compile(r"^[（(]?[一二三四五六七八九十]+[)）、.\s].+"),
        re.compile(r"^(研究目标|研究内容|研究方案|技术路线|进度安排|文献综述|立题依据|目的意义|现有研究不足).+"),
    ]
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(line) > 80:
            continue
        if any(p.match(line) for p in patterns):
            if line not in lines:
                lines.append(line)
        elif 2 <= len(line) <= 22 and not line.endswith(("。", "；", ",", "，", ":", "：")):
            if line not in lines:
                lines.append(line)
        if len(lines) >= max_items:
            break
    return lines


def _make_text_snippets(text: str, keyword: str, context_chars: int = 120, max_hits: int = 8) -> list[dict[str, str | int]]:
    lowered = text.lower()
    needle = keyword.lower()
    hits = []
    start = 0
    while len(hits) < max_hits:
        idx = lowered.find(needle, start)
        if idx < 0:
            break
        left = max(0, idx - context_chars)
        right = min(len(text), idx + len(keyword) + context_chars)
        snippet = text[left:right].replace("\n", " ").strip()
        hits.append({"position": idx, "snippet": snippet})
        start = idx + len(keyword)
    return hits


def _prepare_dataframe(record_name: str, manager: DataManager) -> pd.DataFrame:
    record = manager.get(record_name)
    if record.data_type == "table":
        return manager.get_table(record_name)
    if record.data_type == "vector":
        gdf = manager.get_vector(record_name)
        return pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))
    raise TypeError(f"{record_name} 不是表格或矢量属性数据。")


def _prepare_dataframe_with_geometry(record_name: str, manager: DataManager) -> tuple[pd.DataFrame, gpd.GeoDataFrame | None]:
    record = manager.get(record_name)
    if record.data_type == "table":
        return manager.get_table(record_name).copy(), None
    if record.data_type == "vector":
        gdf = manager.get_vector(record_name).copy()
        return pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore")), gdf
    raise TypeError(f"{record_name} 不是表格或矢量属性数据。")


def _vector_has_point_geometry(gdf: gpd.GeoDataFrame) -> bool:
    geom_types = {str(v) for v in gdf.geometry.geom_type.dropna().unique()}
    return bool(geom_types) and geom_types.issubset({"Point"})


def _append_spatial_coordinates(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, str]:
    if gdf.empty:
        raise ValueError("矢量数据为空，无法进行空间回归。")
    if gdf.crs is None:
        raise ValueError("矢量数据缺少 CRS，无法可靠处理空间距离与空间自相关。")
    if not _vector_has_point_geometry(gdf):
        raise ValueError("当前空间回归仅支持点图层，请先将样本准备为 Point 类型矢量数据。")

    projected, projected_crs = _estimate_projected_gdf(gdf)
    work = gdf.copy()
    work["__spatial_x__"] = projected.geometry.x
    work["__spatial_y__"] = projected.geometry.y
    return work, projected_crs


def _make_spatial_blocks(gdf: gpd.GeoDataFrame, n_blocks: int = 5, random_state: int = 42) -> pd.Series:
    if "__spatial_x__" not in gdf.columns or "__spatial_y__" not in gdf.columns:
        raise ValueError("缺少空间坐标字段，无法进行空间分块。")
    coords = gdf[["__spatial_x__", "__spatial_y__"]].to_numpy(dtype=float)
    if len(coords) < 2:
        raise ValueError("样本量不足，无法进行空间分块交叉验证。")
    block_count = max(2, min(int(n_blocks), len(coords)))
    labels = KMeans(n_clusters=block_count, random_state=random_state, n_init=10).fit_predict(coords)
    return pd.Series(labels, index=gdf.index, name="__spatial_block__")


def _calc_global_moran_i(
    values: pd.Series,
    x_coords: pd.Series,
    y_coords: pd.Series,
    k_neighbors: int = 8,
    permutations: int = 199,
    random_state: int = 42,
) -> dict[str, Any]:
    frame = pd.DataFrame({
        "value": pd.to_numeric(values, errors="coerce"),
        "x": pd.to_numeric(x_coords, errors="coerce"),
        "y": pd.to_numeric(y_coords, errors="coerce"),
    }).dropna()
    n = len(frame)
    if n < 5:
        return {"moran_i": None, "p_value": None, "n": int(n), "k_neighbors": None}

    coords = frame[["x", "y"]].to_numpy(dtype=float)
    z = frame["value"].to_numpy(dtype=float)
    z = z - np.mean(z)
    denominator = float(np.sum(z ** 2))
    if denominator <= 0:
        return {"moran_i": None, "p_value": None, "n": int(n), "k_neighbors": None}

    k_use = max(1, min(int(k_neighbors), n - 1))
    nn = NearestNeighbors(n_neighbors=k_use + 1)
    nn.fit(coords)
    _, indices = nn.kneighbors(coords)

    weights = np.zeros((n, n), dtype=float)
    for i in range(n):
        weights[i, indices[i, 1:]] = 1.0
    weights = np.maximum(weights, weights.T)
    np.fill_diagonal(weights, 0.0)

    s0 = float(weights.sum())
    if s0 <= 0:
        return {"moran_i": None, "p_value": None, "n": int(n), "k_neighbors": int(k_use)}

    moran_i = float((n / s0) * ((z @ weights @ z) / denominator))

    rng = np.random.default_rng(random_state)
    permuted = []
    perm_count = max(0, int(permutations))
    for _ in range(perm_count):
        shuffled = rng.permutation(z)
        permuted.append(float((n / s0) * ((shuffled @ weights @ shuffled) / denominator)))

    p_value = None
    if permuted:
        extreme = sum(abs(val) >= abs(moran_i) for val in permuted)
        p_value = float((extreme + 1) / (len(permuted) + 1))

    return {
        "moran_i": moran_i,
        "p_value": p_value,
        "n": int(n),
        "k_neighbors": int(k_use),
        "permutations": int(perm_count),
    }


def _build_xgb_pipeline(
    n_estimators: int,
    max_depth: int,
    learning_rate: float,
    subsample: float,
    colsample_bytree: float,
    random_state: int,
) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("xgb", XGBRegressor(
            objective="reg:squarederror",
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            random_state=random_state,
            n_jobs=1,
            tree_method="hist",
        )),
    ])


def _save_vector_map_plot(gdf: gpd.GeoDataFrame, output_path: Path, column: str = "", title: str = "") -> None:
    fig, ax = plt.subplots(figsize=(9.6, 6.8))
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#f8fafc")

    if column and column in gdf.columns:
        gdf.plot(ax=ax, column=column, legend=True, cmap="viridis", edgecolor="#334155", linewidth=0.5)
    else:
        gdf.plot(ax=ax, color="#38bdf8", edgecolor="#0f172a", linewidth=0.6)

    ax.set_title(_safe_map_title(title), color="#e2e8f0", pad=12)
    ax.grid(alpha=0.15)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    fig.savefig(output_path, dpi=220, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def _ensure_datetime(df: pd.DataFrame, date_col: str) -> pd.Series:
    if date_col not in df.columns:
        raise ValueError(f"时间字段不存在: {date_col}。可用字段: {list(df.columns)}")
    series = pd.to_datetime(df[date_col], errors="coerce")
    if series.notna().sum() == 0:
        raise ValueError(f"字段 {date_col} 无法解析为日期时间。")
    return series


def _calc_metrics(obs: pd.Series, pred: pd.Series) -> dict[str, float | int | None]:
    paired = pd.DataFrame({"obs": pd.to_numeric(obs, errors="coerce"), "pred": pd.to_numeric(pred, errors="coerce")}).dropna()
    n = len(paired)
    if n == 0:
        return {"n": 0, "R": None, "RMSE": None, "ubRMSE": None, "Bias": None, "NSE": None, "MAE": None}

    err = paired["pred"] - paired["obs"]
    bias = float(err.mean())
    rmse = float(np.sqrt(np.mean(np.square(err))))
    ubrmse = float(np.sqrt(np.mean(np.square(err - bias))))
    mae = float(np.mean(np.abs(err)))
    if n >= 2 and paired["obs"].std(ddof=0) > 0 and paired["pred"].std(ddof=0) > 0:
        r = float(np.corrcoef(paired["obs"], paired["pred"])[0, 1])
    else:
        r = None
    denom = float(np.sum(np.square(paired["obs"] - paired["obs"].mean())))
    nse = None if math.isclose(denom, 0.0) else float(1 - (np.sum(np.square(err)) / denom))
    return {"n": int(n), "R": r, "RMSE": rmse, "ubRMSE": ubrmse, "Bias": bias, "NSE": nse, "MAE": mae}

def _artifact_safe_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip())
    return safe or "artifact"


def _save_json_artifact(manager: DataManager, stem: str, payload: dict[str, Any] | list[Any]) -> Path:
    path = manager.derived_dir / f"{_artifact_safe_name(stem)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _save_markdown_artifact(manager: DataManager, stem: str, text: str) -> Path:
    path = manager.derived_dir / f"{_artifact_safe_name(stem)}.md"
    path.write_text(text, encoding="utf-8")
    try:
        manager.put_text_document(stem, text, filename=path.name)
    except Exception:
        pass
    return path


def _resolve_document_text_input(manager: DataManager, value: str) -> tuple[str, str]:
    raw = (value or "").strip()
    if not raw:
        return "", ""

    try:
        return manager.get_document_text(raw), raw
    except Exception:
        pass

    candidate_paths: list[Path] = []
    raw_path = Path(raw)
    if raw_path.exists() and raw_path.is_file():
        candidate_paths.append(raw_path)

    for base in (manager.derived_dir, manager.plot_dir):
        candidate_paths.extend([
            base / raw,
            base / f"{raw}.md",
            base / f"{raw}.txt",
        ])

    for artifact in manager.list_artifacts():
        artifact_path = Path(artifact.get("path", ""))
        if not artifact_path.exists() or not artifact_path.is_file():
            continue
        if raw in {artifact.get("name", ""), artifact_path.stem, artifact_path.name, str(artifact_path)}:
            candidate_paths.append(artifact_path)

    seen: set[str] = set()
    for candidate in candidate_paths:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8"), str(candidate)
            except Exception:
                continue

    return "", raw


def _make_pipeline_run_id(output_prefix: str) -> str:
    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    return f"pipe_{_artifact_safe_name(output_prefix)}_{timestamp}_{uuid4().hex[:6]}"


def _pick_metric_scope(df: pd.DataFrame) -> pd.Series:
    work = df.copy()
    if "scope" in work.columns:
        scope_order = {"test": 0, "all": 1, "train": 2}
        work["_scope_order"] = work["scope"].astype(str).str.lower().map(scope_order).fillna(9)
        work = work.sort_values(["_scope_order"]).reset_index(drop=True)
    return work.iloc[0]


def _metric_row_with_label(df: pd.DataFrame, predicted: str, model_name: str) -> dict[str, Any]:
    row = _pick_metric_scope(df)
    payload = {"predicted": predicted, "model": model_name, "scope": row.get("scope", "all")}
    for col in ["n", "R", "RMSE", "ubRMSE", "Bias", "NSE", "MAE"]:
        payload[col] = None if col not in row.index or pd.isna(row[col]) else row[col]
    return payload


def _pipeline_steps_markdown(run_detail: dict[str, Any]) -> str:
    lines = [
        f"# 数据库驱动训练流水线记录：{run_detail.get('run_id', '')}" ,
        "",
        f"- 流水线名称：{run_detail.get('pipeline_name', '')}" ,
        f"- 状态：{run_detail.get('status', '')}" ,
        f"- 数据来源：{run_detail.get('source_type', '')} | {run_detail.get('source_value', '')}" ,
        f"- 输出前缀：{run_detail.get('output_prefix', '')}" ,
        f"- 开始时间：{run_detail.get('started_at', '')}" ,
        f"- 完成时间：{run_detail.get('finished_at', '')}" ,
        "",
    ]
    summary = run_detail.get("summary") or {}
    reports = summary.get("reports") if isinstance(summary, dict) else {}
    metrics_dataset = reports.get("metrics_dataset", "") if isinstance(reports, dict) else ""
    gcp_metrics_dataset = reports.get("gcp_metrics_dataset", "") if isinstance(reports, dict) else ""
    if metrics_dataset or gcp_metrics_dataset:
        lines.append("## 结果类型概览")
        if metrics_dataset:
            lines.append(f"- 点预测精度结果：{metrics_dataset}")
        if gcp_metrics_dataset:
            lines.append(f"- GCP 不确定性结果：{gcp_metrics_dataset}")
        lines.append("")
    lines.append("## 处理步骤")
    for step in run_detail.get("steps", []):
        lines.extend([
            f"### {step.get('step_order')}. {step.get('step_name')}（{step.get('status')}）" ,
            f"- 输入：{step.get('input_summary', '') or '—'}" ,
            f"- 输出：{step.get('output_summary', '') or '—'}" ,
        ])
        detail = step.get("detail") or {}
        if detail:
            detail_lines = []
            for key, value in detail.items():
                if isinstance(value, (list, dict)):
                    detail_lines.append(f"  - {key}: {json.dumps(value, ensure_ascii=False, default=str)}")
                else:
                    detail_lines.append(f"  - {key}: {value}")
            if detail_lines:
                lines.append("- 细节：")
                lines.extend(detail_lines)
        lines.append("")
    if summary:
        if metrics_dataset or gcp_metrics_dataset:
            lines.append("## 汇报建议")
            if metrics_dataset:
                lines.append(f"- 点预测精度请优先引用：{metrics_dataset}")
            if gcp_metrics_dataset:
                lines.append(f"- GCP 不确定性请优先引用：{gcp_metrics_dataset}")
            lines.append("- 汇报时建议先讲点预测精度，再讲 GCP 区间可靠性与紧致性，避免把两类指标混在同一张表内解释。")
            lines.append("")
        lines.append("## 输出摘要")
        for key, value in summary.items():
            lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (list, dict)) else value}")
        lines.append("")
    lines.extend([
        "## 给新手的说明",
        "- 先从数据库查询或已有表生成训练表。",
        "- 然后检查缺失值和时间字段，必要时补充时序特征。",
        "- 再分别运行 BTCH、RF、XGBoost、LSTM。",
        "- 最后把点预测精度表、GCP 不确定性表、图表和阶段材料统一回写到工作区，便于复用。",
    ])
    return "\n".join(lines)

def _find_dataset_by_keywords(manager: DataManager, keywords: list[str], data_types: set[str] | None = None) -> str | None:
    lowered = [kw.lower() for kw in keywords if kw]
    for name, record in manager.datasets.items():
        if data_types and record.data_type not in data_types:
            continue
        joined = f"{name} {record.path.name}".lower()
        if all(kw in joined for kw in lowered):
            return name
    return None


def _related_dataset_prefix(name: str) -> str:
    base = (name or '').strip()
    for suffix in [
        '_combined_gcp_metrics',
        '_combined_metrics',
        '_gcp_metrics',
        '_metrics',
        '_summary',
        '_moran_i',
        '_rf_importance',
        '_xgb_importance',
        '_importance',
    ]:
        if base.endswith(suffix):
            return base[:-len(suffix)]
    return base


def _find_dataset_with_columns(
    manager: DataManager,
    required_columns: list[str],
    current_dataset: str = '',
) -> str | None:
    required = [str(col).strip() for col in required_columns if str(col).strip()]
    if not required:
        return None

    prefix = _related_dataset_prefix(current_dataset)
    candidates: list[tuple[int, str]] = []
    for name, record in manager.datasets.items():
        if name == current_dataset:
            continue
        if record.data_type not in {'table', 'vector'}:
            continue
        available = set(record.meta.get('columns', []))
        if not all(col in available for col in required):
            continue

        score = 0
        if prefix and name.startswith(prefix):
            score += 8
        if prefix and prefix in name:
            score += 3
        if record.data_type == 'vector':
            score += 2
        if 'result' in name:
            score += 2
        score -= len(name)
        candidates.append((score, name))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _first_nonempty_text(text: str, fallback: str) -> str:
    return text.strip() if text and text.strip() else fallback


def _table_markdown(df: pd.DataFrame, max_rows: int = 12) -> str:
    if df.empty:
        return "（空表）"
    view = df.head(max_rows).copy()
    return view.to_markdown(index=False)


def _ensure_metric_predicted_column(df: pd.DataFrame, dataset_name: str = "") -> pd.DataFrame:
    work = df.copy()
    if 'predicted' in work.columns:
        work['predicted'] = work['predicted'].astype(str)
        return work

    fallback_col = None
    for candidate in ['model', 'product', 'name', 'dataset', 'label', 'series', 'method', 'prediction_column']:
        if candidate in work.columns:
            fallback_col = candidate
            break
    if fallback_col is not None:
        work['predicted'] = work[fallback_col].astype(str)
        return work

    base_label = (dataset_name or 'result').strip() or 'result'
    if len(work) <= 1:
        work['predicted'] = base_label
        return work

    if 'scope' in work.columns and work['scope'].notna().any():
        scope_labels = work['scope'].astype(str).replace({'nan': ''}).str.strip()
        work['predicted'] = [f"{base_label} | {scope or 'row'}" for scope in scope_labels]
        return work

    work['predicted'] = [f"{base_label} #{idx + 1}" for idx in range(len(work))]
    return work


STANDARD_METRIC_COLUMNS = ['R', 'RMSE', 'ubRMSE', 'Bias', 'NSE', 'MAE']
GCP_METRIC_COLUMNS = ['PICP', 'MPIW', 'NMPIW', 'QCP', 'IS']


def _infer_metric_columns(df: pd.DataFrame, requested: list[str] | None = None) -> tuple[list[str], str]:
    requested = [str(col) for col in (requested or []) if str(col).strip()]
    available = set(df.columns)
    requested_existing = [col for col in requested if col in available]
    if requested_existing:
        family = 'gcp' if any(col in GCP_METRIC_COLUMNS for col in requested_existing) else 'standard'
        return requested_existing, family

    standard = [col for col in STANDARD_METRIC_COLUMNS if col in available]
    gcp = [col for col in GCP_METRIC_COLUMNS if col in available]
    if len(gcp) >= 2 and len(standard) < 2:
        return gcp, 'gcp'
    if standard:
        return standard, 'standard'
    if gcp:
        return gcp, 'gcp'

    numeric_cols = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col]) and col != 'n']
    if numeric_cols:
        return numeric_cols[:6], 'generic'
    return [], 'unknown'


def _extract_metric_highlights(df: pd.DataFrame, dataset_name: str = "") -> dict[str, Any]:
    work = _ensure_metric_predicted_column(df, dataset_name=dataset_name)
    metrics, family = _infer_metric_columns(work)
    for col in metrics:
        work[col] = pd.to_numeric(work[col], errors='coerce')
    highlights: dict[str, Any] = {'metrics': metrics, 'rows': len(work), 'family': family}

    if family == 'standard':
        if 'R' in metrics:
            best_r = work.sort_values('R', ascending=False, na_position='last').head(1)
            if not best_r.empty:
                highlights['best_r'] = best_r[['predicted', 'R']].iloc[0].to_dict()
        if 'NSE' in metrics:
            best_nse = work.sort_values('NSE', ascending=False, na_position='last').head(1)
            if not best_nse.empty:
                highlights['best_nse'] = best_nse[['predicted', 'NSE']].iloc[0].to_dict()
        if 'RMSE' in metrics:
            best_rmse = work.sort_values('RMSE', ascending=True, na_position='last').head(1)
            if not best_rmse.empty:
                highlights['best_rmse'] = best_rmse[['predicted', 'RMSE']].iloc[0].to_dict()
        ranking_cols = [c for c in ['R', 'NSE', 'RMSE', 'ubRMSE', 'Bias', 'MAE'] if c in metrics]
        rank_df = work[['predicted', *ranking_cols]].copy()
        score = pd.Series(0.0, index=rank_df.index)
        for col in ranking_cols:
            ascending = col in {'RMSE', 'ubRMSE', 'Bias', 'MAE'}
            vals = rank_df[col].abs() if col == 'Bias' else rank_df[col]
            score += vals.rank(ascending=ascending, method='average', na_option='bottom')
        rank_df['rank_score'] = score
        highlights['ranking'] = rank_df.sort_values('rank_score').to_dict(orient='records')
        return highlights

    if family == 'gcp':
        if 'PICP' in metrics:
            nominal = pd.to_numeric(work.get('nominal_coverage', pd.Series([np.nan] * len(work))), errors='coerce')
            if nominal.notna().any():
                picp_gap = (pd.to_numeric(work['PICP'], errors='coerce') - nominal).abs()
                work['_picp_gap'] = picp_gap
                best_picp = work.sort_values('_picp_gap', ascending=True, na_position='last').head(1)
                if not best_picp.empty:
                    row = best_picp[['predicted', 'PICP']].iloc[0].to_dict()
                    row['nominal_coverage'] = float(pd.to_numeric(best_picp['nominal_coverage'], errors='coerce').iloc[0]) if 'nominal_coverage' in best_picp.columns else None
                    row['coverage_gap'] = float(best_picp['_picp_gap'].iloc[0]) if pd.notna(best_picp['_picp_gap'].iloc[0]) else None
                    highlights['best_picp'] = row
            else:
                best_picp = work.sort_values('PICP', ascending=False, na_position='last').head(1)
                if not best_picp.empty:
                    highlights['best_picp'] = best_picp[['predicted', 'PICP']].iloc[0].to_dict()
        if 'MPIW' in metrics:
            best_mpiw = work.sort_values('MPIW', ascending=True, na_position='last').head(1)
            if not best_mpiw.empty:
                highlights['best_mpiw'] = best_mpiw[['predicted', 'MPIW']].iloc[0].to_dict()
        if 'IS' in metrics:
            best_is = work.sort_values('IS', ascending=True, na_position='last').head(1)
            if not best_is.empty:
                highlights['best_is'] = best_is[['predicted', 'IS']].iloc[0].to_dict()
        ranking_cols = [c for c in ['PICP', 'MPIW', 'NMPIW', 'QCP', 'IS'] if c in metrics]
        rank_df = work[['predicted', *ranking_cols]].copy()
        score = pd.Series(0.0, index=rank_df.index)
        nominal = pd.to_numeric(work.get('nominal_coverage', pd.Series([np.nan] * len(work))), errors='coerce')
        for col in ranking_cols:
            vals = pd.to_numeric(rank_df[col], errors='coerce')
            if col == 'PICP' and nominal.notna().any():
                vals = (vals - nominal).abs()
                ascending = True
            elif col == 'PICP':
                ascending = False
            else:
                ascending = True
            score += vals.rank(ascending=ascending, method='average', na_option='bottom')
        rank_df['rank_score'] = score
        highlights['ranking'] = rank_df.sort_values('rank_score').to_dict(orient='records')
        return highlights

    rank_df = work[['predicted', *metrics]].copy() if metrics else work[['predicted']].copy()
    if not rank_df.empty:
        rank_df['rank_score'] = np.arange(1, len(rank_df) + 1, dtype=float)
    highlights['ranking'] = rank_df.to_dict(orient='records')
    return highlights


def _extract_feature_highlights(df: pd.DataFrame) -> list[dict[str, Any]]:
    feature_col = 'feature' if 'feature' in df.columns else None
    value_col = 'importance' if 'importance' in df.columns else None
    if not feature_col or not value_col:
        return []
    work = df[[feature_col, value_col]].copy()
    work[value_col] = pd.to_numeric(work[value_col], errors='coerce')
    work = work.dropna().sort_values(value_col, ascending=False).head(8)
    return work.to_dict(orient='records')


def _extract_btch_highlights(df: pd.DataFrame) -> dict[str, Any]:
    if not {'window', 'product', 'weight'}.issubset(df.columns):
        return {}
    work = df[['window', 'product', 'weight']].copy()
    work['weight'] = pd.to_numeric(work['weight'], errors='coerce')
    work = work.dropna()
    if work.empty:
        return {}
    mean_weights = work.groupby('product', dropna=False)['weight'].mean().sort_values(ascending=False).reset_index()
    peak_rows = work.sort_values('weight', ascending=False).head(10)
    return {
        'mean_weights': mean_weights.to_dict(orient='records'),
        'top_windows': peak_rows.to_dict(orient='records'),
    }


def _recent_artifact_paths(manager: DataManager, suffixes: set[str], limit: int = 8) -> list[str]:
    results: list[str] = []
    for item in manager.list_artifacts():
        path = str(item.get('path', ''))
        if Path(path).suffix.lower() in suffixes:
            results.append(path)
        if len(results) >= limit:
            break
    return results

def _geometry_to_sample_point(geom):
    if geom is None or geom.is_empty:
        return None
    geom_type = getattr(geom, "geom_type", "")
    if geom_type == "Point":
        return geom
    if geom_type == "MultiPoint":
        points = list(getattr(geom, "geoms", []))
        return points[0] if points else None
    return geom.representative_point()


def _sample_raster_to_geometries(points: gpd.GeoDataFrame, raster_path: Path, band: int = 1) -> pd.Series:
    with rasterio.open(raster_path) as src:
        pts = points.copy()
        pts["_sample_geom"] = pts.geometry.apply(_geometry_to_sample_point)
        if pts.crs and src.crs and pts.crs != src.crs:
            sample_layer = pts.set_geometry("_sample_geom").to_crs(src.crs)
            sample_geom = sample_layer.geometry
        else:
            sample_geom = pts["_sample_geom"]
        coords = []
        valid_index = []
        for idx, geom in sample_geom.items():
            if geom is None or geom.is_empty:
                continue
            coords.append((geom.x, geom.y))
            valid_index.append(idx)
        sampled = pd.Series(np.nan, index=points.index, dtype=float)
        if coords:
            raw_values = list(src.sample(coords, indexes=band))
            nodata = src.nodata
            values: list[float] = []
            for raw in raw_values:
                val = raw[0] if len(raw) else np.nan
                if nodata is not None and np.isfinite(val) and np.isclose(val, nodata):
                    val = np.nan
                values.append(float(val) if np.isfinite(val) else np.nan)
            sampled.loc[valid_index] = values
        return sampled


def _extract_date_from_name(text: str, pattern: str) -> str | None:
    if not pattern:
        return None
    match = re.search(pattern, text)
    if not match:
        return None
    token = match.group(1) if match.groups() else match.group(0)
    parsed = pd.to_datetime(token, errors="coerce")
    if pd.isna(parsed) and re.fullmatch(r"\d{8}", token or ""):
        parsed = pd.to_datetime(token, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _split_train_test_by_date(df: pd.DataFrame, date_col: str, split_date: str) -> tuple[pd.Series, pd.Series]:
    split_ts = pd.to_datetime(split_date, errors="coerce")
    if pd.isna(split_ts):
        raise ValueError(f"split_date 无法解析为日期: {split_date}")
    dates = _ensure_datetime(df, date_col)
    train_mask = dates <= split_ts
    test_mask = dates > split_ts
    return train_mask, test_mask


def _weighted_row_sum(values: pd.DataFrame, weights: np.ndarray) -> pd.Series:
    arr = values.to_numpy(dtype=float)
    valid = ~np.isnan(arr)
    weight_arr = np.broadcast_to(weights.reshape(1, -1), arr.shape)
    numerator = np.nansum(arr * weight_arr, axis=1)
    denominator = np.sum(np.where(valid, weight_arr, 0.0), axis=1)
    fused = np.divide(numerator, denominator, out=np.full(arr.shape[0], np.nan), where=denominator > 0)
    return pd.Series(fused, index=values.index)


def _fallback_product_variances(x: np.ndarray) -> np.ndarray:
    centered = x - np.nanmean(x, axis=1, keepdims=True)
    variances = np.nanvar(centered, axis=0)
    variances = np.where(np.isfinite(variances) & (variances > 1e-8), variances, 1e-6)
    return variances


def _estimate_btch_weights(x: np.ndarray) -> dict[str, Any]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x).any(axis=1)]
    n_samples, n_products = x.shape
    if n_products < 3:
        raise ValueError("BTCH 至少需要 3 个产品列。")
    if n_samples < max(10, n_products + 2):
        raise ValueError(f"可用于 BTCH 的完整样本不足，当前仅 {n_samples} 条。")

    ref = n_products - 1
    diffs = x[:, :ref] - x[:, [ref]]
    s = np.cov(diffs, rowvar=False, ddof=0)
    if np.ndim(s) == 0:
        s = np.array([[float(s)]], dtype=float)
    a = np.hstack([np.eye(n_products - 1), -np.ones((n_products - 1, 1))])
    diag_guess = _fallback_product_variances(x)
    l0 = np.zeros((n_products, n_products), dtype=float)
    np.fill_diagonal(l0, np.sqrt(diag_guess))
    tri = np.tril_indices(n_products)
    p0 = l0[tri]

    def objective(params: np.ndarray) -> float:
        lmat = np.zeros((n_products, n_products), dtype=float)
        lmat[tri] = params
        r = lmat @ lmat.T
        model = a @ r @ a.T
        off_diag = r - np.diag(np.diag(r))
        return float(np.sum((model - s) ** 2) + 1e-3 * np.sum(off_diag ** 2))

    try:
        result = minimize(objective, p0, method="L-BFGS-B", options={"maxiter": 800})
        params = result.x if result.success else p0
        lmat = np.zeros((n_products, n_products), dtype=float)
        lmat[tri] = params
        cov = lmat @ lmat.T
        variances = np.diag(cov)
        variances = np.where(np.isfinite(variances) & (variances > 1e-8), variances, _fallback_product_variances(x))
        method = "btch_psd_fit" if result.success else "variance_fallback"
    except Exception:
        variances = _fallback_product_variances(x)
        cov = np.diag(variances)
        method = "variance_fallback"

    inv_var = 1.0 / variances
    weights = inv_var / inv_var.sum()
    return {
        "weights": weights,
        "variances": variances,
        "covariance": cov,
        "samples": int(n_samples),
        "estimation_method": method,
    }


def _window_labels(df: pd.DataFrame, date_col: str, mode: str) -> pd.Series:
    dt = _ensure_datetime(df, date_col)
    mode_key = mode.strip().lower()
    if mode_key == "global":
        return pd.Series(["global"] * len(df), index=df.index)
    if mode_key in {"month", "month_of_year"}:
        return dt.dt.month.map(lambda x: f"month_{int(x):02d}")
    if mode_key in {"season", "seasonal"}:
        return dt.dt.month.map(lambda x: f"season_{SEASON_MAP[int(x)]}")
    if mode_key in {"year_month", "monthly_update"}:
        return dt.dt.to_period("M").astype(str)
    raise ValueError("window_mode 目前支持 global、month、season、year_month。")


def _coerce_numeric_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _summarize_train_test_metrics(df: pd.DataFrame, truth_col: str, pred_col: str, train_mask: pd.Series | None, test_mask: pd.Series | None) -> dict[str, Any]:
    summary: dict[str, Any] = {"overall": _calc_metrics(df[truth_col], df[pred_col])}
    if train_mask is not None and bool(train_mask.any()):
        summary["train"] = _calc_metrics(df.loc[train_mask, truth_col], df.loc[train_mask, pred_col])
    if test_mask is not None and bool(test_mask.any()):
        summary["test"] = _calc_metrics(df.loc[test_mask, truth_col], df.loc[test_mask, pred_col])
    return summary



def _rewrite_unquoted_identifiers(expr: str, replacements: dict[str, str]) -> str:
    if not replacements:
        return expr
    parts = re.split(r'''('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")''', expr)
    token_pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")

    def _replace_segment(segment: str) -> str:
        return token_pattern.sub(lambda m: replacements.get(m.group(1), m.group(1)), segment)

    for idx in range(0, len(parts), 2):
        parts[idx] = _replace_segment(parts[idx])
    return "".join(parts)


def _prediction_like_columns(df: pd.DataFrame) -> list[str]:
    candidates: list[str] = []
    for col in df.columns:
        name = str(col)
        lowered = name.lower()
        if (
            lowered.endswith(("_xgb_spatial_cv", "_spatial_cv", "_cv", "_oof", "_prediction"))
            or "spatial_cv" in lowered
            or lowered.startswith("pred_")
        ):
            candidates.append(name)
    return candidates


def _scope_like_columns(df: pd.DataFrame) -> list[str]:
    candidates: list[str] = []
    for col in df.columns:
        lowered = str(col).lower()
        if lowered.endswith(("_spatial_cv_scope", "_cv_scope", "_target_scope", "_split_scope", "_cv_role")):
            candidates.append(str(col))
    return candidates


def _try_special_mask_from_query(df: pd.DataFrame, expr: str) -> pd.Series | None:
    expr_low = (expr or "").strip().lower()
    if not expr_low:
        return None
    if not any(token in expr_low for token in ("holdout", "test", "spatial_cv", "oof")):
        return None

    field_match = re.search(r"""\b([A-Za-z_][A-Za-z0-9_]*)\b\s*==\s*['"]?(holdout|test)['"]?""", expr, flags=re.IGNORECASE)
    field_candidate = field_match.group(1) if field_match else ""
    resolved_field = None
    if field_candidate:
        try:
            resolved_field = _resolve_existing_columns(df, [field_candidate])[0]
        except Exception:
            resolved_field = None

    scope_candidates = _scope_like_columns(df)
    pred_candidates = _prediction_like_columns(df)

    if resolved_field and resolved_field in df.columns:
        series_text = df[resolved_field].astype(str).str.strip().str.lower()
        if resolved_field in scope_candidates or bool(series_text.isin(["holdout", "test", "train", "calibration", "all"]).any()):
            return series_text.isin(["holdout", "test"]).fillna(False)
        numeric_series = pd.to_numeric(df[resolved_field], errors="coerce")
        if resolved_field in pred_candidates or bool(numeric_series.notna().any()):
            return numeric_series.notna().fillna(False)

    if len(scope_candidates) == 1:
        series_text = df[scope_candidates[0]].astype(str).str.strip().str.lower()
        return series_text.isin(["holdout", "test"]).fillna(False)

    if len(pred_candidates) == 1:
        return pd.to_numeric(df[pred_candidates[0]], errors="coerce").notna().fillna(False)

    return None


def _build_mask_from_query(df: pd.DataFrame, expr: str, label: str) -> pd.Series:
    if not expr.strip():
        return pd.Series(True, index=df.index)

    reserved = {"and", "or", "not", "in", "true", "false", "none", "holdout", "test", "train"}
    replacements: dict[str, str] = {}
    for token in sorted(set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expr))):
        if token in df.columns or token.lower() in reserved:
            continue
        try:
            resolved = _resolve_existing_columns(df, [token])[0]
        except Exception:
            continue
        if resolved != token:
            replacements[token] = resolved
    rewritten_expr = _rewrite_unquoted_identifiers(expr, replacements)

    last_error: Exception | None = None
    for candidate_expr in [rewritten_expr, expr]:
        if not candidate_expr.strip():
            continue
        try:
            mask = df.eval(candidate_expr, engine="python")
            if not isinstance(mask, pd.Series):
                raise ValueError("表达式没有返回布尔序列。")
            mask = pd.Series(mask, index=df.index)
            break
        except Exception as exc_eval:
            last_error = exc_eval
            try:
                subset = df.query(candidate_expr, engine="python")
                mask = df.index.isin(subset.index)
                mask = pd.Series(mask, index=df.index)
                break
            except Exception as exc_query:
                last_error = exc_query
        mask = None  # type: ignore[assignment]
    else:
        mask = None  # type: ignore[assignment]

    if mask is None:
        special_mask = _try_special_mask_from_query(df, rewritten_expr)
        if special_mask is None and rewritten_expr != expr:
            special_mask = _try_special_mask_from_query(df, expr)
        if special_mask is not None:
            mask = pd.Series(special_mask, index=df.index)
        else:
            raise ValueError(f"{label} 无法解析: {expr}。错误: {last_error}") from last_error

    mask = pd.Series(mask, index=df.index)
    if mask.dtype != bool:
        truthy = {True, False}
        unique_values = set(mask.dropna().unique().tolist())
        if unique_values.issubset(truthy):
            mask = mask.astype(bool)
        else:
            raise ValueError(f"{label} 需要返回布尔结果，当前表达式为: {expr}")
    return mask.fillna(False)



def _resolve_spatial_coordinates(
    dataset_name: str,
    df: pd.DataFrame,
    manager: DataManager,
    lon_col: str = "",
    lat_col: str = "",
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    record = manager.get(dataset_name)
    if record.data_type == "vector":
        gdf = manager.get_vector(dataset_name).copy()
        if gdf.empty:
            return None, {"coord_source": "geometry", "spatial_ready": False, "reason": "vector_empty"}
        geometry = gdf.copy()
        geom_types = {str(v) for v in geometry.geometry.geom_type.dropna().unique()}
        if geom_types and not geom_types.issubset({"Point"}):
            geometry["geometry"] = geometry.geometry.centroid
        if geometry.crs is not None:
            try:
                projected, projected_crs = _estimate_projected_gdf(geometry)
                coords = pd.DataFrame({
                    "__coord_x__": projected.geometry.x,
                    "__coord_y__": projected.geometry.y,
                }, index=geometry.index)
                return coords, {"coord_source": "geometry", "spatial_ready": True, "projected_crs": projected_crs}
            except Exception:
                pass
        coords = pd.DataFrame({
            "__coord_x__": geometry.geometry.x,
            "__coord_y__": geometry.geometry.y,
        }, index=geometry.index)
        return coords, {"coord_source": "geometry_raw", "spatial_ready": True, "projected_crs": str(geometry.crs) if geometry.crs else None}

    lon_name = lon_col.strip()
    lat_name = lat_col.strip()
    if not lon_name or not lat_name:
        guessed = _infer_coordinate_candidates(df)
        if not lon_name and guessed.get("x_candidates"):
            lon_name = str(guessed["x_candidates"][0]["field"])
        if not lat_name and guessed.get("y_candidates"):
            lat_name = str(guessed["y_candidates"][0]["field"])

    if not lon_name or not lat_name or lon_name not in df.columns or lat_name not in df.columns:
        return None, {"coord_source": "none", "spatial_ready": False, "reason": "missing_coordinate_columns"}

    lon = pd.to_numeric(df[lon_name], errors="coerce")
    lat = pd.to_numeric(df[lat_name], errors="coerce")
    coords = pd.DataFrame({"__coord_x__": lon, "__coord_y__": lat}, index=df.index)
    plausible_lonlat = bool(lon.dropna().between(-180, 180).mean() >= 0.9 and lat.dropna().between(-90, 90).mean() >= 0.9)
    if plausible_lonlat:
        geom = gpd.GeoDataFrame(df[[lon_name, lat_name]].copy(), geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326")
        valid = geom.geometry.notna()
        if bool(valid.any()):
            try:
                projected, projected_crs = _estimate_projected_gdf(geom.loc[valid].copy())
                coords.loc[valid, "__coord_x__"] = projected.geometry.x.to_numpy()
                coords.loc[valid, "__coord_y__"] = projected.geometry.y.to_numpy()
                return coords, {
                    "coord_source": f"columns:{lon_name},{lat_name}",
                    "spatial_ready": True,
                    "projected_crs": projected_crs,
                }
            except Exception:
                pass

    return coords, {
        "coord_source": f"columns:{lon_name},{lat_name}",
        "spatial_ready": bool(coords.notna().all(axis=1).any()),
        "projected_crs": None,
    }



def _conformal_quantile_level(n_scores: int, alpha: float) -> float:
    if n_scores <= 0:
        raise ValueError("共形预测至少需要 1 个校准样本。")
    level = math.ceil((n_scores + 1) * (1 - alpha)) / n_scores
    return float(min(max(level, 0.0), 1.0))



def _weighted_quantile(values: np.ndarray, quantile: float, sample_weight: np.ndarray | None = None) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    q = float(min(max(quantile, 0.0), 1.0))
    if sample_weight is None:
        return float(np.quantile(arr, q, method="higher"))

    weights = np.asarray(sample_weight, dtype=float)
    if weights.shape[0] != arr.shape[0]:
        raise ValueError("权重长度与数值长度不一致。")
    valid = np.isfinite(weights) & (weights > 0)
    arr = arr[valid]
    weights = weights[valid]
    if arr.size == 0:
        return float("nan")

    sorter = np.argsort(arr)
    arr = arr[sorter]
    weights = weights[sorter]
    cumulative = np.cumsum(weights)
    total = float(cumulative[-1])
    if total <= 0:
        return float(np.quantile(arr, q, method="higher"))
    threshold = q * total
    idx = int(np.searchsorted(cumulative, threshold, side="left"))
    idx = min(max(idx, 0), len(arr) - 1)
    return float(arr[idx])



def _kernel_weights(distances: np.ndarray, bandwidth: float, kernel: str) -> np.ndarray:
    dist = np.asarray(distances, dtype=float)
    bw = float(bandwidth) if bandwidth and float(bandwidth) > 0 else 1.0
    u = dist / bw
    key = (kernel or "gaussian").strip().lower()
    if key == "gaussian":
        w = np.exp(-0.5 * np.square(u))
    elif key in {"bisquare", "biweight"}:
        w = np.where(u < 1, np.square(1 - np.square(u)), 0.0)
    elif key == "tricube":
        w = np.where(u < 1, np.power(1 - np.power(u, 3), 3), 0.0)
    elif key == "exponential":
        w = np.exp(-u)
    else:
        raise ValueError("kernel 目前支持 gaussian、bisquare、tricube、exponential。")
    return np.where(np.isfinite(w), w, 0.0)



def _auto_bandwidth(coords: np.ndarray) -> float:
    if len(coords) < 2:
        return 1.0
    k = max(2, min(int(np.sqrt(len(coords))), len(coords) - 1))
    nn = NearestNeighbors(n_neighbors=k + 1)
    nn.fit(coords)
    distances, _ = nn.kneighbors(coords)
    candidate = float(np.median(distances[:, -1]))
    if candidate > 0:
        return candidate
    positive = distances[distances > 0]
    if positive.size:
        return float(np.median(positive))
    return 1.0



def _calc_interval_score(obs: pd.Series, lower: pd.Series, upper: pd.Series, alpha: float) -> float | None:
    frame = pd.DataFrame({
        "obs": pd.to_numeric(obs, errors="coerce"),
        "lower": pd.to_numeric(lower, errors="coerce"),
        "upper": pd.to_numeric(upper, errors="coerce"),
    }).dropna()
    if frame.empty:
        return None
    width = frame["upper"] - frame["lower"]
    penalty_lower = np.where(frame["obs"] < frame["lower"], (2.0 / alpha) * (frame["lower"] - frame["obs"]), 0.0)
    penalty_upper = np.where(frame["obs"] > frame["upper"], (2.0 / alpha) * (frame["obs"] - frame["upper"]), 0.0)
    score = width + penalty_lower + penalty_upper
    return float(np.mean(score))



def _calc_qcp(
    obs: pd.Series,
    lower: pd.Series,
    upper: pd.Series,
    alpha: float,
    reference: pd.Series | None = None,
    bin_count: int = 5,
) -> float | None:
    frame = pd.DataFrame({
        "obs": pd.to_numeric(obs, errors="coerce"),
        "lower": pd.to_numeric(lower, errors="coerce"),
        "upper": pd.to_numeric(upper, errors="coerce"),
        "ref": pd.to_numeric(reference if reference is not None else obs, errors="coerce"),
    }).dropna()
    if len(frame) < max(10, bin_count * 2):
        return None
    try:
        bins = pd.qcut(frame["ref"], q=min(bin_count, frame["ref"].nunique()), duplicates="drop")
    except Exception:
        return None
    nominal = 1 - alpha
    deviations: list[float] = []
    covered = (frame["obs"] >= frame["lower"]) & (frame["obs"] <= frame["upper"])
    for _, sub in frame.assign(_covered=covered).groupby(bins, observed=False):
        if len(sub) < 3:
            continue
        deviations.append(abs(float(sub["_covered"].mean()) - nominal))
    if not deviations:
        return None
    return float(np.mean(deviations))



def _calc_interval_metrics(
    obs: pd.Series,
    lower: pd.Series,
    upper: pd.Series,
    alpha: float,
    pred_reference: pd.Series | None = None,
    bin_count: int = 5,
) -> dict[str, float | int | None]:
    frame = pd.DataFrame({
        "obs": pd.to_numeric(obs, errors="coerce"),
        "lower": pd.to_numeric(lower, errors="coerce"),
        "upper": pd.to_numeric(upper, errors="coerce"),
        "pred": pd.to_numeric(pred_reference, errors="coerce") if pred_reference is not None else pd.to_numeric(obs, errors="coerce"),
    }).dropna()
    if frame.empty:
        return {"n": 0, "PICP": None, "MPIW": None, "NMPIW": None, "QCP": None, "IS": None}
    width = frame["upper"] - frame["lower"]
    covered = (frame["obs"] >= frame["lower"]) & (frame["obs"] <= frame["upper"])
    obs_range = float(frame["obs"].max() - frame["obs"].min())
    nmpiw = None if math.isclose(obs_range, 0.0) else float(width.mean() / obs_range)
    return {
        "n": int(len(frame)),
        "PICP": float(covered.mean()),
        "MPIW": float(width.mean()),
        "NMPIW": nmpiw,
        "QCP": _calc_qcp(frame["obs"], frame["lower"], frame["upper"], alpha=alpha, reference=frame["pred"], bin_count=bin_count),
        "IS": _calc_interval_score(frame["obs"], frame["lower"], frame["upper"], alpha=alpha),
    }


class _FusionLSTM(nn.Module):
    def __init__(self, dynamic_dim: int, static_dim: int, hidden_size: int, num_layers: int = 1, dropout: float = 0.1):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=dynamic_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        proj_in = hidden_size + static_dim
        mid = max(hidden_size // 2, 8)
        self.head = nn.Sequential(
            nn.Linear(proj_in, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, mid),
            nn.ReLU(),
            nn.Linear(mid, 1),
        )

    def forward(self, x_dynamic: torch.Tensor, x_static: torch.Tensor | None = None) -> torch.Tensor:
        output, _ = self.lstm(x_dynamic)
        last_hidden = output[:, -1, :]
        if x_static is not None and x_static.numel() > 0:
            last_hidden = torch.cat([last_hidden, x_static], dim=1)
        return self.head(last_hidden).squeeze(-1)


def _build_lstm_sequences(
    df: pd.DataFrame,
    date_col: str,
    target_col: str,
    dynamic_cols: list[str],
    static_cols: list[str],
    group_col: str,
    seq_len: int,
) -> dict[str, Any]:
    work = df.copy()
    work[date_col] = _ensure_datetime(work, date_col)
    work = _coerce_numeric_frame(work, [target_col, *dynamic_cols, *static_cols])
    group_field = group_col or "__single_group__"
    if not group_col:
        work[group_field] = "all"
    work = work.sort_values([group_field, date_col]).reset_index().rename(columns={"index": "_orig_index"})

    rows: list[dict[str, Any]] = []
    for _, group_df in work.groupby(group_field, dropna=False):
        group_df = group_df.reset_index(drop=True)
        dyn = group_df[dynamic_cols].to_numpy(dtype=float)
        sta = group_df[static_cols].to_numpy(dtype=float) if static_cols else np.zeros((len(group_df), 0), dtype=float)
        target = group_df[target_col].to_numpy(dtype=float)
        dates = group_df[date_col].to_numpy()
        orig_index = group_df["_orig_index"].to_numpy()
        for end in range(seq_len - 1, len(group_df)):
            dyn_window = dyn[end - seq_len + 1 : end + 1]
            sta_row = sta[end] if static_cols else np.zeros((0,), dtype=float)
            y_val = target[end]
            if np.isnan(dyn_window).any() or np.isnan(sta_row).any() or np.isnan(y_val):
                continue
            rows.append({
                "dynamic": dyn_window,
                "static": sta_row,
                "target": y_val,
                "date": pd.Timestamp(dates[end]),
                "orig_index": int(orig_index[end]),
            })

    if not rows:
        raise ValueError("无法构建 LSTM 序列样本，请检查 seq_len、日期字段和缺失值情况。")

    x_dyn = np.stack([row["dynamic"] for row in rows]).astype(np.float32)
    x_sta = np.stack([row["static"] for row in rows]).astype(np.float32) if static_cols else np.zeros((len(rows), 0), dtype=np.float32)
    y = np.array([row["target"] for row in rows], dtype=np.float32)
    dates = pd.Series([row["date"] for row in rows])
    orig_index = np.array([row["orig_index"] for row in rows], dtype=int)
    return {"x_dynamic": x_dyn, "x_static": x_sta, "y": y, "dates": dates, "orig_index": orig_index}


def build_tools(manager: DataManager):
    @tool
    def workspace_status() -> str:
        """查看当前工作区概览，包括数据集数量、制图结果和处理活动。"""
        return _json(
            {
                "summary": manager.workspace_summary(),
                "datasets": manager.list_datasets(),
                "artifacts": manager.list_artifacts()[:8],
                "recent_activity": manager.operation_log[:8],
            }
        )

    @tool
    def list_datasets() -> str:
        """列出当前会话中所有已加载的数据集及其基础信息。"""
        return manager.dataset_brief()

    @tool
    def load_dataset(file_path: str, dataset_name: str = "") -> str:
        """从本地路径加载数据集。支持矢量、栅格、表格、zip shapefile，以及 docx/txt/md 文档。"""
        loaded_name = manager.load_path(file_path=file_path, name=dataset_name or None)
        return f"已加载数据集: {loaded_name}\n{manager.dataset_brief()}"

    @tool
    def describe_dataset(dataset_name: str) -> str:
        """查看指定数据集的详细摘要，包括类型、坐标系、字段、尺寸或文档长度等。"""
        inputs = {"dataset_name": dataset_name}
        errors = validate_dataset_exists(manager, dataset_name)
        if errors:
            return _tool_error_from_validation("describe_dataset", inputs, errors)
        try:
            record = manager.get(dataset_name)
            preview = None
            fields: list[str] = []
            if record.data_type in {"table", "vector"}:
                preview = manager.preview_table_rows(dataset_name, rows=5)
                fields = [str(col) for col in (record.meta.get("columns") or [])] if isinstance(record.meta, dict) else []
            elif record.data_type == "document":
                preview = manager.preview_document(dataset_name, max_chars=500)
            outputs = {
                "name": record.name,
                "type": record.data_type,
                "path": str(record.path),
                "meta": record.meta,
                "preview": preview,
            }
            return tool_result_ok(
                "describe_dataset",
                inputs=inputs,
                outputs=outputs,
                summary=f"已读取数据集 {record.name} 的结构摘要。",
                diagnostics={
                    "field_count": len(fields),
                    "fields": fields,
                    "dataset_type": record.data_type,
                    "crs": record.meta.get("crs") if isinstance(record.meta, dict) else None,
                },
                next_actions=["根据字段、坐标系和缺失值情况选择制图、处理或建模步骤。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("describe_dataset", inputs, exc)

    @tool
    def preview_table(dataset_name: str, rows: int = 8) -> str:
        """预览表格或矢量属性数据前几行，便于识别坐标字段、分类字段和数值字段。"""
        return _json(manager.preview_table_rows(dataset_name, rows=rows))

    @tool
    def preview_document(dataset_name: str, max_chars: int = 1500) -> str:
        """预览文档前若干字符，适合快速查看开题报告、论文草稿、说明文档的正文内容。"""
        text = manager.preview_document(dataset_name, max_chars=max_chars)
        manager.log_operation("预览文档", f"{dataset_name} | {max_chars} chars", "document")
        return text

    @tool
    def document_outline(dataset_name: str, max_items: int = 30) -> str:
        """提取文档中疑似标题、章节或提纲行，适合快速梳理论文或报告结构。"""
        text = manager.get_document_text(dataset_name)
        outline = _heading_like_lines(text, max_items=max_items)
        manager.log_operation("提取文档提纲", dataset_name, "document")
        return _json({"dataset": dataset_name, "outline": outline, "count": len(outline)})

    @tool
    def search_document_text(dataset_name: str, keyword: str, context_chars: int = 120, max_hits: int = 8) -> str:
        """在文档中检索关键词并返回上下文片段，适合定位研究目标、技术路线、实验设计等内容。"""
        text = manager.get_document_text(dataset_name)
        hits = _make_text_snippets(text, keyword=keyword, context_chars=context_chars, max_hits=max_hits)
        manager.log_operation("文档关键词检索", f"{dataset_name} | {keyword}", "document")
        return _json({"dataset": dataset_name, "keyword": keyword, "hits": hits, "count": len(hits)})

    @tool
    def generic_xgboost_workflow(
        dataset_name: str = "",
        target_col: str = "",
        feature_cols: str = "",
        output_name: str = "",
        mode: str = "auto",
        task_type: str = "auto",
        raster_names: str = "",
        target_raster_name: str = "",
        sample_dataset_name: str = "",
        x_col: str = "",
        y_col: str = "",
        date_col: str = "",
        group_col: str = "",
        split_method: str = "auto",
        test_size: float = 0.2,
        random_state: int = 42,
        max_training_samples: int = 200000,
        max_prediction_pixels: int = 5000000,
        raster_resampling: str = "bilinear",
        categorical_strategy: str = "onehot",
    ) -> str:
        """Run generic XGBoost regression/classification for table, vector, sample+raster, or raster stack data."""
        from .ml.generic_xgboost import run_generic_xgboost_workflow

        result = run_generic_xgboost_workflow(
            manager,
            dataset_name=dataset_name,
            target_col=target_col,
            feature_cols=feature_cols,
            output_name=output_name,
            mode=mode,
            task_type=task_type,
            raster_names=raster_names,
            target_raster_name=target_raster_name,
            sample_dataset_name=sample_dataset_name,
            x_col=x_col,
            y_col=y_col,
            date_col=date_col,
            group_col=group_col,
            split_method=split_method,
            test_size=test_size,
            random_state=random_state,
            max_training_samples=max_training_samples,
            max_prediction_pixels=max_prediction_pixels,
            raster_resampling=raster_resampling,
            categorical_strategy=categorical_strategy,
        )
        return _json(result.to_dict())

    @tool
    def detect_coordinate_fields(dataset_name: str) -> str:
        """自动识别表格或矢量属性中可能的经纬度或平面坐标字段，适合在 table_to_points 前或空间回归前先判断坐标信息。"""
        df = _prepare_dataframe(dataset_name, manager)
        result = _infer_coordinate_candidates(df)
        result["dataset"] = dataset_name
        if result["x_candidates"] and result["y_candidates"]:
            result["suggestion"] = (
                f"建议优先尝试 x={result['x_candidates'][0]['field']}，"
                f"y={result['y_candidates'][0]['field']}。"
            )
        else:
            result["suggestion"] = "未检测到明显的坐标字段，请先预览表格或手动指定。"
        return _json(result)

    @tool
    def rename_dataset(dataset_name: str, new_name: str) -> str:
        """重命名当前工作区中的数据集，方便后续引用。"""
        final_name = manager.rename_dataset(dataset_name, new_name)
        return f"已重命名: {dataset_name} -> {final_name}"

    @tool
    def database_status() -> str:
        """查看内置 SQLite 工作区数据库状态，包括数据库路径、已登记数据集数量和 SQL 表数量。"""
        return _json(manager.database_status())

    @tool
    def list_database_objects() -> str:
        """列出内置数据库中的数据目录和 SQL 表，便于决定后续查询与建模。"""
        return _json(manager.list_database_objects())

    @tool
    def explain_database_training_pipeline(models: str = "btch,rf,xgboost,lstm") -> str:
        """用新手能看懂的方式说明数据库驱动训练流水线的完整步骤、输入、输出和推荐命令。"""
        model_list = [item.strip().lower() for item in re.split(r"[,;，\s]+", models or "") if item.strip()]
        data_preview = manager.list_database_objects()
        payload = {
            "pipeline_name": "数据库驱动训练流水线",
            "recommended_models": model_list or ["btch", "rf", "xgboost", "lstm"],
            "steps": [
                {"step": 1, "name": "准备数据", "what": "先把表格、矢量属性和文档同步到 SQLite，明确有哪些 SQL 表可直接使用。", "tools": ["database_status", "list_database_objects", "sync_all_to_database"]},
                {"step": 2, "name": "生成训练表", "what": "通过 SQL 或已有数据集生成训练表，推荐保证每一行都对应一个站点-日期样本。", "tools": ["query_workspace_database"]},
                {"step": 3, "name": "数据体检", "what": "检查字段、缺失值、时间列和目标列，必要时补 lag / rolling 特征。", "tools": ["profile_missing_values", "build_time_features"]},
                {"step": 4, "name": "模型训练", "what": "按需求运行 BTCH、RF、XGBoost、LSTM，并自动产出预测表、指标表和模型文件。", "tools": ["btch_fusion_model", "train_rf_fusion_model", "train_xgboost_fusion_model", "train_lstm_fusion_model"]},
                {"step": 5, "name": "不确定性分析", "what": "对模型输出自动执行 GCP（地理共形预测），生成预测区间、覆盖率和区间宽度指标。", "tools": ["geographical_conformal_prediction"]},
                {"step": 6, "name": "结果汇总", "what": "把各模型指标与 GCP 指标汇总成统一比较表，生成论文图表和阶段材料。", "tools": ["generate_thesis_charts", "generate_model_comparison_summary", "generate_stage_report"]},
                {"step": 7, "name": "查看流程记录", "what": "每次流水线运行都会写入数据库，可回看每一步的输入、输出和状态。", "tools": ["list_pipeline_runs", "show_pipeline_run"]},
                            ],
            "example": {
                "novice_prompt": "用数据库里的训练表做一条完整训练流水线，显示每一步处理过程，并比较 BTCH、RF、XGBoost、LSTM。",
                "typical_sql": "SELECT * FROM tbl_training_table",
            },
            "database_preview": data_preview,
        }
        return _json(payload)

    @tool
    def list_pipeline_runs(limit: int = 10) -> str:
        """列出最近的数据库驱动训练流水线运行记录，便于回看实验过程。"""
        return _json(manager.list_pipeline_runs(limit=limit))

    @tool
    def show_pipeline_run(run_id: str = "") -> str:
        """查看某次训练流水线的完整步骤、输入、输出和状态。若不提供 run_id，则默认展示最近一次。"""
        if not run_id:
            runs = manager.list_pipeline_runs(limit=1)
            if not runs:
                return "当前还没有流水线运行记录。"
            run_id = runs[0]["run_id"]
        detail = manager.pipeline_run_detail(run_id)
        if not detail:
            raise ValueError(f"未找到流水线运行记录: {run_id}")
        return _json(detail)

    @tool
    def sync_dataset_to_database(dataset_name: str) -> str:
        """将指定数据集同步到内置数据库。表格和矢量属性会写入 SQLite，文档会进入 document_store，栅格写入目录。"""
        result = manager.sync_dataset_to_database(dataset_name)
        manager.log_operation("同步到数据库", f"{dataset_name} -> {result.get('sql_table')}", "database")
        return _json(result)

    @tool
    def sync_all_to_database() -> str:
        """将当前工作区所有已加载数据集批量同步到内置数据库。适合第一次整理工作区时使用。"""
        results = manager.sync_all_supported_to_database()
        manager.log_operation("批量同步到数据库", f"数量: {len(results)}", "database")
        return _json({"count": len(results), "items": results})

    @tool
    def query_workspace_database(sql: str, output_name: str = "") -> str:
        """执行 SQLite 查询。若提供 output_name，则把查询结果保存为新的表格数据集，供后续建模、制图和评价直接调用。"""
        df = manager.query_database(sql)
        if output_name:
            saved_name = manager.put_table(output_name, df)
            manager.log_operation("数据库查询", f"输出数据集: {saved_name}", "database")
            return f"查询完成，结果行数: {len(df)}，结果数据集: {saved_name}，保存路径: {manager.get(saved_name).path}"
        manager.log_operation("数据库查询", f"返回 {len(df)} 行", "database")
        return _json(df.head(200).replace({pd.NA: None}).to_dict(orient="records"))

    @tool
    def profile_missing_values(dataset_name: str, output_name: str = "") -> str:
        """统计表格或矢量属性中的缺失值比例、唯一值数量和字段类型，适合建模前检查数据质量。"""
        df = _prepare_dataframe(dataset_name, manager)
        rows = []
        for col in df.columns:
            series = df[col]
            rows.append(
                {
                    "field": col,
                    "dtype": str(series.dtype),
                    "missing_count": int(series.isna().sum()),
                    "missing_ratio": float(series.isna().mean()) if len(series) else 0.0,
                    "unique_count": int(series.nunique(dropna=True)),
                }
            )
        result_df = pd.DataFrame(rows).sort_values(["missing_ratio", "field"], ascending=[False, True]).reset_index(drop=True)
        manager.log_operation("缺失值统计", dataset_name, "analysis")
        if output_name:
            saved_name = manager.put_table(output_name, result_df)
            return f"缺失值统计完成，结果表: {saved_name}，保存路径: {manager.get(saved_name).path}"
        return _json(result_df.to_dict(orient="records"))

    @tool
    def vector_filter(dataset_name: str, expression: str, output_name: str) -> str:
        """按属性表达式筛选矢量数据，例如 expression='POP > 1000'。"""
        gdf = manager.get_vector(dataset_name)
        filtered = gdf.query(expression).copy()
        saved_name = manager.put_vector(output_name, filtered)
        manager.log_operation("矢量筛选", f"{dataset_name} -> {saved_name} | 条件: {expression}", "analysis")
        return f"筛选完成，结果数据集名称: {saved_name}，要素数量: {len(filtered)}，保存路径: {manager.get(saved_name).path}"

    @tool
    def vector_buffer(dataset_name: str, distance: float, output_name: str) -> str:
        """对矢量数据进行缓冲区分析。distance 单位为图层投影坐标系单位，若原始数据为经纬度则会自动估计 UTM 投影。"""
        inputs = {"dataset_name": dataset_name, "distance": distance, "output_name": output_name}
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        try:
            distance_value = float(distance)
            if distance_value <= 0:
                raise ValueError("distance must be positive")
        except Exception:
            return tool_result_error(
                "vector_buffer",
                inputs=inputs,
                error_code="BUFFER_DISTANCE_INVALID",
                error_title="Invalid buffer distance",
                user_message="Buffer distance must be a positive number.",
                diagnostics={"distance": distance},
                next_actions=["Provide a positive buffer distance before running buffer analysis."],
            ).to_json()
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("vector_buffer", inputs, errors)
        try:
            gdf = manager.get_vector(dataset_name)
            projected, used_crs = _estimate_projected_gdf(gdf)
            buffered = projected.copy()
            buffered["geometry"] = projected.buffer(distance_value)
            buffered = buffered.to_crs(gdf.crs)
            saved_name = manager.put_vector(output_name, buffered)
            record = manager.get(saved_name)
            manager.log_operation("缓冲区分析", f"{dataset_name} -> {saved_name} | 距离: {distance_value}", "analysis")
            warnings_list = ["Buffer result is empty; check source geometry and distance."] if buffered.empty else []
            return tool_result_ok(
                "vector_buffer",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(buffered)),
                    "path": str(record.path),
                    "distance": distance_value,
                    "processing_crs": used_crs,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"Buffer result from {dataset_name}.",
                        quality_status="empty" if buffered.empty else "ok",
                        preview_available=True,
                    )
                ],
                summary=f"Created buffer dataset {saved_name} with {len(buffered)} features.",
                diagnostics={
                    "source_dataset": dataset_name,
                    "source_count": int(len(gdf)),
                    "result_count": int(len(buffered)),
                    "source_crs": str(gdf.crs),
                    "processing_crs": used_crs,
                },
                warnings=warnings_list,
                next_actions=["Inspect the buffer result, then continue with clipping, overlay, mapping, or export."],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_buffer", inputs, exc)

    @tool
    def vector_clip_by_vector(dataset_name: str, clip_name: str, output_name: str) -> str:
        """使用一个矢量图层裁剪另一个矢量图层，常用于按研究区裁剪道路、点位或行政区。"""
        inputs = {"dataset_name": dataset_name, "clip_name": clip_name, "output_name": output_name}
        errors = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_dataset_exists(manager, clip_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_vector_readable(manager, clip_name))
            errors.extend(validate_crs(manager, dataset_name))
            errors.extend(validate_crs(manager, clip_name))
        if errors:
            return _tool_error_from_validation("vector_clip_by_vector", inputs, errors)
        try:
            source = manager.get_vector(dataset_name)
            clipper = manager.get_vector(clip_name)
            source, clipper = _align_crs(source, clipper)
            clipped = gpd.clip(source, clipper)
            saved_name = manager.put_vector(output_name, clipped)
            output_path = manager.get(saved_name).path
            manager.log_operation("鐭㈤噺瑁佸壀", f"{dataset_name} by {clip_name} -> {saved_name}", "analysis")
            warnings_list = ["裁剪结果为空，请检查两个图层是否相交。"] if clipped.empty else []
            return tool_result_ok(
                "vector_clip_by_vector",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(clipped)), "path": str(output_path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="dataset",
                        title=f"{saved_name} clipped vector",
                        description=f"{dataset_name} 被 {clip_name} 裁剪后的矢量结果。",
                        quality_status="empty" if clipped.empty else "created",
                        preview_available=False,
                    )
                ],
                summary=f"矢量裁剪完成，结果数据集 {saved_name}，要素数 {len(clipped)}。",
                diagnostics={"source_count": int(len(source)), "clip_count": int(len(clipper)), "result_count": int(len(clipped)), "crs": str(source.crs)},
                warnings=warnings_list,
                next_actions=["检查裁剪结果范围和要素数量。", "如结果为空，请确认两个图层坐标系和空间范围。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_clip_by_vector", inputs, exc)
        source = manager.get_vector(dataset_name)
        clipper = manager.get_vector(clip_name)
        source, clipper = _align_crs(source, clipper)
        clipped = gpd.clip(source, clipper)
        saved_name = manager.put_vector(output_name, clipped)
        manager.log_operation("矢量裁剪", f"{dataset_name} by {clip_name} -> {saved_name}", "analysis")
        return f"矢量裁剪完成，结果: {saved_name}，要素数量: {len(clipped)}，保存路径: {manager.get(saved_name).path}"

    @tool
    def vector_overlay(dataset_name: str, overlay_name: str, how: str, output_name: str) -> str:
        """执行常见矢量叠加分析。how 可选 intersection、union、difference、identity、symmetric_difference。"""
        allowed = {"intersection", "union", "difference", "identity", "symmetric_difference"}
        inputs = {
            "dataset_name": dataset_name,
            "overlay_name": overlay_name,
            "how": how,
            "output_name": output_name,
        }
        if how not in allowed:
            return tool_result_error(
                "vector_overlay",
                inputs=inputs,
                error_code="OVERLAY_MODE_UNSUPPORTED",
                error_title="叠加方式不支持",
                user_message=f"how 必须是 {', '.join(sorted(allowed))} 之一。",
                diagnostics={"allowed": sorted(allowed), "received": how},
                next_actions=["请选择一种受支持的叠加方式后重试。"],
            ).to_json()
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_dataset_exists(manager, overlay_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_vector_readable(manager, overlay_name))
            errors.extend(validate_crs(manager, dataset_name))
            errors.extend(validate_crs(manager, overlay_name))
        if errors:
            return _tool_error_from_validation("vector_overlay", inputs, errors)

        try:
            left = manager.get_vector(dataset_name)
            right = manager.get_vector(overlay_name)
            left, right = _align_crs(left, right)
            result = gpd.overlay(left, right, how=how)
            saved_name = manager.put_vector(output_name, result)
            record = manager.get(saved_name)
            warnings_list = ["叠加结果为空，请检查两个图层是否存在空间重叠或叠加方式是否合适。"] if result.empty else []
            manager.log_operation("鐭㈤噺鍙犲姞", f"{dataset_name} {how} {overlay_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "vector_overlay",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(result)),
                    "path": str(record.path),
                    "how": how,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{dataset_name} {how} {overlay_name} overlay result",
                        quality_status="empty" if result.empty else "ok",
                        preview_available=True,
                    )
                ],
                summary=f"已完成 {dataset_name} 与 {overlay_name} 的 {how} 叠加，输出 {saved_name}，要素数 {len(result)}。",
                diagnostics={
                    "left_count": int(len(left)),
                    "right_count": int(len(right)),
                    "result_count": int(len(result)),
                    "how": how,
                    "crs": str(left.crs) if left.crs is not None else None,
                },
                warnings=warnings_list,
                next_actions=["可继续对叠加结果制图、统计属性字段，或检查空结果区域。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_overlay", inputs, exc)
        if how not in allowed:
            raise ValueError(f"how 必须是 {sorted(allowed)} 之一")
        left = manager.get_vector(dataset_name)
        right = manager.get_vector(overlay_name)
        left, right = _align_crs(left, right)
        result = gpd.overlay(left, right, how=how)
        saved_name = manager.put_vector(output_name, result)
        manager.log_operation("矢量叠加", f"{dataset_name} {how} {overlay_name} -> {saved_name}", "analysis")
        return f"矢量叠加完成，方式: {how}，结果: {saved_name}，要素数量: {len(result)}，保存路径: {manager.get(saved_name).path}"

    @tool
    def vector_dissolve(dataset_name: str, by_field: str, output_name: str) -> str:
        """按字段融合矢量面或线，适合按分类字段汇总区域。"""
        inputs = {"dataset_name": dataset_name, "by_field": by_field, "output_name": output_name}
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
            errors.extend(validate_required_fields(manager, dataset_name, [by_field]))
        if errors:
            return _tool_error_from_validation("vector_dissolve", inputs, errors)
        try:
            gdf = manager.get_vector(dataset_name)
            dissolved = gdf.dissolve(by=by_field).reset_index()
            saved_name = manager.put_vector(output_name, dissolved)
            record = manager.get(saved_name)
            manager.log_operation("矢量融合", f"{dataset_name} by {by_field} -> {saved_name}", "analysis")
            return tool_result_ok(
                "vector_dissolve",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(dissolved)), "path": str(record.path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{dataset_name} dissolved by {by_field}",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"已按字段 {by_field} 融合 {dataset_name}，输出 {saved_name}，要素数 {len(dissolved)}。",
                diagnostics={"source_count": int(len(gdf)), "result_count": int(len(dissolved)), "by_field": by_field, "crs": str(gdf.crs)},
                next_actions=["可继续对融合结果制图、叠加分析或导出。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_dissolve", inputs, exc)
        gdf = manager.get_vector(dataset_name)
        if by_field not in gdf.columns:
            raise ValueError(f"字段不存在: {by_field}。可用字段: {list(gdf.columns)}")
        dissolved = gdf.dissolve(by=by_field).reset_index()
        saved_name = manager.put_vector(output_name, dissolved)
        manager.log_operation("矢量融合", f"{dataset_name} by {by_field} -> {saved_name}", "analysis")
        return f"融合完成，结果: {saved_name}，要素数量: {len(dissolved)}，保存路径: {manager.get(saved_name).path}"

    @tool
    def vector_spatial_join(target_name: str, join_name: str, predicate: str, output_name: str, how: str = "left") -> str:
        """对两个矢量图层执行空间连接。predicate 常用 intersects、within、contains、touches、overlaps。"""
        allowed = {"intersects", "within", "contains", "touches", "overlaps", "crosses"}
        inputs = {"target_name": target_name, "join_name": join_name, "predicate": predicate, "output_name": output_name, "how": how}
        if predicate not in allowed:
            return tool_result_error(
                "vector_spatial_join",
                inputs=inputs,
                error_code="SPATIAL_PREDICATE_UNSUPPORTED",
                error_title="空间关系不支持",
                user_message=f"predicate 必须是 {', '.join(sorted(allowed))} 之一。",
                diagnostics={"allowed": sorted(allowed), "received": predicate},
                next_actions=["请选择一种受支持的空间关系后重试。"],
            ).to_json()
        if how not in {"left", "right", "inner"}:
            return tool_result_error(
                "vector_spatial_join",
                inputs=inputs,
                error_code="JOIN_MODE_UNSUPPORTED",
                error_title="连接方式不支持",
                user_message="how 必须是 left、right 或 inner。",
                diagnostics={"allowed": ["inner", "left", "right"], "received": how},
                next_actions=["请选择 left、right 或 inner 后重试。"],
            ).to_json()
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, target_name))
        errors.extend(validate_dataset_exists(manager, join_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not errors:
            errors.extend(validate_vector_readable(manager, target_name))
            errors.extend(validate_vector_readable(manager, join_name))
            errors.extend(validate_crs(manager, target_name))
            errors.extend(validate_crs(manager, join_name))
        if errors:
            return _tool_error_from_validation("vector_spatial_join", inputs, errors)
        try:
            target = manager.get_vector(target_name)
            join_gdf = manager.get_vector(join_name)
            target, join_gdf = _align_crs(target, join_gdf)
            joined = gpd.sjoin(target, join_gdf, how=how, predicate=predicate)
            if "index_right" in joined.columns:
                joined = joined.drop(columns=["index_right"])
            saved_name = manager.put_vector(output_name, joined)
            record = manager.get(saved_name)
            manager.log_operation("空间连接", f"{target_name} {predicate} {join_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "vector_spatial_join",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(joined)), "path": str(record.path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{target_name} {predicate} {join_name} spatial join result",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"已完成 {target_name} 与 {join_name} 的空间连接，输出 {saved_name}，要素数 {len(joined)}。",
                diagnostics={
                    "target_count": int(len(target)),
                    "join_count": int(len(join_gdf)),
                    "result_count": int(len(joined)),
                    "predicate": predicate,
                    "how": how,
                    "crs": str(target.crs),
                },
                next_actions=["可继续统计连接结果、制图或导出。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("vector_spatial_join", inputs, exc)
        if predicate not in allowed:
            raise ValueError(f"predicate 必须是 {sorted(allowed)} 之一")
        target = manager.get_vector(target_name)
        join_gdf = manager.get_vector(join_name)
        target, join_gdf = _align_crs(target, join_gdf)
        joined = gpd.sjoin(target, join_gdf, how=how, predicate=predicate)
        if "index_right" in joined.columns:
            joined = joined.drop(columns=["index_right"])
        saved_name = manager.put_vector(output_name, joined)
        manager.log_operation("空间连接", f"{target_name} {predicate} {join_name} -> {saved_name}", "analysis")
        return f"空间连接完成，结果: {saved_name}，连接方式: {how}，空间关系: {predicate}，保存路径: {manager.get(saved_name).path}"

    @tool
    def reproject_vector(dataset_name: str, target_crs: str, output_name: str) -> str:
        """将矢量数据重投影到目标坐标系，例如 EPSG:3857 或 EPSG:4326。"""
        inputs = {"dataset_name": dataset_name, "target_crs": target_crs, "output_name": output_name}
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        target_crs_value = str(target_crs or "").strip()
        try:
            if not target_crs_value:
                raise ValueError("target CRS is required")
            CRS.from_user_input(target_crs_value)
        except Exception as exc:
            return tool_result_error(
                "reproject_vector",
                inputs=inputs,
                error_code="TARGET_CRS_INVALID",
                error_title="Invalid target CRS",
                user_message=f"Target CRS {target_crs!r} is not a valid CRS identifier.",
                diagnostics={"target_crs": target_crs, "exception_type": type(exc).__name__},
                next_actions=["Use an EPSG code such as EPSG:4326 or EPSG:3857."],
                technical_detail=f"{type(exc).__name__}: {exc}",
            ).to_json()
        if not errors:
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("reproject_vector", inputs, errors)
        try:
            gdf = manager.get_vector(dataset_name)
            reproj = gdf.to_crs(target_crs_value)
            saved_name = manager.put_vector(output_name, reproj)
            record = manager.get(saved_name)
            manager.log_operation("矢量重投影", f"{dataset_name} -> {saved_name} | {target_crs_value}", "analysis")
            return tool_result_ok(
                "reproject_vector",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(reproj)),
                    "path": str(record.path),
                    "source_crs": str(gdf.crs),
                    "target_crs": target_crs_value,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{dataset_name} reprojected to {target_crs_value}.",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"Reprojected {dataset_name} to {target_crs_value} as {saved_name}.",
                diagnostics={"source_count": int(len(gdf)), "result_count": int(len(reproj)), "source_crs": str(gdf.crs), "target_crs": target_crs_value},
                next_actions=["Use the reprojected dataset for overlay, clipping, mapping, or export."],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("reproject_vector", inputs, exc)

    @tool
    def table_to_points(dataset_name: str, x_col: str, y_col: str, crs: str, output_name: str) -> str:
        """将表格按经纬度或平面坐标字段转换为点图层。"""
        inputs = {"dataset_name": dataset_name, "x_col": x_col, "y_col": y_col, "crs": crs, "output_name": output_name}
        errors = validate_dataset_exists(manager, dataset_name)
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not str(crs or "").strip():
            errors.append(
                {
                    "error_code": "CRS_REQUIRED",
                    "error_title": "缺少坐标系",
                    "user_message": "表格转点需要指定输出点图层的 CRS。",
                    "next_actions": ["如果坐标是经纬度，通常使用 EPSG:4326。", "如果是投影坐标，请填写对应 EPSG 代码。"],
                    "diagnostics": {},
                }
            )
        if not errors:
            try:
                record = manager.get(dataset_name)
                if record.data_type != "table":
                    return tool_result_error(
                        "table_to_points",
                        inputs=inputs,
                        error_code="UNSUPPORTED_DATASET_TYPE",
                        error_title="数据类型不支持",
                        user_message="table_to_points 只能处理表格数据。",
                        diagnostics={"dataset_type": record.data_type},
                        next_actions=["选择 CSV/Excel 表格数据，或直接使用已有矢量数据制图。"],
                    ).to_json()
            except Exception as exc:
                return _tool_internal_error("table_to_points", inputs, exc)
            errors.extend(validate_required_fields(manager, dataset_name, [x_col, y_col]))
            if not errors:
                errors.extend(validate_numeric_fields(manager, dataset_name, [x_col, y_col]))
        if errors:
            return _tool_error_from_validation("table_to_points", inputs, errors)
        try:
            df = manager.get_table(dataset_name)
            gdf = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(df[x_col], df[y_col]), crs=crs)
            saved_name = manager.put_vector(output_name, gdf)
            output_path = manager.get(saved_name).path
            manager.log_operation("琛ㄦ牸杞偣", f"{dataset_name} -> {saved_name} | {x_col},{y_col}", "analysis")
            return tool_result_ok(
                "table_to_points",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(gdf)), "path": str(output_path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="dataset",
                        title=f"{saved_name} point layer",
                        description=f"由表格 {dataset_name} 转换得到的点图层。",
                        quality_status="created",
                        preview_available=False,
                    )
                ],
                summary=f"表格转点完成，结果数据集 {saved_name}，点数量 {len(gdf)}。",
                diagnostics={"x_col": x_col, "y_col": y_col, "crs": crs, "row_count": int(len(df))},
                next_actions=["使用 plot_dataset 生成点位分布图。", "继续叠加边界或提取栅格值。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("table_to_points", inputs, exc)
        df = manager.get_table(dataset_name)
        if x_col not in df.columns or y_col not in df.columns:
            raise ValueError(f"字段不存在。可用字段: {list(df.columns)}")
        gdf = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(df[x_col], df[y_col]), crs=crs)
        saved_name = manager.put_vector(output_name, gdf)
        manager.log_operation("表格转点", f"{dataset_name} -> {saved_name} | {x_col},{y_col}", "analysis")
        return f"表格转点完成，结果: {saved_name}，要素数量: {len(gdf)}，保存路径: {manager.get(saved_name).path}"

    @tool
    def create_centroids(dataset_name: str, output_name: str) -> str:
        """将面或线图层转为质心点图层，常用于区域代表点、标注点和后续点分析。"""
        gdf = manager.get_vector(dataset_name)
        projected, used_crs = _estimate_projected_gdf(gdf)
        centroid_proj = projected.copy()
        centroid_proj["geometry"] = projected.centroid
        centroids = centroid_proj.to_crs(gdf.crs)
        saved_name = manager.put_vector(output_name, centroids)
        manager.log_operation("生成质心", f"{dataset_name} -> {saved_name}", "analysis")
        return f"质心点图层已生成: {saved_name}，处理投影: {used_crs}，保存路径: {manager.get(saved_name).path}"

    @tool
    def calculate_geometry_fields(
        dataset_name: str,
        output_name: str,
        area_field: str = "area_value",
        length_field: str = "length_value",
        centroid_x_field: str = "centroid_x",
        centroid_y_field: str = "centroid_y",
    ) -> str:
        """为矢量图层计算面积、长度和质心坐标字段，适合论文统计、字段补充和制表。"""
        gdf = manager.get_vector(dataset_name)
        projected, used_crs = _estimate_projected_gdf(gdf)
        enriched = gdf.copy()
        enriched[area_field] = projected.area
        enriched[length_field] = projected.length
        centroids = projected.centroid
        enriched[centroid_x_field] = centroids.x
        enriched[centroid_y_field] = centroids.y
        saved_name = manager.put_vector(output_name, enriched)
        manager.log_operation("几何字段计算", f"{dataset_name} -> {saved_name}", "analysis")
        return (
            f"几何字段已写入: {saved_name}，面积字段: {area_field}，长度字段: {length_field}，"
            f"质心字段: {centroid_x_field}/{centroid_y_field}，处理投影: {used_crs}，保存路径: {manager.get(saved_name).path}"
        )

    @tool
    def join_attributes(left_name: str, right_name: str, left_key: str, right_key: str, output_name: str) -> str:
        """按字段把表格或矢量属性连接到另一张表或图层上，适合行政区属性补充、统计结果回连等场景。"""
        inputs = {
            "left_name": left_name,
            "right_name": right_name,
            "left_key": left_key,
            "right_key": right_key,
            "output_name": output_name,
        }
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, left_name))
        errors.extend(validate_dataset_exists(manager, right_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if errors:
            return _tool_error_from_validation("join_attributes", inputs, errors)
        try:
            left_obj, left_type = _prepare_join_frame(left_name, manager)
            right_obj, _ = _prepare_join_frame(right_name, manager)
        except Exception as exc:
            return _tool_internal_error("join_attributes", inputs, exc)

        missing: list[str] = []
        if left_key not in left_obj.columns:
            missing.append(str(left_key))
        if right_key not in right_obj.columns:
            missing.append(str(right_key))
        if missing:
            return tool_result_error(
                "join_attributes",
                inputs=inputs,
                error_code="FIELD_NOT_FOUND",
                error_title="Join key field not found",
                user_message="One or more join key fields do not exist in the selected datasets.",
                diagnostics={
                    "missing_fields": missing,
                    "left_fields": [str(col) for col in left_obj.columns],
                    "right_fields": [str(col) for col in right_obj.columns],
                },
                next_actions=["Choose existing key fields from both datasets, then retry the attribute join."],
            ).to_json()

        try:
            right_attrs = right_obj.drop(columns=["geometry"], errors="ignore").copy()
            merged = left_obj.merge(right_attrs, how="left", left_on=left_key, right_on=right_key, suffixes=("", "_joined"))
            matched_rows = int(merged[right_key].notna().sum()) if right_key in merged.columns else 0

            if left_type == "vector":
                saved_name = manager.put_vector(output_name, gpd.GeoDataFrame(merged, geometry=left_obj.geometry, crs=getattr(left_obj, "crs", None)))
                artifact_type = "dataset"
            else:
                saved_name = manager.put_table(output_name, pd.DataFrame(merged))
                artifact_type = "dataset"
            record = manager.get(saved_name)
            manager.log_operation("属性连接", f"{left_name} <- {right_name} | {left_key}={right_key}", "analysis")
            return tool_result_ok(
                "join_attributes",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "row_count": int(len(merged)),
                    "path": str(record.path),
                    "left_type": left_type,
                    "matched_rows": matched_rows,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type=artifact_type,
                        title=saved_name,
                        description=f"Attribute join result from {left_name} and {right_name}.",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"Joined attributes from {right_name} to {left_name} into {saved_name}.",
                diagnostics={
                    "left_rows": int(len(left_obj)),
                    "right_rows": int(len(right_obj)),
                    "result_rows": int(len(merged)),
                    "matched_rows": matched_rows,
                    "left_key": left_key,
                    "right_key": right_key,
                },
                warnings=[] if matched_rows else ["No rows matched the selected join keys."],
                next_actions=["Inspect join match counts, then map, model, or export the joined dataset."],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("join_attributes", inputs, exc)

    @tool
    def summarize_points_within_polygons(
        point_name: str,
        polygon_name: str,
        output_name: str,
        count_field: str = "point_count",
        numeric_field: str = "",
        stat: str = "mean",
    ) -> str:
        """统计面内点数量，并可对点属性做聚合统计。适合 POI、站点、样点等点位汇总到行政区或网格。"""
        inputs = {
            "point_name": point_name,
            "polygon_name": polygon_name,
            "output_name": output_name,
            "count_field": count_field,
            "numeric_field": numeric_field,
            "stat": stat,
        }
        allowed_stats = {"mean", "sum", "min", "max", "median"}
        if stat not in allowed_stats:
            return tool_result_error(
                "summarize_points_within_polygons",
                inputs=inputs,
                error_code="STAT_UNSUPPORTED",
                error_title="统计方式不支持",
                user_message=f"stat 必须是 {', '.join(sorted(allowed_stats))} 之一。",
                diagnostics={"allowed": sorted(allowed_stats), "received": stat},
                next_actions=["请选择一种受支持的统计方式后重试。"],
            ).to_json()
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, point_name))
        errors.extend(validate_dataset_exists(manager, polygon_name))
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not str(count_field or "").strip():
            errors.append(
                {
                    "error_code": "OUTPUT_FIELD_REQUIRED",
                    "error_title": "缺少输出字段",
                    "user_message": "请指定保存点数量的 count_field。",
                    "next_actions": ["提供 count_field，例如 point_count。"],
                    "diagnostics": {},
                }
            )
        if not errors:
            errors.extend(validate_vector_readable(manager, point_name))
            errors.extend(validate_vector_readable(manager, polygon_name))
            errors.extend(validate_crs(manager, point_name))
            errors.extend(validate_crs(manager, polygon_name))
            errors.extend(validate_geometry_type(manager, point_name, ["Point"]))
            errors.extend(validate_geometry_type(manager, polygon_name, ["Polygon", "MultiPolygon"]))
            if str(numeric_field or "").strip():
                errors.extend(validate_required_fields(manager, point_name, [numeric_field]))
                errors.extend(validate_numeric_fields(manager, point_name, [numeric_field]))
        if errors:
            return _tool_error_from_validation("summarize_points_within_polygons", inputs, errors)
        try:
            points = manager.get_vector(point_name)
            polygons = manager.get_vector(polygon_name)
            points, polygons = _align_crs(points, polygons)
            joined = gpd.sjoin(points, polygons, predicate="within", how="inner")
            grouped_count = joined.groupby("index_right").size()

            result = polygons.copy()
            result[count_field] = result.index.to_series().map(grouped_count).fillna(0).astype(int)
            fields_added = [count_field]
            if numeric_field:
                grouped_values = joined.groupby("index_right")[numeric_field].agg(stat)
                out_field = f"{numeric_field}_{stat}"
                result[out_field] = result.index.to_series().map(grouped_values)
                fields_added.append(out_field)

            saved_name = manager.put_vector(output_name, result)
            record = manager.get(saved_name)
            manager.log_operation("面内点统计", f"{point_name} in {polygon_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "summarize_points_within_polygons",
                inputs=inputs,
                outputs={
                    "result_dataset": saved_name,
                    "feature_count": int(len(result)),
                    "path": str(record.path),
                    "fields_added": fields_added,
                },
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset:{saved_name}",
                        path=str(record.path),
                        type="dataset",
                        title=saved_name,
                        description=f"{point_name} summarized within {polygon_name}",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"已将 {point_name} 汇总到 {polygon_name}，输出 {saved_name}，新增字段 {', '.join(fields_added)}。",
                diagnostics={
                    "point_count": int(len(points)),
                    "polygon_count": int(len(polygons)),
                    "matched_points": int(len(joined)),
                    "stat": stat,
                    "crs": str(polygons.crs),
                },
                next_actions=["可继续对统计字段制图、排序检查异常区域，或导出结果。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("summarize_points_within_polygons", inputs, exc)
        points = manager.get_vector(point_name)
        polygons = manager.get_vector(polygon_name)
        points, polygons = _align_crs(points, polygons)
        joined = gpd.sjoin(points, polygons, predicate="within", how="inner")
        grouped_count = joined.groupby("index_right").size()

        result = polygons.copy()
        result[count_field] = result.index.to_series().map(grouped_count).fillna(0).astype(int)

        extra_msg = ""
        if numeric_field:
            if numeric_field not in joined.columns:
                raise ValueError(f"点图层中未找到字段 {numeric_field}。可用字段: {list(joined.columns)}")
            allowed = {"mean", "sum", "min", "max", "median"}
            if stat not in allowed:
                raise ValueError(f"stat 必须是 {sorted(allowed)} 之一")
            grouped_values = joined.groupby("index_right")[numeric_field].agg(stat)
            out_field = f"{numeric_field}_{stat}"
            result[out_field] = result.index.to_series().map(grouped_values)
            extra_msg = f"，并计算了 {numeric_field} 的 {stat}: 字段 {out_field}"

        saved_name = manager.put_vector(output_name, result)
        manager.log_operation("面内点统计", f"{point_name} in {polygon_name} -> {saved_name}", "analysis")
        return f"面内点统计完成，结果: {saved_name}，计数字段 {count_field}{extra_msg}，保存路径 {manager.get(saved_name).path}"

        inputs = {"point_name": point_name, "raster_name": raster_name, "output_name": output_name, "field_name": field_name, "band": band}
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
                values = [val[0] if len(val) else None for val in src.sample(coords, indexes=band)]
                result = points.copy()
                result[field_name] = values

            saved_name = manager.put_vector(output_name, result)
            output_path = manager.get(saved_name).path
            manager.log_operation("鏍呮牸鎶芥牱鍒扮偣", f"{raster_name} -> {point_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "extract_raster_values_to_points",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(result)), "field_name": field_name, "path": str(output_path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="dataset",
                        title=f"{saved_name} raster sampled points",
                        description=f"点图层 {point_name} 提取栅格 {raster_name} 后的结果。",
                        quality_status="created",
                        preview_available=False,
                    )
                ],
                summary=f"栅格值提取完成，结果数据集 {saved_name}，字段 {field_name}。",
                diagnostics={"sample_count": int(len(values)), "band": int(band), "raster": raster_name},
                next_actions=["检查提取字段的缺失值和异常值。", "可继续用于建模或专题制图。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("extract_raster_values_to_points", inputs, exc)
        points = manager.get_vector(point_name)
        polygons = manager.get_vector(polygon_name)
        points, polygons = _align_crs(points, polygons)
        joined = gpd.sjoin(points, polygons, predicate="within", how="inner")
        grouped_count = joined.groupby("index_right").size()

        result = polygons.copy()
        result[count_field] = result.index.to_series().map(grouped_count).fillna(0).astype(int)

        extra_msg = ""
        if numeric_field:
            if numeric_field not in joined.columns:
                raise ValueError(f"点图层中未找到字段: {numeric_field}。可用字段: {list(joined.columns)}")
            allowed = {"mean", "sum", "min", "max", "median"}
            if stat not in allowed:
                raise ValueError(f"stat 必须是 {sorted(allowed)} 之一")
            grouped_values = joined.groupby("index_right")[numeric_field].agg(stat)
            out_field = f"{numeric_field}_{stat}"
            result[out_field] = result.index.to_series().map(grouped_values)
            extra_msg = f"，并计算了 {numeric_field} 的 {stat}: 字段 {out_field}"

        saved_name = manager.put_vector(output_name, result)
        manager.log_operation("面内点统计", f"{point_name} in {polygon_name} -> {saved_name}", "analysis")
        return f"面内点统计完成，结果: {saved_name}，计数字段: {count_field}{extra_msg}，保存路径: {manager.get(saved_name).path}"

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
            manager.log_operation("鏍呮牸瑁佸壀", f"{raster_name} by {vector_name} -> {stored_name}", "analysis")
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
    def extract_raster_values_to_points(point_name: str, raster_name: str, output_name: str, field_name: str = "raster_val", band: int = 1) -> str:
        """将栅格像元值提取到点图层属性表中，适合站点-栅格匹配、样点验证和建模前特征抽取。"""
        inputs = {"point_name": point_name, "raster_name": raster_name, "output_name": output_name, "field_name": field_name, "band": band}
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
                values = [val[0] if len(val) else None for val in src.sample(coords, indexes=band)]
                result = points.copy()
                result[field_name] = values

            saved_name = manager.put_vector(output_name, result)
            output_path = manager.get(saved_name).path
            manager.log_operation("鏍呮牸鎶芥牱鍒扮偣", f"{raster_name} -> {point_name} -> {saved_name}", "analysis")
            return tool_result_ok(
                "extract_raster_values_to_points",
                inputs=inputs,
                outputs={"result_dataset": saved_name, "feature_count": int(len(result)), "field_name": field_name, "path": str(output_path)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"dataset_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="dataset",
                        title=f"{saved_name} raster sampled points",
                        description=f"点图层 {point_name} 提取栅格 {raster_name} 后的结果。",
                        quality_status="created",
                        preview_available=False,
                    )
                ],
                summary=f"栅格值提取完成，结果数据集 {saved_name}，字段 {field_name}。",
                diagnostics={"sample_count": int(len(values)), "band": int(band), "raster": raster_name},
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


    @tool
    def build_time_features(
        dataset_name: str,
        date_col: str,
        value_cols: str,
        output_name: str,
        group_col: str = "",
        lags: str = "1,3,7",
        rolling_windows: str = "3,7",
    ) -> str:
        """为时间序列表格构建滞后项与滚动统计特征，适合降水累积量、土壤水分记忆效应和 RF 或 LSTM 建模前特征工程。"""
        df = _prepare_dataframe(dataset_name, manager).copy()
        values = _parse_columns(value_cols)
        _validate_columns(df, values)
        if group_col and group_col not in df.columns:
            raise ValueError(f"分组字段不存在: {group_col}")
        df[date_col] = _ensure_datetime(df, date_col)
        lag_list = _parse_int_list(lags, [1, 3, 7])
        rolling_list = _parse_int_list(rolling_windows, [3, 7])

        sort_cols = [group_col, date_col] if group_col else [date_col]
        df = df.sort_values(sort_cols).reset_index(drop=True)

        def _transform(group: pd.DataFrame) -> pd.DataFrame:
            out = group.copy()
            for col in values:
                numeric = pd.to_numeric(out[col], errors="coerce")
                for lag in lag_list:
                    out[f"{col}_lag_{lag}"] = numeric.shift(lag)
                for window in rolling_list:
                    out[f"{col}_rollmean_{window}"] = numeric.rolling(window=window, min_periods=1).mean()
                    out[f"{col}_rollsum_{window}"] = numeric.rolling(window=window, min_periods=1).sum()
            return out

        result = df.groupby(group_col, group_keys=False).apply(_transform) if group_col else _transform(df)
        saved_name = manager.put_table(output_name, result)
        manager.log_operation("构建时间特征", f"{dataset_name} -> {saved_name}", "analysis")
        return f"时间特征构建完成，结果表: {saved_name}，新增字段已包含 lag / rollmean / rollsum，保存路径: {manager.get(saved_name).path}"

    @tool
    def aggregate_time_series(
        dataset_name: str,
        date_col: str,
        value_cols: str,
        output_name: str,
        freq: str = "month",
        agg: str = "mean",
        group_col: str = "",
    ) -> str:
        """按月、季节、季度、年等时间尺度聚合时间序列表格，适合月尺度或季节尺度结果分析。"""
        df = _prepare_dataframe(dataset_name, manager).copy()
        values = _parse_columns(value_cols)
        _validate_columns(df, values)
        if group_col and group_col not in df.columns:
            raise ValueError(f"分组字段不存在: {group_col}")
        allowed_agg = {"mean", "sum", "min", "max", "median"}
        if agg not in allowed_agg:
            raise ValueError(f"agg 必须是 {sorted(allowed_agg)} 之一")
        df[date_col] = _ensure_datetime(df, date_col)
        for col in values:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        freq_key = freq.strip().lower()
        if freq_key in {"month", "monthly", "m"}:
            groupers = [pd.Grouper(key=date_col, freq="MS")]
        elif freq_key in {"quarter", "quarterly", "q"}:
            groupers = [pd.Grouper(key=date_col, freq="QS")]
        elif freq_key in {"year", "yearly", "y", "annual"}:
            groupers = [pd.Grouper(key=date_col, freq="YS")]
        elif freq_key in {"week", "weekly", "w"}:
            groupers = [pd.Grouper(key=date_col, freq="W-MON")]
        elif freq_key in {"season", "seasonal"}:
            df["season"] = df[date_col].dt.month.map(SEASON_MAP)
            df["season_year"] = df[date_col].dt.year + (df[date_col].dt.month == 12).astype(int)
            groupers = ["season_year", "season"]
        else:
            raise ValueError("freq 目前支持 month、quarter、year、week、season。")

        if group_col:
            groupers = [group_col, *groupers]
        grouped = df.groupby(groupers, dropna=False)[values].agg(agg).reset_index()
        saved_name = manager.put_table(output_name, grouped)
        manager.log_operation("时间聚合", f"{dataset_name} -> {saved_name} | {freq}/{agg}", "analysis")
        return f"时间聚合完成，结果表: {saved_name}，频率: {freq}，聚合方式: {agg}，保存路径: {manager.get(saved_name).path}"

    @tool
    def evaluate_prediction_accuracy(
        dataset_name: str,
        observed_col: str,
        predicted_cols: str,
        output_name: str = "",
        group_col: str = "",
    ) -> str:
        """对观测列与一个或多个预测列计算 R、RMSE、ubRMSE、Bias、NSE、MAE，适合土壤水分产品和融合模型比较。"""
        df = _prepare_dataframe(dataset_name, manager).copy()
        pred_cols = _parse_columns(predicted_cols) if str(predicted_cols or "").strip() else []
        _validate_columns(df, [observed_col, *pred_cols])
        if group_col and group_col not in df.columns:
            raise ValueError(f"分组字段不存在: {group_col}")

        rows: list[dict[str, object]] = []
        if group_col:
            for group_value, sub_df in df.groupby(group_col, dropna=False):
                for pred_col in pred_cols:
                    metrics = _calc_metrics(sub_df[observed_col], sub_df[pred_col])
                    rows.append({"group": group_value, "observed": observed_col, "predicted": pred_col, **metrics})
        else:
            for pred_col in pred_cols:
                metrics = _calc_metrics(df[observed_col], df[pred_col])
                rows.append({"observed": observed_col, "predicted": pred_col, **metrics})

        result_df = pd.DataFrame(rows)
        manager.log_operation("精度评价", f"{dataset_name} | {observed_col} vs {pred_cols}", "analysis")
        if output_name:
            saved_name = manager.put_table(output_name, result_df)
            return f"精度评价完成，结果表: {saved_name}，保存路径: {manager.get(saved_name).path}"
        return _json(result_df.to_dict(orient="records"))

    @tool
    def geographical_conformal_prediction(
        calibration_dataset: str,
        observed_col: str,
        predicted_cols: str,
        output_name: str,
        target_dataset_name: str = "",
        lon_col: str = "",
        lat_col: str = "",
        date_col: str = "",
        calibration_filter: str = "",
        target_filter: str = "",
        calibration_ratio: float = 0.3,
        calibration_selection: str = "latest",
        alpha: float = 0.1,
        bandwidth: float = 0.0,
        kernel: str = "gaussian",
        bin_count: int = 5,
    ) -> str:
        """对一个或多个模型预测结果执行地理共形预测（GCP），输出位置相关预测区间、覆盖率和区间宽度等不确定性指标；若缺少空间坐标则自动退化为全局 split conformal。"""
        inputs = {
            "calibration_dataset": calibration_dataset,
            "observed_col": observed_col,
            "predicted_cols": predicted_cols,
            "output_name": output_name,
            "target_dataset_name": target_dataset_name,
            "lon_col": lon_col,
            "lat_col": lat_col,
            "date_col": date_col,
            "alpha": alpha,
            "calibration_ratio": calibration_ratio,
        }
        pred_cols = _parse_columns(predicted_cols)
        validation_errors: list[dict[str, Any]] = []
        validation_errors.extend(validate_dataset_exists(manager, calibration_dataset))
        if str(target_dataset_name or "").strip():
            validation_errors.extend(validate_dataset_exists(manager, target_dataset_name))
        validation_errors.extend(validate_model_target(manager, calibration_dataset, observed_col))
        validation_errors.extend(validate_required_fields(manager, calibration_dataset, pred_cols))
        validation_errors.extend(validate_numeric_fields(manager, calibration_dataset, pred_cols))
        target_name_for_validation = target_dataset_name.strip() or calibration_dataset
        if target_name_for_validation != calibration_dataset:
            validation_errors.extend(validate_required_fields(manager, target_name_for_validation, pred_cols))
            validation_errors.extend(validate_numeric_fields(manager, target_name_for_validation, pred_cols))
        validation_errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not pred_cols:
            validation_errors.append({
                "error_code": "PREDICTED_FIELDS_MISSING",
                "error_title": "Missing predicted fields",
                "user_message": "Please provide at least one prediction field for GCP.",
                "next_actions": ["Choose one or more model prediction columns, for example xgb_pred or rf_pred."],
                "diagnostics": {},
            })
        if not 0 < float(alpha) < 1:
            validation_errors.append({
                "error_code": "ALPHA_OUT_OF_RANGE",
                "error_title": "Invalid alpha",
                "user_message": "alpha must be between 0 and 1.",
                "next_actions": ["Use alpha=0.1 for a 90% prediction interval."],
                "diagnostics": {"alpha": alpha},
            })
        if not 0 < float(calibration_ratio) < 1:
            validation_errors.append({
                "error_code": "CALIBRATION_RATIO_OUT_OF_RANGE",
                "error_title": "Invalid calibration ratio",
                "user_message": "calibration_ratio must be between 0 and 1.",
                "next_actions": ["Use a value such as 0.3 when no explicit calibration filter is provided."],
                "diagnostics": {"calibration_ratio": calibration_ratio},
            })
        calibration_selection = (calibration_selection or "latest").strip().lower()
        if calibration_selection not in {"latest", "earliest", "random"}:
            validation_errors.append({
                "error_code": "CALIBRATION_SELECTION_UNSUPPORTED",
                "error_title": "Unsupported calibration selection",
                "user_message": "calibration_selection only supports latest, earliest, or random.",
                "next_actions": ["Use latest, earliest, or random."],
                "diagnostics": {"calibration_selection": calibration_selection},
            })
        if validation_errors:
            first = first_error(validation_errors) or {}
            return tool_result_error(
                "geographical_conformal_prediction",
                inputs=inputs,
                error_code=str(first.get("error_code") or "GCP_PRECONDITION_FAILED"),
                error_title=str(first.get("error_title") or "GCP precondition failed"),
                user_message=str(first.get("user_message") or "GCP inputs are incomplete or invalid."),
                diagnostics=validation_diagnostics(validation_errors),
                next_actions=merge_next_actions(validation_errors),
                technical_detail=str(first.get("technical_detail") or ""),
            ).to_json()

        cal_df = _prepare_dataframe(calibration_dataset, manager).copy()
        target_name = target_dataset_name.strip() or calibration_dataset
        target_df, target_gdf = _prepare_dataframe_with_geometry(target_name, manager)
        target_df = target_df.copy()

        _validate_columns(cal_df, [observed_col, *pred_cols])
        _validate_columns(target_df, pred_cols)
        if observed_col in target_df.columns:
            target_has_obs = True
        else:
            target_has_obs = False

        if date_col:
            if date_col in cal_df.columns:
                cal_df[date_col] = _ensure_datetime(cal_df, date_col)
            if date_col in target_df.columns:
                target_df[date_col] = _ensure_datetime(target_df, date_col)

        cal_coords, cal_coord_meta = _resolve_spatial_coordinates(calibration_dataset, cal_df, manager, lon_col=lon_col, lat_col=lat_col)
        target_coords, target_coord_meta = _resolve_spatial_coordinates(target_name, target_df, manager, lon_col=lon_col, lat_col=lat_col)
        spatial_ready = bool(
            cal_coords is not None and target_coords is not None and
            cal_coord_meta.get("spatial_ready") and target_coord_meta.get("spatial_ready")
        )

        cal_mask = pd.Series(True, index=cal_df.index)
        if calibration_filter.strip():
            cal_mask &= _build_mask_from_query(cal_df, calibration_filter, "calibration_filter")
        else:
            base_valid = cal_df[observed_col].notna()
            rng = np.random.default_rng(42)
            if date_col and date_col in cal_df.columns:
                ordered = cal_df.loc[base_valid].sort_values(date_col)
                take_n = max(20, int(len(ordered) * float(calibration_ratio)))
                take_n = min(len(ordered), take_n)
                if calibration_selection == "earliest":
                    chosen = ordered.index[:take_n]
                elif calibration_selection == "latest":
                    chosen = ordered.index[-take_n:]
                else:
                    chosen = rng.choice(ordered.index.to_numpy(), size=take_n, replace=False) if take_n else []
                cal_mask &= cal_df.index.isin(chosen)
            else:
                valid_index = cal_df.index[base_valid].to_numpy()
                take_n = max(20, int(len(valid_index) * float(calibration_ratio))) if len(valid_index) else 0
                take_n = min(len(valid_index), take_n)
                if calibration_selection == "earliest":
                    chosen = valid_index[:take_n]
                elif calibration_selection == "latest":
                    chosen = valid_index[-take_n:]
                else:
                    chosen = rng.choice(valid_index, size=take_n, replace=False) if take_n else []
                cal_mask &= cal_df.index.isin(chosen)

        if target_filter.strip():
            target_mask = _build_mask_from_query(target_df, target_filter, "target_filter")
        elif target_name == calibration_dataset:
            target_mask = ~cal_mask
        else:
            target_mask = pd.Series(True, index=target_df.index)

        if target_name == calibration_dataset and not bool(target_mask.any()):
            target_mask = pd.Series(True, index=target_df.index)

        result_df = target_df.copy()
        metrics_rows: list[dict[str, Any]] = []
        summary_rows: list[dict[str, Any]] = []
        bw_value = float(bandwidth) if float(bandwidth) > 0 else None

        for pred_col in pred_cols:
            cal_work = pd.DataFrame({
                "obs": pd.to_numeric(cal_df[observed_col], errors="coerce"),
                "pred": pd.to_numeric(cal_df[pred_col], errors="coerce"),
            }, index=cal_df.index)
            cal_work["score"] = np.abs(cal_work["obs"] - cal_work["pred"])
            if cal_coords is not None:
                cal_work = cal_work.join(cal_coords)
            cal_valid = cal_mask & cal_work["obs"].notna() & cal_work["pred"].notna()
            if spatial_ready:
                cal_valid &= cal_work[["__coord_x__", "__coord_y__"]].notna().all(axis=1)
            cal_use = cal_work.loc[cal_valid].copy()
            if len(cal_use) < 20:
                return tool_result_error(
                    "geographical_conformal_prediction",
                    inputs=inputs,
                    error_code="GCP_CALIBRATION_SAMPLE_TOO_SMALL",
                    error_title="Calibration sample too small",
                    user_message=f"{pred_col} has only {len(cal_use)} usable calibration samples; at least 20 are required.",
                    diagnostics={"predicted_col": pred_col, "usable_calibration_samples": int(len(cal_use))},
                    next_actions=["Use a larger calibration set.", "Relax filters or increase calibration_ratio.", "Check missing values in observed and predicted columns."],
                ).to_json()

            quantile_level = _conformal_quantile_level(len(cal_use), float(alpha))
            global_qhat = _weighted_quantile(cal_use["score"].to_numpy(dtype=float), quantile_level)

            target_work = pd.DataFrame({
                "pred": pd.to_numeric(target_df[pred_col], errors="coerce"),
            }, index=target_df.index)
            if target_has_obs:
                target_work["obs"] = pd.to_numeric(target_df[observed_col], errors="coerce")
            if target_coords is not None:
                target_work = target_work.join(target_coords)
            target_valid = target_mask & target_work["pred"].notna()
            if spatial_ready:
                target_valid &= target_work[["__coord_x__", "__coord_y__"]].notna().all(axis=1)
            if not bool(target_valid.any()):
                return tool_result_error(
                    "geographical_conformal_prediction",
                    inputs=inputs,
                    error_code="GCP_TARGET_SAMPLE_EMPTY",
                    error_title="No usable target samples",
                    user_message=f"{pred_col} has no usable target samples for GCP.",
                    diagnostics={"predicted_col": pred_col, "target_dataset": target_name},
                    next_actions=["Check missing values in prediction columns.", "Relax target_filter.", "Use a target dataset that contains model predictions."],
                ).to_json()

            radius_col = f"{pred_col}_gcp_radius"
            lower_col = f"{pred_col}_gcp_lower"
            upper_col = f"{pred_col}_gcp_upper"
            cover_col = f"{pred_col}_gcp_covered"
            result_df[radius_col] = np.nan
            result_df[lower_col] = np.nan
            result_df[upper_col] = np.nan
            if target_has_obs:
                result_df[cover_col] = np.nan

            target_index = target_df.index[target_valid]
            local_qhat = np.full(len(target_index), float(global_qhat), dtype=float)
            method_used = "split_conformal"

            if spatial_ready:
                cal_xy = cal_use[["__coord_x__", "__coord_y__"]].to_numpy(dtype=float)
                target_xy = target_work.loc[target_index, ["__coord_x__", "__coord_y__"]].to_numpy(dtype=float)
                bw_local = float(bw_value) if bw_value is not None else _auto_bandwidth(cal_xy)
                scores = cal_use["score"].to_numpy(dtype=float)
                for i, xy in enumerate(target_xy):
                    dist = np.sqrt(np.sum(np.square(cal_xy - xy), axis=1))
                    weights = _kernel_weights(dist, bw_local, kernel)
                    if np.sum(weights) > 0:
                        local_qhat[i] = _weighted_quantile(scores, quantile_level, sample_weight=weights)
                method_used = "gcp"
                if bw_value is None:
                    bw_value = bw_local

            pred_values = target_work.loc[target_index, "pred"].to_numpy(dtype=float)
            lower_values = pred_values - local_qhat
            upper_values = pred_values + local_qhat
            result_df.loc[target_index, radius_col] = local_qhat
            result_df.loc[target_index, lower_col] = lower_values
            result_df.loc[target_index, upper_col] = upper_values
            if target_has_obs:
                obs_values = target_work.loc[target_index, "obs"]
                covered = ((obs_values >= lower_values) & (obs_values <= upper_values)).astype(float)
                result_df.loc[target_index, cover_col] = covered.to_numpy(dtype=float)
                interval_metrics = _calc_interval_metrics(
                    obs=obs_values,
                    lower=pd.Series(lower_values, index=target_index),
                    upper=pd.Series(upper_values, index=target_index),
                    alpha=float(alpha),
                    pred_reference=target_work.loc[target_index, "pred"],
                    bin_count=int(bin_count),
                )
            else:
                interval_metrics = {"n": 0, "PICP": None, "MPIW": None, "NMPIW": None, "QCP": None, "IS": None}

            metrics_rows.append({
                "predicted": pred_col,
                "method": method_used,
                "nominal_coverage": float(1 - alpha),
                "alpha": float(alpha),
                "n_calibration": int(len(cal_use)),
                "n_target": int(target_valid.sum()),
                "global_qhat": float(global_qhat),
                "bandwidth": float(bw_value) if bw_value is not None else None,
                "kernel": kernel,
                "coord_source": cal_coord_meta.get("coord_source") if spatial_ready else "none",
                "projected_crs": cal_coord_meta.get("projected_crs") if spatial_ready else None,
                "calibration_dataset": calibration_dataset,
                "target_dataset": target_name,
                "calibration_filter": calibration_filter or None,
                "target_filter": target_filter or None,
                **interval_metrics,
            })
            summary_rows.append({
                "predicted": pred_col,
                "method": method_used,
                "global_qhat": float(global_qhat),
                "n_calibration": int(len(cal_use)),
                "n_target": int(target_valid.sum()),
                "interval_columns": {
                    "radius": radius_col,
                    "lower": lower_col,
                    "upper": upper_col,
                    "covered": cover_col if target_has_obs else None,
                },
            })

        metrics_df = pd.DataFrame(metrics_rows)
        metrics_name = manager.put_table(f"{output_name}_gcp_metrics", metrics_df)
        summary_path = _save_json_artifact(manager, f"{output_name}_gcp_summary", {
            "calibration_dataset": calibration_dataset,
            "target_dataset": target_name,
            "observed_col": observed_col,
            "predicted_cols": pred_cols,
            "date_col": date_col or None,
            "calibration_filter": calibration_filter or None,
            "target_filter": target_filter or None,
            "alpha": float(alpha),
            "calibration_selection": calibration_selection,
            "kernel": kernel,
            "bandwidth": float(bw_value) if bw_value is not None else None,
            "spatial_ready": bool(spatial_ready),
            "coordinate_meta": {
                "calibration": cal_coord_meta,
                "target": target_coord_meta,
            },
            "models": summary_rows,
        })

        if target_gdf is not None:
            result_gdf = target_gdf.copy()
            for col in result_df.columns:
                if col not in result_gdf.columns:
                    result_gdf[col] = result_df[col]
                else:
                    result_gdf[col] = result_df[col]
            saved_name = manager.put_vector(output_name, result_gdf, filename=f"{_artifact_safe_name(output_name)}.geojson")
        else:
            saved_name = manager.put_table(output_name, result_df)

        manager.log_operation("GCP 不确定性分析", f"{calibration_dataset} -> {saved_name}", "analysis")
        model_lines = []
        for row in metrics_rows:
            model_lines.append(
                f"- {row['predicted']}: 方法={row['method']}，PICP={row['PICP'] if row['PICP'] is not None else 'NA'}，MPIW={row['MPIW'] if row['MPIW'] is not None else 'NA'}"
            )
        task_id = f"geographical_conformal_prediction_{uuid4().hex[:10]}"
        model_result_id = generate_model_result_id("GCP", output_name)
        artifacts = [
            ArtifactInfo(
                artifact_id=f"dataset_{uuid4().hex[:10]}",
                path=str(manager.get(saved_name).path),
                type="dataset",
                title=f"{saved_name} GCP intervals",
                description="GCP interval prediction result dataset.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"metrics_{uuid4().hex[:10]}",
                path=str(manager.get(metrics_name).path),
                type="metrics",
                title=f"{metrics_name} GCP metrics",
                description="GCP interval reliability metrics table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"summary_{uuid4().hex[:10]}",
                path=str(summary_path),
                type="summary",
                title=f"{output_name} GCP summary",
                description="GCP configuration and interval column summary.",
                quality_status="created",
                preview_available=False,
            ),
        ]
        artifact_dicts = [item.to_dict() for item in artifacts]
        metrics_payload = metrics_rows[0] if len(metrics_rows) == 1 else {"models": metrics_rows}
        manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=calibration_dataset,
            model_name="GCP",
            output_prefix=output_name,
            result_dataset=saved_name,
            metrics_dataset=metrics_name,
            metrics_path=str(manager.get(metrics_name).path),
            artifact_ids=[str(item.get("artifact_id") or "") for item in artifact_dicts],
            artifacts=artifact_dicts,
            metrics=metrics_payload,
            diagnostics={
                "calibration_dataset": calibration_dataset,
                "target_dataset": target_name,
                "observed_col": observed_col,
                "predicted_cols": pred_cols,
                "spatial_ready": bool(spatial_ready),
                "summary": summary_rows,
            },
        )
        return tool_result_ok(
            "geographical_conformal_prediction",
            inputs=inputs,
            task_id=task_id,
            outputs={
                "model_result_id": model_result_id,
                "result_dataset": saved_name,
                "metrics_dataset": metrics_name,
                "summary_path": str(summary_path),
                "interval_columns": summary_rows,
                "methods": sorted({str(row.get("method") or "") for row in metrics_rows}),
                "spatial_ready": bool(spatial_ready),
            },
            artifacts=artifacts,
            summary=(
                f"GCP uncertainty analysis completed. Result dataset: {saved_name}. "
                f"Metrics dataset: {metrics_name}. "
                f"Spatially adaptive: {'yes' if spatial_ready else 'no, used global split conformal'}."
            ),
            diagnostics={"metrics": metrics_rows, "summary": summary_rows},
            next_actions=["Explain PICP, MPIW, NMPIW, QCP and IS.", "Compare interval reliability with point prediction accuracy."],
        ).to_json()

    @tool
    def btch_fusion_model(
        dataset_name: str,
        product_cols: str,
        output_name: str,
        date_col: str = "",
        window_mode: str = "global",
        group_col: str = "",
        min_samples: int = 20,
    ) -> str:
        """基于多产品误差协方差拟合进行 BTCH 风格加权融合，适合多源土壤水分产品的无真值加权集成与权重分析。"""
        df = _prepare_dataframe(dataset_name, manager).copy()
        products = _parse_columns(product_cols)
        if len(products) < 3:
            raise ValueError("BTCH 融合至少需要 3 个产品列。")
        _validate_columns(df, products)
        if group_col and group_col not in df.columns:
            raise ValueError(f"分组字段不存在: {group_col}")
        df = _coerce_numeric_frame(df, products)

        global_weights: dict[Any, np.ndarray] = {}
        global_info: dict[Any, dict[str, Any]] = {}
        groups = [(None, df)] if not group_col else list(df.groupby(group_col, dropna=False))
        for group_value, sub_df in groups:
            complete = sub_df[products].dropna()
            if len(complete) < max(min_samples, len(products) + 2):
                raise ValueError(f"组 {group_value if group_col else 'all'} 的完整样本不足，无法进行 BTCH 融合。")
            estimate = _estimate_btch_weights(complete.to_numpy(dtype=float))
            global_weights[group_value] = estimate["weights"]
            global_info[group_value] = estimate

        if date_col:
            df["_btch_window"] = _window_labels(df, date_col, window_mode)
        else:
            df["_btch_window"] = "global"
            window_mode = "global"

        weights_rows: list[dict[str, Any]] = []
        fused_series = pd.Series(np.nan, index=df.index, dtype=float)
        if group_col:
            grouped_items = list(df.groupby([group_col, "_btch_window"], dropna=False))
        else:
            grouped_items = [(('all', window), sub_df) for window, sub_df in df.groupby("_btch_window", dropna=False)]

        for key, sub_df in grouped_items:
            group_value = key[0] if group_col else None
            window_value = key[1] if group_col else key[1]
            current_est = global_info[group_value]
            if window_mode != "global":
                complete = sub_df[products].dropna()
                if len(complete) >= max(min_samples, len(products) + 2):
                    try:
                        current_est = _estimate_btch_weights(complete.to_numpy(dtype=float))
                    except Exception:
                        current_est = global_info[group_value]
            weights = current_est["weights"]
            estimate_method = current_est["estimation_method"]
            samples = current_est["samples"]
            fused_series.loc[sub_df.index] = _weighted_row_sum(sub_df[products], weights)
            variances = current_est["variances"]
            for col, weight, variance in zip(products, weights, variances):
                weights_rows.append({
                    "group": group_value if group_col else "all",
                    "window": window_value,
                    "product": col,
                    "weight": float(weight),
                    "estimated_variance": float(variance),
                    "samples": int(samples),
                    "estimation_method": estimate_method,
                })

        result = df.drop(columns=["_btch_window"]).copy()
        pred_col = f"{output_name}_btch"
        result[pred_col] = fused_series
        saved_name = manager.put_table(output_name, result)
        weights_df = pd.DataFrame(weights_rows)
        weight_table_name = manager.put_table(f"{output_name}_btch_weights", weights_df)
        summary_path = _save_json_artifact(manager, f"{output_name}_btch_summary", {
            "dataset": dataset_name,
            "products": products,
            "prediction_column": pred_col,
            "window_mode": window_mode,
            "group_col": group_col or None,
            "global_weights": {str(k if k is not None else 'all'): {col: float(w) for col, w in zip(products, v)} for k, v in global_weights.items()},
        })
        manager.log_operation("BTCH 融合", f"{dataset_name} -> {saved_name}", "model")
        return (
            f"BTCH 融合完成，结果表: {saved_name}，预测列: {pred_col}。\n"
            f"权重表: {weight_table_name}。\n"
            f"摘要文件: {summary_path}"
        )

    @tool
    def train_rf_fusion_model(
        dataset_name: str,
        target_col: str,
        feature_cols: str,
        output_name: str,
        date_col: str = "",
        split_date: str = "",
        n_estimators: int = 300,
        max_depth: int = 12,
        min_samples_leaf: int = 1,
        random_state: int = 42,
    ) -> str:
        """训练随机森林融合模型并输出预测结果、特征重要性和训练/测试精度，适合多源土壤水分回归融合。"""
        inputs = {
            "dataset_name": dataset_name,
            "target_col": target_col,
            "feature_cols": feature_cols,
            "output_name": output_name,
            "date_col": date_col,
            "split_date": split_date,
        }
        errors = validate_dataset_exists(manager, dataset_name)
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        features_for_validation: list[str] = []
        if not errors:
            errors.extend(validate_model_target(manager, dataset_name, target_col))
            try:
                features_for_validation = _parse_columns(feature_cols)
            except Exception as exc:
                errors.append(
                    {
                        "error_code": "FEATURE_FIELDS_MISSING",
                        "error_title": "缺少特征字段",
                        "user_message": "请指定用于随机森林建模的特征字段。",
                        "next_actions": ["从数值字段中选择一个或多个特征字段。", "多个字段可用逗号分隔。"],
                        "diagnostics": {"technical_detail": str(exc)},
                    }
                )
            if features_for_validation:
                errors.extend(validate_required_fields(manager, dataset_name, features_for_validation))
                errors.extend(validate_numeric_fields(manager, dataset_name, features_for_validation))
            if date_col:
                errors.extend(validate_required_fields(manager, dataset_name, [date_col]))
        if errors:
            return _tool_error_from_validation("train_rf_fusion_model", inputs, errors)

        try:
            df = _prepare_dataframe(dataset_name, manager).copy()
        except Exception as exc:
            return _tool_internal_error("train_rf_fusion_model", inputs, exc)
        features = _parse_columns(feature_cols)
        _validate_columns(df, [target_col, *features])
        df = _coerce_numeric_frame(df, [target_col, *features])

        valid_target = df[target_col].notna()
        if date_col and split_date:
            train_mask, test_mask = _split_train_test_by_date(df, date_col, split_date)
        else:
            train_mask = valid_target.copy()
            test_mask = ~train_mask

        fit_mask = valid_target & train_mask
        if int(fit_mask.sum()) < 20:
            return tool_result_error(
                "train_rf_fusion_model",
                inputs=inputs,
                error_code="INSUFFICIENT_TRAINING_SAMPLES",
                error_title="训练样本不足",
                user_message=f"RF 可用于训练的有效样本不足，当前仅 {int(fit_mask.sum())} 条。",
                diagnostics={"valid_training_samples": int(fit_mask.sum()), "minimum_required": 20},
                next_actions=["补充样本或减少缺失值。", "确认目标变量和特征字段是否选择正确。"],
            ).to_json()

        model = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("rf", RandomForestRegressor(
                n_estimators=n_estimators,
                max_depth=max_depth if max_depth > 0 else None,
                min_samples_leaf=min_samples_leaf,
                random_state=random_state,
                n_jobs=-1,
            )),
        ])
        model.fit(df.loc[fit_mask, features], df.loc[fit_mask, target_col])
        pred_col = f"{output_name}_rf"
        df[pred_col] = model.predict(df[features])

        metrics = _summarize_train_test_metrics(df, target_col, pred_col, train_mask & valid_target, test_mask & valid_target if date_col and split_date else None)
        importances = model.named_steps["rf"].feature_importances_
        importance_df = pd.DataFrame({"feature": features, "importance": importances}).sort_values("importance", ascending=False).reset_index(drop=True)

        saved_name = manager.put_table(output_name, df)
        importance_name = manager.put_table(f"{output_name}_rf_importance", importance_df)
        metrics_name = manager.put_table(f"{output_name}_rf_metrics", pd.DataFrame([{"scope": k, **v} for k, v in metrics.items()]))
        model_path = manager.derived_dir / f"{_artifact_safe_name(output_name)}_rf_model.joblib"
        joblib.dump(model, model_path)
        task_id = f"train_rf_fusion_model_{uuid4().hex[:10]}"
        model_result_id = generate_model_result_id("RF", output_name)
        rf_artifact_ids = {
            "dataset": f"dataset_{uuid4().hex[:10]}",
            "metrics": f"metrics_{uuid4().hex[:10]}",
            "importance": f"importance_{uuid4().hex[:10]}",
            "model": f"model_{uuid4().hex[:10]}",
        }
        artifacts = [
            ArtifactInfo(
                artifact_id=rf_artifact_ids["dataset"],
                path=str(manager.get(saved_name).path),
                type="dataset",
                title=f"{saved_name} RF predictions",
                description="Random forest prediction result table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=rf_artifact_ids["metrics"],
                path=str(manager.get(metrics_name).path),
                type="metrics",
                title=f"{metrics_name} metrics",
                description="Random forest accuracy metrics table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=rf_artifact_ids["importance"],
                path=str(manager.get(importance_name).path),
                type="feature_importance",
                title=f"{importance_name} feature importance",
                description="Random forest feature importance table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=rf_artifact_ids["model"],
                path=str(model_path),
                type="model",
                title=f"{output_name} RF model",
                description="Trained random forest model file.",
                quality_status="created",
                preview_available=False,
            ),
        ]
        artifact_dicts = [item.to_dict() for item in artifacts]
        manager.log_operation("RF 融合训练", f"{dataset_name} -> {saved_name}", "model")
        summary = (
            f"RF 模型训练完成，结果表: {saved_name}，预测列: {pred_col}。\n"
            f"特征重要性表: {importance_name}。\n"
            f"精度指标表: {metrics_name}。\n"
            f"模型文件: {model_path}。"
        )
        manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=dataset_name,
            model_name="RF",
            output_prefix=output_name,
            result_dataset=saved_name,
            metrics_dataset=metrics_name,
            metrics_path=str(manager.get(metrics_name).path),
            artifact_ids=list(rf_artifact_ids.values()),
            artifacts=artifact_dicts,
            metrics=metrics.get("overall") if isinstance(metrics.get("overall"), dict) else metrics,
            diagnostics={"metrics": metrics, "features": features, "target_col": target_col},
        )
        return tool_result_ok(
            "train_rf_fusion_model",
            inputs=inputs,
            task_id=task_id,
            outputs={
                "model_result_id": model_result_id,
                "result_dataset": saved_name,
                "prediction_column": pred_col,
                "metrics_dataset": metrics_name,
                "importance_dataset": importance_name,
                "model_path": str(model_path),
            },
            artifacts=artifacts,
            summary=summary,
            diagnostics={"metrics": metrics, "features": features, "target_col": target_col},
            next_actions=["解释 RF 指标和特征重要性。", "检查残差或继续与 XGBoost 结果对比。"],
        ).to_json()
        meta_path = _save_json_artifact(manager, f"{output_name}_rf_summary", {
            "dataset": dataset_name,
            "target_col": target_col,
            "features": features,
            "prediction_column": pred_col,
            "split_date": split_date or None,
            "params": {
                "n_estimators": int(n_estimators),
                "max_depth": int(max_depth),
                "min_samples_leaf": int(min_samples_leaf),
                "random_state": int(random_state),
            },
            "metrics": metrics,
        })
        manager.log_operation("RF 融合训练", f"{dataset_name} -> {saved_name}", "model")
        return (
            f"RF 融合模型训练完成，结果表: {saved_name}，预测列: {pred_col}。\n"
            f"特征重要性表: {importance_name}。\n"
            f"精度指标表: {metrics_name}。\n"
            f"模型文件: {model_path}。\n"
            f"摘要文件: {meta_path}"
        )

    @tool
    def train_xgboost_fusion_model(
        dataset_name: str,
        target_col: str,
        feature_cols: str,
        output_name: str,
        date_col: str = "",
        split_date: str = "",
        n_estimators: int = 500,
        max_depth: int = 6,
        learning_rate: float = 0.05,
        subsample: float = 0.9,
        colsample_bytree: float = 0.9,
        random_state: int = 42,
        spatial_validation: bool = True,
        spatial_block_count: int = 5,
        add_spatial_coordinates: bool = True,
        moran_k_neighbors: int = 8,
        moran_permutations: int = 199,
    ) -> str:
        """训练 XGBoost 回归模型。对点图层会自动保留 geometry、添加空间坐标特征、执行空间分块交叉验证、计算残差 Moran's I，并输出残差空间分布图。"""
        inputs = {
            "dataset_name": dataset_name,
            "target_col": target_col,
            "feature_cols": feature_cols,
            "output_name": output_name,
            "date_col": date_col,
            "split_date": split_date,
            "spatial_validation": spatial_validation,
        }
        errors = validate_dataset_exists(manager, dataset_name)
        features_for_validation: list[str] = []
        if not errors:
            errors.extend(validate_model_target(manager, dataset_name, target_col))
            try:
                features_for_validation = _parse_columns(feature_cols)
            except Exception as exc:
                errors.append(
                    {
                        "error_code": "FEATURE_FIELDS_MISSING",
                        "error_title": "缺少特征字段",
                        "user_message": "请指定用于建模的特征字段。",
                        "next_actions": ["从数值字段中选择一个或多个特征字段。", "多个字段可用逗号分隔。"],
                        "diagnostics": {"technical_detail": str(exc)},
                    }
                )
            if features_for_validation:
                errors.extend(validate_required_fields(manager, dataset_name, features_for_validation))
                errors.extend(validate_numeric_fields(manager, dataset_name, features_for_validation))
            try:
                record_for_validation = manager.get(dataset_name)
                if bool(spatial_validation) and record_for_validation.data_type == "vector":
                    errors.extend(validate_crs(manager, dataset_name))
                    errors.extend(validate_geometry_type(manager, dataset_name, ["Point"]))
            except Exception:
                pass
        errors.extend(validate_output_path(manager.derived_dir, output_name))
        if errors:
            return _tool_error_from_validation("train_xgboost_fusion_model", inputs, errors)

        if XGBRegressor is None:
            return tool_result_error(
                "train_xgboost_fusion_model",
                inputs=inputs,
                error_code="XGBOOST_UNAVAILABLE",
                error_title="XGBoost 依赖不可用",
                user_message="当前 Python 环境未安装 xgboost，无法训练 XGBoost 模型。",
                diagnostics={"dependency": "xgboost"},
                next_actions=["安装 xgboost 后重试。", "或先使用随机森林建模工具。"],
            ).to_json()

        df, source_gdf = _prepare_dataframe_with_geometry(dataset_name, manager)
        features = _parse_columns(feature_cols)
        resolved_columns = _resolve_existing_columns(df, [target_col, *features])
        target_col = resolved_columns[0]
        features = resolved_columns[1:]
        spatial_enabled = bool(spatial_validation and source_gdf is not None)
        spatial_gdf = None
        projected_crs = None

        if spatial_enabled:
            spatial_gdf, projected_crs = _append_spatial_coordinates(source_gdf.copy())
            if add_spatial_coordinates:
                for coord_col in ["__spatial_x__", "__spatial_y__"]:
                    df[coord_col] = spatial_gdf[coord_col]
                    if coord_col not in features:
                        features.append(coord_col)

        _validate_columns(df, [target_col, *features])
        df = _coerce_numeric_frame(df, [target_col, *features])

        valid_target = df[target_col].notna()
        if int(valid_target.sum()) < 20:
            raise ValueError(f"XGBoost 可用于训练的样本不足，当前仅 {int(valid_target.sum())} 条。")

        pred_col = f"{output_name}_xgb"
        cv_pred_col = f"{output_name}_xgb_spatial_cv"
        legacy_cv_pred_col = f"{output_name}_spatial_cv"
        cv_scope_col = f"{output_name}_spatial_cv_scope"
        cv_fold_col = f"{output_name}_spatial_cv_fold"
        cv_available_col = f"{output_name}_spatial_cv_available"
        resid_col = f"{output_name}_residual"
        residual_map_path: Path | None = None
        moran_table_name: str | None = None
        spatial_diag: dict[str, Any] | None = None

        model = _build_xgb_pipeline(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            random_state=random_state,
        )
        model.fit(df.loc[valid_target, features], df.loc[valid_target, target_col])
        df[pred_col] = model.predict(df[features])
        df[legacy_cv_pred_col] = np.nan
        df[cv_scope_col] = pd.Series(pd.NA, index=df.index, dtype="object")
        df[cv_fold_col] = pd.Series(pd.NA, index=df.index, dtype="object")
        df[cv_available_col] = False

        if spatial_enabled and spatial_gdf is not None:
            valid_spatial_gdf = spatial_gdf.loc[valid_target].copy()
            block_series = _make_spatial_blocks(valid_spatial_gdf, n_blocks=spatial_block_count, random_state=random_state)
            unique_blocks = int(block_series.nunique())
            if unique_blocks < 2:
                raise ValueError("空间分块数量不足，无法进行空间交叉验证。")

            df[cv_pred_col] = np.nan
            gkf = GroupKFold(n_splits=unique_blocks)
            valid_index = df.index[valid_target]
            x_valid = df.loc[valid_index, features]
            y_valid = df.loc[valid_index, target_col]
            groups = block_series.loc[valid_index]

            for fold_id, (train_idx, test_idx) in enumerate(gkf.split(x_valid, y_valid, groups=groups), start=1):
                fold_model = _build_xgb_pipeline(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    learning_rate=learning_rate,
                    subsample=subsample,
                    colsample_bytree=colsample_bytree,
                    random_state=random_state + fold_id,
                )
                train_index = valid_index[train_idx]
                test_index = valid_index[test_idx]
                fold_model.fit(df.loc[train_index, features], df.loc[train_index, target_col])
                fold_pred = fold_model.predict(df.loc[test_index, features])
                df.loc[test_index, cv_pred_col] = fold_pred
                df.loc[test_index, legacy_cv_pred_col] = fold_pred
                df.loc[test_index, cv_scope_col] = "holdout"
                df.loc[test_index, cv_fold_col] = int(fold_id)
                df.loc[test_index, cv_available_col] = True

            df[resid_col] = df[target_col] - df[cv_pred_col]
            metrics = {
                "spatial_cv": _calc_metrics(df.loc[valid_target, target_col], df.loc[valid_target, cv_pred_col]),
                "final_model_in_sample": _calc_metrics(df.loc[valid_target, target_col], df.loc[valid_target, pred_col]),
            }
            spatial_diag = _calc_global_moran_i(
                df[resid_col],
                spatial_gdf["__spatial_x__"],
                spatial_gdf["__spatial_y__"],
                k_neighbors=moran_k_neighbors,
                permutations=moran_permutations,
                random_state=random_state,
            )
            spatial_diag.update({
                "validation": "GroupKFold on spatial blocks",
                "spatial_block_count": int(unique_blocks),
                "projected_crs": projected_crs,
                "residual_column": resid_col,
                "cv_prediction_column": cv_pred_col,
                "legacy_cv_prediction_column": legacy_cv_pred_col,
                "cv_scope_column": cv_scope_col,
                "cv_fold_column": cv_fold_col,
            })
        else:
            if date_col and split_date:
                train_mask, test_mask = _split_train_test_by_date(df, date_col, split_date)
                metrics = _summarize_train_test_metrics(df, target_col, pred_col, train_mask & valid_target, test_mask & valid_target)
            else:
                metrics = {"overall": _calc_metrics(df.loc[valid_target, target_col], df.loc[valid_target, pred_col])}
            df[resid_col] = df[target_col] - df[pred_col]

        importances = model.named_steps["xgb"].feature_importances_
        importance_df = pd.DataFrame({"feature": features, "importance": importances}).sort_values("importance", ascending=False).reset_index(drop=True)

        if source_gdf is not None:
            result_gdf = source_gdf.copy()
            for col in df.columns:
                result_gdf[col] = df[col]
            saved_name = manager.put_vector(output_name, result_gdf, filename=f"{_artifact_safe_name(output_name)}.geojson")

            residual_map_path = manager.plot_dir / f"{_artifact_safe_name(output_name)}_residual_map.png"
            residual_plot_gdf = result_gdf.dropna(subset=[resid_col]).copy()
            if not residual_plot_gdf.empty:
                _save_vector_map_plot(residual_plot_gdf, residual_map_path, column=resid_col, title=f"{output_name} residual spatial distribution")
                manager.last_plot_path = str(residual_map_path)
                manager.log_operation("生成残差空间图", f"{output_name} -> {residual_map_path.name}", "plot")
        else:
            saved_name = manager.put_table(output_name, df)

        importance_name = manager.put_table(f"{output_name}_xgb_importance", importance_df)
        metrics_name = manager.put_table(f"{output_name}_xgb_metrics", pd.DataFrame([{"scope": key, **value} for key, value in metrics.items()]))
        if spatial_diag:
            moran_table_name = manager.put_table(f"{output_name}_moran_i", pd.DataFrame([spatial_diag]))
        model_path = manager.derived_dir / f"{_artifact_safe_name(output_name)}_xgb_model.joblib"
        joblib.dump(model, model_path)

        meta_path = _save_json_artifact(manager, f"{output_name}_xgb_summary", {
            "dataset": dataset_name,
            "target_col": target_col,
            "features": features,
            "prediction_column": pred_col,
            "cv_prediction_column": cv_pred_col if cv_pred_col in df.columns else None,
            "legacy_cv_prediction_column": legacy_cv_pred_col if legacy_cv_pred_col in df.columns else None,
            "cv_scope_column": cv_scope_col if cv_scope_col in df.columns else None,
            "cv_fold_column": cv_fold_col if cv_fold_col in df.columns else None,
            "cv_available_column": cv_available_col if cv_available_col in df.columns else None,
            "residual_column": resid_col,
            "split_date": split_date or None,
            "spatial_validation": bool(spatial_enabled),
            "params": {
                "n_estimators": int(n_estimators),
                "max_depth": int(max_depth),
                "learning_rate": float(learning_rate),
                "subsample": float(subsample),
                "colsample_bytree": float(colsample_bytree),
                "random_state": int(random_state),
                "spatial_block_count": int(spatial_block_count),
                "add_spatial_coordinates": bool(add_spatial_coordinates),
            },
            "metrics": metrics,
            "spatial_diagnostics": spatial_diag,
            "residual_map": str(residual_map_path) if residual_map_path else None,
        })
        manager.log_operation("XGBoost 融合训练", f"{dataset_name} -> {saved_name}", "model")

        reply_lines = [
            f"XGBoost 模型训练完成，结果数据集: {saved_name}，预测列: {pred_col}，残差列: {resid_col}。",
            f"特征重要性表: {importance_name}。",
            f"精度指标表: {metrics_name}。",
            f"模型文件: {model_path}。",
            f"摘要文件: {meta_path}。",
        ]
        if moran_table_name is not None:
            reply_lines.append(f"Moran's I 结果表: {moran_table_name}。")
        if residual_map_path is not None:
            reply_lines.append(f"残差空间分布图: {residual_map_path}。")
        if spatial_diag and spatial_diag.get("moran_i") is not None:
            detail = f"残差 Moran's I = {spatial_diag['moran_i']:.4f}"
            if spatial_diag.get("p_value") is not None:
                detail += f"，置换检验 p = {spatial_diag['p_value']:.4f}"
            reply_lines.append(detail + "。")
        artifacts = [
            ArtifactInfo(
                artifact_id=f"dataset_{uuid4().hex[:10]}",
                path=str(manager.get(saved_name).path),
                type="dataset",
                title=f"{saved_name} XGBoost predictions",
                description="XGBoost 预测结果数据集。",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"table_{uuid4().hex[:10]}",
                path=str(manager.get(metrics_name).path),
                type="metrics",
                title=f"{metrics_name} metrics",
                description="XGBoost 精度指标表。",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"table_{uuid4().hex[:10]}",
                path=str(manager.get(importance_name).path),
                type="feature_importance",
                title=f"{importance_name} feature importance",
                description="XGBoost 特征重要性表。",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"model_{uuid4().hex[:10]}",
                path=str(model_path),
                type="model",
                title=f"{output_name} XGBoost model",
                description="训练后的 XGBoost 模型文件。",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"summary_{uuid4().hex[:10]}",
                path=str(meta_path),
                type="summary",
                title=f"{output_name} XGBoost summary",
                description="模型参数、指标和空间诊断摘要。",
                quality_status="created",
                preview_available=False,
            ),
        ]
        if moran_table_name is not None:
            artifacts.append(
                ArtifactInfo(
                    artifact_id=f"moran_{uuid4().hex[:10]}",
                    path=str(manager.get(moran_table_name).path),
                    type="diagnostics",
                    title=f"{moran_table_name} Moran's I",
                    description="残差空间自相关诊断表。",
                    quality_status="created",
                    preview_available=False,
                )
            )
        if residual_map_path is not None:
            artifacts.append(
                ArtifactInfo(
                    artifact_id=f"map_{uuid4().hex[:10]}",
                    path=str(residual_map_path),
                    type="map",
                    title=f"{output_name} residual map",
                    description="残差空间分布图。",
                    quality_status="created",
                    preview_available=True,
                )
            )
        task_id = f"train_xgboost_fusion_model_{uuid4().hex[:10]}"
        model_result_id = generate_model_result_id("XGBoost", output_name)
        artifact_dicts = [item.to_dict() for item in artifacts]
        manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=dataset_name,
            model_name="XGBoost",
            output_prefix=output_name,
            result_dataset=saved_name,
            metrics_dataset=metrics_name,
            metrics_path=str(manager.get(metrics_name).path),
            figure_path=str(residual_map_path) if residual_map_path else "",
            artifact_ids=[str(item.get("artifact_id") or "") for item in artifact_dicts if item.get("artifact_id")],
            artifacts=artifact_dicts,
            metrics=metrics.get("spatial_cv") if isinstance(metrics.get("spatial_cv"), dict) else metrics.get("overall") if isinstance(metrics.get("overall"), dict) else metrics,
            diagnostics={"metrics": metrics, "spatial_diagnostics": spatial_diag, "features": features, "target_col": target_col},
        )
        return tool_result_ok(
            "train_xgboost_fusion_model",
            inputs=inputs,
            task_id=task_id,
            outputs={
                "model_result_id": model_result_id,
                "result_dataset": saved_name,
                "prediction_column": pred_col,
                "residual_column": resid_col,
                "metrics_dataset": metrics_name,
                "importance_dataset": importance_name,
                "moran_dataset": moran_table_name,
                "model_path": str(model_path),
                "summary_path": str(meta_path),
                "residual_map_path": str(residual_map_path) if residual_map_path else "",
            },
            artifacts=artifacts,
            summary="\n".join(reply_lines),
            diagnostics={"metrics": metrics, "spatial_diagnostics": spatial_diag},
            next_actions=["解释模型指标、特征重要性和残差空间分布。", "检查残差是否存在空间聚集，并考虑补充空间特征。"],
        ).to_json()


    @tool
    def train_lstm_fusion_model(
        dataset_name: str,
        target_col: str,
        dynamic_feature_cols: str,
        output_name: str,
        date_col: str,
        group_col: str = "",
        static_feature_cols: str = "",
        seq_len: int = 7,
        split_date: str = "",
        hidden_size: int = 32,
        num_layers: int = 1,
        epochs: int = 40,
        batch_size: int = 64,
        learning_rate: float = 0.001,
    ) -> str:
        """训练 LSTM 时序融合模型并输出预测结果与精度指标，适合刻画土壤水分时间记忆效应和动态变化。"""
        inputs = {
            "dataset_name": dataset_name,
            "target_col": target_col,
            "dynamic_feature_cols": dynamic_feature_cols,
            "output_name": output_name,
            "date_col": date_col,
            "group_col": group_col,
            "static_feature_cols": static_feature_cols,
            "seq_len": seq_len,
            "split_date": split_date,
            "hidden_size": hidden_size,
            "num_layers": num_layers,
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
        }
        dynamic_cols = _parse_columns(dynamic_feature_cols) if str(dynamic_feature_cols or "").strip() else []
        static_cols = _parse_columns(static_feature_cols) if static_feature_cols.strip() else []
        validation_errors: list[dict[str, Any]] = []
        validation_errors.extend(validate_dataset_exists(manager, dataset_name))
        validation_errors.extend(validate_model_target(manager, dataset_name, target_col))
        validation_errors.extend(validate_required_fields(manager, dataset_name, [date_col] if str(date_col or "").strip() else []))
        validation_errors.extend(validate_required_fields(manager, dataset_name, dynamic_cols + static_cols))
        validation_errors.extend(validate_numeric_fields(manager, dataset_name, dynamic_cols + static_cols))
        validation_errors.extend(validate_output_path(manager.derived_dir, output_name))
        if not dynamic_cols:
            validation_errors.append({
                "error_code": "LSTM_DYNAMIC_FIELDS_MISSING",
                "error_title": "Missing dynamic feature fields",
                "user_message": "LSTM requires at least one dynamic feature field.",
                "next_actions": ["Provide time-varying numeric fields, for example precipitation, temperature or remote sensing variables."],
                "diagnostics": {},
            })
        if seq_len < 2:
            validation_errors.append({
                "error_code": "LSTM_SEQ_LEN_TOO_SMALL",
                "error_title": "Invalid sequence length",
                "user_message": "seq_len must be at least 2 for LSTM training.",
                "next_actions": ["Use seq_len=7 or another sequence length greater than 1."],
                "diagnostics": {"seq_len": seq_len},
            })
        if validation_errors:
            first = first_error(validation_errors) or {}
            return tool_result_error(
                "train_lstm_fusion_model",
                inputs=inputs,
                error_code=str(first.get("error_code") or "LSTM_PRECONDITION_FAILED"),
                error_title=str(first.get("error_title") or "LSTM precondition failed"),
                user_message=str(first.get("user_message") or "LSTM inputs are incomplete or invalid."),
                diagnostics=validation_diagnostics(validation_errors),
                next_actions=merge_next_actions(validation_errors),
                technical_detail=str(first.get("technical_detail") or ""),
            ).to_json()
        df = _prepare_dataframe(dataset_name, manager).copy()
        _validate_columns(df, [target_col, date_col, *dynamic_cols, *static_cols])

        seq_data = _build_lstm_sequences(
            df=df,
            date_col=date_col,
            target_col=target_col,
            dynamic_cols=dynamic_cols,
            static_cols=static_cols,
            group_col=group_col,
            seq_len=seq_len,
        )
        x_dyn = seq_data["x_dynamic"]
        x_sta = seq_data["x_static"]
        y = seq_data["y"]
        seq_dates = seq_data["dates"]
        orig_index = seq_data["orig_index"]

        if split_date:
            split_ts = pd.to_datetime(split_date, errors="coerce")
            if pd.isna(split_ts):
                raise ValueError(f"split_date 无法解析为日期: {split_date}")
            train_mask = seq_dates <= split_ts
            test_mask = seq_dates > split_ts
        else:
            train_mask = pd.Series([True] * len(seq_dates))
            test_mask = pd.Series([False] * len(seq_dates))

        if int(train_mask.sum()) < max(20, seq_len * 2):
            return tool_result_error(
                "train_lstm_fusion_model",
                inputs=inputs,
                error_code="LSTM_TRAINING_SAMPLE_TOO_SMALL",
                error_title="Training sample too small",
                user_message=f"LSTM has only {int(train_mask.sum())} usable sequence samples for training.",
                diagnostics={"usable_training_sequences": int(train_mask.sum()), "required_minimum": int(max(20, seq_len * 2))},
                next_actions=["Use a longer time series.", "Reduce seq_len if appropriate.", "Check missing values in target and dynamic feature fields."],
            ).to_json()

        x_dyn_train = x_dyn[train_mask.to_numpy()]
        x_sta_train = x_sta[train_mask.to_numpy()]
        y_train = y[train_mask.to_numpy()]

        dyn_mean = x_dyn_train.mean(axis=(0, 1), keepdims=True)
        dyn_std = x_dyn_train.std(axis=(0, 1), keepdims=True)
        dyn_std = np.where(dyn_std < 1e-6, 1.0, dyn_std)
        x_dyn_scaled = (x_dyn - dyn_mean) / dyn_std

        if static_cols:
            sta_mean = x_sta_train.mean(axis=0, keepdims=True)
            sta_std = x_sta_train.std(axis=0, keepdims=True)
            sta_std = np.where(sta_std < 1e-6, 1.0, sta_std)
            x_sta_scaled = (x_sta - sta_mean) / sta_std
        else:
            sta_mean = np.zeros((1, 0), dtype=np.float32)
            sta_std = np.ones((1, 0), dtype=np.float32)
            x_sta_scaled = x_sta

        y_mean = float(y_train.mean())
        y_std = float(y_train.std()) if float(y_train.std()) >= 1e-6 else 1.0
        y_scaled = (y - y_mean) / y_std

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = _FusionLSTM(dynamic_dim=len(dynamic_cols), static_dim=len(static_cols), hidden_size=hidden_size, num_layers=num_layers).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        loss_fn = nn.MSELoss()

        train_dataset = TensorDataset(
            torch.tensor(x_dyn_scaled[train_mask.to_numpy()], dtype=torch.float32),
            torch.tensor(x_sta_scaled[train_mask.to_numpy()], dtype=torch.float32),
            torch.tensor(y_scaled[train_mask.to_numpy()], dtype=torch.float32),
        )
        train_loader = DataLoader(train_dataset, batch_size=min(batch_size, len(train_dataset)), shuffle=True)

        history_rows: list[dict[str, Any]] = []
        model.train()
        for epoch in range(1, epochs + 1):
            running = 0.0
            seen = 0
            for batch_dyn, batch_sta, batch_y in train_loader:
                batch_dyn = batch_dyn.to(device)
                batch_sta = batch_sta.to(device)
                batch_y = batch_y.to(device)
                optimizer.zero_grad()
                pred = model(batch_dyn, batch_sta if batch_sta.shape[1] > 0 else None)
                loss = loss_fn(pred, batch_y)
                loss.backward()
                optimizer.step()
                running += float(loss.item()) * len(batch_y)
                seen += len(batch_y)
            history_rows.append({"epoch": epoch, "train_mse": running / max(seen, 1)})

        model.eval()
        with torch.no_grad():
            pred_scaled = model(
                torch.tensor(x_dyn_scaled, dtype=torch.float32, device=device),
                torch.tensor(x_sta_scaled, dtype=torch.float32, device=device) if len(static_cols) else None,
            ).detach().cpu().numpy()
        pred_values = pred_scaled * y_std + y_mean

        result_df = df.copy()
        pred_col = f"{output_name}_lstm"
        result_df[pred_col] = np.nan
        for idx, pred_value in zip(orig_index, pred_values):
            result_df.loc[idx, pred_col] = float(pred_value)

        row_train_mask = pd.Series(False, index=result_df.index)
        row_test_mask = pd.Series(False, index=result_df.index)
        row_train_mask.loc[orig_index[train_mask.to_numpy()]] = True
        row_test_mask.loc[orig_index[test_mask.to_numpy()]] = True
        metrics = _summarize_train_test_metrics(result_df, target_col, pred_col, row_train_mask, row_test_mask if split_date else None)

        saved_name = manager.put_table(output_name, result_df)
        history_name = manager.put_table(f"{output_name}_lstm_history", pd.DataFrame(history_rows))
        metrics_name = manager.put_table(f"{output_name}_lstm_metrics", pd.DataFrame([{"scope": k, **v} for k, v in metrics.items()]))
        model_path = manager.derived_dir / f"{_artifact_safe_name(output_name)}_lstm_model.pt"
        torch.save({
            "state_dict": model.state_dict(),
            "dynamic_cols": dynamic_cols,
            "static_cols": static_cols,
            "target_col": target_col,
            "seq_len": int(seq_len),
            "hidden_size": int(hidden_size),
            "num_layers": int(num_layers),
            "dyn_mean": dyn_mean.tolist(),
            "dyn_std": dyn_std.tolist(),
            "sta_mean": sta_mean.tolist(),
            "sta_std": sta_std.tolist(),
            "y_mean": y_mean,
            "y_std": y_std,
        }, model_path)
        meta_path = _save_json_artifact(manager, f"{output_name}_lstm_summary", {
            "dataset": dataset_name,
            "target_col": target_col,
            "dynamic_cols": dynamic_cols,
            "static_cols": static_cols,
            "date_col": date_col,
            "group_col": group_col or None,
            "seq_len": int(seq_len),
            "prediction_column": pred_col,
            "split_date": split_date or None,
            "params": {
                "hidden_size": int(hidden_size),
                "num_layers": int(num_layers),
                "epochs": int(epochs),
                "batch_size": int(batch_size),
                "learning_rate": float(learning_rate),
            },
            "metrics": metrics,
            "sequence_count": int(len(orig_index)),
        })
        manager.log_operation("LSTM 融合训练", f"{dataset_name} -> {saved_name}", "model")
        task_id = f"train_lstm_fusion_model_{uuid4().hex[:10]}"
        model_result_id = generate_model_result_id("LSTM", output_name)
        artifacts = [
            ArtifactInfo(
                artifact_id=f"dataset_{uuid4().hex[:10]}",
                path=str(manager.get(saved_name).path),
                type="dataset",
                title=f"{saved_name} LSTM predictions",
                description="LSTM prediction result table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"history_{uuid4().hex[:10]}",
                path=str(manager.get(history_name).path),
                type="training_history",
                title=f"{history_name} training history",
                description="LSTM training loss history.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"metrics_{uuid4().hex[:10]}",
                path=str(manager.get(metrics_name).path),
                type="metrics",
                title=f"{metrics_name} metrics",
                description="LSTM accuracy metrics table.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"model_{uuid4().hex[:10]}",
                path=str(model_path),
                type="model",
                title=f"{output_name} LSTM model",
                description="Trained LSTM model checkpoint.",
                quality_status="created",
                preview_available=False,
            ),
            ArtifactInfo(
                artifact_id=f"summary_{uuid4().hex[:10]}",
                path=str(meta_path),
                type="summary",
                title=f"{output_name} LSTM summary",
                description="LSTM configuration and metrics summary.",
                quality_status="created",
                preview_available=False,
            ),
        ]
        artifact_dicts = [item.to_dict() for item in artifacts]
        manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=dataset_name,
            model_name="LSTM",
            output_prefix=output_name,
            result_dataset=saved_name,
            metrics_dataset=metrics_name,
            metrics_path=str(manager.get(metrics_name).path),
            artifact_ids=[str(item.get("artifact_id") or "") for item in artifact_dicts],
            artifacts=artifact_dicts,
            metrics=metrics.get("test") if isinstance(metrics.get("test"), dict) else metrics.get("train") if isinstance(metrics.get("train"), dict) else metrics,
            diagnostics={
                "metrics": metrics,
                "dynamic_cols": dynamic_cols,
                "static_cols": static_cols,
                "target_col": target_col,
                "date_col": date_col,
                "sequence_count": int(len(orig_index)),
            },
        )
        return tool_result_ok(
            "train_lstm_fusion_model",
            inputs=inputs,
            task_id=task_id,
            outputs={
                "model_result_id": model_result_id,
                "result_dataset": saved_name,
                "prediction_column": pred_col,
                "history_dataset": history_name,
                "metrics_dataset": metrics_name,
                "model_path": str(model_path),
                "summary_path": str(meta_path),
            },
            artifacts=artifacts,
            summary=f"LSTM model training completed. Result dataset: {saved_name}. Metrics dataset: {metrics_name}.",
            diagnostics={"metrics": metrics, "sequence_count": int(len(orig_index))},
            next_actions=["Explain LSTM train/test metrics.", "Compare LSTM with RF/XGBoost and consider GCP uncertainty analysis."],
        ).to_json()

    @tool
    def generate_thesis_charts(
        dataset_name: str,
        chart_type: str,
        output_prefix: str,
        x_col: str = "",
        y_cols: str = "",
        observed_col: str = "",
        group_col: str = "",
        metrics_cols: str = "R,RMSE,ubRMSE,NSE",
        title: str = "",
        top_n: int = 12,
    ) -> str:
        """自动生成适合论文使用的对比图、精度图、观测-预测散点图、BTCH 权重图和特征重要性图，并附带图注草稿。"""
        dataset_used = dataset_name
        df = _prepare_dataframe(dataset_used, manager).copy()
        chart_key = chart_type.strip().lower()
        files: list[str] = []
        captions: list[str] = []
        requested_metrics = _parse_columns(metrics_cols) if metrics_cols.strip() else []
        metrics_list, metric_family = _infer_metric_columns(df, requested=requested_metrics)
        if not metrics_list:
            fallback_requested = requested_metrics or STANDARD_METRIC_COLUMNS
            metrics_list = [col for col in fallback_requested if col in df.columns]

        def _switch_dataset_for_columns(required_cols: list[str]) -> None:
            nonlocal df, dataset_used, metrics_list, metric_family
            required = [str(col).strip() for col in required_cols if str(col).strip()]
            if not required:
                return
            missing = [col for col in required if col not in df.columns]
            if not missing:
                return
            alt_dataset = _find_dataset_with_columns(manager, required, current_dataset=dataset_used)
            if not alt_dataset:
                return
            dataset_used = alt_dataset
            df = _prepare_dataframe(dataset_used, manager).copy()
            metrics_list, metric_family = _infer_metric_columns(df, requested=requested_metrics)
            if not metrics_list:
                fallback_requested = requested_metrics or STANDARD_METRIC_COLUMNS
                metrics_list = [col for col in fallback_requested if col in df.columns]

        def _resolved_scatter_fields() -> tuple[str, list[str]]:
            requested = _parse_columns(y_cols)
            if observed_col.strip():
                requested.append(observed_col.strip())
            _switch_dataset_for_columns(requested)
            cols = _resolve_existing_columns(df, _parse_columns(y_cols))
            obs = _infer_observed_column(df, explicit_observed=observed_col, predicted_cols=cols)
            return obs, cols

        def _save_current(fig, suffix: str) -> str:
            path = manager.plot_dir / f"{_artifact_safe_name(output_prefix)}_{suffix}.png"
            fig.savefig(path, dpi=260, bbox_inches="tight")
            plt.close(fig)
            manager.last_plot_path = str(path)
            files.append(str(path))
            return str(path)

        def _render_time_series() -> None:
            cols = _parse_columns(y_cols)
            x_name = x_col or "date"
            _switch_dataset_for_columns([x_name, *cols])
            _validate_columns(df, cols)
            series = _ensure_datetime(df, x_name)
            work = df.copy()
            work[x_name] = series
            for col in cols:
                work[col] = pd.to_numeric(work[col], errors="coerce")
            grouped = work.groupby(x_name, dropna=False)[cols].mean().reset_index().sort_values(x_name)
            fig, ax = plt.subplots(figsize=(10, 6))
            for col in cols:
                ax.plot(grouped[x_name], grouped[col], linewidth=1.8, label=col)
            ax.set_title(_safe_map_title(title or f"{dataset_name} time series"))
            ax.set_xlabel(x_name)
            ax.set_ylabel("Value")
            ax.grid(alpha=0.25)
            ax.legend()
            _save_current(fig, "time_series")
            captions.append(f"图：{dataset_name} 中 {', '.join(cols)} 的时间序列对比。图中展示各变量在研究期内的平均时序变化，可用于论文中的时间维度比较分析。")

        def _render_metric_bar() -> None:
            work = _ensure_metric_predicted_column(df, dataset_name=dataset_name)
            local_metrics, local_family = _infer_metric_columns(work, requested=metrics_list)
            needed = ["predicted", *local_metrics]
            _validate_columns(work, needed)
            if group_col and group_col in work.columns:
                work[group_col] = work[group_col].astype(str)
                group_values = list(work[group_col].dropna().astype(str).unique())
                if group_values:
                    work = work[work[group_col].astype(str) == group_values[0]].copy()
            lower_is_better = {"RMSE", "UBRMSE", "BIAS", "MAE", "MPIW", "NMPIW", "QCP", "IS"}
            for metric in local_metrics:
                fig, ax = plt.subplots(figsize=(9.5, 5.8))
                plot_df = work[["predicted", metric]].copy().dropna().sort_values(metric, ascending=(metric.upper() in lower_is_better))
                ax.bar(plot_df["predicted"].astype(str), plot_df[metric])
                ax.set_title(_safe_map_title(title or f"{metric} comparison"))
                ax.set_xlabel("Model / Product")
                ax.set_ylabel(metric)
                ax.tick_params(axis="x", rotation=30)
                ax.grid(alpha=0.2, axis="y")
                _save_current(fig, f"metric_{metric.lower()}")
                if local_family == 'gcp':
                    captions.append(f"图：不同产品/模型的 {metric} 区间预测指标对比。该图用于比较 GCP 不确定性分析中的覆盖率、区间宽度或区间评分表现。")
                else:
                    captions.append(f"图：不同产品/模型的 {metric} 对比。该图用于比较 {metric} 指标上的优劣，可直接用于总体精度分析部分。")

        def _render_obs_pred_scatter() -> None:
            obs_col, cols = _resolved_scatter_fields()
            _validate_columns(df, [obs_col, *cols])
            work = _coerce_numeric_frame(df, [obs_col, *cols])
            for col in cols:
                paired = work[[obs_col, col]].dropna()
                if paired.empty:
                    continue
                fig, ax = plt.subplots(figsize=(6.6, 6.2))
                ax.scatter(paired[obs_col], paired[col], alpha=0.65, s=16)
                min_v = float(np.nanmin([paired[obs_col].min(), paired[col].min()]))
                max_v = float(np.nanmax([paired[obs_col].max(), paired[col].max()]))
                ax.plot([min_v, max_v], [min_v, max_v], linestyle="--", linewidth=1.2)
                metric = _calc_metrics(paired[obs_col], paired[col])
                ax.set_title(_safe_map_title(title or f"{col} vs {obs_col}"))
                ax.set_xlabel(obs_col)
                ax.set_ylabel(col)
                ax.grid(alpha=0.2)
                ax.text(0.03, 0.97, f"R={metric['R']:.3f}\nRMSE={metric['RMSE']:.3f}", transform=ax.transAxes, va="top")
                _save_current(fig, f"scatter_{_artifact_safe_name(col)}")
                captions.append(f"图：{col} 与 {obs_col} 的散点对比及 1:1 参考线。该图可用于说明模型/产品对观测值的一致性与离散程度。")

        def _render_feature_importance() -> None:
            feature_col = x_col or "feature"
            value_col = _parse_columns(y_cols)[0] if y_cols.strip() else "importance"
            _switch_dataset_for_columns([feature_col, value_col])
            _validate_columns(df, [feature_col, value_col])
            work = df[[feature_col, value_col]].copy().dropna().sort_values(value_col, ascending=False).head(top_n)
            fig, ax = plt.subplots(figsize=(9.5, 5.8))
            ax.barh(work[feature_col].astype(str)[::-1], work[value_col].astype(float)[::-1])
            ax.set_title(_safe_map_title(title or "Feature importance"))
            ax.set_xlabel(value_col)
            ax.set_ylabel(feature_col)
            ax.grid(alpha=0.2, axis="x")
            _save_current(fig, "feature_importance")
            captions.append("图：模型特征重要性排序。该图用于识别对融合结果贡献较高的变量，可用于解释 RF/XGBoost 模型的主要驱动因子。")

        def _render_btch_weights() -> None:
            _validate_columns(df, ["window", "product", "weight"])
            work = df.copy()
            work["window"] = work["window"].astype(str)
            work["weight"] = pd.to_numeric(work["weight"], errors="coerce")
            order = sorted(work["window"].dropna().unique().tolist())
            fig, ax = plt.subplots(figsize=(10, 6))
            for product, sub in work.groupby("product", dropna=False):
                sub = sub.sort_values("window", key=lambda s: s.map({v: i for i, v in enumerate(order)}))
                ax.plot(sub["window"], sub["weight"], marker="o", linewidth=1.6, label=str(product))
            ax.set_title(_safe_map_title(title or "BTCH weight dynamics"))
            ax.set_xlabel("Window")
            ax.set_ylabel("Weight")
            ax.tick_params(axis="x", rotation=30)
            ax.grid(alpha=0.25)
            ax.legend()
            _save_current(fig, "btch_weights")
            captions.append("图：BTCH 融合中各产品权重随时间窗口的变化。该图可用于讨论不同产品在不同时段的相对可信度及其季节性特征。")

        def _pick_spatial_column(preferred_mode: str = "auto") -> str:
            available_df = _prepare_dataframe(dataset_used, manager).copy()
            candidates: list[str] = []
            if y_cols.strip():
                try:
                    candidates.extend(_resolve_existing_columns(available_df, _parse_columns(y_cols)))
                except Exception:
                    pass
            if x_col.strip() and x_col in available_df.columns:
                candidates.append(x_col)

            mode_order = []
            if preferred_mode == "residual":
                mode_order = ["_residual", "residual", "_gcp_radius", "_gcp_width", "_gcp_upper", "_gcp_lower"]
            elif preferred_mode == "prediction":
                mode_order = ["_xgb", "_rf", "_btch", "_lstm", "prediction", "_spatial_cv"]
            else:
                mode_order = ["_residual", "_gcp_radius", "_gcp_width", "_xgb", "_rf", "_btch", "_lstm", "prediction", "_spatial_cv"]

            for suffix in mode_order:
                for col in available_df.columns:
                    lowered = str(col).lower()
                    if suffix in lowered:
                        candidates.append(str(col))

            seen = set()
            ordered = []
            for col in candidates:
                if col not in seen:
                    seen.add(col)
                    ordered.append(col)

            for col in ordered:
                numeric = pd.to_numeric(available_df[col], errors="coerce")
                if numeric.notna().any():
                    return col
            raise ValueError("spatial_distribution 需要提供可映射的数值字段，或结果数据集中应包含 residual / prediction / gcp 等数值列。")

        def _render_spatial_distribution(preferred_mode: str = "auto") -> None:
            _, gdf = _prepare_dataframe_with_geometry(dataset_used, manager)
            if gdf is None:
                raise ValueError("spatial_distribution / residual_map 需要矢量数据集。")
            value_col = _pick_spatial_column(preferred_mode=preferred_mode)
            plot_gdf = gdf.copy()
            plot_gdf[value_col] = pd.to_numeric(plot_gdf[value_col], errors="coerce")
            plot_gdf = plot_gdf.dropna(subset=[value_col]).copy()
            if plot_gdf.empty:
                raise ValueError(f"字段 {value_col} 没有可用于空间分布图的有效数值。")
            path = manager.plot_dir / f"{_artifact_safe_name(output_prefix)}_{_artifact_safe_name(value_col)}_spatial_distribution.png"
            _save_vector_map_plot(plot_gdf, path, column=value_col, title=_safe_map_title(title or f"{dataset_used} spatial distribution of {value_col}"))
            manager.last_plot_path = str(path)
            files.append(str(path))
            captions.append(f"图：{value_col} 的空间分布图。该图用于展示预测值、残差或不确定性指标在空间上的异质性，可直接用于论文中的空间格局分析。")

        def _render_group_box() -> None:
            cols = _parse_columns(y_cols)
            _switch_dataset_for_columns([group_col, *cols])
            _validate_columns(df, [group_col, *cols])
            work = df.copy()
            work[group_col] = work[group_col].astype(str)
            for col in cols:
                plot_df = work[[group_col, col]].copy().dropna()
                groups = [sub[col].astype(float).tolist() for _, sub in plot_df.groupby(group_col)]
                labels = [str(k) for k, _ in plot_df.groupby(group_col)]
                fig, ax = plt.subplots(figsize=(9.5, 5.8))
                ax.boxplot(groups, labels=labels, showfliers=False)
                ax.set_title(_safe_map_title(title or f"{col} by {group_col}"))
                ax.set_xlabel(group_col)
                ax.set_ylabel(col)
                ax.tick_params(axis="x", rotation=25)
                ax.grid(alpha=0.2, axis="y")
                _save_current(fig, f"box_{_artifact_safe_name(col)}")
                captions.append(f"图：{col} 在不同 {group_col} 分组下的箱线图。该图适合用于空间分区或地类分组差异分析。")

        if chart_key == "time_series":
            _render_time_series()
        elif chart_key == "metric_bar":
            _render_metric_bar()
        elif chart_key == "obs_pred_scatter":
            _render_obs_pred_scatter()
        elif chart_key == "feature_importance":
            _render_feature_importance()
        elif chart_key == "btch_weights":
            _render_btch_weights()
        elif chart_key == "group_box":
            if not group_col:
                raise ValueError("group_box 需要提供 group_col。")
            _render_group_box()
        elif chart_key in {"spatial_distribution", "spatial_map", "residual_map", "residual_spatial", "prediction_map"}:
            preferred_mode = "auto"
            if chart_key in {"residual_map", "residual_spatial"}:
                preferred_mode = "residual"
            elif chart_key == "prediction_map":
                preferred_mode = "prediction"
            _render_spatial_distribution(preferred_mode=preferred_mode)
        elif chart_key == "auto_pack":
            if y_cols.strip():
                try:
                    _resolved_scatter_fields()
                    _render_obs_pred_scatter()
                    if x_col:
                        _render_time_series()
                except Exception:
                    pass
            metric_like_cols = set(STANDARD_METRIC_COLUMNS + GCP_METRIC_COLUMNS)
            if not files and len(metric_like_cols.intersection(set(df.columns))) >= 2:
                _render_metric_bar()
            elif not files and {"feature", "importance"}.issubset(df.columns):
                _render_feature_importance()
            elif {"window", "product", "weight"}.issubset(df.columns):
                _render_btch_weights()
            else:
                try:
                    _, gdf = _prepare_dataframe_with_geometry(dataset_used, manager)
                except Exception:
                    gdf = None
                if gdf is not None:
                    _render_spatial_distribution(preferred_mode="auto")
                else:
                    raise ValueError("auto_pack 未能从当前表结构推断图表类型，请显式指定 chart_type。")
        else:
            raise ValueError("chart_type 目前支持 time_series、metric_bar、obs_pred_scatter、feature_importance、btch_weights、group_box、spatial_distribution、spatial_map、residual_map、prediction_map、auto_pack。")

        if not files:
            raise ValueError("没有生成任何图件，请检查输入字段和数据有效性。")

        caption_text = "# 论文图表草稿\n\n" + "\n\n".join(f"{idx + 1}. {cap}" for idx, cap in enumerate(captions))
        caption_path = _save_markdown_artifact(manager, f"{output_prefix}_figure_notes", caption_text)
        manager.log_operation("论文图表生成", f"{dataset_used} -> {len(files)} files", "plot")
        return f"论文图表生成完成，共 {len(files)} 个 PNG。图件: {files}。图注草稿: {caption_path}"


    @tool
    def generate_stage_report(
        stage: str,
        output_prefix: str = "stage_pack",
        topic: str = "",
        research_document: str = "",
        metrics_dataset: str = "",
        gcp_metrics_dataset: str = "",
        feature_importance_dataset: str = "",
        btch_weights_dataset: str = "",
        figure_notes_document: str = "",
    ) -> str:
        """生成开题/中期/答辩一体化阶段材料，包括阶段报告、汇报提纲、答辩问答库和材料清单。stage 支持 proposal/opening、midterm、defense。"""
        stage_key = stage.strip().lower()
        aliases = {
            "opening": "proposal", "open": "proposal", "proposal": "proposal", "开题": "proposal",
            "midterm": "midterm", "mid": "midterm", "中期": "midterm",
            "defense": "defense", "答辩": "defense",
        }
        if stage_key not in aliases:
            raise ValueError("stage 仅支持 proposal/opening、midterm、defense。")
        stage_key = aliases[stage_key]

        if not research_document:
            research_document = _find_dataset_by_keywords(manager, ["开题"], {"document"}) or _find_dataset_by_keywords(manager, ["report"], {"document"}) or ""
        if not metrics_dataset:
            metrics_dataset = _find_dataset_by_keywords(manager, ["metrics"], {"table"}) or _find_dataset_by_keywords(manager, ["accuracy"], {"table"}) or ""
        if not gcp_metrics_dataset:
            gcp_metrics_dataset = _find_dataset_by_keywords(manager, ["gcp", "metrics"], {"table"}) or ""
        if not feature_importance_dataset:
            feature_importance_dataset = _find_dataset_by_keywords(manager, ["importance"], {"table"}) or ""
        if not btch_weights_dataset:
            btch_weights_dataset = _find_dataset_by_keywords(manager, ["btch", "weight"], {"table"}) or _find_dataset_by_keywords(manager, ["weights"], {"table"}) or ""
        if not figure_notes_document:
            figure_notes_document = _find_dataset_by_keywords(manager, ["figure", "notes"], {"document"}) or ""

        doc_text = manager.get_document_text(research_document) if research_document else ""
        doc_preview = doc_text[:2400].strip()
        topic_text = _first_nonempty_text(topic, "基于多源遥感的流域表层土壤水分数据融合及模型比较研究")
        datasets = manager.list_datasets()
        artifacts = manager.list_artifacts()

        metrics_md = ""
        metric_highlights: dict[str, Any] = {}
        if metrics_dataset:
            metrics_df = _prepare_dataframe(metrics_dataset, manager)
            metric_highlights = _extract_metric_highlights(metrics_df, dataset_name=metrics_dataset)
            metrics_md = _table_markdown(metrics_df)

        gcp_metrics_md = ""
        gcp_highlights: dict[str, Any] = {}
        if gcp_metrics_dataset:
            gcp_metrics_df = _prepare_dataframe(gcp_metrics_dataset, manager)
            gcp_highlights = _extract_metric_highlights(gcp_metrics_df, dataset_name=gcp_metrics_dataset)
            gcp_metrics_md = _table_markdown(gcp_metrics_df)

        importance_md = ""
        feature_highlights: list[dict[str, Any]] = []
        if feature_importance_dataset:
            importance_df = _prepare_dataframe(feature_importance_dataset, manager)
            feature_highlights = _extract_feature_highlights(importance_df)
            importance_md = _table_markdown(importance_df)

        btch_md = ""
        btch_highlights: dict[str, Any] = {}
        if btch_weights_dataset:
            btch_df = _prepare_dataframe(btch_weights_dataset, manager)
            btch_highlights = _extract_btch_highlights(btch_df)
            btch_md = _table_markdown(btch_df)

        figure_notes_text, figure_notes_source = _resolve_document_text_input(manager, figure_notes_document) if figure_notes_document else ("", "")
        figure_notes = figure_notes_text[:2000]
        recent_pngs = _recent_artifact_paths(manager, {".png"}, limit=10)
        recent_docs = _recent_artifact_paths(manager, {".md", ".txt", ".json", ".csv"}, limit=12)

        dataset_overview = pd.DataFrame([
            {"name": item["name"], "type": item["type"], "path": item["path"]} for item in datasets
        ]) if datasets else pd.DataFrame(columns=["name", "type", "path"])
        artifact_overview = pd.DataFrame([
            {"name": item["name"], "category": item["category"], "path": item["path"]} for item in artifacts[:16]
        ]) if artifacts else pd.DataFrame(columns=["name", "category", "path"])

        stage_titles = {"proposal": "开题阶段", "midterm": "中期检查阶段", "defense": "答辩阶段"}
        common_header = (
            f"# {topic_text}{stage_titles[stage_key]}材料包\n\n"
            f"- 阶段：{stage_titles[stage_key]}\n"
            f"- 研究主题：{topic_text}\n"
            f"- 工作区数据集数量：{len(datasets)}\n"
            f"- 工作区成果文件数量：{len(artifacts)}\n"
            f"- 点预测精度表：{metrics_dataset or '未指定'}\n"
            f"- GCP 不确定性表：{gcp_metrics_dataset or '未指定'}\n\n"
        )

        if stage_key == "proposal":
            report_parts = [
                common_header,
                "## 1. 研究背景与选题意义\n" ,
                (doc_preview or "请结合研究区背景、土壤水分的重要性、多源遥感产品的互补性来补充该部分。") + "\n\n" ,
                "## 2. 拟解决的核心问题\n"
                "- 如何在统一空间边界、统一深度和统一时间尺度下整合多源土壤水分产品。\n"
                "- 如何比较 BTCH、RF、XGBoost 与 LSTM 在流域尺度上的适用性。\n"
                "- 如何从总体、时间和空间维度完成独立验证与论文表达。\n"
                "- 如何联合汇报点预测精度与 GCP 不确定性结果。\n\n" ,
                "## 3. 数据基础与预处理计划\n" + _table_markdown(dataset_overview, 20) + "\n\n" ,
                "## 4. 方法路线\n"
                "1. 站点—栅格配准与时间对齐。\n"
                "2. 缺失值检查与时序特征构建。\n"
                "3. BTCH、RF、XGBoost、LSTM 建模。\n"
                "4. 按 2019 训练、2020 验证开展时间外推检验。\n"
                "5. 生成点预测图表与 GCP 区间结果分析。\n\n" ,
                "## 5. 预期成果\n"
                "- 融合结果表与精度评价表。\n"
                "- 权重变化图、特征重要性图、观测-预测散点图。\n"
                "- GCP 指标表与不确定性比较结果。\n"
                "- 开题、中期、答辩三阶段可复用材料模板。\n\n" ,
                "## 6. 风险点与应对\n"
                "- 缺失值过多：优先做站点—栅格配准后的可用性评估。\n"
                "- 时间交集不足：统一交集时间窗并记录删减规则。\n"
                "- 模型泛化不足：坚持时间外推验证，避免随机混洗替代独立验证。\n"
                "- 汇报混淆：将点预测精度和 GCP 不确定性分成两类图表与表格分别表述。\n" ,
            ]
            report = "".join(report_parts)
            outline = (
                "# 开题汇报提纲\n\n"
                "1. 选题背景与意义\n"
                "2. 国内外研究现状与不足\n"
                "3. 数据来源与研究区\n"
                "4. 技术路线与关键方法（BTCH/RF/XGBoost/LSTM/GCP）\n"
                "5. 进度安排与预期成果\n"
                "6. 风险点与可行性说明\n"
            )
            qa = (
                "# 开题常见问题与回答提纲\n\n"
                "1. 为什么选择该流域？\n- 因为其生态脆弱、水文敏感，且已有站网支撑独立验证。\n\n"
                "2. 为什么要同时比较四类方法？\n- 因为它们分别代表误差统计加权、传统集成学习、提升树回归与时序深度学习，具有互补性。\n\n"
                "3. 为什么还要做 GCP？\n- 因为点预测精度只能说明准确性，GCP 进一步回答模型预测区间是否可靠、是否足够紧致。\n"
            )
        elif stage_key == "midterm":
            highlights = []
            if metric_highlights.get("best_r"):
                highlights.append(f"点预测相关性最优模型：{metric_highlights['best_r']['predicted']} (R={metric_highlights['best_r']['R']:.3f})")
            if metric_highlights.get("best_rmse"):
                highlights.append(f"点预测误差最小模型：{metric_highlights['best_rmse']['predicted']} (RMSE={metric_highlights['best_rmse']['RMSE']:.3f})")
            if gcp_highlights.get("best_picp"):
                highlights.append(f"GCP 覆盖率最优模型：{gcp_highlights['best_picp']['predicted']} (PICP={gcp_highlights['best_picp']['PICP']:.3f})")
            if gcp_highlights.get("best_is"):
                highlights.append(f"GCP 区间评分最优模型：{gcp_highlights['best_is']['predicted']} (IS={gcp_highlights['best_is']['IS']:.3f})")
            highlight_text = "\n".join(f"- {item}" for item in highlights) if highlights else "- 当前尚未指定指标表，建议在中期材料中分别补充点预测精度表和 GCP 不确定性表。"
            report_parts = [
                common_header,
                "## 1. 已完成工作\n"
                "- 已形成数据清点、站点—栅格配准、时序特征构建与基础精度评价流程。\n"
                "- 已接入 BTCH、RF、XGBoost、LSTM 及论文图表自动生成模块。\n"
                "- 已生成的成果文件如下：\n" ,
                _table_markdown(artifact_overview, 20) + "\n\n" ,
                "## 2. 阶段性结果\n" ,
                highlight_text + "\n\n" ,
            ]
            if metrics_md:
                report_parts.append("### 2.1 点预测精度摘要\n" + metrics_md + "\n\n")
            if gcp_metrics_md:
                report_parts.append("### 2.2 GCP 不确定性摘要\n" + gcp_metrics_md + "\n\n")
            if importance_md:
                report_parts.append("### 2.3 特征重要性摘要\n" + importance_md + "\n\n")
            if btch_md:
                report_parts.append("### 2.4 BTCH 权重摘要\n" + btch_md + "\n\n")
            report_parts.append(
                "## 3. 当前存在的问题\n"
                "- 不同产品时间交集与缺失模式可能不一致。\n"
                "- 站点样本量与时序长度可能限制 LSTM 稳定性。\n"
                "- 不同分区结果仍需补充月尺度、季节尺度与空间分组分析。\n"
                "- 点预测精度与 GCP 不确定性需要分开解释，避免把 R/RMSE 与 PICP/MPIW 混为一谈。\n\n"
                "## 4. 后续计划\n"
                "- 完成统一指标表并补全图表编号。\n"
                "- 完成 2020 独立验证期的模型对比。\n"
                "- 补充分地类/高程/坡度分组统计。\n"
                "- 整理论文结果章节初稿。\n"
            )
            report = "".join(report_parts)
            outline = (
                "# 中期汇报提纲\n\n"
                "1. 研究目标回顾\n"
                "2. 数据准备与流程进展\n"
                "3. 已完成的模型与图表\n"
                "4. 阶段性结果（点预测精度 + GCP 不确定性）\n"
                "5. 当前问题与原因分析\n"
                "6. 后续工作计划\n"
            )
            qa = (
                "# 中期检查常见问题与回答提纲\n\n"
                "1. 当前最好的模型是谁？\n- 回答时先基于独立验证期点预测指标表，再补充 GCP 不确定性结果，说明准确性与可靠性并不完全等价。\n\n"
                "2. 为什么中期还不能直接下最终结论？\n- 因为还需补充分组检验、季节尺度分析，并把点预测与 GCP 区间结果联合整合。\n\n"
                "3. 后续最关键工作是什么？\n- 完成统一验证框架下的模型比较，并将点预测精度与不确定性结果转换为论文图表和章节文本。\n"
            )
        else:
            ranking_lines = []
            for idx, row in enumerate(metric_highlights.get("ranking", [])[:5], start=1):
                ranking_lines.append(f"{idx}. {row.get('predicted')}（点预测综合排序分数 {row.get('rank_score'):.2f}）")
            gcp_ranking_lines = []
            for idx, row in enumerate(gcp_highlights.get("ranking", [])[:5], start=1):
                gcp_ranking_lines.append(f"{idx}. {row.get('predicted')}（GCP 综合排序分数 {row.get('rank_score'):.2f}）")
            feat_lines = [f"- {row['feature']}: {row['importance']:.4f}" for row in feature_highlights[:6]]
            btch_lines = [f"- {row['product']}: 平均权重 {row['weight']:.4f}" for row in btch_highlights.get("mean_weights", [])[:6]]
            report_parts = [
                common_header,
                "## 1. 研究目标与完成情况\n"
                "- 已完成多源土壤水分产品与站点观测的统一整理。\n"
                "- 已完成 BTCH、RF、XGBoost、LSTM 四类方法的实验接入与对比准备。\n"
                "- 已具备自动生成论文图表、阶段材料和结果摘要的能力。\n\n" ,
                "## 2. 核心结果摘要\n" ,
                ("\n".join(ranking_lines) if ranking_lines else "- 请指定点预测指标表后重新生成，以写入最终模型排序。") + "\n\n" ,
            ]
            if gcp_ranking_lines:
                report_parts.append("### 2.1 GCP 不确定性排序\n" + "\n".join(gcp_ranking_lines) + "\n\n")
            if metrics_md:
                report_parts.append("### 2.2 点预测精度表\n" + metrics_md + "\n\n")
            if gcp_metrics_md:
                report_parts.append("### 2.3 GCP 指标表\n" + gcp_metrics_md + "\n\n")
            if feat_lines:
                report_parts.append("### 2.4 主要驱动因子\n" + "\n".join(feat_lines) + "\n\n")
            if btch_lines:
                report_parts.append("### 2.5 BTCH 权重特征\n" + "\n".join(btch_lines) + "\n\n")
            if recent_pngs:
                report_parts.append("## 3. 建议用于答辩的图件\n" + "\n".join(f"- {p}" for p in recent_pngs[:8]) + "\n\n")
            if figure_notes:
                report_parts.append("## 4. 图注草稿摘录\n" + figure_notes + "\n\n")
            report_parts.append(
                "## 5. 研究创新与不足\n"
                "- 创新：统一同一流域尺度下比较统计融合、集成学习与时序深度学习方法。\n"
                "- 创新：将配准、建模、评价、出图和阶段材料整合为一体化流程。\n"
                "- 不足：仍受站点密度、时间交集与模型超参数稳定性影响。\n\n"
                "## 6. 结论表达建议\n"
                "- 先给出独立验证期点预测总体排序，再单独说明 GCP 区间可靠性与紧致性。\n"
                "- 对最优模型的优势和局限同时表述，避免仅以单一指标下结论。\n"
                "- 将 BTCH 权重、特征重要性、时序图与 GCP 指标组合呈现，提高可解释性。\n"
            )
            report = "".join(report_parts)
            outline = (
                "# 答辩汇报提纲（10-12 分钟）\n\n"
                "1. 研究背景与问题提出\n"
                "2. 数据来源与研究区\n"
                "3. 技术路线\n"
                "4. 四类模型构建思路\n"
                "5. 点预测结果与 GCP 不确定性对比\n"
                "6. 时间/空间维度分析\n"
                "7. 结论、创新与不足\n"
                "8. 展望\n\n"
                "## 3 分钟精简版\n"
                "- 研究问题\n- 数据与方法\n- 点预测最优结果\n- GCP 可靠性最优结果\n- 结论与意义\n"
            )
            qa = (
                "# 答辩问答库\n\n"
                "1. 为什么 BTCH 仍然有必要？\n- 因为它不依赖真值直接参与权重估计，适合在站点稀缺场景下提供统计基线。\n\n"
                "2. RF 和 XGBoost 的差别是什么？\n- RF 更稳健、解释简单；XGBoost 更强调 boosting 迭代，往往在非线性拟合上更强，但更依赖参数。\n\n"
                "3. LSTM 的优势和限制是什么？\n- 优势在于刻画记忆效应与时序依赖；限制在于样本长度、缺失模式和训练稳定性。\n\n"
                "4. 为什么采用 2019 训练、2020 验证？\n- 为避免随机混洗带来的信息泄露，更真实地检验跨年泛化能力。\n\n"
                "5. 如果老师质疑最优模型结论怎么办？\n- 回到点预测指标表与 GCP 指标表，分别说明准确性和可靠性，再解释为什么最终推荐该模型。\n"
            )

        report_path = _save_markdown_artifact(manager, f"{output_prefix}_{stage_key}_report", report)
        outline_path = _save_markdown_artifact(manager, f"{output_prefix}_{stage_key}_outline", outline)
        qa_path = _save_markdown_artifact(manager, f"{output_prefix}_{stage_key}_qa", qa)
        manifest = {
            "stage": stage_key,
            "topic": topic_text,
            "research_document": research_document,
            "metrics_dataset": metrics_dataset,
            "gcp_metrics_dataset": gcp_metrics_dataset,
            "feature_importance_dataset": feature_importance_dataset,
            "btch_weights_dataset": btch_weights_dataset,
            "figure_notes_document": figure_notes_document,
            "figure_notes_source": figure_notes_source,
            "recent_pngs": recent_pngs,
            "recent_docs": recent_docs,
            "outputs": {
                "report": str(report_path),
                "outline": str(outline_path),
                "qa": str(qa_path),
            },
        }
        manifest_path = _save_json_artifact(manager, f"{output_prefix}_{stage_key}_manifest", manifest)
        report_name = manager.put_text_document(f"{output_prefix}_{stage_key}_report_doc", report, filename=f"{_artifact_safe_name(output_prefix)}_{stage_key}_report.txt")
        outline_name = manager.put_text_document(f"{output_prefix}_{stage_key}_outline_doc", outline, filename=f"{_artifact_safe_name(output_prefix)}_{stage_key}_outline.txt")
        qa_name = manager.put_text_document(f"{output_prefix}_{stage_key}_qa_doc", qa, filename=f"{_artifact_safe_name(output_prefix)}_{stage_key}_qa.txt")
        manager.log_operation("阶段材料生成", f"{stage_key} -> {report_path.name}", "report")
        stage_label = stage_titles[stage_key]
        return (
            f"已生成 {stage_label} 材料包。报告: {report_path}（数据集 {report_name}）；"
            f"提纲: {outline_path}（数据集 {outline_name}）；问答库: {qa_path}（数据集 {qa_name}）；"
            f"清单: {manifest_path}"
        )


    @tool
    def generate_model_comparison_summary(metrics_dataset: str, output_prefix: str = "model_summary") -> str:
        """根据统一精度指标表或 GCP 指标表生成模型排序摘要、论文式结果段落和答辩用结论卡片。"""
        df = _prepare_dataframe(metrics_dataset, manager)
        highlights = _extract_metric_highlights(df, dataset_name=metrics_dataset)
        ranking = pd.DataFrame(highlights.get("ranking", []))
        ranking_name = manager.put_table(f"{output_prefix}_ranking", ranking, filename=f"{_artifact_safe_name(output_prefix)}_ranking.csv")
        metrics = highlights.get("metrics", [])
        family = highlights.get("family", "standard")
        lines = [f"# 模型比较摘要（来源：{metrics_dataset}）", ""]
        if ranking.empty:
            lines.append("当前指标表无法形成有效排序。")
        else:
            lines.append("## 综合排序")
            for idx, row in ranking.head(6).iterrows():
                lines.append(f"{idx + 1}. {row['predicted']}：综合排序分数 {row['rank_score']:.2f}")
            lines.append("")
        if family == 'gcp':
            if highlights.get("best_picp"):
                gap = highlights['best_picp'].get('coverage_gap')
                extra = f"，覆盖偏差={gap:.3f}" if isinstance(gap, (int, float)) else ""
                lines.append(f"- 覆盖率最优：{highlights['best_picp']['predicted']}（PICP={highlights['best_picp']['PICP']:.3f}{extra}）")
            if highlights.get("best_mpiw"):
                lines.append(f"- 区间最紧致：{highlights['best_mpiw']['predicted']}（MPIW={highlights['best_mpiw']['MPIW']:.3f}）")
            if highlights.get("best_is"):
                lines.append(f"- 区间评分最优：{highlights['best_is']['predicted']}（IS={highlights['best_is']['IS']:.3f}）")
            lines += [
                "",
                "## 论文式结果表述",
                "在统一 GCP 验证框架下，不同模型的区间预测质量存在明显差异。综合覆盖率、区间宽度、条件覆盖偏差和区间评分可见，排名靠前的方法在保持覆盖率接近名义水平的同时，具有更紧致的预测区间和更稳定的空间不确定性表征能力。",
                "",
                "## 答辩结论卡片",
                "1. GCP 结果不能只看覆盖率，还要同时考虑区间宽度与综合区间评分。",
                "2. 覆盖率接近名义水平且区间更窄，说明模型在可靠性与紧致性之间取得了更好的平衡。",
                "3. 建议将 GCP 结果与点预测精度结果联合汇报，体现模型准确性与可靠性。",
                "",
                "## 可引用指标字段",
                ", ".join(metrics) if metrics else "（未识别到指标列）",
            ]
        else:
            if highlights.get("best_r"):
                lines.append(f"- 相关性最优：{highlights['best_r']['predicted']}（R={highlights['best_r']['R']:.3f}）")
            if highlights.get("best_nse"):
                lines.append(f"- NSE 最优：{highlights['best_nse']['predicted']}（NSE={highlights['best_nse']['NSE']:.3f}）")
            if highlights.get("best_rmse"):
                lines.append(f"- RMSE 最优：{highlights['best_rmse']['predicted']}（RMSE={highlights['best_rmse']['RMSE']:.3f}）")
            lines += [
                "",
                "## 论文式结果表述",
                "在统一验证框架下，不同模型/产品的总体精度存在明显差异。综合相关性、误差和效率系数等指标可见，排名靠前的方法在独立验证期表现出更好的稳定性与泛化能力。建议在正文中同时报告最优模型的优势与局限，避免仅依据单一指标下结论。",
                "",
                "## 答辩结论卡片",
                "1. 最优模型并非只看单一指标，而是基于独立验证期综合排序。",
                "2. BTCH 提供了统计融合基线，RF/XGBoost 体现非线性拟合能力，LSTM 则体现时序记忆能力。",
                "3. 建议结合总体、时间维度和空间维度三类结果共同汇报。",
                "",
                "## 可引用指标字段",
                ", ".join(metrics) if metrics else "（未识别到指标列）",
            ]
        text = "\n".join(lines)
        md_path = _save_markdown_artifact(manager, f"{output_prefix}_summary", text)
        doc_name = manager.put_text_document(f"{output_prefix}_summary_doc", text, filename=f"{_artifact_safe_name(output_prefix)}_summary.txt")
        manager.log_operation("模型比较摘要", f"{metrics_dataset} -> {md_path.name}", "report")
        return f"模型比较摘要已生成: {md_path}。排序表数据集: {ranking_name}。文本数据集: {doc_name}"


    @tool
    def run_database_training_pipeline(
        output_prefix: str,
        target_col: str,
        feature_cols: str,
        sql: str = "",
        source_dataset: str = "",
        models: str = "btch,rf,xgboost,lstm",
        date_col: str = "",
        split_date: str = "",
        product_cols: str = "",
        observed_col: str = "",
        dynamic_feature_cols: str = "",
        static_feature_cols: str = "",
        group_col: str = "",
        lag_feature_cols: str = "",
        lag_steps: str = "1,3,7",
        rolling_windows: str = "3,7",
        seq_len: int = 7,
        stage: str = "",
        run_gcp: bool = True,
        gcp_alpha: float = 0.1,
        gcp_calibration_ratio: float = 0.3,
        gcp_selection: str = "latest",
        gcp_kernel: str = "gaussian",
        gcp_bandwidth: float = 0.0,
        gcp_lon_col: str = "",
        gcp_lat_col: str = "",
        gcp_target_scope: str = "holdout",
    ) -> str:
        """运行数据库驱动训练流水线：从 SQLite 或已有数据集生成训练表，显示完整步骤，并自动完成数据检查、特征构建、模型训练、指标汇总、图表与阶段材料输出。"""
        if not sql and not source_dataset:
            raise ValueError("请至少提供 sql 或 source_dataset 之一。")
        if not output_prefix.strip():
            raise ValueError("output_prefix 不能为空。")
        models_requested = [item.strip().lower() for item in re.split(r"[,;，\s]+", models or "") if item.strip()]
        models_requested = models_requested or ["btch", "rf", "xgboost", "lstm"]
        feature_list = _parse_columns(feature_cols)
        product_list = _parse_columns(product_cols) if product_cols.strip() else []
        observed_field = observed_col.strip() or target_col
        dynamic_cols_text = dynamic_feature_cols.strip() or feature_cols
        run_id = _make_pipeline_run_id(output_prefix)
        source_type = "sql" if sql.strip() else "dataset"
        source_value = sql.strip() if sql.strip() else source_dataset
        summary_seed = {
            "models_requested": models_requested,
            "target_col": target_col,
            "feature_cols": feature_list,
            "date_col": date_col or None,
            "split_date": split_date or None,
            "product_cols": product_list,
            "run_gcp": bool(run_gcp),
            "gcp_alpha": float(gcp_alpha),
            "gcp_calibration_ratio": float(gcp_calibration_ratio),
            "gcp_target_scope": gcp_target_scope or "holdout",
        }
        manager.start_pipeline_run(run_id, "database_training_pipeline", source_type, source_value, output_prefix, summary_seed)
        step_order = 0
        local_steps: list[dict[str, Any]] = []

        def record(step_name: str, status: str, input_summary: str, output_summary: str, detail: dict[str, Any] | None = None) -> None:
            nonlocal step_order
            step_order += 1
            detail = detail or {}
            manager.add_pipeline_step(run_id, step_order, step_name, status, input_summary, output_summary, detail)
            local_steps.append({
                "step_order": step_order,
                "step_name": step_name,
                "status": status,
                "input_summary": input_summary,
                "output_summary": output_summary,
                "detail": detail,
            })

        try:
            if sql.strip():
                source_df = manager.query_database(sql)
                source_name = manager.put_table(f"{output_prefix}_source", source_df)
                record("生成训练表", "success", "从 SQLite 执行 SQL", f"得到训练表 {source_name}，{len(source_df)} 行", {"sql": sql, "dataset": source_name, "rows": int(len(source_df))})
            else:
                source_name = source_dataset
                source_df = _prepare_dataframe(source_name, manager)
                record("读取已有训练表", "success", f"数据集 {source_name}", f"读取 {len(source_df)} 行", {"dataset": source_name, "rows": int(len(source_df))})

            current_dataset = source_name
            profile_name = f"{output_prefix}_missing_profile"
            profile_missing_values.invoke({"dataset_name": current_dataset, "output_name": profile_name})
            record("数据体检", "success", f"检查 {current_dataset}", f"生成缺失值统计表 {profile_name}", {"profile_dataset": profile_name})

            if lag_feature_cols.strip() and date_col.strip():
                time_output = f"{output_prefix}_features"
                build_time_features.invoke({
                    "dataset_name": current_dataset,
                    "date_col": date_col,
                    "group_col": group_col,
                    "value_cols": lag_feature_cols,
                    "output_name": time_output,
                    "lags": lag_steps,
                    "rolling_windows": rolling_windows,
                })
                current_dataset = time_output
                record("构建时序特征", "success", f"base_cols={lag_feature_cols}", f"生成增强训练表 {time_output}", {"lag_steps": lag_steps, "rolling_windows": rolling_windows, "dataset": time_output})
            else:
                record("构建时序特征", "skipped", "未提供 lag_feature_cols 或 date_col", "跳过该步骤", {})

            combined_metric_rows: list[dict[str, Any]] = []
            created_outputs: dict[str, Any] = {"source_dataset": source_name, "working_dataset": current_dataset, "models": {}, "reports": {}, "charts": []}

            def _parsed_tool_success(raw: Any, step_name: str, input_summary: str) -> dict[str, Any] | None:
                parsed = parse_tool_result(raw)
                if parsed is not None and not parsed.get("ok"):
                    detail = {
                        "error_code": parsed.get("error_code"),
                        "user_message": parsed.get("user_message"),
                        "next_actions": parsed.get("next_actions"),
                        "diagnostics": parsed.get("diagnostics"),
                    }
                    record(step_name, "failed", input_summary, str(parsed.get("user_message") or parsed.get("error_code") or "tool failed"), detail)
                    return None
                return parsed or {}

            if "btch" in models_requested:
                if len(product_list) < 3:
                    record("BTCH 融合", "skipped", "产品列少于 3 个", "BTCH 至少需要 3 个产品列", {"product_cols": product_list})
                else:
                    btch_output = f"{output_prefix}_btch_result"
                    btch_fusion_model.invoke({
                        "dataset_name": current_dataset,
                        "product_cols": ",".join(product_list),
                        "output_name": btch_output,
                        "window_mode": "global",
                    })
                    pred_col = f"{btch_output}_btch"
                    created_outputs["models"]["btch"] = {"result_dataset": btch_output, "prediction_column": pred_col, "weights_dataset": f"{btch_output}_btch_weights"}
                    if observed_field:
                        btch_df = _prepare_dataframe(btch_output, manager)
                        _validate_columns(btch_df, [observed_field, pred_col])
                        metric_row = _calc_metrics(btch_df[observed_field], btch_df[pred_col])
                        metric_row.update({"predicted": pred_col, "model": "BTCH", "scope": "all"})
                        combined_metric_rows.append(metric_row)
                    record("BTCH 融合", "success", f"输入表 {current_dataset}", f"生成结果 {btch_output}", created_outputs["models"]["btch"])

            if "rf" in models_requested:
                rf_output = f"{output_prefix}_rf_result"
                rf_raw = train_rf_fusion_model.invoke({
                    "dataset_name": current_dataset,
                    "target_col": target_col,
                    "feature_cols": ",".join(feature_list),
                    "output_name": rf_output,
                    "date_col": date_col,
                    "split_date": split_date,
                })
                rf_result = _parsed_tool_success(rf_raw, "RF 融合训练", f"输入表 {current_dataset}")
                if rf_result is not None:
                    rf_outputs = rf_result.get("outputs") if isinstance(rf_result.get("outputs"), dict) else {}
                    rf_metrics_name = str(rf_outputs.get("metrics_dataset") or f"{rf_output}_rf_metrics")
                    rf_pred_col = str(rf_outputs.get("prediction_column") or f"{rf_output}_rf")
                    rf_metrics_df = _prepare_dataframe(rf_metrics_name, manager)
                    combined_metric_rows.append(_metric_row_with_label(rf_metrics_df, rf_pred_col, "RF"))
                    created_outputs["models"]["rf"] = {
                        "model_result_id": rf_outputs.get("model_result_id"),
                        "result_dataset": rf_outputs.get("result_dataset") or rf_output,
                        "prediction_column": rf_pred_col,
                        "metrics_dataset": rf_metrics_name,
                        "importance_dataset": rf_outputs.get("importance_dataset") or f"{rf_output}_rf_importance",
                    }
                    record("RF 融合训练", "success", f"输入表 {current_dataset}", f"生成结果 {rf_output}", created_outputs["models"]["rf"])

            if "xgboost" in models_requested or "xgb" in models_requested:
                try:
                    xgb_output = f"{output_prefix}_xgb_result"
                    xgb_raw = train_xgboost_fusion_model.invoke({
                        "dataset_name": current_dataset,
                        "target_col": target_col,
                        "feature_cols": ",".join(feature_list),
                        "output_name": xgb_output,
                        "date_col": date_col,
                        "split_date": split_date,
                    })
                    xgb_result = _parsed_tool_success(xgb_raw, "XGBoost 融合训练", f"输入表 {current_dataset}")
                    if xgb_result is not None:
                        xgb_outputs = xgb_result.get("outputs") if isinstance(xgb_result.get("outputs"), dict) else {}
                        xgb_metrics_name = str(xgb_outputs.get("metrics_dataset") or f"{xgb_output}_xgb_metrics")
                        xgb_pred_col = str(xgb_outputs.get("prediction_column") or f"{xgb_output}_xgb")
                        xgb_metrics_df = _prepare_dataframe(xgb_metrics_name, manager)
                        combined_metric_rows.append(_metric_row_with_label(xgb_metrics_df, xgb_pred_col, "XGBoost"))
                        created_outputs["models"]["xgboost"] = {
                            "model_result_id": xgb_outputs.get("model_result_id"),
                            "result_dataset": xgb_outputs.get("result_dataset") or xgb_output,
                            "prediction_column": xgb_pred_col,
                            "metrics_dataset": xgb_metrics_name,
                            "importance_dataset": xgb_outputs.get("importance_dataset") or f"{xgb_output}_xgb_importance",
                        }
                        record("XGBoost 融合训练", "success", f"输入表 {current_dataset}", f"生成结果 {xgb_output}", created_outputs["models"]["xgboost"])
                except Exception as exc:
                    record("XGBoost 融合训练", "failed", f"输入表 {current_dataset}", str(exc), {})

            if "lstm" in models_requested:
                if not date_col.strip():
                    record("LSTM 融合训练", "skipped", "未提供 date_col", "跳过 LSTM", {})
                else:
                    try:
                        lstm_output = f"{output_prefix}_lstm_result"
                        lstm_raw = train_lstm_fusion_model.invoke({
                            "dataset_name": current_dataset,
                            "target_col": target_col,
                            "dynamic_feature_cols": dynamic_cols_text,
                            "output_name": lstm_output,
                            "date_col": date_col,
                            "group_col": group_col,
                            "static_feature_cols": static_feature_cols,
                            "seq_len": int(seq_len),
                            "split_date": split_date,
                        })
                        lstm_result = _parsed_tool_success(lstm_raw, "LSTM 融合训练", f"输入表 {current_dataset}")
                        if lstm_result is not None:
                            lstm_outputs = lstm_result.get("outputs") if isinstance(lstm_result.get("outputs"), dict) else {}
                            lstm_metrics_name = str(lstm_outputs.get("metrics_dataset") or f"{lstm_output}_lstm_metrics")
                            lstm_pred_col = str(lstm_outputs.get("prediction_column") or f"{lstm_output}_lstm")
                            lstm_metrics_df = _prepare_dataframe(lstm_metrics_name, manager)
                            combined_metric_rows.append(_metric_row_with_label(lstm_metrics_df, lstm_pred_col, "LSTM"))
                            created_outputs["models"]["lstm"] = {
                                "model_result_id": lstm_outputs.get("model_result_id"),
                                "result_dataset": lstm_outputs.get("result_dataset") or lstm_output,
                                "prediction_column": lstm_pred_col,
                                "metrics_dataset": lstm_metrics_name,
                                "history_dataset": lstm_outputs.get("history_dataset") or f"{lstm_output}_lstm_history",
                            }
                            record("LSTM 融合训练", "success", f"输入表 {current_dataset}", f"生成结果 {lstm_output}", created_outputs["models"]["lstm"])
                    except Exception as exc:
                        record("LSTM 融合训练", "failed", f"输入表 {current_dataset}", str(exc), {})

            gcp_metric_rows: list[dict[str, Any]] = []
            created_outputs["gcp"] = {}

            def _save_subset_dataset(base_dataset: str, mask: pd.Series, subset_name: str) -> str:
                record = manager.get(base_dataset)
                if record.data_type == "vector":
                    subset_gdf = manager.get_vector(base_dataset).loc[mask].copy()
                    return manager.put_vector(subset_name, subset_gdf, filename=f"{_artifact_safe_name(subset_name)}.geojson")
                subset_df = _prepare_dataframe(base_dataset, manager).loc[mask].copy()
                return manager.put_table(subset_name, subset_df)

            if run_gcp and observed_field:
                gcp_scope = (gcp_target_scope or "holdout").strip().lower()
                if gcp_scope not in {"holdout", "all"}:
                    record("GCP 不确定性分析", "skipped", f"gcp_target_scope={gcp_target_scope}", "仅支持 holdout 或 all，已跳过", {})
                else:
                    for model_key, model_info in created_outputs["models"].items():
                        pred_col = str(model_info.get("prediction_column") or "").strip()
                        result_dataset = str(model_info.get("result_dataset") or "").strip()
                        if not pred_col or not result_dataset:
                            continue
                        try:
                            gcp_output = f"{output_prefix}_{model_key}_gcp"
                            calibration_dataset_name = result_dataset
                            target_dataset_name = ""
                            if gcp_scope == "holdout" and date_col.strip() and split_date.strip():
                                result_df = _prepare_dataframe(result_dataset, manager)
                                date_series = _ensure_datetime(result_df, date_col)
                                split_ts = pd.to_datetime(split_date)
                                calibration_mask = date_series <= split_ts
                                target_mask = date_series > split_ts
                                if int(calibration_mask.sum()) < 20 or int(target_mask.sum()) < 1:
                                    raise ValueError("按 split_date 划分后，校准集或目标集样本不足。")
                                calibration_dataset_name = _save_subset_dataset(result_dataset, calibration_mask, f"{result_dataset}_gcp_calibration")
                                target_dataset_name = _save_subset_dataset(result_dataset, target_mask, f"{result_dataset}_gcp_target")

                            gcp_raw = geographical_conformal_prediction.invoke({
                                "calibration_dataset": calibration_dataset_name,
                                "target_dataset_name": target_dataset_name,
                                "observed_col": observed_field,
                                "predicted_cols": pred_col,
                                "output_name": gcp_output,
                                "lon_col": gcp_lon_col,
                                "lat_col": gcp_lat_col,
                                "date_col": date_col,
                                "calibration_ratio": float(gcp_calibration_ratio),
                                "calibration_selection": gcp_selection,
                                "alpha": float(gcp_alpha),
                                "bandwidth": float(gcp_bandwidth),
                                "kernel": gcp_kernel,
                            })
                            gcp_result = _parsed_tool_success(gcp_raw, "GCP 不确定性分析", f"模型 {model_key} | 结果表 {result_dataset}")
                            if gcp_result is not None:
                                gcp_outputs = gcp_result.get("outputs") if isinstance(gcp_result.get("outputs"), dict) else {}
                                gcp_metrics_name = str(gcp_outputs.get("metrics_dataset") or f"{gcp_output}_gcp_metrics")
                                gcp_df = _prepare_dataframe(gcp_metrics_name, manager).copy()
                                gcp_df["model"] = model_key.upper() if model_key != "xgboost" else "XGBoost"
                                gcp_df["prediction_column"] = pred_col
                                gcp_metric_rows.extend(gcp_df.to_dict(orient="records"))
                                created_outputs["gcp"][model_key] = {
                                    "model_result_id": gcp_outputs.get("model_result_id"),
                                    "result_dataset": gcp_outputs.get("result_dataset") or gcp_output,
                                    "metrics_dataset": gcp_metrics_name,
                                    "prediction_column": pred_col,
                                    "calibration_dataset": calibration_dataset_name,
                                    "target_dataset": target_dataset_name or calibration_dataset_name,
                                }
                                record("GCP 不确定性分析", "success", f"模型 {model_key} | 结果表 {result_dataset}", f"生成区间结果 {gcp_output}", created_outputs["gcp"][model_key])
                        except Exception as exc:
                            record("GCP 不确定性分析", "failed", f"模型 {model_key} | 结果表 {result_dataset}", str(exc), {})
            else:
                record("GCP 不确定性分析", "skipped", f"run_gcp={run_gcp} observed_field={observed_field}", "未启用或缺少 observed_col，跳过 GCP", {})

            if gcp_metric_rows:
                gcp_metrics_dataset_name = manager.put_table(f"{output_prefix}_combined_gcp_metrics", pd.DataFrame(gcp_metric_rows))
                created_outputs["reports"]["gcp_metrics_dataset"] = gcp_metrics_dataset_name
                record("汇总 GCP 指标", "success", "收集各模型区间指标", f"生成统一 GCP 指标表 {gcp_metrics_dataset_name}", {"rows": int(len(gcp_metric_rows))})
                try:
                    gcp_chart_message = generate_thesis_charts.invoke({
                        "dataset_name": gcp_metrics_dataset_name,
                        "chart_type": "metric_bar",
                        "output_prefix": f"{output_prefix}_gcp_fig",
                        "title": f"{output_prefix} GCP 不确定性比较",
                    })
                    created_outputs["charts"].append(gcp_chart_message)
                    record("生成 GCP 图表", "success", f"GCP 指标表 {gcp_metrics_dataset_name}", "已生成 GCP 指标图与图注草稿", {"message": gcp_chart_message})
                except Exception as exc:
                    record("生成 GCP 图表", "failed", f"GCP 指标表 {gcp_metrics_dataset_name}", str(exc), {})

            if not combined_metric_rows:
                raise ValueError("流水线未生成任何可比较的模型指标，请检查输入字段和模型参数。")

            combined_metrics_df = pd.DataFrame(combined_metric_rows)
            metrics_dataset_name = manager.put_table(f"{output_prefix}_combined_metrics", combined_metrics_df)
            created_outputs["reports"]["metrics_dataset"] = metrics_dataset_name
            record("汇总模型指标", "success", "收集各模型指标", f"生成统一指标表 {metrics_dataset_name}", {"rows": int(len(combined_metrics_df))})

            try:
                charts_message = generate_thesis_charts.invoke({
                    "dataset_name": metrics_dataset_name,
                    "chart_type": "metric_bar",
                    "output_prefix": f"{output_prefix}_metrics_fig",
                    "title": f"{output_prefix} 模型精度比较",
                })
                created_outputs["charts"].append(charts_message)
                record("生成论文图表", "success", f"指标表 {metrics_dataset_name}", "已生成精度对比图与图注草稿", {"message": charts_message})
            except Exception as exc:
                record("生成论文图表", "failed", f"指标表 {metrics_dataset_name}", str(exc), {})

            summary_message = generate_model_comparison_summary.invoke({"metrics_dataset": metrics_dataset_name, "output_prefix": f"{output_prefix}_model_summary"})
            created_outputs["reports"]["comparison_summary"] = summary_message
            record("生成模型比较摘要", "success", f"指标表 {metrics_dataset_name}", "已生成摘要与结论卡片", {"message": summary_message})

            if created_outputs["reports"].get("gcp_metrics_dataset"):
                try:
                    gcp_summary_message = generate_model_comparison_summary.invoke({
                        "metrics_dataset": created_outputs["reports"]["gcp_metrics_dataset"],
                        "output_prefix": f"{output_prefix}_gcp_summary",
                    })
                    created_outputs["reports"]["gcp_comparison_summary"] = gcp_summary_message
                    record("生成 GCP 比较摘要", "success", f"指标表 {created_outputs['reports']['gcp_metrics_dataset']}", "已生成 GCP 摘要与结论卡片", {"message": gcp_summary_message})
                except Exception as exc:
                    record("生成 GCP 比较摘要", "failed", f"指标表 {created_outputs['reports']['gcp_metrics_dataset']}", str(exc), {})

            if stage.strip():
                stage_message = generate_stage_report.invoke({
                    "stage": stage,
                    "output_prefix": f"{output_prefix}_stage",
                    "metrics_dataset": metrics_dataset_name,
                    "gcp_metrics_dataset": created_outputs["reports"].get("gcp_metrics_dataset", ""),
                    "feature_importance_dataset": created_outputs["models"].get("rf", {}).get("importance_dataset") or created_outputs["models"].get("xgboost", {}).get("importance_dataset", ""),
                    "btch_weights_dataset": created_outputs["models"].get("btch", {}).get("weights_dataset", ""),
                })
                created_outputs["reports"]["stage_pack"] = stage_message
                record("生成阶段材料", "success", stage, "已生成阶段报告、提纲与问答库", {"message": stage_message})
            else:
                record("生成阶段材料", "skipped", "未提供 stage", "跳过阶段材料生成", {})

            final_detail = {
                "run_id": run_id,
                "pipeline_name": "database_training_pipeline",
                "status": "success",
                "source_type": source_type,
                "source_value": source_value,
                "output_prefix": output_prefix,
                "started_at": "",
                "finished_at": "",
                "steps": local_steps,
                "summary": created_outputs,
            }
            pipeline_md = _pipeline_steps_markdown(final_detail)
            pipeline_md_path = _save_markdown_artifact(manager, f"{output_prefix}_pipeline_report", pipeline_md)
            pipeline_doc_name = manager.put_text_document(f"{output_prefix}_pipeline_report_doc", pipeline_md, filename=f"{_artifact_safe_name(output_prefix)}_pipeline_report.txt")
            created_outputs["reports"]["pipeline_markdown"] = str(pipeline_md_path)
            created_outputs["reports"]["pipeline_document"] = pipeline_doc_name
            manager.finish_pipeline_run(run_id, "success", created_outputs)
            record("保存流程记录", "success", run_id, f"已生成流程文档 {pipeline_doc_name}", {"markdown": str(pipeline_md_path), "document": pipeline_doc_name})
            detail = manager.pipeline_run_detail(run_id) or final_detail
            latest_report = _pipeline_steps_markdown(detail)
            manager.put_text_document(f"{output_prefix}_pipeline_latest_doc", latest_report, filename=f"{_artifact_safe_name(output_prefix)}_pipeline_latest.txt")
            gcp_summary_line = ""
            if created_outputs["reports"].get("gcp_metrics_dataset"):
                gcp_summary_line = f"统一 GCP 指标表: {created_outputs['reports']['gcp_metrics_dataset']}。\n"
            return (
                f"数据库驱动训练流水线已完成。运行编号: {run_id}。\n"
                f"训练表: {created_outputs['source_dataset']}；工作表: {created_outputs['working_dataset']}。\n"
                f"统一指标表: {metrics_dataset_name}。\n"
                + gcp_summary_line
                + f"流程文档: {pipeline_md_path}（数据集 {pipeline_doc_name}）。\n"
                + "可继续用 show_pipeline_run 查看完整步骤，或用 list_pipeline_runs 查看历史记录。"
            )
        except Exception as exc:
            manager.finish_pipeline_run(run_id, "failed", {"error": str(exc), "partial_steps": local_steps})
            raise


    @tool
    def plot_dataset(dataset_name: str, column: str = "", title: str = "", output_name: str = "") -> str:
        """为矢量或栅格数据生成地图 PNG。矢量可选 column 进行专题制图。"""
        inputs = {"dataset_name": dataset_name, "column": column, "title": title, "output_name": output_name}
        errors = validate_dataset_exists(manager, dataset_name)
        errors.extend(validate_output_path(manager.plot_dir, output_name, allowed_suffixes={".png"}))
        if errors:
            return _tool_error_from_validation("plot_dataset", inputs, errors)

        try:
            record = manager.get(dataset_name)
        except Exception as exc:
            return _tool_internal_error("plot_dataset", inputs, exc)

        if record.data_type == "table":
            return tool_result_error(
                "plot_dataset",
                inputs=inputs,
                error_code="UNSUPPORTED_DATASET_TYPE",
                error_title="表格不能直接制图",
                user_message="表格数据不能直接绘制为空间地图，需要先转换为点图层或选择已有矢量/栅格数据。",
                diagnostics={"dataset_type": record.data_type},
                next_actions=["先使用 table_to_points 将经纬度表转换为点图层。", "或选择一个矢量/栅格数据集制图。"],
            ).to_json()
        if record.data_type not in {"vector", "raster"}:
            return tool_result_error(
                "plot_dataset",
                inputs=inputs,
                error_code="UNSUPPORTED_DATASET_TYPE",
                error_title="数据类型不支持制图",
                user_message=f"当前数据类型 {record.data_type} 暂不支持直接制图。",
                diagnostics={"dataset_type": record.data_type},
                next_actions=["选择矢量或栅格数据集。"],
            ).to_json()

        errors = []
        if record.data_type == "vector":
            errors.extend(validate_vector_readable(manager, dataset_name))
            errors.extend(validate_crs(manager, dataset_name))
            if str(column or "").strip():
                errors.extend(validate_required_fields(manager, dataset_name, [column]))
        else:
            errors.extend(validate_raster_readable(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("plot_dataset", inputs, errors)

        try:
            record = manager.get(dataset_name)
            output_stem = output_name or f"{dataset_name}_map"
            if Path(output_stem).suffix.lower() == ".png":
                output_stem = Path(output_stem).stem
            output_path = manager.plot_dir / f"{output_stem}.png"
            fig, ax = plt.subplots(figsize=(9.6, 6.8))
            fig.patch.set_facecolor("#0f172a")
            ax.set_facecolor("#f8fafc")
            if record.data_type == "vector":
                plt.close(fig)
                gdf = manager.get_vector(dataset_name)
                _save_vector_map_plot(gdf, output_path, column=column, title=title or dataset_name)
            else:
                raster_path = manager.get_raster_path(dataset_name)
                with rasterio.open(raster_path) as src:
                    raster_show(src, ax=ax, cmap="viridis")
                ax.set_title(_safe_map_title(title or dataset_name), color="white", pad=12)
                ax.grid(alpha=0.15)
                ax.spines[["top", "right"]].set_visible(False)
                plt.tight_layout()
                fig.savefig(output_path, dpi=220, facecolor=fig.get_facecolor(), bbox_inches="tight")
                plt.close(fig)

            manager.last_plot_path = str(output_path)
            manager.log_operation("鐢熸垚鍦板浘", f"{dataset_name} -> {output_path.name}", "plot")
            font_msg = f"使用字体 {_ACTIVE_FONT}" if _ACTIVE_FONT else "未检测到可用中文字体，标题可能自动降级"
            return tool_result_ok(
                "plot_dataset",
                inputs=inputs,
                outputs={"path": str(output_path), "dataset_name": dataset_name, "column": column or ""},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"map_{uuid4().hex[:10]}",
                        path=str(output_path),
                        type="map",
                        title=title or f"{dataset_name} map",
                        description=f"数据集 {dataset_name} 的地图图件。",
                        quality_status="created",
                        preview_available=True,
                    )
                ],
                summary=f"地图已生成：{output_path}",
                diagnostics={"dataset_type": record.data_type, "font": font_msg, "crs": record.meta.get("crs") if isinstance(record.meta, dict) else None},
                next_actions=["查看图件空间分布，并结合字段含义解释异常区域。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("plot_dataset", inputs, exc)

        output_stem = output_name or f"{dataset_name}_map"
        output_path = manager.plot_dir / f"{output_stem}.png"

        fig, ax = plt.subplots(figsize=(9.6, 6.8))
        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#f8fafc")

        if record.data_type == "vector":
            plt.close(fig)
            gdf = manager.get_vector(dataset_name)
            _save_vector_map_plot(gdf, output_path, column=column, title=title or dataset_name)
            font_msg = f"，使用字体: {_ACTIVE_FONT}" if _ACTIVE_FONT else "，未检测到可用中文字体，已自动降级为英文标题或静默告警"
            manager.last_plot_path = str(output_path)
            manager.log_operation("生成地图", f"{dataset_name} -> {output_path.name}", "plot")
            return f"地图已生成: {output_path}{font_msg}"
        elif record.data_type == "raster":
            raster_path = manager.get_raster_path(dataset_name)
            with rasterio.open(raster_path) as src:
                raster_show(src, ax=ax, cmap="viridis")
        elif record.data_type == "table":
            raise ValueError("表格数据不能直接制图，请先转为点图层。")
        else:
            raise ValueError(f"暂不支持绘制的数据类型: {record.data_type}")

        ax.set_title(_safe_map_title(title or dataset_name), color="white" if record.data_type == "raster" else "#e2e8f0", pad=12)
        ax.grid(alpha=0.15)
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        fig.savefig(output_path, dpi=220, facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)

        font_msg = f"，使用字体: {_ACTIVE_FONT}" if _ACTIVE_FONT else "，未检测到可用中文字体，已自动降级为英文标题或静默告警"
        manager.last_plot_path = str(output_path)
        manager.log_operation("生成地图", f"{dataset_name} -> {output_path.name}", "plot")
        return f"地图已生成: {output_path}{font_msg}"

    @tool
    def raster_histogram(dataset_name: str, band: int = 1, output_name: str = "") -> str:
        """为栅格波段生成直方图 PNG，便于查看数值分布。"""
        inputs = {"dataset_name": dataset_name, "band": band, "output_name": output_name}
        output_stem = output_name or f"{dataset_name}_hist"
        errors: list[dict[str, Any]] = []
        errors.extend(validate_dataset_exists(manager, dataset_name))
        errors.extend(validate_output_path(manager.plot_dir, output_stem, allowed_suffixes={".png"}))
        if not errors:
            errors.extend(validate_raster_readable(manager, dataset_name))
        if errors:
            return _tool_error_from_validation("raster_histogram", inputs, errors)

        try:
            raster_path = manager.get_raster_path(dataset_name)
            output_path = manager.plot_dir / f"{Path(output_stem).stem}.png"
            with rasterio.open(raster_path) as src:
                if band < 1 or band > src.count:
                    return tool_result_error(
                        "raster_histogram",
                        inputs=inputs,
                        error_code="RASTER_BAND_OUT_OF_RANGE",
                        error_title="波段编号超出范围",
                        user_message=f"数据 {dataset_name} 只有 {src.count} 个波段，不能读取第 {band} 个波段。",
                        diagnostics={"band": band, "band_count": int(src.count)},
                        next_actions=["请选择 1 到波段总数之间的 band 参数后重试。"],
                    ).to_json()
                arr = src.read(band, masked=True)
                valid = arr.compressed()
                if valid.size == 0:
                    return tool_result_error(
                        "raster_histogram",
                        inputs=inputs,
                        error_code="RASTER_BAND_EMPTY",
                        error_title="波段没有有效像元",
                        user_message=f"{dataset_name} 的第 {band} 个波段没有有效像元，无法生成直方图。",
                        diagnostics={"band": band, "valid_count": 0},
                        next_actions=["检查 NoData 设置，或选择其他波段/数据集。"],
                    ).to_json()

            fig, ax = plt.subplots(figsize=(8.5, 5.5))
            ax.hist(valid, bins=30, color="#38bdf8", edgecolor="#0f172a")
            ax.set_title(_safe_map_title(f"{dataset_name} histogram"))
            ax.set_xlabel("Value")
            ax.set_ylabel("Frequency")
            ax.grid(alpha=0.2)
            plt.tight_layout()
            fig.savefig(output_path, dpi=220, bbox_inches="tight")
            plt.close(fig)
            manager.last_plot_path = str(output_path)
            manager.log_operation("栅格直方图", f"{dataset_name} band {band} -> {output_path.name}", "plot")
            return tool_result_ok(
                "raster_histogram",
                inputs=inputs,
                outputs={"path": str(output_path), "band": int(band), "valid_count": int(valid.size)},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"plot:{output_path.name}",
                        path=str(output_path),
                        type="plot",
                        title=output_path.name,
                        description=f"Histogram for {dataset_name} band {band}",
                        quality_status="ok",
                        preview_available=True,
                    )
                ],
                summary=f"已生成 {dataset_name} 第 {band} 波段的直方图，共统计 {valid.size} 个有效像元。",
                diagnostics={
                    "min": float(np.min(valid)),
                    "max": float(np.max(valid)),
                    "mean": float(np.mean(valid)),
                    "valid_count": int(valid.size),
                },
                next_actions=["可继续查看直方图判断异常值、偏态分布或分级制图阈值。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("raster_histogram", inputs, exc)
        raster_path = manager.get_raster_path(dataset_name)
        output_stem = output_name or f"{dataset_name}_hist"
        output_path = manager.plot_dir / f"{output_stem}.png"
        with rasterio.open(raster_path) as src:
            arr = src.read(band, masked=True)
            valid = arr.compressed()
            if valid.size == 0:
                raise ValueError("该波段没有有效像元，无法生成直方图。")
        fig, ax = plt.subplots(figsize=(8.5, 5.5))
        ax.hist(valid, bins=30, color="#38bdf8", edgecolor="#0f172a")
        ax.set_title(_safe_map_title(f"{dataset_name} histogram"))
        ax.set_xlabel("Value")
        ax.set_ylabel("Frequency")
        ax.grid(alpha=0.2)
        plt.tight_layout()
        fig.savefig(output_path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        manager.last_plot_path = str(output_path)
        manager.log_operation("栅格直方图", f"{dataset_name} band {band} -> {output_path.name}", "plot")
        return f"直方图已生成: {output_path}"

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
    def dem_terrain_derivatives(dem_name: str, output_prefix: str, derivatives: str = "slope,aspect,terrain") -> str:
        """Create DEM derivatives such as slope, aspect, terrain factor, TPI, or TRI rasters."""
        inputs = {"dem_name": dem_name, "output_prefix": output_prefix, "derivatives": derivatives}
        errors = validate_dataset_exists(manager, dem_name) + validate_output_path(manager.derived_dir, output_prefix)
        if not errors:
            errors.extend(validate_raster_readable(manager, dem_name))
            errors.extend(validate_crs(manager, dem_name))
        requested = [item.strip().lower() for item in str(derivatives or "").split(",") if item.strip()] or ["slope", "aspect", "terrain"]
        invalid = [item for item in requested if item not in {"slope", "aspect", "terrain", "tpi", "tri"}]
        if invalid:
            return tool_result_error("dem_terrain_derivatives", inputs=inputs, error_code="DEM_DERIVATIVE_UNSUPPORTED", error_title="Unsupported DEM derivative", user_message=f"Unsupported derivatives: {', '.join(invalid)}.").to_json()
        if errors:
            return _tool_error_from_validation("dem_terrain_derivatives", inputs, errors)
        try:
            raster_path = manager.get_raster_path(dem_name)
            with rasterio.open(raster_path) as src:
                band = src.read(1, masked=True).astype("float32")
                arr = np.asarray(band.filled(np.nan), dtype="float32")
                xres = abs(float(src.transform.a)) or 1.0
                yres = abs(float(src.transform.e)) or 1.0
            gy, gx = np.gradient(arr, yres, xres)
            slope = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))
            aspect = (np.degrees(np.arctan2(-gx, gy)) + 360.0) % 360.0
            padded = np.pad(arr, 1, mode="edge")
            neighborhood_mean = sum(padded[y:y + arr.shape[0], x:x + arr.shape[1]] for y in range(3) for x in range(3)) / 9.0
            tpi = arr - neighborhood_mean
            tri = np.sqrt(gx * gx + gy * gy)
            arrays = {"slope": slope, "aspect": aspect, "terrain": tpi, "tpi": tpi, "tri": tri}
            datasets: list[str] = []
            artifacts: list[ArtifactInfo] = []
            for derivative in requested:
                suffix = "terrain" if derivative == "tpi" else derivative
                stored_name, output_path, _ = _write_raster_dataset_like(raster_path, f"{output_prefix}_{suffix}", arrays[derivative], source_tool="dem_terrain_derivatives", meta_updates={"source_dem": dem_name, "derivative": derivative})
                datasets.append(stored_name)
                artifacts.append(ArtifactInfo(f"raster:{output_path.name}", str(output_path), "raster", f"{stored_name} DEM derivative", f"{derivative} derived from DEM {dem_name}.", "created", False))
            return tool_result_ok("dem_terrain_derivatives", inputs=inputs, outputs={"datasets": datasets, "map_ready": True, "map_layer_ids": [_map_layer_id(name) for name in datasets]}, artifacts=artifacts, summary=f"Created DEM derivative datasets: {', '.join(datasets)}.").to_json()
        except Exception as exc:
            return _tool_internal_error("dem_terrain_derivatives", inputs, exc)

    @tool
    def raster_reproject(raster_name: str, target_crs: str, output_name: str, resampling: str = "bilinear") -> str:
        """Reproject a raster dataset and register the output as a map-ready GeoTIFF."""
        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject

        inputs = {"raster_name": raster_name, "target_crs": target_crs, "output_name": output_name, "resampling": resampling}
        errors = validate_dataset_exists(manager, raster_name) + validate_output_path(manager.derived_dir, output_name, allowed_suffixes={".tif", ".tiff"})
        if not errors:
            errors.extend(validate_raster_readable(manager, raster_name))
            errors.extend(validate_crs(manager, raster_name))
        if errors:
            return _tool_error_from_validation("raster_reproject", inputs, errors)
        try:
            source_path = manager.get_raster_path(raster_name)
            output_stem = Path(output_name).stem if Path(output_name).suffix else output_name
            output_path = manager.derived_dir / f"{_artifact_safe_name(output_stem)}.tif"
            mode = getattr(Resampling, str(resampling or "bilinear"), Resampling.bilinear)
            with rasterio.open(source_path) as src:
                transform, width, height = calculate_default_transform(src.crs, target_crs, src.width, src.height, *src.bounds)
                profile = src.profile.copy()
                profile.update(crs=target_crs, transform=transform, width=width, height=height)
                with rasterio.open(output_path, "w", **profile) as dst:
                    for index in range(1, src.count + 1):
                        reproject(source=rasterio.band(src, index), destination=rasterio.band(dst, index), src_transform=src.transform, src_crs=src.crs, dst_transform=transform, dst_crs=target_crs, resampling=mode)
            stored_name = manager.put_raster_path(output_stem, output_path, meta={"crs": target_crs, "source_raster": raster_name, "resampling": str(resampling), "map_ready": True, "map_layer_id": _map_layer_id(output_stem), "layer_kind": _dataset_map_kind(output_stem, "raster"), "source_tool": "raster_reproject"})
            return tool_result_ok("raster_reproject", inputs=inputs, outputs={**_map_ready_outputs(manager, stored_name, source_tool="raster_reproject"), "path": str(output_path), "target_crs": target_crs}, artifacts=[ArtifactInfo(f"raster:{output_path.name}", str(output_path), "raster", f"{stored_name} reprojected raster", "", "created", False)], summary=f"Reprojected raster {raster_name} to {target_crs} as {stored_name}.").to_json()
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
            first_dataset = next(iter(mapping.values()))
            first_path = manager.get_raster_path(first_dataset)
            with rasterio.open(first_path) as reference:
                shape = (reference.height, reference.width)
            arrays: dict[str, np.ndarray] = {}
            for variable, dataset_name in mapping.items():
                with rasterio.open(manager.get_raster_path(dataset_name)) as src:
                    if (src.height, src.width) != shape:
                        raise ValueError("All input rasters must have the same width and height in raster_algebra.")
                    band = src.read(1, masked=True).astype("float32")
                    arrays[variable] = np.asarray(band.filled(np.nan), dtype="float32")
            safe_np = type("SafeNumpy", (), {name: getattr(np, name) for name in ["where", "clip", "log", "log1p", "sqrt", "abs", "minimum", "maximum", "sin", "cos", "tan"]})
            result = eval(compile(parsed, "<raster_algebra>", "eval"), {"__builtins__": {}, "np": safe_np}, arrays)
            stored_name, output_path, _ = _write_raster_dataset_like(first_path, output_name, np.asarray(result, dtype="float32"), source_tool="raster_algebra", meta_updates={"expression": expression, "input_rasters": mapping})
            return tool_result_ok("raster_algebra", inputs=inputs, outputs={**_map_ready_outputs(manager, stored_name, source_tool="raster_algebra"), "path": str(output_path), "expression": expression}, artifacts=[ArtifactInfo(f"raster:{output_path.name}", str(output_path), "raster", f"{stored_name} raster algebra", "", "created", False)], summary=f"Created raster algebra output {stored_name}.").to_json()
        except Exception as exc:
            return _tool_internal_error("raster_algebra", inputs, exc)

    @tool
    def export_dataset(dataset_name: str, output_path: str) -> str:
        """将已有结果导出到指定路径。矢量默认导出为 GeoJSON，表格导出为 CSV，栅格直接复制，文档导出为文本。"""
        inputs = {"dataset_name": dataset_name, "output_path": output_path}
        errors = validate_dataset_exists(manager, dataset_name)
        if not str(output_path or "").strip():
            errors.append(
                {
                    "error_code": "OUTPUT_PATH_REQUIRED",
                    "error_title": "缺少导出路径",
                    "user_message": "请指定导出文件路径。",
                    "next_actions": ["提供 output_path，例如 results/output.csv。"],
                    "diagnostics": {},
                }
            )
        else:
            errors.extend(validate_output_file_path(manager.workdir, output_path))
        if errors:
            return _tool_error_from_validation("export_dataset", inputs, errors)
        try:
            record = manager.get(dataset_name)
            raw_target = Path(output_path)
            target = raw_target.resolve() if raw_target.is_absolute() else (manager.workdir / raw_target).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            export_details: dict[str, Any] = {}
            export_warnings: list[dict[str, Any]] = []

            if record.data_type == "vector":
                gdf = manager.get_vector(dataset_name)
                suffix = target.suffix.lower()
                if suffix == ".geojson":
                    gdf.to_file(target, driver="GeoJSON")
                elif suffix in {".shp", ".zip"}:
                    zip_target = target if suffix == ".zip" else target.with_suffix(".zip")
                    staging = target.parent / f".{target.stem}_shp_{uuid4().hex[:8]}"
                    staging.mkdir(parents=True, exist_ok=True)
                    export_warnings.append(
                        {
                            "code": "SHAPEFILE_ZIP_PACKAGE",
                            "message": "Shapefile exports are delivered as a zip package containing .shp/.shx/.dbf and available sidecar files.",
                            "next_actions": ["Use the zip file as the downloadable artifact; keep sidecar files together."],
                        }
                    )
                    long_field_names = [str(col) for col in gdf.columns if str(col) != "geometry" and len(str(col)) > 10]
                    if long_field_names:
                        export_warnings.append(
                            {
                                "code": "SHAPEFILE_FIELD_NAME_TRUNCATION",
                                "message": "ESRI Shapefile limits DBF field names to 10 characters; long names may be truncated by the writer.",
                                "fields": long_field_names,
                                "next_actions": ["Use GeoJSON when full field names must be preserved.", "Check exported DBF field names before downstream analysis."],
                            }
                        )
                    try:
                        shp_path = staging / f"{target.stem}.shp"
                        writer_stderr = io.StringIO()
                        previous_cpl_log = pyogrio.get_gdal_config_option("CPL_LOG")
                        pyogrio.set_gdal_config_options({"CPL_LOG": os.devnull})
                        with warnings.catch_warnings(record=True) as captured_warnings:
                            warnings.simplefilter("always")
                            try:
                                with contextlib.redirect_stderr(writer_stderr):
                                    gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="UTF-8")
                            finally:
                                pyogrio.set_gdal_config_options({"CPL_LOG": previous_cpl_log})
                        cpg_path = staging / f"{target.stem}.cpg"
                        if not cpg_path.exists():
                            cpg_path.write_text("UTF-8", encoding="ascii")
                        members = sorted(path for path in staging.glob(f"{target.stem}.*") if path.is_file())
                        with zipfile.ZipFile(zip_target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                            for member in members:
                                archive.write(member, arcname=member.name)
                        target = zip_target
                        export_details = {
                            "format": "shapefile_zip",
                            "requested_format": suffix,
                            "encoding": "UTF-8",
                            "members": [member.name for member in members],
                            "limitations": ["field_names_limited_to_10_characters", "multi_file_format_packaged_as_zip"],
                            "writer_warnings": [
                                *[str(item.message) for item in captured_warnings],
                                *[line.strip() for line in writer_stderr.getvalue().splitlines() if line.strip()],
                            ],
                        }
                    finally:
                        shutil.rmtree(staging, ignore_errors=True)
                else:
                    gdf.to_file(target)
            elif record.data_type == "table":
                df = manager.get_table(dataset_name)
                if target.suffix.lower() in {".xlsx", ".xls"}:
                    df.to_excel(target, index=False)
                else:
                    df.to_csv(target, index=False)
            elif record.data_type == "raster":
                source = manager.get_raster_path(dataset_name)
                shutil.copy2(source, target)
            elif record.data_type == "document":
                target.write_text(manager.get_document_text(dataset_name), encoding="utf-8")
            else:
                return tool_result_error(
                    "export_dataset",
                    inputs=inputs,
                    error_code="UNSUPPORTED_DATASET_TYPE",
                    error_title="数据类型不支持导出",
                    user_message=f"当前数据类型 {record.data_type} 暂不支持导出。",
                    diagnostics={"dataset_type": record.data_type},
                    next_actions=["请选择表格、矢量、栅格或文档数据集。"],
                ).to_json()

            manager.log_operation("导出结果", f"{dataset_name} -> {target}", "export")
            return tool_result_ok(
                "export_dataset",
                inputs=inputs,
                outputs={"path": str(target), "dataset_name": dataset_name, "dataset_type": record.data_type, **export_details},
                artifacts=[
                    ArtifactInfo(
                        artifact_id=f"file:{target.name}",
                        path=str(target),
                        type="file",
                        title=target.name,
                        description=f"Exported {record.data_type} dataset {dataset_name}",
                        quality_status="ok",
                        preview_available=target.suffix.lower() in {".csv", ".txt", ".json", ".geojson"},
                    )
                ],
                summary=f"已导出 {dataset_name} 到 {target}。",
                diagnostics={
                    "dataset_type": record.data_type,
                    "path": str(target),
                    "bytes": int(target.stat().st_size) if target.exists() else 0,
                    "shapefile_encoding": export_details.get("encoding"),
                    "shapefile_limitations": export_details.get("limitations", []),
                    "shapefile_members": export_details.get("members", []),
                },
                warnings=export_warnings,
                next_actions=["可下载或在外部 GIS/表格软件中打开导出文件。"],
            ).to_json()
        except Exception as exc:
            return _tool_internal_error("export_dataset", inputs, exc)
        record = manager.get(dataset_name)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if record.data_type == "vector":
            gdf = manager.get_vector(dataset_name)
            driver = "GeoJSON" if target.suffix.lower() == ".geojson" else None
            if driver:
                gdf.to_file(target, driver=driver)
            else:
                gdf.to_file(target)
        elif record.data_type == "table":
            df = manager.get_table(dataset_name)
            if target.suffix.lower() in {".xlsx", ".xls"}:
                df.to_excel(target, index=False)
            else:
                df.to_csv(target, index=False)
        elif record.data_type == "raster":
            source = manager.get_raster_path(dataset_name)
            shutil.copy2(source, target)
        elif record.data_type == "document":
            target.write_text(manager.get_document_text(dataset_name), encoding="utf-8")
        else:
            raise ValueError(f"暂不支持导出的数据类型: {record.data_type}")

        manager.log_operation("导出结果", f"{dataset_name} -> {target}", "export")
        return f"导出完成: {target}"

    base_tools = [
        workspace_status,
        list_datasets,
        load_dataset,
        describe_dataset,
        preview_table,
        preview_document,
        document_outline,
        search_document_text,
        generic_xgboost_workflow,
        detect_coordinate_fields,
        rename_dataset,
        database_status,
        list_database_objects,
        explain_database_training_pipeline,
        list_pipeline_runs,
        show_pipeline_run,
        sync_dataset_to_database,
        sync_all_to_database,
        query_workspace_database,
        profile_missing_values,
        vector_filter,
        vector_buffer,
        vector_clip_by_vector,
        vector_overlay,
        vector_dissolve,
        vector_spatial_join,
        reproject_vector,
        table_to_points,
        create_centroids,
        calculate_geometry_fields,
        join_attributes,
        summarize_points_within_polygons,
        raster_basic_stats,
        raster_zonal_stats,
        clip_raster_by_vector,
        raster_mosaic,
        dem_terrain_derivatives,
        raster_reproject,
        raster_algebra,
        extract_raster_values_to_points,
        batch_register_points_to_rasters,
        build_time_features,
        aggregate_time_series,
        evaluate_prediction_accuracy,
        geographical_conformal_prediction,
        btch_fusion_model,
        train_rf_fusion_model,
        train_xgboost_fusion_model,
        train_lstm_fusion_model,
        generate_thesis_charts,
        generate_stage_report,
        generate_model_comparison_summary,
        run_database_training_pipeline,
        plot_dataset,
        raster_histogram,
        export_dataset,
    ]
    return base_tools + build_resource_tools(manager)
