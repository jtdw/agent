# GIS 智能体结构清理与运行数据重置设计

## 1. 目标

在保持普通用户功能一致的前提下，清理已经弃用、冲突、重复或无引用的代码，拆分超大模块，统一内部接口，并重置运行数据。

允许调整内部 Python/TypeScript API、模块导入和目录结构。对外 HTTP API 尽量保持兼容；如必须调整，由前后端在同一阶段同步迁移，不保留长期重复实现。

运行数据清理后仅保留：

- 平台用户账号、密码哈希、套餐、配额及必要认证数据；
- 每个用户自己的 GSCloud `storage_state/Cookie`；
- 平台 GSCloud 账号登录态；
- 项目根目录 `local_library` 中的有效内置数据。

## 2. 非目标

- 不重写 GIS 算法本身；
- 不改变用户可见的聊天、地图、下载、账号和 artifact 基本流程；
- 不在本轮更换数据库引擎、前端框架或 GIS 基础库；
- 不保留仅为旧内部调用服务的永久兼容层。

## 3. 目标架构

### 3.1 后端

后端划分为四层：

```text
app.py
api/
  dependencies.py
  schemas/
  routes/
services/
  chat/
  downloads/
  data_sources/
  artifacts/
  local_library/
domain/
  models/
  status/
  policies/
infrastructure/
  database/
  browser/
  storage/
  providers/
```

- `api/routes` 只负责 HTTP、认证、请求校验和响应组装。
- `services` 负责编排用例，不直接依赖 FastAPI 请求对象。
- `domain` 保存任务状态、业务规则和纯数据模型，不执行文件或网络操作。
- `infrastructure` 封装 SQLite、Playwright、文件系统和外部数据源。
- `app.py` 保持为唯一后端启动入口。

优先拆分：

- `api_server.py`：按认证、聊天、地图、下载、数据源账号、artifact、本地文件库拆分路由；
- `core/service.py`：拆分聊天编排、工作区操作和本地文件导入；
- `core/gis_tools.py`：按矢量、栅格、统计、模型和导出工具拆分；
- GSCloud 登录、下载、状态检查统一通过数据源服务访问。

### 3.2 前端

```text
src/
  features/
    chat/
    map/
    downloads/
    data-sources/
    settings/
    product-console/
  shared/
    api/
    components/
    hooks/
    types/
```

- `ChatPanel.tsx` 拆为会话容器、消息列表、输入器、动作卡和登录引导。
- `ProductConsole.tsx` 拆为导航壳、任务、结果、设置和总览页面。
- `MapStage.tsx` 拆为地图实例、底图、业务图层、交互和状态同步模块。
- 数据请求集中到 feature API 层，避免组件内重复轮询、状态映射和错误处理。

## 4. 清理规则

### 4.1 可直接删除

- 已无启动入口或 CI 引用的旧 UI、旧配置和旧脚本；
- 已被新模块完全替代且调用方迁移完成的实现；
- `__pycache__`、测试缓存、Playwright trace、截图、HTML 报告和临时运行目录；
- 重复的 `workspace/local_library`；
- 无数据库引用且不在有效目录中的孤立 artifact 和结果文件。

### 4.2 迁移后删除

- legacy artifact 路径下载接口；
- 旧云端导出兼容工具；
- 旧模型结果文件扫描与新 registry 的重复实现；
- 旧状态名称、旧响应拼接器和旧前端状态映射；
- 仅用于内部旧调用的别名、转发函数和重复 schema。

删除前必须通过引用搜索、调用测试和行为回归确认无活动依赖。

### 4.3 暂不自动删除

- 用途无法从代码、测试或运行数据库确认的模块；
- 可能被外部脚本调用但仓库内无证据的管理脚本；
- 许可证、数据来源和迁移说明文件。

这些内容进入待确认清单。

## 5. 运行数据重置

### 5.1 保留

- 用户账号、密码哈希、套餐、配额；
- 必要认证数据；
- 用户和平台 GSCloud 登录态文件；
- 登录态数据库映射；
- 根目录 `local_library`。

### 5.2 删除

- 聊天消息、会话上下文和模型结果；
- 下载任务、场景任务、分幅任务和运行审计记录；
- 用户 `uploads`、`derived`、`exports`、`plots`、临时目录；
- artifact 数据库记录和文件；
- 测试账号产生的数据、测试下载和浏览器运行缓存；
- 旧本地库副本和旧边界解压缓存。

### 5.3 执行方式

1. 生成数据清单和数据库表级统计；
2. 备份账号相关表、套餐配额表和登录态文件；
3. 执行受路径白名单约束的清理脚本；
4. 恢复并验证账号和 GSCloud 登录态；
5. 检查其他运行表、用户目录和 artifact 目录为空；
6. 生成可审计的清理结果报告。

清理脚本必须支持 dry-run，并拒绝删除项目根目录之外的路径。

## 6. 迁移阶段

### 阶段 1：回归基线

- 固化后端 API、聊天、地图、下载、账号、artifact 和安全测试；
- 记录当前路由、数据库表、运行目录和主要模块依赖；
- 建立删除候选清单。

### 阶段 2：领域与基础设施提取

- 提取任务状态、数据模型和策略；
- 封装数据库、文件存储、Playwright 和 GSCloud provider；
- 保持对外行为不变。

### 阶段 3：后端拆分

- 拆分 `api_server.py`；
- 拆分聊天、下载、本地库和 artifact 服务；
- 拆分 `gis_tools.py`；
- 迁移测试导入路径。

### 阶段 4：前端拆分

- 拆分聊天、控制台和地图组件；
- 统一 API、类型、轮询和错误状态；
- 验证桌面和移动端交互。

### 阶段 5：删除旧实现

- 删除已完成迁移的 legacy 接口、别名和重复逻辑；
- 删除无引用文件和旧生成物；
- 更新 README、启动脚本和环境变量示例。

### 阶段 6：运行数据重置

- dry-run；
- 备份账号及登录态；
- 删除其他运行数据；
- 恢复并验证保留内容。

### 阶段 7：综合验证

- Python compileall 和完整 unittest；
- 前端测试和生产构建；
- Playwright 聊天、地图、登录、下载恢复和 artifact 流程；
- 安全测试、路径穿越测试和敏感文件下载测试；
- 启动脚本与全新工作区冒烟测试。

## 7. 错误处理与回滚

- 每阶段单独提交，禁止把结构迁移和运行数据清理混为一个不可回滚提交；
- 数据清理前保存数据库和登录态备份；
- 任一阶段回归失败时停止进入下一阶段；
- 迁移期间短期转发层必须标注删除阶段，并有测试覆盖；
- 恢复失败时优先恢复账号数据库和 GSCloud storage state，不继续清理。

## 8. 验收标准

- `app.py` 和 Vite 前端可正常启动；
- 普通用户的聊天、地图、下载、登录恢复和 artifact 流程行为不退化；
- `api_server.py`、`service.py`、`gis_tools.py`、`ChatPanel.tsx`、`ProductConsole.tsx`、`MapStage.tsx` 的职责明显收敛；
- 不存在两个活动本地库根目录或两套任务状态映射；
- 删除候选均有引用证据或迁移证明；
- 运行数据清理后，账号、套餐、配额和 GSCloud 登录态保留；
- 聊天、任务、成果、上传、缓存和测试数据为空；
- 完整测试、构建、Playwright 和安全检查通过；
- 输出结构迁移清单、删除清单、数据清理报告及剩余风险。
