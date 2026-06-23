from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..admin_boundary import clean_admin_region_query, extract_local_admin_boundary
from ..data_manager import DataManager
from .archive_manifest import extract_loadable_members
from .base import DomesticDownloadResult, DomesticSource
from .downloader import find_loadable_file, postprocess_download, safe_extract_zip, safe_name, zip_result_folder
from .gscloud_download_recovery import recover_gscloud_download_from_error_page
from .registry import get_source


GSCLOUD_HOME = "https://www.gscloud.cn/"
_SHANDIAN_BOUNDARY_FILENAMES = ("shandianhe_basin_boundary_full.zip", "shandianhe_basin_boundary.zip")
_SHANDIAN_BOUNDARY_DATASET_NAME = "shandianhe_basin_boundary"
# 你截图里的 ASTER GDEM 30M 访问数据页。
GSCLOUD_ASTER_GDEM30_ACCESS_URL = "https://www.gscloud.cn/sources/accessdata/310?pid=1"
GSCLOUD_DEM_INDEX_URL = "https://www.gscloud.cn/sources/index?pid=1&rootid=1&title=DEM&sort=priority&page=1"

# 常见产品页。后续你可以继续补充实际 id。
GSCLOUD_DEM_DATASETS: dict[str, dict[str, Any]] = {
    "aster_gdem_30m": {
        "dataset_id": "310",
        "name": "ASTER GDEM 30M 分辨率数字高程数据",
        "access_url": GSCLOUD_ASTER_GDEM30_ACCESS_URL,
        "file_pattern": "ASTGTM_N{lat:02d}E{lon:03d}.img.zip",
    },
    "gdemv2_30m": {
        # 这个 id 来自你截图底部状态栏 accessdata/421?pid=1；如页面变化，可在调用时覆盖 dataset_id。
        "dataset_id": "421",
        "name": "GDEMV2 30M 分辨率数字高程数据",
        "access_url": "https://www.gscloud.cn/sources/accessdata/421?pid=1",
        "file_pattern": "ASTGTM_N{lat:02d}E{lon:03d}.img.zip",
    },
}


GSCLOUD_DEM_DATASETS.update(
    {
        "aster_gdem_30m": {
            **GSCLOUD_DEM_DATASETS.get("aster_gdem_30m", {}),
            "pid": "1",
            "tile_scheme": "astgtm_1deg",
        },
        "gdemv2_30m": {
            **GSCLOUD_DEM_DATASETS.get("gdemv2_30m", {}),
            "pid": "1",
            "tile_scheme": "astgtm_1deg",
        },
        "srtmdemutm_90m": {
            "dataset_id": "306",
            "pid": "302",
            "name": "SRTMDEMUTM 90M 数字高程数据",
            "access_url": "https://www.gscloud.cn/sources/accessdata/306?pid=302",
            "file_pattern": "utm_srtm_{strip:02d}_{row:02d}.img.zip",
            "tile_scheme": "srtm_utm_5deg",
        },
    }
)


def _json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "缺少 Playwright。请先执行: pip install playwright && python -m playwright install chromium"
        ) from exc
    return sync_playwright, PlaywrightTimeoutError

