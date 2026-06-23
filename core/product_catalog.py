from __future__ import annotations

from typing import Any

from core.capability_config import configured_products
from core.dataset_availability import availability_for_product


PRODUCT_CATALOG_VERSION = "download-product-catalog/v1"


_PRODUCTS: list[dict[str, Any]] = [
    {
        "product_id": "gscloud_dem_30m",
        "display_name_zh": "地理空间数据云 DEM 30米",
        "source": "gscloud",
        "source_product_key": "gscloud_dem",
        "resource_type": "dem",
        "supported_resolutions": ["30m"],
        "temporal_requirement": "none",
        "spatial_coverage": "中国陆地区域，具体可用性以地理空间数据云实际记录为准",
        "required_parameters": ["area_asset_id", "resolved_resolution"],
        "optional_parameters": ["output_name", "account_mode"],
        "login_or_license_requirement": "需要地理空间数据云账号登录；开始下载前需要用户确认。",
        "supported_output_format": ["zip", "tif"],
        "tool_card": "submit_commercial_download_job",
        "download_adapter": "gscloud_dem_tile",
        "unsupported_scenarios": ["指定时间范围不会改变 DEM 产品。", "区域无覆盖时无法下载。"],
        "alternatives": ["gscloud_dem_90m"],
        "aliases": ["dem", "高程", "30m dem", "30米dem", "30米 dem"],
    },
    {
        "product_id": "gscloud_dem_90m",
        "display_name_zh": "地理空间数据云 DEM 90米",
        "source": "gscloud",
        "source_product_key": "gscloud_dem",
        "resource_type": "dem",
        "supported_resolutions": ["90m"],
        "temporal_requirement": "none",
        "spatial_coverage": "中国陆地区域，具体可用性以地理空间数据云实际记录为准",
        "required_parameters": ["area_asset_id", "resolved_resolution"],
        "optional_parameters": ["output_name", "account_mode"],
        "login_or_license_requirement": "需要地理空间数据云账号登录；开始下载前需要用户确认。",
        "supported_output_format": ["zip", "tif"],
        "tool_card": "submit_commercial_download_job",
        "download_adapter": "gscloud_dem_tile",
        "unsupported_scenarios": ["指定时间范围不会改变 DEM 产品。", "区域无覆盖时无法下载。"],
        "alternatives": ["gscloud_dem_30m"],
        "aliases": ["dem", "高程", "90m dem", "90米dem", "90米 dem"],
    },
    {
        "product_id": "gscloud_ndvi_500m_10day",
        "display_name_zh": "MODND1T 中国 500M NDVI 旬合成产品",
        "source": "gscloud",
        "source_product_key": "modnd1t_china_500m_ndvi_10day",
        "resource_type": "modnd1t_ndvi_10day",
        "supported_resolutions": ["500m"],
        "temporal_requirement": "date_range",
        "spatial_coverage": "中国区域，按地理空间数据云场景记录筛选",
        "required_parameters": ["area_asset_id", "time_range"],
        "optional_parameters": ["output_name", "account_mode", "max_scenes", "include_qc"],
        "login_or_license_requirement": "需要地理空间数据云账号登录；开始下载前需要用户确认。",
        "supported_output_format": ["zip"],
        "tool_card": "submit_commercial_download_job",
        "download_adapter": "gscloud_scene_table",
        "unsupported_scenarios": ["缺少时间范围时不能提交下载。", "默认只下载 NDVI/MAX 主产品，QC 质量控制文件需要显式参数。"],
        "alternatives": ["gscloud_evi_250m_10day"],
        "aliases": ["ndvi", "归一化植被指数", "modnd1t", "modnd1d", "500m ndvi", "modis ndvi", "植被指数"],
    },
    {
        "product_id": "gscloud_lst_1km_10day",
        "display_name_zh": "MODLT1T 中国 1KM 地表温度旬合成产品",
        "source": "gscloud",
        "source_product_key": "modl1t_china_1km_lst_composite",
        "resource_type": "modl1t_lst_composite",
        "supported_resolutions": ["1km"],
        "temporal_requirement": "date_range",
        "spatial_coverage": "中国区域，按地理空间数据云场景记录筛选",
        "required_parameters": ["area_asset_id", "time_range"],
        "optional_parameters": ["output_name", "account_mode", "max_scenes"],
        "login_or_license_requirement": "需要地理空间数据云账号登录；开始下载前需要用户确认。",
        "supported_output_format": ["zip"],
        "tool_card": "submit_commercial_download_job",
        "download_adapter": "gscloud_scene_table",
        "unsupported_scenarios": ["缺少时间范围时不能提交下载。"],
        "alternatives": [],
        "aliases": ["lst", "地表温度", "modl1t", "modlt1t"],
    },
    {
        "product_id": "gscloud_evi_250m_10day",
        "display_name_zh": "MODEV1T 中国 250M EVI 旬合成产品",
        "source": "gscloud",
        "source_product_key": "modev1t_china_250m_evi_10day",
        "resource_type": "modev1t_evi_10day",
        "supported_resolutions": ["250m"],
        "temporal_requirement": "date_range",
        "spatial_coverage": "中国区域，按地理空间数据云场景记录筛选",
        "required_parameters": ["area_asset_id", "time_range"],
        "optional_parameters": ["output_name", "account_mode", "max_scenes"],
        "login_or_license_requirement": "需要地理空间数据云账号登录；开始下载前需要用户确认。",
        "supported_output_format": ["zip"],
        "tool_card": "submit_commercial_download_job",
        "download_adapter": "gscloud_scene_table",
        "unsupported_scenarios": ["缺少时间范围时不能提交下载。"],
        "alternatives": [],
        "aliases": ["evi", "modev1t", "植被指数"],
    },
    {
        "product_id": "gscloud_surface_reflectance_1km",
        "display_name_zh": "MOD021KM 1KM 地表反射率",
        "source": "gscloud",
        "source_product_key": "mod021km_1km_surface_reflectance",
        "resource_type": "mod021km_surface_reflectance",
        "supported_resolutions": ["1km"],
        "temporal_requirement": "date_range",
        "spatial_coverage": "中国区域，按地理空间数据云场景记录筛选",
        "required_parameters": ["area_asset_id", "time_range"],
        "optional_parameters": ["output_name", "account_mode", "max_scenes"],
        "login_or_license_requirement": "需要地理空间数据云账号登录；开始下载前需要用户确认。",
        "supported_output_format": ["zip"],
        "tool_card": "submit_commercial_download_job",
        "download_adapter": "gscloud_scene_table",
        "unsupported_scenarios": ["缺少时间范围时不能提交下载。"],
        "alternatives": [],
        "aliases": ["地表反射率", "surface reflectance", "mod021km", "反射率"],
    },
    {
        "product_id": "gscloud_sentinel2_msi",
        "display_name_zh": "Sentinel-2 MSI 影像",
        "source": "gscloud",
        "source_product_key": "sentinel2_msi",
        "resource_type": "sentinel2_msi",
        "supported_resolutions": ["10m", "20m", "60m"],
        "temporal_requirement": "date_range",
        "spatial_coverage": "中国区域，按地理空间数据云场景记录筛选",
        "required_parameters": ["area_asset_id", "time_range"],
        "optional_parameters": ["output_name", "account_mode", "max_scenes", "cloud_max"],
        "login_or_license_requirement": "需要地理空间数据云账号登录；开始下载前需要用户确认。",
        "supported_output_format": ["zip"],
        "tool_card": "submit_commercial_download_job",
        "download_adapter": "gscloud_scene_table",
        "unsupported_scenarios": ["缺少时间范围时不能提交下载。", "具体波段分辨率取决于 Sentinel-2 原始产品。"],
        "alternatives": ["landsat8_oli_tirs"],
        "aliases": ["sentinel", "sentinel-2", "sentinel2", "哨兵", "哨兵2号"],
    },
    {
        "product_id": "gscloud_landsat8_oli_tirs",
        "display_name_zh": "Landsat 8 OLI_TIRS 卫星数字产品",
        "source": "gscloud",
        "source_product_key": "landsat8_oli_tirs",
        "resource_type": "landsat8_oli_tirs",
        "supported_resolutions": ["30m", "100m"],
        "temporal_requirement": "date_range",
        "spatial_coverage": "中国区域，按地理空间数据云场景记录筛选",
        "required_parameters": ["area_asset_id", "time_range"],
        "optional_parameters": ["output_name", "account_mode", "max_scenes", "cloud_max"],
        "login_or_license_requirement": "需要地理空间数据云账号登录；开始下载前需要用户确认。",
        "supported_output_format": ["zip"],
        "tool_card": "submit_commercial_download_job",
        "download_adapter": "gscloud_scene_table",
        "unsupported_scenarios": ["缺少时间范围时不能提交下载。", "具体波段与热红外分辨率取决于 Landsat 8 原始产品。"],
        "alternatives": ["gscloud_sentinel2_msi"],
        "aliases": ["landsat", "landsat 8", "landsat8", "oli_tirs", "oli tirs", "l8", "陆地卫星8", "陆地卫星"],
    },
]


