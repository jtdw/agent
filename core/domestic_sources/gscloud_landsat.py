from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..data_manager import DataManager
from .gscloud_adapter import _ensure_playwright, _postprocess_gscloud_files
from .gscloud_products import LANDSAT8_OLI_TIRS
from .gscloud_reliability import find_existing_scene_download, validate_download_artifact
from .gscloud_scene_table import (
    AVAILABLE,
    DOWNLOAD_BUTTON_SELECTORS,
    UNAVAILABLE,
    find_scene_row_by_id,
    get_scene_table_rows,
    goto_scene_page,
    scan_scene_table_pages,
    update_scene_status,
)
from .registry import get_source


REGION_CENTERS: dict[str, tuple[float, float]] = {
    "成都市": (104.0668, 30.5728),
    "成都": (104.0668, 30.5728),
    "四川省": (104.0, 30.6),
    "四川": (104.0, 30.6),
    "闪电河流域": (116.05, 41.95),
    "闪电河": (116.05, 41.95),
}


def _safe_float(value: Any) -> float | None:
    try:
        return float(str(value).strip().replace("%", ""))
    except Exception:
        return None


def _scene_year(scene_id: str) -> str:
    match = re.search(r"LC8\d{6}(\d{4})", scene_id or "")
    return match.group(1) if match else ""


def _scene_path_row(scene_id: str) -> tuple[int | None, int | None]:
    match = re.search(r"LC8(\d{3})(\d{3})", scene_id or "")
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _region_center(region: str) -> tuple[float, float] | None:
    for key, center in REGION_CENTERS.items():
        if key in str(region or ""):
            return center
    return None


def _distance_score(lon: float | None, lat: float | None, center: tuple[float, float] | None) -> float:
    if lon is None or lat is None or center is None:
        return 9999.0
    return math.hypot(lon - center[0], lat - center[1])


def _row_cells(row) -> list[str]:
    cells: list[str] = []
    try:
        loc = row.locator("td")
        for idx in range(loc.count()):
            cells.append(" ".join(loc.nth(idx).inner_text(timeout=1000).split()))
    except Exception:
        pass
    return cells


def _try_select_data_available(page) -> bool:
    for selector in ("select", ".layui-table-tool select", ".el-select", ".ivu-select", ".layui-form-select"):
        try:
            loc = page.locator(selector)
            for idx in range(min(loc.count(), 8)):
                item = loc.nth(idx)
                if selector == "select":
                    try:
                        item.select_option(label=AVAILABLE)
                        page.wait_for_timeout(1200)
                        return True
                    except Exception:
                        continue
                text = item.inner_text(timeout=800)
                if AVAILABLE in text or "数据" in text:
                    item.click()
                    page.get_by_text(AVAILABLE, exact=True).last.click(timeout=1500)
                    page.wait_for_timeout(1200)
                    return True
        except Exception:
            continue
    return False


def parse_landsat_cells(cells: list[str], row_index: int, page_index: int = 0) -> dict[str, Any] | None:
    if len(cells) < 8:
        return None
    scene_id = next((c for c in cells if re.search(r"LC8\w+", c)), "")
    if not scene_id:
        return None

    path, row_no = _scene_path_row(scene_id)
    numbers = [_safe_float(c) for c in cells[1:]]
    if path is None:
        path = next((int(v) for v in numbers if v is not None and 1 <= v <= 233), None)
    if path is not None:
        after_path = False
        for value in numbers:
            if value is None:
                continue
            if int(value) == path and not after_path:
                after_path = True
                continue
            if row_no is None and after_path and 1 <= value <= 248:
                row_no = int(value)
                break

    date = next((c for c in cells if re.match(r"\d{4}-\d{2}-\d{2}", c)), "")
    cloud = None
    lon = None
    lat = None
    if date:
        try:
            date_idx = cells.index(date)
            cloud = _safe_float(cells[date_idx + 1])
            lon = _safe_float(cells[date_idx + 2])
            lat = _safe_float(cells[date_idx + 3])
        except Exception:
            pass

    data_available = AVAILABLE if any(c == AVAILABLE for c in cells) else (UNAVAILABLE if any(c == UNAVAILABLE for c in cells) else "")
    return {
        "scene_id": scene_id,
        "path": path,
        "row": row_no,
        "date": date,
        "year": _scene_year(scene_id) or (date[:4] if date else ""),
        "cloud": cloud,
        "longitude": lon,
        "latitude": lat,
        "data_available": data_available,
        "page_index": page_index,
        "row_index": row_index,
        "cells": cells,
    }


def _parse_landsat_row(row, row_index: int) -> dict[str, Any] | None:
    return parse_landsat_cells(_row_cells(row), row_index=row_index)


