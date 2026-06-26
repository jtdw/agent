# GIS 调度台聊天 UI 升级设计

## 目标

把当前 GIS Agent 的聊天体验升级为“平衡型 GIS 调度台”，并重点增强对话栏中的实时任务卡、公开思考过程、任务动作和结果展示。

本设计已经确认采用：

- 主结构：A1 平衡型 GIS 调度台；
- 重点能力：A3 深度实时任务卡；
- 思考过程：默认摘要 + 可展开公开执行日志；
- 实施策略：保持现有 FastAPI 接口和前端调用兼容，先升级 UI 和组件边界，再逐步疏通逻辑；
- 安全边界：不展示隐藏推理链、系统提示词、原始工具参数、敏感路径、Cookie、Token、storage_state、raw job dict、内部堆栈或未脱敏日志。

本项目不是普通聊天机器人，而是 GIS 智能工作台。UI 升级必须服务核心流程：

用户上传地理数据 -> 智能体识别数据类型 -> 选择 GIS 工具或工作流 -> 执行空间处理、制图或分析 -> 在地图和结果面板展示 -> 提供可下载产物和分析说明。

## 当前代码关系

### 前端入口

- `ui_next/src/App.tsx`
  - 顶层工作台容器。
  - 管理地图、控制台、浮动聊天、图层面板、分析面板、当前用户、当前会话、地图命令、结果面板和聊天上下文。
  - 把 `currentSessionId`、`chatContext`、`resultPanel` 和地图命令在 `MapStage`、`ProductConsole`、`ChatPanel`、`LayerPanel`、`AnalysisPanel` 之间传递。

- `ui_next/src/components/ProductConsole.tsx`
  - 主控制台。
  - 包含概览、任务创建、任务列表、日志、结果、数据资产、设置、能力管理等区域。
  - 在 `chat` tab 内以 `mode="page"` 嵌入 `ChatWorkspace`。

- `ui_next/src/components/ChatPanel.tsx`
  - 当前聊天工作区的核心文件。
  - 导出 `ChatWorkspace` 和浮动版 `ChatPanel`。
  - 目前集中承担会话列表、消息列表、上传、模型选择、语音输入、编辑重试、流式请求、SSE 事件、任务卡合并、下载任务动作、GSCloud 登录恢复和确认执行等职责。
  - 后续需要小步拆分，避免继续扩大该文件。

- `ui_next/src/components/ChatMessageRenderer.tsx`
  - 渲染普通消息、Markdown、代码块、artifact 下载卡、`PresentationResult`、`UserFacingResult` 和任务状态卡。
  - 当前已有 `TaskStatusCard`、`AgentProcessTimeline`、状态判断和任务动作按钮，是实时任务卡升级的核心落点。

- `ui_next/src/components/ChatComposer.tsx`
  - 输入栏组件。
  - 已支持上传附件、拖拽上传、`@` 引用工作区数据、语音输入、停止生成和发送。
  - 后续重点是按钮层级、可访问性、移动端布局稳定性和状态反馈。

- `ui_next/src/lib/api.ts`
  - 前端统一 API 客户端。
  - 聊天发送走 `/api/chat/stream`，任务事件走 `/api/chat/events`，事件补拉走 `/api/chat/events/replay`。
  - 上传走 `/api/files/upload`，地图图层走 `/api/map/layers`，下载任务走 `/api/downloads/*`，artifact 下载走 `/api/artifacts/{artifact_id}/download`。

### 后端入口

- `api_server.py`
  - FastAPI 装配层。
  - 负责服务创建、依赖注入、workspace/service 工厂、安全校验函数、事件桥接和路由注册。

- `api/routes/chat_actions.py`
  - 聊天行为接口。
  - 包含 `/api/chat/ask`、`/api/chat/stream`、`/api/chat/confirm`。
  - `/api/chat/stream` 会启动后台线程，发布 `model_token`、`model_complete`、`task_status` 等事件。

- `api/routes/chat_state.py`
  - 聊天状态接口。
  - 包含消息、会话、模型选择、交互模式、取消任务、SSE 事件流和 replay。
  - 是前端实时任务同步的主要数据源。

- `api/routes/workspace.py`
  - 上传、dashboard、mentions、workspace export、artifact 元数据、artifact 删除和 artifact 下载。
  - 文件上传、工作区数据引用、结果下载都依赖该模块。

- `api/routes/downloads_main.py`
  - 商业下载任务提交、预检、登录状态、任务列表、日志、取消、重试、结果下载。
  - 实时任务卡中的“等待登录、继续、取消、重试、下载结果”主要消费这里返回的 `management_view`。

- `core/realtime_events.py`
  - 实时事件模型和事件 hub。
  - 支撑 `RealtimeChatEvent`、任务事件持久化、SSE 推送和前端去重合并。

