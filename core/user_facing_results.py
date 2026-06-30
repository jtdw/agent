from __future__ import annotations

import csv
import json
import mimetypes
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from .tool_contracts import is_tool_result_success

_PRIVATE_DETAIL_KEYS = {
    "path",
    "absolute_path",
    "relative_path",
    "display_path",
    "source_path",
    "output_path",
    "zip_path",
    "download_url",
    "url",
    "direct_url",
    "local_file_path",
    "request_text",
    "status_path",
    "log_path",
    "storage_state_path",
    "state_path",
    "user_id",
    "session_id",
    "account_id",
    "token",
    "password",
    "cookie",
    "cookies",
}
_PRIVATE_DETAIL_TEXT_MARKERS = (
    "traceback",
    "storage_state",
    "token=",
    "cookie",
    "/api/files/artifact",
    "/api/downloads/artifact",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed == parsed else None


def _fmt(value: Any, digits: int = 4) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "--"
    return f"{parsed:.{digits}g}"


def _looks_private_detail_text(value: Any) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    if not text:
        return False
    if any(marker in lowered for marker in _PRIVATE_DETAIL_TEXT_MARKERS):
        return True
    if (
        ":\\" in text
        or "\\workspace\\" in text
        or "/workspace/" in text
        or text.startswith(("/tmp/", "/home/", "/var/", "/etc/", "/root/", "/Users/"))
    ):
        return True
    if text.startswith(("http://", "https://", "file:", "/api/files/artifact", "/api/downloads/artifact")):
        return True
    return False


def _public_detail_value(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _PRIVATE_DETAIL_KEYS:
                continue
            cleaned = _public_detail_value(item)
            if cleaned in ({}, [], ""):
                continue
            output[key_text] = cleaned
        return output
    if isinstance(value, list):
        output = [_public_detail_value(item) for item in value]
        return [item for item in output if item not in ({}, [], "")]
    if isinstance(value, str):
        return "" if _looks_private_detail_text(value) else value[:500]
    return value


def _filename(artifact: dict[str, Any]) -> str:
    for key in ("filename", "name", "title"):
        value = str(artifact.get(key) or "").strip()
        if value and not any(sep in value for sep in ("\\", "/")):
            return value
    path = str(artifact.get("path") or artifact.get("absolute_path") or artifact.get("relative_path") or "")
    return Path(path).name if path else "result"


def _mime_type(artifact: dict[str, Any], filename: str) -> str:
    return str(artifact.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream")


def _artifact_kind(artifact: dict[str, Any], filename: str = "") -> str:
    text = f"{artifact.get('type') or ''} {artifact.get('kind') or ''} {filename}".lower()
    suffix = Path(filename).suffix.lower()
    if "image" in text or suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return "image"
    if suffix in {".csv", ".xlsx", ".xls"} or any(token in text for token in ("predictions", "residuals", "metrics", "feature_importance", "table")):
        return "table"
    if suffix in {".json", ".geojson"}:
        return "json" if suffix == ".json" else "gis"
    if suffix in {".md", ".txt"} or "report" in text:
        return "markdown"
    if suffix in {".joblib", ".pkl"} or "model" in text:
        return "model"
    if suffix in {".tif", ".tiff", ".shp", ".zip"} or any(token in text for token in ("raster", "dataset", "vector", "shp")):
        return "gis"
    return "file"


def _artifact_title(artifact: dict[str, Any], filename: str, kind: str) -> str:
    raw_type = str(artifact.get("type") or "").lower()
    title = str(artifact.get("title") or artifact.get("label") or artifact.get("name") or "").lower()
    image_name = str(_as_dict(artifact.get("meta")).get("image_name") or "").lower()
    if raw_type == "predictions":
        return "预测结果表"
    if raw_type == "residuals":
        return "残差结果表"
    if raw_type in {"metrics", "metrics_json"}:
        return "模型指标摘要"
    if raw_type == "feature_importance" and "legacy" not in title:
        return "特征重要性表"
    if raw_type == "model":
        return "模型文件"
    if raw_type == "report":
        return "建模报告"
    if raw_type == "summary":
        return "模型摘要 JSON"
    if raw_type == "diagnostics":
        return "高级诊断表"
    if kind == "image":
        if "feature_importance" in image_name or "feature importance" in title:
            return "特征重要性图"
        if "pred_vs_actual" in image_name or "predicted vs actual" in title:
            return "预测值 vs 真实值图"
        if "residual_distribution" in image_name:
            return "残差分布图"
        if "residual_spatial" in image_name or "residual spatial" in title:
            return "残差空间分布图"
        if "prediction_spatial" in image_name or "prediction spatial" in title:
            return "预测空间分布图"
        return str(artifact.get("title") or "图像结果")
    return str(artifact.get("title") or filename)


def _canonical_download_url(artifact: dict[str, Any], artifact_id: str) -> str:
    if not artifact_id:
        return ""
    url = str(artifact.get("download_url") or "").strip()
    prefix = f"/api/artifacts/{artifact_id}/download"
    if url == prefix or url.startswith(f"{prefix}?"):
        return url
    return ""


def _artifact_group(artifact: dict[str, Any], filename: str, kind: str, title: str) -> str:
    raw_type = str(artifact.get("type") or "").lower()
    title_l = f"{title} {filename} {artifact.get('title') or ''}".lower()
    if "legacy" in title_l or raw_type == "diagnostics" or "moran" in title_l:
        return "高级诊断"
    if title in {"模型指标摘要", "特征重要性图", "预测值 vs 真实值图", "残差空间分布图"}:
        return "推荐查看"
    if kind == "image":
        return "图像结果"
    if raw_type in {"predictions", "residuals", "metrics", "metrics_json", "feature_importance", "dataset"} or kind in {"table", "json"}:
        return "数据结果"
    if raw_type in {"model", "report", "summary"} or kind in {"model", "markdown"}:
        return "模型与报告"
    return "数据结果"


def _priority(title: str, group: str, filename: str) -> int:
    order = {
        "模型指标摘要": 1,
        "特征重要性图": 2,
        "预测值 vs 真实值图": 3,
        "残差空间分布图": 4,
        "预测结果表": 5,
        "残差结果表": 6,
        "特征重要性表": 7,
        "建模报告": 8,
    }
    base = order.get(title, 50)
    if group == "高级诊断":
        base += 100
    if "legacy" in filename.lower():
        base += 100
    return base


def _read_csv_preview(path: Path, rows: int = 20) -> dict[str, Any]:
    preview_rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = [str(item) for item in (reader.fieldnames or [])]
        for index, row in enumerate(reader):
            if index >= rows:
                break
            preview_rows.append({str(key): value for key, value in row.items()})
    return {"columns": columns, "rows": preview_rows}


def _read_text_preview(path: Path, max_chars: int = 4000) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def _preview_for_artifact(artifact: dict[str, Any], kind: str, filename: str) -> Any:
    raw_path = str(artifact.get("path") or "")
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return {"status": "missing"}
    try:
        suffix = path.suffix.lower()
        if kind == "table" and suffix == ".csv":
            return _read_csv_preview(path)
        if suffix == ".json":
            return json.loads(_read_text_preview(path, max_chars=8000))
        if kind == "markdown" or suffix in {".md", ".txt"}:
            return _read_text_preview(path)
    except Exception as exc:
        return {"status": "preview_failed", "reason": type(exc).__name__}
    return None


def public_artifact_card(artifact: dict[str, Any], *, include_preview: bool = True) -> dict[str, Any]:
    filename = _filename(artifact)
    kind = _artifact_kind(artifact, filename)
    title = _artifact_title(artifact, filename, kind)
    group = _artifact_group(artifact, filename, kind, title)
    mime_type = _mime_type(artifact, filename)
    artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or "")
    previewable = kind in {"image", "table", "json", "markdown", "gis"} and kind != "model"
    raw_path = str(artifact.get("path") or artifact.get("absolute_path") or "")
    status = "available"
    if raw_path and (not Path(raw_path).exists() or not Path(raw_path).is_file()):
        status = "missing"
    card = {
        "artifact_id": artifact_id,
        "title": title,
        "description": str(artifact.get("description") or ""),
        "filename": filename,
        "artifact_type": kind,
        "type": kind,
        "kind": kind,
        "mime_type": mime_type,
        "previewable": bool(previewable),
        "preview_available": bool(artifact.get("preview_available") or previewable),
        "download_url": _canonical_download_url(artifact, artifact_id),
        "group": group,
        "priority": _priority(title, group, filename),
        "hidden_by_default": group == "高级诊断",
        "source_tool": str(artifact.get("source_tool") or _as_dict(artifact.get("source")).get("tool_name") or ""),
        "status": status,
    }
    if include_preview and previewable and kind != "image":
        preview = _preview_for_artifact(artifact, kind, filename)
        if preview not in (None, ""):
            card["preview"] = preview
    if _as_dict(artifact.get("meta")).get("map_ready") or kind == "gis":
        card["map_ready"] = bool(_as_dict(artifact.get("meta")).get("map_ready") or kind == "gis")
    return card


def _dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for card in sorted(cards, key=lambda item: int(item.get("priority") or 99)):
        key = str(card.get("artifact_id") or card.get("filename") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(card)
    return output


def _step_tool_names(workflow_result: dict[str, Any]) -> set[str]:
    return {str(_as_dict(step).get("tool_name") or "") for step in _as_list(workflow_result.get("steps")) if isinstance(step, dict)}


def _find_step(workflow_result: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for step in _as_list(workflow_result.get("steps")):
        if isinstance(step, dict) and str(step.get("tool_name") or "") == tool_name:
            return step
    return {}


def _find_step_by_id(workflow_result: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in _as_list(workflow_result.get("steps")):
        if isinstance(step, dict) and str(step.get("step_id") or "") == step_id:
            return step
    return {}


def _result_from_step(step: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(step.get("tool_result"))


def _modeling_step(workflow_result: dict[str, Any]) -> dict[str, Any]:
    for name in ("train_xgboost_fusion_model", "generic_xgboost_workflow", "train_rf_fusion_model", "geographical_conformal_prediction"):
        step = _find_step(workflow_result, name)
        if step:
            return step
    return {}


def _collect_artifacts(workflow_result: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = [item for item in _as_list(workflow_result.get("final_artifacts")) if isinstance(item, dict)]
    if artifacts:
        return artifacts
    for step in _as_list(workflow_result.get("steps")):
        artifacts.extend(item for item in _as_list(_result_from_step(_as_dict(step)).get("artifacts")) if isinstance(item, dict))
    return artifacts


def _csv_numeric_stats(path: Path, column: str) -> dict[str, float] | None:
    values: list[float] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                value = _safe_float(row.get(column))
                if value is not None:
                    values.append(value)
    except Exception:
        return None
    if not values:
        return None
    return {"min": min(values), "max": max(values), "mean": sum(values) / len(values), "n": float(len(values))}


def _top_features_from_artifacts(artifacts: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    candidates = []
    for artifact in artifacts:
        filename = _filename(artifact).lower()
        title = str(artifact.get("title") or "").lower()
        if "feature_importance" not in filename and "importance" not in title:
            continue
        if "legacy" in title or "_xgb_importance" in filename:
            continue
        candidates.append(artifact)
    for artifact in candidates:
        path = Path(str(artifact.get("path") or ""))
        if not path.exists() or path.suffix.lower() != ".csv":
            continue
        rows: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    feature = str(row.get("feature") or row.get("variable") or "").strip()
                    importance = _safe_float(row.get("importance") or row.get("gain") or row.get("value"))
                    if feature and importance is not None:
                        rows.append({"feature": feature, "importance": importance})
        except Exception:
            continue
        rows.sort(key=lambda item: float(item.get("importance") or 0), reverse=True)
        return rows[:limit]
    return []


def _prediction_stats_from_artifacts(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    for artifact in artifacts:
        if str(artifact.get("type") or "").lower() != "predictions":
            continue
        path = Path(str(artifact.get("path") or ""))
        if path.exists():
            stats = _csv_numeric_stats(path, "y_true")
            if stats:
                return stats
    return {}


def _metric_scope(metrics: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(metrics.get("spatial_cv"), dict):
        return _as_dict(metrics.get("spatial_cv")), _as_dict(metrics.get("final_model_in_sample"))
    if isinstance(metrics.get("overall"), dict):
        return _as_dict(metrics.get("overall")), {}
    return metrics, {}


def _xgboost_insights(step: dict[str, Any], artifacts: list[dict[str, Any]]) -> tuple[list[str], list[str], dict[str, Any]]:
    result = _result_from_step(step)
    diagnostics = _as_dict(result.get("diagnostics"))
    outputs = _as_dict(result.get("outputs"))
    metrics_all = _as_dict(diagnostics.get("metrics"))
    metrics, train_metrics = _metric_scope(metrics_all)
    spatial = _as_dict(diagnostics.get("spatial_diagnostics"))
    sample_count = int(_safe_float(metrics.get("n")) or _safe_float(outputs.get("sample_count")) or 0)
    if not sample_count:
        sample_count = int(_safe_float(_prediction_stats_from_artifacts(artifacts).get("n")) or 0)
    prediction_stats = _prediction_stats_from_artifacts(artifacts)
    top_features = _top_features_from_artifacts(artifacts)
    insights: list[str] = []
    warnings: list[str] = []
    if prediction_stats:
        insights.append(
            "目标变量真实值范围约 "
            f"{_fmt(prediction_stats.get('min'))} 到 {_fmt(prediction_stats.get('max'))}，"
            f"均值约 {_fmt(prediction_stats.get('mean'))}。"
        )
    rmse = _safe_float(metrics.get("RMSE"))
    mae = _safe_float(metrics.get("MAE"))
    nse = _safe_float(metrics.get("NSE"))
    if rmse is not None or mae is not None or nse is not None:
        quality = "较好" if (nse is not None and nse >= 0.75) else "一般" if (nse is not None and nse >= 0.4) else "需要谨慎"
        insights.append(f"空间交叉验证 RMSE={_fmt(rmse)}，MAE={_fmt(mae)}，NSE={_fmt(nse)}，整体预测效果{quality}。")
    bias = _safe_float(metrics.get("Bias"))
    if bias is not None:
        direction = "低估" if bias < -1e-9 else "高估" if bias > 1e-9 else "无明显系统偏差"
        insights.append(f"Bias={_fmt(bias)}，当前验证结果显示模型{direction}。")
    moran = _safe_float(spatial.get("moran_i"))
    p_value = _safe_float(spatial.get("p_value"))
    if moran is not None:
        if p_value is not None and p_value >= 0.05:
            insights.append(f"残差 Moran's I={_fmt(moran)}，p={_fmt(p_value)}，未显示显著空间自相关；仍建议查看残差空间分布图。")
        elif p_value is not None:
            insights.append(f"残差 Moran's I={_fmt(moran)}，p={_fmt(p_value)}，残差可能存在空间聚集，需要检查遗漏空间因子。")
        else:
            insights.append(f"残差 Moran's I={_fmt(moran)}，可用于判断误差是否空间聚集。")
    if top_features:
        feature_text = "、".join(f"{item['feature']}({_fmt(item['importance'])})" for item in top_features)
        insights.append(f"前三个重要特征为 {feature_text}，应结合业务机理检查其合理性。")
    if sample_count and sample_count < 80:
        warnings.append(f"样本量为 {sample_count}，数量偏少，空间交叉验证指标可能仍不稳定。")
    train_rmse = _safe_float(train_metrics.get("RMSE"))
    if rmse is not None and train_rmse is not None and train_rmse > 0 and rmse / train_rmse >= 3:
        warnings.append("训练集表现明显好于空间交叉验证，不要只看 in-sample 指标，应重点关注空间泛化能力。")
    if top_features and float(top_features[0].get("importance") or 0) >= 0.6:
        warnings.append(f"{top_features[0]['feature']} 的重要性占比很高，建议检查是否存在数据泄漏、伪相关或空间代理变量。")
    debug = {"metrics": metrics_all, "spatial_diagnostics": spatial, "top_features": top_features, "prediction_stats": prediction_stats}
    return insights, warnings, debug


def _xgboost_next_actions(warnings: list[str], artifacts: list[dict[str, Any]], debug: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if any("样本量" in item for item in warnings):
        actions.append("增加样本数量或扩展时间范围，再重新评估空间交叉验证指标。")
    if any("空间交叉验证" in item for item in warnings):
        actions.append("优先检查空间泛化能力，必要时调整空间分块或补充区域性特征。")
    spatial = _as_dict(debug.get("spatial_diagnostics"))
    p_value = _safe_float(spatial.get("p_value"))
    if p_value is not None and p_value >= 0.05:
        actions.append("残差未显示明显空间聚集，但建议优先查看残差空间分布图确认局部异常。")
    top_features = _as_list(debug.get("top_features"))
    if top_features and _safe_float(_as_dict(top_features[0]).get("importance")) and float(_as_dict(top_features[0]).get("importance") or 0) >= 0.6:
        actions.append("检查最高重要性特征是否存在数据泄漏、伪相关或与采样位置强绑定。")
    image_names = " ".join(_filename(item).lower() for item in artifacts if str(item.get("type") or "").lower() == "image")
    if image_names:
        actions.append("优先查看特征重要性图、预测值 vs 真实值图和残差空间分布图。")
    actions.append("结果文件已完整生成，可继续做 GCP 不确定性分析。")
    return list(dict.fromkeys(actions))[:5]


def _make_bundle(manager: Any, artifacts: list[dict[str, Any]], *, workflow_id: str, label: str, suffix: str) -> dict[str, Any] | None:
    if manager is None or not artifacts:
        return None
    safe_workflow = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in (workflow_id or "workflow"))[:80]
    zip_path = Path(manager.derived_dir) / f"{safe_workflow}_{suffix}.zip"
    used_names: set[str] = set()
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for artifact in artifacts:
                path = Path(str(artifact.get("path") or ""))
                if not path.exists() or not path.is_file():
                    continue
                arcname = path.name
                if arcname in used_names:
                    arcname = f"{path.stem}_{len(used_names) + 1}{path.suffix}"
                used_names.add(arcname)
                archive.write(path, arcname=arcname)
        if not used_names:
            zip_path.unlink(missing_ok=True)
            return None
        return manager.register_artifact(
            artifact_id=f"bundle_{suffix}_{uuid4().hex[:10]}",
            path=str(zip_path),
            type="bundle",
            title=label,
            description="打包后的结果文件，下载时仍通过 artifact 权限校验。",
            quality_status="created",
            preview_available=False,
            source_tool="user_facing_result",
        )
    except Exception:
        return None


def _workflow_kind(workflow_result: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    tools = _step_tool_names(workflow_result)
    task_type = str(_as_dict(plan).get("task_type") or "")
    if {"train_xgboost_fusion_model", "generic_xgboost_workflow", "train_rf_fusion_model"} & tools or task_type == "modeling":
        return "modeling"
    if "geographical_conformal_prediction" in tools:
        return "uncertainty"
    if any(name.startswith("raster_") or "raster" in name for name in tools):
        return "raster"
    if any(name.startswith("vector_") or "vector" in name or name == "table_to_points" for name in tools):
        return "vector"
    if any("download" in name for name in tools):
        return "download"
    if "plot_dataset" in tools:
        return "map"
    return "generic"


def build_user_facing_result_from_workflow(
    workflow_result: dict[str, Any],
    *,
    manager: Any = None,
    context: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = _as_dict(context)
    workflow_id = str(workflow_result.get("workflow_id") or "")
    raw_artifacts = _collect_artifacts(workflow_result)
    cards = _dedupe_cards([public_artifact_card(item) for item in raw_artifacts])
    groups: list[dict[str, Any]] = []
    for group_name in ["推荐查看", "数据结果", "图像结果", "模型与报告", "高级诊断"]:
        items = [item for item in cards if item.get("group") == group_name]
        if items:
            groups.append({"group": group_name, "default_expanded": group_name in {"推荐查看", "数据结果"}, "artifacts": items})
    primary = [item for item in cards if item.get("group") == "推荐查看"][:5]
    if not primary:
        primary = [item for item in cards if not item.get("hidden_by_default")][:5]
    primary_ids = {str(item.get("artifact_id") or "") for item in primary}
    secondary = [item for item in cards if str(item.get("artifact_id") or "") not in primary_ids and not item.get("hidden_by_default")]
    preview = [item for item in cards if item.get("previewable") and item.get("artifact_type") in {"image", "table", "json", "markdown"}][:8]
    kind = _workflow_kind(workflow_result, plan)
    summary = "工作流已完成，结果已整理为可预览和可下载的成果。"
    key_findings: list[str] = []
    insights: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    technical_details: dict[str, Any] = {
        "workflow_id": workflow_id,
        "workflow_type": kind,
        "steps": _as_list(workflow_result.get("steps")),
        "diagnostics": _as_dict(workflow_result.get("diagnostics")),
    }
    debug: dict[str, Any] = {"workflow_id": workflow_id, "workflow_type": kind}
    next_actions = ["查看推荐结果和数据结果。", "需要复核过程时展开技术详情。"]

    if str(workflow_result.get("status") or "") not in {"", "succeeded"} or not bool(workflow_result.get("success", workflow_result.get("ok", True))):
        failed_step = str(workflow_result.get("failed_step") or "")
        failed_result = _result_from_step(_find_step_by_id(workflow_result, failed_step)) if failed_step else {}
        message = str(failed_result.get("user_message") or failed_result.get("error_title") or "工作流执行失败。")
        error_code = str(failed_result.get("error_code") or "")
        key_findings = [f"失败步骤: {failed_step}"] if failed_step else []
        if error_code:
            key_findings.append(error_code)
        return {
            "schema_version": "user-facing-result/v1",
            "summary": f"任务未完成：{message}",
            "key_findings": key_findings,
            "primary_artifacts": primary,
            "secondary_artifacts": secondary,
            "preview_artifacts": preview,
            "grouped_artifacts": groups,
            "download_bundle": None,
            "metrics": {},
            "insights": [],
            "warnings": [message],
            "next_actions": [str(item) for item in _as_list(workflow_result.get("next_actions")) if str(item).strip()] or ["检查失败步骤的输入数据、字段和文件是否仍然存在，然后重试。"],
            "technical_details": technical_details,
            "debug": debug,
        }

    model_step = _modeling_step(workflow_result)
    model_tool = str(model_step.get("tool_name") or "")
    if model_tool == "train_xgboost_fusion_model":
        result = _result_from_step(model_step)
        outputs = _as_dict(result.get("outputs"))
        diagnostics = _as_dict(result.get("diagnostics"))
        metrics_all = _as_dict(diagnostics.get("metrics"))
        primary_metrics, train_metrics = _metric_scope(metrics_all)
        metrics = primary_metrics
        features = [str(item) for item in _as_list(_as_dict(_as_dict(manager.get_model_result(outputs.get("model_result_id")) if manager and outputs.get("model_result_id") else {}).get("diagnostics")).get("features"))]
        if not features:
            features = [str(item) for item in _as_list(_as_dict(diagnostics.get("features")))]
        target = str(outputs.get("target_column") or _as_dict(diagnostics.get("target_col")).get("target_col") or "目标变量")
        sample_count = int(_safe_float(primary_metrics.get("n")) or 0)
        validation = "空间分块验证" if _as_dict(diagnostics.get("spatial_diagnostics")) else "模型验证"
        summary = f"已完成 XGBoost 建模。模型使用 {sample_count or '--'} 条样本，以 {target} 为目标变量"
        if features:
            summary += "，使用 " + "、".join(features) + " 作为特征"
        summary += f"，并启用了{validation}。"
        key_findings = [
            f"空间交叉验证 RMSE = {_fmt(primary_metrics.get('RMSE'))}",
            f"MAE = {_fmt(primary_metrics.get('MAE'))}",
            f"NSE = {_fmt(primary_metrics.get('NSE'))}",
            f"Bias = {_fmt(primary_metrics.get('Bias'))}",
        ]
        spatial = _as_dict(diagnostics.get("spatial_diagnostics"))
        if spatial:
            key_findings.append(f"Moran's I = {_fmt(spatial.get('moran_i'))}，p = {_fmt(spatial.get('p_value'))}")
        insights, warnings, model_debug = _xgboost_insights(model_step, raw_artifacts)
        model_debug["train_metrics"] = train_metrics
        debug.update({key: value for key, value in model_debug.items() if key != "raw_workflow_result"})
        technical_details.update(model_debug)
        next_actions = _xgboost_next_actions(warnings, raw_artifacts, model_debug)
    elif kind == "modeling":
        metrics = _as_dict(_as_dict(_result_from_step(model_step).get("diagnostics")).get("metrics"))
        summary = "建模工作流已完成，模型指标、图像和结果文件已整理为可下载成果。"
        key_findings = [f"{key} = {_fmt(value)}" for key, value in metrics.items() if _safe_float(value) is not None][:6]
        insights = ["请优先查看模型指标、特征重要性和残差相关结果。"]
    elif kind == "map":
        summary = "地图制图已完成，图像预览和下载文件已整理在结果卡片中。"
        insights = ["地图可用于查看空间分布、局部异常和研究区内梯度变化。"]
    elif kind == "raster":
        summary = "栅格处理已完成，结果数据和可下载文件已整理。"
        insights = ["请检查栅格范围、坐标系、nodata 和统计值是否符合预期。"]
    elif kind == "vector":
        summary = "矢量/表格空间处理已完成，结果数据和下载文件已整理。"
        insights = ["请检查结果要素数量、字段和空间范围是否符合任务目标。"]

    all_bundle = _make_bundle(manager, raw_artifacts, workflow_id=workflow_id, label="完整结果包.zip", suffix="all_results")
    recommended_raw = [
        artifact
        for artifact in raw_artifacts
        if str(artifact.get("artifact_id") or "") in {str(item.get("artifact_id") or "") for item in primary}
    ]
    recommended_bundle = _make_bundle(manager, recommended_raw or raw_artifacts[:5], workflow_id=workflow_id, label="推荐结果包.zip", suffix="recommended_results")
    download_bundle = {
        "all": public_artifact_card(all_bundle, include_preview=False) if all_bundle else None,
        "recommended": public_artifact_card(recommended_bundle, include_preview=False) if recommended_bundle else None,
    }
    return {
        "schema_version": "user-facing-result/v1",
        "summary": summary,
        "key_findings": key_findings,
        "primary_artifacts": primary,
        "secondary_artifacts": secondary,
        "preview_artifacts": preview,
        "grouped_artifacts": groups,
        "download_bundle": download_bundle if download_bundle.get("all") or download_bundle.get("recommended") else None,
        "metrics": metrics,
        "insights": insights,
        "warnings": warnings,
        "next_actions": next_actions,
        "technical_details": technical_details,
        "debug": debug,
    }


def build_user_facing_result_from_tool_results(tool_results: list[Any], *, manager: Any = None) -> dict[str, Any]:
    raw_artifacts: list[dict[str, Any]] = []
    summaries: list[str] = []
    technical_details = {"tool_results": tool_results}
    debug = {"tool_count": len(tool_results)}
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        raw_artifacts.extend(item for item in _as_list(result.get("artifacts")) if isinstance(item, dict))
        if result.get("summary"):
            summaries.append(str(result.get("summary")))
    cards = _dedupe_cards([public_artifact_card(item) for item in raw_artifacts])
    primary = [item for item in cards if not item.get("hidden_by_default")][:5]
    all_bundle = _make_bundle(manager, raw_artifacts, workflow_id=f"tool_{uuid4().hex[:8]}", label="完整结果包.zip", suffix="all_results")
    ok = all(is_tool_result_success(_as_dict(result)) for result in tool_results if isinstance(result, dict))
    failed = next((_as_dict(result) for result in tool_results if isinstance(result, dict) and not is_tool_result_success(_as_dict(result))), {})
    return {
        "schema_version": "user-facing-result/v1",
        "summary": (summaries[0] if ok and summaries else str(failed.get("user_message") or failed.get("error_title") or "工具执行失败。")),
        "key_findings": summaries[:4],
        "primary_artifacts": primary,
        "secondary_artifacts": [item for item in cards if item not in primary and not item.get("hidden_by_default")],
        "preview_artifacts": [item for item in cards if item.get("previewable")][:8],
        "grouped_artifacts": [{"group": "结果文件", "default_expanded": True, "artifacts": cards}] if cards else [],
        "download_bundle": {"all": public_artifact_card(all_bundle, include_preview=False), "recommended": None} if all_bundle else None,
        "metrics": {},
        "insights": [],
        "warnings": [] if ok else [str(failed.get("error_code") or "TOOL_FAILED")],
        "next_actions": ["查看推荐结果。", "需要复核过程时展开技术详情。"] if ok else [str(item) for item in _as_list(failed.get("next_actions")) if str(item).strip()] or ["检查输入数据和参数后重试。"],
        "technical_details": technical_details,
        "debug": debug,
    }


def build_user_facing_result(value: Any, *, manager: Any = None, context: dict[str, Any] | None = None, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _as_dict(value)
    if {"workflow_id", "steps", "final_artifacts"}.issubset(payload):
        return build_user_facing_result_from_workflow(payload, manager=manager, context=context, plan=plan)
    if {"ok", "tool_name", "artifacts"}.issubset(payload):
        return build_user_facing_result_from_tool_results([payload], manager=manager)
    if isinstance(value, list):
        return build_user_facing_result_from_tool_results(value, manager=manager)
    public_details = _public_detail_value(payload)
    technical_details = public_details if isinstance(public_details, dict) else {}
    return {
        "schema_version": "user-facing-result/v1",
        "summary": str(payload.get("summary") or payload.get("message") or "任务结果已生成。"),
        "key_findings": [],
        "primary_artifacts": [],
        "secondary_artifacts": [],
        "preview_artifacts": [],
        "grouped_artifacts": [],
        "download_bundle": None,
        "metrics": {},
        "insights": [],
        "warnings": [],
        "next_actions": [],
        "technical_details": technical_details,
        "debug": {},
    }


def format_user_facing_reply(result: dict[str, Any]) -> str:
    lines: list[str] = [str(result.get("summary") or "任务已完成。")]
    key_findings = [str(item) for item in _as_list(result.get("key_findings")) if str(item).strip()]
    if key_findings:
        lines.extend(["", "核心指标：", *[f"- {item}" for item in key_findings[:8]]])
    insights = [str(item) for item in _as_list(result.get("insights")) if str(item).strip()]
    if insights:
        lines.extend(["", "结果解读：", *[f"- {item}" for item in insights[:8]]])
    warnings = [str(item) for item in _as_list(result.get("warnings")) if str(item).strip()]
    if warnings:
        lines.extend(["", "需要注意：", *[f"- {item}" for item in warnings[:5]]])
    primary = [item for item in _as_list(result.get("primary_artifacts")) if isinstance(item, dict)]
    if primary:
        lines.extend(["", "推荐查看：", *[f"- {item.get('title') or item.get('filename')}" for item in primary[:5]]])
    actions = [str(item) for item in _as_list(result.get("next_actions")) if str(item).strip()]
    if actions:
        lines.extend(["", "下一步建议：", *[f"- {item}" for item in actions[:5]]])
    return "\n".join(lines)
