from __future__ import annotations

from typing import Any

from .tool_contracts import parse_tool_result
from .workflow_executor import parse_workflow_result
from .workflow_interpreter import interpret_workflow_result


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dataset_label(context: dict[str, Any]) -> str:
    dataset = _as_dict(context.get("active_dataset"))
    return str(dataset.get("name") or context.get("active_dataset") or "当前数据集")


def _artifact_lines(items: list[Any], limit: int = 5) -> list[str]:
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("title") or item.get("name") or "成果文件")
        path = str(item.get("display_path") or item.get("path") or item.get("download_url") or "")
        lines.append(f"- {label}" + (f": {path}" if path else ""))
        if len(lines) >= limit:
            break
    return lines


def _frontend_reference_note(context: dict[str, Any]) -> str:
    ref = _as_dict(context.get("referenced_object"))
    if ref.get("source") != "frontend_context":
        return ""
    ref_type = str(ref.get("type") or "")
    label = str(ref.get("label") or ref.get("id") or ref.get("path") or "")
    if ref_type == "artifact":
        return f"我正在解释你当前选中的图件或结果文件：{label}。"
    if ref_type == "feature":
        props = _as_dict(ref.get("properties"))
        preview = "，".join(f"{k}={v}" for k, v in list(props.items())[:6])
        return f"我正在解释你当前选中的地图要素：{label}" + (f"；关键属性：{preview}。" if preview else "。")
    if ref_type == "layer":
        return f"我正在解释你当前选中的地图图层：{label}。"
    if ref_type == "map_bounds":
        return f"我正在分析你当前地图视野范围：{ref.get('bounds')}。"
    if ref_type == "model_result":
        return f"我正在解释你当前选中的模型结果：{label}。"
    return ""


def _format_tool_result_reply(tool_result: dict[str, Any], context: dict[str, Any]) -> str:
    tool_name = str(tool_result.get("tool_name") or "GIS 工具")
    dataset = _dataset_label(context)
    if tool_name == "tool_executor":
        outputs = _as_dict(tool_result.get("outputs"))
        diagnostics = _as_dict(tool_result.get("diagnostics"))
        results = _as_list(outputs.get("tool_results")) or _as_list(diagnostics.get("tool_results"))
        executed = _as_list(outputs.get("executed_tools")) or [item.get("tool_name") for item in results if isinstance(item, dict)]
        result_lines: list[str] = []
        output_lines: list[str] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            name = str(item.get("tool_name") or "tool")
            if item.get("ok"):
                result_lines.append(f"- {name}: {item.get('summary') or 'ok'}")
            else:
                result_lines.append(f"- {name}: {item.get('error_code') or 'TOOL_FAILED'} - {item.get('user_message') or item.get('error_title') or 'failed'}")
            output_lines.extend(_artifact_lines(_as_list(item.get("artifacts"))))
        actions = "；".join(str(item) for item in _as_list(tool_result.get("next_actions")) if str(item).strip())
        if not actions:
            for item in results:
                if isinstance(item, dict) and not item.get("ok"):
                    actions = "；".join(str(action) for action in _as_list(item.get("next_actions")) if str(action).strip())
                    break
        return "\n".join(
            [
                "已完成操作：执行经过验证的确定性 GIS 工具计划。",
                f"使用的数据：{dataset}。",
                "关键结果：" + ("\n" + "\n".join(result_lines) if result_lines else f"已执行工具：{', '.join(str(x) for x in executed)}"),
                "输出文件：" + ("\n" + "\n".join(output_lines) if output_lines else " 本次没有登记新的输出文件。"),
                "结果含义：这些结果来自工具返回的 ToolResult，可继续用于追问、制图、空间处理或结果解释。",
                "可能问题：" + (str(tool_result.get("error_code") or tool_result.get("user_message")) if not tool_result.get("ok") else "暂未发现明确警告。"),
                "下一步建议：" + (actions or "查看输出并继续提出解释、制图或处理需求。"),
            ]
        )
    if not tool_result.get("ok"):
        actions = "；".join(str(item) for item in _as_list(tool_result.get("next_actions"))) or "请补齐输入后重试。"
        return "\n".join(
            [
                f"已完成操作：调用 {tool_name} 前置检查或执行。",
                f"使用的数据：{dataset}。",
                f"关键结果：{tool_result.get('error_code') or 'TOOL_FAILED'} - {tool_result.get('user_message') or tool_result.get('error_title') or '工具执行失败'}",
                "输出文件：本次失败，没有登记新的输出文件。",
                "结果含义：工具返回了结构化失败诊断，不需要依赖裸异常文本判断原因。",
                f"可能问题：{tool_result.get('technical_detail') or tool_result.get('error_title') or '输入不满足工具前置条件'}",
                f"下一步建议：{actions}",
            ]
        )
    output_lines = _artifact_lines(_as_list(tool_result.get("artifacts")))
    return "\n".join(
        [
            f"已完成操作：{tool_result.get('summary') or f'{tool_name} 已完成'}",
            f"使用的数据：{dataset}。",
            f"关键结果：{tool_result.get('outputs') or '工具返回成功。'}",
            "输出文件：" + ("\n" + "\n".join(output_lines) if output_lines else " 本次没有登记新的输出文件。"),
            "结果含义：工具返回了结构化结果，可基于 outputs、artifacts 和 diagnostics 继续解释。",
            "可能问题：" + ("；".join(str(item) for item in _as_list(tool_result.get("warnings"))) or "暂未发现明确警告。"),
            "下一步建议：" + ("；".join(str(item) for item in _as_list(tool_result.get("next_actions"))) or "可继续做结果解释、制图或导出。"),
        ]
    )


