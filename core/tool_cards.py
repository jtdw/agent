from __future__ import annotations

from typing import Any

from core.capability_config import CAPABILITY_CONFIG_VERSION, configured_tool_cards

REQUIRED_TOOL_CARD_FIELDS = {
    "tool_name",
    "capability",
    "applicable_tasks",
    "required_inputs",
    "optional_inputs",
    "input_asset_roles",
    "preconditions",
    "output_types",
    "side_effects",
    "confirmation_required",
    "common_failure_cases",
    "result_schema",
    "examples",
    "forbidden_uses",
}


def _card(
    tool_name: str,
    capability: str,
    applicable_tasks: list[str],
    required_inputs: list[str],
    output_types: list[str],
    *,
    optional_inputs: list[str] | None = None,
    input_asset_roles: list[str] | None = None,
    preconditions: list[str] | None = None,
    side_effects: list[str] | None = None,
    confirmation_required: bool = False,
    common_failure_cases: list[str] | None = None,
    examples: list[dict[str, Any]] | None = None,
    forbidden_uses: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "capability": capability,
        "applicable_tasks": applicable_tasks,
        "required_inputs": required_inputs,
        "optional_inputs": optional_inputs or [],
        "input_asset_roles": input_asset_roles or [],
        "preconditions": preconditions or [],
        "output_types": output_types,
        "side_effects": side_effects or [],
        "confirmation_required": confirmation_required,
        "common_failure_cases": common_failure_cases or [],
        "result_schema": "ToolResult/v1",
        "examples": examples or [],
        "forbidden_uses": forbidden_uses or [],
    }


_TOOL_CARDS: tuple[dict[str, Any], ...] = (
    _card(
        "download_backend_status",
        "检查下载后端、账号和数据源可用性，不直接开始下载。",
        ["data_download", "troubleshooting"],
        [],
        ["status_summary"],
        common_failure_cases=["下载源未配置", "账号或 Cookie 不可用"],
        forbidden_uses=["不能把状态检查描述为已下载数据"],
    ),
    _card(
        "list_remote_resource_catalog",
        "列出支持的远程数据源和产品目录。",
        ["data_download"],
        [],
        ["resource_catalog"],
        common_failure_cases=["数据源未启用", "产品名不明确"],
        forbidden_uses=["不能替代真实下载或处理结果"],
    ),
    _card(
        "submit_commercial_download_job",
        "根据已验证的下载请求创建受管理的下载任务；不自行解析用户原文。",
        ["data_download"],
        ["user_id", "source_key", "resource_type", "region"],
        ["download_job", "management_view"],
        optional_inputs=["start_date", "end_date", "account_mode", "request_text", "output_name"],
        input_asset_roles=["resolved_area_boundary", "download_product"],
        preconditions=["TaskPlan 必须包含经 Product Catalog 校验的 download_requests", "区域必须来自 AreaResolver", "需要用户/会话权限上下文"],
        side_effects=["创建下载任务记录", "可能触发后续下载队列"],
        confirmation_required=True,
        common_failure_cases=["未登录", "产品或分辨率不支持", "时间范围缺失", "区域边界不可用"],
        forbidden_uses=["不得根据原始用户文本、关键词或历史区域自行选择产品或区域", "不得在 download_requests 为空时调用"],
    ),
    _card(
        "vector_clip_by_vector",
        "用矢量边界裁剪矢量数据，并注册输出数据集/artifact。",
        ["data_processing", "vector_clip"],
        ["dataset_name", "clip_name", "output_name"],
        ["vector_dataset", "artifact", "map_layer"],
        input_asset_roles=["target_vector", "clip_boundary"],
        preconditions=["输入必须是矢量数据", "裁剪边界应为面要素", "路径必须在 workspace 内"],
        common_failure_cases=["缺少裁剪边界", "CRS 不一致", "几何无效或无交集"],
        forbidden_uses=["不能用矢量裁剪工具处理纯表格或未加载文件"],
    ),
    _card(
        "raster_basic_stats",
        "计算栅格基础统计和有效值概况。",
        ["data_upload_analysis", "raster_statistics"],
        ["dataset_name"],
        ["raster_statistics"],
        input_asset_roles=["raster"],
        preconditions=["输入必须是真实已加载栅格"],
        common_failure_cases=["NoData 过多", "栅格损坏", "缺少 CRS"],
        forbidden_uses=["不能凭文件名推断统计值"],
    ),
    _card(
        "clip_raster_by_vector",
        "使用矢量边界裁剪栅格，输出 map-ready 栅格 artifact。",
        ["data_processing", "raster_clip"],
        ["raster_name", "vector_name", "output_name"],
        ["raster_dataset", "artifact", "map_layer"],
        input_asset_roles=["target_raster", "clip_boundary"],
        preconditions=["栅格和矢量均已加载", "边界必须落在允许 workspace 内"],
        common_failure_cases=["CRS 转换失败", "裁剪范围无覆盖", "NoData 全覆盖"],
        forbidden_uses=["不能裁剪未下载完成或不存在的栅格"],
    ),
    _card(
        "table_to_points",
        "将含经纬度/坐标字段的表格转换为点图层。",
        ["data_processing", "table_to_points", "mapping"],
        ["dataset_name", "x_col", "y_col", "crs", "output_name"],
        ["vector_dataset", "artifact", "map_layer"],
        input_asset_roles=["coordinate_table"],
        preconditions=["坐标字段必须来自真实表字段", "CRS 必须明确"],
        common_failure_cases=["缺少经度或纬度字段", "坐标列不是数值", "坐标超出 CRS 合理范围"],
        forbidden_uses=["不能仅凭列名以外的猜测创建点位"],
    ),
    _card(
        "plot_dataset",
        "为矢量或栅格数据生成地图图件 artifact。",
        ["map_generation", "result_analysis"],
        ["dataset_name"],
        ["map_artifact", "image"],
        optional_inputs=["column", "title", "output_name"],
        input_asset_roles=["map_dataset"],
        preconditions=["数据集必须已加载", "专题制图字段必须存在"],
        common_failure_cases=["字段不存在", "矢量缺少 CRS", "无可绘制几何或栅格"],
        forbidden_uses=["不能把未生成的地图说成已生成"],
    ),
    _card(
        "generic_xgboost_workflow",
        "运行通用 XGBoost 回归/分类，可处理表格、矢量属性、站点-栅格采样或栅格堆栈。",
        ["modeling", "xgboost", "soil_moisture"],
        ["dataset_name or raster_names", "target_col or target_raster_name", "feature_cols or raster_names", "output_name"],
        ["prediction_table", "model_metrics", "feature_importance", "model_artifacts"],
        optional_inputs=["sample_dataset_name", "x_col", "y_col", "date_col", "group_col", "split_method"],
        input_asset_roles=["training_table", "target_variable", "feature_variables", "optional_raster_features"],
        preconditions=["目标变量和特征必须来自真实元数据", "样本数应足以训练/验证", "空间验证需要坐标或几何"],
        common_failure_cases=["目标列缺失", "特征列缺失", "有效样本不足", "训练/验证切分不可行"],
        forbidden_uses=["不能伪造 RMSE/MAE/R2/NSE 或模型产物", "不能在缺少目标变量时训练"],
    ),
    _card(
        "geographical_conformal_prediction",
        "基于真实预测结果执行 GCP/空间共形预测不确定性分析。",
        ["modeling", "uncertainty", "gcp"],
        ["calibration_dataset", "observed_col", "predicted_cols", "output_name"],
        ["prediction_intervals", "coverage_metrics", "uncertainty_artifacts"],
        optional_inputs=["target_dataset_name", "lon_col", "lat_col", "date_col", "alpha", "spatial_weighting"],
        input_asset_roles=["calibration_predictions", "observed_variable", "predicted_variable"],
        preconditions=["必须已有真实观测列和预测列", "空间 GCP 需要坐标或可退化为全局 split conformal"],
        common_failure_cases=["预测列不存在", "校准样本不足", "alpha 非法", "空间坐标缺失"],
        forbidden_uses=["不能在没有模型预测结果时声称完成不确定性分析"],
    ),
)


