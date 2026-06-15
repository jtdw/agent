# GIS 智能体结构清理实施计划

> 依据设计：`docs/superpowers/specs/2026-06-15-agent-structure-cleanup-design.md`

## 实施原则

- 使用测试驱动：每个行为迁移先补失败测试，再移动实现。
- 每个阶段独立提交，测试通过后才能进入下一阶段。
- 不混合结构迁移、行为修改和运行数据删除。
- 不覆盖当前工作区中无法确认归属的改动。
- 运行数据清理必须先 dry-run、备份和校验路径。

## 阶段 0：隔离与基线

### 任务 0.1：建立独立工作区

- 从当前分支创建专用 worktree/分支 `refactor/agent-structure-cleanup`。
- 保存当前工作区状态和基线提交号。
- 不把 `workspace/`、`artifacts/`、浏览器缓存带入结构迁移提交。

验收：

```powershell
git status --short
git rev-parse HEAD
```

### 任务 0.2：固化完整回归基线

记录以下命令的结果和耗时：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m compileall core tests api_server.py app.py
.venv\Scripts\python.exe -m unittest discover tests
cd ui_next
npm test
npm run build
npx playwright test
```

新增或确认覆盖：

- 认证、聊天、地图图层、下载任务、GSCloud 登录恢复；
- 本地县级边界查询；
- artifact 注册、下载和敏感文件拦截；
- 移动端聊天登录引导；
- 当前公开 HTTP API 路由清单。

提交：`test: establish refactor regression baseline`

### 任务 0.3：生成依赖和删除候选清单

新增只读审计脚本 `scripts/audit_code_structure.py`，输出：

- Python 模块引用关系；
- API 路由及所属模块；
- 超大文件、重复函数名、兼容别名；
- 前端组件依赖；
- legacy、deprecated、TODO 和无引用候选；
- 运行目录、数据库表和文件占用统计。

输出到非源码临时目录，不提交扫描结果。

测试：`tests/test_audit_code_structure.py`

提交：`chore: add structure audit tooling`

## 阶段 1：领域模型统一

### 任务 1.1：统一任务状态

新增：

- `domain/downloads/status.py`
- `domain/downloads/models.py`
- `domain/downloads/policies.py`

统一状态：

`waiting_parameters`、`waiting_login`、`ready_to_start`、`queued`、`running`、`success`、`failed`、`cancelled`。

迁移：

- `core/download_status.py`
- `core/commercial/service.py`
- GSCloud scene/tile workers；
- 前端状态映射。

先新增跨模块契约测试，确认等待状态不被描述为运行中。

提交：`refactor: centralize download job status model`

### 任务 1.2：统一聊天动作模型

新增：

- `domain/chat/actions.py`
- `domain/chat/messages.py`

定义 `clarification_required`、`login_required`、`resume_download`、`cancel_task` 和 artifact 消息契约。

迁移：

- `core/chat_response.py`
- `core/api_helpers.py`
- `core/task_planner.py`
- `core/task_slots.py`
- 前端 `ChatMessageRenderer`。

删除重复字典拼装前，确保 API 契约测试覆盖所有动作。

提交：`refactor: introduce structured chat action contracts`

### 任务 1.3：统一 artifact 模型和安全策略

新增：

- `domain/artifacts/models.py`
- `domain/artifacts/policies.py`

迁移 `core/artifacts.py` 中的纯规则，集中维护：

- 公共字段；
- MIME/文件类型；
- 禁止下载路径和敏感文件规则；
- artifact 所有权。

提交：`refactor: centralize artifact domain policies`

## 阶段 2：基础设施封装

### 任务 2.1：数据库仓储拆分

新增：

```text
infrastructure/database/
  connection.py
  users.py
  conversations.py
  datasets.py
  jobs.py
  artifacts.py
  model_results.py