def _launch_visible_browser(p, headless: bool = False):
    """启动一个尽量能在 Windows 桌面前台显示的浏览器。

    默认使用 Playwright 自带 Chromium；如果设置环境变量
    GSCLOUD_BROWSER_CHANNEL=msedge 或 chrome，会优先用本机 Edge/Chrome。
    """
    import os

    channel = os.getenv("GSCLOUD_BROWSER_CHANNEL", "").strip()
    launch_kwargs: dict[str, Any] = {
        "headless": bool(headless),
        "args": [
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    if channel:
        launch_kwargs["channel"] = channel

    try:
        return p.chromium.launch(**launch_kwargs)
    except Exception:
        # 如果用户设置了 msedge/chrome 但本机 Playwright 找不到对应 channel，则回退到自带 Chromium。
        if "channel" in launch_kwargs:
            launch_kwargs.pop("channel", None)
            return p.chromium.launch(**launch_kwargs)
        raise


def _try_open_gscloud_login(page) -> dict[str, Any]:
    """尽量把地理空间数据云的登录入口点开。

    GSCloud 首页右上角通常是“登录/注册”。如果已登录，页面会显示用户名和“注销”，
    此时不需要再弹出登录页。
    """
    clicked = False
    notes: list[str] = []
    login_selectors = [
        "text=登录/注册",
        "text=登录",
        "text=立刻登录",
        "a:has-text('登录/注册')",
        "a:has-text('登录')",
        "button:has-text('登录')",
    ]
    for selector in login_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible(timeout=1500):
                loc.click(timeout=3000)
                clicked = True
                notes.append(f"clicked {selector}")
                page.wait_for_timeout(1200)
                break
        except Exception as exc:
            notes.append(f"skip {selector}: {exc.__class__.__name__}")

    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        url = page.url
    except Exception:
        url = ""

    return {"clicked_login": clicked, "page_title": title, "page_url": url, "notes": notes[:6]}


def gscloud_state_dir(workdir: Path) -> Path:
    path = Path(workdir) / "domestic_auth"
    path.mkdir(parents=True, exist_ok=True)
    return path


def gscloud_user_state_path(workdir: Path, user_id: str, source_key: str = "gscloud") -> Path:
    user = safe_name(user_id or "anonymous")
    return gscloud_state_dir(workdir) / f"user_{user}_{source_key}_storage_state.json"


def gscloud_platform_state_path(workdir: Path, account_id: str, source_key: str = "gscloud") -> Path:
    account = safe_name(account_id or "platform")
    return gscloud_state_dir(workdir) / f"platform_{account}_{source_key}_storage_state.json"


def open_login_and_save_state(
    workdir: Path,
    state_path: str | Path,
    timeout_seconds: int = 300,
    headless: bool = False,
    start_url: str = GSCLOUD_HOME,
    status_path: str | Path = "",
) -> dict[str, Any]:
    """打开地理空间数据云，让操作者手动登录并保存 Cookie。

    关键修复：
    - 不再只在最后一次性保存 Cookie，而是在等待期间每隔数秒保存一次；
    - 即使用户提前关闭浏览器，只要之前已经保存过 storage_state，也返回成功；
    - Playwright 只在独立登录 worker 中运行，避免主聊天请求被 300 秒等待阻塞。
    """
    sync_playwright, _ = _ensure_playwright()
    from .gscloud_reliability import inspect_storage_state
    state_path = Path(state_path)
    status_file = Path(status_path) if status_path else None
    state_path.parent.mkdir(parents=True, exist_ok=True)
    timeout_seconds = max(30, int(timeout_seconds or 300))

    def close_requested() -> bool:
        if not status_file or not status_file.exists():
            return False
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            return bool(data.get("close_requested"))
        except Exception:
            return False

    launch_info: dict[str, Any] = {
        "browser_opened": False,
        "clicked_login": False,
        "page_url": "",
        "page_title": "",
        "periodic_saved": False,
        "last_save_at": "",
        "closed_early": False,
        "login_detected": False,
        "close_requested": False,
        "save_errors": [],
    }

    last_error: str = ""
    login_detected = False
    with sync_playwright() as p:
        browser = _launch_visible_browser(p, headless=headless)
        launch_info["browser_opened"] = True
        kwargs: dict[str, Any] = {"accept_downloads": True, "no_viewport": True}
        if state_path.exists():
            kwargs["storage_state"] = str(state_path)
        context = browser.new_context(**kwargs)
        page = context.new_page()
        page.goto(start_url or GSCLOUD_HOME, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.wait_for_timeout(1200)
        login_info = _try_open_gscloud_login(page)
        launch_info.update(login_info)

        deadline = time.time() + timeout_seconds
        # 周期性保存，避免用户已经登录但主程序还要等完整 300 秒；也避免提前关浏览器后完全丢失 Cookie。
        while time.time() < deadline:
            try:
                context.storage_state(path=str(state_path))
                launch_info["periodic_saved"] = True
                launch_info["last_save_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                health = inspect_storage_state(state_path)
                if health.get("ok"):
                    login_detected = True
                    launch_info["login_detected"] = True
                    break
                if close_requested():
                    launch_info["close_requested"] = True
                    break
            except Exception as exc:
                last_error = str(exc)
                launch_info["save_errors"].append(last_error[:200])
                # 如果用户提前关闭浏览器，但已经有 storage_state 文件，就不要判失败。
                health = inspect_storage_state(state_path) if state_path.exists() else {"ok": False}
                if health.get("ok"):
                    launch_info["closed_early"] = True
                    launch_info["login_detected"] = True
                    login_detected = True
                    break
                raise RuntimeError("login_window_closed_before_valid_cookie") from exc
            for _ in range(5):
                if close_requested():
                    launch_info["close_requested"] = True
                    break
                time.sleep(1)
            if launch_info.get("close_requested"):
                break

        try:
            context.storage_state(path=str(state_path))
            launch_info["periodic_saved"] = True
            launch_info["last_save_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            health = inspect_storage_state(state_path)
            if health.get("ok"):
                login_detected = True
                launch_info["login_detected"] = True
        except Exception as exc:
            last_error = str(exc)
            launch_info["save_errors"].append(last_error[:200])
            health = inspect_storage_state(state_path) if state_path.exists() else {"ok": False}
            if health.get("ok"):
                login_detected = True
                launch_info["login_detected"] = True
                launch_info["closed_early"] = True
            else:
                raise
        try:
            browser.close()
        except Exception:
            pass

    final_health = inspect_storage_state(state_path, include_path=True)
    if not login_detected or not final_health.get("ok"):
        raise TimeoutError(f"GSCloud login did not produce a valid cookie: {final_health.get('reason') or 'unknown'}")

    return {
        "source_key": "gscloud",
        "state_path": str(state_path),
        "exists": state_path.exists(),
        "timeout_seconds": timeout_seconds,
        "headless": bool(headless),
        "launch_info": launch_info,
        "last_error": last_error,
        "message": (
            "已保存地理空间数据云登录状态。该版本会后台运行，不阻塞对话；"
            "登录后可等待几秒再继续提交下载任务。若手动关闭浏览器，只要已保存 Cookie，也可以继续使用。"
        ),
    }


def _new_context(browser, storage_state_path: str | Path = ""):
    kwargs: dict[str, Any] = {"accept_downloads": True}
    if storage_state_path and Path(storage_state_path).exists():
        kwargs["storage_state"] = str(storage_state_path)
    return browser.new_context(**kwargs)


def _save_download(download, target_dir: Path, output_name: str = "") -> Path:
    suggested = safe_name(download.suggested_filename or f"gscloud_{uuid4().hex[:8]}")
    filename = suggested
    if output_name:
        base = safe_name(output_name)
        suffixes = "".join(Path(suggested).suffixes)
        if not suffixes:
            suffixes = Path(suggested).suffix
        filename = base + (suffixes if suffixes and not base.endswith(suffixes) else "")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    if target_path.exists():
        stem = target_path.stem
        suffix = "".join(target_path.suffixes) or target_path.suffix
        target_path = target_dir / f"{stem}_{datetime.now().strftime('%H%M%S')}{suffix}"
    download.save_as(str(target_path))
    return target_path


def extract_astgtm_tile_id_from_name(name: str | Path) -> str:
    """从地理空间数据云下载文件名中提取 ASTER GDEM 分幅编号。"""
    text = Path(str(name)).name.upper()
    m = re.search(r"ASTGTM_[NS]\d{2}[EW]\d{3}", text)
    return m.group(0) if m else ""


def validate_gscloud_tile_downloads(
    downloaded: list[Path],
    expected_tile_ids: list[str] | None = None,
    require_all: bool = False,
) -> dict[str, Any]:
    """校验用户/自动流程下载的文件是否属于预期分幅。

    这一步是商业版必须的保护：
    - 用户手动下载了错误分幅时，不再把任务标记为“四川 DEM 已完成”；
    - 自动分幅下载缺少某些分幅时，不再误报完整成功。
    """
    expected = [str(x).strip().upper() for x in (expected_tile_ids or []) if str(x).strip()]
    expected_set = set(expected)
    downloaded_items: list[dict[str, Any]] = []
    downloaded_tile_ids: list[str] = []
    unknown_files: list[str] = []
    unexpected: list[str] = []

    for path in downloaded:
        tile_id = extract_astgtm_tile_id_from_name(path.name)
        item = {"file": str(path), "filename": path.name, "tile_id": tile_id}
        downloaded_items.append(item)
        if tile_id:
            downloaded_tile_ids.append(tile_id)
            if expected_set and tile_id not in expected_set:
                unexpected.append(tile_id)
        else:
            unknown_files.append(path.name)

    downloaded_set = set(downloaded_tile_ids)
    missing = [x for x in expected if x not in downloaded_set]
    valid = not unexpected and not unknown_files and (not require_all or not missing)
    return {
        "valid": bool(valid),
        "expected_tile_ids": expected,
        "expected_count": len(expected),
        "downloaded_items": downloaded_items,
        "downloaded_tile_ids": downloaded_tile_ids,
        "downloaded_count": len(downloaded_tile_ids),
        "unexpected_tile_ids": sorted(set(unexpected)),
        "unexpected_count": len(set(unexpected)),
        "unknown_files": unknown_files,
        "missing_tile_ids": missing,
        "missing_count": len(missing),
        "require_all": bool(require_all),
    }


def assert_valid_gscloud_tile_downloads(
    downloaded: list[Path],
    expected_tile_ids: list[str] | None = None,
    require_all: bool = False,
) -> dict[str, Any]:
    validation = validate_gscloud_tile_downloads(downloaded, expected_tile_ids=expected_tile_ids, require_all=require_all)
    if not validation["valid"]:
        parts: list[str] = []
        if validation["unexpected_tile_ids"]:
            parts.append("下载了不属于目标区域的分幅：" + ", ".join(validation["unexpected_tile_ids"][:20]))
        if validation["unknown_files"]:
            parts.append("无法从文件名识别 ASTGTM 分幅编号：" + ", ".join(validation["unknown_files"][:10]))
        if validation["require_all"] and validation["missing_tile_ids"]:
            parts.append("目标区域分幅尚未全部下载，缺少：" + ", ".join(validation["missing_tile_ids"][:30]))
        detail = "；".join(parts) or "下载文件未通过分幅校验。"
        raise RuntimeError(
            detail
            + " 请按系统生成的分幅清单下载；商业任务不会把错误或不完整分幅标记为完成。"
        )
    return validation


def capture_gscloud_downloads(
    manager: DataManager,
    start_url: str = GSCLOUD_ASTER_GDEM30_ACCESS_URL,
    storage_state_path: str | Path = "",
    output_name: str = "",
    max_downloads: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = False,
    auto_load: bool = True,
    expected_tile_ids: list[str] | None = None,
    require_all_expected: bool = False,
) -> dict[str, Any]:
    """打开地理空间数据云页面，等待操作者点击下载，捕获 1 个或多个下载文件。

    适合你截图里的流程：进入 accessdata/310 页面后，用户可以筛选或直接点击下载图标，
    文件名例如 ASTGTM_N00E026.img.zip。
    """
    sync_playwright, PlaywrightTimeoutError = _ensure_playwright()
    src = get_source("gscloud")
    target_dir = Path(manager.workdir) / "domestic_downloads" / "gscloud"
    target_dir.mkdir(parents=True, exist_ok=True)
    max_downloads = max(1, int(max_downloads or 1))
    timeout_ms = max(30, int(timeout_seconds or 1800)) * 1000
    start_url = start_url or GSCLOUD_ASTER_GDEM30_ACCESS_URL

    downloaded: list[Path] = []
    with sync_playwright() as p:
        browser = _launch_visible_browser(p, headless=headless)
        context = _new_context(browser, storage_state_path)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        page.bring_to_front()
        for idx in range(max_downloads):
            try:
                download = page.wait_for_event("download", timeout=timeout_ms if idx == 0 else 45_000)
            except PlaywrightTimeoutError:
                if idx == 0:
                    context.storage_state(path=str(storage_state_path)) if storage_state_path else None
                    browser.close()
                    raise TimeoutError(
                        f"在 {timeout_seconds} 秒内没有捕获到下载。请确认已登录地理空间数据云，并在页面中点击下载按钮。"
                    )
                break
            name = output_name if max_downloads == 1 else f"{output_name or 'gscloud_dem'}_{idx+1:03d}"
            downloaded.append(_save_download(download, target_dir, name))
        if storage_state_path:
            context.storage_state(path=str(storage_state_path))
        browser.close()

    validation = None
    if expected_tile_ids:
        validation = assert_valid_gscloud_tile_downloads(
            downloaded, expected_tile_ids=expected_tile_ids, require_all=require_all_expected
        )
    result = _postprocess_gscloud_files(manager, downloaded, src, output_name=output_name, auto_load=auto_load)
    if validation:
        result["tile_validation"] = validation
    return result


def _postprocess_gscloud_files(
    manager: DataManager,
    downloaded: list[Path],
    source: DomesticSource,
    output_name: str = "",
    auto_load: bool = True,
) -> dict[str, Any]:
    if not downloaded:
        raise RuntimeError("没有捕获到任何下载文件。")
    if len(downloaded) == 1:
        result = postprocess_download(
            manager=manager,
            downloaded_path=downloaded[0],
            source_key=source.key,
            output_name=output_name or downloaded[0].stem,
            auto_load=auto_load,
        ).to_dict()
        result["downloads"] = [str(p) for p in downloaded]
        result["download_count"] = 1
        return result

    base = safe_name(output_name or "gscloud_batch")
    bundle_dir = manager.derived_dir / f"{base}_gscloud_batch"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    imported: list[dict[str, Any]] = []
    for i, path in enumerate(downloaded, start=1):
        item_dir = bundle_dir / path.stem
        extracted_members: list[str] = []
        if path.suffix.lower() == ".zip" and zipfile.is_zipfile(path):
            _, _, extracted_members = extract_loadable_members(path, item_dir, max_datasets=1, clean=True)
        candidate = find_loadable_file(item_dir if item_dir.exists() else path)
        dataset_name = None
        if auto_load and candidate:
            try:
                dataset_name = manager.register_dataset_reference(candidate, name=f"{base}_{i:03d}", meta={"source": "gscloud_batch", "source_archive": str(path)})
            except Exception as exc:
                manager.log_operation("地理空间数据云批量导入失败", f"{candidate}: {exc}", "download")
        imported.append({"file": str(path), "candidate": str(candidate) if candidate else None, "dataset_name": dataset_name, "extracted_members": extracted_members})

    zip_path = manager.derived_dir / f"{base}_gscloud_batch.zip"
    zip_result_folder(bundle_dir, zip_path)
    manager.log_operation("地理空间数据云批量下载完成", f"{len(downloaded)} 个文件 -> {zip_path}", "download")
    return DomesticDownloadResult(
        source_key=source.key,
        downloaded_path=bundle_dir,
        dataset_name=imported[0].get("dataset_name") if imported else None,
        auto_loaded=any(bool(x.get("dataset_name")) for x in imported),
        extracted_dir=bundle_dir,
        zip_path=zip_path,
        message="已捕获多个地理空间数据云下载文件，并完成解压/入库/打包。",
        meta={"items": imported, "download_count": len(downloaded)},
    ).to_dict()


def _fill_data_id_filter(page, tile_id: str) -> bool:
    """尝试在 accessdata 页面填写“输入数据标识”筛选框。失败时返回 False。"""
    tile_id = str(tile_id or "").strip()
    if not tile_id:
        return False
    selectors = [
        "input[placeholder*='数据标识']",
        "input[placeholder*='标识']",
        "input[ng-model*='data']",
    ]
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() > 0:
                item = loc.first
                item.fill(tile_id)
                item.press("Enter")
                page.wait_for_timeout(1800)
                return True
        except Exception:
            continue
    return False


def _click_download_in_row(page, tile_id: str) -> bool:
    """尝试点击包含 tile_id 的表格行里的下载按钮。页面结构变化时可能失败。"""
    tile_id = str(tile_id or "").strip()
    if not tile_id:
        return False
    row = page.locator("tr", has_text=tile_id).first
    try:
        row.wait_for(timeout=10_000)
    except Exception:
        return False

    # 先找标题/文本含“下载”的元素。
    candidates = [
        row.locator("[title*='下载']"),
        row.locator("a:has-text('下载')"),
        row.locator("button:has-text('下载')"),
        row.locator("i[class*='download']"),
        row.locator("span[class*='download']"),
        row.locator("a, button, i, span").nth(1),  # 你截图里操作列通常是 信息/下载/收藏，下载是第二个。
    ]
    for loc in candidates:
        try:
            if loc.count() > 0:
                loc.first.click()
                return True
        except Exception:
            continue
    return False


def auto_download_gscloud_tiles(
    manager: DataManager,
    tile_ids: list[str],
    dataset_id: str = "310",
    storage_state_path: str | Path = "",
    output_name: str = "",
    timeout_seconds: int = 1800,
    headless: bool = False,
    auto_load: bool = True,
) -> dict[str, Any]:
    """尝试按数据标识自动下载 ASTER/GDEM 分幅。

    说明：该函数依赖页面筛选框和下载按钮结构。若页面改版或按钮选择失败，
    返回错误后请使用 capture_gscloud_downloads 让操作者手动点击下载。
    """
    tile_ids = [x.strip() for x in tile_ids if str(x or "").strip()]
    if not tile_ids:
        raise ValueError("请提供至少一个数据标识，例如 ASTGTM_N30E103。")
    sync_playwright, PlaywrightTimeoutError = _ensure_playwright()
    start_url = f"https://www.gscloud.cn/sources/accessdata/{dataset_id}?pid=1"
    target_dir = Path(manager.workdir) / "domestic_downloads" / "gscloud"
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    errors: list[str] = []
    timeout_ms = max(30, int(timeout_seconds or 1800)) * 1000

    with sync_playwright() as p:
        browser = _launch_visible_browser(p, headless=headless)
        context = _new_context(browser, storage_state_path)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        page.bring_to_front()
        for tile_id in tile_ids:
            try:
                _fill_data_id_filter(page, tile_id)
                with page.expect_download(timeout=timeout_ms) as dl_info:
                    clicked = _click_download_in_row(page, tile_id)
                    if not clicked:
                        raise RuntimeError(f"未找到 {tile_id} 对应行的下载按钮。")
                download = dl_info.value
                downloaded.append(_save_download(download, target_dir, tile_id))
            except PlaywrightTimeoutError:
                recovered = recover_gscloud_download_from_error_page(
                    page,
                    timeout_ms=timeout_ms,
                    playwright_timeout_error=PlaywrightTimeoutError,
                )
                if recovered is not None:
                    downloaded.append(_save_download(recovered, target_dir, tile_id))
                else:
                    errors.append(f"{tile_id}: 等待下载超时")
            except Exception as exc:
                errors.append(f"{tile_id}: {exc}")
        if storage_state_path:
            context.storage_state(path=str(storage_state_path))
        browser.close()

    if not downloaded:
        raise RuntimeError("自动下载未成功。" + ("; ".join(errors) if errors else "请检查登录态或页面结构。"))

    validation = assert_valid_gscloud_tile_downloads(downloaded, expected_tile_ids=tile_ids, require_all=True)
    result = _postprocess_gscloud_files(manager, downloaded, get_source("gscloud"), output_name=output_name, auto_load=auto_load)
    result["auto_tile_errors"] = errors
    result["requested_tile_ids"] = tile_ids
    result["tile_validation"] = validation
    result["message"] = (
        f"已自动下载并校验 {validation['downloaded_count']} 个目标 DEM 分幅。"
        "全部分幅均属于目标区域，已完成解压、入库和打包。"
    )
    return result



# -------------------------
# ASTER/GDEM 分幅规划工具
# -------------------------
# ASTGTM_N30E103 表示以北纬30度、东经103度为左下角的 1°×1° 分幅。
# 该命名规则适用于地理空间数据云 ASTER GDEM 30M 页面中常见的数据标识。
REGION_BBOX_PRESETS: dict[str, tuple[float, float, float, float]] = {
    # 兜底用的近似外包框；如果工作区已有矢量边界，会优先使用真实边界求交。
    "四川": (97.3, 26.0, 108.6, 34.4),
    "四川省": (97.3, 26.0, 108.6, 34.4),
    "sichuan": (97.3, 26.0, 108.6, 34.4),
    "成都": (102.8, 30.1, 104.9, 31.6),
    "成都市": (102.8, 30.1, 104.9, 31.6),
    "chengdu": (102.8, 30.1, 104.9, 31.6),
    "重庆": (105.3, 28.1, 110.2, 32.3),
    "重庆市": (105.3, 28.1, 110.2, 32.3),
    "云南": (97.5, 21.1, 106.3, 29.3),
    "云南省": (97.5, 21.1, 106.3, 29.3),
    "贵州": (103.6, 24.6, 109.6, 29.3),
    "贵州省": (103.6, 24.6, 109.6, 29.3),
}


REGION_BBOX_PRESETS.setdefault("\u95ea\u7535\u6cb3", (115.2, 41.1, 116.6, 42.4))
REGION_BBOX_PRESETS.setdefault("\u95ea\u7535\u6cb3\u6d41\u57df", (115.2, 41.1, 116.6, 42.4))
REGION_BBOX_PRESETS.setdefault("shandianhe", (115.2, 41.1, 116.6, 42.4))


def _format_astgtm_tile_id(lat_floor: int, lon_floor: int) -> str:
    lat_prefix = "N" if lat_floor >= 0 else "S"
    lon_prefix = "E" if lon_floor >= 0 else "W"
    return f"ASTGTM_{lat_prefix}{abs(int(lat_floor)):02d}{lon_prefix}{abs(int(lon_floor)):03d}"


def _is_shandianhe_region(region: str) -> bool:
    text = str(region or "").strip().lower()
    return "闪电河" in str(region or "") or "shandian" in text


def _candidate_shandian_boundary_paths(manager: DataManager) -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    roots = [
        manager.workdir / "local_library" / "data" / "boundary",
        project_root / "local_library" / "data" / "boundary",
    ]
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for filename in _SHANDIAN_BOUNDARY_FILENAMES:
            path = root / filename
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path
            if path.exists() and resolved not in seen:
                seen.add(resolved)
                candidates.append(path)
    return candidates


def _extract_local_shandian_boundary(manager: DataManager, region: str):
    if not _is_shandianhe_region(region):
        return None, "", ""

    import geopandas as gpd

    for archive_path in _candidate_shandian_boundary_paths(manager):
        try:
            with zipfile.ZipFile(archive_path) as archive:
                shp_names = [name for name in archive.namelist() if name.lower().endswith(".shp")]
                if not shp_names:
                    continue
                shp_name = sorted(shp_names, key=lambda item: ("/" in item, item))[0]
                target_dir = manager.temp_dir / "local_boundary_cache" / safe_name(archive_path.stem)
                target_dir.mkdir(parents=True, exist_ok=True)
                safe_extract_zip(archive, target_dir)
            gdf = gpd.read_file(target_dir / shp_name)
            if gdf.empty:
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326", allow_override=True)
            else:
                gdf = gdf.to_crs("EPSG:4326")
            dataset_name = manager.put_vector(
                _SHANDIAN_BOUNDARY_DATASET_NAME,
                gdf,
                filename=f"{_SHANDIAN_BOUNDARY_DATASET_NAME}.geojson",
            )
            return gdf, dataset_name, "local_library_boundary"
        except Exception:
            continue
    return None, "", ""


def _format_srtm_utm_tile_id(row: int, strip: int) -> str:
    return f"utm_srtm_{int(strip):02d}_{int(row):02d}"


def resolve_gscloud_dem_product(product_key: str = "", dataset_id: str = "") -> tuple[str, dict[str, Any]]:
    key = str(product_key or "").strip().lower()
    dataset = str(dataset_id or "").strip()
    if dataset:
        for candidate_key, product in GSCLOUD_DEM_DATASETS.items():
            if str(product.get("dataset_id") or "") == dataset:
                return candidate_key, product
    if key and key in GSCLOUD_DEM_DATASETS:
        return key, GSCLOUD_DEM_DATASETS[key]
    return "aster_gdem_30m", GSCLOUD_DEM_DATASETS["aster_gdem_30m"]


def _tile_bounds_from_id(tile_id: str) -> tuple[float, float, float, float]:
    import re

    m = re.search(r"([NS])(\d{2})([EW])(\d{3})", str(tile_id).upper())
    if not m:
        raise ValueError(f"无法解析分幅编号: {tile_id}")
    lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
    lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
    return float(lon), float(lat), float(lon + 1), float(lat + 1)


def _srtm_utm_cell_bounds(row: int, strip: int) -> tuple[float, float, float, float]:
    west = -180.0 + (int(strip) - 1) * 5.0
    south = 60.0 - int(row) * 5.0
    return west, south, west + 5.0, south + 5.0


def _srtm_utm_indices_for_bbox(minx: float, miny: float, maxx: float, maxy: float) -> list[tuple[int, int, tuple[float, float, float, float]]]:
    items: list[tuple[int, int, tuple[float, float, float, float]]] = []
    for strip in range(1, 73):
        for row in range(1, 31):
            bounds = _srtm_utm_cell_bounds(row, strip)
            if _bbox_intersects((minx, miny, maxx, maxy), bounds):
                items.append((row, strip, bounds))
    return items


def _find_region_gdf_for_tile_plan(manager: DataManager, region: str = "", region_dataset: str = ""):
    """优先从工作区边界数据集获取区域；找不到时返回 None。"""
    import geopandas as gpd

    region = clean_admin_region_query(region)

    def _is_generated_tile_grid(name: str, gdf: gpd.GeoDataFrame) -> bool:
        lower_name = str(name or "").lower()
        if "tile_plan" not in lower_name and not lower_name.endswith("_grid"):
            return False
        tile_columns = {"tile_id", "expected_filename", "row", "strip", "lat_floor", "lon_floor"}
        return bool(tile_columns.intersection({str(col) for col in gdf.columns}))

    candidates: list[str] = []
    if region_dataset:
        candidates.append(region_dataset)
    region_key = str(region or "").strip().lower()
    if _is_shandianhe_region(region):
        candidates.extend([_SHANDIAN_BOUNDARY_DATASET_NAME, "local_library_shandianhe_basin_boundary"])
    if region_key:
        for name in manager.list_dataset_names():
            lower = name.lower()
            if region_key in lower or lower in {"sichuan_boundary", "四川边界", "四川省边界"}:
                candidates.append(name)
    # 常用默认名
    candidates.extend(["sichuan_boundary", "四川边界", "四川省边界"])

    seen: set[str] = set()
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            gdf = manager.get_vector(name)
            if gdf.empty:
                continue
            if _is_generated_tile_grid(name, gdf):
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326", allow_override=True)
            else:
                gdf = gdf.to_crs("EPSG:4326")
            return gdf, name, "workspace_vector"
        except Exception:
            continue
    try:
        gdf, source_name, source_type = _extract_local_shandian_boundary(manager, region)
        if gdf is not None and not gdf.empty:
            return gdf, source_name, source_type
    except Exception:
        pass
    try:
        gdf, source_name, source_type = extract_local_admin_boundary(manager, region)
        if gdf is not None and not gdf.empty:
            return gdf, source_name, source_type
    except Exception:
        pass
    return None, "", ""


def _preset_gdf_for_region(region: str):
    import geopandas as gpd
    from shapely.geometry import box

    key = str(region or "").strip()
    bbox = REGION_BBOX_PRESETS.get(key) or REGION_BBOX_PRESETS.get(key.lower())
    if not bbox:
        return None
    minx, miny, maxx, maxy = bbox
    return gpd.GeoDataFrame([{"region": key or "preset_region"}], geometry=[box(minx, miny, maxx, maxy)], crs="EPSG:4326")



# -------------------------
# 区域边界可信度校验：防止错误边界把四川算成 N00E022
# -------------------------
def _bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """Return whether two lon/lat bboxes intersect."""
    aminx, aminy, amaxx, amaxy = a
    bminx, bminy, bmaxx, bmaxy = b
    return not (amaxx < bminx or bmaxx < aminx or amaxy < bminy or bmaxy < aminy)


def _region_preset_bbox(region: str) -> tuple[float, float, float, float] | None:
    key = str(region or "").strip()
    if "四川" in key or key.lower() == "sichuan":
        return REGION_BBOX_PRESETS.get("四川省") or (97.3, 26.0, 108.6, 34.4)
    return REGION_BBOX_PRESETS.get(key) or REGION_BBOX_PRESETS.get(key.lower())


def _bbox_is_plausible_for_region(
    bbox: tuple[float, float, float, float],
    region: str,
    min_overlap_required: bool = True,
) -> tuple[bool, str]:
    """Check whether a candidate boundary bbox is plausible for the requested region.

    For commercial downloads, this guard is necessary. If a wrong layer named
    `sichuan_boundary` actually has bounds near lon=22, lat=0, the old planner would
    compute ASTGTM_N00E022 and may download Africa, not Sichuan.
    """
    minx, miny, maxx, maxy = [float(x) for x in bbox]
    if maxx <= minx or maxy <= miny:
        return False, f"边界范围无效：{bbox}"

    # 经纬度基本范围校验。
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        return False, f"边界坐标不在经纬度范围内，可能没有转为 EPSG:4326：{bbox}"

    preset = _region_preset_bbox(region)
    if not preset:
        return True, "未配置该区域的预设范围，跳过区域相交校验。"

    if min_overlap_required and not _bbox_intersects((minx, miny, maxx, maxy), preset):
        return False, (
            f"边界范围 {bbox} 与 {region} 预设范围 {preset} 不相交。"
            "该边界很可能不是目标区域边界，已阻止用它计算分幅。"
        )

    # 四川的额外强校验，避免 N00E022 这类明显错误。
    if "四川" in str(region) or str(region).lower() == "sichuan":
        sx_minx, sx_miny, sx_maxx, sx_maxy = preset
        buffer = 3.0
        if not (sx_minx - buffer <= minx <= sx_maxx + buffer and sx_minx - buffer <= maxx <= sx_maxx + buffer and
                sx_miny - buffer <= miny <= sx_maxy + buffer and sx_miny - buffer <= maxy <= sx_maxy + buffer):
            return False, (
                f"四川边界范围异常：{bbox}。正常应大致在东经97–109、北纬26–35附近。"
                "已阻止错误分幅计算。"
            )

    return True, f"边界范围通过校验：{bbox}"


def _guard_region_gdf_or_fallback(gdf, region: str, source_name: str, source_type: str):
    """Validate workspace boundary; fallback to preset bbox if it is implausible."""
    try:
        bounds = tuple(float(x) for x in gdf.total_bounds)
    except Exception as exc:
        bounds = None
        ok = False
        reason = f"无法读取边界范围：{exc}"
    else:
        ok, reason = _bbox_is_plausible_for_region(bounds, region)

    if ok:
        return gdf, source_name, source_type, reason

    fallback = _preset_gdf_for_region(region)
    if fallback is not None:
        note = (
            f"警告：工作区边界数据 {source_name!r} 未通过区域校验：{reason} "
            f"因此已自动改用 {region} 内置外包框兜底。请检查或重新导入正确边界。"
        )
        return fallback, region, "preset_bbox_after_invalid_workspace_boundary", note

    raise ValueError(
        f"边界数据 {source_name!r} 未通过校验：{reason}。"
        "且该区域没有内置外包框，无法安全计算分幅。"
    )

def plan_aster_gdem_tiles(
    manager: DataManager,
    region: str = "四川省",
    region_dataset: str = "",
    output_name: str = "",
    bbox_only: bool = False,
    save_preview: bool = True,
) -> dict[str, Any]:
    """根据区域边界自动计算地理空间数据云 ASTER GDEM 30M 需要的分幅编号。

    优先使用工作区里的矢量边界数据集；如果没有边界但 region 是内置省份，使用近似外包框兜底。
    """
    import math
    import pandas as pd
    import geopandas as gpd
    from shapely.geometry import box

    region = str(region or "四川省").strip() or "四川省"
    gdf, source_name, source_type = _find_region_gdf_for_tile_plan(manager, region=region, region_dataset=region_dataset)
    region_guard_note = ""
    if gdf is not None:
        gdf, source_name, source_type, region_guard_note = _guard_region_gdf_or_fallback(
            gdf, region, source_name, source_type
        )
    if gdf is None:
        gdf = _preset_gdf_for_region(region)
        source_name = region
        source_type = "preset_bbox"
        region_guard_note = f"未找到工作区边界，已使用 {region} 内置外包框。"
    if gdf is None or gdf.empty:
        raise ValueError(
            f"未找到 {region} 的边界数据。请先下载/导入边界，例如数据集名 sichuan_boundary；"
            "或者把 region 设置为已内置外包框的区域。"
        )

    geom = gdf.geometry.unary_union
    minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
    lon_start = math.floor(minx)
    lon_end = math.ceil(maxx) - 1
    lat_start = math.floor(miny)
    lat_end = math.ceil(maxy) - 1

    records: list[dict[str, Any]] = []
    geoms = []
    for lat in range(lat_start, lat_end + 1):
        for lon in range(lon_start, lon_end + 1):
            tile_geom = box(lon, lat, lon + 1, lat + 1)
            intersects = True if bbox_only else bool(tile_geom.intersects(geom))
            if not intersects:
                continue
            tile_id = _format_astgtm_tile_id(lat, lon)
            records.append(
                {
                    "tile_id": tile_id,
                    "lat_floor": lat,
                    "lon_floor": lon,
                    "south": lat,
                    "north": lat + 1,
                    "west": lon,
                    "east": lon + 1,
                    "expected_filename": f"{tile_id}.img.zip",
                }
            )
            geoms.append(tile_geom)

    records.sort(key=lambda x: (x["lat_floor"], x["lon_floor"]))
    tile_ids = [r["tile_id"] for r in records]
    if not records:
        raise RuntimeError("区域范围内没有计算出任何 ASTER GDEM 分幅，请检查边界坐标系或区域名称。")

    base = safe_name(output_name or f"{region}_aster_gdem_tiles")
    derived_files: dict[str, str] = {}
    if save_preview:
        df = pd.DataFrame(records)
        csv_path = manager.derived_dir / f"{base}.csv"
        txt_path = manager.derived_dir / f"{base}.txt"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        txt_path.write_text("\n".join(tile_ids), encoding="utf-8")
        derived_files["csv_path"] = str(csv_path)
        derived_files["txt_path"] = str(txt_path)
        try:
            grid = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")
            grid_name = manager.put_vector(base + "_grid", grid, filename=f"{base}_grid.geojson")
            derived_files["grid_dataset_name"] = grid_name
            derived_files["grid_path"] = str(manager.get(grid_name).path)
        except Exception as exc:
            derived_files["grid_error"] = str(exc)
        manager.log_operation("计算地理空间数据云 DEM 分幅", f"{region} -> {len(tile_ids)} 个分幅", "download")

    return {
        "region": region,
        "region_dataset": source_name,
        "region_source": source_type,
        "region_guard_note": region_guard_note,
        "bbox": [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)],
        "tile_count": len(tile_ids),
        "tile_ids": tile_ids,
        "tile_ids_text": ", ".join(tile_ids),
        "records": records,
        "derived_files": derived_files,
        "notes": [
            "ASTER GDEM 分幅按 1°×1° 经纬度网格组织，编号如 ASTGTM_N30E103。",
            "如果 region_source=preset_bbox，说明当前没有使用真实边界，而是用近似外包框兜底，可能多下载少量周边分幅。",
            "建议先用生成的 grid 预览分幅范围，再批量下载；下载后可再按真实边界裁剪。",
        ],
    }


def plan_gscloud_dem_tiles(
    manager: DataManager,
    region: str = "四川省",
    region_dataset: str = "",
    output_name: str = "",
    bbox_only: bool = False,
    save_preview: bool = True,
    product_key: str = "aster_gdem_30m",
    dataset_id: str = "",
) -> dict[str, Any]:
    """Plan GSCloud DEM tile identifiers for supported DEM grid products."""
    import math
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    product_key, product = resolve_gscloud_dem_product(product_key, dataset_id)
    tile_scheme = str(product.get("tile_scheme") or "astgtm_1deg")
    region = str(region or "四川省").strip() or "四川省"
    gdf, source_name, source_type = _find_region_gdf_for_tile_plan(manager, region=region, region_dataset=region_dataset)
    region_guard_note = ""
    if gdf is not None:
        gdf, source_name, source_type, region_guard_note = _guard_region_gdf_or_fallback(gdf, region, source_name, source_type)
    if gdf is None:
        gdf = _preset_gdf_for_region(region)
        source_name = region
        source_type = "preset_bbox"
        region_guard_note = f"未找到工作区边界，已使用 {region} 内置外包框兜底。"
    if gdf is None or gdf.empty:
        raise ValueError(f"未找到 {region} 的边界数据，无法安全计算 GSCloud DEM 分幅。")

    geom = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.geometry.unary_union
    minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
    records: list[dict[str, Any]] = []
    geoms = []

    if tile_scheme == "srtm_utm_5deg":
        for row, strip, bounds in _srtm_utm_indices_for_bbox(minx, miny, maxx, maxy):
            west, south, east, north = bounds
            tile_geom = box(west, south, east, north)
            if not (True if bbox_only else bool(tile_geom.intersects(geom))):
                continue
            tile_id = _format_srtm_utm_tile_id(row, strip)
            records.append(
                {
                    "tile_id": tile_id,
                    "row": row,
                    "strip": strip,
                    "south": south,
                    "north": north,
                    "west": west,
                    "east": east,
                    "expected_filename": f"{tile_id}.img.zip",
                }
            )
            geoms.append(tile_geom)
        records.sort(key=lambda x: (x["row"], x["strip"]))
    else:
        lon_start = math.floor(minx)
        lon_end = math.ceil(maxx) - 1
        lat_start = math.floor(miny)
        lat_end = math.ceil(maxy) - 1
        for lat in range(lat_start, lat_end + 1):
            for lon in range(lon_start, lon_end + 1):
                tile_geom = box(lon, lat, lon + 1, lat + 1)
                if not (True if bbox_only else bool(tile_geom.intersects(geom))):
                    continue
                tile_id = _format_astgtm_tile_id(lat, lon)
                records.append(
                    {
                        "tile_id": tile_id,
                        "lat_floor": lat,
                        "lon_floor": lon,
                        "south": lat,
                        "north": lat + 1,
                        "west": lon,
                        "east": lon + 1,
                        "expected_filename": f"{tile_id}.img.zip",
                    }
                )
                geoms.append(tile_geom)
        records.sort(key=lambda x: (x["lat_floor"], x["lon_floor"]))

    tile_ids = [r["tile_id"] for r in records]
    if not records:
        raise RuntimeError("区域范围内没有计算出任何 GSCloud DEM 分幅，请检查边界坐标系或区域名称。")

    base = safe_name(output_name or f"{region}_{product_key}_tiles")
    derived_files: dict[str, str] = {}
    if save_preview:
        df = pd.DataFrame(records)
        csv_path = manager.derived_dir / f"{base}.csv"
        txt_path = manager.derived_dir / f"{base}.txt"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        txt_path.write_text("\n".join(tile_ids), encoding="utf-8")
        derived_files["csv_path"] = str(csv_path)
        derived_files["txt_path"] = str(txt_path)
        try:
            grid = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")
            grid_name = manager.put_vector(base + "_grid", grid, filename=f"{base}_grid.geojson")
            derived_files["grid_dataset_name"] = grid_name
            derived_files["grid_path"] = str(manager.get(grid_name).path)
        except Exception as exc:
            derived_files["grid_error"] = str(exc)
        manager.log_operation("计算 GSCloud DEM 分幅", f"{region} -> {len(tile_ids)} tiles | {product_key}", "download")

    return {
        "product_key": product_key,
        "product_name": product.get("name"),
        "dataset_id": str(product.get("dataset_id") or ""),
        "pid": str(product.get("pid") or "1"),
        "access_url": product.get("access_url"),
        "tile_scheme": tile_scheme,
        "region": region,
        "region_dataset": source_name,
        "region_source": source_type,
        "region_guard_note": region_guard_note,
        "bbox": [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)],
        "tile_count": len(tile_ids),
        "tile_ids": tile_ids,
        "tile_ids_text": ", ".join(tile_ids),
        "records": records,
        "derived_files": derived_files,
        "notes": [
            f"{product.get('name') or product_key} 使用 {tile_scheme} 分幅规则。",
            "如果 region_source=preset_bbox，说明当前没有使用真实边界，下载后仍会按边界裁剪。",
        ],
    }


def parse_tile_ids(tile_ids: str | list[str]) -> list[str]:
    if isinstance(tile_ids, list):
        return [str(x).strip() for x in tile_ids if str(x).strip()]
    text = str(tile_ids or "")
    for sep in ["\n", ";", "，", "、", " "]:
        text = text.replace(sep, ",")
    return [x.strip() for x in text.split(",") if x.strip()]
