---
title: "安全、会话隔离与数据生命周期"
language: "zh-CN"
tags: ["security", "session", "artifact", "privacy", "cleanup", "zip", "安全", "会话删除", "私有知识", "数据生命周期", "权限"]
applicable_scope: "security_and_lifecycle"
reliability: "high"
version: "2026-06-22.1"
status: "draft"
source: "project-code: core/data_manager.py; core/lifecycle_cleanup.py; core/capability_config.py; core/durable_jobs.py; core/commercial/service.py; api_server.py"
---

# 安全、会话隔离与数据生命周期

本项目的普通用户数据、会话资产、私有知识和任务结果必须按用户、会话或项目隔离。任何工具执行、artifact 下载、地图图层访问和知识检索都应基于后端可信上下文校验权限。

## 上传和 ZIP 风险

上传文件不能直接信任文件名。ZIP 解压必须防止路径穿越、压缩炸弹、异常文件数量和可疑扩展名。解压后的路径必须限制在允许 workspace 内。敏感文件、配置、Cookie、Token、日志和数据库不得注册为普通 artifact。

## artifact 权限

artifact 下载和预览必须通过 artifact_id 解析，并校验用户和会话权限。前端不能把 user_id 或 session_id 当作授权依据，也不能拼接服务器路径。

## 私有知识和会话记忆

用户私有知识、切分 chunks、索引、检索缓存、Planner trace、previous_result 和 selected object 只能在对应会话或授权范围内使用。

当前已实现行为：会话删除链路已通过后端硬删除测试覆盖，删除会话会移除会话私有知识记录、history、按 session 命名的知识 chunks/index/cache 文件、durable job 记录和 checkpoint/log，并清理会话 artifact、dataset、model result、pipeline 和商业下载 job 关联记录。删除后旧 artifact、job、知识和图层不应再被 Planner、Retriever、Artifact Resolver 或地图图层访问。

目标安全策略：如果未来接入新的向量数据库、外部缓存、异步 worker checkpoint 或项目级私有知识存储，也必须纳入同一删除级联。任何未纳入自动测试的存储，都只能标记为“待接入”，不得宣称已硬删除。

## 任务和成果清理

删除会话时，应先取消仍在运行的会话任务，再清理 uploads、derived、plots、temp、下载文件、模型成果、地图图层、artifact registry、dataset catalog、durable jobs 和商业下载记录。公共系统知识、公共 Product Catalog 和公共 Asset Registry 不应受会话删除影响。

若某项存储当前只能停用而不能删除 chunks、向量索引、缓存和持久化记录，应在 Result Interpreter 或管理端说明为“停用/不可用于检索”，不得写成“硬删除或等效不可恢复删除”。只有真实删除测试覆盖并通过后，才能将该项标记为已实现。

## 输出安全

普通用户界面不应显示内部路径、raw dict、请求头、异常堆栈、user_id、session_id、Cookie、Token 或下载器内部参数。失败解释应使用脱敏 diagnostics、error_code、error_title 和 user_message。

## 检索测试问题

1. “删除会话后私有知识还能被检索吗？”
2. “artifact 下载为什么必须经过 resolver？”
3. “ZIP 上传有哪些安全检查？”
