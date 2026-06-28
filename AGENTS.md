# AGENTS.md

本项目是一个 GIS 智能体项目，包含 FastAPI 后端、React/TypeScript 前端、GIS 空间处理工具链、文件上传下载、地图预览、智能体对话和工作流执行能力。

Codex 在本项目中工作时，必须遵守以下规则。

## 一、总体原则

* 不要一次性大规模重写项目。
* 不要破坏现有后端 API、前端调用方式和已有核心功能。
* 修改前先阅读相关文件，理解现有结构后再改。
* 优先小步修改、分批提交、每批修改后运行检查。
* 不要为了重构而重构，优先修复实际问题。
* 所有修改都要尽量保持向后兼容。
* 如果发现风险较大的改动，应先说明方案，不要直接大改。
* 使用项目内 .venv，这比当前系统 python 更可信。

## 二、项目目标

本项目目标不是普通聊天机器人，而是 GIS 智能工作台。

核心流程是：

用户上传地理数据
→ 智能体识别数据类型
→ 选择合适 GIS 工具或工作流
→ 执行空间处理、制图或分析
→ 在地图和结果面板中展示
→ 提供可下载产物和分析说明

因此，任何修改都应围绕以下目标：

* 提升 GIS 数据处理能力；
* 提升智能体工具调用稳定性；
* 提升文件、会话、地图、结果之间的绑定关系；
* 提升网页使用体验；
* 提升中文兼容性；
* 提升项目可维护性和可测试性。

## 三、前端 UI 规则

前端整体布局已经确定，除非用户明确要求，不要重新设计整体布局。

UI 修改默认只做：

* 视觉美化；
* 组件样式优化；
* 交互细节优化；
* 响应式适配；
* 错误提示优化；
* 结果卡片优化；
* 文件上传和下载体验优化；
* 地图工具栏和图层面板优化。

推荐风格：

* SaaS Dashboard；
* AI Copilot；
* GIS 智能工作台；
* 简洁、现代、专业；
* 浅色主题为主，可兼容深色模式；
* 不要做成复杂传统 GIS 软件；
* 不要只做普通聊天页面。

前端技术要求：

* 优先使用 React + TypeScript + Tailwind CSS；
* 优先复用现有组件；
* 不要引入过多新的 UI 依赖；
* 不要破坏现有路由、状态管理和 API 请求；
* 修改后必须尽量运行 npm run build；
* 如果无法运行 build，要说明原因。

## 四、后端规则

后端以稳定、安全、可维护为优先。

修改后端时必须注意：

* 不要破坏现有 FastAPI 接口；
* 不要随意改变已有请求参数和响应结构；
* 新增字段时尽量保持兼容；
* 文件上传、artifact 下载、地图图层、会话数据必须考虑 user_id 和 session_id 绑定；
* 涉及 workspace、uploads、outputs、artifacts、map layers 的逻辑必须避免跨用户、跨会话混用；
* 删除会话时，应考虑同步清理或失效对应上传文件、结果文件、artifact 和地图图层；
* 工具执行不要直接相信外部传入的 user_id 或 session_id，应优先从后端上下文中读取当前用户和当前会话。

## 五、GIS 工具与智能体规则

本项目的智能体不应完全依赖 LLM 自由发挥，应尽量把高频 GIS 任务做成稳定工作流。

常见工作流包括：

* 上传数据后识别数据类型、字段、坐标系、范围；
* 矢量数据基本信息查看；
* 栅格数据基本信息查看；
* 矢量裁剪矢量；
* 矢量裁剪栅格；
* 表格经纬度转点；
* 栅格统计；
* 坐标系检查和重投影；
* 地图制图；
* 结果报告生成。

工具执行要求：

* 执行前检查参数；
* 执行前检查文件是否存在；
* 执行前检查路径是否在允许 workspace 内；
* 执行失败时返回结构化错误；
* 错误信息应包含原因和建议；
* 输出结果应注册为 artifact，方便前端展示和下载。

## 六、中文与 UTF-8 编码规则

本项目必须完整支持中文。

所有源码、文档、配置、脚本默认使用 UTF-8 编码。

Python 文本读写必须显式指定 encoding，例如：

* open(..., encoding="utf-8")
* Path.read_text(encoding="utf-8")
* Path.write_text(..., encoding="utf-8")
* json.dump(..., ensure_ascii=False)
* logging.FileHandler(..., encoding="utf-8")
* pandas.read_csv(..., encoding="utf-8" 或 encoding="utf-8-sig")
* DataFrame.to_csv(..., encoding="utf-8-sig" 或 encoding="utf-8")

不得依赖 Windows 默认编码。

不得通过 PowerShell 管道传递中文源码、中文常量或中文提示词给 Python。如果必须处理中文输入，优先使用：

* 传文件路径给 Python；
* Python 内部用 UTF-8 显式读取；
* 设置 PYTHONUTF8=1；
* 设置 PYTHONIOENCODING=utf-8；
* PowerShell 中设置 InputEncoding、OutputEncoding 和 $OutputEncoding 为 UTF-8。

## 六点一、PowerShell 命令规则

本项目默认 shell 是 PowerShell。Codex 运行内联 Python、Node 或其他多行脚本时，禁止使用 Bash heredoc 写法，例如：

```bash
python - <<'PY'
...
PY
```

PowerShell 中必须使用 here-string 管道写法：

```powershell
@'
print("hello")
'@ | .\.venv\Scripts\python.exe -
```

如果需要执行多行 Python，优先使用项目 `.venv`：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'

