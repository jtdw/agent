# Runtime Staging and CI Continuation Plan

Date: 2026-06-29
Status: planned

## 背景

Phase 39 已完成 Soil Moisture + XGBoost + GeoConformal Prediction / GCP 主体改造。Phase 45-46 恢复了真实 Shandianhe 三样本 smoke，并新增轻量 recurring gate。Phase 47-52 已把本机 staging 10% readiness、观测窗口、路由 smoke、准真实任务质量窗口和 observation gate 固化。Phase 54-55 已稳定 PR #3 CI 并补充低风险依赖缓存。

当前活动计划位于 `.planning/langchain_agent_redesign`。以下 Codex 会话属于同一工作流，应共享该计划状态：

- `019f07d3-5044-7870-940d-bc362a2b8a8b`
- `019f0f8a-1ed9-7f41-95f0-33bf0607ea22`

## 当前安全边界

- 不直接把 staging exposure 从 10% 提升到更高比例。
- 不自动触碰生产流量。
- 不提交 `.env`、token、cookie、storage state 或真实账号凭据。
- 不为了观测降低鉴权要求。
- 远端或真实 staging 操作前必须先确认目标环境、回滚方式和只读检查命令。

## Phase 56 目标

把 Phase 47-55 的本机证据迁移成“远端 staging 可执行 checklist + CI 性能观测入口”，让下一轮 rollout 决策有明确证据，而不是只依赖本机通过。

完成后应具备：

- 远端 staging 环境变量清单。
- 服务重启/重载步骤。
- 只读 admin exposure 检查步骤。
- recurring observation gate 执行频率建议。
- 真实用户任务观测指标。
- 回滚触发条件和操作。
- CI 缓存效果观测方法。
- 必要的文档/脚本/测试固化。

## Phase 56.1 远端 staging 同步 checklist

目标：把本机 Phase 49-52 gate 迁移到远端或实际部署环境的操作流程写清楚。

建议产物：

- 新增或更新 `docs/runtime/` 下的 staging checklist/runbook。
- 明确远端 `.env` 或部署配置需要包含：
  - `GIS_AGENT_RUNTIME_EXPOSURE_ENV=staging`
  - `GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=10`
  - `GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1`
  - `GIS_AGENT_RUNTIME_ROLLBACK=0`
  - `GIS_AGENT_RUNTIME_REQUIRE_SOIL_MOISTURE_GCP_SMOKE=1`
  - `GIS_AGENT_RUNTIME_SMOKE_REPORT`
  - `GIS_AGENT_RUNTIME_SOIL_MOISTURE_GCP_SMOKE_REPORT`
- 说明服务重启/重载后必须使用只读 admin exposure endpoint 验证配置已生效。
- 明确只输出脱敏状态，不输出密钥、cookie、token 或完整 `.env`。

验收：

- 文档中有远端配置、重启、只读检查、失败处置和回滚步骤。
- 本地文档测试或契约测试能锁住关键命令/字段。

## Phase 56.2 recurring observation gate 频率

目标：定义 staging 10% 观察期间的重复执行节奏。

建议节奏：

- 部署后立即运行一次 full observation gate。
- 观察前 2 小时每 15-30 分钟运行一次。
- 稳定后每 2-4 小时运行一次。
- 每次部署、配置变更、依赖更新或回滚恢复后立即运行一次。

必须采集：

- exposure policy eligibility。
- active smoke 9/9。
- soil moisture/GCP recurring gate `ok=true`。
- routing bucket 分布。
- diagnostics 中 rollback/production override 状态。
- 最近真实任务错误率和 latency 摘要。

## Phase 56.3 真实用户任务指标

目标：从“gate 通过”扩展到“真实任务质量可观察”。

至少记录：

- 请求总量、active 命中量、legacy fallback 量。
- HTTP 4xx/5xx 比例。
- runtime planner fallback 原因分布。
- 外部下载工具误触发次数，期望为 0。
- artifact/map/raster/png/summary 输出成功率。
- soil moisture/GCP 路径是否持续通过 recurring gate。
- p50/p95 latency。
- 用户任务类别：矢量裁剪制图、表格转点制图、XGBoost raster prediction map、answer-only fallback。

注意：

- 指标日志不得包含原始 prompt、完整文件路径、token、cookie、账号密码或原始用户数据行。
- 若必须落盘，使用脱敏摘要和短 hash。

## Phase 56.4 回滚触发条件

以下任一条件应触发 `GIS_AGENT_RUNTIME_ROLLBACK=1` 并重启/重载服务：

- observation gate 失败。
- soil moisture/GCP recurring gate 失败。
- active smoke 低于 9/9。
- 外部下载工具误触发。
- active runtime 5xx 或用户可见错误率明显高于 legacy。
- artifact/map 输出缺失或下载异常重复出现。
- p95 latency 明显劣化且无法快速定位。
- admin exposure 报告不再 eligible 或出现 production override 意外开启。

回滚验证：

- admin exposure 返回 `eligible_for_user_exposure=false`。
- blocking reason 包含 rollback。
- 新请求全部回到 legacy/fallback 路径。
- 记录回滚时间、触发原因、恢复条件和证据文件。

## Phase 56.5 CI 性能观测

目标：观察 Phase 55 缓存是否缩短 GitHub Actions 单次构建耗时。

建议记录：

- `python-tests` 总耗时、Install Python dependencies 耗时。
- `frontend-build` 总耗时、Install frontend dependencies 耗时。
- `smoke` 总耗时、Install Python dependencies、Install frontend dependencies、E2E smoke 耗时。
- `actions/setup-python` pip cache 命中情况。
- `actions/setup-node` npm cache 命中情况。
- Yarn fallback cache restore/save 情况。

不建议：

- 不缓存 `node_modules`。
- 不缓存 `.venv`。
- 不把本地 runner 特有路径写死到跨平台脚本。

## 推荐验证命令

本地文档/契约测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ci_baseline_workflow.py -q
git diff --check
node .\.gitnexus\run.cjs detect-changes --scope all
```

远端 PR 检查：

```powershell
gh pr checks 3 --repo jtdw/agent
```

本机 staging observation gate：

```powershell
pwsh -File .\scripts\run_agent_runtime_staging10_observation_gate.ps1
```

Soil moisture/GCP recurring gate：

```powershell
pwsh -File .\scripts\run_soil_moisture_gcp_smoke.ps1
```

## 下一步建议

优先执行 Phase 56.1：新增远端 staging checklist/runbook，并配一个轻量契约测试锁住关键字段。完成后再决定是否把 recurring gate 频率写成脚本、GitHub Actions workflow_dispatch、或外部调度任务。