### 主数据链路

```text
用户输入/上传
  -> ChatComposer / Upload
  -> ui_next/src/lib/api.ts
  -> FastAPI route: chat_actions / workspace / downloads
  -> GISWorkspaceService / Agent / Tool Executor / Durable Job / Download Service
  -> PresentationResult / UserFacingResult / ManagementView / TaskProgressEvent
  -> api.ts 接收普通响应或 SSE
  -> ChatPanel 合并消息和任务状态
  -> ChatMessageRenderer 渲染普通消息、实时任务卡、成果卡、下载卡
  -> App / ProductConsole 同步 resultPanel、map layers、session id、chat context
```

## 信息架构

### 页面模式

`ProductConsole -> ChatWorkspace(mode="page")` 使用平衡型三栏布局：

```text
┌────────────────────────────────────────────────────────────┐
│ 当前会话标题 / 实时同步 / 模型选择 / 上传 / 运行工作流        │
├──────────────┬──────────────────────────┬──────────────────┤
│ 会话列表      │ 对话流                    │ 任务与成果摘要     │
│ 新建会话      │ 用户消息                  │ 当前任务阶段       │
│ 最近会话      │ 普通回答                  │ 结果文件           │
│ 删除会话      │ 实时任务卡                │ 地图图层           │
│              │ 思考过程/执行日志          │ 下载动作           │
├──────────────┴──────────────────────────┴──────────────────┤
│ 快捷提示 / 聊天-工具模式切换 / 输入栏 / 上传 / @数据 / 语音 / 发送 │
└────────────────────────────────────────────────────────────┘
```

右侧摘要栏只在页面模式启用。它展示当前任务阶段、结果文件、地图图层、下载动作和诊断摘要，不取代对话中的任务卡。

### 浮动模式

`App -> ChatPanel` 使用紧凑布局：

```text
┌──────────────────────────────┐
│ 会话标题 / 实时状态 / 关闭     │
├──────────────────────────────┤
│ 紧凑会话选择 / 模型选择 / 上传 │
├──────────────────────────────┤
│ 对话流 + 实时任务卡            │
├──────────────────────────────┤
│ 模式切换 + 输入栏              │
└──────────────────────────────┘
```

浮动模式不显示完整右侧摘要栏，避免遮挡地图。任务卡本身承担实时状态和动作入口。

## 实时任务卡

任务卡是本次升级的核心。执行型消息不再只是普通气泡，而是一个持续更新的任务控制单元。

### 区域

1. 任务头部
   - 任务标题；
   - 状态 badge；
   - 实时同步状态；
   - 更新时间或最近事件说明。

2. 公开思考过程
   - 默认展示一行摘要；
   - 展开后显示结构化公开执行日志；
   - 日志来自安全事件字段、`PresentationResult`、`execution_summary`、`management_view`、`task_card` 或前端可推断状态；
   - 不展示隐藏推理链。

3. 阶段时间线
   - 保留并优化当前 `AgentProcessTimeline`；
   - 默认阶段为：接收任务、制定计划、检查输入、调用工具、注册成果、生成回复；
   - 有真实工具步骤时展示工具步骤；
   - 没有真实工具步骤时只展示阶段，不伪造百分比和预计时间。

4. 进度区域
   - 只有后端返回真实 `progress` 时显示百分比；
   - 没有真实进度时显示当前阶段文字；
   - 不估算剩余时间。

5. 操作区
   - 主按钮：确认执行、登录后继续、下载结果、加入地图；
   - 次按钮：查看详情、复制、展开文件；
   - 危险按钮：取消、删除、重试失败任务；
   - 按钮固定高度和宽度约束，hover 不改变布局尺寸。

6. 成果区
   - 展示 artifact、地图图层、表格、图片、报告和下一步建议；
   - 继续复用 `ArtifactDownloadCard`；
   - 文件名、类型、大小、下载、删除、加入地图动作要清楚分层。

### 状态

状态标签保持稳定：

- `planning`：规划中，蓝色；
- `awaiting_confirmation`：待确认，黄色；
- `queued`：已排队，蓝灰色；
- `running`：运行中，蓝色；
- `waiting_login`：等待登录，黄色；
- `paused`：已暂停，灰色；
- `succeeded`：已完成，绿色；
- `failed`：失败，红色；
- `cancelled` / `canceled`：已取消，灰色；
- `blocked`：已阻断，黄色或红黄色。

### 公开思考过程文案

普通问答默认：

```text
正在分析问题...
正在生成回答...
```

工具任务默认摘要：

```text
正在检查输入数据，已完成 2/5 个阶段。
```

展开日志示例：