def list_tool_cards() -> list[dict[str, Any]]:
    cards = {str(card.get("tool_name") or ""): dict(card, schema_version=CAPABILITY_CONFIG_VERSION, version=str(card.get("version") or "builtin")) for card in _TOOL_CARDS}
    for card in configured_tool_cards():
        if str(card.get("status") or "enabled") != "enabled":
            continue
        cards[str(card.get("tool_name") or "")] = dict(card, schema_version=CAPABILITY_CONFIG_VERSION)
    return [card for card in cards.values() if card.get("tool_name")]


def validate_tool_card(card: dict[str, Any]) -> list[str]:
    missing = sorted(REQUIRED_TOOL_CARD_FIELDS - set(card))
    errors = [f"missing:{field}" for field in missing]
    if not isinstance(card.get("tool_name"), str) or not card.get("tool_name"):
        errors.append("tool_name_required")
    if not isinstance(card.get("confirmation_required"), bool):
        errors.append("confirmation_required_must_be_bool")
    for field in REQUIRED_TOOL_CARD_FIELDS - {"confirmation_required", "result_schema"}:
        if field in card and field not in {"tool_name", "capability"} and not isinstance(card[field], list):
            errors.append(f"{field}_must_be_list")
    return errors


def candidate_tool_cards(query: str, *, task_type: str = "", limit: int = 8) -> list[dict[str, Any]]:
    terms = {token.lower() for token in str(query or "").replace("_", " ").split() if token.strip()}
    if task_type:
        terms.add(str(task_type).lower())
    scored: list[tuple[int, dict[str, Any]]] = []
    for card in list_tool_cards():
        haystack = " ".join(
            [
                str(card.get("tool_name") or ""),
                str(card.get("capability") or ""),
                " ".join(card.get("applicable_tasks") or []),
                " ".join(card.get("input_asset_roles") or []),
            ]
        ).lower()
        score = sum(1 for term in terms if term and term in haystack)
        if task_type and task_type in card.get("applicable_tasks", []):
            score += 3
        if score:
            scored.append((score, card))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("tool_name") or "")))
    return [dict(card) for _, card in scored[:limit]]
