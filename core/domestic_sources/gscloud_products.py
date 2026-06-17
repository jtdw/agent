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

MODND1D_CHINA_500M_NDVI_DAILY = GSCloudProduct(
    key="modnd1d_china_500m_ndvi_daily",
    name="MODND1D 中国 500M NDVI 每天产品",
    resource_type="modnd1d_ndvi_daily",
    dataset_id="343",
    pid="333",
    access_url="https://www.gscloud.cn/sources/accessdata/343?pid=333",
    aliases=("modnd1d", "ndvi", "中国 500m ndvi", "500m ndvi", "modis ndvi", "每日ndvi", "每天产品"),
    download_mode="scene_table",
)

MODL1D_CHINA_1KM_LST_DAILY = GSCloudProduct(
    key="modl1d_china_1km_lst_daily",
    name="MODL1D 中国 1KM 地表温度每天产品",
    resource_type="modl1d_lst_daily",
    dataset_id="334",
    pid="333",
    access_url="https://www.gscloud.cn/sources/accessdata/334?pid=333",
    aliases=("modl1d", "地表温度", "lst", "1km 地表温度", "1km lst", "modis 地表温度", "每天产品"),
    download_mode="scene_table",
)

MODEV1F_CHINA_250M_EVI_5DAY = GSCloudProduct(
    key="modev1f_china_250m_evi_5day",
    name="MODEV1F 中国 250M EVI 五天合成产品",
    resource_type="modev1f_evi_5day",
    dataset_id="352",
    pid="333",
    access_url="https://www.gscloud.cn/sources/accessdata/352?pid=333",
    aliases=("modev1f", "evi", "250m evi", "modis evi", "五天合成", "5天合成", "五日合成", "5day evi"),
    download_mode="scene_table",
)

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

SRTMDEMUTM_90M = GSCloudProduct(
    key="srtmdemutm_90m",
    name="SRTMDEMUTM 90M 分辨率数字高程数据产品",
    resource_type="srtmdemutm_90m",
    dataset_id="306",
    pid="302",
    access_url="https://www.gscloud.cn/sources/accessdata/306?pid=302",
    aliases=("srtmdemutm", "srtm dem utm", "srtm 90m", "srtm90", "90m dem", "90米dem", "srtm", "utm_srtm", "accessdata/306", "pid=302"),
    download_mode="tile_grid",
)


GSCLOUD_PRODUCTS = {
    LANDSAT8_OLI_TIRS.key: LANDSAT8_OLI_TIRS,
    MODND1D_CHINA_500M_NDVI_DAILY.key: MODND1D_CHINA_500M_NDVI_DAILY,
    MODL1D_CHINA_1KM_LST_DAILY.key: MODL1D_CHINA_1KM_LST_DAILY,
    MODEV1F_CHINA_250M_EVI_5DAY.key: MODEV1F_CHINA_250M_EVI_5DAY,
    MOD021KM_1KM_SURFACE_REFLECTANCE.key: MOD021KM_1KM_SURFACE_REFLECTANCE,
    SENTINEL2_MSI.key: SENTINEL2_MSI,
    SRTMDEMUTM_90M.key: SRTMDEMUTM_90M,
}


def match_gscloud_product(text: str) -> GSCloudProduct | None:
    lowered = str(text or "").lower()
    best: tuple[int, GSCloudProduct] | None = None
    for product in GSCLOUD_PRODUCTS.values():
        score = sum(len(alias) for alias in product.aliases if alias in lowered)
        if score and (best is None or score > best[0]):
            best = (score, product)
    return best[1] if best else None
