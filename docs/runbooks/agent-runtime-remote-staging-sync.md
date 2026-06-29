# Agent Runtime 远端 Staging 同步 Checklist

Status: Phase 56
Date: 2026-06-29

## 目标和边界

本 runbook 用于把本机 Phase 47-52 的 staging 10% gate 迁移为远端或真实 staging 可执行、可审计、可回滚的流程。它不是提量审批，不允许仅因为本机 gate 通过就把 staging exposure 提到 10% 以上，也不允许触碰 production 或真实生产用户流量。

执行过程中不要输出 `.env` 全文、API key、token、cookie、storage_state、账号密码、原始 prompt、完整用户文件路径或原始用户数据行。需要记录证据时，只记录脱敏状态、短 hash、计数、耗时和通过/失败原因。

## 远端配置核验

远端 staging 部署配置应包含以下 runtime rollout 键。核验时只确认键和值是否符合预期，不打印完整配置文件。

```env
GIS_AGENT_RUNTIME_EXPOSURE_ENV=staging
GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=10
GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1
GIS_AGENT_RUNTIME_ROLLBACK=0
GIS_AGENT_RUNTIME_REQUIRE_SOIL_MOISTURE_GCP_SMOKE=1
GIS_AGENT_RUNTIME_SMOKE_REPORT=outputs/phase52_staging10_observation_gate.json
GIS_AGENT_RUNTIME_SOIL_MOISTURE_GCP_SMOKE_REPORT=outputs/phase45_real_soil_gcp_smoke/phase45_real_soil_gcp_recurring_smoke_summary.json
GIS_AGENT_RUNTIME_SOIL_MOISTURE_GCP_SMOKE_SUMMARY=outputs/phase45_real_soil_gcp_smoke/phase45_real_soil_gcp_recurring_smoke_summary.json
GIS_AGENT_RUNTIME_REQUIRE_LLM_SMOKE=0
GIS_AGENT_RUNTIME_ALLOW_PRODUCTION_EXPOSURE=0
```

`GIS_AGENT_RUNTIME_SOIL_MOISTURE_GCP_SMOKE_REPORT` 是 Phase 56 checklist 中使用的可读名称；若当前服务仍读取 `GIS_AGENT_RUNTIME_SOIL_MOISTURE_GCP_SMOKE_SUMMARY`，两者应指向同一份 recurring gate summary，直到代码层完成兼容统一。

## 部署和重启步骤

1. 在远端 staging 配置系统中写入或核验上述键值。
2. 重启或重载 staging 服务，让运行中的 FastAPI 进程重新读取配置。
3. 不发送普通用户请求做探测，先使用只读 admin exposure endpoint 验证运行态配置。
4. 若只读检查不通过，先停在 legacy/fallback 路径，不继续执行真实任务观测。

PowerShell 只读检查示例：

```powershell
Invoke-RestMethod `
  -Uri "https://<staging-host>/api/admin/agent-runtime/exposure" `
  -Headers @{ "x-admin-token" = "<admin-token>" }
```

必须检查这些字段：

- `/api/admin/agent-runtime/exposure` 返回 HTTP 200。
- `eligible_for_user_exposure=true`。
- `recommendation=allow_staging_exposure`。
- `environment=staging`。
- `requested_percent=10`。
- `rollback_requested=false`。
- `production_override=false` 或等价字段未开启。
- `deterministic_smoke.status=passed`。
- soil moisture/GCP recurring gate `ok=true` 或等价状态通过。

若返回 `eligible_for_user_exposure=false`、`recommendation=do_not_expose_users`、`rollback_requested=true`、缺少 smoke 报告、缺少 soil moisture/GCP 报告或出现 production override 意外开启，立即停止后续观测并按回滚流程处理。

## 本地和远端 Gate 命令

本机复核命令：

```powershell
pwsh -File .\scripts\run_agent_runtime_staging10_observation_gate.ps1
pwsh -File .\scripts\run_soil_moisture_gcp_smoke.ps1
```