```text
1. 读取当前会话上下文和上传数据清单
   已找到 3 个数据集、2 个可下载结果。

2. 检查字段、CRS、范围和数据类型
   正在验证矢量边界与栅格范围是否重叠。

3. 生成处理计划
   等待参数校验完成，确认前不会执行下载或写入结果。
```

这些内容是公开过程摘要，不是模型隐藏推理链。

## 组件拆分计划

本设计不要求一次性大迁移。建议按风险由低到高拆分。

### 第一层：低风险 UI 组件

从 `ChatPanel.tsx` 抽出：

- `ChatHeader`
- `ChatSessionRail`
- `ChatModeSwitch`
- `ChatEmptyState`
- `ChatQuickPrompts`
- `RealtimeSyncIndicator`

目标是让 `ChatPanel.tsx` 的 JSX 更清晰，保持行为不变。

### 第二层：聊天行为 Hook

从 `ChatPanel.tsx` 抽出：

- `useChatSessions`
- `useChatStreaming`
- `useRealtimeChatEvents`
- `useChatUploads`
- `useDownloadTaskActions`
- `useVoiceInput`

目标是把 API 调用、事件连接、状态合并、上传和下载动作从布局组件中分离。

### 第三层：任务卡组件

从 `ChatMessageRenderer.tsx` 抽出：

- `TaskStatusCard`
- `TaskThinkingSummary`
- `TaskProcessTimeline`
- `TaskActionBar`
- `TaskResultGroups`
- `TaskDiagnosticsDetails`

目标是让消息渲染器只负责分发消息类型，任务卡内部自成一组可测试组件。

### 第四层：类型和状态工具

新增或整理：

- `taskStatus.ts`
- `taskCardModel.ts`
- `chatMessageKeys.ts`
- `realtimeEventMerge.ts`

目标是把状态归一化、任务卡数据模型、消息 key 和实时事件合并逻辑集中管理。

## 按钮体系

统一聊天工作区按钮层级。

### Primary

用途：

- 发送；
- 确认执行；
- 继续任务；
- 下载推荐结果；
- 加入地图。

视觉：

- 蓝到青渐变；
- 图标 + 短文案；
- 高度 36-42px；
- 禁用态清晰。

### Secondary

用途：

- 上传；
- 查看详情；
- 复制；
- 展开全部；
- 模型选择；
- 切换会话。

视觉：

- 白底；
- 浅边框；
- 轻 hover；
- 不抢主按钮视觉。

### Icon

用途：

- 关闭；
- 删除会话；
- 语音；
- 停止生成；
- 引用数据；
- 上传附件。

视觉：

- 固定正方形；
- 使用 lucide 图标；
- 必须有 `title` 或 `aria-label`。

### Danger

用途：

- 取消任务；
- 删除会话；
- 删除 artifact。

视觉：

- 浅红底或红字；
- 不与主按钮混用；
- 删除类动作需要更清楚的视觉区分。

### Segmented

用途：

- 聊天模式 / 工具模式。

文案必须明确：

- 聊天模式：只回答问题，不操作数据；
- 工具模式：经过计划、校验、确认后执行工具。

## 视觉系统

主风格：SaaS Dashboard + GIS Command Center。

需要收敛当前较重的玻璃拟态、过强阴影和装饰性渐变，让界面更专业、更像工作台。

### 颜色

```text
背景：#F8FAFC / #EEF7FF
主色：#0F62FE
GIS 青色：#0891B2 / #22D3EE
成功：#10B981
等待：#F59E0B
危险：#FB7185 / #E11D48
文本：#0F172A / #475569 / #64748B
边框：rgba(203,213,225,.82)
```

### 尺寸

- 卡片圆角：12-18px；
- 按钮圆角：10-12px；
- 输入栏高度：稳定，不因按钮状态跳动；
- 状态 badge：10-11px；
- 任务标题：14-16px；
- 正文：12-14px。

### 动效

- 保留轻量进入和状态变化；
- 减少装饰性浮动；
- 遵守 `prefers-reduced-motion`；
- hover 不应导致布局位移明显。

## 后端配合边界

短期 UI 升级不需要改后端接口，优先消费现有字段：

```text
RealtimeChatEvent.kind
RealtimeChatEvent.status
RealtimeChatEvent.progress
RealtimeChatEvent.current_step
RealtimeChatEvent.message
RealtimeChatEvent.management_view
RealtimeChatEvent.presentation_result
message.meta.task_card
message.meta.action_required
message.meta.execution_summary
message.meta.user_facing_result
```

后续如果要增强公开思考过程，可以新增安全字段：

```json
{
  "public_process": [
    {
      "id": "validate-input",
      "title": "检查输入数据",
      "summary": "正在验证字段、坐标系和范围。",
      "status": "running",
      "safe_detail": "不会包含路径、token、raw 参数或堆栈。"
    }
  ]
}
```

