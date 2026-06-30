from __future__ import annotations

import json
import os
import shutil
import ipaddress
import socket
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import requests
from langchain.tools import tool

from .data_manager import DataManager
from .domestic_sources import DOMESTIC_RESOURCE_CATALOG, DOMESTIC_SOURCES, build_domestic_tools
from .commercial import build_commercial_tools


def _json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _guess_direct_resource_type(text: str) -> str:
    lower = str(text or "").lower()
    if any(k in lower for k in ["dem", "高程", "地形", "aster", "srtm"]):
        return "dem"
    if any(k in lower for k in ["降水", "降雨", "precip", "rain"]):
        return "precipitation"
    if any(k in lower for k in ["气温", "温度", "temperature"]):
        return "temperature"
    if any(k in lower for k in ["行政", "边界", "boundary", "shp", "区划"]):
        return "boundary"
    if any(k in lower for k in ["土地利用", "土地覆盖", "lucc", "landuse", "land cover"]):
        return "landuse"
    return "other"


def validate_public_http_url(url: str) -> str:
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("请提供有效的 http/https 下载链接。")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise ValueError("不允许下载 localhost 地址。")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"无法解析下载域名: {host}") from exc
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    if not addresses:
        raise ValueError(f"无法解析下载域名: {host}")
    for address in addresses:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified:
            raise ValueError("不允许下载内网、回环、链路本地或保留地址。")
    return text


def _download_binary(url: str, target_path: Path, timeout: int = 120) -> None:
    url = validate_public_http_url(url)
    max_bytes = int(os.getenv("GIS_AGENT_MAX_DIRECT_DOWNLOAD_MB", "1000") or 1000) * 1024 * 1024
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        content_length = int(r.headers.get("content-length") or 0)
        if content_length and content_length > max_bytes:
            raise RuntimeError(f"下载文件超过大小限制：{content_length / 1024 / 1024:.1f} MB")
        downloaded = 0
        with target_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise RuntimeError(f"下载文件超过大小限制：{max_bytes // 1024 // 1024} MB")
                    f.write(chunk)


def get_export_task_overview(manager: DataManager, refresh: bool = False, limit: int = 8) -> dict[str, Any]:
    """Compatibility shim kept for older service code.

    The project has removed the old cloud-export backend. This function now returns an
    empty local-task overview instead of referencing any third-party cloud runtime.
    """
    return {
        "enabled": False,
        "backend": "domestic_sources_and_local_library",
        "message": "当前版本已移除旧云端导出后端；请使用本地文件库、国内数据源或地理空间数据云商业任务。",
        "items": [],
        "limit": limit,
    }


