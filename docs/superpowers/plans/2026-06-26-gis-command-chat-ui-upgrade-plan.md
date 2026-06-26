# GIS 调度台聊天 UI 升级实施计划

> 依据设计：`docs/superpowers/specs/2026-06-26-gis-command-chat-ui-upgrade-design.md`

## 实施原则

- 不改变现有 FastAPI 接口形状，优先消费现有 `RealtimeChatEvent`、`management_view`、`presentation_result`、`task_card` 和 `action_required`。
- 不一次性重写聊天模块；每阶段只做一个边界清晰的改动。
- 页面模式和浮动模式必须同时可用。
- 实时任务卡只能展示公开过程摘要和执行日志，不展示隐藏推理链、系统提示词、原始工具参数、敏感路径、Cookie、Token、storage_state、raw job dict 或内部堆栈。
- 所有新增中文源码、文档和测试使用 UTF-8。
- 每个阶段完成后运行聚焦前端测试；触及后端事件字段时补充后端测试。

## 阶段 0：基线与保护

### 任务 0.1：建立 UI 回归基线

记录当前前端聊天相关测试结果：

```powershell
cd E:\agent\gis_agent_web_only_builtin_shp_v1\ui_next
npm run test:chat-panel-experience
npm run test:chat-message-content
npm run test:task-outcome-experience
npm run test:chat-persistence
npm run build
```

如果已有失败，先记录失败测试、原因和是否与本次任务相关；不在 UI 升级提交里混入无关修复。

验收：

- 有明确基线结果；
- 明确当前失败是否阻塞 UI 升级；
- 没有开始修改业务 UI。

### 任务 0.2：确认页面模式和浮动模式入口

只读确认以下调用链：

- `App.tsx -> ChatPanel`：浮动聊天；
- `ProductConsole.tsx -> ChatWorkspace(mode="page")`：控制台聊天页；
- `ChatWorkspace -> ChatMessageRenderer -> TaskStatusCard`：消息和任务卡渲染；
- `ChatWorkspace -> ChatComposer`：输入栏；
- `api.ts -> /api/chat/stream`、`/api/chat/events`、`/api/chat/events/replay`：流式和实时事件。

验收：

- 记录两个模式的布局差异；
- 确认本次改动不会新增路由或改变后端 API；
- 明确需要保留的 `data-testid`，避免破坏现有测试。

提交：不单独提交，只作为后续实现前检查。

## 阶段 1：视觉系统和低风险组件抽取

### 任务 1.1：统一聊天工作区样式 token

修改：

- `ui_next/src/index.css`

内容：

- 新增或整理 chat 专用样式变量和类名；
- 收敛过重玻璃拟态、超大阴影和装饰渐变；
- 统一按钮、badge、卡片、输入栏、会话行、任务卡基础样式；
- 保持暗色模式可读；
- 保持 `prefers-reduced-motion`。

验收：

- 普通消息、任务卡、输入栏和会话列表视觉统一；
- hover/focus 不导致明显布局跳动；
- 移动端按钮和输入栏不溢出。

测试：

```powershell
cd ui_next
npm run test:chat-panel-experience
npm run build
```

提交：`style: unify chat workspace visual system`

### 任务 1.2：抽出低风险展示组件

新增建议：

```text
ui_next/src/components/chat/RealtimeSyncIndicator.tsx
ui_next/src/components/chat/ChatHeader.tsx
ui_next/src/components/chat/ChatSessionRail.tsx
ui_next/src/components/chat/ChatModeSwitch.tsx
ui_next/src/components/chat/ChatEmptyState.tsx
ui_next/src/components/chat/ChatQuickPrompts.tsx
```

迁移自：

- `ui_next/src/components/ChatPanel.tsx`

边界：

- 只抽 JSX 和 className；
- 不改变状态管理；
- 不改变 API 调用；
- 保留现有 `data-testid`。

验收：

- `ChatPanel.tsx` JSX 可读性提升；
- 页面模式和浮动模式渲染结果一致；
- 会话切换、新建、删除、上传按钮仍可用。

测试：

