from __future__ import annotations

import os
from typing import Any, Callable

from fastapi import APIRouter, Query

from core.llm_config import check_llm_provider_health, validate_llm_config
from core.ops_config import validate_production_config


def _tianditu_layer_url(layer: str, matrix_set: str = "w") -> str:
    token = os.getenv("TIANDITU_TOKEN", "").strip()
    return (
        f"https://t{{s}}.tianditu.gov.cn/{layer}_{matrix_set}/wmts?"
        f"SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={layer}"
        f"&STYLE=default&TILEMATRIXSET={matrix_set}&FORMAT=tiles"
        f"&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}&tk={token}"
    )


def create_system_router(
    *,
    local_library_root: Callable[[], Any],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/api/status")
    def status():
        def run():
            llm_validation = validate_llm_config()
            return {
                "ok": True,
                "service": "GIS Agent Web API",
                "version": "1.4.0",
                "profile": "Web-only / LangChain 交互式 GIS 智能体 / 土壤水分融合建模 / 本地文件库 / 天地图底图与数据服务 / 国内资源下载 / 商业化账号体系",
                "desktop_removed": True,
                "local_library": {"enabled": True},
                "tianditu": {"enabled": bool(os.getenv("TIANDITU_TOKEN", "").strip())},
                "llm_status": {
                    "status": llm_validation.get("status"),
                    "provider": llm_validation.get("provider"),
                    "model": llm_validation.get("model"),
                    "role_models": llm_validation.get("role_models", {}),
                    "api_key_present": llm_validation.get("api_key_present"),
                    "intent_classifier": llm_validation.get("enable_llm_intent_classifier"),
                    "fallback_to_rule_classifier": llm_validation.get("fallback_to_rule_classifier"),
                },
            }

        return guard(run)

    @router.get("/api/llm/health")
    def llm_health(network: bool = Query(default=False)):
        return guard(lambda: check_llm_provider_health(skip_network=not network))

    @router.get("/api/ops/config")
    def ops_config():
        return guard(validate_production_config)

    @router.get("/api/tianditu/config")
    def tianditu_config():
        def run():
            token = os.getenv("TIANDITU_TOKEN", "").strip()
            default_basemap = os.getenv("TIANDITU_DEFAULT_BASEMAP", "vec").strip().lower() or "vec"
            enabled = bool(token)
            return {
                "enabled": enabled,
                "token_masked": (token[:4] + "***" + token[-4:]) if len(token) >= 8 else "",
                "default_basemap": default_basemap,
                "subdomains": ["0", "1", "2", "3", "4", "5", "6", "7"],
                "matrix_set": "w",
                "tile_url_templates": {
                    "vector": _tianditu_layer_url("vec"),
                    "vector_annotation": _tianditu_layer_url("cva"),
                    "image": _tianditu_layer_url("img"),
                    "image_annotation": _tianditu_layer_url("cia"),
                    "terrain": _tianditu_layer_url("ter"),
                    "terrain_annotation": _tianditu_layer_url("cta"),
                } if enabled else {},
                "capabilities": [
                    "WMTS 矢量底图",
                    "WMTS 影像底图",
                    "WMTS 地形晕渲",
                    "中文注记叠加",
                    "地名搜索与逆地理编码可通过后端服务继续封装",
                    "政区/道路/水系/居民地等数据 API 可作为辅助要素源",
                ],
                "setup_hint": "请在 .env 中配置 TIANDITU_TOKEN，并在天地图控制台限制浏览器端 Key 的域名 Referer。" if not enabled else "天地图 Token 已配置。",
            }

        return guard(run)

    return router
