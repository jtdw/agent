
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

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
from .registry import get_source


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def per_tile_download_timeout_ms(timeout_seconds: int) -> int:
    return min(120, max(30, int(timeout_seconds or 30))) * 1000


def normalize_gscloud_tile_id(tile_id: str, *, tile_scheme: str = "astgtm_1deg") -> str:
    text = str(tile_id or "").strip()
    if str(tile_scheme or "").lower() == "srtm_utm_5deg":
        return text.lower()
    return text.upper()


def extract_gscloud_tile_id_from_name(name: str | Path, *, tile_scheme: str = "astgtm_1deg") -> str:
    text = Path(str(name)).name
    if str(tile_scheme or "").lower() == "srtm_utm_5deg":
        match = re.search(r"utm_srtm_\d{2}_\d{2}", text, flags=re.IGNORECASE)
        return match.group(0).lower() if match else ""
    return extract_astgtm_tile_id_from_name(text)


def _tile_search_terms(tile_id: str, *, tile_scheme: str = "astgtm_1deg") -> list[str]:
    normalized = normalize_gscloud_tile_id(tile_id, tile_scheme=tile_scheme)
    if not normalized:
        return []
    if str(tile_scheme or "").lower() == "srtm_utm_5deg":
        coordinate = normalized.removeprefix("utm_srtm_")
        return list(dict.fromkeys([normalized, coordinate]))
    coordinate = normalized.removeprefix("ASTGTM_")
    return list(dict.fromkeys([normalized, coordinate]))


def existing_gscloud_tile_downloads(target_dir: Path, tile_ids: list[str], *, tile_scheme: str = "astgtm_1deg") -> dict[str, Path]:
    expected = {normalize_gscloud_tile_id(str(tile_id), tile_scheme=tile_scheme) for tile_id in tile_ids if str(tile_id).strip()}
    found: dict[str, Path] = {}
    if not target_dir.exists():
        return found
    for path in target_dir.iterdir():
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        tile_id = extract_gscloud_tile_id_from_name(path.name, tile_scheme=tile_scheme)
        if tile_id in expected:
            found[tile_id] = path
    return found


def validate_gscloud_tile_downloads_for_scheme(
    downloaded: list[Path],
    expected_tile_ids: list[str],
    *,
    tile_scheme: str = "astgtm_1deg",
) -> dict[str, Any]:
    if str(tile_scheme or "").lower() != "srtm_utm_5deg":
        return assert_valid_gscloud_tile_downloads(downloaded, expected_tile_ids=expected_tile_ids, require_all=True)

    expected = [normalize_gscloud_tile_id(x, tile_scheme=tile_scheme) for x in expected_tile_ids if str(x or "").strip()]
    expected_set = set(expected)
    downloaded_items: list[dict[str, Any]] = []
    downloaded_tile_ids: list[str] = []
    unknown_files: list[str] = []
    unexpected: list[str] = []
    for path in downloaded:
        tile_id = extract_gscloud_tile_id_from_name(path.name, tile_scheme=tile_scheme)
        downloaded_items.append({"file": str(path), "filename": path.name, "tile_id": tile_id})
        if tile_id:
            downloaded_tile_ids.append(tile_id)
            if tile_id not in expected_set:
                unexpected.append(tile_id)
        else:
            unknown_files.append(path.name)
    missing = [tile_id for tile_id in expected if tile_id not in set(downloaded_tile_ids)]
    valid = not unexpected and not unknown_files and not missing
    if not valid:
        raise RuntimeError(
            "下载文件未通过 GSCloud 分幅校验。"
            + (f" 缺少: {', '.join(missing[:20])}." if missing else "")
            + (f" 非目标分幅: {', '.join(sorted(set(unexpected))[:20])}." if unexpected else "")
            + (f" 无法识别: {', '.join(unknown_files[:10])}." if unknown_files else "")
        )
    return {
        "valid": True,
        "expected_tile_ids": expected,
        "expected_count": len(expected),
        "downloaded_items": downloaded_items,
        "downloaded_tile_ids": downloaded_tile_ids,
        "downloaded_count": len(downloaded_tile_ids),
        "unexpected_tile_ids": [],
        "unexpected_count": 0,
        "unknown_files": [],
        "missing_tile_ids": [],
        "missing_count": 0,
        "require_all": True,
    }


def _safe_read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _safe_write_json(path: str | Path | None, data: dict[str, Any]) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


def _update_status(status_path: str | Path | None, **updates: Any) -> None:
    if not status_path:
        return
    data = _safe_read_json(status_path)
    data.update(updates)
    data["updated_at"] = _now()
    _safe_write_json(status_path, data)


def _row_text(row) -> str:
    try:
        return row.inner_text(timeout=5000).strip()
    except Exception:
        return ""


def _get_table_rows(page):
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
            text = _row_text(row)
            if text:
                rows.append(row)
        except Exception:
            continue
    return rows