```powershell
cd ui_next
npm run test:chat-panel-experience
npm run test:chat-persistence
npm run build
```

提交：`refactor: extract chat workspace display components`

## 阶段 2：实时任务卡组件化和公开思考过程

### 任务 2.1：建立任务卡数据归一化层

新增建议：

```text
ui_next/src/components/chat/taskCardModel.ts
ui_next/src/components/chat/taskStatus.ts
```

内容：

- 归一化状态：`planning`、`awaiting_confirmation`、`queued`、`running`、`waiting_login`、`paused`、`succeeded`、`failed`、`cancelled`、`blocked`；
- 从 `ChatMessage.meta`、`PresentationResult`、`management_view`、`task_card`、`action_required` 推导安全展示模型；
- 生成公开过程摘要和默认阶段；
- 判断按钮可用性。

边界：

- 不改变后端字段；
- 不暴露 raw meta；
- 不根据缺失进度伪造百分比。

测试：

新增或扩展：

- `ui_next/tests/taskOutcomeExperience.test.mjs`
- `ui_next/tests/chatMessageContent.test.mjs`

覆盖：

- 状态标签映射；
- 待确认、等待登录、运行中、成功、失败、取消；
- 无真实 progress 时不显示伪造百分比；
- 公开思考过程不包含敏感字段。

提交：`test: cover task card presentation model`

### 任务 2.2：拆分任务卡子组件

新增建议：

```text
ui_next/src/components/chat/TaskStatusCard.tsx
ui_next/src/components/chat/TaskThinkingSummary.tsx
ui_next/src/components/chat/TaskProcessTimeline.tsx
ui_next/src/components/chat/TaskActionBar.tsx
ui_next/src/components/chat/TaskResultGroups.tsx
ui_next/src/components/chat/TaskDiagnosticsDetails.tsx
```

迁移自：

- `ui_next/src/components/ChatMessageRenderer.tsx`

边界：

- `ChatMessageRenderer` 只负责判断普通消息、系统消息、任务消息和结果消息；
- `TaskStatusCard` 负责任务头、公开思考过程、时间线、动作、成果和详情；
- 保持当前 `onLogin`、`onResume`、`onCancel`、`onRetry`、`onClarification`、`onConfirmAction` 行为兼容。

验收：

- 任务卡视觉符合 A1 + A3；
- 普通聊天仍是轻量气泡；
- 长任务默认展示公开过程；
- 普通问答的“正在生成”不被任务日志污染；
- 失败和等待登录状态可读。

测试：

```powershell
cd ui_next
npm run test:chat-message-content
npm run test:task-outcome-experience
npm run test:chat-confirmation-action
npm run build
```

提交：`refactor: modularize realtime task card`

### 任务 2.3：实现混合公开思考过程

行为：

- 普通问答：
  - 空内容时显示“正在生成回答”；
  - 有内容时显示流式光标；
  - 不显示执行日志。

- 工具任务：
  - 显示一行公开摘要；
  - 可展开显示执行日志；
  - 日志来源优先级：
    1. 后端未来可能提供的 `public_process`；
    2. `PresentationResult.executed_steps`；
    3. `management_view.current_step`、`action_state`、`user_message`；
    4. `execution_summary`；
    5. 前端安全默认阶段。

文案示例：

```text
正在检查输入数据，已完成 2/5 个阶段。
读取当前会话上下文和上传数据清单。
检查字段、CRS、范围和数据类型。
生成处理计划，确认前不会执行下载或写入结果。
```

安全过滤：

- 不渲染包含 `.env`、`cookie`、`storage_state`、`token`、绝对路径、堆栈片段的诊断文本；
- 技术详情只在开发模式显示，沿用当前 `technicalDetailsEnabled()`。

测试：

- 新增公开过程生成单元测试；
- 增加敏感词过滤测试；
- 覆盖折叠/展开状态。

提交：`feat: show public task thinking summaries`

## 阶段 3：输入栏和按钮体系升级

### 任务 3.1：升级 ChatComposer

修改：

- `ui_next/src/components/ChatComposer.tsx`
- `ui_next/src/index.css`

内容：

