# GIS 智能体发布候选验收报告

## 范围

本轮是发布候选验收，不新增 GIS 功能，不改 LLM-first 主链路，不恢复关键词直连。验收范围包括：

- LLM-first 请求链路、Validator、Executor/Coordinator、ToolResult、PresentationResult；
- 通用下载、核心 GIS 工作流、XGBoost、后台 Worker、会话删除与隔离；
- 管理端能力配置审核流；
- 兼容层使用统计；
- 后端测试、前端测试、构建和真实浏览器 E2E。

## 本轮变更

- 管理端能力资源新增正式状态流：`draft -> pending_review -> active -> deprecated / disabled`。
- 新增审核元数据：创建人、审核人、提交时间、审核时间、修改摘要、回滚来源。
- 运行时检索只读取 `active` 和历史兼容 `enabled` 状态；新建资源默认 `draft`，不会直接影响 Planner。
- Product Catalog adapter 仍使用后端 allowlist；Asset Registry 仍要求服务器验证路径。
- 新增持久化兼容层统计库 `workspace/compat_usage.db`，记录：
  - `user_facing_result_fallback_used`
  - `deprecated_raw_job_api_used`
  - `legacy_download_url_used`
  - `prevalidated_executor_used`
  - `include_raw`
  - `legacy_api_used`
  - `direct_command_legacy_api_used`
- 下载 raw 兼容 API 的 `include_raw` 调用会记录来源、调用方、最后使用时间。
- `service.ask` 的已验证执行入口会旁路记录 `prevalidated_executor_used`，用于观察是否仍依赖兼容执行入口。

## 真实业务数据压测结论

已使用受控小型真实结构 fixture 覆盖：

- DEM 坡度坡向；
- NDVI；
- 栅格裁剪失败；
- 重投影/重采样参数；
- 栅格采样到站点表；
- 表格转点；
- 矢量处理基础链路；
- 闪电河流域多产品 fixture 下载；
- waiting_login、失败、取消、恢复、会话删除；
- STM/XGBoost 成功与失败链路；
- artifact resolver、地图图层注册、下载入口和会话删除后的拒绝访问。

未执行真实外部账号下载：

- 成都市 30m DEM 的真实远端下载；
- 闪电河流域真实多产品远端下载。

原因：本地验收环境没有提供发布用 GSCloud/平台账号登录态与配额授权。当前通过 Product Catalog、下载适配器和 fixture 下载链路验证执行合同；真实远端下载需在试运行环境用授权账号单独验收，不能在报告中伪造通过。

## 管理端审核流程

Schema 状态：

- `draft`：创建或修改后的默认状态，不进入 Planner/Context Builder。
- `pending_review`：等待管理员审核，不进入运行时。
- `active`：审核通过，可进入运行时检索。
- `deprecated`：历史版本保留，不进入运行时。
- `disabled`：停用，不进入运行时。
- `enabled`：历史兼容状态，运行时仍可读取，后续应迁移为 `active`。

审核 API：

- `POST /api/admin/capabilities/{resource_type}/{item_id}/status`
- `POST /api/admin/capabilities/{resource_type}/{item_id}/rollback`
- `GET /api/admin/capabilities/audit/events`

兼容统计 API：

- `GET /api/admin/compat-usage/report`

管理员令牌仍只在后端校验，普通用户无法访问系统级配置管理 API。

## 兼容层统计

本地观察窗口：

- 开始时间：`2026-06-22T15:58:59`
- 生成时间：`2026-06-22T19:50:50`
- 有效聊天请求计数：`0`（本报告读取的是当前工作区统计库，浏览器 E2E 使用独立测试工作区）

当前计数：

- `deprecated_raw_job_api_used`: 6
- `include_raw`: 6
- `legacy_download_url_used`: 0
- `user_facing_result_fallback_used`: 0
- `prevalidated_executor_used`: 0
- `legacy_api_used`: 0
- `direct_command_legacy_api_used`: 0

解释：

- 6 次 raw job / include_raw 来自自动化兼容测试的 TestClient，不是普通用户界面主链路。
- 因仍存在测试和受控诊断消费者，本阶段不删除 raw job 兼容层。
- 删除兼容层前必须在自动测试、浏览器 E2E、真实试运行观察窗口中持续为零，并确认没有管理诊断客户端依赖。

## 测试结果

- 后端完整测试：`633 passed, 1 warning, 74 subtests passed`
- 前端单元测试：`17 passed`
- 前端生产构建：通过
- 真实后端浏览器 E2E：`6 passed`
- Python 编译检查：通过

