from __future__ import annotations

from .base import DomesticSource


DOMESTIC_SOURCES: dict[str, DomesticSource] = {

    "tianditu": DomesticSource(
        key="tianditu",
        name="天地图",
        home_url="https://lbs.tianditu.gov.cn/",
        login_url="https://lbs.tianditu.gov.cn/",
        categories=("basemap", "geocoding", "admin", "road", "water", "place_name"),
        notes="适合作为网页底图、影像/地形底图、地名搜索、逆地理编码、政区/道路/水系等辅助要素服务入口。需要申请 Key。",
        username_env="",
        password_env="",
    ),
    "gscloud": DomesticSource(
        key="gscloud",
        name="地理空间数据云",
        home_url="https://www.gscloud.cn/",
        login_url="https://www.gscloud.cn/",
        categories=("dem", "remote_sensing", "landcover", "landsat", "modis"),
        notes="适合作为 DEM / 遥感影像类资源的国内下载入口。若网站存在验证码，请使用手动登录保存 Cookie。",
        username_env="GSCLOUD_USERNAME",
        password_env="GSCLOUD_PASSWORD",
    ),
    "cma": DomesticSource(
        key="cma",
        name="中国气象数据网 / 国家气象信息中心",
        home_url="https://data.cma.cn/",
        login_url="https://data.cma.cn/",
        categories=("precipitation", "temperature", "weather", "station"),
        notes="适合作为降水、气温、站点气象数据下载入口。实际下载流程可能需要人工选择数据集和下单。",
        username_env="CMA_USERNAME",
        password_env="CMA_PASSWORD",
    ),
    "geodata": DomesticSource(
        key="geodata",
        name="国家地球系统科学数据中心",
        home_url="https://www.geodata.cn/",
        login_url="https://www.geodata.cn/",
        categories=("precipitation", "temperature", "geoscience", "raster", "table"),
        notes="适合作为整理型地学数据集下载入口。部分数据集可直接下载，部分可能需要登录。",
        username_env="GEODATA_USERNAME",
        password_env="GEODATA_PASSWORD",
    ),
    "resdc": DomesticSource(
        key="resdc",
        name="资源环境科学与数据平台",
        home_url="https://www.resdc.cn/",
        login_url="https://www.resdc.cn/",
        categories=("boundary", "landuse", "population", "ecology", "vector"),
        notes="适合作为行政边界、土地利用、人口和生态环境数据下载入口。部分数据可能需要申请或人工确认。",
        username_env="RESDC_USERNAME",
        password_env="RESDC_PASSWORD",
    ),
}


DOMESTIC_RESOURCE_CATALOG: dict[str, dict[str, object]] = {
    "basemap": {
        "label": "天地图底图 / 注记 / 影像 / 地形",
        "default_source": "tianditu",
        "candidate_sources": ["tianditu"],
        "keywords": ["天地图", "底图", "矢量底图", "影像底图", "地形晕渲", "注记", "WMTS"],
        "typical_outputs": ["web_map", "wmts", "tile"],
    },
    "admin_feature": {
        "label": "政区/道路/水系等天地图数据 API 要素",
        "default_source": "tianditu",
        "candidate_sources": ["tianditu", "resdc", "geodata"],
        "keywords": ["政区要素", "道路要素", "水系要素", "居民地要素", "地名", "逆地理编码"],
        "typical_outputs": ["json", "geojson", "table"],
    },
    "dem": {
        "label": "DEM / 高程数据",
        "default_source": "gscloud",
        "candidate_sources": ["gscloud", "geodata"],
        "keywords": ["DEM", "高程", "地形", "SRTM", "ASTER", "GDEM"],
        "typical_outputs": ["tif", "zip", "img"],
    },
    "precipitation": {
        "label": "降水数据",
        "default_source": "cma",
        "candidate_sources": ["cma", "geodata"],
        "keywords": ["降水", "降雨", "逐日降水", "逐月降水", "precipitation"],
        "typical_outputs": ["csv", "nc", "tif", "zip"],
    },
    "temperature": {
        "label": "气温数据",
        "default_source": "cma",
        "candidate_sources": ["cma", "geodata"],
        "keywords": ["气温", "温度", "最高气温", "最低气温", "temperature"],
        "typical_outputs": ["csv", "nc", "tif", "zip"],
    },
    "boundary": {
        "label": "行政边界 / 矢量边界",
        "default_source": "resdc",
        "candidate_sources": ["resdc", "geodata"],
        "keywords": ["行政边界", "行政区划", "省界", "县界", "shp", "矢量"],
        "typical_outputs": ["shp", "geojson", "zip"],
    },
    "landuse": {
        "label": "土地利用 / 覆盖数据",
        "default_source": "resdc",
        "candidate_sources": ["resdc", "gscloud", "geodata"],
        "keywords": ["土地利用", "土地覆盖", "LUCC", "land use", "land cover"],
        "typical_outputs": ["tif", "shp", "zip"],
    },
}


def get_source(source_key: str) -> DomesticSource:
    key = str(source_key or "").strip().lower()
    if key not in DOMESTIC_SOURCES:
        raise ValueError(f"不支持的国内数据源: {source_key}。可选: {', '.join(DOMESTIC_SOURCES)}")
    return DOMESTIC_SOURCES[key]
