from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .archive_manifest import extract_loadable_members
from .auth import load_cookies_from_storage_state, source_download_dir, storage_state_path
from .base import DomesticDownloadResult, DomesticSource
from ..data_manager import DataManager


LOADABLE_EXTS = {".shp", ".geojson", ".gpkg", ".json", ".kml", ".tif", ".tiff", ".img", ".csv", ".xlsx", ".xls", ".docx", ".txt", ".md"}
ARCHIVE_EXTS = {".zip", ".7z", ".rar"}
MAX_DIRECT_DOWNLOAD_BYTES = int(os.getenv("GIS_AGENT_MAX_DIRECT_DOWNLOAD_MB", "1000") or 1000) * 1024 * 1024


def _assert_archive_members_safe(member_names: list[str], output_dir: Path) -> None:
    root = output_dir.resolve()
    for name in member_names:
        raw = str(name or "").strip()
        if not raw:
            continue
        member_path = Path(raw)
        if member_path.is_absolute():
            raise RuntimeError(f"压缩包包含不安全路径：{raw}")
        target = (root / member_path).resolve()
        try:
            target.relative_to(root)
        except Exception:
            raise RuntimeError(f"压缩包包含不安全路径：{raw}")


def safe_extract_zip(zf: zipfile.ZipFile, output_dir: Path) -> None:
    root = output_dir.resolve()
    for member in zf.infolist():
        mode = member.external_attr >> 16
        if mode & 0o170000 == 0o120000:
            raise RuntimeError(f"Unsafe zip symlink: {member.filename}")
    _assert_archive_members_safe([member.filename for member in zf.infolist()], root)
    zf.extractall(root)


def _json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def safe_name(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace(" ", "_")
    keep = []
    for ch in text:
        if ch.isalnum() or ch in {"_", "-", "."} or "\u4e00" <= ch <= "\u9fff":
            keep.append(ch)
        else:
            keep.append("_")
    out = "".join(keep).strip("._-")
    return out or f"download_{uuid4().hex[:8]}"


def _prepare_extract_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def make_requests_session(source: DomesticSource | None = None, workdir: Path | None = None) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36 gis-dual-agent",
    })

    if source and workdir:
        state_path = storage_state_path(workdir, source)
        for cookie in load_cookies_from_storage_state(state_path):
            try:
                s.cookies.set(
                    cookie.get("name"),
                    cookie.get("value"),
                    domain=cookie.get("domain"),
                    path=cookie.get("path", "/"),
                )
            except Exception:
                continue
    return s


def infer_filename_from_url(url: str, response: requests.Response | None = None, fallback: str = "") -> str:
    if response is not None:
        cd = response.headers.get("content-disposition", "")
        # 简单兼容 filename=xxx，不做复杂 RFC 解码。
        for token in cd.split(";"):
            token = token.strip()
            if token.lower().startswith("filename="):
                name = token.split("=", 1)[1].strip().strip('"')
                if name:
                    return safe_name(name)
    path_name = Path(urlparse(url).path).name
    if path_name:
        return safe_name(path_name)
    return safe_name(fallback or f"download_{uuid4().hex[:8]}")


