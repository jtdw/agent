---
title: "ISMN、土壤水分 XGBoost 与 GCP 不确定性参考"
language: "zh-CN"
tags: ["ismn", "soil_moisture", "xgboost", "gcp", "geoconformal", "arcpy", "arcgis", "uncertainty", "土壤水分", "不确定性", "空间预测"]
applicable_scope: "ismn_soil_moisture_gcp_reference"
reliability: "high"
version: "2026-06-29.1"
status: "draft"
source: "project-code: core/tool_cards.py; core/data_semantics.py; core/ismn_adapter.py; core/ml/generic_xgboost.py; core/gcp_uncertainty.py; external-reference: ArcGIS Pro ArcPy; ISMN docs; GeoConformal Prediction"
---

# ISMN、土壤水分 XGBoost 与 GCP 不确定性参考

本文档是 Planner 和知识检索参考，不得替代 Tool Cards、Plan Validator 或真实 ToolResult。外部文档只用于术语、前置条件和解释边界，不覆盖项目代码、产品目录、权限策略或当前已注册工具。

## 参考边界

ArcGIS Pro 和 ArcPy 文档可作为 GIS 操作分类参考，例如地理处理工具、Spatial Analyst、Image Analyst、制图、表格转点和分区统计等能力域。它们不表示本项目新增 ArcPy 运行时依赖，也不表示可以绕过当前 Python/Rasterio/GeoPandas/Shapely 工具链。任何执行都必须由当前 Tool Cards、TaskPlan、Validator 和工具实现确认。

ISMN 文档可作为本地 archive 结构和元数据参考。项目只处理用户上传、workspace 内已有或 local_library 中已有的官方 ISMN archive；不得自动下载 ISMN 数据，不得处理登录凭据、Cookie、token 或 storage_state。

GeoConformal Prediction 参考用于解释模型无关的空间预测不确定性。项目中 GCP 必须基于真实观测、预测、残差和校准数据。不得凭自然语言声称完成不确定性分析，也不得编造 coverage、interval width 或 uncertainty map。

## ISMN 本地 archive 姿态

当前工具卡覆盖 `list_ismn_archives`、`profile_ismn_archive` 和 `import_ismn_soil_moisture_archive`。这些工具只应发现、剖析和导入本地 archive，不触发联网下载。

ISMN archive profile 应优先暴露安全摘要：

- network、station、sensor 和 variable。
- depth_from、depth_to 和观测深度范围。
- start_time、end_time 和时间覆盖。
- latitude、longitude 或可转换为空间点的坐标字段。
- instrument、quality flag、soil、land cover、climate 等可用元数据。

如果 archive 中存在多个 station、sensor、depth 或时间范围，而用户没有明确选择，应先提出具体澄清问题。不能任意挑选第一个深度、站点或传感器作为训练目标。

## 土壤水分工作流

土壤水分建模应遵循稳定的数据角色顺序：

1. 从已上传或 local_library 中的 ISMN archive 导入观测。
2. 生成或读取 data semantic card，标记 `soil_moisture_observation`、`model_target_candidate` 和 `gcp_calibration_candidate` 等科学角色。
3. 检查坐标、时间、depth、quality flag 和目标变量。
4. 解析 DEM、NDVI、LST、降水、土地覆盖、土壤属性或其它特征数据的语义卡。
5. 对站点和栅格做 CRS、范围、时间窗口和 NoData 检查。
6. 使用真实采样或对齐结果构造训练表。
7. 训练 XGBoost 并输出真实预测、残差、验证字段和模型产物。
8. 仅在已有真实预测结果后运行 GCP。
9. 注册 prediction table、uncertainty artifact、map layer、summary JSON 和 result semantic card。

如果只有 ISMN 观测而没有特征数据，应停止在观测表或训练表准备阶段，返回 `SOIL_FEATURE_DATA_MISSING` 或等价的结构化提示，并说明需要哪些特征数据。

## XGBoost 输出合同

XGBoost 结果必须来自真实工具输出。知识库只能提示应检查哪些字段，不能替工具生成指标。

建议结果至少保留：

- target_column 和 feature_columns。
- prediction column，例如 `xgb_prediction`。
- residual column，例如 `xgb_residual`。
- validation prediction 和 validation residual。
- validation_method，例如 random、group、date、spatial_block 或 spatiotemporal。
- validation fold、validation role 或 split 标识。
- coordinate_columns 和 time_column。
- feature_semantics、training_data_semantic_card 和 limitation diagnostics。

随机划分是弱泛化证据。存在空间自相关、重复站点、重复像元或时间序列时，应优先考虑空间分块、group、date 或 spatiotemporal validation。若工具只能执行 random split，应在结果解释中明确该限制。

## GCP 不确定性解释

GCP 适用于已有校准观测和模型预测的表格。默认非一致性分数可以使用绝对残差。global split conformal 是安全基线；只有当校准数据具有有效空间坐标、样本量和目标点坐标时，才可解释为空间加权或 spatially adaptive GCP。

空间坐标不足时，GCP 应回退 global split conformal，并在 diagnostics、metrics、summary 和用户回复中说明 fallback 原因。常见代码包括 `GCP_COORDINATES_MISSING_GLOBAL_FALLBACK` 或 `GCP_COORDINATES_INSUFFICIENT_GLOBAL_FALLBACK`。

GCP 结果可包含：

- prediction interval lower 和 upper。
- interval width 或本地 quantile。
- covered、target coverage 和 empirical coverage。
- method、alpha、fallback code 和 interval score。
- uncertainty map、interval-width map、coverage plot 或 histogram。

GCP interval width uncertainty map 只能使用真实坐标和真实区间宽度绘制。如果结果表没有坐标，只能解释全局区间，不能声称生成空间 uncertainty map。

## ArcGIS 和 ArcPy 术语对齐

ArcGIS 的 XY Table To Point 可作为表格转点术语参考：表格必须有真实 x/y 坐标字段，并且坐标系解释要明确。对应到本项目，应优先使用 `table_to_points` 工具卡，检查字段唯一性、数值范围、CRS 和输出点图层。

ArcGIS 的 Zonal Statistics as Table 可作为分区统计术语参考：按 zone 汇总 raster 值并输出表。对应到本项目，应使用 `raster_zonal_stats` 工具卡，检查 value raster、zone polygon、zone field、CRS 和有效像元。

ArcPy 或 ArcGIS 文档不是执行授权。不新增 ArcPy 运行时依赖，不把外部工具名当作已注册工具名，不让知识文本绕过本项目 workspace、artifact、user_id、session_id 和下载安全策略。

## 何时追问或阻断

- ISMN archive 不在 workspace 或 local_library 中。
- 用户要求下载 ISMN 数据但没有上传或提供本地 archive。
- 多个 depth、sensor、station 或 time range 均可用但用户未选择。
- 观测表没有 soil_moisture 目标列或质量标记无法解释。
- 特征栅格缺失、时间不匹配、CRS 不一致或 NoData 过多。
- XGBoost 结果缺少真实预测或残差列。
- GCP 请求缺少观测列、预测列、alpha 或有效校准样本。
- 用户要求空间 uncertainty map 但结果表没有坐标。

## 检索测试问题

1. "ISMN 本地 archive 如何导入土壤水分观测？"
2. "GCP interval width uncertainty map 如何解释？"
3. "空间坐标不足时 GCP 为什么回退 global split conformal？"
4. "ArcPy ArcGIS 是否意味着项目要新增 arcpy 依赖？"
