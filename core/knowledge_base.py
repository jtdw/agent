from __future__ import annotations

import re
from typing import Any

from core.capability_config import CAPABILITY_CONFIG_VERSION, configured_knowledge

_SNIPPETS: tuple[dict[str, Any], ...] = (
    {
        "id": "raster-vector-crs",
        "title": "栅格、矢量与 CRS",
        "content": "矢量数据包含几何和属性字段；栅格数据包含像元、分辨率、波段、NoData、范围和 CRS。裁剪、采样、叠加前应确认 CRS、空间范围和 NoData。",
        "tags": ["raster", "vector", "crs", "projection", "裁剪", "采样"],
        "source": "project-gis-agent-knowledge",
        "version": "2026-06-20",
        "scope": "general_gis_processing",
        "trust_level": "high",
    },
    {
        "id": "station-raster-matching",
        "title": "站点与栅格时空匹配",
        "content": "站点-栅格特征提取需要真实站点坐标、时间字段和候选栅格。应先转点或确认点几何，再按空间位置采样栅格，并在有时间维度时匹配日期或时间窗口。",
        "tags": ["station", "raster", "sample", "feature", "time", "站点", "栅格", "特征"],
        "source": "project-gis-agent-knowledge",
        "version": "2026-06-20",
        "scope": "station_raster_feature_extraction",
        "trust_level": "high",
    },
    {
        "id": "xgboost-validation",
        "title": "XGBoost 建模与验证",
        "content": "XGBoost 任务必须明确目标变量、特征数据、训练/验证切分和真实输出产物。空间数据应优先考虑空间交叉验证，报告 RMSE、MAE、R2、NSE、残差和特征重要性。",
        "tags": ["xgboost", "modeling", "rmse", "mae", "r2", "nse", "空间交叉验证", "残差"],
        "source": "project-gis-agent-knowledge",
        "version": "2026-06-20",
        "scope": "ml_regression_validation",
        "trust_level": "high",
    },
    {
        "id": "download-safety",
        "title": "下载数据源、许可和失败处理",
        "content": "下载任务应先确认产品、区域、时间、账号和许可限制。商业下载、高成本下载、平台账号使用和覆盖已有成果需要用户确认；失败时报告登录、许可、网络、分页或文件校验原因。",
        "tags": ["download", "license", "gscloud", "commercial", "confirmation", "下载"],
        "source": "project-gis-agent-knowledge",
        "version": "2026-06-20",
        "scope": "data_download",
        "trust_level": "high",
    },
    {
        "id": "map-loading-formats",
        "title": "文件格式与地图加载",
        "content": "地图预览通常可加载 GeoJSON、Shapefile 转换结果和 GeoTIFF 栅格。CSV 需要真实坐标字段并转换为点图层后才能作为空间图层稳定显示。",
        "tags": ["format", "map", "geojson", "shp", "geotiff", "csv", "table_to_points"],
        "source": "project-gis-agent-knowledge",
        "version": "2026-06-20",
        "scope": "map_display",
        "trust_level": "medium",
    },
    {
        "id": "ismn-local-archive",
        "title": "ISMN 本地归档与土壤水分观测",
        "content": "ISMN 土壤水分任务只使用用户上传、workspace 或 local_library 中已有的本地 archive。不得自动下载 ISMN 数据，不处理登录凭据、Cookie、token 或 storage_state；导入前应剖析 network、station、sensor、depth、variable、quality flag、坐标和时间范围。",
        "tags": ["ismn", "archive", "soil_moisture", "station", "sensor", "depth", "土壤水分", "本地归档", "观测"],
        "source": "project-gis-agent-knowledge",
        "version": "2026-06-29",
        "scope": "ismn_soil_moisture_reference",
        "trust_level": "high",
    },
    {
        "id": "gcp-uncertainty-interpretation",
        "title": "GCP 空间预测不确定性解释",
        "content": "GCP 必须基于真实观测、预测、残差和校准数据。global split conformal 是安全基线；只有坐标和校准样本充足时才解释为空间加权 GCP。interval width、coverage、uncertainty map 必须来自真实 ToolResult，坐标不足时应回退 global split conformal 并说明原因。",
        "tags": ["gcp", "geoconformal", "uncertainty", "interval", "coverage", "global", "split", "conformal", "不确定性", "空间预测"],
        "source": "project-gis-agent-knowledge",
        "version": "2026-06-29",
        "scope": "gcp_uncertainty_reference",
        "trust_level": "high",
    },
    {
        "id": "arcgis-arcpy-taxonomy-boundary",
        "title": "ArcGIS 和 ArcPy 仅作为 GIS 术语参考",
        "content": "ArcGIS Pro 和 ArcPy 文档可作为表格转点、分区统计、制图和地理处理术语参考。不新增 ArcPy 运行时依赖，不把外部 ArcPy 工具名当作已注册工具名；实际执行仍必须由本项目 Tool Cards、TaskPlan、Validator 和工具实现确认。",
        "tags": ["arcgis", "arcpy", "taxonomy", "xy", "zonal", "table_to_points", "术语", "依赖", "分区统计"],
        "source": "project-gis-agent-knowledge",
        "version": "2026-06-29",
        "scope": "gis_taxonomy_reference",
        "trust_level": "high",
    },
)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", str(text or ""))}


def retrieve_knowledge_snippets(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    configured = configured_knowledge(query, limit=limit)
    query_tokens = _tokens(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in _SNIPPETS:
        haystack = _tokens(" ".join([item["title"], item["content"], " ".join(item.get("tags") or [])]))
        score = len(query_tokens & haystack)
        compact_query = str(query or "").lower()
        for tag in item.get("tags") or []:
            if str(tag).lower() in compact_query:
                score += 2
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id") or "")))
    builtin = [dict(item, knowledge_chunk_id=f"{item.get('id')}:{item.get('version')}", knowledge_id=item.get("id"), knowledge_version=item.get("version"), source_trust="trusted_operator", schema_version=CAPABILITY_CONFIG_VERSION) for _, item in scored[:limit]]
    merged = configured + builtin
    normalized: list[dict[str, Any]] = []
    for item in merged[:limit]:
        snippet = dict(item)
        snippet.setdefault("version", snippet.get("knowledge_version") or "")
        snippet.setdefault("scope", snippet.get("applicable_scope") or "")
        snippet.setdefault("trust_level", snippet.get("reliability") or snippet.get("source_trust") or "")
        normalized.append(snippet)
    return normalized
