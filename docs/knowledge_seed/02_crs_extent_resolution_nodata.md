---
title: "CRS、范围、分辨率与 NoData 质量检查"
language: "zh-CN"
tags: ["crs", "extent", "resolution", "nodata", "quality", "坐标系", "范围", "分辨率", "无效值", "质量检查"]
applicable_scope: "gis_quality_and_preconditions"
reliability: "high"
version: "2026-06-22.1"
status: "draft"
source: "project-code: core/data_quality.py; core/data_manager.py; core/tools/raster_tools.py; core/tools/vector_tools.py; core/plan_validator.py"
---

# CRS、范围、分辨率与 NoData 质量检查

GIS 工具执行前后必须依赖确定性元数据和质量检查。LLM 只能解释真实检查结果，不能猜测 CRS、分辨率、范围、NoData 或几何有效性。

## 核心概念

- CRS：坐标参考系统。裁剪、叠加、采样和制图前应确认输入数据 CRS 是否存在并可转换。
- 范围：数据的空间边界。两个数据无空间交集时，裁剪或采样不应继续伪造成果。
- 分辨率：栅格像元大小。重采样会改变像元尺度，应由已验证计划或明确参数触发。
- NoData：栅格无效值。若裁剪后全部为 NoData，结果应作为失败或警告处理。
- 几何有效性：矢量几何为空、无效或类型不符合工具前置条件时，应阻断或要求修复。

## 裁剪、重投影和重采样前置条件

栅格裁剪需要真实栅格、真实面边界、存在的文件路径和可处理 CRS。矢量裁剪需要目标矢量、面状裁剪边界和可比较的空间范围。重投影或重采样只有在 TaskPlan 或 Coordinator 的剩余步骤允许时才能执行，不能由工具根据原始用户文本临时决定。

## 常见质量失败

- 文件损坏或无法读取。
- CRS 缺失，且没有安全默认值。
- 栅格为空、波段缺失、NoData 覆盖全部有效区域。
- 矢量无要素、几何为空、几何类型不符合工具。
- 表格坐标字段缺失、非数值或坐标超出 CRS 合理范围。
- 输出 artifact 文件不存在、大小为零或无法重新读取。

## 正确澄清方式

澄清问题应具体说明缺少哪类信息。例如：“这个栅格没有 CRS，请确认它的坐标系，或上传带 CRS 的版本。”不要笼统说“数据有问题”。若工具已返回统一 ToolResult，应基于其中的 errors、warnings、diagnostics 和 user_message 解释。

## 检索测试问题

1. “裁剪栅格前为什么要检查 CRS 和范围？”
2. “栅格裁剪后全是 NoData 应该怎么回复用户？”
3. “表格转点时坐标列不是数字怎么办？”
