# LangChain GIS 智能体改造计划书

日期：2026-06-27  
适用仓库：`E:\agent\gis_agent_web_only_builtin_shp_v1`  
计划类型：架构改造实施计划，不生成代码  
采用方案：改造方案 1，即在现有 GIS 工作台上增量引入 LangChain 标准运行边界，保留确定性 GIS 工作流，逐步切流

## 1. 背景与目标

当前项目已经不是普通聊天机器人，而是 GIS 智能工作台。核心目标仍然是：

用户上传地理数据 -> 智能体识别数据类型 -> 选择 GIS 工具或工作流 -> 执行空间处理、制图或分析 -> 地图和结果面板展示 -> 产出可下载 artifact 和分析说明。

本次改造的目标不是把所有逻辑交给 LLM 自由发挥，而是把现有系统整理成更符合 LangChain 官方架构的智能体运行层：

- 使用 LangChain agent harness 统一模型、工具、提示词、上下文、流式输出和中间件。
- 保留现有确定性 GIS workflow executor，作为高风险空间处理任务的执行核心。
- 将工具注册、上下文构造、任务规划、工作流执行、RAG、记忆和观测性拆成明确边界。
- 将当前不完整的“标准 LCEL”和“向量化 RAG”列为显式建设项，不把它们误认为已经完成。
- 尽量保持后端 API、前端调用方式、artifact 展示、地图图层绑定和会话行为向后兼容。

## 2. 依据与设计原则

LangChain 官方 overview 展示的高层入口是 `create_agent(model, tools, system_prompt=...)`，其设计重点是把模型、工具和系统提示词组合为一个 agent 运行单元。官方文档同时强调，LangChain 的 agent 能力建立在 LangGraph 之上，用于持久执行、人机协作、记忆、流式输出和复杂任务编排；调试和可观测性可接入 LangSmith。

本项目应采用混合架构：

- LangChain 负责 agent harness、工具 schema、上下文注入、结构化输出、流式事件和可观测性。
- 项目自研 GIS workflow 负责可验证、可回放、可审计的地理处理步骤。
- LLM 负责理解意图、补全参数、解释结果、选择候选工作流；不直接绕过安全检查访问文件系统或任意执行工具。

参考来源：

