from __future__ import annotations

import re
from urllib.parse import unquote, urlparse
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


def _looks_like_path_or_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    parsed = urlparse(text)
    if parsed.scheme or lowered.startswith(("data:", "javascript:", "file:", "http:", "https:")):
        return True
    if re.match(r"^[a-zA-Z]:[\\/]", text):
        return True
    normalized = unquote(text).replace("\\", "/")
    if normalized.startswith(("/api/files/artifact?", "/api/artifacts/", "/api/downloads/artifact?", "/")):
        return True
    if "workspace/users/" in normalized or "workspace/sessions/" in normalized:
        return True
    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts):
        return True
    if "/" in normalized:
        return True
    return False


def _artifact_ref(item: dict[str, Any]) -> str:
    for key in ("title", "label", "name", "filename", "original_filename", "artifact_id", "id"):
        value = str(item.get(key) or "").strip()
        if value and not _looks_like_path_or_url(value):
            return value
    return ""


def _artifact_paths(artifacts: list[Any], limit: int = 6) -> list[str]:
    refs: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        if not str(item.get("artifact_id") or item.get("id") or "").strip():
            continue
        ref = _artifact_ref(item)
        if ref:
            refs.append(ref)
        if len(refs) >= limit:
            break
    return refs


def _safe_result_refs(values: Any, limit: int = 6) -> list[str]:
    refs: list[str] = []
    for item in _as_list(values):
        text = str(item or "").strip()
        if text and not _looks_like_path_or_url(text):
            refs.append(text)
        if len(refs) >= limit:
            break
    return list(dict.fromkeys(refs))


def _display_path(value: Any) -> str:
    if _looks_like_path_or_url(value):
        return ""
    return str(value or "").strip()


def _metric_summary(metrics: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("R", "RMSE", "ubRMSE", "Bias", "NSE", "MAE"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{key}={value:.4g}")
    return ", ".join(parts)


def _canonical_artifact_refs(result: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for container_key, refs_key in (
        ("management_view", "artifact_refs"),
        ("presentation_result", "artifact_refs"),
    ):
        container = _as_dict(result.get(container_key))
        for item in _as_list(container.get(refs_key)):
            artifact = _as_dict(item)
            label = str(artifact.get("title") or artifact.get("artifact_id") or "").strip()
            if label:
                refs.append(label)
    tool_result = _as_dict(result.get("tool_result"))
    for item in _as_list(tool_result.get("artifacts")):
        artifact = _as_dict(item)
        label = str(artifact.get("title") or artifact.get("artifact_id") or artifact.get("filename") or "").strip()
        if label:
            refs.append(label)
    return list(dict.fromkeys(refs))


def _upload_summary(result: dict[str, Any], dashboard: dict[str, Any]) -> str:
    count = result.get("count")
    messages = [str(item) for item in _as_list(result.get("messages")) if str(item).strip()]
    datasets = [str(item.get("name") or "") for item in _as_list(dashboard.get("datasets")) if isinstance(item, dict)]
    lines = []
    if count:
        lines.append(f"已处理 {count} 个上传文件。")
    if messages:
        lines.append("；".join(messages[:4]))
    if datasets:
        dataset_text = ", ".join([name for name in datasets if name][:8])
        lines.append(f"当前工作区数据集：{dataset_text}。")
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
        presentation = _as_dict(result.get("presentation_result"))
        if presentation:
            refs = []
            for key in ("artifact_refs", "map_layer_refs", "table_refs", "image_refs"):
                for item in _as_list(presentation.get(key)):
                    ref = _as_dict(item)
                    label = str(ref.get("title") or ref.get("name") or ref.get("artifact_id") or ref.get("layer_id") or ref.get("table_id") or ref.get("image_id") or "").strip()
                    if label:
                        refs.append(label)
            outcome.update(
                status=str(presentation.get("status") or "completed"),
                has_results=bool(refs or presentation.get("concise_summary") or presentation.get("result_highlights")),
                summary=str(presentation.get("concise_summary") or result.get("reply") or "分析已完成。"),
                result_paths=_safe_result_refs(refs),
                metrics={},
                recommendations=[str(item) for item in _as_list(presentation.get("next_action_suggestions")) if str(item).strip()],
            )
            return outcome

        user_result = _as_dict(result.get("user_facing_result"))
        if user_result:
            outcome.update(
                has_results=bool(user_result.get("primary_artifacts") or user_result.get("preview_artifacts") or user_result.get("summary")),
                summary=str(user_result.get("summary") or result.get("reply") or "分析已完成。"),
                result_paths=[],
                metrics=_as_dict(user_result.get("metrics")),
                recommendations=[str(item) for item in _as_list(user_result.get("next_actions")) if str(item).strip()],
            )
            return outcome

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
        management = _as_dict(result.get("management_view"))
        tool_result = _as_dict(result.get("tool_result"))
        presentation = _as_dict(result.get("presentation_result"))
        paths = _canonical_artifact_refs(result)
        status = str(management.get("status") or tool_result.get("status") or presentation.get("status") or result.get("status") or "running")
        status_label = "完成" if status in {"completed", "success", "succeeded"} else "提交或启动"
        task_id = str(management.get("task_id") or tool_result.get("task_id") or "--")
        summary = str(management.get("user_message") or presentation.get("concise_summary") or "")
        if summary and task_id != "--":
            summary = f"{summary} 任务号：{task_id}。"
        if not summary:
            summary = f"下载任务已{status_label}。任务号：{task_id}。"
        outcome.update(
            status=status,
            has_results=bool(paths or management or tool_result or presentation),
            summary=summary,
            result_paths=paths,
            recommendations=[str(item) for item in _as_list(tool_result.get("next_actions")) if str(item).strip()]
            or [str(item) for item in _as_list(presentation.get("next_action_suggestions")) if str(item).strip()]
            or ["检查下载产物、坐标系和地图加载状态；如失败，请按可用操作重试或重新登录。"],
        )
        return outcome

    if clean_type == "upload":
        dataset_count = len(_as_list(dashboard.get("datasets")))
        dataset_names = [str(item.get("name") or "") for item in _as_list(dashboard.get("datasets")) if isinstance(item, dict) and str(item.get("name") or "").strip()]
        dataset_text = "、".join(dataset_names[:3])
        upload_messages = [str(item) for item in _as_list(result.get("messages")) if str(item).strip()]
        uploaded_text = "；".join(upload_messages[:3])
        summary = "上传成功。"
        if uploaded_text:
            summary = f"上传成功：{uploaded_text}。"
        if dataset_text:
            summary = f"{summary.rstrip('。')}。已加载数据集：{dataset_text}。"
        outcome.update(
            has_results=bool(result.get("count") or dataset_count),
            summary=summary,
            result_paths=[],
            recommendations=[],
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
    paths = _safe_result_refs(outcome.get("result_paths"))
    if paths:
        lines.extend(["", "结果引用：", *[f"- {item}" for item in paths[:6]]])
    recommendations = [str(item) for item in _as_list(outcome.get("recommendations")) if str(item).strip()]
    if recommendations:
        lines.extend(["", "推荐下一步：", *[f"- {item}" for item in recommendations[:5]]])
    return "\n".join(lines).rstrip()
