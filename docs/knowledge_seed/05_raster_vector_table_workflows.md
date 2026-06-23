---
title: "栅格、矢量、表格转点与制图工作流"
language: "zh-CN"
tags: ["raster", "vector", "table_to_points", "mapping", "toolresult", "栅格", "矢量", "表格转点", "制图", "坡度", "坡向", "缓冲区", "空间连接"]
applicable_scope: "gis_processing_workflows"
reliability: "high"
version: "2026-06-22.1"
status: "draft"
source: "project-code: core/tool_cards.py; core/tools/raster_tools.py; core/tools/vector_tools.py; core/tools/table_tools.py; core/presentation_result.py"
---

# 栅格、矢量、表格转点与制图工作流

本文档说明常见 GIS 工具的前置条件和结果解释方式。真实工具是否可用、输入字段和输出结构以当前 Tool Cards、Plan Validator 和 ToolResult 为准。

## 栅格分析

栅格统计、裁剪和制图需要真实已加载栅格、可读取文件、CRS、范围、波段和 NoData 元数据。若裁剪边界来自矢量，应确认边界存在、几何有效且与栅格范围有交集。统计值必须来自工具输出，不能凭文件名或产品名推断。

矢量边界裁剪栅格属于已登记 Tool Card 覆盖的常见工作流，前置条件是目标栅格、面状边界和可处理 CRS。当前 Tool Cards 已覆盖 DEM 坡度坡向、栅格计算、明确波段映射的 NDVI、栅格重投影、矢量边界裁剪栅格和站点-栅格采样。即便如此，Planner 仍必须通过候选 Tool Cards、TaskPlan 和 Validator 选择工具，不能仅凭知识文本调用工具。

DEM 坡度坡向只能对具备投影坐标 CRS 的 DEM 执行。若 DEM 是经纬度 CRS，应先通过已验证计划重投影，或向用户确认目标投影；不得直接对地理坐标 DEM 计算平面坡度。坡度单位必须明确为 degree 或 percent。

栅格重投影支持显式目标 CRS、重采样方法和目标分辨率。目标分辨率必须由 TaskPlan 明确给出，并以目标 CRS 的坐标单位解释；若目标分辨率缺失，只能在 Tool Card 或任务规则允许时保留默认计算分辨率，不得由知识文本或 LLM 猜测新的分辨率。ToolResult diagnostics 应包含原始 CRS、目标 CRS、原始分辨率、目标分辨率、重采样方法和输出 transform。

## 矢量分析

矢量裁剪需要目标矢量和面状边界。若几何无效、无要素、CRS 缺失或无空间交集，应阻断或返回明确失败。不能把纯表格当作矢量图层裁剪。

当前 Tool Cards 已覆盖矢量缓冲区和空间连接。缓冲区必须明确距离和单位；米制缓冲在地理 CRS 下需要使用验证后的临时投影处理。空间连接必须明确目标图层、连接图层、空间关系、连接方式和字段冲突策略。按边界汇总点位也有工具支持，但仍必须由候选 Tool Cards 和 Validator 确认输入。

## 表格转点

表格转点需要真实字段元数据中的 x/y 或经纬度字段，并需要明确 CRS。若候选坐标字段不唯一，应询问用户选择字段。转换成功后应生成点矢量数据集、artifact 或 map layer。

当前 Tool Cards 已覆盖单栅格采样到点和多栅格批量采样到点。站点-栅格采样需要先确认站点点位、栅格 CRS、范围、波段、采样方法和时间匹配。支持的采样方法以当前 Tool Card 和工具实现为准；当前单栅格采样支持 nearest 和 bilinear。

## 制图和地图加载

制图只能使用已加载数据集或工具真实输出。专题字段必须存在。结果应通过 map_layer_refs、image_refs 或 artifact_refs 呈现，不能只用自然语言声称“已制图”。

## ToolResult 应包含的信息

成功时应包含 outputs、artifacts、map_layers、diagnostics 和必要 warnings。失败时应包含 errors、error_code、error_title 和 user_message。next_actions 是建议，不代表已执行。

## 何时追问

- 用户未指定要处理的数据，且当前轮没有明确上传。
- 表格坐标字段不明确。
- 裁剪任务缺少边界或目标数据。
- 制图字段不存在或用户没有说明专题字段。

## 检索测试问题

1. “CSV 什么时候可以直接上地图？”
2. “矢量裁剪栅格需要哪些输入？”
3. “制图工具失败时 PresentationResult 应展示什么？”
4. “DEM 是经纬度 CRS 时能不能直接计算坡度？”
5. “栅格重投影时目标分辨率没说清楚能不能自动猜？”
