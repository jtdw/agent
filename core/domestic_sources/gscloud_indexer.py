from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..data_manager import DataManager
from .gscloud_adapter import (
    GSCLOUD_ASTER_GDEM30_ACCESS_URL,
    _ensure_playwright,
    _launch_visible_browser,
    _new_context,
    _save_download,
    _postprocess_gscloud_files,
    assert_valid_gscloud_tile_downloads,
    extract_astgtm_tile_id_from_name,
)
from .gscloud_download_recovery import recover_gscloud_download_from_error_page
from .registry import get_source


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        if path and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _safe_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _update_status(status_path: str | Path | None, **updates: Any) -> None:
    if not status_path:
        return
    path = Path(status_path)
    data = _safe_read_json(path)
    data.update(updates)
    data["updated_at"] = _now()
    _safe_write_json(path, data)


def _index_dir(workdir: str | Path) -> Path:
    path = Path(workdir) / "resource_index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def gscloud_index_db_path(workdir: str | Path) -> Path:
    return _index_dir(workdir) / "gscloud_resources.sqlite"


def _ensure_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL,
                dataset_id TEXT,
                dataset_name TEXT,
                resource_type TEXT,
                tile_id TEXT,
                title TEXT,
                page_url TEXT,
                page_no INTEGER,
                row_no INTEGER,
                row_text TEXT,
                collected_at TEXT,
                UNIQUE(source_key, dataset_id, tile_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gscloud_tile ON resources(source_key, dataset_id, tile_id)")
        conn.commit()


def _upsert_resources(db_path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    _ensure_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO resources (
                source_key, dataset_id, dataset_name, resource_type, tile_id, title,
                page_url, page_no, row_no, row_text, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key, dataset_id, tile_id) DO UPDATE SET
                dataset_name=excluded.dataset_name,
                resource_type=excluded.resource_type,
                title=excluded.title,
                page_url=excluded.page_url,
                page_no=excluded.page_no,
                row_no=excluded.row_no,
                row_text=excluded.row_text,
                collected_at=excluded.collected_at
            """,
            [
                (
                    r.get("source_key", "gscloud"),
                    r.get("dataset_id", ""),
                    r.get("dataset_name", ""),
                    r.get("resource_type", "dem"),
                    r.get("tile_id", ""),
                    r.get("title", ""),
                    r.get("page_url", ""),
                    int(r.get("page_no") or 0),
                    int(r.get("row_no") or 0),
                    r.get("row_text", ""),
                    r.get("collected_at", _now()),
                )
                for r in rows
                if r.get("tile_id")
            ],
        )
        conn.commit()


def _write_index_csv(workdir: str | Path, dataset_id: str, rows: list[dict[str, Any]], output_name: str = "") -> Path:
    base = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", output_name or f"gscloud_dataset_{dataset_id}_index")
    path = _index_dir(workdir) / f"{base}.csv"
    fields = ["tile_id", "title", "dataset_id", "dataset_name", "page_no", "row_no", "page_url", "row_text", "collected_at"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})
    return path


def _extract_tile_from_text(text: str) -> str:
    m = re.search(r"ASTGTM_[NS]\d{2}[EW]\d{3}", str(text or "").upper())
    return m.group(0) if m else ""


def _get_table_rows(page):
    """Return row locators from the current page using several common table frameworks."""
    selectors = [
        "table tbody tr",
        ".el-table__body-wrapper tbody tr",
        ".el-table__row",
        ".ivu-table-body tbody tr",
        ".ant-table-tbody tr",
        "tr",
    ]
    best = None
    best_count = 0
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = loc.count()
            if count > best_count:
                best = loc
                best_count = count
        except Exception:
            continue
    if best is None or best_count <= 0:
        return []
    rows = []
    for i in range(best_count):
        try:
            row = best.nth(i)
            txt = row.inner_text(timeout=3000).strip()
            if txt:
                rows.append(row)
        except Exception:
            continue
    return rows


def _row_text(row) -> str:
    try:
        return row.inner_text(timeout=5000).strip()
    except Exception:
        return ""


def _is_disabled(locator) -> bool:
    try:
        disabled = locator.get_attribute("disabled", timeout=1000)
        if disabled is not None:
            return True
    except Exception:
        pass
    try:
        cls = locator.get_attribute("class", timeout=1000) or ""
        if any(x in cls.lower() for x in ["disabled", "is-disabled", "layui-disabled"]):
            return True
    except Exception:
        pass
    try:
        aria = locator.get_attribute("aria-disabled", timeout=1000)
        if str(aria).lower() == "true":
            return True
    except Exception:
        pass
    return False


def _click_next_page(page) -> bool:
    """Best-effort click on pagination next button. Returns False when no active next exists."""
    candidates = [
        "a[rel='next']",
        "button:has-text('下一页')",
        "a:has-text('下一页')",
        "li:has-text('下一页')",
        "span:has-text('下一页')",
        "button[aria-label*='Next']",
        "button[aria-label*='下一页']",
        "a[aria-label*='Next']",
        "a[title*='下一页']",
        ".pagination-next",
        ".el-pagination .btn-next",
        ".ivu-page-next",
        ".ant-pagination-next",
        "text=下一页",
        "text=Next",
    ]
    before = ""
    try:
        rows = _get_table_rows(page)
        before = _row_text(rows[0])[:200] if rows else page.url
    except Exception:
        before = page.url

    for sel in candidates:
        try:
            loc = page.locator(sel).last
            if loc.count() <= 0:
                continue
            if not loc.is_visible(timeout=1200):
                continue
            if _is_disabled(loc):
                continue
            loc.click(timeout=5000)
            page.wait_for_timeout(1800)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            # Avoid infinite loops if click is no-op.
            try:
                rows_after = _get_table_rows(page)
                after = _row_text(rows_after[0])[:200] if rows_after else page.url
                if after == before and page.url == before:
                    # Still maybe same first row but next page; don't immediately fail.
                    pass
            except Exception:
                pass
            return True
        except Exception:
            continue
    return False


def _click_download_in_row_for_indexer(row) -> bool:
    """Click only the download control in a matched target row."""
    candidates = [
        row.locator("[title*='下载']"),
        row.locator("a[title*='下载']"),
        row.locator("button[title*='下载']"),
        row.locator("i[title*='下载']"),
        row.locator("span[title*='下载']"),
        row.locator("a:has-text('下载')"),
        row.locator("button:has-text('下载')"),
        row.locator("i[class*='download']"),
        row.locator("span[class*='download']"),
        row.locator(".download"),
        row.locator("a, button, i, span").nth(1),  # 操作列常见：信息 / 下载 / 收藏
    ]
    for loc in candidates:
        try:
            if loc.count() <= 0:
                continue
            item = loc.first
            if not item.is_visible(timeout=1200):
                continue
            item.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


def scan_gscloud_dataset_index(
    *,
    workdir: str | Path,
    dataset_id: str = "310",
    dataset_name: str = "ASTER GDEM 30M",
    storage_state_path: str | Path = "",
    start_url: str = "",
    max_pages: int = 0,
    headless: bool = True,
    timeout_seconds: int = 1200,
    output_name: str = "",
    status_path: str | Path | None = None,
) -> dict[str, Any]:
    """Scan all visible pages of a GSCloud accessdata table and build a local resource index.

    This is the first step for a real downloader: it does not assume the target tile is on page 1.
    It traverses pagination, extracts ASTGTM_NxxExxx IDs, writes CSV + SQLite, and returns records.
    """
    sync_playwright, _ = _ensure_playwright()
    start_url = start_url or f"https://www.gscloud.cn/sources/accessdata/{dataset_id}?pid=1"
    max_pages = int(max_pages or 0)
    if max_pages <= 0:
        max_pages = int(os.getenv("GSCLOUD_INDEX_MAX_PAGES", "1000") or "1000")
    timeout_ms = max(30, int(timeout_seconds or 1200)) * 1000
    collected: list[dict[str, Any]] = []
    seen_tiles: set[str] = set()
    pages_scanned = 0
    stop_reason = ""
    started_at = _now()

    _update_status(status_path, state="INDEXING", message="正在扫描地理空间数据云资源分页。", pages_scanned=0)

    with sync_playwright() as p:
        browser = _launch_visible_browser(p, headless=headless)
        context = _new_context(browser, storage_state_path)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_selector("table, .el-table, .ivu-table, .ant-table", timeout=min(timeout_ms, 30_000))
        except Exception:
            pass

        page_signatures: set[str] = set()
        while pages_scanned < max_pages:
            pages_scanned += 1
            rows = _get_table_rows(page)
            page_records = 0
            first_text = ""
            last_text = ""
            for row_no, row in enumerate(rows, start=1):
                text = _row_text(row)
                if not text:
                    continue
                if not first_text:
                    first_text = text[:120]
                last_text = text[:120]
                tile_id = _extract_tile_from_text(text)
                if not tile_id:
                    continue
                if tile_id in seen_tiles:
                    continue
                seen_tiles.add(tile_id)
                record = {
                    "source_key": "gscloud",
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_name,
                    "resource_type": "dem",
                    "tile_id": tile_id,
                    "title": tile_id,
                    "page_url": page.url,
                    "page_no": pages_scanned,
                    "row_no": row_no,
                    "row_text": text,
                    "collected_at": _now(),
                }
                collected.append(record)
                page_records += 1

            _update_status(
                status_path,
                state="INDEXING",
                message=f"已扫描第 {pages_scanned} 页，累计发现 {len(collected)} 个资源分幅。",
                pages_scanned=pages_scanned,
                resources_found=len(collected),
                current_url=page.url,
            )

            signature = f"{page.url}|{first_text}|{last_text}|{len(rows)}"
            if signature in page_signatures and pages_scanned > 1:
                stop_reason = "分页内容重复，停止扫描，避免死循环。"
                break
            page_signatures.add(signature)

            if pages_scanned >= max_pages:
                stop_reason = f"达到最大扫描页数 {max_pages}。"
                break
            if not _click_next_page(page):
                stop_reason = "没有找到可点击的下一页，扫描结束。"
                break

        if storage_state_path:
            try:
                context.storage_state(path=str(storage_state_path))
            except Exception:
                pass
        browser.close()

    db_path = gscloud_index_db_path(workdir)
    _upsert_resources(db_path, collected)
    csv_path = _write_index_csv(workdir, dataset_id, collected, output_name=output_name or f"gscloud_{dataset_id}_index")
    result = {
        "ok": True,
        "source_key": "gscloud",
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "resource_type": "dem",
        "start_url": start_url,
        "pages_scanned": pages_scanned,
        "resource_count": len(collected),
        "db_path": str(db_path),
        "csv_path": str(csv_path),
        "started_at": started_at,
        "finished_at": _now(),
        "stop_reason": stop_reason,
        "tile_ids_preview": [r["tile_id"] for r in collected[:50]],
    }
    _update_status(status_path, state="INDEXED", message="资源分页扫描完成。", index_result=result)
    return result


def _scan_and_download_expected_tiles(
    *,
    manager: DataManager,
    expected_tile_ids: list[str],
    dataset_id: str = "310",
    dataset_name: str = "ASTER GDEM 30M",
    storage_state_path: str | Path = "",
    output_name: str = "",
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
    max_pages: int = 0,
    status_path: str | Path | None = None,
) -> dict[str, Any]:
    sync_playwright, PlaywrightTimeoutError = _ensure_playwright()
    expected = [x.strip().upper() for x in expected_tile_ids if str(x or "").strip()]
    expected_set = set(expected)
    if not expected:
        raise ValueError("没有目标分幅，无法下载。")

    start_url = f"https://www.gscloud.cn/sources/accessdata/{dataset_id}?pid=1"
    max_pages = int(max_pages or 0)
    if max_pages <= 0:
        max_pages = int(os.getenv("GSCLOUD_INDEX_MAX_PAGES", "1000") or "1000")
    timeout_ms = max(30, int(timeout_seconds or 1800)) * 1000
    target_dir = Path(manager.workdir) / "domestic_downloads" / "gscloud"
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    downloaded_tiles: set[str] = set()
    found_tiles: set[str] = set()
    index_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    pages_scanned = 0
    started_at = _now()

    _update_status(
        status_path,
        state="INDEXING_AND_DOWNLOADING",
        message="正在扫描所有分页，并仅下载目标区域分幅。",
        expected_count=len(expected),
        downloaded_count=0,
        found_count=0,
    )

    with sync_playwright() as p:
        browser = _launch_visible_browser(p, headless=headless)
        context = _new_context(browser, storage_state_path)
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_selector("table, .el-table, .ivu-table, .ant-table", timeout=30_000)
        except Exception:
            pass

        page_signatures: set[str] = set()
        while pages_scanned < max_pages and downloaded_tiles != expected_set:
            pages_scanned += 1
            rows = _get_table_rows(page)
            first_text = ""
            last_text = ""
            for row_no, row in enumerate(rows, start=1):
                text = _row_text(row)
                if not text:
                    continue
                if not first_text:
                    first_text = text[:120]
                last_text = text[:120]
                tile_id = _extract_tile_from_text(text)
                if not tile_id:
                    continue
                index_rows.append({
                    "source_key": "gscloud",
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_name,
                    "resource_type": "dem",
                    "tile_id": tile_id,
                    "title": tile_id,
                    "page_url": page.url,
                    "page_no": pages_scanned,
                    "row_no": row_no,
                    "row_text": text,
                    "collected_at": _now(),
                })
                if tile_id not in expected_set:
                    continue
                found_tiles.add(tile_id)
                if tile_id in downloaded_tiles:
                    continue
                try:
                    _update_status(
                        status_path,
                        state="DOWNLOADING",
                        message=f"在第 {pages_scanned} 页找到目标分幅 {tile_id}，正在下载。",
                        current_tile=tile_id,
                        pages_scanned=pages_scanned,
                        found_count=len(found_tiles),
                        downloaded_count=len(downloaded_tiles),
                        missing_preview=sorted(expected_set - downloaded_tiles)[:30],
                    )
                    with page.expect_download(timeout=timeout_ms) as dl_info:
                        clicked = _click_download_in_row_for_indexer(row)
                        if not clicked:
                            raise RuntimeError("找到目标行，但未找到可点击下载按钮。")
                    download = dl_info.value
                    saved = _save_download(download, target_dir, tile_id)
                    detected = extract_astgtm_tile_id_from_name(saved.name)
                    if detected != tile_id:
                        raise RuntimeError(f"下载文件名校验失败：目标 {tile_id}，实际文件 {saved.name}，识别为 {detected or '无法识别'}。")
                    downloaded.append(saved)
                    downloaded_tiles.add(tile_id)
                    _update_status(
                        status_path,
                        state="DOWNLOADING",
                        message=f"已下载 {len(downloaded_tiles)}/{len(expected_set)} 个目标分幅。",
                        pages_scanned=pages_scanned,
                        found_count=len(found_tiles),
                        downloaded_count=len(downloaded_tiles),
                        last_download=str(saved),
                        missing_preview=sorted(expected_set - downloaded_tiles)[:30],
                    )
                except PlaywrightTimeoutError:
                    recovered = recover_gscloud_download_from_error_page(
                        page,
                        timeout_ms=timeout_ms,
                        playwright_timeout_error=PlaywrightTimeoutError,
                    )
                    if recovered is not None:
                        try:
                            saved = _save_download(recovered, target_dir, tile_id)
                            detected = extract_astgtm_tile_id_from_name(saved.name)
                            if detected != tile_id:
                                raise RuntimeError(f"下载文件名校验失败：目标 {tile_id}，实际文件 {saved.name}，识别为 {detected or '无法识别'}。")
                            downloaded.append(saved)
                            downloaded_tiles.add(tile_id)
                            _update_status(
                                status_path,
                                state="DOWNLOADING",
                                message=f"已从下载错误页刷新恢复并下载 {len(downloaded_tiles)}/{len(expected_set)} 个目标分幅。",
                                pages_scanned=pages_scanned,
                                found_count=len(found_tiles),
                                downloaded_count=len(downloaded_tiles),
                                last_download=str(saved),
                                missing_preview=sorted(expected_set - downloaded_tiles)[:30],
                            )
                        except Exception as exc:
                            errors.append(f"{tile_id}: {exc}")
                    else:
                        errors.append(f"{tile_id}: 等待下载超时")
                except Exception as exc:
                    errors.append(f"{tile_id}: {exc}")

            signature = f"{page.url}|{first_text}|{last_text}|{len(rows)}"
            if signature in page_signatures and pages_scanned > 1:
                errors.append("分页内容重复，提前停止扫描，避免死循环。")
                break
            page_signatures.add(signature)

            if downloaded_tiles == expected_set:
                break
            if pages_scanned >= max_pages:
                errors.append(f"达到最大扫描页数 {max_pages}，仍有目标分幅未找到。")
                break
            if not _click_next_page(page):
                break

        if storage_state_path:
            try:
                context.storage_state(path=str(storage_state_path))
            except Exception:
                pass
        browser.close()

    # Save scanned index for audit and later reuse.
    dedup: dict[str, dict[str, Any]] = {}
    for r in index_rows:
        if r.get("tile_id") and r["tile_id"] not in dedup:
            dedup[r["tile_id"]] = r
    all_rows = list(dedup.values())
    db_path = gscloud_index_db_path(manager.workdir)
    _upsert_resources(db_path, all_rows)
    csv_path = _write_index_csv(manager.workdir, dataset_id, all_rows, output_name=f"{output_name or 'gscloud_dem'}_resource_index")

    if not downloaded:
        raise RuntimeError(
            "没有成功下载任何目标分幅。"
            + (" 错误：" + "；".join(errors[:20]) if errors else "")
            + " 请检查登录态、分页结构、下载按钮和网站是否限制访问。"
        )

    validation = assert_valid_gscloud_tile_downloads(downloaded, expected_tile_ids=expected, require_all=True)
    # assert_valid will raise if any expected tile was missing.
    result = _postprocess_gscloud_files(manager, downloaded, get_source("gscloud"), output_name=output_name, auto_load=auto_load)
    result["tile_validation"] = validation
    result["requested_tile_ids"] = expected
    result["found_tile_ids"] = sorted(found_tiles)
    result["missing_from_site_tile_ids"] = sorted(expected_set - found_tiles)
    result["downloaded_tile_ids"] = sorted(downloaded_tiles)
    result["scan_pages_scanned"] = pages_scanned
    result["resource_index"] = {"db_path": str(db_path), "csv_path": str(csv_path), "indexed_count": len(all_rows)}
    result["auto_tile_errors"] = errors
    result["started_at"] = started_at
    result["finished_at"] = _now()
    result["message"] = (
        f"已扫描地理空间数据云 ASTER/GDEM 全部分页，并只下载目标区域分幅："
        f"{validation['downloaded_count']}/{validation['expected_count']}。"
        "下载文件已通过 ASTGTM 分幅编号校验。"
    )
    _update_status(status_path, state="COMPLETED", message="分页扫描下载完成。", result_summary={
        "downloaded_count": validation["downloaded_count"],
        "expected_count": validation["expected_count"],
        "pages_scanned": pages_scanned,
    })
    return result


def download_gscloud_tiles_by_full_scan(
    *,
    manager: DataManager,
    tile_ids: list[str],
    dataset_id: str = "310",
    storage_state_path: str | Path = "",
    output_name: str = "",
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
    max_pages: int = 0,
    status_path: str | Path | None = None,
) -> dict[str, Any]:
    """Scan all pages of the GSCloud accessdata table and download only expected ASTER tile IDs.

    This is safer than opening the website and letting the user choose, and safer than searching only
    the current page. Wrong tiles such as ASTGTM_N00E022 are rejected.
    """
    return _scan_and_download_expected_tiles(
        manager=manager,
        expected_tile_ids=tile_ids,
        dataset_id=dataset_id,
        dataset_name="ASTER GDEM 30M" if str(dataset_id) == "310" else f"GSCloud dataset {dataset_id}",
        storage_state_path=storage_state_path,
        output_name=output_name,
        timeout_seconds=timeout_seconds,
        headless=headless,
        auto_load=auto_load,
        max_pages=max_pages,
        status_path=status_path,
    )


def query_index_for_tiles(workdir: str | Path, dataset_id: str, tile_ids: list[str]) -> dict[str, Any]:
    db_path = gscloud_index_db_path(workdir)
    if not db_path.exists():
        return {"ok": False, "error": "本地资源索引库不存在，请先扫描资源分页。", "db_path": str(db_path)}
    expected = [x.strip().upper() for x in tile_ids if str(x or "").strip()]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        qmarks = ",".join(["?"] * len(expected)) or "''"
        rows = conn.execute(
            f"SELECT * FROM resources WHERE source_key='gscloud' AND dataset_id=? AND tile_id IN ({qmarks})",
            [dataset_id, *expected],
        ).fetchall()
    found = [dict(r) for r in rows]
    found_ids = {r["tile_id"] for r in found}
    return {
        "ok": True,
        "db_path": str(db_path),
        "dataset_id": dataset_id,
        "expected_count": len(expected),
        "found_count": len(found_ids),
        "found_tile_ids": sorted(found_ids),
        "missing_tile_ids": [x for x in expected if x not in found_ids],
        "records": found,
    }
