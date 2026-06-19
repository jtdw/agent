from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GSCloudProduct:
    key: str
    name: str
    resource_type: str
    dataset_id: str
    pid: str
    access_url: str
    aliases: tuple[str, ...]
    download_mode: str


LANDSAT8_OLI_TIRS = GSCloudProduct(
    key="landsat8_oli_tirs",
    name="Landsat 8 OLI_TIRS 卫星数字产品",
    resource_type="landsat8_oli_tirs",
    dataset_id="411",
    pid="263",
    access_url="https://www.gscloud.cn/sources/accessdata/411?pid=263",
    aliases=("landsat 8", "landsat8", "oli_tirs", "oli tirs", "l8", "陆地卫星8", "landsat"),
    download_mode="scene_table",
)

MODND1T_CHINA_500M_NDVI_10DAY = GSCloudProduct(
    key="modnd1t_china_500m_ndvi_10day",
    name="MODND1T 中国 500M NDVI 旬合成产品",
    resource_type="modnd1t_ndvi_10day",
    dataset_id="346",
    pid="333",
    access_url="https://www.gscloud.cn/sources/accessdata/346?pid=333",
    aliases=("modnd1t", "modnd1d", "ndvi", "中国 500m ndvi", "500m ndvi", "modis ndvi", "旬合成", "旬产品", "10天合成", "十天合成"),
    download_mode="scene_table",
)

MODND1D_CHINA_500M_NDVI_DAILY = MODND1T_CHINA_500M_NDVI_10DAY

MODL1T_CHINA_1KM_LST_COMPOSITE = GSCloudProduct(
    key="modl1t_china_1km_lst_composite",
    name="MODLT1T 中国 1KM 地表温度旬合成产品",
    resource_type="modl1t_lst_composite",
    dataset_id="337",
    pid="333",
    access_url="https://www.gscloud.cn/sources/accessdata/337?pid=333",
    aliases=("modlt1t", "modl1t", "modl1d", "地表温度", "lst", "1km 地表温度", "1km lst", "modis 地表温度", "旬合成", "旬产品", "10天合成", "十天合成"),
    download_mode="scene_table",
)

MODL1D_CHINA_1KM_LST_DAILY = MODL1T_CHINA_1KM_LST_COMPOSITE

MODEV1T_CHINA_250M_EVI_10DAY = GSCloudProduct(
    key="modev1t_china_250m_evi_10day",
    name="MODEV1T 中国 250M EVI 旬合成产品",
    resource_type="modev1t_evi_10day",
    dataset_id="353",
    pid="333",
    access_url="https://www.gscloud.cn/sources/accessdata/353?pid=333",
    aliases=("modev1t", "modev1f", "evi", "250m evi", "modis evi", "旬合成", "旬产品", "10天合成", "十天合成"),
    download_mode="scene_table",
)

MODEV1F_CHINA_250M_EVI_5DAY = MODEV1T_CHINA_250M_EVI_10DAY

MOD021KM_1KM_SURFACE_REFLECTANCE = GSCloudProduct(
    key="mod021km_1km_surface_reflectance",
    name="MOD021KM 1KM 地表反射率",
    resource_type="mod021km_surface_reflectance",
    dataset_id="293",
    pid="291",
    access_url="https://www.gscloud.cn/sources/accessdata/293?pid=291",
    aliases=("mod021km", "modis l1b", "modisl1b", "1km 地表反射率", "地表反射率", "surface reflectance", "1km reflectance"),
    download_mode="scene_table",
)

SENTINEL2_MSI = GSCloudProduct(
    key="sentinel2_msi",
    name="Sentinel-2",
    resource_type="sentinel2_msi",
    dataset_id="448",
    pid="446",
    access_url="https://www.gscloud.cn/sources/accessdata/448?pid=446",
    aliases=("sentinel-2", "sentinel2", "sentinel 2", "s2 msi", "s2c", "s2a", "s2b", "msil2a", "msil1c", "哨兵2", "哨兵-2"),
    download_mode="scene_table",
)


GSCLOUD_PRODUCTS = {
    LANDSAT8_OLI_TIRS.key: LANDSAT8_OLI_TIRS,
    MODND1T_CHINA_500M_NDVI_10DAY.key: MODND1T_CHINA_500M_NDVI_10DAY,
    MODL1T_CHINA_1KM_LST_COMPOSITE.key: MODL1T_CHINA_1KM_LST_COMPOSITE,
    MODEV1T_CHINA_250M_EVI_10DAY.key: MODEV1T_CHINA_250M_EVI_10DAY,
    MOD021KM_1KM_SURFACE_REFLECTANCE.key: MOD021KM_1KM_SURFACE_REFLECTANCE,
    SENTINEL2_MSI.key: SENTINEL2_MSI,
}


def match_gscloud_product(text: str) -> GSCloudProduct | None:
    lowered = str(text or "").lower()
    best: tuple[int, GSCloudProduct] | None = None
    for product in GSCLOUD_PRODUCTS.values():
        score = sum(len(alias) for alias in product.aliases if alias in lowered)
        if score and (best is None or score > best[0]):
            best = (score, product)
    return best[1] if best else None
