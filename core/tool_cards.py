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
        "raster_covariate_quality_check",
        "QA daily NDVI/LST rasters for NoData, valid ratio, and value range.",
        ["data_processing", "raster_quality", "remote_sensing", "soil_moisture", "modeling"],
        ["raster_names", "output_name"],
        ["quality_summary", "table_dataset", "artifact"],
        optional_inputs=["band", "min_valid_ratio", "expected_ranges", "covariate_type", "expected_categories"],
        input_asset_roles=["daily_ndvi_raster", "daily_lst_raster", "covariate_raster"],
        preconditions=["Rasters must be loaded", "expected_ranges uses raster=min:max"],
        common_failure_cases=["NoData too high", "values outside range", "band out of range"],
        forbidden_uses=["Do not treat QA as gap filling", "Do not call low-valid-ratio daily rasters reliable"],
    ),
    _card(
        "build_temporal_covariate_composite",
        "Build same-grid temporal composites for daily NDVI/LST/precipitation rasters with gaps.",
        ["data_processing", "raster_composite", "remote_sensing", "soil_moisture", "modeling"],
        ["raster_names", "output_name"],
        ["raster_dataset", "summary", "artifact", "map_layer"],
        optional_inputs=["covariate_type", "method", "band", "min_observations", "band_selection", "start_date", "end_date"],
        input_asset_roles=["daily_ndvi_raster", "daily_lst_raster", "daily_precipitation_raster", "covariate_raster"],
        preconditions=["Rasters must be loaded and share the same CRS, transform, width, and height"],
        common_failure_cases=["Input grids are not aligned", "all pixels missing", "categorical rasters need a mode workflow"],
        forbidden_uses=["Do not use for unaligned rasters", "Do not use continuous composites for landcover classes"],
    ),
    _card(
        "raster_zonal_stats",
        "按面状分区统计栅格像元值，并返回注册后的统计表 artifact。",
        ["analysis", "raster_statistics", "zonal_statistics", "data_processing"],
        ["raster_name", "zone_name", "output_name"],
        ["table_dataset", "artifact", "zonal_statistics"],
        optional_inputs=["zone_field", "stats"],
        input_asset_roles=["value_raster", "zone_polygon_layer"],
        preconditions=["栅格和分区面图层必须已加载", "分区图层必须包含面几何", "输入必须位于允许的 workspace 内"],
        common_failure_cases=["缺少栅格", "缺少分区面图层", "CRS 不一致", "没有重叠像元", "zone_field 缺失或无效"],
        forbidden_uses=["不得在未运行工具时编造分区统计结果", "不得用于纯矢量统计"],
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
        "raster_reproject",
        "将真实已加载栅格重投影为目标 CRS，并注册 map-ready GeoTIFF。",
        ["data_processing", "raster_reproject", "raster_resample"],
        ["raster_name", "target_crs", "output_name"],
        ["raster_dataset", "artifact", "map_layer"],
        optional_inputs=["resampling", "target_resolution"],
        input_asset_roles=["source_raster", "target_crs"],
        preconditions=["输入必须是可读取栅格", "源 CRS 必须存在", "target_crs 必须由 TaskPlan 明确给出", "target_resolution 如提供必须为目标 CRS 单位下的正数", "重采样方法必须受 rasterio 支持"],
        common_failure_cases=["源 CRS 缺失", "target_crs 非法", "target_resolution 非法", "输出路径非法", "重投影后无有效像元"],
        forbidden_uses=["不能凭用户原文临时决定目标 CRS 或目标分辨率", "不能把重投影描述为裁剪或下载"],
    ),
    _card(
        "dem_terrain_derivatives",
        "从已验证的投影坐标 DEM 生成坡度、坡向等地形派生栅格。",
        ["terrain_analysis", "dem", "slope", "aspect"],
        ["dem_name", "output_prefix"],
        ["raster_dataset", "artifact", "map_layer", "terrain_statistics"],
        optional_inputs=["derivatives", "slope_units"],
        input_asset_roles=["dem_raster"],
        preconditions=["DEM 必须是真实已加载栅格", "DEM 必须有 CRS", "平面坡度计算要求投影坐标 CRS", "slope_units 必须明确为 degree 或 percent"],
        common_failure_cases=["DEM 是地理坐标 CRS", "NoData 全覆盖", "derivatives 参数不支持", "输出路径非法"],
        forbidden_uses=["不得直接对经纬度 DEM 计算平面坡度", "不得伪造坡度统计或坡向范围"],
    ),
    _card(
        "raster_algebra",
        "对已对齐的栅格执行受限表达式计算，可用于明确波段/栅格映射的 NDVI。",
        ["raster_calculation", "ndvi_calculation", "data_processing"],
        ["expression", "input_rasters", "output_name"],
        ["raster_dataset", "artifact", "map_layer", "raster_statistics"],
        input_asset_roles=["aligned_raster_inputs", "formula"],
        preconditions=["表达式变量必须映射到真实栅格数据集", "输入栅格 CRS、范围、分辨率和形状必须一致", "NDVI 的 red/nir 映射必须由用户或真实元数据明确"],
        common_failure_cases=["缺少变量映射", "栅格未对齐", "表达式非法", "NoData 导致结果为空"],
        forbidden_uses=["不得凭文件名猜测红光或近红外波段", "不得扫描工作区自动混入其他栅格"],
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
        "vector_buffer",
        "对矢量图层生成缓冲区，米制缓冲会在地理 CRS 下使用验证后的临时投影处理。",
        ["data_processing", "vector_buffer"],
        ["dataset_name", "distance", "unit", "output_name"],
        ["vector_dataset", "artifact", "map_layer"],
        input_asset_roles=["target_vector"],
        preconditions=["输入必须是矢量数据", "distance 必须为正数", "unit 必须明确", "输入 CRS 必须存在"],
        common_failure_cases=["距离非法", "CRS 缺失", "无法估计投影坐标系", "缓冲结果为空"],
        forbidden_uses=["不得在距离和单位缺失时自动执行", "不得把经纬度单位误当米直接缓冲"],
    ),
    _card(
        "vector_spatial_join",
        "按明确空间关系连接两个矢量图层，并输出真实要素数、字段和 artifact。",
        ["data_processing", "spatial_join"],
        ["target_name", "join_name", "predicate", "output_name"],
        ["vector_dataset", "artifact", "map_layer"],
        optional_inputs=["how", "field_conflict_strategy"],
        input_asset_roles=["target_vector", "join_vector"],
        preconditions=["两个输入都必须是矢量数据", "CRS 必须存在", "predicate 必须是支持的空间关系", "字段冲突策略必须明确或使用默认 suffix"],
        common_failure_cases=["空间关系不支持", "连接方式不支持", "CRS 缺失", "结果为空"],
        forbidden_uses=["不得在目标图层或连接图层不明确时执行", "不得凭历史 selected object 自动补连接图层"],
    ),
    _card(
        "extract_raster_values_to_points",
        "把一个栅格的像元值采样到点图层字段中，适合站点-栅格特征提取。",
        ["data_processing", "raster_sampling", "station_raster_feature_extraction"],
        ["point_name", "raster_name", "output_name", "field_name"],
        ["vector_dataset", "artifact", "sample_diagnostics"],
        optional_inputs=["band", "method"],
        input_asset_roles=["point_station_layer", "feature_raster"],
        preconditions=["点图层必须是真实 Point 几何", "栅格必须可读取", "点和栅格 CRS 必须存在", "method 必须为 nearest 或 bilinear"],
        common_failure_cases=["点图层 CRS 缺失", "栅格波段不存在", "采样结果 NoData 过多", "输出字段缺失"],
        forbidden_uses=["不得在站点坐标不明确时执行", "不得伪造采样值或缺失率"],
    ),
    _card(
        "batch_register_points_to_rasters",
        "把多个栅格批量采样到点图层，输出长表或宽表，供建模或质量检查使用。",
        ["data_processing", "raster_sampling", "station_raster_feature_extraction", "modeling"],
        ["point_name", "raster_names", "output_name"],
        ["table_dataset", "vector_dataset", "artifact", "sample_diagnostics"],
        optional_inputs=["id_cols", "output_mode", "value_field_prefix", "band", "parse_date", "date_regex"],
        input_asset_roles=["point_station_layer", "feature_rasters"],
        preconditions=["点图层和所有栅格必须来自真实元数据", "栅格列表必须由 TaskPlan 明确选择", "输出模式必须为 long 或 wide"],
        common_failure_cases=["栅格列表为空", "ID 字段不存在", "波段越界", "采样结果缺失"],
        forbidden_uses=["不得自动扫描工作区混入其他栅格", "不得替 XGBoost 伪造训练特征"],
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
        "predict_xgboost_raster_map",
        "Use a trained XGBoost model bundle to predict a full-basin soil moisture raster map from DEM, NDVI, LST, or other feature rasters.",
        ["modeling", "xgboost", "soil_moisture", "raster_prediction", "map_generation"],
        ["model_path", "feature_rasters", "output_name"],
        ["prediction_raster", "map_artifact", "summary_json"],
        optional_inputs=["boundary_name", "representative_date", "max_prediction_pixels", "raster_resampling", "chunk_size"],
        input_asset_roles=["trained_xgboost_model", "feature_rasters", "optional_basin_boundary"],
        preconditions=[
            "model_path must point to a model artifact inside the current workspace",
            "feature_rasters must map model feature names to loaded raster dataset names",
            "boundary_name, when provided, must be a vector dataset with CRS",
            "date features are representative snapshot metadata unless date-matched rasters are supplied",
        ],
        common_failure_cases=[
            "model path is outside the workspace",
            "required feature raster mapping is missing",
            "feature rasters have no valid overlap after reprojection",
            "reference raster exceeds max_prediction_pixels",
        ],
        forbidden_uses=[
            "Do not use it before a model has been trained and saved",
            "Do not claim the output is a daily dynamic product when NDVI/LST are static snapshots",
            "Do not pass .env, cookies, storage_state, database, or secret files as model_path",
        ],
    ),
    _card(
        "train_xgboost_fusion_model",
        "训练表格或点数据的 XGBoost 回归模型，支持经纬度字段驱动的空间分块验证、残差、特征重要性、精度指标和模型文件输出。",
        ["modeling", "xgboost", "soil_moisture", "spatial_validation"],
        ["dataset_name", "target_col", "feature_cols", "output_name"],
        ["prediction_table", "residual_table", "model_metrics", "feature_importance", "model_file", "diagnostic_images"],
        optional_inputs=["date_col", "split_date", "lon_col", "lat_col", "spatial_validation", "validation_method", "spatial_block_count", "random_state", "requested_outputs"],
        input_asset_roles=["training_table", "target_variable", "feature_variables", "coordinate_fields", "optional_time_field"],
        preconditions=["目标列、特征列、坐标列和时间列必须来自真实 Asset Profile", "空间分块验证需要真实有效的 lon/lat 或点几何", "样本量必须满足训练和验证要求"],
        common_failure_cases=["目标列缺失", "特征列缺失", "坐标列无效", "样本不足", "xgboost 依赖不可用", "空间分块不足以形成验证折"],
        forbidden_uses=["不得伪造 RMSE/MAE/R2 或残差诊断", "不得在缺少目标变量或有效坐标时执行空间分块验证", "不得扫描工作区混入未被 TaskPlan 选择的数据"],
    ),
    _card(
        "list_ismn_archives",
        "List official ISMN zip archives already available in uploads, derived outputs, or the local ISMN library without downloading data or exposing absolute paths.",
        ["data_discovery", "soil_moisture", "ismn", "local_archive"],
        [],
        ["ismn_archive_catalog"],
        input_asset_roles=["local_ismn_archive_library", "uploaded_ismn_archive"],
        preconditions=["User has already downloaded or uploaded an official ISMN archive", "Archive must stay inside the managed workspace or local library"],
        common_failure_cases=["No local ISMN archive is available", "Archive candidate is outside the allowed workspace", "Archive is not a zip file"],
        forbidden_uses=["Do not download ISMN data from the internet", "Do not expose absolute server paths", "Do not read cookies, tokens, or browser storage"],
    ),
    _card(
        "profile_ismn_archive",
        "Inspect a local official ISMN archive and summarize networks, stations, sensors, variables, depths, and time ranges for planner-safe data selection.",
        ["data_profiling", "soil_moisture", "ismn", "station_metadata"],
        ["archive"],
        ["ismn_archive_profile"],
        input_asset_roles=["ismn_archive"],
        preconditions=["Archive must be selected from uploaded files, derived files, or local_library/data/ismn", "Optional TUW-GEO ismn dependency must be installed for full profiling"],
        common_failure_cases=["Archive not found", "Archive is outside the allowed workspace", "ismn dependency is not installed", "Archive cannot be parsed as an official ISMN package"],
        forbidden_uses=["Do not download or refresh remote data", "Do not expose absolute server paths", "Do not infer station metadata that is not present in the archive"],
    ),
    _card(
        "import_ismn_soil_moisture_archive",
        "Import soil-moisture observations from a local official ISMN archive into the workspace with semantic metadata for downstream XGBoost and GCP workflows.",
        ["data_import", "soil_moisture", "ismn", "modeling"],
        ["archive", "output_name"],
        ["soil_moisture_observation_table", "data_semantic_card"],
        optional_inputs=["network", "station", "sensor", "depth_from", "depth_to", "start_time", "end_time", "variable", "quality_flags"],
        input_asset_roles=["ismn_archive", "soil_moisture_observation"],
        preconditions=["Archive must be local and official ISMN data", "User must choose explicit station, sensor, depth, or time filters for large archives", "Imported rows must preserve observed values and metadata provenance"],
        common_failure_cases=["Archive not found", "ismn dependency is not installed", "Selected network or station is missing", "No observations match the requested filters"],
        forbidden_uses=["Do not download ISMN data", "Do not fabricate soil-moisture observations", "Do not merge unrelated workspace archives automatically", "Do not expose absolute source paths in planner context"],
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
    raw_query = str(query or "")
    terms = {token.lower() for token in raw_query.replace("_", " ").split() if token.strip()}
    lower_query = raw_query.lower()
    synonym_terms: list[str] = []
    if any(token in lower_query for token in ("ndvi", "lst", "precipitation", "landcover", "land use")) and (
        any(token in lower_query for token in ("missing", "nodata", "quality", "valid ratio", "valid pixel"))
        or any(token in raw_query for token in ("缺失", "质量", "有效像元", "有效比例", "日数据", "降水", "土地利用"))
    ):
        synonym_terms.extend(["raster_covariate_quality_check", "raster_quality", "remote_sensing", "quality_summary"])
    if any(token in lower_query for token in ("ndvi", "lst", "precipitation")) and any(
        token in lower_query for token in ("temporal", "composite", "gap", "fill", "missing")
    ):
        synonym_terms.extend(["build_temporal_covariate_composite", "raster_composite", "remote_sensing"])
    if any(token in raw_query for token in ("站点", "采样", "提取")) and ("栅格" in raw_query or "raster" in lower_query):
        synonym_terms.extend(["raster_sampling", "station_raster_feature_extraction", "table_to_points"])
    if any(token in raw_query for token in ("坡度", "坡向", "地形")) or any(token in lower_query for token in ("slope", "aspect", "terrain")):
        synonym_terms.extend(["terrain_analysis", "dem_terrain_derivatives", "raster_reproject"])
    if "ndvi" in lower_query or any(token in raw_query for token in ("红光", "近红外", "栅格计算")):
        synonym_terms.extend(["ndvi_calculation", "raster_calculation", "raster_algebra"])
    if "裁剪" in raw_query and ("栅格" in raw_query or "raster" in lower_query):
        synonym_terms.extend(["raster_clip", "clip_raster_by_vector"])
    terms.update(term.lower() for term in synonym_terms if term)
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
