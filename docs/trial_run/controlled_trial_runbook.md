# 受控试运行手册

## 1. 环境隔离

必须使用三套互不复用的环境。

| 环境 | 用途 | workspace | 数据库 | artifact | 兼容统计 | 管理员 token |
|---|---|---|---|---|---|---|
| development | 本地开发和手工调试 | `workspace/dev` 或开发者本机默认目录 | 开发库 | 开发目录 | 开发统计 | 开发 token |
| test | 自动化测试、fixture、Playwright | 测试临时目录 | 临时库 | 临时目录 | 测试统计，`actor_type=automated_test` | 测试 token |
| trial | 真实授权试运行 | `workspace/trial` | 试运行专用库 | 试运行专用目录 | 试运行统计，默认排除 automated_test | 试运行 token |

配置要求：

- `GIS_AGENT_ADMIN_TOKEN` 每个环境必须不同。
- `GIS_AGENT_CAPABILITY_CONFIG_DIR` 每个环境必须不同。
- 试运行环境不得指向测试 fixture 目录。
- 试运行环境不得复用开发或测试的 `compat_usage.db`、`trial_monitoring.db`、DurableJobStore、commercial 数据库。
- 自动化测试调用必须标记为 `actor_type=automated_test`。HTTP 测试可使用 `x-actor-type: automated_test`；TestClient/Playwright User-Agent 会被后端自动识别。
- 试运行报告默认排除 `automated_test`。

## 2. 当前测试 warning

完整后端测试中存在 1 个 warning：

- `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`

结论：

- 这是测试依赖层的弃用提示，不影响运行时 API、LLM-first 链路、下载、artifact resolver 或权限控制。
- 当前登记为 P2 可接受风险。
- 后续升级测试依赖或 Starlette/httpx2 时再处理，避免在发布候选阶段引入依赖 churn。

## 3. 真实授权验收

以下步骤必须在具备真实许可、账号、Cookie/登录态和配额的 trial 环境完成。不得使用 fixture、手工造 artifact 或修改数据库伪造成功。

### 3.1 成都市 30m DEM

1. 使用中文普通聊天请求：`下载成都市30m的DEM数据`。
2. 验证 Planner 生成下载 TaskPlan，区域为成都市真实边界，产品来自 Product Catalog。
3. Validator 通过后进入下载执行，不绕过 Planner。
4. 任务成功后检查：
   - ToolResult `status=succeeded`；
   - DownloadManagementView 有 artifact_refs；
   - artifact resolver 可下载；
   - 预览可打开；
   - 地图图层可加载；
   - 文件可由 GIS 工具重新读取。

### 3.2 闪电河流域多产品下载

请求：`下载闪电河流域2020年6月至8月的EVI、地表反射率和Sentinel数据`。

验收：

- 区域必须使用 `library:basin:shandianhe`；
- 每个产品独立 download_request、独立状态、独立 ToolResult；
- 任一产品无数据或失败时，不影响其他产品真实成功结果；
- 不伪造失败产品 artifact。

### 3.3 waiting_login 恢复

1. 清空或使登录态过期。
2. 发起需要登录的数据下载。
3. 验证状态为 `awaiting_confirmation` 或 `waiting_login`，中文说明要求登录。
4. 完成真实登录。
5. 重试或恢复任务。
6. 验证任务真实继续执行，成功后 artifact 可访问。

### 3.4 真实失败

至少制造一种真实失败：

- 远端无数据；
- 配额不足；
- 登录失效；
- 产品时间范围不可用。

验收：

- ToolResult `status=failed` 或 `blocked`；
- 中文 `user_message` 说明真实原因；
- 没有成功模板；
- 没有虚假 artifact；
- ProductConsole 与聊天结果状态一致。

## 4. 监控指标

持久化位置：

- 兼容统计：`workspace/trial/compat_usage.db`
- 试运行指标：`workspace/trial/trial_monitoring.db`

只记录结构化指标，不记录用户原文全文、Token、Cookie、内部路径或敏感数据。

指标：

- Planner 成功率：`planner_success`
- 澄清率：`planner_clarification`
- Validator 阻断：`validator_blocked`
- 工具成功：`tool_succeeded`
- 工具失败：`tool_failed`
- 下载失败：`download_failed`
- Worker 取消：`worker_cancelled`
- Worker 恢复：`worker_recovered`
- artifact 注册失败：`artifact_registration_failed`
- 兼容层调用：`compat_layer_used`

管理 API：

- `GET /api/admin/compat-usage/report`
- `GET /api/admin/trial-monitoring/report`

两个报告默认排除 `automated_test`。

## 5. P0/P1 告警

P0：

- 跨会话或跨用户访问成功；
- 下载区域错误；
- 关键词绕过 Planner；
- 伪造 artifact；
- 任务取消后继续写入成功产物。

P1：

- 权限错误；
- 登录态恢复失败；
- 配额不足未给出清晰中文说明；
- Validator 阻断原因不清楚；
- artifact 注册失败。

## 6. 退出条件

建议观察周期：

- 至少 7 个自然日，或覆盖两个完整业务工作日加一个周末。

最低有效任务量：

- 普通聊天 GIS 请求不少于 50 次；
- 下载请求不少于 20 次；
- 栅格/矢量/表格/制图/建模任务每类不少于 5 次；
- 至少 3 次真实失败恢复或重试。

阻断条件：

- 任一 P0 未关闭；
- P1 超过 3 个且无明确规避方案；
- 真实远端下载核心产品未通过；
- 兼容统计显示普通 UI 仍依赖 raw job、legacy download_url 或 user_facing_result fallback；
- 出现跨会话数据串用或删除会话后数据仍可访问。

兼容层删除条件：

- 自动测试、浏览器 E2E 和真实试运行报告中均持续零使用；
- 观察窗口内 `deprecated_raw_job_api_used`、`legacy_download_url_used`、`user_facing_result_fallback_used` 均为 0；
- 没有管理诊断客户端仍依赖 raw job；
- 删除前有回滚方案。

正式封版条件：

- 真实授权验收全部通过；
- P0 为 0；
- P1 有关闭记录或明确发布说明；
- 管理配置审核、回滚、兼容统计报告可由管理员独立操作；
- 备份、部署、登录态、数据源许可和回滚流程演练完成。