def download_direct_url(
    manager: DataManager,
    url: str,
    source: DomesticSource | None = None,
    output_name: str = "",
    auto_load: bool = True,
    timeout_seconds: int = 300,
) -> DomesticDownloadResult:
    if not str(url or "").lower().startswith(("http://", "https://")):
        raise ValueError("请提供有效的 http/https 下载链接。")
    session = make_requests_session(source, manager.workdir)
    target_dir = source_download_dir(manager.workdir, source.key if source else "direct")
    with session.get(url, stream=True, timeout=max(30, int(timeout_seconds))) as response:
        response.raise_for_status()
        content_length = int(response.headers.get("content-length") or 0)
        if content_length and content_length > MAX_DIRECT_DOWNLOAD_BYTES:
            raise RuntimeError(f"下载文件超过大小限制：{content_length / 1024 / 1024:.1f} MB")
        filename = safe_name(output_name) if output_name else infer_filename_from_url(url, response=response)
        target_path = target_dir / filename
        if not target_path.suffix and "." in infer_filename_from_url(url, response=response):
            target_path = target_dir / infer_filename_from_url(url, response=response)
        downloaded = 0
        with open(target_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    downloaded += len(chunk)
                    if downloaded > MAX_DIRECT_DOWNLOAD_BYTES:
                        raise RuntimeError(f"下载文件超过大小限制：{MAX_DIRECT_DOWNLOAD_BYTES // 1024 // 1024} MB")
                    f.write(chunk)

    result = postprocess_download(manager, target_path, source_key=source.key if source else "direct", output_name=output_name, auto_load=auto_load)
    result.meta.update({"url": url, "status_code": response.status_code, "content_type": response.headers.get("content-type")})
    return result


def capture_browser_download(
    manager: DataManager,
    source: DomesticSource,
    start_url: str = "",
    output_name: str = "",
    timeout_seconds: int = 900,
    headless: bool = False,
    auto_load: bool = True,
) -> DomesticDownloadResult:
    """打开浏览器复用登录态，等待用户手动点击一次下载，并捕获下载文件。

    该函数不破解验证码、不绕过权限；用户在浏览器中正常检索、选择资源、点击下载。
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "缺少 Playwright。请先执行: pip install playwright && python -m playwright install chromium"
        ) from exc

    state_path = storage_state_path(manager.workdir, source)
    target_dir = source_download_dir(manager.workdir, source.key)
    target_dir.mkdir(parents=True, exist_ok=True)
    url = start_url or source.home_url
    timeout_ms = max(30, int(timeout_seconds or 900)) * 1000

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_kwargs: dict[str, Any] = {"accept_downloads": True}
        if state_path.exists():
            context_kwargs["storage_state"] = str(state_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.bring_to_front()
        try:
            download = page.wait_for_event("download", timeout=timeout_ms)
        except PlaywrightTimeoutError as exc:
            context.storage_state(path=str(state_path))
            browser.close()
            raise TimeoutError(
                f"在 {timeout_seconds} 秒内没有捕获到下载。请确认已在浏览器中完成登录、检索并点击下载按钮；"
                "如网站有弹窗确认，请也在浏览器中确认。"
            ) from exc

        suggested = safe_name(download.suggested_filename or output_name or f"download_{uuid4().hex[:8]}")
        if output_name:
            out = safe_name(output_name)
            # 用户如果没写扩展名，保留网站建议扩展名。
            if not Path(out).suffix and Path(suggested).suffix:
                out = out + Path(suggested).suffix
            suggested = out
        target_path = target_dir / suggested
        download.save_as(str(target_path))
        context.storage_state(path=str(state_path))
        browser.close()

    return postprocess_download(manager, target_path, source_key=source.key, output_name=output_name, auto_load=auto_load)


def _extract_archive(path: Path, output_dir: Path) -> Path | None:
    suffix = path.suffix.lower()
    if suffix == ".zip" and zipfile.is_zipfile(path):
        extract_loadable_members(path, output_dir, allowed_exts=LOADABLE_EXTS, max_datasets=1, clean=True)
        return output_dir
    if suffix == ".7z":
        try:
            import py7zr  # type: ignore
        except Exception as exc:
            raise RuntimeError("解压 .7z 需要安装 py7zr：pip install py7zr") from exc
        _prepare_extract_dir(output_dir)
        with py7zr.SevenZipFile(path, mode="r") as z:
            names = z.getnames() if hasattr(z, "getnames") else []
            _assert_archive_members_safe([str(name) for name in names], output_dir)
            z.extractall(path=output_dir)
        return output_dir
    if suffix == ".rar":
        # rarfile 通常还需要系统 unrar/bsdtar。这里给出明确提示，不强行失败整个流程。
        try:
            import rarfile  # type: ignore
        except Exception as exc:
            raise RuntimeError("解压 .rar 需要安装 rarfile，并确保系统有 unrar/bsdtar。") from exc
        _prepare_extract_dir(output_dir)
        with rarfile.RarFile(path) as rf:
            infos = rf.infolist()
            for member in infos:
                is_link = getattr(member, "is_symlink", lambda: False)
                mode = int(getattr(member, "mode", getattr(member, "filemode", 0)) or 0)
                if (callable(is_link) and is_link()) or (mode & 0o170000 == 0o120000):
                    raise RuntimeError(f"Unsafe rar symlink: {member.filename}")
            _assert_archive_members_safe([str(member.filename) for member in infos], output_dir)
            rf.extractall(output_dir)
        return output_dir
    return None


def find_loadable_file(path_or_dir: Path) -> Path | None:
    if path_or_dir.is_file() and path_or_dir.suffix.lower() in LOADABLE_EXTS:
        return path_or_dir
    if not path_or_dir.exists():
        return None
    if path_or_dir.is_dir():
        # 优先 shp，其次 tif，再表格/GeoJSON。
        priority = [".shp", ".tif", ".tiff", ".geojson", ".gpkg", ".csv", ".xlsx", ".xls", ".docx", ".txt", ".md"]
        files = [p for p in path_or_dir.rglob("*") if p.is_file() and p.suffix.lower() in LOADABLE_EXTS]
        for ext in priority:
            for item in files:
                if item.suffix.lower() == ext:
                    return item
    return None


def zip_result_folder(source_path: Path, zip_path: Path) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    root = source_path if source_path.is_dir() else source_path.parent
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if source_path.is_file():
            zf.write(source_path, source_path.name)
        else:
            for file_path in source_path.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(root.parent))
    return zip_path


def postprocess_download(
    manager: DataManager,
    downloaded_path: Path,
    source_key: str,
    output_name: str = "",
    auto_load: bool = True,
) -> DomesticDownloadResult:
    downloaded_path = Path(downloaded_path)
    if not downloaded_path.exists() or downloaded_path.stat().st_size == 0:
        raise RuntimeError(f"下载文件不存在或为空: {downloaded_path}")

    base_name = safe_name(output_name or downloaded_path.stem)
    extract_dir: Path | None = None
    if downloaded_path.suffix.lower() in ARCHIVE_EXTS:
        try:
            extract_dir = manager.derived_dir / f"{base_name}_extracted"
            extract_dir = _extract_archive(downloaded_path, extract_dir)
        except Exception as exc:
            # 保留原始下载，不中断整体流程。
            manager.log_operation("国内数据源解压失败", f"{downloaded_path.name}: {exc}", "download")
            extract_dir = None

    load_candidate = find_loadable_file(extract_dir or downloaded_path)
    dataset_name: str | None = None
    auto_loaded = False
    if auto_load and load_candidate:
        try:
            dataset_name = manager.register_dataset_reference(load_candidate, name=base_name, meta={"source": "download_postprocess"})
            auto_loaded = True
        except Exception as exc:
            manager.log_operation("国内数据源自动加载失败", f"{load_candidate}: {exc}", "download")

    package_source = extract_dir or downloaded_path
    zip_path = manager.derived_dir / f"{base_name}_domestic_download.zip"
    try:
        zip_result_folder(package_source, zip_path)
    except Exception:
        zip_path = None

    manager.log_operation(
        "国内数据源下载完成",
        f"source={source_key} | file={downloaded_path} | dataset={dataset_name or '未自动加载'}",
        "download",
    )
    return DomesticDownloadResult(
        source_key=source_key,
        downloaded_path=downloaded_path,
        dataset_name=dataset_name,
        auto_loaded=auto_loaded,
        extracted_dir=extract_dir,
        zip_path=zip_path,
        message="下载完成；若 auto_loaded=false，请检查文件格式或手动上传/加载。",
        meta={
            "size_mb": round(downloaded_path.stat().st_size / 1024 / 1024, 3),
            "suffix": downloaded_path.suffix.lower(),
            "load_candidate": str(load_candidate) if load_candidate else None,
        },
    )