def _with_availability(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    profile = availability_for_product(str(payload.get("product_id") or ""))
    if profile:
        payload["availability_profile"] = profile
    return payload


def list_product_catalog() -> list[dict[str, Any]]:
    products = {str(item.get("product_id") or ""): dict(item, schema_version=PRODUCT_CATALOG_VERSION, version=str(item.get("version") or "builtin"), status="enabled") for item in _PRODUCTS}
    for item in configured_products():
        if str(item.get("status") or "enabled") != "enabled":
            continue
        products[str(item.get("product_id") or "")] = dict(item, schema_version=PRODUCT_CATALOG_VERSION)
    return [_with_availability(item) for item in products.values() if item.get("product_id")]


def product_by_id(product_id: str) -> dict[str, Any] | None:
    normalized = str(product_id or "").strip()
    for item in list_product_catalog():
        if item["product_id"] == normalized:
            return item
    for item in list_product_catalog():
        if item.get("source_product_key") == normalized:
            return item
    return None


def product_catalog_context(query: str = "", *, limit: int = 8) -> list[dict[str, Any]]:
    text = str(query or "").lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in list_product_catalog():
        aliases = [str(value).lower() for value in item.get("aliases", [])]
        terms = [item["product_id"].lower(), str(item["display_name_zh"]).lower(), str(item["resource_type"]).lower(), *aliases]
        score = sum(1 for term in terms if term and term in text)
        for resolution in item.get("supported_resolutions", []):
            value = str(resolution).lower()
            compact = value.replace(" ", "")
            if value and (value in text or compact in text.replace(" ", "")):
                score += 6
        if item["product_id"] == "gscloud_sentinel2_msi" and ("sentinel" in text or "哨兵" in text):
            score += 5
        if item["resource_type"] == "dem" and ("dem" in text or "高程" in text):
            score += 1
        scored.append((score, item))
    scored.sort(key=lambda pair: (pair[0], pair[1]["product_id"]), reverse=True)
    return [item for _, item in scored[: max(1, int(limit or 1))]]
