from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Literal

from .gscloud_products import (
    GSCLOUD_PRODUCTS,
    LANDSAT8_OLI_TIRS,
    MOD021KM_1KM_SURFACE_REFLECTANCE,
    MODEV1F_CHINA_250M_EVI_5DAY,
    MODL1D_CHINA_1KM_LST_DAILY,
    MODND1D_CHINA_500M_NDVI_DAILY,
    SENTINEL2_MSI,
)


RouteKind = Literal["matched", "clarify", "none"]


@dataclass(frozen=True)
class GSCloudIntentRoute:
    kind: RouteKind
    product_key: str = ""
    resource_type: str = ""
    confidence: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    clarification: str = ""


@dataclass(frozen=True)
class _IntentSpec:
    product_key: str
    resource_type: str
    aliases: tuple[str, ...]
    category_terms: tuple[str, ...] = ()


def _norm(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "").lower())


def _tokens(value: str) -> list[str]:
    raw = str(value or "").lower()
    return re.findall(r"[0-9a-zA-Z]+|[\u4e00-\u9fff]+", raw)


def _has_download_action(prompt: str) -> bool:
    normalized = _norm(prompt)
    return any(term in normalized for term in ("下载", "获取", "准备", "检索", "download", "get", "retrieve"))


def _has_region_hint(prompt: str) -> bool:
    text = str(prompt or "")
    normalized = _norm(text)
    explicit = ("成都", "成都市", "四川", "四川省", "重庆", "重庆市", "云南", "云南省", "贵州", "贵州省", "闪电河", "研究区", "区域", "流域")
    if any(term in text for term in explicit):
        return True
    return any(term in normalized for term in ("chengdu", "sichuan", "chongqing", "yunnan", "guizhou", "basin", "region", "aoi"))


def _product_aliases(product_key: str, *extra: str) -> tuple[str, ...]:
    product = GSCLOUD_PRODUCTS.get(product_key)
    base = product.aliases if product is not None else ()
    return tuple(dict.fromkeys((*base, *extra)))


INTENTS: tuple[_IntentSpec, ...] = (
    _IntentSpec(
        product_key=MODND1D_CHINA_500M_NDVI_DAILY.key,
        resource_type=MODND1D_CHINA_500M_NDVI_DAILY.resource_type,
        aliases=_product_aliases(MODND1D_CHINA_500M_NDVI_DAILY.key, "植被指数ndvi", "归一化植被指数"),
        category_terms=("ndvi", "归一化植被", "植被指数"),
    ),
    _IntentSpec(
        product_key=MODEV1F_CHINA_250M_EVI_5DAY.key,
        resource_type=MODEV1F_CHINA_250M_EVI_5DAY.resource_type,
        aliases=_product_aliases(MODEV1F_CHINA_250M_EVI_5DAY.key, "五天evi", "5天evi", "增强植被指数"),
        category_terms=("evi", "五天", "5天", "增强植被"),
    ),
    _IntentSpec(
        product_key=MODL1D_CHINA_1KM_LST_DAILY.key,
        resource_type=MODL1D_CHINA_1KM_LST_DAILY.resource_type,
        aliases=_product_aliases(MODL1D_CHINA_1KM_LST_DAILY.key, "地温", "陆表温度", "地表热"),
        category_terms=("地表温度", "地温", "lst", "温度"),
    ),
    _IntentSpec(
        product_key=MOD021KM_1KM_SURFACE_REFLECTANCE.key,
        resource_type=MOD021KM_1KM_SURFACE_REFLECTANCE.resource_type,
        aliases=_product_aliases(MOD021KM_1KM_SURFACE_REFLECTANCE.key, "mod21km", "mod021", "地表反射", "反射率"),
        category_terms=("mod021", "mod21", "反射", "反射率", "modis l1b"),
    ),
    _IntentSpec(
        product_key=SENTINEL2_MSI.key,
        resource_type=SENTINEL2_MSI.resource_type,
        aliases=_product_aliases(SENTINEL2_MSI.key, "sentinal2", "sentinal-2", "哨兵二", "哨兵2号", "s2"),
        category_terms=("sentinel", "sentinal", "哨兵", "s2", "msil2a", "msil1c"),
    ),
    _IntentSpec(
        product_key=LANDSAT8_OLI_TIRS.key,
        resource_type=LANDSAT8_OLI_TIRS.resource_type,
        aliases=_product_aliases(LANDSAT8_OLI_TIRS.key, "陆地卫星八", "landsat八", "landsat影像"),
        category_terms=("landsat", "陆地卫星", "l8", "oli"),
    ),
    _IntentSpec(
        product_key="gscloud_dem",
        resource_type="dem",
        aliases=("dem", "高程", "数字高程", "aster gdem", "gdem", "地形"),
        category_terms=("dem", "高程", "地形", "gdem"),
    ),
)