def _find_identifier_input(page):
    selectors = [
        "input[placeholder*='数据标识']",
        "input[placeholder*='标识']",
        "input[placeholder*='输入']",
        "input[aria-label*='数据标识']",
        "input[aria-label*='标识']",
        "input[name*='data']",
        "input[name*='Data']",
        "input[id*='data']",
        "input[id*='Data']",
        ".el-input input",
        "input[type='text']",
        "input:not([type])",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                item = loc.nth(i)
                try:
                    if item.is_visible(timeout=1000) and item.is_enabled(timeout=1000):
                        return item
                except Exception:
                    continue
        except Exception:
            continue

    try:
        handle = page.evaluate_handle(
            """
            () => {
              const labels = Array.from(document.querySelectorAll('label, span, div, td, th'));
              const hit = labels.find(x => /数据标识|标识/.test((x.innerText || '').trim()));
              if (!hit) return null;
              let parent = hit.parentElement;
              for (let depth = 0; parent && depth < 5; depth++, parent = parent.parentElement) {
                const input = parent.querySelector('input');
                if (input) return input;
              }
              return null;
            }
            """
        )
        element = handle.as_element()
        if element:
            return element
    except Exception:
        pass
    return None


def _click_search_button(page) -> bool:
    candidates = [
        "button:has-text('查询')",
        "button:has-text('搜索')",
        "button:has-text('检索')",
        "button:has-text('筛选')",
        "a:has-text('查询')",
        "a:has-text('搜索')",
        "span:has-text('查询')",
        "span:has-text('搜索')",
        "input[type='submit']",
        ".el-button:has-text('查询')",
        ".el-button:has-text('搜索')",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible(timeout=1000) and item.is_enabled(timeout=1000):
                    item.click(timeout=5000)
                    page.wait_for_timeout(1800)
                    return True
        except Exception:
            continue
    return False


def _search_tile_id(page, tile_id: str, *, tile_scheme: str = "astgtm_1deg") -> dict[str, Any]:
    tile_id = normalize_gscloud_tile_id(tile_id, tile_scheme=tile_scheme)
    if not tile_id:
        return {"ok": False, "error": "空分幅编号"}

    inp = _find_identifier_input(page)
    if inp is None:
        return {
            "ok": False,
            "error": "未找到‘数据标识/标识’筛选输入框。为防止下载错误分幅，已停止自动点击。",
        }

    attempted: list[str] = []
    for search_term in _tile_search_terms(tile_id, tile_scheme=tile_scheme):
        attempted.append(search_term)
        try:
            inp.click(timeout=3000)
            inp.fill("", timeout=3000)
            inp.fill(search_term, timeout=5000)
            clicked = _click_search_button(page)
            if not clicked:
                inp.press("Enter")
                page.wait_for_timeout(1800)
        except Exception as exc:
            return {"ok": False, "error": f"填写数据标识失败：{exc}", "attempted_terms": attempted}

        for _ in range(10):
            rows = _get_table_rows(page)
            for row in rows:
                text = _row_text(row)
                if str(tile_scheme or "").lower() == "srtm_utm_5deg":
                    found = [x.lower() for x in re.findall(r"utm_srtm_\d{2}_\d{2}", text, flags=re.IGNORECASE)]
                else:
                    found = re.findall(r"ASTGTM_[NS]\d{2}[EW]\d{3}", text.upper())
                if tile_id in found:
                    return {
                        "ok": True,
                        "row": row,
                        "row_text": text,
                        "search_clicked": clicked,
                        "search_term": search_term,
                    }
            page.wait_for_timeout(800)
    return {
        "ok": False,
        "error": f"搜索结果中没有找到目标分幅 {tile_id}。已尝试：{', '.join(attempted)}",
        "attempted_terms": attempted,
    }


def _click_download_in_exact_row(row) -> bool:
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
        row.locator("a, button, i, span").nth(1),
    ]
    for loc in candidates:
        try:
            if loc.count() <= 0:
                continue
            item = loc.first
            if item.is_visible(timeout=1200):
                item.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


def download_gscloud_tiles_by_identifier_search(
    *,
    manager: DataManager,
    tile_ids: list[str],
    dataset_id: str = "310",
    pid: str = "1",
    tile_scheme: str = "astgtm_1deg",
    storage_state_path: str | Path = "",
    output_name: str = "",
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
    status_path: str | Path | None = None,
) -> dict[str, Any]:
    sync_playwright, PlaywrightTimeoutError = _ensure_playwright()
    expected = [normalize_gscloud_tile_id(str(x), tile_scheme=tile_scheme) for x in tile_ids if str(x or "").strip()]
    if not expected:
        raise ValueError("没有目标分幅，无法下载。")

    start_url = f"https://www.gscloud.cn/sources/accessdata/{dataset_id}?pid={str(pid or '1').strip() or '1'}"
    target_dir = Path(manager.workdir) / "domestic_downloads" / "gscloud"
    target_dir.mkdir(parents=True, exist_ok=True)
    timeout_ms = per_tile_download_timeout_ms(timeout_seconds)
    existing = existing_gscloud_tile_downloads(target_dir, expected, tile_scheme=tile_scheme)
    downloaded: list[Path] = list(existing.values())
    downloaded_tiles: set[str] = set(existing)
    not_found: list[str] = []
    errors: list[str] = []
    step_records: list[dict[str, Any]] = []
    started_at = _now()

    _update_status(
        status_path,
        state="IDENTIFIER_SEARCH_DOWNLOADING",
        message="正在按数据标识逐个搜索并下载目标分幅。",
        expected_count=len(expected),
        downloaded_count=0,
        target_tiles_preview=expected[:50],
    )

    with sync_playwright() as p:
        browser = _launch_visible_browser(p, headless=headless)
        context = _new_context(browser, storage_state_path)
        page = context.new_page()
        page.goto(start_url or GSCLOUD_ASTER_GDEM30_ACCESS_URL, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_selector("table, .el-table, .ivu-table, .ant-table, input", timeout=30_000)
        except Exception:
            pass

        for idx, tile_id in enumerate(expected, start=1):
            if tile_id in downloaded_tiles:
                step_records.append({"tile_id": tile_id, "status": "reused", "file": str(existing[tile_id])})
                continue
            _update_status(
                status_path,
                state="IDENTIFIER_SEARCH_DOWNLOADING",
                message=f"正在搜索 {idx}/{len(expected)}：{tile_id}",
                current_tile=tile_id,
                downloaded_count=len(downloaded_tiles),
                remaining_count=len(expected) - len(downloaded_tiles),
            )
            tile_errors: list[str] = []
            for attempt in range(1, 4):
                if attempt > 1:
                    try:
                        page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
                    except Exception:
                        pass
                search_result = _search_tile_id(page, tile_id, tile_scheme=tile_scheme)
                if not search_result.get("ok"):
                    tile_errors.append(str(search_result.get("error") or "not found"))
                    step_records.append({"tile_id": tile_id, "status": "search_retry", "attempt": attempt, "error": search_result.get("error")})
                    continue
                try:
                    with page.expect_download(timeout=timeout_ms) as dl_info:
                        clicked = _click_download_in_exact_row(search_result["row"])
                        if not clicked:
                            raise RuntimeError("找到目标行，但未找到可点击下载按钮。")
                    download = dl_info.value
                    saved = _save_download(download, target_dir, tile_id)
                    detected = extract_gscloud_tile_id_from_name(saved.name, tile_scheme=tile_scheme)
                    if detected != tile_id:
                        raise RuntimeError(f"下载文件校验失败：目标 {tile_id}，实际 {saved.name}，识别为 {detected or '无法识别'}。")
                    downloaded.append(saved)
                    downloaded_tiles.add(tile_id)
                    step_records.append({"tile_id": tile_id, "status": "downloaded", "attempt": attempt, "file": str(saved)})
                    _update_status(
                        status_path,
                        state="IDENTIFIER_SEARCH_DOWNLOADING",
                        message=f"已下载 {len(downloaded_tiles)}/{len(expected)}：{tile_id}",
                        current_tile=tile_id,
                        downloaded_count=len(downloaded_tiles),
                        remaining_count=len(expected) - len(downloaded_tiles),
                        last_download=str(saved),
                    )
                    break
                except PlaywrightTimeoutError:
                    tile_errors.append(f"第 {attempt} 次等待下载超时")
                    step_records.append({"tile_id": tile_id, "status": "download_timeout", "attempt": attempt})
                except Exception as exc:
                    tile_errors.append(str(exc))
                    step_records.append({"tile_id": tile_id, "status": "error", "attempt": attempt, "error": str(exc)})
            if tile_id not in downloaded_tiles:
                not_found.append(tile_id)
                errors.append(f"{tile_id}: {'; '.join(tile_errors[-3:])}")

        if storage_state_path:
            try:
                context.storage_state(path=str(storage_state_path))
            except Exception:
                pass
        browser.close()

    if not downloaded:
        raise RuntimeError(
            "没有成功下载任何目标分幅。"
            + (" 错误：" + "；".join(errors[:20]) if errors else "")
            + " 系统没有打开给用户随便选择；请检查登录态、数据标识输入框或网站权限。"
        )

    _update_status(status_path, download_steps=step_records, auto_tile_errors=errors, not_found_tile_ids=not_found)
    validation = validate_gscloud_tile_downloads_for_scheme(downloaded, expected, tile_scheme=tile_scheme)
    result = _postprocess_gscloud_files(manager, downloaded, get_source("gscloud"), output_name=output_name, auto_load=auto_load)
    result["tile_validation"] = validation
    result["requested_tile_ids"] = expected
    result["downloaded_tile_ids"] = sorted(downloaded_tiles)
    result["not_found_tile_ids"] = not_found
    result["download_steps"] = step_records
    result["auto_tile_errors"] = errors
    result["started_at"] = started_at
    result["finished_at"] = _now()
    result["message"] = (
        f"已按数据标识精确搜索并下载 {validation['downloaded_count']}/{validation['expected_count']} 个目标 DEM 分幅。"
        "所有下载文件均通过 ASTGTM 分幅编号校验。"
    )
    _update_status(
        status_path,
        state="COMPLETED",
        message="按数据标识精确搜索下载完成。",
        result_summary={
            "downloaded_count": validation["downloaded_count"],
            "expected_count": validation["expected_count"],
            "not_found_count": len(not_found),
        },
    )
    return result
