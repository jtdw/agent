# Soil Moisture + XGBoost + GeoConformal Prediction Implementation Plan

Date: 2026-06-28
Status: complete_phase_39

## Execution Update 2026-06-28

- Phase 39.1 is complete: data semantic cards and sanitized context integration are implemented.
- Phase 39.2 is complete: local-only ISMN archive adapter/tools/tool cards are implemented, with optional `TUW-GEO/ismn` dependency handling.
- Phase 39.3 is complete: runtime code no longer imports `core.station_data`; old local STM-compatible parsing moved into `core.ismn_adapter`; `core/station_data.py` was deleted.
- Compatibility note: the old tool name `convert_stm_station_archive_to_training_table` remains as a backward-compatible alias, but it now uses the ISMN local archive adapter.
- Phase 39.4 is complete: generic XGBoost now emits GCP-ready prediction/residual/validation columns, validation metadata, feature semantics, and random split limitations.
- Phase 39.5 is complete: GCP now emits explicit method names, structured fallback diagnostics, row-level uncertainty contract fields, and result semantic cards.
- Phase 39.6 is complete: planner semantic routing now uses sanitized data semantic cards for ISMN observation modeling, XGBoost prediction-to-GCP, GCP result analysis, and GCP uncertainty map fields.
- Phase 39.7 is complete: deterministic tests, default active smoke, opt-in semantic GCP-result map smoke, and staging 5% dry-run evidence passed. Further staging expansion is a separate major choice.

## 目标

在不破坏现有 LangChain runtime staging 5% 配置的前提下，把已批准的 ISMN 土壤水分、XGBoost、GeoConformal Prediction / GCP 设计拆成可执行代码批次。

本阶段先做本地、授权边界内的数据接入和建模增强：

- 只读取用户已下载的官方 ISMN archive、workspace 内 archive、以及 agent local library 中的数据。
- 让智能体通过数据语义卡片知道每个数据集的用途，例如观测目标、模型特征、校准集、预测结果、地图图层或派生产物。
- 兼容扩展现有 `run_stm_soil_moisture_xgboost_workflow`、`generic_xgboost_workflow`、`geographical_conformal_prediction` 和 runtime planner，不一次性替换。
- 标准 LCEL 和向量化 RAG 仍按当前项目状态处理：已有基础能力，但不能假设已经是完整生产实现。

## 不做什么

- 不自动登录、抓取或下载 ISMN 网站数据。
- 不存储 ISMN 账号、cookie、token、storage state。
- 不把 `.env`、绝对路径、原始 ISMN 行数据、token/cookie/env、完整 prompt 发送给外部 LLM。
- 不在同一批次扩大 active runtime rollout 百分比。
- 不重写前端整体布局，不改现有 API 响应结构的必需字段。
- 不顺手修复旧文件中的历史乱码；如确实影响本阶段功能，单独标记 `TODO_ENCODING_REVIEW`。

## 旧 STM 解析迁移决定

用户已确认：Phase 39 的目标不是继续维护 `core/station_data.py` 中较早的手写 `.stm` 站点压缩包解析，而是迁移到新的 ISMN 本地 archive 适配器。

执行要求：

- Phase 39.1 先建立数据语义卡片基础，不触碰旧解析器。
- Phase 39.2 新增 ISMN 本地 archive 适配器和工具。
- Phase 39.3 将现有 STM/soil moisture workflow 改为使用 ISMN adapter 产出的 observation table / semantic card。
- Phase 39.3 或紧随其后的清理批次中，替换 `core/tools/common_tools.py`、`core/workflows/stm_soil_moisture.py`、`api_server.py` 对 `core/station_data.py` 的依赖。
- 只有当 `rg "core.station_data|station_data|stm_archive_to_training_dataframe|find_station_archives"` 不再命中运行时代码后，才删除 `core/station_data.py` 并更新旧 STM 测试。

完成标准：

