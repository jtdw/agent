from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..data_manager import DataManager
from .gscloud_adapter import _ensure_playwright, _postprocess_gscloud_files
from .gscloud_download_recovery import recover_gscloud_download_from_error_page
from .gscloud_products import MODND1T_CHINA_500M_NDVI_10DAY
from .gscloud_reliability import find_existing_scene_download, validate_download_artifact
from .gscloud_scene_table import (
    AVAILABLE,
    DOWNLOAD_BUTTON_SELECTORS,
    UNAVAILABLE,
    find_scene_row_by_id,
    find_scene_date_cell,
    get_scene_table_rows,
    goto_scene_page,
    scan_scene_table_pages,
    search_scene_row_by_id,
    scene_data_available,
    scene_data_unavailable,
    select_scene_records,
    update_scene_status,
)
from .registry import get_source


def _safe_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except Exception:
        return None


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
    for selector in ("select", ".el-select", ".ivu-select", ".layui-form-select"):
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
                if "全部" in text or AVAILABLE in text or "数据" in text:
                    item.click()
                    page.get_by_text(AVAILABLE, exact=True).last.click(timeout=1500)
                    page.wait_for_timeout(1200)
                    return True
        except Exception:
            continue
    return False


def parse_modnd1d_cells(cells: list[str], row_index: int) -> dict[str, Any] | None:
    if len(cells) < 6:
        return None
    scene_id = next((c for c in cells if c.upper().startswith(("MODND1T.", "MODND1D."))), "")
    if not scene_id:
        return None
    date, date_idx = find_scene_date_cell(cells, scene_id)
    lon = None
    lat = None
    if date and date_idx >= 0:
        try:
            lon = _safe_float(cells[date_idx + 1])
            lat = _safe_float(cells[date_idx + 2])
        except Exception:
            pass
    data_available = AVAILABLE if any(scene_data_available(c) for c in cells) else (UNAVAILABLE if any(scene_data_unavailable(c) for c in cells) else "")
    scene_upper = scene_id.upper()
    product_tag = "NDVI" if ".NDVI." in scene_upper or scene_upper.endswith(".NDVI.V2") else ("QC" if ".QC." in scene_upper else "")
    return {
        "scene_id": scene_id,
        "date": date,
        "year": date[:4] if date else "",
        "longitude": lon,
        "latitude": lat,
        "data_available": data_available,
        "product_tag": product_tag,
        "row_index": row_index,
        "cells": cells,
    }


def _parse_modnd1d_row(row, row_index: int) -> dict[str, Any] | None:
    return parse_modnd1d_cells(_row_cells(row), row_index=row_index)


def _click_row_download(page, row, timeout_ms: int):
    last_error: Exception | None = None
    for selector in DOWNLOAD_BUTTON_SELECTORS:
        try:
            loc = row.locator(selector)
            if loc.count() == 0:
                continue
            with page.expect_download(timeout=timeout_ms) as dl_info:
                loc.first.click(timeout=5000)
            return dl_info.value
        except Exception as exc:
            recovered = recover_gscloud_download_from_error_page(
                page,
                timeout_ms=timeout_ms,
                playwright_timeout_error=type(exc),
            )
            if recovered is not None:
                return recovered
            last_error = exc
            continue
    raise RuntimeError(f"未能定位当前行下载按钮：{last_error}")


def download_modnd1d_china_ndvi_daily(
    *,
    manager: DataManager,
    storage_state_path: str,
    region: str,
    output_name: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    include_qc: bool = False,
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
    status_path: str | Path | None = None,
) -> dict[str, Any]:
    sync_playwright, PlaywrightTimeoutError = _ensure_playwright()
    timeout_ms = max(30, int(timeout_seconds or 1800)) * 1000
    max_scenes = max(1, int(max_scenes or 1))
    target_dir = Path(manager.workdir) / "domestic_downloads" / "gscloud" / "modnd1t"
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
            page.goto(MODND1T_CHINA_500M_NDVI_10DAY.access_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector("table, .el-table, .ivu-table, .ant-table, tr", timeout=30_000)
            _try_select_data_available(page)
            page.wait_for_timeout(1200)
            scan = scan_scene_table_pages(page, _parse_modnd1d_row, status_path=status_path)
            pages_scanned = scan.pages_scanned
            stop_reason = scan.stop_reason
            selected, candidates = select_scene_records(
                scan.records,
                year=year,
                start_date=start_date,
                end_date=end_date,
                max_scenes=max_scenes,
                extra_filter=(None if include_qc else lambda item: item.get("product_tag") != "QC"),
                extra_skip_reason="默认只下载 NDVI 主产品，跳过 QC 质量控制文件。",
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
                    f"未找到满足条件的 MODND1T NDVI 旬合成可下载记录。已扫描 {pages_scanned} 页，"
                    f"筛选条件：数据=有，产品={'NDVI+QC' if include_qc else 'NDVI/MAX'}，年份={year or '未指定'}，"
                    f"开始日期={start_date or '未指定'}，结束日期={end_date or '未指定'}。"
                    "请放宽日期或年份条件，或提高 GSCLOUD_SCENE_MAX_PAGES。"
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
                    MODND1T_CHINA_500M_NDVI_10DAY.access_url,
                    int(item.get("page_no") or 1),
                    after_goto=lambda p: (_try_select_data_available(p), p.wait_for_timeout(1200)),
                )
                row = find_scene_row_by_id(get_scene_table_rows(page), item["scene_id"])
                if row is None:
                    update_scene_status(
                        status_path,
                        state="DOWNLOADING",
                        pages_scanned=pages_scanned,
                        selected_count=len(selected),
                        downloaded_count=len(downloaded),
                        current_scene=item["scene_id"],
                        message=f"第 {item.get('page_no')} 页未重新定位到 {item['scene_id']}，正在改用数据标识搜索。",
                    )
                    row = search_scene_row_by_id(page, item["scene_id"], parse_row=_parse_modnd1d_row)
                if row is None:
                    raise RuntimeError(f"已选中 {item['scene_id']}，但按第 {item.get('page_no')} 页和数据标识搜索都未能重新定位该记录。")
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
    result["product"] = MODND1T_CHINA_500M_NDVI_10DAY.__dict__
    result["scene_count"] = len(downloaded)
    result["selected_scenes"] = selected
    result["candidate_count"] = len(candidates)
    result["pages_scanned"] = pages_scanned
    result["scan_stop_reason"] = stop_reason
    result["filters"] = {
        "data_available": AVAILABLE,
        "product": "NDVI/MAX" if not include_qc else "NDVI/MAX+QC",
        "region": region,
        "year": year,
        "start_date": start_date,
        "end_date": end_date,
    }
    result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return result