@'
from pathlib import Path
print(Path.cwd())
'@ | .\.venv\Scripts\python.exe -
```

不要在 PowerShell 中使用 `<<`、`<<EOF`、`<<'PY'` 等 Bash heredoc 语法。

如果内联脚本包含中文内容，不要通过 PowerShell 管道传递；应写入临时 `.py` 文件或使用已有脚本，并确保 UTF-8 编码。

## 六点二、常见执行注意事项

* 当前项目运行环境是 Windows + PowerShell，命令示例必须优先使用 PowerShell 语法，不要默认使用 Bash/Linux 语法。
* 路径默认使用 Windows 路径或 PowerShell 可识别路径；路径含空格时必须使用 `-LiteralPath` 或引号包裹。
* 运行 Python 命令优先使用项目 `.venv\Scripts\python.exe`，不要默认使用系统 Python。
* 运行 npm 命令前先确认所在目录；前端命令通常应在 `ui_next` 目录执行。
* 不要把 `.env`、API Key、token、cookie、storage_state、日志中的敏感内容输出到回复或终端摘要中。
* 检查 API key 是否可用时，只输出是否存在、长度、HTTP 状态、错误码和脱敏错误信息，不输出完整 key。
* 工作区可能已有用户改动。修改前先看 `git status --short`，不要回滚、覆盖或格式化无关文件。
* 修改代码前先阅读相关文件，避免凭文件名猜测结构。
* 只改和任务直接相关的文件；不要顺手做大规模格式化、重命名或重构。
* 如果命令失败，先判断是 shell 语法、路径、依赖、环境变量还是业务逻辑问题，不要连续重复运行同一个失败命令。
* PowerShell 中不要用 `&&`、`||`、heredoc、`export VAR=...` 等 Bash 写法；应使用 `$env:VAR='value'`、`;` 或分步执行。
* 涉及中文内容时，显式设置 UTF-8，并避免通过 PowerShell 管道传递中文源码或中文提示词。

## 六点三、Codex 自检规则

Codex 在运行命令前应先确认当前 shell、当前工作目录和项目虚拟环境。

如果命令需要联网、调用外部 API 或读取 `.env`，必须：

* 不打印敏感值；
* 使用最小请求验证；
* 输出脱敏后的状态摘要；
* 遇到认证失败时报告 HTTP 状态码和供应商错误码，不猜测 key 内容。

如果第一次命令因为 shell 语法失败，应明确记录原因，并改用当前 shell 的原生写法继续执行。

发现以下疑似乱码时，不要凭空猜测原文：

* ???
* 锟斤拷
* �
* Ã
* å
* æ
* ä

如果无法从上下文、Git 历史或备份恢复，应标注 TODO_ENCODING_REVIEW，并输出清单让用户确认。

## 七、文件、路径和 artifact 规则

处理文件时必须注意：

* 不要直接信任用户上传文件名；
* 上传文件应避免同名覆盖；
* 内部存储建议使用 uuid 或安全文件名；
* 展示层保留 original_filename；
* 下载时应校验用户和会话权限；
* 不允许通过 artifact 下载 .env、token、cookie、storage_state、日志、数据库等敏感文件；
* 解压 zip 时必须防止路径穿越；
* 所有路径都应限制在项目允许的 workspace 内。

## 八、测试与检查规则

修改代码后，尽量运行相应检查。

后端常用检查：

* python -m py_compile 相关文件
* pytest
* python -m unittest discover tests

前端常用检查：

* npm run build
* npm run lint
* npm test

如果测试环境不完整，无法运行某些命令，必须说明原因，不要假装已经通过。

重要功能修改应优先补充测试，尤其是：

* 用户隔离；
* 会话隔离；
* artifact 下载权限；
* 文件上传；
* zip 解压安全；
* SQL 只读限制；
* 中文文件名；
* 中文字段名；
* 中文 JSON；
* 中文日志；
* 工具上下文；
* GIS 工作流 smoke test。

## 九、安全规则

当前项目仍在开发阶段，但不要新增明显安全风险。

必须避免：

* 把 API Key、账号密码、cookie、storage_state 写入代码；
* 把 .env、日志、登录态文件暴露为 artifact；
* 让用户下载任意服务器文件；
* 让 LLM 任意执行危险 SQL；
* 让工具访问 workspace 外部路径；
* 让不同用户或不同会话的数据互相串用。

## 十、代码结构规则

如果某个文件过大，可以建议拆分，但不要一次性大规模迁移。

GIS 工具模块可以逐步拆为：

* vector_tools.py
* raster_tools.py
* table_tools.py
* map_tools.py
* ml_tools.py
* download_tools.py
* document_tools.py
* commercial_tools.py
* registry.py

拆分时必须保持原有工具注册机制兼容，并确保 import 正常。

## 十一、输出要求

Codex 每次完成任务后，应输出：

* 修改了哪些文件；
* 为什么这样修改；
* 是否运行了测试或构建；
* 测试或构建结果；
* 是否还有未解决问题；
* 后续建议。

如果只是审查任务，不要修改代码，只输出问题清单、风险等级、涉及文件和修复建议。

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **agent** (9231 symbols, 20862 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/agent/context` | Codebase overview, check index freshness |
| `gitnexus://repo/agent/clusters` | All functional areas |
| `gitnexus://repo/agent/processes` | All execution flows |
| `gitnexus://repo/agent/process/{name}` | Step-by-step execution trace |

## CLI Compatibility

This project uses GitNexus CLI 1.6.8 compatible parameters. Do not use `--max-depth`; this version does not accept it. When limiting analysis scope, pass an explicit path to `node .gitnexus/run.cjs analyze` or configure `.gitnexusignore`. Before using version-sensitive flags, check the current command help with `node .gitnexus/run.cjs <command> --help`.

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