def _format_workflow_result_reply(workflow_result: dict[str, Any], context: dict[str, Any]) -> str:
    dataset = _dataset_label(context)
    steps = _as_list(workflow_result.get("steps"))
    step_lines: list[str] = []
    output_lines = _artifact_lines(_as_list(workflow_result.get("final_artifacts")), limit=8)
    failed_step = str(workflow_result.get("failed_step") or "")
    failed_message = ""
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("step_id") or "")
        tool_name = str(step.get("tool_name") or "")
        status = str(step.get("status") or "")
        result = _as_dict(step.get("tool_result"))
        outputs = _as_dict(result.get("outputs"))
        output_bits: list[str] = []
        for key in ("model_result_id", "metrics_dataset", "result_dataset", "prediction_column", "path"):
            if outputs.get(key):
                output_bits.append(f"{key}={outputs[key]}")
        output_note = f" ({'; '.join(output_bits)})" if output_bits else ""
        if status == "success":
            step_lines.append(f"- {step_id} ({tool_name}): success - {result.get('summary') or 'ok'}{output_note}")
        elif status == "failed":
            failed_message = f"{result.get('error_code') or 'WORKFLOW_STEP_FAILED'} - {result.get('user_message') or result.get('error_title') or 'step failed'}"
            step_lines.append(f"- {step_id} ({tool_name}): failed - {failed_message}{output_note}")
        elif status == "skipped":
            step_lines.append(f"- {step_id} ({tool_name}): skipped")
        else:
            step_lines.append(f"- {step_id} ({tool_name}): {status or 'pending'}")
    actions = "；".join(str(item) for item in _as_list(workflow_result.get("next_actions")) if str(item).strip())
    return "\n".join(
        [
            "已完成操作：执行多步 GIS 工作流（WorkflowResult）。",
            f"使用的数据：{dataset}。",
            "关键结果：" + ("\n" + "\n".join(step_lines) if step_lines else str(workflow_result.get("final_summary") or "")),
            "输出文件：" + ("\n" + "\n".join(output_lines) if output_lines else " 本次没有登记新的输出文件。"),
            "结果含义：工作流按步骤执行，并把上一步输出传给后续步骤；可基于最终 artifact 继续追问或分析。",
            "可能问题：" + (f"失败步骤 {failed_step}: {failed_message}" if failed_step else "暂未发现明确失败步骤。"),
            "下一步建议：" + (actions or "查看最终图件/数据集，并继续做结果解释、导出或后续空间分析。"),
        ]
    )


def _model_result(context: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any]:
    ref = _as_dict(context.get("referenced_object"))
    if ref.get("type") == "model_result" and not ref.get("missing"):
        data = ref.get("data")
        if isinstance(data, dict) and data:
            return data
    model = context.get("recent_model_result")
    if isinstance(model, dict) and model:
        return model
    for item in _as_list(dashboard.get("model_results")):
        if isinstance(item, dict):
            return item
    return {}