- 运行时代码不再 import `core.station_data`。
- 旧 `convert_stm_station_archive_to_training_table` 要么移除，要么作为兼容别名调用新的 ISMN import 工具。
- 旧 `.stm` fixture 测试被 ISMN adapter/tool/workflow 测试替代。
- 后端启动、工具注册、planner 候选工具检索不依赖旧乱码文件。

## 当前代码基线

已确认可复用基础：

- `core/workflows/stm_soil_moisture.py`
  - 现有 STM 站点 archive 到训练表、点图层、栅格采样、XGBoost 的工作流入口。
  - 已支持缺少栅格特征时返回 `needs_raster_features`。
- `core/station_data.py`
  - 现有 `.stm` 压缩包解析和 local library 站点 archive 查找。
  - 存在历史乱码，Phase 39 不直接重写。
- `core/ml/generic_xgboost.py`
  - 已有 XGBoost 训练、随机/空间/时序/时空切分、特征重要性、模型结果注册。
  - 需要补显式方法元数据、CV/残差列和 GCP 友好输出。
- `core/gcp_uncertainty.py`
  - 已有 split conformal、空间加权、区间图、覆盖率图和指标。
  - 需要补方法命名、fallback 诊断、结果语义卡片和更明确的 GCP 输出契约。
- `core/context_builder.py`、`core/tool_cards.py`、`core/agent_runtime/planner.py`
  - 已有上下文、工具卡和 runtime planner 边界。
  - 需要接入经过脱敏的数据语义摘要。

## 执行原则

- 每一批先跑 GitNexus impact，再改被影响的函数/类/方法。
- 优先测试驱动：先加或更新最小失败测试，再实现。
- 使用项目 `.venv`。示例命令优先用 `.venv\Scripts\python.exe`。
- 每批只改一个清晰边界，批次之间可独立回滚。
- 所有新增文档和 Python 文本读写使用 UTF-8。
- 新增工具结果必须是结构化 `ToolResult` 风格，错误包含 `error_code`、`reason` 或 `user_message`、`next_actions`。

## Phase 39.1 数据语义卡片基础

目标：建立最小数据语义卡片 schema、catalog helper 和脱敏摘要，不改变现有工具行为。

预计文件：

- 新增 `core/data_semantics.py`
- 可能小改 `core/data_manager.py`
- 可能小改 `core/context_builder.py`
- 新增 `tests/test_data_semantics.py`

实现内容：

- 定义 `gis-data-semantic-card/v1` 的 JSON-safe helper。
- 支持写入 dataset meta，并镜像到轻量 catalog 文件，例如 workspace 下的安全派生目录。
- 提供 `sanitize_semantic_card_for_planner()`，只保留 dataset name、roles、变量、单位、行数、坐标/时间可用性、推荐工具等。
- 明确禁止输出绝对路径、raw rows、cookie/token/env、credential-like 字段。

GitNexus impact 目标：

- `DataManager.put_table`
- `DataManager.put_vector`
- `DataManager.put_raster_path`
- `build_conversation_context`
- `format_context_for_agent`

测试：