def build_resource_tools(manager: DataManager):
    @tool
    def download_backend_status() -> str:
        """检查当前数据获取能力，包括本地文件库、国内数据源、天地图配置和商业化下载任务。"""
        local_library_dir = Path(os.getenv("GIS_AGENT_LOCAL_LIBRARY_DIR", str(manager.workdir.parent / "local_library"))).expanduser()
        tdt_token = os.getenv("TIANDITU_TOKEN", "").strip()
        payload = {
            "local_library": {
                "enabled": True,
                "exists": local_library_dir.exists(),
            },
            "tianditu": {
                "enabled": bool(tdt_token),
                "token_masked": (tdt_token[:4] + "***" + tdt_token[-4:]) if len(tdt_token) >= 8 else "",
                "uses": ["网页底图", "影像底图", "地形晕渲", "地名搜索", "逆地理编码", "政区/道路/水系等数据 API 辅助查询"],
            },
            "domestic_sources": {key: {
                "name": src.name,
                "home_url": src.home_url,
                "categories": list(src.categories),
                "notes": src.notes,
            } for key, src in DOMESTIC_SOURCES.items()},
            "resource_catalog": DOMESTIC_RESOURCE_CATALOG,
            "recommendation": "优先顺序：本地文件库 → 用户已保存登录态的国内数据源 → 付费用户平台账号池 → 用户提供直链。",
        }
        return _json(payload)

    @tool
    def list_remote_resource_catalog(category: str = "") -> str:
        """列出当前内置的数据资源目录；以本地文件库和国内数据源为主。"""
        category = str(category or "").strip().lower()
        items = []
        for key, spec in DOMESTIC_RESOURCE_CATALOG.items():
            if category and category not in {key, str(spec.get("label", "")).lower()}:
                continue
            items.append({"resource_key": key, **spec})
        if not items:
            raise ValueError(f"没有找到 category={category} 的资源模板。可选: {', '.join(DOMESTIC_RESOURCE_CATALOG)}")
        return _json({"count": len(items), "items": items})

    @tool
    def download_admin_boundary(
        country: str,
        area_name: str = "",
        adm_level: str = "ADM1",
        output_name: str = "",
        output_format: str = "shp",
    ) -> str:
        """登记行政区边界需求。实际边界优先从本地文件库或国内数据源导入，避免自动使用境外云数据源。"""
        request = {
            "country": country,
            "area_name": area_name,
            "adm_level": adm_level,
            "output_name": output_name or f"{country}_{area_name or adm_level}_boundary",
            "output_format": output_format,
            "recommended_actions": [
                "先在本地文件库搜索行政区划/边界数据并导入当前工作区。",
                "若本地文件库没有，再使用 RESDC、国家地球系统科学数据中心或天地图数据 API 查询边界相关资源。",
                "若用户已手动下载 shp/zip/geojson，可用 load_dataset 或上传入口直接载入。",
            ],
        }
        manager.log_operation("行政区边界需求登记", f"{country} {area_name} {adm_level}", "download")
        return _json(request)

    @tool
    def download_remote_raster(
        resource_key: str,
        region_dataset: str,
        output_name: str,
        start_date: str = "",
        end_date: str = "",
        reducer: str = "",
        scale: int = 0,
        crs: str = "",
    ) -> str:
        """登记栅格下载需求。实际下载由本地文件库、国内数据源或商业化任务系统完成。"""
        resource_type = _guess_direct_resource_type(resource_key)
        payload = {
            "ok": False,
            "resource_key": resource_key,
            "resource_type": resource_type,
            "region_dataset": region_dataset,
            "output_name": output_name,
            "start_date": start_date or None,
            "end_date": end_date or None,
            "scale": scale or None,
            "crs": crs or None,
            "message": "当前版本已移除旧云端栅格直下载后端。请改用本地文件库、国内数据源登录态、平台账号池任务，或提供可下载直链。",
            "next_steps": [
                "在本地文件库中搜索 DEM、降水、气温或遥感产品。",
                "如果需要地理空间数据云数据，调用商业化下载任务并使用 own/platform 账号模式。",
                "如果用户已给出 http/https 直链，调用 download_file_from_url。",
            ],
        }
        manager.log_operation("栅格下载需求登记", f"{resource_key} -> {output_name}", "download")
        return _json(payload)

    @tool
    def list_export_tasks(limit: int = 8, refresh: bool = False) -> str:
        """列出当前外部下载/导出任务概览。旧云端导出已移除，仅返回兼容信息。"""
        return _json(get_export_task_overview(manager, refresh=refresh, limit=limit))

    @tool
    def query_export_task_status(task_id: str = "", dataset_name: str = "", latest: bool = False, refresh: bool = True) -> str:
        """查询旧云端导出任务兼容接口。当前建议使用商业下载任务列表查询。"""
        return _json({
            "enabled": False,
            "task_id": task_id,
            "dataset_name": dataset_name,
            "latest": latest,
            "message": "当前版本已移除旧云端导出任务。请查询 /api/downloads/jobs 或使用商业下载任务工具。",
        })

    @tool
    def download_file_from_url(url: str, output_name: str = "", auto_load: bool = True) -> str:
        """从直接下载链接获取文件到本地工作区；若 auto_load=true，则自动识别并加载 zip/shp/tif/csv/docx 等资源。"""
        if not url or not str(url).strip().lower().startswith(("http://", "https://")):
            raise ValueError("请提供有效的 http/https 下载链接。")
        filename = output_name.strip() if output_name else Path(str(url).split("?")[0]).name
        if not filename:
            filename = f"download_{uuid4().hex[:8]}"
        target_path = manager.temp_dir / filename
        _download_binary(url, target_path)

        loaded_name = None
        if auto_load:
            try:
                loaded_name = manager.load_path(str(target_path), name=Path(filename).stem)
            except Exception:
                loaded_name = None

        manager.log_operation("URL 下载", f"{url} -> {target_path.name}", "download")
        payload: dict[str, Any] = {
            "path": str(target_path),
            "auto_loaded": bool(loaded_name),
            "dataset_name": loaded_name,
        }
        if zipfile.is_zipfile(target_path):
            payload["is_zip"] = True
        return _json(payload)

    return [
        download_backend_status,
        list_remote_resource_catalog,
        download_admin_boundary,
        download_remote_raster,
        list_export_tasks,
        query_export_task_status,
        download_file_from_url,
    ] + build_domestic_tools(manager) + build_commercial_tools(manager)