def _metrics_text(metrics: dict[str, Any]) -> str:
    labels = {
        "R": "相关性，越接近 1 越好",
        "RMSE": "均方根误差，越小越好",
        "MAE": "平均绝对误差，越小越好",
        "Bias": "系统偏差，越接近 0 越好",
        "NSE": "纳什效率系数，越接近 1 越好",
        "ubRMSE": "去偏均方根误差，越小越好",
        "PICP": "GCP 区间覆盖率，越接近名义覆盖率越好",
        "MPIW": "GCP 平均区间宽度，覆盖可靠时越小越紧致",
        "NMPIW": "归一化区间宽度，用于跨变量比较区间紧致性",
        "QCP": "条件覆盖偏差，用于检查不同分组或区间上的覆盖稳定性",
        "IS": "区间评分，同时惩罚区间过宽和未覆盖观测值",
    }
    parts: list[str] = []
    for key, explanation in labels.items():
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"- {key}={value:.4g}：{explanation}。")
        elif key in {"R", "RMSE", "MAE", "Bias", "NSE"}:
            parts.append(f"- {key}：当前结果中未识别到该指标，需要查看指标表确认。")
    return "\n".join(parts)


def _recommendations(plan: dict[str, Any], model: dict[str, Any], context: dict[str, Any]) -> list[str]:
    advice = [str(item) for item in _as_list(model.get("recommendations")) if str(item).strip()]
    if advice:
        return advice[:5]
    if str(plan.get("task_type") or "") == "modeling" or model:
        return ["检查特征重要性是否符合领域认知。", "查看残差空间分布，判断误差是否空间聚集。", "必要时做 GCP 不确定性分析或补充特征。"]
    if str(plan.get("task_type") or "") == "map_generation" or context.get("recent_map_path"):
        return ["核对坐标系和图层范围。", "检查异常区域是否与地形、土地利用或缺失值有关。", "补充图例、比例尺和数据来源说明。"]
    return ["先完成字段、坐标、时间和缺失值检查。", "明确目标后再进入制图、空间处理或建模。"]