- 固定按钮尺寸和输入栏最小/最大高度；
- 上传、引用数据、语音、停止、发送按钮层级更清楚；
- 拖拽上传状态更明显；
- mention 菜单和移动端布局不溢出；
- 保留现有 `@` 数据引用能力。

验收：

- 空输入时发送按钮禁用；
- sending 时发送按钮切换为停止；
- 上传中状态不会挤压输入框；
- 移动端隐藏/压缩非关键按钮时仍可发送。

测试：

```powershell
cd ui_next
npm run test:chat-panel-experience
npm run test:frontend-context-payload
npm run build
```

提交：`style: refine chat composer controls`

### 任务 3.2：统一任务动作按钮

修改：

- `TaskActionBar.tsx`
- `index.css`

按钮体系：

- Primary：确认执行、继续、下载结果、加入地图；
- Secondary：查看详情、复制、展开文件；
- Icon：关闭、语音、引用、上传、停止；
- Danger：取消、删除、重试失败任务。

验收：

- 待确认任务只突出“确认执行”；
- 等待登录任务突出“去登录/登录后继续”；
- 运行中任务突出“取消”但不误导；
- 成功任务突出“下载结果/加入地图”；
- 失败任务突出“重试”和错误摘要。

测试：

```powershell
cd ui_next
npm run test:chat-confirmation-action
npm run test:task-outcome-experience
npm run build
```

提交：`style: standardize task action hierarchy`

## 阶段 4：实时事件合并逻辑疏通

### 任务 4.1：抽出实时事件 hook

新增建议：

```text
ui_next/src/components/chat/useRealtimeChatEvents.ts
ui_next/src/components/chat/realtimeEventMerge.ts
```

迁移自：

- `ChatPanel.tsx` 中的 `applyRealtimeEvent`、EventSource 管理、事件去重和 version 处理。

边界：

- 一个会话只有一个 EventSource；
- 会话切换时关闭旧连接；
- 按 `event_id` 和 `version` 去重；
- 终态任务不被旧事件回退；
- SSE 不可用时保持现有轮询兜底。

验收：

- 切换会话不会继续更新旧会话任务卡；
- 重复事件不会生成重复卡片；
- `model_token` 合并到当前 streaming message；
- `task_*` 更新匹配任务卡。

测试：

新增或扩展：

- `ui_next/tests/chatTaskCardAndResults.test.mjs`
- `ui_next/tests/chatPersistence.test.mjs`

提交：`refactor: isolate realtime chat event merging`

### 任务 4.2：抽出会话、上传、下载动作 hook

新增建议：

```text
ui_next/src/components/chat/useChatSessions.ts
ui_next/src/components/chat/useChatUploads.ts
ui_next/src/components/chat/useDownloadTaskActions.ts
ui_next/src/components/chat/useVoiceInput.ts
```

目标：

- `ChatPanel.tsx` 保留布局和组合；
- 会话加载、新建、切换、删除独立；
- 上传逻辑独立；
- 下载恢复、取消、重试独立；
- 语音输入独立。

验收：

- `ChatPanel.tsx` 复杂度明显下降；
- 所有原有操作仍可用；
- 错误信息仍显示在聊天区域；
- `onSessionChange`、`onResultPanel`、`chatContext` 行为不变。

测试：

```powershell
cd ui_next
npm run test:chat-panel-experience
npm run test:chat-persistence
npm run test:session-scoped-actions
npm run build
```

提交：`refactor: split chat workspace behavior hooks`

## 阶段 5：页面模式右侧摘要栏

### 任务 5.1：新增页面模式任务与成果摘要栏

新增建议：

```text
ui_next/src/components/chat/ChatTaskSummaryRail.tsx
```

仅在 `mode="page"` 显示。

内容：

- 当前活动任务状态；
- 最近成果；
- 可加入地图的图层；
- 下载动作；
- 诊断摘要。

数据来源：

- 当前 messages 中最后一个任务卡；
- `presentation_result.artifact_refs`；
- `presentation_result.map_layer_refs`；
- `management_view.artifact_refs`；
- `ResultPanel` 回调；
- 已有 `chatContext` / dashboard mentions。