- `tests/test_data_semantics.py`
- `tests/test_agent_runtime_planner_adapter.py` 中增加脱敏上下文断言。
- 命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_data_semantics.py tests/test_agent_runtime_planner_adapter.py -q`
  - `.venv\Scripts\python.exe -m py_compile core/data_semantics.py core/context_builder.py`

完成标准：

- 现有 dataset 可附加语义卡片。
- planner 上下文只看到脱敏摘要。
- 敏感字段扫描不泄漏路径、cookie、token、env。

## Phase 39.2 ISMN 本地 archive 适配器和工具

目标：新增官方 ISMN archive 的本地读取能力，兼容 optional `TUW-GEO/ismn`，不自动下载。

预计文件：

- 新增 `core/ismn_adapter.py`
- 新增或扩展 `core/tools/soil_moisture_tools.py`
- 小改 `core/tools/registry.py`
- 小改 `core/tool_cards.py`
- 新增 `tests/test_ismn_adapter.py`
- 新增 `tests/test_ismn_tools.py`

实现内容：

- `list_ismn_archives`
  - 搜索 upload、derived、workspace archive、`local_library/data/ismn/**/*.zip`。
  - 只返回相对安全摘要，不暴露绝对路径给 LLM。
- `profile_ismn_archive`
  - 优先用 `ismn.interface.ISMN_Interface`。
  - 缺依赖返回 `ISMN_DEPENDENCY_MISSING`。
  - 摘要 networks、stations、sensors、depths、time range、variables。
- `import_ismn_soil_moisture_archive`
  - 支持 network/station/depth/time/variable/quality/aggregation 过滤。
  - 输出标准观测表和 semantic card。
  - 当多个深度且用户未指定时返回 `ISMN_DEPTH_AMBIGUOUS`，不随意选一个。

GitNexus impact 目标：

- `build_tools`
- `list_tool_cards`
- `candidate_tool_cards`

测试：

- optional dependency missing 测试必须不要求安装 `ismn`。
- fixture 可先用 mock/fake interface，不依赖真实 ISMN 账号数据。
- 命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_ismn_adapter.py tests/test_ismn_tools.py tests/test_tool_contracts.py -q`
  - `.venv\Scripts\python.exe -m py_compile core/ismn_adapter.py core/tools/soil_moisture_tools.py core/tools/registry.py core/tool_cards.py`

完成标准：

- 无 `ismn` 依赖时后端启动和工具注册不失败。
- 有 fake/fixture interface 时能生成观测表、artifact、semantic card。
- 工具卡能被 planner 候选检索到。

## Phase 39.3 土壤水分训练表工作流升级

目标：让现有 soil moisture workflow 消费 ISMN 导入结果和语义卡片，并迁移掉旧 `.stm` 手写解析依赖。

预计文件：

- 小改 `core/workflows/stm_soil_moisture.py`
- 可能新增 `core/workflows/soil_moisture_training.py`
- 小改 `core/workflows/registry.py`
- 新增或扩展 `tests/test_stm_xgboost_workflow.py`
- 新增 `tests/test_soil_moisture_training_workflow.py`

实现内容：

- 支持 observation dataset 作为输入，而不只支持 archive path。
- 使用 semantic cards 选择目标列、坐标列、时间列、depth、station/network 分组字段。
- 如果只有 ISMN 观测而无 feature rasters，返回 `needs_feature_data`，并给出下一步建议。
- 从 workspace/local library 的语义卡片中识别 DEM、NDVI/EVI、LST、precipitation、soil texture、land cover 等候选特征。
- station id、network/station 默认不得作为预测特征，只能用于分组和诊断。
- 替换 `core.station_data` 依赖，完成后删除 `core/station_data.py`。

GitNexus impact 目标：

- `run_stm_soil_moisture_xgboost_workflow`
- `resolve_default_station_archive`
- `list_workflow_templates`
- `build_executable_workflow`

测试：

