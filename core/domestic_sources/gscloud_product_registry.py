from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .gscloud_products import (
    LANDSAT8_OLI_TIRS,
    MOD021KM_1KM_SURFACE_REFLECTANCE,
    MODEV1F_CHINA_250M_EVI_5DAY,
    MODL1D_CHINA_1KM_LST_DAILY,
    MODND1D_CHINA_500M_NDVI_DAILY,
    SENTINEL2_MSI,
)


@dataclass(frozen=True)
class GSCloudSceneProductConfig:
    product_key: str
    resource_type: str
    label: str
    default_output_name: str
    stage_prefix: str
    supports_preflight: bool = True


_SCENE_PRODUCTS: tuple[GSCloudSceneProductConfig, ...] = (
    GSCloudSceneProductConfig(LANDSAT8_OLI_TIRS.key, LANDSAT8_OLI_TIRS.resource_type, LANDSAT8_OLI_TIRS.name, "landsat8_oli_tirs", "landsat8"),
    GSCloudSceneProductConfig(MODND1D_CHINA_500M_NDVI_DAILY.key, MODND1D_CHINA_500M_NDVI_DAILY.resource_type, MODND1D_CHINA_500M_NDVI_DAILY.name, "modnd1d_ndvi", "modnd1d"),
    GSCloudSceneProductConfig(MODL1D_CHINA_1KM_LST_DAILY.key, MODL1D_CHINA_1KM_LST_DAILY.resource_type, MODL1D_CHINA_1KM_LST_DAILY.name, "modl1d_lst", "modl1d"),
    GSCloudSceneProductConfig(MODEV1F_CHINA_250M_EVI_5DAY.key, MODEV1F_CHINA_250M_EVI_5DAY.resource_type, MODEV1F_CHINA_250M_EVI_5DAY.name, "modev1f_evi", "modev1f"),
    GSCloudSceneProductConfig(MOD021KM_1KM_SURFACE_REFLECTANCE.key, MOD021KM_1KM_SURFACE_REFLECTANCE.resource_type, MOD021KM_1KM_SURFACE_REFLECTANCE.name, "mod021km_reflectance", "mod021km"),
    GSCloudSceneProductConfig(SENTINEL2_MSI.key, SENTINEL2_MSI.resource_type, SENTINEL2_MSI.name, "sentinel2_msi", "sentinel2"),
)


def list_scene_product_configs() -> list[GSCloudSceneProductConfig]:
    return list(_SCENE_PRODUCTS)


def iter_scene_product_configs() -> Iterable[GSCloudSceneProductConfig]:
    return iter(_SCENE_PRODUCTS)


def get_scene_product_config(value: str) -> GSCloudSceneProductConfig:
    text = str(value or "").strip().lower()
    for product in _SCENE_PRODUCTS:
        if text in {product.product_key.lower(), product.resource_type.lower()}:
            return product
    raise KeyError(f"不支持的 GSCloud 场景产品: {value}")