边界：

- 不新增后端请求作为首版要求；
- 不在浮动模式显示完整 rail；
- 不与 `LayerPanel` 功能重复。

验收：

- 页面模式可一眼看到当前任务、成果和图层；
- 浮动模式不遮挡地图；
- 没有任务时显示轻量空状态；
- 成功任务可引导下载或加入地图。

测试：

```powershell
cd ui_next
npm run test:chat-task-card-and-results
npm run test:analysis-panel
npm run build
```

提交：`feat: add page-mode task summary rail`

## 阶段 6：后端安全增强，按需实施

该阶段不是首版 UI 升级的阻塞项。只有当前端默认推断过程不足时再做。

### 任务 6.1：新增安全公开过程字段

候选字段：

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

可能修改：

- `core/realtime_events.py`
- `core/presentation_result.py`
- `core/management_views.py`
- `api/routes/chat_actions.py`
- 相关测试。

边界：

- 不改变现有字段；
- 新增字段可选；
- 所有内容必须脱敏；
- 不从隐藏推理链提取。

测试：

```powershell
cd E:\agent\gis_agent_web_only_builtin_shp_v1
.\.venv\Scripts\python.exe -m unittest discover tests
cd ui_next
npm run test:task-outcome-experience
npm run build
```

提交：`feat: expose safe public task process events`

## 阶段 7：浏览器验收和最终清理

### 任务 7.1：本地浏览器验收

启动服务：

```powershell
cd E:\agent\gis_agent_web_only_builtin_shp_v1
.\start_backend_api.ps1
.\start_web_ui.ps1
```

检查流程：

- 未登录/已登录状态；
- 页面模式聊天；
- 浮动模式聊天；
- 普通问答流式展示；
- 工具模式待确认；
- 确认执行；
- 等待登录和登录后继续；
- 取消任务；
- 重试任务；
- 上传中文文件名；
- `@` 引用工作区数据；
- 成功结果下载；
- 地图图层联动；
- 窄屏输入栏。

验收：

- 无明显重叠、溢出、按钮跳动；
- 无重复任务卡；
- 无 React key warning；
- 普通聊天不被任务过程干扰；
- 长任务有持续状态反馈。

### 任务 7.2：完整前端回归

运行：

```powershell
cd E:\agent\gis_agent_web_only_builtin_shp_v1\ui_next
npm test
npm run build
```

如涉及后端事件字段，额外运行：

```powershell
cd E:\agent\gis_agent_web_only_builtin_shp_v1
.\.venv\Scripts\python.exe -m unittest discover tests
```

最终提交：`test: verify GIS command chat UI upgrade`

## 建议提交顺序

1. `style: unify chat workspace visual system`
2. `refactor: extract chat workspace display components`
3. `test: cover task card presentation model`
4. `refactor: modularize realtime task card`
5. `feat: show public task thinking summaries`
6. `style: refine chat composer controls`
7. `style: standardize task action hierarchy`
8. `refactor: isolate realtime chat event merging`
9. `refactor: split chat workspace behavior hooks`
10. `feat: add page-mode task summary rail`
11. 可选：`feat: expose safe public task process events`
12. `test: verify GIS command chat UI upgrade`

## 首批建议执行范围

为了降低风险，第一轮实现建议只做阶段 1 和阶段 2：

- 统一聊天视觉系统；
- 抽低风险展示组件；
- 拆分任务卡；
- 实现混合公开思考过程；
- 不改后端接口；
- 不新增右侧摘要栏；
- 跑聊天聚焦测试和 build。

第一轮完成后再评估是否进入阶段 3-5。

## 停止条件

出现以下任一情况，应暂停继续扩大范围：

- `npm run build` 无法通过且原因不明确；
- 会话切换后任务卡串到错误会话；
- 实时事件重复生成卡片；
- 上传或 artifact 下载行为回归；
- 浮动模式遮挡地图且短期无法修复；
- 公开思考过程需要依赖隐藏推理链才能成立。

暂停后应先修复当前阶段回归，再进入下一阶段。