def interpret_result(
    prompt: str,
    intent: dict[str, Any],
    plan: dict[str, Any],
    raw_reply: str,
    context: dict[str, Any],
    dashboard: Any,
) -> str:
    parsed_workflow_result = parse_workflow_result(raw_reply)
    if parsed_workflow_result is not None:
        reply = interpret_workflow_result(parsed_workflow_result, prompt=prompt, context=context, plan=plan).get("markdown_reply", "")
        note = _frontend_reference_note(context)
        return f"{note}\n{reply}" if note else reply

    parsed_tool_result = parse_tool_result(raw_reply)
    if parsed_tool_result is not None:
        reply = _format_tool_result_reply(parsed_tool_result, context)
        note = _frontend_reference_note(context)
        return f"{note}\n{reply}" if note else reply

    dashboard_dict = _as_dict(dashboard)
    task_type = str(plan.get("task_type") or intent.get("intent") or "general")
    dataset = _dataset_label(context)
    raw = str(raw_reply or "").strip()
    if not raw and plan.get("should_ask_clarification") and plan.get("clarification_question"):
        raw = str(plan["clarification_question"])

    referenced = _as_dict(context.get("referenced_object"))
    if referenced.get("type") == "model_result" and referenced.get("missing"):
        model_id = str(referenced.get("id") or referenced.get("label") or "selected model result")
        return "\n".join(
            [
                f"已完成操作：尝试定位你当前选中的模型结果 {model_id}。",
                f"使用的数据：{dataset}。",
                f"关键结果：找不到 model_result_id={model_id} 对应的模型结果记录。",
                "输出文件：未读取到该模型结果绑定的指标表、图件或模型文件。",
                "结果含义：前端传回了模型结果 ID，但后端模型结果注册表或 dashboard 中没有对应记录，因此不能可靠解释指标。",
                "可能问题：该结果可能来自旧会话、工作区已清理、模型结果尚未完成注册，或前端缓存了过期 ID。",
                "下一步建议：刷新分析结果面板后重新选择模型；如果刚完成建模，请先确认 dashboard 中 model_results 包含该 model_result_id。",
            ]
        )

    frontend_note = _frontend_reference_note(context)
    if frontend_note:
        raw = f"{frontend_note}\n{raw}" if raw else frontend_note

    if task_type == "troubleshooting":
        error = _as_dict(context.get("recent_error"))
        message = str(error.get("message") or error.get("error") or raw or "没有记录到具体错误。")
        return "\n".join(
            [
                "已完成操作：读取最近一次失败记录。",
                f"使用的数据：{dataset}。",
                f"关键结果：{message}",
                "输出文件：本次是错误解释，没有新的输出文件。",
                "结果含义：任务失败通常来自字段名不匹配、数据类型不符合工具前置条件、缺少 CRS、样本不足或外部服务不可用。",
                "可能问题：请优先核对报错中提到的字段、路径、CRS、样本数量和登录状态。",
                "下一步建议：根据错误信息补齐缺失输入后重试；如果不确定字段，请先让我检查数据字段和缺失值。",
            ]
        )

    model = _model_result(context, dashboard_dict)
    artifacts = _as_list(model.get("artifacts")) or _as_list(context.get("recent_artifacts"))
    output_lines = _artifact_lines(artifacts)

    if task_type == "map_generation" or (context.get("recent_map_path") and "图" in str(prompt)):
        map_path = str(context.get("recent_map_path") or "")
        return "\n".join(
            [
                "已完成操作：整理最近图件并生成地图结果解释。",
                f"使用的数据：{dataset}。",
                f"关键结果：{raw or '已定位最近图件，可从空间分布、异常区域和数据局限三个角度解释。'}",
                "输出文件：" + (f"\n- {map_path}" if map_path else ("\n" + "\n".join(output_lines) if output_lines else " 暂未识别到图件文件。")),
                "结果含义：重点看空间分布是否呈现聚集、梯度变化或局部异常；异常区域可能与地形、土地利用、观测缺失、重采样或坐标偏移有关。",
                "可能问题：地图只反映当前数据和制图字段，不能单独证明因果关系；若 CRS、范围或颜色分级不合适，图面判断会偏差。",
                "下一步建议：核对坐标系、叠加研究区边界，并对异常区域提取属性或栅格值进一步验证。",
            ]
        )

    if task_type in {"modeling", "result_analysis"} and model:
        metric_block = _metrics_text(_as_dict(model.get("metrics")))
        return "\n".join(
            [
                "已完成操作：整理模型结果并生成解释。",
                f"使用的数据：{dataset}。",
                f"关键结果：{raw or str(model.get('model') or model.get('model_name') or '模型结果已生成')}。",
                "输出文件：" + ("\n" + "\n".join(output_lines) if output_lines else " 暂未识别到输出文件。"),
                "结果含义：",
                metric_block,
                "特征重要性/鐗瑰緛閲嶈鎬?：用于判断哪些输入变量对预测贡献更大；需要结合领域知识排除伪相关。",
                "残差空间分布/娈嬪樊绌洪棿鍒嗗竷：用于检查误差是否在空间上聚集；若残差聚集，说明模型可能遗漏了空间因素或区域差异。",
                "可能问题：样本量不足、目标变量缺失、特征共线、空间泄漏或训练/验证划分不合理都会导致指标偏乐观或偏差。",
                "下一步建议：" + "；".join(_recommendations(plan, model, context)),
            ]
        )

    return "\n".join(
        [
            f"已完成操作：{raw or '已根据当前上下文完成本轮对话判断。'}",
            f"使用的数据：{dataset}。",
            "关键结果：" + (raw or "已生成任务计划或上下文建议。"),
            "输出文件：" + ("\n" + "\n".join(output_lines) if output_lines else " 本轮未识别到新的输出文件。"),
            "结果含义：该回答基于当前工作区、最近结果和本轮意图生成；如果缺少关键输入，应先补齐再执行工具。",
            "可能问题：如果数据集、字段或结果对象没有指定清楚，后续工具调用可能不稳定。",
            "下一步建议：" + "；".join(_recommendations(plan, model, context)),
        ]
    )
