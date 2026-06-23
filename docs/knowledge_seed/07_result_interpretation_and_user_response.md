---
title: "结果解释与普通用户回复边界"
language: "zh-CN"
tags: ["presentation_result", "toolresult", "user_response", "frontend", "结果解释", "用户回复", "前端展示", "脱敏"]
applicable_scope: "result_interpretation"
reliability: "high"
version: "2026-06-22.1"
status: "draft"
source: "project-code: core/presentation_result.py; core/result_interpreter.py; core/tool_contracts.py; core/execution_trace.py; ui_next/src/components/ChatMessageRenderer.tsx"
---

# 结果解释与普通用户回复边界

最终回复必须基于 canonical ToolResult 和 ExecutionTrace 中的真实事实。Result Interpreter 只能读取 outputs、artifacts、warnings、errors、diagnostics、next_actions、状态、步骤和工具标识，不能读取 raw job、旧 workflow steps、内部路径或异常堆栈。

## 成功结果

成功回复只展示真实生成的结果、artifact、图层、表格、图片和指标。artifact_refs、map_layer_refs、table_refs、image_refs 必须来自后端真实 ID。下载或预览链接由后端 resolver 生成，LLM 不生成 URL。

## 失败结果

失败时应说明失败步骤、用户可理解原因、稳定错误码和可选下一步。不能使用成功模板，也不能说“已生成结果”。内部路径、堆栈、user_id、session_id、Cookie、Token 和调试日志不得展示给普通用户。

## 等待和阻断

running 表示仍在执行，应展示真实状态。awaiting_confirmation 表示需要用户确认具体事项。blocked 表示权限、登录、配额或输入缺失阻止继续。此类状态都不能被描述为完成。

## 下一步建议

next_action_suggestions 只能来自真实 next_actions、已验证计划或安全的确定性解释。建议不代表动作已经执行。任何新增下载、覆盖输出、付费数据或长耗时操作仍需门控和确认。

## 检索测试问题

1. “工具返回 failed 时最终回复应该包含哪些内容？”
2. “artifact_refs 可以让 LLM 自己编吗？”
3. “普通用户界面能不能显示 raw job dict？”
