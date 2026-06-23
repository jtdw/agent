---
title: "下载产品、区域与时间规则"
language: "zh-CN"
tags: ["download", "product_catalog", "area_resolver", "time_range", "dem", "sentinel", "下载", "产品目录", "区域解析", "时间范围", "哨兵"]
applicable_scope: "data_download_planning"
reliability: "high"
version: "2026-06-22.1"
status: "draft"
source: "project-code: core/product_catalog.py; core/area_resolver.py; core/download_candidates.py; core/task_plan_schema.py; core/plan_validator.py"
---

# 下载产品、区域与时间规则

本文档只解释下载规划边界。具体产品、分辨率、时间规则、适配器、登录要求和启停状态始终以当前 Product Catalog 为准。

## 下载请求必须具备的信息

一个可执行下载请求至少需要经过验证的区域、产品、分辨率或已解析分辨率、必要时间参数、权限上下文和用户确认状态。区域必须来自 AreaResolver、上传边界或用户明确引用的默认空间资产。产品必须来自 Product Catalog。下载工具只能读取已验证的 `download_requests`，不能重新解析用户原文。

时间范围完整不等于远端一定存在数据。Product Catalog 只说明理论支持、参数要求和适配器关系；提交下载前仍必须由 Validator 和下载适配器基于真实数据源能力、登录状态、覆盖范围、分页或场景查询结果确认可用性。若适配器返回无数据，必须如实说明，不得创建虚假 artifact。

## 时间规则差异

DEM 类产品通常是无时间维度产品。若当前 Product Catalog 标记 DEM 的 `temporal_requirement=none`，不应要求用户提供日期。

LST、EVI、地表反射率、Sentinel 等时间相关产品通常需要日期或时间范围。若 Product Catalog 标记为 `date_range` 且用户未提供时间范围，Planner 应用中文提出一个具体时间问题，不应创建下载任务。

Sentinel 的云量、波段、空间分辨率、最大场景数等参数只按当前 Product Catalog 和下载适配器实际支持解释。知识库不能替 Sentinel 补充未配置的波段规则、云量阈值或数据源能力。

## 区域解析原则

行政区名称应由 AreaResolver 基于真实行政区边界库或已登记资产解析。省级、市级范围应由下级单元真实筛选并 dissolve，不得凭名称伪造几何。流域边界只有在用户明确说出该流域或默认资产时才可使用。例如用户明确说“闪电河流域”时，应优先使用对应默认流域资产，不得被历史区域、selected object 或默认行政区覆盖。

同名行政区存在多个候选时，应返回候选并用中文追问上级区域。Resolver 只提供候选边界和元数据，不决定产品。

## 多产品请求

同一 TaskPlan 可以包含多个 download_requests。每个产品应独立校验、独立执行并独立产生 ToolResult。一个产品失败、等待登录或无数据，不代表其他产品已失败或已成功。

## 禁止行为

- 不得因为文本里出现 DEM、LST、Sentinel 等词就直接下载。
- 不得把知识库中的描述当作 Product Catalog 的替代事实。
- 不得在缺少时间范围时提交时间产品下载。
- 不得把“时间范围齐全”描述成“远端一定有数据”。
- 不得把“文件库”的“文”解析成行政区名。

## 检索测试问题

1. “下载成都市 30m DEM 是否需要日期？”
2. “下载闪电河流域 LST 但没说时间，应该怎么问？”
3. “用户同时要 EVI、地表反射率和 Sentinel 时如何处理多个结果？”