```

从以下文件逐步迁移 SQL：

- `core/workspace_db.py`
- `core/commercial/database.py`
- `core/commercial/service.py`

保留薄 facade，直到调用方全部迁移。每个 repository 使用临时 SQLite 集成测试。

提交：`refactor: split database repositories`

### 任务 2.2：文件存储边界

新增：

- `infrastructure/storage/workspace_paths.py`
- `infrastructure/storage/artifact_store.py`
- `infrastructure/storage/local_library_store.py`
- `infrastructure/storage/secure_delete.py`

集中处理：

- 工作区路径解析；
- 用户隔离；
- ZIP 安全解压；
- Shapefile 侧文件；
- artifact 白名单；
- 受控递归删除。

迁移 `core/data_manager.py` 中的文件系统职责。

提交：`refactor: isolate workspace storage operations`

### 任务 2.3：Playwright 与 GSCloud provider

新增：

```text
infrastructure/browser/playwright_session.py
infrastructure/providers/gscloud/auth.py
infrastructure/providers/gscloud/dem.py
infrastructure/providers/gscloud/scenes.py
infrastructure/providers/gscloud/verification.py
```

迁移：

- 登录会话去重、停止和 storage state 保存；
- DEM 分幅搜索、断点续传和验证；
- scene 产品下载；
- Cookie 健康检查。

worker 仅调用 provider/service，不直接包含业务状态规则。

提交：`refactor: isolate gscloud provider infrastructure`

## 阶段 3：服务层拆分

### 任务 3.1：数据源账号服务

新增 `services/data_sources/gscloud_accounts.py`，负责：

- status/start/complete/logout；
- 用户所有权校验；
- storage state 路径映射；
- waiting_login 任务发现。

迁移 `api_server.py` 和 `core/commercial/service.py` 对应逻辑。

提交：`refactor: extract gscloud account service`

### 任务 3.2：下载任务服务

新增：

- `services/downloads/jobs.py`
- `services/downloads/planner.py`
- `services/downloads/resume.py`
- `services/downloads/results.py`

负责参数校验、登录预检、任务恢复、worker 启动和结果 artifact 注册。

迁移 GSCloud direct-router 中的任务创建逻辑，删除 API 层直接调用私有 `_update_job`。

提交：`refactor: extract download application services`

### 任务 3.3：聊天服务

新增：

- `services/chat/coordinator.py`
- `services/chat/persistence.py`
- `services/chat/response_builder.py`
- `services/chat/context.py`

从 `core/service.py` 提取：

- 会话加载和持久化；
- 意图/任务规划编排；
- 工具执行；
- 结构化动作与 artifact 消息；
- 结果解释。

防止 dashboard 历史结果污染当前回复的测试必须持续通过。

提交：`refactor: split chat coordination services`

### 任务 3.4：本地库与工作区服务

新增：

- `services/local_library/catalog.py`
- `services/local_library/importer.py`
- `services/workspaces/datasets.py`

统一唯一的 `GIS_AGENT_LOCAL_LIBRARY_DIR`，移除重复 fallback 根目录。

提交：`refactor: unify local library and dataset services`

## 阶段 4：API 路由拆分

### 任务 4.1：应用工厂与依赖

新增：

- `api/app.py`
- `api/dependencies.py`
- `api/errors.py`
- `api/schemas/`

`app.py` 仅导入并启动应用工厂。

迁移认证、workspace/service 获取、审计和统一错误处理。

提交：`refactor: introduce backend application factory`

### 任务 4.2：按领域拆分路由

新增：

```text
api/routes/auth.py
api/routes/chat.py
api/routes/map.py
api/routes/downloads.py
api/routes/data_sources.py
api/routes/artifacts.py
api/routes/local_library.py
api/routes/admin.py
```

路由只调用 service 公共方法。

完成后将 `api_server.py` 缩为临时导出入口；所有测试改从 `api.app` 导入。

提交：`refactor: split fastapi routes by feature`

### 任务 4.3：删除临时 `api_server.py` facade

确认：

- 启动脚本、测试和 worker 无导入；
- 路由快照一致；
- OpenAPI 可生成。

然后删除 facade 并更新文档。

提交：`cleanup: remove legacy api server facade`

## 阶段 5：GIS 工具拆分

### 任务 5.1：建立工具注册中心

新增 `core/tools/registry.py` 和明确的工具元数据模型。

按模块迁移：

```text
core/tools/vector.py
core/tools/raster.py
core/tools/statistics.py
core/tools/modeling.py
core/tools/export.py
core/tools/workspace.py
```

每迁移一组：

1. 补工具契约测试；
2. 迁移函数和依赖；
3. 更新注册表；
4. 删除旧定义。

禁止长期从 `gis_tools.py` 重导出全部工具。

提交按工具组拆分，最终提交：`cleanup: remove monolithic gis tools module`

## 阶段 6：前端 feature 化

### 任务 6.1：共享 API 和类型

拆分 `src/lib/api.ts`：

```text
shared/api/client.ts
features/chat/api.ts
features/downloads/api.ts
features/data-sources/api.ts
features/map/api.ts
features/artifacts/api.ts
```

集中认证错误、取消请求和轮询生命周期。

提交：`refactor: split frontend api clients`

### 任务 6.2：聊天模块

迁移到 `features/chat/`：

- `ChatWorkspace` 容器；
- 会话列表；
- 消息列表；
- composer；
- login/clarification/resume action cards；
- artifact 卡片；
- job watcher hook。

删除 `ChatPanel.tsx` 中迁移后的重复状态和回调。

提交：`refactor: modularize chat feature`

### 任务 6.3：控制台与设置

拆分 `ProductConsole.tsx`：

- shell/navigation；
- overview；
- tasks；
- results；
- data assets；
- settings。

GSCloud 账号组件归入 `features/data-sources`，聊天和设置复用同一实现。

提交：`refactor: modularize product console`

### 任务 6.4：地图模块

拆分 `MapStage.tsx`：

- map lifecycle hook；
- Tianditu basemap；
- workspace layers；
- selection/drawing；
- viewport state；
- layer style adapters。

加入旧数据集删除后地图不残留图层的回归测试。

提交：`refactor: modularize map feature`

## 阶段 7：删除弃用和冲突代码

### 任务 7.1：移除确认弃用入口

候选包括：

- Streamlit 配置和已删除的 `web_app.py` 引用；
- 根目录旧 package lock；
- 旧云端导出兼容工具；
- legacy artifact 路径下载；
- 已迁移完成的 alias/facade；
- 重复的任务状态和响应格式器；
- `.playwright-cli`、测试结果、trace 和生成缓存。

每项必须在审计报告中记录“证据、替代实现、测试”。

提交：`cleanup: remove deprecated application paths`

### 任务 7.2：清理文档和配置冲突

- README 只保留当前启动方式；
- `.env.example` 与实际默认值一致；
- `.gitignore` 覆盖运行缓存、备份和测试输出；
- 删除过期迁移计划，保留必要历史设计文档。

提交：`docs: align configuration with refactored architecture`

## 阶段 8：运行数据重置

### 任务 8.1：扩展 dry-run 清单

完善现有清理脚本，使其分类展示：

- 保留账号/套餐/配额表；
- 保留认证必要数据；
- 保留用户及平台 GSCloud storage state；
- 删除聊天、任务、模型结果、artifact、上传、成果和缓存；
- 删除测试账号及其数据；
- 删除重复 `workspace/local_library`。

测试覆盖路径越界、符号链接、重复运行和失败回滚。

提交：`test: define runtime reset preservation contract`

### 任务 8.2：备份

生成：

- 数据库完整备份；
- 保留表的 JSON/SQL 导出；
- storage state 文件清单、权限和哈希；
- 清理前目录统计。

备份写入项目外指定目录，禁止注册为 artifact。

### 任务 8.3：执行清理

停止后端和 worker，执行 migrate 脚本，然后验证：

- 用户可登录；
- 套餐、配额正确；
- GSCloud status 保持 logged_in；
- 聊天、任务、artifact、模型结果为空；
- 用户运行目录为空；
- 根 `local_library` 保留；
- 无 storage state 出现在公开目录。

生成清理报告但不包含 Cookie/token 内容。

提交：只提交脚本和文档，不提交运行数据库或登录态。

## 阶段 9：最终验证

运行：

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m compileall core api domain services infrastructure tests
.venv\Scripts\python.exe -m unittest discover tests
cd ui_next
npm test
npm run build
npx playwright test
```

补充验证：

- 后端冷启动；
- 全新用户注册和登录；
- 设置页 GSCloud 状态；
- DEM 缺参数追问；
- 未登录引导和任务恢复；
- 县、市、省边界查询；
- 下载完成 artifact 卡片；
- 移动端输入框和登录弹窗；
- 路径穿越、敏感文件下载、跨用户访问。

最终输出：

- 新目录结构；
- 删除文件和兼容接口清单；
- 数据库迁移说明；
- 运行数据清理统计；
- 测试结果；
- 未迁移或待确认风险。

## 提交顺序摘要

1. 回归基线与审计工具；
2. 领域模型；
3. 基础设施；
4. 服务层；
5. API 路由；
6. GIS 工具；
7. 前端 features；
8. 删除弃用代码；
9. 清理脚本与运行数据重置；
10. 文档和最终验证。

任何阶段出现三次连续修复仍无法保持基线，应停止继续拆分，重新审查该模块边界。
