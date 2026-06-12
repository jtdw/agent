from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain.tools import tool

from ..data_manager import DataManager
from .auth import credential_status, open_manual_login_window, storage_state_path
from .downloader import capture_browser_download, download_direct_url, postprocess_download
from .registry import DOMESTIC_RESOURCE_CATALOG, DOMESTIC_SOURCES, get_source


def _json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def build_domestic_tools(manager: DataManager):
    @tool
    def list_domestic_data_sources(category: str = "") -> str:
        """列出已内置的国内数据源适配器和资源类型目录，例如 DEM、降水、气温、行政边界。"""
        category_key = str(category or "").strip().lower()
        sources = []
        for key, src in DOMESTIC_SOURCES.items():
            if category_key and category_key not in src.categories:
                continue
            state_path = storage_state_path(manager.workdir, src)
            status = credential_status(src)
            sources.append(
                {
                    "source_key": key,
                    "name": src.name,
                    "home_url": src.home_url,
                    "login_url": src.login_url,
                    "categories": list(src.categories),
                    "notes": src.notes,
                    "storage_state_exists": state_path.exists(),
                    **status,
                }
            )
        return _json({"resource_catalog": DOMESTIC_RESOURCE_CATALOG, "sources": sources})

    @tool
    def domestic_login_status(source_key: str = "") -> str:
        """查看国内数据源的账号环境变量和 Cookie 登录态是否存在；不会显示明文密码。"""
        keys = [source_key.strip().lower()] if source_key else list(DOMESTIC_SOURCES.keys())
        items: list[dict[str, Any]] = []
        for key in keys:
            src = get_source(key)
            state_path = storage_state_path(manager.workdir, src)
            items.append(
                {
                    **credential_status(src),
                    "storage_state_exists": state_path.exists(),
                    "home_url": src.home_url,
                    "login_url": src.login_url,
                }
            )
        return _json({"items": items})

    @tool
    def open_domestic_login_window(source_key: str, timeout_seconds: int = 300, headless: bool = False) -> str:
        """打开国内数据源登录窗口，用户手动登录/输入验证码，超时后自动保存 Cookie。适合有验证码的网站。"""
        src = get_source(source_key)
        result = open_manual_login_window(src, manager.workdir, timeout_seconds=timeout_seconds, headless=headless)
        result.pop("storage_state_path", None)
        manager.log_operation("国内数据源登录态保存", f"{src.name} -> <storage_state_path_redacted>", "download")
        return _json(result)

    @tool
    def capture_domestic_browser_download(
        source_key: str,
        start_url: str = "",
        output_name: str = "",
        timeout_seconds: int = 900,
        headless: bool = False,
        auto_load: bool = True,
    ) -> str:
        """打开国内网站浏览器窗口，复用 Cookie，等待用户手动点击一次下载，自动捕获文件、解压、加载到工作区并打包。"""
        src = get_source(source_key)
        result = capture_browser_download(
            manager=manager,
            source=src,
            start_url=start_url,
            output_name=output_name,
            timeout_seconds=timeout_seconds,
            headless=headless,
            auto_load=auto_load,
        )
        return _json(result.to_dict())

    @tool
    def download_domestic_url(
        url: str,
        source_key: str = "",
        output_name: str = "",
        auto_load: bool = True,
        timeout_seconds: int = 300,
    ) -> str:
        """下载国内数据源的直接链接；如果指定 source_key，会自动带上该数据源保存的 Cookie。下载后可自动解压/加载/打包。"""
        src = get_source(source_key) if str(source_key or "").strip() else None
        result = download_direct_url(
            manager=manager,
            url=url,
            source=src,
            output_name=output_name,
            auto_load=auto_load,
            timeout_seconds=timeout_seconds,
        )
        return _json(result.to_dict())

    @tool
    def import_domestic_downloaded_file(file_path: str, output_name: str = "", auto_load: bool = True) -> str:
        """把已经手动下载到本机的国内数据源文件导入工作区，自动解压、识别 shp/tif/csv 等并生成 zip 包。"""
        path = Path(file_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        manager._require_allowed_import_source(path)
        result = postprocess_download(manager, path, source_key="manual", output_name=output_name or path.stem, auto_load=auto_load)
        return _json(result.to_dict())

    return [
        list_domestic_data_sources,
        domestic_login_status,
        open_domestic_login_window,
        capture_domestic_browser_download,
        download_domestic_url,
        import_domestic_downloaded_file,
    ]
