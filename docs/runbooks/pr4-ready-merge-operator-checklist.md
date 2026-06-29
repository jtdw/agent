# PR #4 Ready / Merge 操作清单

Date: 2026-06-29
Scope: Phase 60F operator checklist
PR: https://github.com/jtdw/agent/pull/4

## 目的

这份清单用于负责人确认后执行 PR #4 ready / merge / merge 后验证。

它不是授权记录。本清单本身不代表可以自动转 ready、合并 `main`、提升 staging exposure、执行真实远端 staging、触碰 production 或接入真实用户流量。

## 当前推荐状态

PR #4 已具备 ready-state 决策证据：

- PR open / draft / merge state clean。
- 远端 CI 当前绿：`changes`、`python-tests`、`smoke-light`、CodeRabbit。
- 本地 gate 已复现：knowledge/runbook/CI contract tests、soil moisture/GCP recurring gate、staging10 observation gate。
- 交付审计和目标完成度审计已固化：
  - `docs/runbooks/pr4-knowledge-activation-delivery-audit.md`
  - `docs/runbooks/phase60e-goal-completion-audit.md`

## 人工确认点

以下动作必须逐项确认，不允许一次确认隐含全部后续动作：

1. 确认是否将 PR #4 从 draft 转为 ready。
2. 确认是否合并 PR #4 到 `main`。
3. 确认是否在真实远端 staging 执行同步 checklist。
4. 确认是否调整 staging exposure。
5. 确认是否触碰 production 或真实用户流量。

## Ready 前检查

```powershell
git status --short --branch
gh pr view 4 --repo jtdw/agent --json number,title,isDraft,state,headRefName,baseRefName,mergeStateStatus,url
gh pr checks 4 --repo jtdw/agent
```

要求：

- 工作区干净。
- PR #4 仍指向预期 head 分支。
- `mergeStateStatus` 为 `CLEAN` 或 GitHub 明确允许合并的等效状态。
- required checks 通过；skipped job 与路径/事件规则一致。

## 转 Ready

只有在负责人明确确认“转 ready”后执行：

```powershell
gh pr ready 4 --repo jtdw/agent
gh pr view 4 --repo jtdw/agent --json isDraft,state,mergeStateStatus
gh pr checks 4 --repo jtdw/agent
```

要求：

- `isDraft=false`。
- PR 仍 open。
- checks 保持绿色。

转 ready 不等于合并，也不等于提高 exposure。

## 合并前最后检查

只有在负责人明确确认“准备合并”后执行本节。

```powershell
git fetch origin main
gh pr view 4 --repo jtdw/agent --json isDraft,state,mergeStateStatus,statusCheckRollup
gh pr checks 4 --repo jtdw/agent
```

合并前必须重新确认：

- PR 非 draft。
- PR checks 仍绿色。
- merge state 可合并。
- 没有新增 review blocker。
- 没有要求改变认证、权限、计费、下载安全策略。
- 没有要求执行数据库迁移或破坏性操作。

## 合并

只有在负责人明确确认“合并 PR #4 到 main”后执行。优先使用 GitHub PR 合并机制，不手动改写 `main`：

```powershell
gh pr merge 4 --repo jtdw/agent --merge --delete-branch=false
```

如果仓库策略要求 squash 或 rebase，应按负责人指定策略执行，不要自行更换合并策略。

## 合并后只读 / 本地验证

合并后不自动提升 staging exposure。先做只读和本地 gate：

```powershell
git fetch origin main
git switch main
git pull --ff-only origin main
git status --short --branch
gh run list --repo jtdw/agent --branch main --limit 5
pwsh -File .\scripts\run_soil_moisture_gcp_smoke.ps1
pwsh -File .\scripts\run_agent_runtime_staging10_observation_gate.ps1
```

要求：

- `main` 工作区干净。
- 最新 main CI 成功或正在运行并可追踪。
- soil moisture/GCP recurring gate `ok=true`。
- staging10 observation gate `ok=true`。
- 无外部下载工具误触发。

## 真实远端 staging

真实远端 staging 仍是单独确认点。确认后应按 `docs/runbooks/agent-runtime-remote-staging-sync.md` 执行。

必须保持：

- 不输出 `.env`、API key、token、cookie、storage_state。
- 服务重启/重载后用只读 admin exposure 检查确认配置。
- 先运行 recurring observation gate，再收集真实任务指标。
- 不因本地 gate 或 PR CI 绿色自动提升 exposure。

## 回滚验证

如真实 staging 观测失败，优先使用：

```powershell
GIS_AGENT_RUNTIME_ROLLBACK=1
```

然后重启/重载目标服务，并用只读 admin exposure 检查确认：

- `eligible_for_user_exposure=false`
- blocking reason 包含 rollback
- 新请求回到 legacy/fallback 路径

## 禁止事项

- 不要在未确认时合并 PR 或修改 `main`。
- 不要在未确认时提高 staging exposure。
- 不要触碰 production 或真实用户流量。
- 不要执行数据库迁移、删除数据或破坏性操作。
- 不要改变认证、权限、计费或下载安全策略方向。
- 不要输出 `.env`、API key、token、cookie、storage_state 或敏感日志。
