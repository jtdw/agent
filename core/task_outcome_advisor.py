from __future__ import annotations

import re
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_model_result(dashboard: dict[str, Any]) -> dict[str, Any]:
    for item in _as_list(dashboard.get("model_results")):
        if isinstance(item, dict):
            return item
    return {}


def _artifact_paths(artifacts: list[Any], limit: int = 6) -> list[str]:
    paths: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or "成果文件")
        path = str(item.get("display_path") or item.get("path") or item.get("download_url") or "")
        if path:
            paths.append(f"{label}: {path}")
        if len(paths) >= limit:
            break
    return paths


def _metric_summary(metrics: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("R", "RMSE", "ubRMSE", "Bias", "NSE", "MAE"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{key}={value:.4g}")
    return ", ".join(parts)


def _compact_upload_message(message: str) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    loaded = None
    for pattern in (
        r"(?:已加载数据集|已加载数据)\s*[:：]\s*([^\s\[（(。\n;；]+)",
        r"Loaded dataset\s+([^\s(]+)",
    ):
        match = re.search(pattern, text)
        if match:
            loaded = match.group(1).strip()
            break
    if loaded:
        return f"已加载数据：{loaded}。"

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first_line = first_line.split("[", 1)[0].strip()
    first_line = first_line.split("{", 1)[0].strip()
    if len(first_line) > 100:
        first_line = first_line[:97].rstrip() + "..."
    return first_line


def _dataset_upload_detail(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "").strip()
    if not name:
        return ""
    data_type = str(item.get("type") or item.get("data_type") or "").strip()
    meta = _as_dict(item.get("meta"))
    details: list[str] = []
    rows = meta.get("rows") or item.get("row_count")
    columns = _as_list(meta.get("columns"))
    if rows is not None:
        details.append(f"{rows} 行")
    if columns:
        details.append(f"{len(columns)} 个字段")
    if data_type:
        details.insert(0, data_type)
    return f"{name}（{'，'.join(details)}）" if details else name


def _download_paths(result: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("job", "scene_job", "tile_job"):
        job = _as_dict(result.get(key))
        for field in ("zip_path", "output_path", "download_url"):
            value = str(job.get(field) or "")
            if value:
                paths.append(value)
    return list(dict.fromkeys(paths))


def _upload_summary(result: dict[str, Any], dashboard: dict[str, Any]) -> str:
    count = result.get("count")
    messages = list(
        dict.fromkeys(
            item
            for item in (_compact_upload_message(str(value)) for value in _as_list(result.get("messages")))
            if item
        )
    )
    datasets = [
        item
        for item in (_dataset_upload_detail(value) for value in _as_list(dashboard.get("datasets")) if isinstance(value, dict))
        if item
    ]
    lines = []
    if count:
        lines.append(f"已处理 {count} 个上传文件。")
    if messages:
        lines.append(" ".join(messages[:4]))
    if datasets:
        dataset_text = "；".join(datasets[:6])
        suffix = f" 等 {len(datasets)} 个数据集" if len(datasets) > 6 else ""
        lines.append(f"当前工作区数据集：{dataset_text}{suffix}。")
    return "\n".join(lines) or "上传任务已完成。"


def build_task_outcome(task_type: str, result: dict[str, Any] | None = None, *, dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _as_dict(result)
    dashboard = _as_dict(dashboard)
    clean_type = str(task_type or "general").strip() or "general"
    outcome: dict[str, Any] = {
        "task_type": clean_type,
        "status": "completed",
        "has_results": False,
        "summary": "",
        "result_paths": [],
        "metrics": {},
        "recommendations": [],
    }

    if clean_type in {"analysis", "model", "workflow"}:
        model_result = _first_model_result(dashboard)
        if not model_result:
            outcome.update(
                has_results=False,
                summary=str(result.get("reply") or "当前没有可展示的分析结果。"),
                result_paths=[],
                recommendations=[
                    "先上传或导入可分析的数据，再运行制图、建模或结果分析任务。",
                    "如果已经上传数据，请先执行字段、坐标、时间和缺失值检查。",
                ],
            )
            return outcome

        metrics = _as_dict(model_result.get("metrics"))
        artifacts = _as_list(model_result.get("artifacts"))
        paths = _artifact_paths(artifacts)
        advice = [str(item) for item in _as_list(model_result.get("recommendations")) if str(item).strip()]
        metric_text = _metric_summary(metrics)
        model_name = str(model_result.get("model") or "模型结果")
        prefix = str(model_result.get("output_prefix") or model_result.get("metrics_dataset") or "")
        prefix_text = f"结果前缀：{prefix}。" if prefix else ""
        metric_summary = f"关键指标：{metric_text}。" if metric_text else ""
        outcome.update(
            has_results=True,
            summary=f"{model_name} 分析已完成。{prefix_text}{metric_summary}",
            result_paths=paths,
            metrics=metrics,
            recommendations=advice or [
                "打开指标表和特征重要性表，确认模型精度与关键驱动因子。",
                "继续做 GCP 不确定性分析、残差空间分布图和论文图表输出。",
            ],
        )
        return outcome

    if clean_type == "download":
        paths = _download_paths(result)
        job = _as_dict(result.get("job"))
        status = str(job.get("status") or result.get("status") or "submitted")
        status_label = "完成" if status in {"completed", "success"} else "提交或启动"
        outcome.update(
            status=status,
            has_results=bool(paths or job),
            summary=f"下载任务已{status_label}。任务号：{job.get('job_id') or '--'}。",
            result_paths=paths,
            recommendations=[
                "先检查下载文件是否可解压、坐标系是否正确，并确认能在地图中显示。",
                "如果是 DEM，下一步建议裁剪到研究区并生成坡度、坡向、地形因子。",
                "如果是遥感产品，下一步建议按边界裁剪、重投影，并与站点或目标变量做时间匹配。",
            ],
        )
        return outcome

    if clean_type == "upload":
        dataset_count = len(_as_list(dashboard.get("datasets")))
        outcome.update(
            has_results=bool(result.get("count") or dataset_count),
            summary=_upload_summary(result, dashboard),
            result_paths=[],
            recommendations=[
                "下一步先检查字段、坐标、时间和缺失值，避免直接建模导致错误。",
                "如果包含经纬度或矢量边界，可以加载到地图检查空间范围是否正确。",
                "如果目标是 XGBoost/RF/LSTM，建议先明确目标变量和候选特征列。",
            ],
        )
        return outcome

    artifacts = _as_list(dashboard.get("artifacts"))
    outcome.update(
        has_results=bool(artifacts or result.get("reply")),
        summary=str(result.get("reply") or "任务已完成。"),
        result_paths=_artifact_paths(artifacts),
        recommendations=[
            "查看成果文件和分析结果面板，确认输出是否符合任务目标。",
            "如果结果可用，建议导出成果包；如果结果不足，继续补充字段、边界或时间条件。",
        ],
    )
    return outcome


def format_task_outcome_markdown(outcome: dict[str, Any]) -> str:
    if not outcome or not outcome.get("has_results"):
        return ""
    lines = ["", "任务结果分析：", str(outcome.get("summary") or "").strip()]
    paths = [str(item) for item in _as_list(outcome.get("result_paths")) if str(item).strip()]
    if paths:
        lines.extend(["", "结果位置：", *[f"- {item}" for item in paths[:6]]])
    recommendations = [str(item) for item in _as_list(outcome.get("recommendations")) if str(item).strip()]
    if recommendations:
        lines.extend(["", "推荐下一步：", *[f"- {item}" for item in recommendations[:5]]])
    return "\n".join(lines).rstrip()