- [LangChain overview](https://docs.langchain.com/oss/python/langchain/overview)
- [LangChain tools](https://docs.langchain.com/oss/python/langchain/tools)
- [LangChain retrieval](https://docs.langchain.com/oss/python/langchain/retrieval)
- [ArcGIS Pro help](https://pro.arcgis.com/ja/pro-app/latest/help/main/welcome-to-the-arcgis-pro-app-help.htm)

## 3. 当前能力盘点

已有能力：

- `core/agent.py`：已有 LangChain agent 入口形态，包含模型、工具、系统提示词和工具注册。
- `core/tools/registry.py`：已有 common、document、table、vector、raster、map、ml、download 等工具域注册。
- `core/llm_task_planner.py`：已有 LLM planner、provider 配置、计划校验和 fallback。
- `core/workflow_executor.py`：已有确定性多步骤 workflow executor，支持步骤依赖、工具调用和 ToolResult 聚合。
- `core/workflow_coordinator.py`：已有 coordinator decision 模型。
- `core/context_builder.py`：已有 workspace、active dataset、knowledge snippets、tool cards、download candidates、area candidates 等上下文组合逻辑。
- `core/conversation_state.py`：已有会话状态和记忆字段。
- `core/capability_config.py`：已有 knowledge、tool cards、products、assets 管理和关键词检索。

需要补齐的能力：

- 标准 LCEL：当前不能视为完整实现，缺少稳定的 runnable chain 边界、输入输出契约、组合式测试和观测点。
- 向量化 RAG：当前更接近关键词或规则增强检索，缺少 embedding、vector store、retriever、文档切分、增量索引和检索评测。
- LangChain runtime boundary：当前 planner、context、tools、workflow 分散在各模块，缺少统一运行时抽象。
- 工具 runtime context：工具调用需要更清晰地接收 user_id、session_id、workspace、artifact registry、map layer registry、权限上下文。
- 可观测性：需要把规划、工具选择、参数校验、workflow 执行、artifact 注册、前端事件串成可追踪链路。

## 4. 目标架构

建议新增一个运行时边界，先并行于旧入口存在，逐步接管流量：

```text
core/agent_runtime/
  runtime.py              # GISAgentRuntime 统一入口
  config.py               # provider/model/runtime 配置
  context.py              # LangChain runtime context 适配
  prompts.py              # system prompt 和任务提示模板
  middleware.py           # 安全、会话、工具前后置、观测
  tools.py                # 现有工具 registry 到 LangChain tools 的适配
  planner.py              # planner/coordinator 的 LangChain 适配层
  workflows.py            # workflow executor bridge
  rag/
    loaders.py
    splitters.py
    embeddings.py
    vector_store.py
    retriever.py
    indexer.py
  chains/
    answer.py
    retrieval.py
    planner_precheck.py
  tracing.py
```

核心调用流：

```text
API chat endpoint
  -> GISAgentRuntime.invoke/stream
  -> ContextBuilder 组装用户、会话、文件、地图、工具、知识上下文
  -> LangChain agent harness 判断：回答 / 工具 / workflow / RAG
  -> Tool runtime 做权限、路径、参数、session 校验
  -> WorkflowExecutor 执行确定性 GIS 步骤
  -> artifact/map layer/session state 注册
  -> 前端保持原响应结构展示结果
```

## 5. 分阶段实施计划

### Phase 0：基线锁定与风险审计

目标：在改造前固定当前行为，避免架构调整后无法判断是否回归。

任务：

- 梳理 chat、upload、artifact、map layer、workflow、download 的关键 API 和前端依赖。
- 建立最小 smoke tests：中文问题、上传矢量数据、查询图层、执行一个确定性 workflow、下载 artifact。
- 记录当前 planner 和 workflow 的输入输出样例。
- 对核心函数做 GitNexus impact analysis 后再进入代码修改阶段。

验收：

- 有一份基线测试清单。
- 明确哪些行为必须保持兼容。
- 明确高风险模块和回滚点。

### Phase 1：新增 LangChain Runtime 外壳

目标：新增 `core/agent_runtime/`，先包住旧能力，不替换旧入口。

任务：

- 新增 `GISAgentRuntime`，统一暴露 `invoke()` 和 `stream()`。
- 复用现有 `core/agent.py`、`build_tools(manager)`、`ContextBuilder` 和 provider 配置。
- 将 system prompt、model、tools、runtime context 组织成 LangChain agent harness。
- 加 feature flag，例如 `AGENT_RUNTIME_V2=false`，默认仍走旧路径。

验收：

- 旧 API 不变。
- 新 runtime 可在测试或 shadow 模式下运行。
- 不改变前端事件结构和 test id。

### Phase 2：Context 与 Memory 分层

目标：把当前上下文构造整理成可注入、可测试、可裁剪的上下文管道。

任务：

- 将上下文拆成 session context、workspace context、active dataset context、map context、tool cards、retrieval snippets。
- 明确短期记忆与长期知识的边界。
- 让工具只通过 runtime context 获取 user_id、session_id、workspace，不直接相信外部参数。
- 对中文文件名、中文字段、中文 JSON 保持 UTF-8 显式处理。

验收：

- 同一个 session 的文件、artifact、map layer 绑定不串用。
- 上下文过长时可稳定裁剪，不丢失 active dataset 和安全边界。

### Phase 3：Tool Runtime 标准化

目标：把现有 GIS 工具注册适配为 LangChain tools，同时保留原工具实现。

任务：

- 为工具建立统一 schema：name、description、args_schema、returns、artifact policy、map layer policy、risk level。
- 将 common/document/table/vector/raster/map/ml/download 工具统一包装为 LangChain tool。
- 工具执行前统一做路径、权限、文件存在、CRS、参数类型和 workspace 范围校验。
- 工具失败时返回结构化错误：原因、用户可读建议、是否可重试、关联文件或字段。

验收：

- 工具调用日志能看到参数、上下文、结果和 artifact id。
- 不允许下载 `.env`、token、cookie、storage_state、日志、数据库等敏感文件。
- 现有工具调用方式兼容。

### Phase 4：Planner/Coordinator 改造为 LangChain Harness

目标：让 LLM 规划与 coordinator 决策进入统一 agent runtime，但不牺牲确定性 workflow。

任务：

- 将 `llm_task_planner.py` 的计划生成封装成 planner component。
- 将 `workflow_coordinator.py` 的 decision model 作为 routing/middleware 能力。
- 对高频 GIS 请求优先匹配确定性 workflow；低风险解释类请求走 answer chain。
- 对 planner 输出做 schema 校验和 fallback，禁止未验证路径、未注册工具、跨用户资源。

验收：

- Planner 输出可审计、可回放。
- 高频 GIS 任务不退化成 LLM 随机工具调用。
- 失败时前端仍能看到清晰错误和建议。

### Phase 5：Workflow Graph 整理

目标：把现有 workflow executor 定位为 GIS 任务的可靠执行内核。

任务：

- 将 workflow steps 映射为可追踪节点：参数准备、校验、执行、artifact 注册、map layer 注册、结果说明。
- 为矢量裁剪、矢量信息、表格转点、栅格信息、栅格统计、重投影、制图等高频任务建立稳定模板。
- 保留现有 executor，不在第一批迁移到完整 LangGraph；先把边界、日志和状态打清楚。
- 后续如需长任务恢复、人机确认、断点续跑，再评估引入 LangGraph workflow。

验收：

- 每个 workflow 都能输出结构化步骤状态。
- artifact 和 map layer 与 user_id/session_id 绑定。
- 失败步骤有可解释原因和建议。

### Phase 6：向量化 RAG 建设

目标：把当前知识检索从关键词增强升级为真正的 embedding/vector-store RAG。

任务：

- 定义知识源：项目知识卡片、GIS 工具说明、工作流说明、可公开 GIS 文档摘要、用户上传文档的可索引片段。
- 建立 loader、splitter、embedding、vector store、retriever、rerank 或过滤策略。
- 向量库需要支持 user/session 过滤，避免不同用户知识串用。
- ArcGIS Pro 文档只作为 GIS 工具概念和操作 taxonomy 的参考来源，不直接复制长文档，不把 ArcGIS 私有功能误当成本项目已实现能力。
- 加检索评测：命中率、中文查询、GIS 术语、工具选择准确性、幻觉率。

验收：

- 可以明确回答“检索到了哪些片段、来自哪里、是否用户私有”。
- RAG 输出不会声称项目没有实现的 GIS 能力已经可用。
- 中文 GIS 术语检索稳定。

### Phase 7：标准 LCEL 局部引入

目标：在低风险、边界清楚的链路引入 LCEL，而不是一次性替换所有逻辑。

候选链路：

- answer-only chain：仅解释现有结果，不调用工具。
- retrieval chain：基于向量检索片段生成回答。
- planner precheck chain：把用户意图整理成候选任务和缺失参数。
- result summarization chain：把 ToolResult/workflow result 转成中文说明。

验收：

- 每条 chain 有明确输入、输出、错误处理和测试样例。
- LCEL chain 可单测，不依赖真实外部 LLM 时可 mock。
- 不把高风险文件操作和下载权限交给裸 chain。

### Phase 8：可观测性、评测与调试

目标：让每次智能体执行可追踪、可复盘、可评估。

任务：

- 定义 trace event：request、context build、retrieval、planner、tool call、workflow step、artifact registration、response。
- 本地先落结构化 JSONL 或数据库事件；可选对齐 LangSmith 字段。
- 建立评测集：中文 GIS 问法、文件上传后分析、错误路径、权限隔离、下载任务、地图预览。
- 加 shadow mode：新 runtime 先旁路产出决策，不影响用户结果。

验收：

- 一次失败能定位是 context、retrieval、planner、tool、workflow 还是前端展示问题。
- 能对比旧 runtime 和新 runtime 的工具选择差异。

### Phase 9：前后端兼容与逐步切流

目标：保证架构改造不破坏用户体验。

任务：

- 保持 chat API 响应结构、任务卡片、结果卡片、artifact 下载、地图图层接口兼容。
- 新增字段只做兼容扩展。
- 前端仅在必要时展示更细的 workflow 状态和错误建议。
- 逐步从 shadow -> 小流量 -> 默认启用 -> 删除旧路径。

验收：

- `npm run build`、关键前端测试、后端 py_compile/pytest 尽量通过。
- 旧会话和旧 artifact 不受影响。
- 用户能看到更稳定的任务执行状态和结果说明。

## 6. 文件级影响范围

第一批建议新增或改动：

- 新增：`core/agent_runtime/*`
- 修改：`core/agent.py`，只接入 runtime flag，不删除旧实现。
- 修改：`core/context_builder.py`，逐步拆分可测试 context sections。
- 修改：`core/tools/registry.py`，增加 LangChain tool adapter，不改原工具签名。
- 修改：`core/llm_task_planner.py`，增加 planner adapter 和 schema 校验边界。
- 修改：`core/workflow_executor.py`，增加 trace/step status，不改核心执行语义。
- 新增：`tests/test_agent_runtime_*.py`、`tests/test_rag_*.py`、`tests/test_workflow_runtime_*.py`。

前端第一批尽量不改；只有后端新增结构化状态后，再小步增强 UI。

## 7. 风险与控制

主要风险：

- LLM 过度自由调用工具，导致路径、权限、会话隔离风险。
- RAG 检索到外部 GIS 文档后，误导用户以为本项目已经实现同名 ArcGIS 功能。
- Runtime 切换导致前端任务卡片、结果面板或地图图层状态不兼容。
- LCEL 过早进入高风险工具执行链路，增加不可控性。

控制策略：

- 所有工具调用必须经过 runtime context 和工具前置校验。
- 高频 GIS 操作优先走确定性 workflow。
- 新 runtime 先 shadow，不直接替换。
- RAG 输出必须带来源和能力边界说明。
- 每次改动前对目标 symbol 做 impact analysis；提交前做 detect_changes。

## 8. 测试策略

后端：

- `.venv` 下运行相关 `python -m py_compile`。
- 对 runtime、tool adapter、workflow bridge、RAG retriever 做单元测试。
- 对中文路径、中文字段、中文 JSON、中文日志做编码测试。
- 对 user_id/session_id 隔离、artifact 下载权限、workspace 路径限制做安全测试。

前端：

- `ui_next` 下运行 `npm run build`。
- 保留任务卡片和结果卡片 test id。
- 验证 chat、upload、artifact download、map layer preview、workflow status 展示。

集成：

- 上传矢量数据 -> 数据识别 -> 信息查看 -> 地图预览。
- 表格经纬度转点 -> artifact 注册 -> 地图展示。
- 失败文件路径 -> 结构化错误 -> 中文建议。
- RAG 问工具能力 -> 返回来源与能力边界。

## 9. 推荐执行顺序

建议按以下顺序开工：

1. Phase 0：基线测试与行为记录。
2. Phase 1：新增 runtime 外壳和 feature flag。
3. Phase 3：工具 runtime 标准化，因为它是安全边界。
4. Phase 2：上下文与 memory 分层。
5. Phase 4 和 Phase 5：planner/coordinator 与 workflow bridge。
6. Phase 6：向量化 RAG。
7. Phase 7：LCEL 局部引入。
8. Phase 8 和 Phase 9：观测、评测、切流、前端兼容。

## 10. 下一步确认点

如果确认按本计划实施，建议下一轮先做 Phase 0 和 Phase 1：

- 不删除旧 agent。
- 新增 `core/agent_runtime/` 最小可运行外壳。
- 加 runtime feature flag。
- 补一组最小后端测试。
- 保持前端完全不变。

这会给后续工具标准化、RAG、LCEL 和 workflow graph 改造留出稳定落点。
