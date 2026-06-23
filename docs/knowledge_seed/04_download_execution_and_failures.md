---
title: "下载执行状态、失败与成果边界"
language: "zh-CN"
tags: ["download", "toolresult", "management_view", "artifact", "failure", "下载状态", "登录等待", "取消", "过期", "重试"]
applicable_scope: "download_execution_and_result_handling"
reliability: "high"
version: "2026-06-22.1"
status: "draft"
source: "project-code: core/download_request_executor.py; core/tool_contracts.py; core/download_status.py; core/commercial/service.py; core/presentation_result.py"
---

# 下载执行状态、失败与成果边界

下载执行结果必须通过统一 ToolResult、ManagementView 和 PresentationResult 展示。普通用户界面不得直接展示 raw job、scene_job、tile_job、内部路径、Cookie、Token、user_id、session_id 或异常堆栈。

## 状态语义

- queued：任务已进入队列，但尚未开始执行。用户展示应为“已排队/等待开始”，不得描述为“正在下载”。
- running：任务正在执行、查询、下载或校验。用户展示可说明“正在处理”，但不能说已经完成。
- awaiting_confirmation：需要用户确认平台账号、下载成本、覆盖输出、许可事项或长耗时任务。用户展示应说明需要确认的具体事项。
- waiting_login：需要用户登录或授权。用户展示应为“等待登录/需要授权”，不得描述为“失败”。
- blocked：缺少权限、配额不足、账号不可用、参数非法或状态不允许继续。用户展示应说明阻断原因和所需信息。
- succeeded：真实文件已生成并通过 artifact 注册或可预览。
- failed：下载或校验失败，应说明稳定错误码和用户可理解原因。
- cancelled：用户或服务端取消了任务。用户展示应为“已取消”，不得描述为“已完成”。
- expired：任务、授权或临时状态已过期。用户展示应为“已过期/需要重新提交或重新登录”，不得描述为“已完成”。

## Durable Job、ToolResult 与用户展示映射

Durable Job 是后端任务生命周期状态；ToolResult 是统一执行事实；用户展示状态是脱敏后的界面状态。三者应按事实映射，不应互相伪造。

| Durable Job 状态 | ToolResult status | 用户展示状态 | 展示要求 |
| --- | --- | --- | --- |
| queued | running | 已排队 | 等待开始，不得说正在下载 |
| running | running | 正在处理 | 可展示进度或阶段，不得说完成 |
| awaiting_confirmation | awaiting_confirmation | 需要确认 | 说明确认事项 |
| waiting_login | awaiting_confirmation | 等待登录 | 提示登录或授权，不得说失败 |
| blocked | blocked | 已阻断 | 说明阻断原因和可选下一步 |
| succeeded | succeeded | 已完成 | 仅展示真实 artifacts、图层或结果 |
| failed | failed | 失败 | 展示稳定错误码和脱敏原因 |
| cancelled | blocked | 已取消 | 不得展示成功模板 |
| expired | blocked | 已过期 | 提示重新提交或重新授权 |

若某个旧 job 状态无法精确映射，后端应先转换为最保守的 ToolResult 状态，并保留脱敏 diagnostics。普通回复不能直接展示原始 job dict。

## 登录、重试和取消

等待登录时，应提示用户完成登录或授权，不应继续自动下载。失败后只有在后端提供可用 retry action 且状态允许时才能重试。取消任务必须由服务端真实取消或失效，不只是停止前端显示。

## artifact resolver 边界

下载成果只能通过真实 artifact_id、map layer id 或后端授权 resolver 暴露。LLM 和前端不能拼接文件路径或下载 URL。旧 download_url 只能作为兼容兜底，不应成为新结果事实来源。

## 禁止伪造成果

如果远端无数据、登录失败、文件不存在、校验失败或任务仍在运行，回复中不能出现“已下载完成”“已生成文件”或虚构下载链接。下一步建议只能来自真实 ToolResult 的 next_actions 或后端状态。

## 检索测试问题

1. “下载任务 waiting_login 时应该怎样回复？”
2. “为什么不能让 LLM 生成下载链接？”
3. “一个多产品下载里 Sentinel 失败但 DEM 成功时怎么展示？”