def _clarification_for(prompt: str) -> str:
    normalized = _norm(prompt)
    if any(term in normalized for term in ("植被", "植被指数")) and not any(term in normalized for term in ("ndvi", "evi")):
        return "你是想下载 NDVI 还是 EVI？如果用于植被指数时间序列，通常选 NDVI；如果需要 250M 五天合成增强植被指数，选 EVI。"
    if "遥感影像" in normalized or ("遥感" in normalized and "影像" in normalized):
        return "你是想下载 Sentinel-2 还是 Landsat 8？如果需要较新的高分辨率光学影像，通常选 Sentinel-2；如果要 Landsat 系列数据，选 Landsat 8。"
    if "modis" in normalized and not any(term in normalized for term in ("ndvi", "evi", "lst", "温度", "反射", "mod021", "mod21")):
        return "你要下载哪类 MODIS 数据？可选 NDVI、LST 地表温度、EVI 五天合成或 MOD021KM 地表反射率。"
    return ""


def _score_intent(prompt: str, spec: _IntentSpec) -> tuple[float, list[str]]:
    normalized = _norm(prompt)
    tokens = [_norm(t) for t in _tokens(prompt)]
    score = 0.0
    matched: list[str] = []

    for alias in spec.aliases:
        alias_norm = _norm(alias)
        if not alias_norm:
            continue
        if alias_norm in normalized:
            score += min(0.62, 0.28 + len(alias_norm) / 28)
            matched.append(alias)
            continue
        if tokens and max(difflib.SequenceMatcher(None, alias_norm, token).ratio() for token in tokens) >= 0.84:
            score += 0.46
            matched.append(alias)

    for term in spec.category_terms:
        term_norm = _norm(term)
        if term_norm and term_norm in normalized:
            score += 0.22
            matched.append(term)

    if _has_download_action(prompt) and matched:
        score += 0.12

    return min(score, 1.0), list(dict.fromkeys(matched))


def route_gscloud_download_intent(prompt: str) -> GSCloudIntentRoute:
    text = str(prompt or "").strip()
    if not text:
        return GSCloudIntentRoute(kind="none")

    scored = []
    for spec in INTENTS:
        score, terms = _score_intent(text, spec)
        if score > 0:
            scored.append((score, spec, terms))
    scored.sort(key=lambda item: item[0], reverse=True)

    if scored:
        best_score, best_spec, best_terms = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        if best_score >= 0.72 and best_score - second_score >= 0.12:
            if best_spec.product_key == LANDSAT8_OLI_TIRS.key and _has_download_action(text) and not _has_region_hint(text):
                return GSCloudIntentRoute(
                    kind="clarify",
                    product_key=best_spec.product_key,
                    resource_type=best_spec.resource_type,
                    confidence=round(best_score, 3),
                    matched_terms=best_terms,
                    clarification="已识别产品，但还缺少下载区域。请补充区域，例如“成都”“四川省”，或选择/上传工作区边界。",
                )
            return GSCloudIntentRoute(
                kind="matched",
                product_key=best_spec.product_key,
                resource_type=best_spec.resource_type,
                confidence=round(best_score, 3),
                matched_terms=best_terms,
            )

    clarification = _clarification_for(text)
    if clarification:
        confidence = scored[0][0] if scored else 0.5
        return GSCloudIntentRoute(kind="clarify", confidence=round(max(confidence, 0.5), 3), clarification=clarification)

    return GSCloudIntentRoute(kind="none")
