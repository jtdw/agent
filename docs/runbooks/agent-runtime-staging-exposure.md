# Agent Runtime Active Staging 暴露 Runbook

## 目标

本 runbook 用于把 Agent Runtime active mode 从本地验证推进到 staging 小比例验证。它不要求也不建议直接进入 production。默认策略是先观察，再 1%，再 5%，最高到 10%，每一步都保留一键回滚。

## 前置条件

- `GIS_AGENT_RUNTIME_V2=1`
- `GIS_AGENT_RUNTIME_MODE=active`
- `GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER=1`
- `scripts/test_agent_runtime_decision_eval.ps1` 通过
- `scripts/test_agent_runtime_active_smoke.ps1` 通过
- 如需要 LLM coordinator 门禁，再手动运行：

```powershell
.\scripts\test_agent_runtime_active_smoke.ps1 -IncludeLlmCoordinatorSmoke
```

## 只读检查

使用管理员 token 调用只读端点：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/admin/agent-runtime/exposure" `
  -Headers @{ "x-admin-token" = "<admin-token>" }
```

返回结果中的关键字段：

- `eligible_for_user_exposure`: 是否具备放量资格。
- `recommendation`: 当前建议，例如 `do_not_expose_users` 或 `allow_staging_exposure`。
- `reasons`: 阻止放量的具体原因。
- `deterministic_smoke.status`: deterministic smoke 是否通过。
- `llm_smoke.status`: LLM coordinator smoke 是否通过或是否不要求。

## Staging 1% 流程

在 staging 环境设置：

```env
GIS_AGENT_RUNTIME_EXPOSURE_ENV=staging
GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=1
GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1
GIS_AGENT_RUNTIME_EXPOSURE_SALT=agent-runtime-exposure-v1
GIS_AGENT_RUNTIME_ROLLBACK=0
GIS_AGENT_RUNTIME_SMOKE_REPORT=outputs/agent_runtime_service_active_smoke_guard.json
GIS_AGENT_RUNTIME_REQUIRE_SOIL_MOISTURE_GCP_SMOKE=1
GIS_AGENT_RUNTIME_SOIL_MOISTURE_GCP_SMOKE_SUMMARY=outputs/phase45_real_soil_gcp_smoke/phase45_real_soil_gcp_recurring_smoke_summary.json
GIS_AGENT_RUNTIME_REQUIRE_LLM_SMOKE=0
GIS_AGENT_RUNTIME_ALLOW_PRODUCTION_EXPOSURE=0
```

然后重启 staging 服务，调用 `/api/admin/agent-runtime/exposure`。只有当 `eligible_for_user_exposure=true` 且 `recommendation=allow_staging_exposure` 时，才允许把 staging 流量接入 active 验证。

## Phase 47: Staging 10% readiness dry-run

进入真实 10% 暴露前，先运行只读 dry-run：

```powershell
.\scripts\run_agent_runtime_staging_exposure_dry_run.ps1
```

该脚本会依次执行：

- `run_agent_runtime_active_smoke.ps1`，验证 active smoke guard。
- `run_soil_moisture_gcp_smoke.ps1 -ValidateOnly`，验证 Phase 45/46 recurring soil moisture/XGBoost/GCP summary。
- `python -m core.agent_runtime.exposure staging-dry-run --percent 10`，生成 staging 10% readiness evidence。

通过条件：

- `deterministic_smoke.status=passed`
- `soil_moisture_gcp_smoke.status=passed`
- `eligible_for_user_exposure=true`
- `recommendation=allow_staging_exposure`
- `live_traffic_changed=false`

这一步只写入 `outputs/agent_runtime_exposure_staging_dry_run.json`，不修改 `.env`，不切换真实流量。

## Staging 5% 到 10%

1% 验证稳定后，可以逐步改为：

```env
GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=5
```

再观察一轮真实任务。若无阻断问题，再改为：

```env
GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=10
```

策略层会阻止 staging 初始比例超过 10%。更高比例需要先完成新的验证阶段。

## Phase 53: 远端 staging 10% 观测

本机 Phase 49-52 gate 通过后，不要直接把 staging 提升到更高比例。先按 [agent-runtime-phase53-remote-staging-observation.md](agent-runtime-phase53-remote-staging-observation.md) 把 10% gate 迁移到远端 staging 或实际部署环境，完成只读 admin exposure 检查、recurring observation gate、真实任务指标观察和 rollback probe。

## 可选 LLM Coordinator 门禁

当需要把 LLM coordinator smoke 纳入 staging 门禁时：

```env
GIS_AGENT_RUNTIME_REQUIRE_LLM_SMOKE=1
GIS_AGENT_RUNTIME_LLM_SMOKE_REPORTS=outputs/agent_runtime_service_llm_coordinator_describe_guard.json,outputs/agent_runtime_service_llm_coordinator_map_guard.json,outputs/agent_runtime_service_llm_coordinator_table_points_guard.json
```

启用后，任一 LLM smoke 报告缺失或失败，`eligible_for_user_exposure` 都应为 `false`。

## 回滚

发现 active 行为异常时，优先设置：

```env
GIS_AGENT_RUNTIME_ROLLBACK=1
```

重启服务后再次调用 `/api/admin/agent-runtime/exposure`，应看到：

- `eligible_for_user_exposure=false`
- `reasons` 包含 `rollback_requested`

如需完全退出 active runtime，再设置：

```env
GIS_AGENT_RUNTIME_MODE=shadow
```

## Production 禁止项

不要直接把 staging 配置复制到 production。production 至少需要：

- 单独的 production smoke 报告。
- 明确的人工审批记录。
- `GIS_AGENT_RUNTIME_ALLOW_PRODUCTION_EXPOSURE=1`。
- 独立的回滚窗口和监控确认。

默认 `GIS_AGENT_RUNTIME_ALLOW_PRODUCTION_EXPOSURE=0`，因此 production 会被策略层阻止。