- 旧 STM archive 测试应被迁移为 ISMN adapter/workflow 测试；不再要求旧乱码解析器继续通过。
- 新 ISMN observation table 输入缺特征时停在训练表。
- 有栅格特征时构建 feature table，并调用 XGBoost。
- `rg "core.station_data|station_data|stm_archive_to_training_dataframe|find_station_archives" core tests` 不再命中运行时依赖。
- 命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_stm_xgboost_workflow.py tests/test_soil_moisture_training_workflow.py -q`
  - `.venv\Scripts\python.exe -m py_compile core/workflows/stm_soil_moisture.py`

完成标准：

- 旧入口兼容。
- 新入口可通过 semantic card 知道目标、坐标、时间、分组。
- 结果 artifact 和语义卡片可被后续 XGBoost/GCP 使用。

## Phase 39.4 XGBoost 输出契约和验证元数据

目标：增强 `generic_xgboost_workflow` 的结果契约，使其直接服务 GCP 校准和空间/时空诊断。

预计文件：

- 小改 `core/ml/generic_xgboost.py`
- 小改 `core/tools/ml_tools.py`
- 新增或扩展 `tests/test_xgboost_modeling_routing.py`
- 新增 `tests/test_generic_xgboost_method_metadata.py`

实现内容：

- 输出显式字段：
  - `validation_method`
  - `cv_fold_column`
  - `target_column`
  - `prediction_column`
  - `cv_prediction_column`
  - `residual_column`
  - `coordinate_columns`
  - `time_column`
  - `feature_semantics`
  - `training_data_semantic_card`
- 在结果表中补残差列和可用于 GCP 的预测列。
- 优先级保持：spatiotemporal、spatial_block、group、date、random。
- 当只能 random split 时输出 warning。

GitNexus impact 目标：

- `run_generic_xgboost_workflow`
- `_fit_table_model`
- `_split_indices`
- `generic_xgboost_workflow` tool wrapper

测试：

- 空间/时空字段存在时 validation method 正确。
- 结果表包含 prediction、residual、cv/fold 相关字段。
- metadata 中保留 feature semantics，不泄漏原始路径。
- 命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_generic_xgboost_method_metadata.py tests/test_xgboost_modeling_routing.py tests/test_stm_xgboost_workflow.py -q`
  - `.venv\Scripts\python.exe -m py_compile core/ml/generic_xgboost.py core/tools/ml_tools.py`

完成标准：

- 旧调用参数继续可用。
- 新输出足够让 GCP 自动识别 observed/predicted/coordinate/time/fold。

## Phase 39.5 GCP 输出、fallback 和语义卡片升级

目标：把现有 conformal/GCP 能力整理成更明确的 GeoConformal Prediction 工具契约。

预计文件：

- 小改 `core/gcp_uncertainty.py`
- 小改 `core/tools/ml_tools.py`
- 小改 `core/tool_cards.py`
- 扩展 `tests/test_gcp_uncertainty.py`
- 新增 `tests/test_gcp_tool_contract.py`

实现内容：

- 方法模式明确为：
  - `global_split_conformal`
  - `spatially_weighted_gcp`
  - `global_split_conformal_fallback`
- 坐标缺失或不足时返回 warning/error code `GCP_COORDINATES_MISSING_GLOBAL_FALLBACK`，但可继续产出全局区间。
- 校准样本不足时返回 `GCP_CALIBRATION_TOO_SMALL`。
- 输出 prediction interval lower/upper、width、covered、local quantile 或 radius、coverage/width by block、interval score。
- 注册 result semantic card：
  - `prediction_with_uncertainty`
  - `gcp_result`
  - `map_ready`
  - `calibration_diagnostics`

GitNexus impact 目标：

- `run_gcp_uncertainty_analysis`
- `compute_uncertainty_metrics`
- `geographical_conformal_prediction`
- `generate_gcp_visualizations`

测试：

