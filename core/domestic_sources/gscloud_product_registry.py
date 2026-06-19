from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .gscloud_products import (
    LANDSAT8_OLI_TIRS,
    MOD021KM_1KM_SURFACE_REFLECTANCE,
    MODEV1F_CHINA_250M_EVI_5DAY,
    MODL1T_CHINA_1KM_LST_COMPOSITE,
    MODND1T_CHINA_500M_NDVI_10DAY,
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
    GSCloudSceneProductConfig(MODND1T_CHINA_500M_NDVI_10DAY.key, MODND1T_CHINA_500M_NDVI_10DAY.resource_type, MODND1T_CHINA_500M_NDVI_10DAY.name, "modnd1t_ndvi", "modnd1t"),
    GSCloudSceneProductConfig(MODL1T_CHINA_1KM_LST_COMPOSITE.key, MODL1T_CHINA_1KM_LST_COMPOSITE.resource_type, MODL1T_CHINA_1KM_LST_COMPOSITE.name, "modl1t_lst", "modl1t"),
    GSCloudSceneProductConfig(MODEV1F_CHINA_250M_EVI_5DAY.key, MODEV1F_CHINA_250M_EVI_5DAY.resource_type, MODEV1F_CHINA_250M_EVI_5DAY.name, "modev1t_evi", "modev1t"),
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
