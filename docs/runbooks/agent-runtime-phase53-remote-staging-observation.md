# Agent Runtime Phase 53 远端 staging 10% 观测 Runbook

## 目标

Phase 53 的目标是把本机 Phase 49-52 已通过的 staging 10% gate 迁移到远端 staging 或实际部署环境，并保留清晰、可验证、可回滚的观测方案。该阶段不提升流量比例，不进入 production，不扩大到 10% 以上。

当前基线提交为 `f0d3a69 test(runtime): add staging observation gate`。远端环境应部署该提交或包含该提交的后续版本。

## 远端环境基线

远端 staging 服务应确认以下环境变量已经生效：

```env
GIS_AGENT_RUNTIME_EXPOSURE_ENV=staging
GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=10
GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1
GIS_AGENT_RUNTIME_ROLLBACK=0
GIS_AGENT_RUNTIME_REQUIRE_SOIL_MOISTURE_GCP_SMOKE=1
```

检查时不要打印 `.env`、API key、admin token、cookie、storage_state 或日志中的敏感值。只记录是否配置、暴露比例、HTTP 状态、错误码和脱敏错误信息。

## 只读 admin exposure 检查

在远端服务重启或 reload 后，先执行只读检查：

```powershell
.\scripts\run_agent_runtime_remote_staging10_check.ps1 `
  -BaseUrl "https://staging.example.com" `
  -OutputPath "outputs/phase53_remote_staging10_baseline.json"
```

脚本只调用 `/api/admin/agent-runtime/exposure`，不会修改远端 `.env` 或运行时开关。管理员 token 使用 `GIS_AGENT_ADMIN_TOKEN` 环境变量或 `-AdminToken` 参数传入，执行摘要不得输出 token。

在 CI 或 recurring automation 中建议加上 `-FailOnNotReady`，这样任一检查不通过时任务会返回非零退出码：

```powershell
.\scripts\run_agent_runtime_remote_staging10_check.ps1 `
  -BaseUrl "https://staging.example.com" `
  -OutputPath "outputs/phase53_remote_staging10_baseline.json" `
  -FailOnNotReady
```

通过条件：

- `schema_version=agent-runtime-exposure-policy/v1`
- `environment=staging`
- `requested_percent=10`
- `rollback_requested=false`
- `eligible_for_user_exposure=true`
- `recommendation=allow_staging_exposure`
- `deterministic_smoke.status=passed`
- `soil_moisture_gcp_smoke.status=passed`

## Observation gate 证据

远端 staging 的 Phase 53 证据建议保存为：

- `outputs/phase53_remote_staging10_baseline.json`
- `outputs/phase53_remote_staging10_observation_gate.json`
- `outputs/phase53_remote_staging10_rollback_probe.json`

如果远端执行环境能访问同一套样本和 outputs 路径，可继续使用本机已固化的 gate：

```powershell
.\scripts\run_agent_runtime_staging10_observation_gate.ps1 `
  -OutputPath "outputs/phase53_remote_staging10_observation_gate.json"
```

如果远端采用 CI、容器或平台任务运行，应把上述 JSON 作为 CI artifact 或部署证据归档，和服务 commit、执行时间、BaseUrl、执行人/任务 ID 绑定。

完成 baseline、observation gate 和 rollback probe 后，运行离线证据汇总：

```powershell
.\scripts\validate_agent_runtime_phase53_evidence.ps1 `
  -BaselinePath "outputs/phase53_remote_staging10_baseline.json" `
  -ObservationGatePath "outputs/phase53_remote_staging10_observation_gate.json" `
  -RollbackProbePath "outputs/phase53_remote_staging10_rollback_probe.json" `
  -OutputPath "outputs/phase53_remote_staging10_evidence_summary.json"
```

汇总文件只记录输入文件名和关键判定，不保存远端绝对路径或 admin token。

## recurring observation gate 频率

初始远端 staging 24 小时内，每 30 分钟执行一次只读 admin exposure 检查和 observation gate。若连续窗口无异常，可降为每 2 小时一次。任何升流前，必须恢复每 30 分钟一次，并至少覆盖 4 个连续窗口。

每次 recurring gate 至少记录：

- exposure policy 和 routing distribution 是否符合 staging 10%。
- diagnostics、active smoke、soil moisture/GCP smoke 是否通过。
- 最近窗口错误率、HTTP 4xx/5xx、工具结构化错误。
- artifact/map 输出是否存在、非空、绑定正确 user/session。
- 是否出现外部下载误触发。
- latency 的 P50/P95/P99，特别是 routing、planner、GIS 工具、artifact 注册和地图预览生成耗时。

## 真实用户任务观测指标

Phase 53 只观测远端 staging 10%，不扩大比例。重点指标如下：

- 错误率：active runtime planner 错误率、legacy fallback 错误率、HTTP 4xx/5xx、工具执行结构化错误。
- 外部下载误触发：不得在无用户确认的情况下触发 NOAA、GSCloud、GEE 类远端下载，也不得访问 workspace 外路径。
- artifact/map：artifact 下载权限、map layer session 绑定、PNG/GeoJSON/CSV/栅格输出存在且非空。
- soil moisture/GCP：soil moisture/GCP smoke 稳定通过，XGBoost raster prediction 产出 raster/png/summary。
- latency：active runtime 的 P95/P99 不应明显高于 legacy fallback；异常时暂停升流。

## 回滚触发条件

出现以下任一硬触发，立即回滚：

- admin exposure 检查失败。
- deterministic active smoke 失败。
- soil moisture/GCP required smoke 失败。
- 出现跨用户或跨会话 artifact/map layer 迹象。
- 出现外部下载误触发。
- active runtime 5xx 明显升高。
- 输出路径逃逸 workspace。
- artifact 暴露 `.env`、token、cookie、storage_state、日志或数据库等敏感文件风险。

以下情况暂停升流并调查：

- routing sample 明显偏离 10%。
- active planner fallback 比例异常。
- latency P95/P99 明显劣化。
- 中文文件名、中文字段名、中文 JSON 或中文日志任务失败。
- map 预览偶发缺失，或 summary 缺失但主产物存在。

## 回滚操作

远端 staging 回滚只使用一个主开关：

```env
GIS_AGENT_RUNTIME_ROLLBACK=1
```

操作步骤：

1. 设置 `GIS_AGENT_RUNTIME_ROLLBACK=1`。
2. 重启或 reload 远端 staging 服务。
3. 再次执行：

```powershell
.\scripts\run_agent_runtime_remote_staging10_check.ps1 `
  -BaseUrl "https://staging.example.com" `
  -OutputPath "outputs/phase53_remote_staging10_rollback_probe.json"
```

4. 确认 admin exposure 返回 `eligible_for_user_exposure=false`，且 `reasons` 包含 `rollback_requested`。
5. 执行最小 routed request smoke，确认原本 10% 内 bucket 也走 legacy fallback。

## 后续门槛

只有当远端 Phase 53 证据连续稳定，且没有硬触发或未解释的软触发时，才允许规划下一阶段。下一阶段仍应先写 gate，不应直接把 staging 提高到更大比例。
