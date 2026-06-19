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
    return merged[:limit]