唯一 warning：

- Starlette TestClient 上游弃用提示，不影响当前功能，但建议后续升级测试依赖。

## P0/P1/P2

P0：

- 无阻断发布候选的问题。

P1：

- 真实远端下载未在本环境执行，需要在授权账号和配额受控环境补做：成都市 30m DEM、闪电河流域多产品下载、waiting_login 后登录恢复。
- 后台 Worker 对 GDAL/外部下载子进程的取消仍依赖工具安全检查点和适配器能力，不能声明所有任务都支持任意时刻无损中断。
- 历史 `enabled` 状态仍作为兼容 active 状态存在，需迁移存量配置到 `active` 后再考虑移除。

P2：

- Starlette TestClient 弃用 warning。
- 兼容统计目前记录 `testclient` 调用方，真实部署可进一步接入认证主体和受控客户端标识。
- 发布手册可继续扩充截图和管理员操作示例。

## 性能、可靠性、安全、隐私和数据正确性

性能：

- 小型 fixture 和浏览器 E2E 通过；尚未完成大并发真实远端下载压测。

可靠性：

- DurableJobStore、Worker 队列、幂等提交、取消、重启恢复已有测试覆盖。
- 不安全恢复场景返回明确状态，不伪造成功。

安全与隐私：

- 普通 UI 走 PresentationResult、ManagementView、DiagnosticEventView 和 artifact resolver。
- raw job 仅在 `include_raw=true` 兼容路径返回，并有统计。
- artifact 下载经 artifact_id resolver 与权限校验。
- 会话删除后 artifact、layer、job、私有知识不可访问的测试通过。

数据正确性：

- 核心 GIS fixture 可读、可加载、可下载。
- 地理坐标 DEM 坡度、NDVI 波段缺失、边界无交集等失败场景不会生成伪 artifact。

## 部署与运维说明

部署：

- 设置真实 `GIS_AGENT_ADMIN_TOKEN`。
- 配置 LLM Provider 和模型环境变量。
- 配置 `GIS_AGENT_CAPABILITY_CONFIG_DIR` 或使用默认 `workspace/capability_config`。
- 配置 Product Catalog 中 adapter 的后端 allowlist，禁止任意模块、命令、URL 或代码路径。
- 配置下载源登录态、账号模式、配额和许可。

备份：

- 备份 `workspace/capability_config`、产品目录、公共 Asset Registry、DurableJobStore、商业下载数据库和必要公共资产。
- 不备份会话私有临时文件作为长期系统资产，除非有明确合规策略。

迁移：

- 将历史 `enabled` 配置逐项提交审核并迁移为 `active`。
- 观察兼容统计，确认 raw job、download_url、user_facing_result 旧消费者为零后再删除兼容层。

回滚：

- CapabilityConfigStore 支持按版本 rollback，但 rollback 结果为 `draft`，需要重新审核为 `active`。
- 应保留上一版配置备份和应用部署包。

## 用户手册摘要

普通用户：

- 上传数据后发起明确 GIS 请求。
- 中文请求默认中文回复。
- 文件、图层和下载入口只以结果卡片中的真实 artifact/layer 为准。
- 任务等待登录、确认、失败或阻断时，按卡片提示补充信息或重试。
- 删除会话后，该会话私有数据和成果不可继续访问。

管理员：

- 通过能力管理入口上传知识、维护 Tool Card、Product Catalog、Asset Registry。
- 新增或修改默认为 draft，提交 pending_review，审核后 active。
- 定期查看兼容统计报告、下载诊断事件和审计日志。
- 不在知识文档中配置真实下载能力；真实能力以 Product Catalog、Tool Cards、Validator 和 adapter 为准。

## 已知限制

- 真实外部下载依赖账号、登录态、许可和配额，当前本地验收只覆盖受控 fixture。
- 长时 GDAL/外部下载任务的细粒度取消能力取决于具体适配器。
- Workflow Coordinator 已能按 canonical ToolResult 决策，但不在本轮新增任意动态工具。
- 兼容层尚不能删除：raw job、旧 `enabled`、部分诊断 API 仍保留。

## 封版建议

建议进入“受控试运行”，不建议直接删除兼容层或宣布真实远端下载全部通过。

试运行前必须补做：

- 使用授权账号跑成都市 30m DEM 和闪电河流域多产品真实下载；
- 观察兼容统计至少一个真实业务窗口；
- 确认管理端审核流程和回滚操作由管理员演练通过。
