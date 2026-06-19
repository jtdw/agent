from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .gscloud_adapter import _ensure_playwright
from .gscloud_landsat import _parse_landsat_row, _try_select_data_available as _try_select_landsat_available, select_landsat_records
from .gscloud_mod021km import _parse_mod021km_row
from .gscloud_modev1f import _parse_modev1f_row
from .gscloud_modl1d import _parse_modl1d_row
from .gscloud_modnd1d import _parse_modnd1d_row, _try_select_data_available
from .gscloud_products import (
    GSCLOUD_PRODUCTS,
    LANDSAT8_OLI_TIRS,
    MOD021KM_1KM_SURFACE_REFLECTANCE,
    MODEV1F_CHINA_250M_EVI_5DAY,
    MODL1T_CHINA_1KM_LST_COMPOSITE,
    MODND1T_CHINA_500M_NDVI_10DAY,
    SENTINEL2_MSI,
)
from .gscloud_reliability import inspect_storage_state, validate_download_artifact
from .gscloud_scene_table import (
    DOWNLOAD_BUTTON_SELECTORS,
    click_scene_row_download,
    find_scene_row_by_id,
    get_scene_table_rows,
    goto_scene_page,
    scan_scene_table_pages,
    search_scene_row_by_id,
    select_scene_records,
)
from .gscloud_sentinel2 import _parse_sentinel2_row


@dataclass(frozen=True)
class VerificationSpec:
    product_key: str
    parse_row: Callable[[Any, int], dict[str, Any] | None]
    select_available: Callable[[Any], bool]
    select_records: Callable[[list[dict[str, Any]], dict[str, Any]], tuple[list[dict[str, Any]], list[dict[str, Any]]]]


