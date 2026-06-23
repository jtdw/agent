# 实时对话与任务流设计

## 目标

为 GIS Agent 增加两条受控实时通道：

- 模型回答按 token 或小文本块逐步显示；
- 已验证任务的计划、确认、排队、执行、登录等待、取消、失败和真实成果状态持续更新同一张任务卡。

本设计不改变 `LLM Planner -> TaskPlan -> Validator -> Executor/Worker` 的决策边界。流式通道只传递已经发生的事实，不创建工具调用，不重新解析用户原文，也不绕过权限和确认门控。

## 现状与约束

- `ChatPanel` 已按稳定 job/confirmation 标识合并任务卡，但主要依赖请求完成后的结果和定时轮询。
- `DurableJobStore` 已持久化任务状态；商业下载和 GIS Worker 各有状态源。
- `ChatMessageRenderer` 已有单卡任务生命周期和 canonical `PresentationResult` 渲染。
- FastAPI 后端和 React 前端均需保持现有普通 API 兼容。
- 任何事件、SSE、诊断和 UI 都不得泄露路径、Cookie、Token、用户原文、会话密钥、原始异常堆栈或 raw job dict。

## 方案

采用 SSE 优先、轮询兜底、事件持久化的方案。

### 1. 事件合同

新增 `TaskProgressEvent`，版本固定为 `task-progress-event/v1`：

```json
{
  "event_id": "evt_...",
  "version": 12,
  "kind": "task_status | task_progress | task_result | model_token | model_complete | warning | error",
  "conversation_id": "session_...",
  "task_id": "task_...",
  "job_id": "durable_...",
  "message_id": "msg_...",
  "status": "planning | awaiting_confirmation | queued | running | waiting_login | paused | succeeded | failed | cancelled",
  "progress": 0,
  "current_step": "",
  "message": "用户可读、脱敏的状态说明",
  "delta": "仅用于 model_token 的文本增量",
  "management_view": {},
  "presentation_result": {},
  "created_at": "ISO-8601"
}
```

- `delta` 只能承载模型输出片段，不能承载系统提示词、工具参数或模型内部推理。
- `management_view`、`presentation_result` 仅使用已有 canonical/脱敏模型。
- 每个事件使用单调 `version` 和稳定 `event_id`，前端按二者去重。

### 2. 持久化与发布

在 Durable Job 所在 SQLite 存储中增加有界事件表：

- 写入 `queued/running/waiting_login/succeeded/failed/cancelled` 等状态变化；
- Worker 每个实际步骤完成后写入 canonical ToolResult 摘要事件；
- 商业下载状态通过受控 bridge 转为同一事件合同；
- 仅保存有限窗口，终态任务按保留策略清理；
- 会话硬删除时级联删除事件。

为模型对话提供会话级短期事件缓冲：模型 token 完成后立即清理 token 内容，仅保留最终持久化聊天消息。这样页面连接期间可逐 token 显示，但不把大量 token 分片存入会话历史。

### 3. 后端接口

保留现有 `POST /api/chat/ask` 和确认接口作为兼容路径；新增：

- `POST /api/chat/stream`：SSE 响应，发送 `model_token`、`model_complete`、`task_status` 等事件。若 Provider 不支持流式，则发送一个 final token/complete 事件，不改变工具执行规则。
- `GET /api/chat/events?session_id=...&after_version=...`：会话级 SSE 订阅，发送任务状态与结果事件。
- `GET /api/chat/events/replay?session_id=...&after_version=...`：短连接补拉接口，供断线恢复和测试使用。

三类接口都从可信认证上下文校验用户与会话归属；不接受前端伪造 user_id 作为授权依据。

### 4. 前端状态合并

新增 `useRealtimeChatEvents`：

- 一个会话只有一个 EventSource；会话切换时关闭旧连接；
- 按 `event_id/version` 去重；
- `model_token` 合并到当前 assistant streaming message；
- `task_*` 只更新匹配 `task_id/job_id/confirmation_id` 的既有任务卡；
- 收到终态 `presentation_result` 后停止该任务的兜底轮询；
- SSE 不可用时显示轻量连接状态，并按现有任务 API 轮询；
- 页面刷新后先读取已持久化消息和任务状态，再用 `after_version` 补拉事件。

普通聊天消息继续使用紧凑气泡；执行型任务只保留一个随事件更新的任务卡，不增添 coordinator 技术气泡。

### 5. UI 状态

任务卡顶部增加实时连接标记：

- `实时同步`：SSE 已连接；
- `正在同步`：正在重连或补拉；
- `定时同步`：SSE 不可用，轮询兜底；

模型回复显示低干扰的“正在生成”指示和流式光标。任务卡只在后端提供真实进度时展示进度条；无真实进度时显示当前阶段，不伪造百分比或预计时间。

### 6. 失败与降级

- Provider 流式调用超时、限流、内容安全或 JSON 无效：发送受控中文失败事件，零工具执行。
- EventSource 断开：指数退避重连；连续失败后启用轮询。
- 事件重复/乱序：丢弃旧 version，保持终态不可被较旧事件覆盖。
- 服务重启：从持久化任务状态和最终聊天消息恢复；未完成 token 流不伪造成完整回答。

### 7. 测试

- 后端：事件 schema、顺序、权限、跨会话拒绝、重放、终态不回退、会话删除级联。
- Provider：流式文本、非流式 provider 降级、超时/限流/安全拦截时零工具执行。
- 前端：token 合并、单卡更新、去重、断线降级、会话切换清理 EventSource。
- 浏览器 E2E：普通问答流式显示、下载确认到运行到完成、等待登录、取消、刷新恢复、无重复卡片和无 React key warning。

## 分阶段实施

1. 定义 `TaskProgressEvent`、事件存储和后端 replay/SSE；
2. 接入 DurableJob 与下载管理状态 bridge；
3. 接入 Provider 流式文本适配；
4. 接入 `ChatPanel` 事件 hook、任务卡实时标识和轮询降级；
5. 后端、前端、浏览器 E2E 验收。

## 非目标

- 不使用原生 Function Calling 绕过 TaskPlan/Validator；
- 不引入 WebSocket；
- 不在流式事件中暴露 raw job、内部日志或敏感数据；
- 不新增 GIS 产品或工作流。