def select_landsat_records(
    records: list[dict[str, Any]],
    *,
    region: str = "",
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    cloud_max: float = 30.0,
    max_scenes: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    center = _region_center(region)
    max_scenes = max(1, int(max_scenes or 1))
    candidates: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        if item.get("data_available") != AVAILABLE:
            item["skip_reason"] = "数据列不是“有”，不可下载。"
        elif item.get("cloud") is not None and float(item["cloud"]) > float(cloud_max):
            item["skip_reason"] = f"云量 {item.get('cloud')} 高于阈值 {cloud_max}。"
        elif year and item.get("year") and str(item["year"]) != str(year):
            item["skip_reason"] = f"年份 {item.get('year')} 不等于 {year}。"
        elif start_date and item.get("date") and item["date"] < start_date:
            item["skip_reason"] = f"日期早于 {start_date}。"
        elif end_date and item.get("date") and item["date"] > end_date:
            item["skip_reason"] = f"日期晚于 {end_date}。"
        item["distance_score"] = _distance_score(item.get("longitude"), item.get("latitude"), center)
        candidates.append(item)

    selected = sorted(
        [item for item in candidates if not item.get("skip_reason")],
        key=lambda item: (
            item.get("distance_score", 9999.0),
            item.get("cloud") if item.get("cloud") is not None else 100.0,
            item.get("date") or "",
        ),
    )[:max_scenes]
    return selected, candidates


def _click_row_download(page, row, timeout_ms: int):
    last_error: Exception | None = None
    for selector in DOWNLOAD_BUTTON_SELECTORS:
        try:
            loc = row.locator(selector)
            if loc.count() == 0:
                continue
            for attempt in range(1, 3):
                try:
                    with page.expect_download(timeout=timeout_ms) as dl_info:
                        loc.first.click(timeout=5000)
                    return dl_info.value
                except Exception as exc:
                    last_error = exc
                    try:
                        page.wait_for_timeout(800 * attempt)
                    except Exception:
                        pass
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"未能定位当前行下载按钮：{last_error}")


def download_landsat8_oli_tirs_scenes(
    *,
    manager: DataManager,
    storage_state_path: str,
    region: str,
    output_name: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    cloud_max: float = 30.0,
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
    status_path: str | Path | None = None,
) -> dict[str, Any]:
    sync_playwright, PlaywrightTimeoutError = _ensure_playwright()
    timeout_ms = max(30, int(timeout_seconds or 1800)) * 1000
    max_scenes = max(1, int(max_scenes or 1))
    target_dir = Path(manager.workdir) / "domestic_downloads" / "gscloud" / "landsat8"
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    candidates: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    pages_scanned = 0
    stop_reason = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_kwargs: dict[str, Any] = {"accept_downloads": True}
        if storage_state_path and Path(storage_state_path).exists():
            context_kwargs["storage_state"] = str(storage_state_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        try:
            page.goto(LANDSAT8_OLI_TIRS.access_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector("table, .el-table, .ivu-table, .ant-table, tr", timeout=30_000)
            _try_select_data_available(page)
            page.wait_for_timeout(1200)
            scan = scan_scene_table_pages(page, _parse_landsat_row, status_path=status_path)
            pages_scanned = scan.pages_scanned
            stop_reason = scan.stop_reason
            selected, candidates = select_landsat_records(
                scan.records,
                region=region,
                year=year,
                start_date=start_date,
                end_date=end_date,
                cloud_max=cloud_max,
                max_scenes=max_scenes,
            )
            update_scene_status(
                status_path,
                state="SCANNING",
                pages_scanned=pages_scanned,
                candidate_count=len(candidates),
                selected_count=len(selected),
                scan_stop_reason=stop_reason,
            )
            if not selected:
                raise RuntimeError(
                    f"未找到满足条件的 Landsat 8 可下载记录。已扫描 {pages_scanned} 页，"
                    f"筛选条件：数据=有，区域={region or '未指定'}，年份={year or '未指定'}，"
                    f"开始日期={start_date or '未指定'}，结束日期={end_date or '未指定'}，云量<={cloud_max}。"
                    "请放宽云量、日期或年份条件，或提高 GSCLOUD_SCENE_MAX_PAGES。"
                )

            for item in selected:
                existing = find_existing_scene_download(target_dir, item["scene_id"])
                if existing is not None:
                    item["downloaded_path"] = str(existing)
                    item["reused_existing"] = True
                    downloaded.append(existing)
                    update_scene_status(
                        status_path,
                        state="DOWNLOADING",
                        pages_scanned=pages_scanned,
                        selected_count=len(selected),
                        downloaded_count=len(downloaded),
                        current_scene=item["scene_id"],
                        last_download_validation=validate_download_artifact(existing),
                    )
                    continue
                goto_scene_page(
                    page,
                    LANDSAT8_OLI_TIRS.access_url,
                    int(item.get("page_no") or 1),
                    after_goto=lambda p: (_try_select_data_available(p), p.wait_for_timeout(1200)),
                )
                row = find_scene_row_by_id(get_scene_table_rows(page), item["scene_id"])
                if row is None:
                    raise RuntimeError(f"已选中 {item['scene_id']}，但在第 {item.get('page_no')} 页未能重新定位该记录。")
                try:
                    download = _click_row_download(page, row, timeout_ms)
                except PlaywrightTimeoutError as exc:
                    raise RuntimeError(f"点击 {item['scene_id']} 下载后未捕获到文件，可能需要二次确认或账号权限不足。") from exc
                suggested = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", download.suggested_filename or f"{item['scene_id']}.zip")
                save_path = target_dir / suggested
                download.save_as(save_path)
                item["download_validation"] = validate_download_artifact(save_path)
                item["downloaded_path"] = str(save_path)
                downloaded.append(save_path)
                update_scene_status(
                    status_path,
                    state="DOWNLOADING",
                    pages_scanned=pages_scanned,
                    selected_count=len(selected),
                    downloaded_count=len(downloaded),
                    current_scene=item["scene_id"],
                )
        finally:
            context.close()
            browser.close()

    result = _postprocess_gscloud_files(manager, downloaded, get_source("gscloud"), output_name=output_name, auto_load=auto_load)
    result["product"] = LANDSAT8_OLI_TIRS.__dict__
    result["scene_count"] = len(downloaded)
    result["selected_scenes"] = selected
    result["candidate_count"] = len(candidates)
    result["pages_scanned"] = pages_scanned
    result["scan_stop_reason"] = stop_reason
    result["filters"] = {
        "data_available": AVAILABLE,
        "region": region,
        "year": year,
        "start_date": start_date,
        "end_date": end_date,
        "cloud_max": cloud_max,
    }
    result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return result