def _select_default_records(records: list[dict[str, Any]], options: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return select_scene_records(
        records,
        year=str(options.get("year") or ""),
        start_date=str(options.get("start_date") or ""),
        end_date=str(options.get("end_date") or ""),
        max_scenes=1,
    )


def _select_modnd1d_records(records: list[dict[str, Any]], options: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    include_qc = bool(options.get("include_qc"))
    return select_scene_records(
        records,
        year=str(options.get("year") or ""),
        start_date=str(options.get("start_date") or ""),
        end_date=str(options.get("end_date") or ""),
        max_scenes=1,
        extra_filter=(None if include_qc else lambda item: item.get("product_tag") != "QC"),
        extra_skip_reason="默认只验证 NDVI 主产品，跳过 QC 质量控制文件。",
    )


def _select_modl1d_records(records: list[dict[str, Any]], options: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    include_quality = bool(options.get("include_quality"))
    return select_scene_records(
        records,
        year=str(options.get("year") or ""),
        start_date=str(options.get("start_date") or ""),
        end_date=str(options.get("end_date") or ""),
        max_scenes=1,
        extra_filter=(None if include_quality else lambda item: item.get("product_family") != "quality"),
        extra_skip_reason="默认只验证 LTD/LTN 主产品，跳过 QCD/QCN 质量控制文件。",
    )


def _select_sentinel2_records(records: list[dict[str, Any]], options: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    level = str(options.get("processing_level") or "").upper().replace(" ", "")
    return select_scene_records(
        records,
        year=str(options.get("year") or ""),
        start_date=str(options.get("start_date") or ""),
        end_date=str(options.get("end_date") or ""),
        max_scenes=1,
        extra_filter=(lambda item: item.get("processing_level") == level) if level else None,
        extra_skip_reason=f"处理级别不是 {level}。",
    )


def _select_landsat_records(records: list[dict[str, Any]], options: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return select_landsat_records(
        records,
        region=str(options.get("region") or ""),
        year=str(options.get("year") or ""),
        start_date=str(options.get("start_date") or ""),
        end_date=str(options.get("end_date") or ""),
        cloud_max=float(options.get("cloud_max") if options.get("cloud_max") is not None else 30.0),
        max_scenes=1,
    )


VERIFICATION_SPECS: dict[str, VerificationSpec] = {
    LANDSAT8_OLI_TIRS.key: VerificationSpec(LANDSAT8_OLI_TIRS.key, _parse_landsat_row, _try_select_landsat_available, _select_landsat_records),
    MODND1T_CHINA_500M_NDVI_10DAY.key: VerificationSpec(MODND1T_CHINA_500M_NDVI_10DAY.key, _parse_modnd1d_row, _try_select_data_available, _select_modnd1d_records),
    MODL1T_CHINA_1KM_LST_COMPOSITE.key: VerificationSpec(MODL1T_CHINA_1KM_LST_COMPOSITE.key, _parse_modl1d_row, _try_select_data_available, _select_modl1d_records),
    MODEV1F_CHINA_250M_EVI_5DAY.key: VerificationSpec(MODEV1F_CHINA_250M_EVI_5DAY.key, _parse_modev1f_row, _try_select_data_available, _select_default_records),
    MOD021KM_1KM_SURFACE_REFLECTANCE.key: VerificationSpec(MOD021KM_1KM_SURFACE_REFLECTANCE.key, _parse_mod021km_row, _try_select_data_available, _select_default_records),
    SENTINEL2_MSI.key: VerificationSpec(SENTINEL2_MSI.key, _parse_sentinel2_row, _try_select_data_available, _select_sentinel2_records),
}


def validate_downloaded_file(path: str | Path) -> dict[str, Any]:
    result = validate_download_artifact(path)
    return {k: v for k, v in result.items() if k != "ok"}


def build_verification_result(
    *,
    product_key: str,
    execute_download: bool,
    scene: dict[str, Any],
    pages_scanned: int,
    candidate_count: int,
    download_selector_hits: list[str],
    downloaded_file: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "state": "DOWNLOADED" if downloaded_file else "READY_TO_DOWNLOAD",
        "product_key": product_key,
        "execute_download": bool(execute_download),
        "scene": scene,
        "pages_scanned": pages_scanned,
        "candidate_count": candidate_count,
        "download_selector_hits": download_selector_hits,
        "downloaded_file": downloaded_file,
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _download_selector_hits(row) -> list[str]:
    hits: list[str] = []
    for selector in DOWNLOAD_BUTTON_SELECTORS:
        try:
            count = row.locator(selector).count()
        except Exception:
            count = 0
        if count:
            hits.append(f"{selector}:{count}")
    return hits


def _safe_filename(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", name).strip("._") or "gscloud_download"


def verify_gscloud_scene_download(
    *,
    product_key: str,
    storage_state_path: str | Path,
    download_dir: str | Path,
    execute_download: bool = False,
    max_pages: int = 1,
    timeout_seconds: int = 600,
    headless: bool = True,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if product_key not in VERIFICATION_SPECS or product_key not in GSCLOUD_PRODUCTS:
        raise RuntimeError(f"不支持的 GSCloud 验证产品: {product_key}")
    state_path = Path(storage_state_path)
    login_health = inspect_storage_state(state_path)
    if not login_health.get("ok"):
        raise RuntimeError(f"登录态不可用: {login_health.get('reason')} ({state_path})")
    target_dir = Path(download_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    spec = VERIFICATION_SPECS[product_key]
    product = GSCLOUD_PRODUCTS[product_key]
    options = dict(options or {})
    timeout_ms = max(30, int(timeout_seconds or 600)) * 1000
    sync_playwright, PlaywrightTimeoutError = _ensure_playwright()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, downloads_path=str(target_dir))
        context = browser.new_context(storage_state=str(state_path), accept_downloads=True)
        page = context.new_page()
        try:
            page.goto(product.access_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector("table, .el-table, .ivu-table, .ant-table, tr", timeout=30_000)
            spec.select_available(page)
            page.wait_for_timeout(1200)
            scan = scan_scene_table_pages(page, spec.parse_row, max_pages=max_pages)
            selected, candidates = spec.select_records(scan.records, options)
            if not selected:
                raise RuntimeError(f"未找到可用于验证的 {product_key} 下载记录；已扫描 {scan.pages_scanned} 页，候选 {len(candidates)} 条。")
            scene = dict(selected[0])
            goto_scene_page(
                page,
                product.access_url,
                int(scene.get("page_no") or 1),
                after_goto=lambda current: (spec.select_available(current), current.wait_for_timeout(1200)),
            )
            row = find_scene_row_by_id(get_scene_table_rows(page), scene["scene_id"])
            if row is None:
                row = search_scene_row_by_id(page, scene["scene_id"], parse_row=spec.parse_row)
            if row is None:
                raise RuntimeError(f"已选中 {scene['scene_id']}，但按第 {scene.get('page_no')} 页和数据标识搜索都无法重新定位该行。")
            hits = _download_selector_hits(row)
            if not hits:
                raise RuntimeError(f"已定位 {scene['scene_id']}，但未找到可点击下载入口。")

            downloaded_file = None
            if execute_download:
                try:
                    download = click_scene_row_download(page, row, timeout_ms)
                except PlaywrightTimeoutError as exc:
                    raise RuntimeError(f"点击 {scene['scene_id']} 下载后未捕获到文件。") from exc
                suggested = _safe_filename(download.suggested_filename or f"{scene['scene_id']}.zip")
                save_path = target_dir / suggested
                download.save_as(save_path)
                downloaded_file = validate_downloaded_file(save_path)

            return build_verification_result(
                product_key=product_key,
                execute_download=execute_download,
                scene=scene,
                pages_scanned=scan.pages_scanned,
                candidate_count=len(candidates),
                download_selector_hits=hits,
                downloaded_file=downloaded_file,
            )
        finally:
            context.close()
            browser.close()


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
