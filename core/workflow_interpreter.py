from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dataset_label(context: dict[str, Any] | None) -> str:
    ctx = _as_dict(context)
    dataset = _as_dict(ctx.get("active_dataset"))
    return str(dataset.get("name") or ctx.get("active_dataset") or "当前数据集")


def _step_result(step: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(step.get("tool_result"))


def _outputs_text(outputs: dict[str, Any]) -> str:
    if not outputs:
        return "无结构化输出"
    pairs: list[str] = []
    for key in (
        "result_dataset",
        "feature_count",
        "fields_added",
        "field_name",
        "path",
        "column",
        "model_result_id",
        "metrics_dataset",
        "prediction_column",
        "format",
        "source_dataset",
        "source_path",
    ):
        if outputs.get(key) not in (None, ""):
            pairs.append(f"{key}={outputs[key]}")
    return "; ".join(pairs) if pairs else str(outputs)


def _diagnostics_text(diagnostics: dict[str, Any]) -> str:
    if not diagnostics:
        return ""
    pairs: list[str] = []
    for key, value in diagnostics.items():
        if value in (None, ""):
            continue
        if isinstance(value, (dict, list, tuple)) and not value:
            continue
        pairs.append(f"{key}={value}")
        if len(pairs) >= 8:
            break
    return "; ".join(pairs)


def _artifacts(workflow_result: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _as_list(workflow_result.get("final_artifacts")) if isinstance(item, dict)]


def _artifact_lines(artifacts: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in artifacts:
        title = str(item.get("title") or item.get("name") or item.get("type") or "artifact")
        path = str(item.get("path") or item.get("display_path") or "")
        artifact_type = str(item.get("type") or "file")
        lines.append(f"- {artifact_type}: {title}" + (f" -> {path}" if path else ""))
    return lines


def _action_for_tool(tool_name: str) -> str:
    return {
        "describe_dataset": "检查数据结构、字段、路径和基础元数据",
        "field_match": "确认用户表达中的字段概念和真实字段之间的匹配关系",
        "vector_clip_by_vector": "用边界或研究区裁剪输入矢量数据",
        "plot_dataset": "根据指定字段生成地图图件",
        "train_xgboost_fusion_model": "训练 XGBoost 空间/表格预测模型并输出指标",
        "train_rf_fusion_model": "训练随机森林预测模型并输出指标",
        "export_dataset": "把数据集导出为指定格式文件",
        "export_artifact": "把已有图件或文件复制为导出成果",
        "interpret_result": "整理前面步骤的输出，准备面向用户解释",
    }.get(tool_name, f"执行 {tool_name}")


def _why_for_tool(tool_name: str) -> str:
    return {
        "describe_dataset": "先检查数据可以避免字段、类型、坐标系或路径问题在后续工具中才暴露。",
        "field_match": "字段匹配用于把自然语言概念稳定落到真实字段，避免误用不存在的字段。",
        "vector_clip_by_vector": "裁剪能把分析范围限制在研究区内，减少无关要素对制图和统计的干扰。",
        "plot_dataset": "制图用于查看字段的空间分布、局部异常和整体格局。",
        "train_xgboost_fusion_model": "建模用于评估目标变量与特征之间的预测关系并生成诊断指标。",
        "train_rf_fusion_model": "建模用于评估目标变量与特征之间的预测关系并生成诊断指标。",
        "export_dataset": "导出让处理结果可以在外部 GIS 或表格软件中继续使用。",
        "export_artifact": "导出让图件或文件可以下载、归档或用于报告。",
        "interpret_result": "解释步骤把工具输出转成可追问的结论和下一步建议。",
    }.get(tool_name, "该步骤来自任务规划，用于推进当前 GIS 工作流。")


def _step_explanation(step: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(step.get("tool_name") or "")
    step_name = str(step.get("step_id") or tool_name or "workflow_step")
    status = str(step.get("status") or "pending")
    args = _as_dict(step.get("validated_tool_args"))
    result = _step_result(step)
    outputs = _as_dict(result.get("outputs"))
    diagnostics = _as_dict(result.get("diagnostics"))
    diagnostics_note = _diagnostics_text(diagnostics)
    warnings = [str(item) for item in _as_list(result.get("warnings")) if str(item).strip()]
    failure_reason = ""
    if status == "failed" or not result.get("ok", True):
        failure_reason = f"{result.get('error_code') or 'WORKFLOW_STEP_FAILED'} - {result.get('user_message') or result.get('error_title') or '该步骤执行失败'}"
    next_actions = [str(item) for item in _as_list(result.get("next_actions")) if str(item).strip()]
    return {
        "step_name": step_name,
        "action": _action_for_tool(tool_name),
        "input": args,
        "output": outputs,
        "status": status,
        "explanation": f"{_why_for_tool(tool_name)} 输出：{_outputs_text(outputs)}" + (f"；diagnostics：{diagnostics_note}" if diagnostics_note else "") + "。",
        "warnings": warnings,
        "failure_reason": failure_reason,
        "next_action": next_actions[0] if next_actions else ("继续检查后续输出。" if status == "success" else "修正该步骤输入后重试。"),
    }


def _final_interpretation(workflow_result: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    artifacts = _artifacts(workflow_result)
    artifact_types = {str(item.get("type") or "").lower() for item in artifacts}
    failed_step = str(workflow_result.get("failed_step") or "")
    if failed_step:
        failed = next((item for item in steps if item["step_name"] == failed_step), {})
        reason = str(failed.get("failure_reason") or "未返回具体失败原因")
        if "FIELD_NOT_FOUND" in reason:
            return f"工作流在 {failed_step} 失败：{reason}。这通常表示制图或建模字段不存在，需重新选择真实字段。"
        if "OBJECT_NOT_FOUND" in reason:
            return f"工作流在 {failed_step} 失败：{reason}。这通常表示数据集、图层、边界或图件引用不存在，需重新选择对象。"
        return f"工作流在 {failed_step} 失败：{reason}。后续依赖该步骤的操作没有继续执行。"

    text: list[str] = []
    if "map" in artifact_types or "plot" in artifact_types:
        text.append("地图结果可用于观察空间分布、局部异常和研究区内的梯度变化；异常区域只能作为线索，仍需结合字段含义、坐标系、采样密度和外部背景数据验证。")
    if "dataset" in artifact_types:
        clip_outputs = [_as_dict(_step_result(step).get("outputs")) for step in _as_list(workflow_result.get("steps")) if _as_dict(step).get("tool_name") == "vector_clip_by_vector"]
        feature_counts = [str(item.get("feature_count")) for item in clip_outputs if item.get("feature_count") not in (None, "")]
        suffix = f" 保留要素数：{', '.join(feature_counts)}。" if feature_counts else ""
        text.append(f"裁剪或处理结果已经生成新的数据集，可继续用于制图、导出或后续空间分析。{suffix}")
    if {"metrics", "model", "summary"} & artifact_types or any("model_result_id" in _as_dict(_step_result(step).get("outputs")) for step in _as_list(workflow_result.get("steps"))):
        text.append("模型结果需要重点查看 R、RMSE、MAE、Bias、NSE、特征重要性和残差空间分布；这些指标说明预测精度、系统偏差、变量贡献和空间误差聚集情况。")
    if {"table", "file"} & artifact_types:
        text.append("表格或文件结果可用于检查关键字段、导出记录和异常值；如果包含统计结果，应继续核对样本量、缺失值和字段单位。")
    return "\n".join(text) if text else "工作流已完成，但最终 artifact 类型不足以做更细解释；建议查看每一步 outputs 和 diagnostics。"


def _summary(workflow_result: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    steps = _as_list(workflow_result.get("steps"))
    artifacts = _artifacts(workflow_result)
    used_datasets: list[str] = []
    for step in steps:
        args = _as_dict(_as_dict(step).get("validated_tool_args"))
        for key in ("dataset_name", "clip_name", "raster_name", "vector_name", "point_name", "polygon_name"):
            value = str(args.get(key) or "")
            if value and not value.startswith("$steps.") and value not in used_datasets:
                used_datasets.append(value)
    if not used_datasets:
        used_datasets.append(_dataset_label(context))
    return {
        "completed": bool(workflow_result.get("ok")),
        "workflow_id": str(workflow_result.get("workflow_id") or ""),
        "used_data": used_datasets,
        "final_results": [{"type": item.get("type"), "title": item.get("title") or item.get("name"), "path": item.get("path")} for item in artifacts],
        "summary": str(workflow_result.get("final_summary") or ("Workflow completed." if workflow_result.get("ok") else "Workflow failed.")),
    }


def _next_actions(workflow_result: dict[str, Any], final_interpretation: str) -> list[str]:
    actions = [str(item) for item in _as_list(workflow_result.get("next_actions")) if str(item).strip()]
    if workflow_result.get("failed_step"):
        defaults = ["补齐失败步骤缺少的数据、字段或边界对象。", "重新运行工作流前先检查数据字段和坐标系。"]
    elif "地图结果" in final_interpretation:
        defaults = ["查看地图异常区域的属性值。", "导出图件或裁剪后的数据集。", "叠加研究区边界或辅助因子验证空间格局。"]
    elif "模型结果" in final_interpretation:
        defaults = ["查看模型指标和特征重要性。", "检查残差空间分布。", "必要时补充特征或重新划分验证集。"]
    else:
        defaults = ["查看输出文件。", "继续做结果解释或导出。"]
    merged = []
    for item in [*actions, *defaults]:
        if item not in merged:
            merged.append(item)
    return merged[:4]


def _markdown(summary: dict[str, Any], steps: list[dict[str, Any]], final_interpretation: str, actions: list[str], workflow_result: dict[str, Any]) -> str:
    lines = [
        "**工作流总结**",
        f"- workflow_id: {summary['workflow_id']}",
        f"- 状态: {'成功' if summary['completed'] else '失败'}",
        f"- 使用数据: {', '.join(summary['used_data'])}",
        "- 最终结果:",
    ]
    result_lines = [f"  - {item.get('type')}: {item.get('title') or ''} -> {item.get('path') or ''}" for item in summary["final_results"]]
    lines.extend(result_lines or ["  - 无最终 artifact"])

    if workflow_result.get("failed_step"):
        completed = [step["step_name"] for step in steps if step["status"] == "success"]
        skipped = [step["step_name"] for step in steps if step["status"] == "skipped"]
        lines.extend(
            [
                "",
                "**失败定位**",
                f"- 失败步骤: {workflow_result.get('failed_step')}",
                "- 已完成步骤: " + (", ".join(completed) if completed else "无"),
                "- 未执行步骤: " + (", ".join(skipped) if skipped else "无"),
            ]
        )

    lines.extend(["", "**逐步解释**"])
    for step in steps:
        lines.extend(
            [
                f"- {step['step_name']} [{step['status']}]",
                f"  - action: {step['action']}",
                f"  - input: {step['input']}",
                f"  - output: {step['output']}",
                f"  - explanation: {step['explanation']}",
                f"  - failure_reason: {step['failure_reason'] or '无'}",
                f"  - next_action: {step['next_action']}",
            ]
        )
        if step["warnings"]:
            lines.append(f"  - warnings: {'; '.join(step['warnings'])}")

    lines.extend(
        [
            "",
            "**结果解读**",
            final_interpretation,
            "",
            "**下一步建议**",
            *[f"- {item}" for item in actions],
        ]
    )
    return "\n".join(lines)


def interpret_workflow_result(
    workflow_result: dict[str, Any],
    prompt: str = "",
    context: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del prompt, plan
    payload = _as_dict(workflow_result)
    step_explanations = [_step_explanation(step) for step in _as_list(payload.get("steps")) if isinstance(step, dict)]
    workflow_summary = _summary(payload, context)
    final_interpretation = _final_interpretation(payload, step_explanations)
    user_next_actions = _next_actions(payload, final_interpretation)
    markdown_reply = _markdown(workflow_summary, step_explanations, final_interpretation, user_next_actions, payload)
    return {
        "workflow_summary": workflow_summary,
        "step_explanations": step_explanations,
        "final_interpretation": final_interpretation,
        "user_next_actions": user_next_actions,
        "markdown_reply": markdown_reply,
    }