- 无坐标 fallback 到全局 split conformal。
- 有坐标且校准充分时使用空间加权。
- 校准样本过小返回结构化错误。
- 结果 artifact、metrics、maps、semantic card 均存在。
- 命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_gcp_uncertainty.py tests/test_gcp_tool_contract.py -q`
  - `.venv\Scripts\python.exe -m py_compile core/gcp_uncertainty.py core/tools/ml_tools.py`

完成标准：

- GCP 不再只有模糊 `gcp` / `split_conformal` 名称。
- planner 和结果面板能知道这是不确定性结果。

## Phase 39.6 Planner、context、runtime active smoke 接线

目标：让智能体能用语义卡片规划 ISMN、土壤水分建模和 GCP，而不是猜文件名。

执行状态：complete。

完成内容：

- `core/task_planner.py` 已支持从 sanitized `data_semantic_cards` 自动补齐 ISMN observation table 的 `generic_xgboost_workflow` 参数。
- 当 ISMN observation 只有目标/坐标/时间、没有真实特征字段时，planner 仍要求补充 feature columns，不伪造特征。
- 当 XGBoost prediction semantic card 可用且用户请求 GCP 时，planner 可直接构造 `geographical_conformal_prediction` 参数。
- 当 GCP result semantic card 可用时，result analysis 不再要求用户额外指定 result object；uncertainty map 请求会使用 interval width 字段并保留既有 table-to-points map workflow。

验证：

- `tests/test_soil_moisture_semantic_planning.py -q`: 5 passed。
- `py_compile core/task_planner.py tests/test_soil_moisture_semantic_planning.py`: passed。
- `tests/test_agent_runtime_planner_adapter.py tests/test_task_slots.py tests/test_xgboost_modeling_routing.py -q`: 42 passed。
- `tests/test_next_data_processing_migration.py tests/test_gcp_uncertainty.py tests/test_gcp_tool_contract.py -q`: 17 passed。

预计文件：

- 小改 `core/context_builder.py`
- 小改 `core/task_planner.py`
- 小改 `core/agent_runtime/planner.py`
- 小改 `core/tool_cards.py`
- 扩展 `tests/test_agent_runtime_planner_adapter.py`
- 新增 `tests/test_soil_moisture_semantic_planning.py`
- 可能扩展 `scripts/run_agent_runtime_active_smoke.ps1` 的 opt-in case

实现内容：

- context 增加 `data_semantic_cards` 的脱敏摘要。
- task planner 在以下情况优先使用 semantic evidence：
  - 存在 ISMN observation card 时作为 soil moisture target。
  - 多 depth 未指定时要求澄清。
  - observation 有、feature rasters 无时执行导入/训练表步骤后停下。
  - 已有 XGBoost prediction card 且用户要求 GCP 时路由到 `geographical_conformal_prediction`。
- active runtime planner 只拿脱敏摘要。

GitNexus impact 目标：

- `build_conversation_context`
- `format_context_for_agent`
- `build_task_plan`
- `RuntimePlannerAdapter.build_active_task_plan`

测试：

- planner 从 semantic card 选择 ISMN observation。
- 多 depth 触发澄清。
- 无特征时不会硬训模型。
- GCP 请求能从 prediction semantic card 路由。
- 脱敏测试不泄漏 raw rows、absolute path、cookie、token、env。
- 命令：
  - `.venv\Scripts\python.exe -m pytest tests/test_soil_moisture_semantic_planning.py tests/test_agent_runtime_planner_adapter.py -q`
  - `.venv\Scripts\python.exe -m py_compile core/context_builder.py core/task_planner.py core/agent_runtime/planner.py`

完成标准：

- deterministic planner 与 runtime planner 都能使用语义摘要。
- 现有 Phase 38A active smoke 不退化。

## Phase 39.7 验证、smoke 和 rollout 决策

目标：完成本地工具验证和 opt-in LLM coordinator smoke，再决定是否进入真实更广 staging。

执行状态：complete。

完成内容：

- 新增 opt-in active smoke case `semantic_gcp_result_uncertainty_map`，默认 9 个 smoke case 不变。
- 修复 GCP result map prompt 因 GCP 关键词被误归入 modeling 的问题；已有 GCP result semantic card 且用户请求 map/plot 时，deterministic planner 进入 `map_generation`。
- 修复 active LLM planner 跳过 `table_to_points` 前置步骤时的漂移：若 deterministic plan 已有 table-to-points map workflow，而 LLM plan 只直接 `plot_dataset` 原始表格，则使用 deterministic fallback。

验证结果：

- Phase 39 相关本地测试：25 passed。
- Planner/runtime/smoke targeted regression：27 passed。
- Modeling/GCP/迁移回归：41 passed。
- Full deterministic active smoke：9/9 passed，证据 `outputs/agent_runtime_phase39_7_deterministic_smoke.json`。
- Opt-in semantic GCP result map smoke：1/1 passed，证据 `outputs/agent_runtime_phase39_7_semantic_gcp_result_map_smoke.json`。
- Staging 5% dry-run：`eligible_for_user_exposure=true`，`recommendation=allow_staging_exposure`，`live_traffic_changed=false`，证据 `outputs/agent_runtime_phase39_7_staging_5pct_dry_run.json`。

决策：

- Phase 39 到此完成。
- 不在本阶段扩大真实 staging 或生产流量。
- 下一步若继续 rollout，应作为 Phase 40 重大选择：是否从 staging 5% 进入 staging 10% 观察，或先补更多真实 soil moisture/GCP 样本 smoke。

预计文件：

- 可能新增 `scripts/run_soil_moisture_gcp_smoke.ps1`
- 可能新增 fixture under `tests/fixtures/`
- 更新 `.planning/langchain_agent_redesign/*`

验证命令：

- `.venv\Scripts\python.exe -m pytest tests/test_data_semantics.py tests/test_ismn_adapter.py tests/test_ismn_tools.py tests/test_soil_moisture_training_workflow.py tests/test_generic_xgboost_method_metadata.py tests/test_gcp_uncertainty.py tests/test_gcp_tool_contract.py tests/test_soil_moisture_semantic_planning.py -q`
- `.venv\Scripts\python.exe -m pytest tests/test_stm_xgboost_workflow.py tests/test_tool_contracts.py tests/test_agent_runtime_planner_adapter.py -q`
- `.venv\Scripts\python.exe -m py_compile core/data_semantics.py core/ismn_adapter.py core/tools/soil_moisture_tools.py core/ml/generic_xgboost.py core/gcp_uncertainty.py`
- `powershell -ExecutionPolicy Bypass -File scripts/test_agent_runtime_decision_eval.ps1`
- `powershell -ExecutionPolicy Bypass -File scripts/test_agent_runtime_active_smoke.ps1`

Opt-in smoke 建议：

- ISMN archive discovery/profile/import。
- 观测表存在但无特征时返回 `needs_feature_data`。
- 有 raster feature fixture 时完成 XGBoost。
- XGBoost 输出后完成 GCP。
- LLM coordinator smoke 只在显式 opt-in 时运行，并优先使用 GLM-4.5-Air。

完成标准：

- 本地 deterministic tests 通过。
- active smoke 仍为 9/9 或更高。
- 新 soil moisture/GCP smoke 无敏感信息泄漏。
- 再进入真实 staging 10% 或生产前，需要单独重大选择。

## 依赖和环境建议

`.env.example` 可加入说明，`.env` 只在实际需要时配置：

- `GIS_AGENT_ISMN_LOCAL_LIBRARY=local_library/data/ismn`
- `GIS_AGENT_ENABLE_ISMN_TOOLS=1`
- `GIS_AGENT_ENABLE_DATA_SEMANTIC_CARDS=1`

暂不建议默认启用：

- `ismn` 依赖作为 hard requirement。
- 自动 ISMN 下载。
- 自动把 semantic card 全量发给 LLM。

## 风险和停止条件

立即停止并回到用户确认的情况：

- GitNexus impact 返回 HIGH 或 CRITICAL。
- 需要新增硬依赖并影响后端启动。
- 需要更改既有 API 请求/响应必需字段。
- 需要真实 ISMN 登录、下载或凭证处理。
- GCP 方法实现需要超出当前论文/设计范围的大改。
- active runtime staging 5% 出现新失败，需要先回滚或修复 runtime。

## 推荐执行顺序

推荐一次执行一批：

1. Phase 39.1 数据语义卡片基础。
2. Phase 39.2 ISMN 本地 archive 适配器和工具。
3. Phase 39.3 土壤水分训练表工作流升级。
4. Phase 39.4 XGBoost 输出契约和验证元数据。
5. Phase 39.5 GCP 输出、fallback 和语义卡片升级。
6. Phase 39.6 Planner、context、runtime 接线。
7. Phase 39.7 验证、smoke 和 rollout 决策。

我的建议是先执行 39.1 和 39.2。原因是它们建立数据语义和 ISMN 本地读取边界，后续 XGBoost/GCP 才不会继续依赖文件名猜测。
