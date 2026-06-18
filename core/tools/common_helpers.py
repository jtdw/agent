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

from core.data_manager import DataManager
from core.model_results import generate_model_result_id
from core.tool_contracts import ArtifactInfo, parse_tool_result, tool_result_error, tool_result_ok
from core.tool_preconditions import (
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
