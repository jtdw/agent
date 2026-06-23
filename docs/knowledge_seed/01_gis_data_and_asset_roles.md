---
title: "GIS 数据类型与资产角色"
language: "zh-CN"
tags: ["gis", "asset", "asset_roles", "planner", "uploads", "数据角色", "资产角色", "上传数据", "默认资产"]
applicable_scope: "asset_role_understanding"
reliability: "high"
version: "2026-06-22.1"
status: "draft"
source: "project-code: core/context_builder.py; core/task_plan_schema.py; core/area_resolver.py; core/tool_cards.py"
---

# GIS 数据类型与资产角色

本文档是 Planner 的参考知识，不是工具注册表、产品目录或资产注册表。真实可用工具以 Tool Cards 为准，真实可下载产品以当前 Product Catalog 为准，真实默认资产以 Asset Registry 和 AreaResolver 返回的候选为准。

## 常见数据角色

- 栅格：通常用于 DEM、NDVI、LST、预测结果、专题底图等网格数据。可参与栅格统计、裁剪、采样、制图或作为模型特征。
- 矢量：包含点、线、面几何和属性字段。面数据常作为边界，点数据常作为站点或采样位置。
- 表格：CSV、Excel 等非空间表格必须有真实字段元数据。只有存在坐标字段并明确 CRS 时，才能转换为点图层。
- 站点包：站点观测数据通常需要目标变量、坐标、时间字段和深度等业务字段。不能仅凭文件名断定字段存在。
- 边界：边界可以来自上传文件、AreaResolver 解析的行政区、或用户明确引用的默认空间资产。边界不能由历史图层自动替代。
- 成果文件：工具真实生成并注册的 artifact、map layer、table 或 image。不能由 LLM 编造文件名、下载链接或指标。

## 配置资源的边界

- 知识库：提供领域解释、约束和澄清建议。知识库文本不能直接触发工具，也不能覆盖 Product Catalog、Tool Card 或权限校验。
- Asset Registry：登记真实存在、可授权访问的默认资产。默认资产只有在用户明确引用时才能进入输入候选。
- Product Catalog：描述真实支持的数据产品、分辨率、时间规则、适配器和状态。涉及产品能力时始终以当前 Product Catalog 为准。
- Tool Card：描述工具能力、输入角色、前置条件、输出类型和禁用用途。Tool Card 只约束候选工具，不代表工具已执行。

## 优先级规则

当前用户请求优先于历史结果、selected object、默认区域和最近文件。当前轮上传文件和用户明确指定的默认数据优先于自动下载替代数据。若用户没有明确提到“上次结果”“刚才下载”“这个图层”等历史引用，Planner 不应把 previous_result 或 selected object 填入新任务。

## 需要追问的情况

- 用户说“用我的数据分析”，但当前轮没有上传资产，也没有明确选择默认资产。
- 存在多个候选边界或同名行政区，且缺少上级区域。
- 表格需要转点，但字段元数据中没有明确经纬度或坐标字段。
- 模型任务缺少目标变量、特征变量或样本来源。

## 检索测试问题

1. “我上传了一个 CSV 和一个 shp，哪个可以作为裁剪边界？”
2. “默认文件库里的数据什么时候可以自动使用？”
3. “知识库文档能不能覆盖 Product Catalog 的产品分辨率？”