远端 staging 应使用同等脚本或部署平台的等价任务执行，产物写入部署约定的 `outputs/` 或 CI artifact 目录。证据文件只保留脱敏摘要，不保留原始账号凭据、cookie、token、storage_state、完整 prompt 或完整用户文件内容。

## Recurring Observation Gate 频率

- 部署后立即运行一次 full observation gate。
- 观察前 2 小时每 15-30 分钟运行一次。
- 稳定后每 2-4 小时运行一次。
- 每次部署、配置变更、依赖更新、回滚恢复后立即运行一次。

每次 observation gate 必须采集：

- exposure policy eligibility。
- active smoke 9/9。
- soil moisture/GCP recurring gate `ok=true`。
- routing bucket 分布和 active/legacy 比例。
- diagnostics 中 rollback 与 production override 状态。
- 最近真实任务错误率和 p50/p95 latency 摘要。

## 真实用户任务指标

真实 staging 任务观测要从“gate 通过”扩展到“任务质量可观察”。至少记录：

- 请求总量。
- active 命中量。
- legacy fallback 量。
- HTTP 4xx/5xx 比例。
- runtime planner fallback 原因分布。
- 外部下载工具误触发次数，期望为 0。
- artifact/map/raster/png/summary 输出成功率。
- soil moisture/GCP 路径是否持续通过 recurring gate。
- p50/p95 latency。
- 用户任务类别：矢量裁剪制图、表格转点制图、XGBoost raster prediction map、answer-only fallback。

指标日志不得包含原始 prompt、完整路径、token、cookie、账号密码、storage_state 或原始用户数据行。需要关联请求时使用短 hash。

## 回滚触发条件

以下任一条件出现，应设置 `GIS_AGENT_RUNTIME_ROLLBACK=1`，重启或重载 staging 服务，并重新调用只读 admin exposure endpoint 验证：

- observation gate 失败。
- soil moisture/GCP recurring gate 失败。
- active smoke 低于 9/9。
- 外部下载工具误触发。
- active runtime 5xx 或用户可见错误率明显高于 legacy。
- artifact/map 输出缺失或下载异常重复出现。
- p95 latency 明显劣化且无法快速定位。
- admin exposure 报告不再 eligible。
- production override 意外开启。

回滚验证必须满足：

- `eligible_for_user_exposure=false`。
- blocking reason 或 `reasons` 包含 `rollback_requested`。
- 新请求全部回到 legacy/fallback 路径。
- 记录回滚时间、触发原因、恢复条件和证据文件。

恢复 rollout 前必须重新运行 full observation gate 和 soil moisture/GCP recurring gate，并确认 rollback 已恢复为 `GIS_AGENT_RUNTIME_ROLLBACK=0`。

## CI 缓存效果观测

Phase 55 只允许缓存 package-manager 下载缓存，不缓存安装产物目录。远端 CI 观测命令：

```powershell
gh pr checks 3 --repo jtdw/agent
```

建议记录这些 job 和步骤耗时：

- `python-tests` 总耗时。
- `python-tests` 中 `Install Python dependencies` 耗时。
- `frontend-build` 总耗时。
- `frontend-build` 中 `Install frontend dependencies` 耗时。
- `smoke` 总耗时。
- `smoke` 中 `Install Python dependencies`、`Install frontend dependencies` 和 E2E smoke 耗时。
- `actions/setup-python` pip cache restore/save 命中情况。
- `actions/setup-node` npm cache 命中情况。
- `Yarn fallback cache` restore/save 命中情况。

不要缓存 node_modules。
不要缓存 .venv。
不要把 runner 本地绝对路径写死进跨平台脚本或 workflow。

## Phase 56 验收

Phase 56 可视为完成的最低条件：

- 远端 staging 配置、重启、只读 admin exposure 检查、失败处置和回滚步骤已固化。
- recurring observation gate 频率和采集字段已明确。
- 真实用户任务指标、latency、artifact/map/raster/png/summary 输出、外部下载误触发和 soil moisture/GCP gate 均有观测入口。
- CI 缓存效果观测方法已明确，并保持不缓存 `node_modules` 或 `.venv`。
- 文档契约测试通过，后续修改不会静默删除关键 checklist 字段。