该字段应由工具执行器、计划校验器、下载服务和 workspace service 生成安全摘要，不从模型隐藏推理中提取。

## 分阶段实施

### 阶段 1：视觉统一和小组件抽取

范围：

- `ui_next/src/index.css`
- `ui_next/src/components/ChatPanel.tsx`
- `ui_next/src/components/ChatComposer.tsx`
- `ui_next/src/components/ChatMessageRenderer.tsx`

目标：

- 统一按钮、会话栏、头部、输入栏、空状态和实时同步 badge；
- 抽出低风险 UI 组件；
- 不改 API；
- 不改变聊天、上传、下载和会话行为。

### 阶段 2：实时任务卡升级

范围：

- `ChatMessageRenderer.tsx`
- 新的任务卡子组件。

目标：

- 实现默认摘要 + 可展开公开执行日志；
- 优化阶段时间线；
- 统一确认、登录、继续、取消、重试、下载、加入地图按钮；
- 保持现有 `management_view`、`presentation_result`、`action_required` 兼容。

### 阶段 3：逻辑疏通

范围：

- 从 `ChatPanel.tsx` 抽 hook；
- 整理实时事件合并逻辑；
- 整理下载任务动作。

目标：

- 会话、流式事件、上传、下载动作、语音输入各自独立；
- 降低 `ChatPanel.tsx` 复杂度；
- 不破坏 SSE 清理、会话切换和任务卡合并。

### 阶段 4：页面模式右侧摘要栏

范围：

- `ChatWorkspace(mode="page")`；
- 新增或增强任务与成果摘要栏。

目标：

- 当前任务、成果、图层、下载动作更容易找到；
- 浮动模式不显示完整摘要栏；
- 页面和浮动两种模式都验证响应式。

### 阶段 5：验证

前端重点检查：

```powershell
cd E:\agent\gis_agent_web_only_builtin_shp_v1\ui_next
npm run test:chat-panel-experience
npm run test:chat-message-content
npm run test:task-outcome-experience
npm test
npm run build
```

后端涉及接口或事件字段时再运行：

```powershell
cd E:\agent\gis_agent_web_only_builtin_shp_v1
.\.venv\Scripts\python.exe -m unittest discover tests
```

必要时补充 Playwright/E2E 检查：

- 页面模式聊天；
- 浮动模式聊天；
- 流式普通回答；
- 工具任务待确认；
- 下载等待登录；
- 取消和重试；
- artifact 下载；
- 地图图层结果联动；
- 移动端输入栏和按钮不溢出。

## 风险与约束

### `ChatPanel.tsx` 复杂度

当前 `ChatPanel.tsx` 承担过多职责。直接大改容易引发会话、SSE、上传、下载动作和 GSCloud 登录恢复回归。

缓解方式：

- 先抽纯 UI；
- 再抽 hook；
- 每一阶段跑聚焦测试；
- 保留原有 API 和响应结构。

### 思考过程边界

用户希望接近 Codex/ChatGPT 的思考体验，但不能展示隐藏推理链。

设计边界：

- 展示公开过程摘要；
- 展示工具和工作流执行阶段；
- 展示安全诊断和下一步；
- 不展示系统提示词、隐藏推理、内部参数和敏感信息。

### 页面模式和浮动模式共享组件

同一个 `ChatWorkspace` 需要服务控制台页面和地图浮窗。任何样式都必须同时验证两种模式。

缓解方式：

- 页面模式启用三栏；
- 浮动模式保持紧凑；
- 任务卡组件共享；
- 右侧摘要栏只在页面模式出现。

### 中文和编码

所有新增源码、文档和测试必须使用 UTF-8。Python 文本读写必须显式指定 encoding。不得通过 PowerShell 管道传递中文源码或中文常量给 Python。

## 验收标准

完成 UI 升级后，应满足：

- 用户能清楚区分聊天模式和工具模式；
- 用户能在对话中看到当前任务阶段、公开执行过程和下一步；
- 实时任务只更新同一张任务卡，不产生重复卡片；
- 确认、登录、取消、重试、下载、加入地图按钮层级清楚；
- 普通问答不会被大量过程信息干扰；
- 长任务有持续状态反馈；
- artifact、地图图层、结果面板和当前会话绑定关系更清楚；
- 页面模式和浮动模式都可用；
- 中文文案正常；
- `npm run build` 通过；
- 相关聊天和任务卡测试通过。

## 非目标

- 不重写整个前端；
- 不替换 React/Vite/Tailwind 技术栈；
- 不引入大型 UI 依赖；
- 不改变现有核心后端 API；
- 不绕过 TaskPlan、Validator、权限校验和确认门控；
- 不把隐藏推理链当作 UI 内容展示；
- 不新增 GIS 产品或下载源。
