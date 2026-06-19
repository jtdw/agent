from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .gscloud_download_recovery import recover_gscloud_download_from_error_page


AVAILABLE = "\u6709"
UNAVAILABLE = "\u65e0"
DOWNLOAD_BUTTON_SELECTORS = [
    ".download-img",
    "img[title*='下载']",
    "img[value*='下载']",
    "[title*='下载']",
    "button:has-text('下载')",
    "a:has-text('下载')",
    "i[class*='download']",
    "i[class*='down']",
    ".fa-download",
    ".layui-icon-download-circle",
    "td:last-child img",
    "td:last-child i",
    "td:last-child button",
    "td:last-child a",
]


@dataclass(frozen=True)
class SceneTableScanResult:
    records: list[dict[str, Any]]
    pages_scanned: int
    stop_reason: str
    row_count: int


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _safe_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def update_scene_status(status_path: str | Path | None, **updates: Any) -> None:
    if not status_path:
        return
    path = Path(status_path)
    data = _safe_read_json(path)
    data.update(updates)
    data["updated_at"] = _now()
    _safe_write_json(path, data)


def default_scene_max_pages(max_pages: int | str | None = 0) -> int:
    value = int(max_pages or 0)
    if value <= 0:
        value = int(os.getenv("GSCLOUD_SCENE_MAX_PAGES", "20") or "20")
    return max(1, value)


def get_scene_table_rows(page) -> list[Any]:
    selectors = [
        "table tbody tr",
        ".el-table__body-wrapper tbody tr",
        ".el-table__row",
        ".ivu-table-body tbody tr",
        ".ant-table-tbody tr",
        "tbody tr",
        "tr",
    ]
    best = None
    best_count = 0
    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = loc.count()
            if count > best_count:
                best = loc
                best_count = count
        except Exception:
            continue
    if best is None or best_count <= 0:
        return []
    rows: list[Any] = []
    for idx in range(best_count):
        try:
            row = best.nth(idx)
            text = row.inner_text(timeout=2000).strip()
            if text:
                rows.append(row)
        except Exception:
            continue
    return rows


def row_text(row) -> str:
    try:
        return row.inner_text(timeout=3000).strip()
    except Exception:
        return ""


def find_scene_row_by_id(rows: list[Any], scene_id: str):
    scene_id = str(scene_id or "").strip()
    if not scene_id:
        return None
    for row in rows:
        if scene_id in row_text(row):
            return row
    return None


def _identifier_input_score(item) -> int:
    try:
        return int(
            item.evaluate(
                """
                (el) => {
                  const attr = (name) => (el.getAttribute(name) || '').trim();
                  const text = [
                    attr('placeholder'),
                    attr('aria-label'),
                    attr('title'),
                    attr('name'),
                    attr('id'),
                    attr('class')
                  ].join(' ');
                  const lower = text.toLowerCase();
                  const placeholder = attr('placeholder');
                  const type = attr('type').toLowerCase();
                  if (type === 'number') return 0;

                  let context = '';
                  for (let node = el, depth = 0; node && depth < 5; node = node.parentElement, depth += 1) {
                    context += ' ' + ((node.innerText || '').replace(/\\s+/g, ' ').slice(0, 500));
                    context += ' ' + ((node.className || '').toString());
                  }
                  const all = `${text} ${context}`;
                  const pageLike = /分页|页码|跳页|跳转|上一页|下一页|pagination|pager|page-|page_|laypage|btn-next|btn-prev|共\\s*\\d+\\s*页|第\\s*\\d*\\s*共/i;
                  const identifierLike = /数据标识|输入数据标识|data\\s*id|dataid|identifier/i;

                  if (identifierLike.test(placeholder)) return 120;
                  if (/标识/.test(placeholder) && !/页|页码|分页/.test(placeholder)) return 100;
                  if (identifierLike.test(text)) return pageLike.test(lower) ? 50 : 90;
                  if (identifierLike.test(all) && !pageLike.test(all)) return 70;
                  return 0;
                }
                """
            )
        )
    except Exception:
        return 0


def find_identifier_filter_input(page):
    """Return the GSCloud data-identifier filter input, never the page jump box."""
    try:
        loc = page.locator("input")
        scored: list[tuple[int, int, Any]] = []
        for idx in range(loc.count()):
            item = loc.nth(idx)
            try:
                if not item.is_visible(timeout=1000) or not item.is_enabled(timeout=1000):
                    continue
            except Exception:
                continue
            score = _identifier_input_score(item)
            if score > 0:
                scored.append((score, -idx, item))
        if scored:
            scored.sort(reverse=True, key=lambda value: (value[0], value[1]))
            return scored[0][2]
    except Exception:
        pass
    return None


def _click_scene_search_button(page) -> bool:
    selectors = [
        "button:has-text('查询')",
        "button:has-text('搜索')",
        "button:has-text('检索')",
        "button:has-text('筛选')",
        "a:has-text('查询')",
        "a:has-text('搜索')",
        ".el-button:has-text('查询')",
        ".el-button:has-text('搜索')",
        "input[type='submit']",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for idx in range(loc.count()):
                item = loc.nth(idx)
                if item.is_visible(timeout=1000) and item.is_enabled(timeout=1000):
                    item.click(timeout=5000)
                    page.wait_for_timeout(1800)
                    return True
        except Exception:
            continue
    return False


def search_scene_row_by_id(page, scene_id: str, parse_row: Callable[[Any, int], dict[str, Any] | None] | None = None):
    """Relocate a scene row through the table's identifier search box.

    GSCloud scene tables can re-render or change pagination after filters are
    reapplied. Searching by the selected scene id is safer than relying only on
    the page number captured during the initial scan.
    """
    scene_id = str(scene_id or "").strip()
    if not scene_id:
        return None
    inp = find_identifier_filter_input(page)
    if inp is None:
        return None
    try:
        inp.click(timeout=3000)
        inp.fill("", timeout=3000)
        inp.fill(scene_id, timeout=5000)
        if not _click_scene_search_button(page):
            inp.press("Enter")
            page.wait_for_timeout(1800)
    except Exception:
        return None

    for _ in range(10):
        rows = get_scene_table_rows(page)
        row = find_scene_row_by_id(rows, scene_id)
        if row is not None:
            return row
        if parse_row is not None:
            for idx, candidate in enumerate(rows):
                try:
                    parsed = parse_row(candidate, idx)
                except Exception:
                    parsed = None
                if parsed and str(parsed.get("scene_id") or "").strip().upper() == scene_id.upper():
                    return candidate
        page.wait_for_timeout(800)
    return None


def click_scene_row_download(page, row, timeout_ms: int):
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


def _is_disabled(locator) -> bool:
    try:
        if locator.get_attribute("disabled", timeout=1000) is not None:
            return True
    except Exception:
        pass
    try:
        cls = locator.get_attribute("class", timeout=1000) or ""
        if any(token in cls.lower() for token in ("disabled", "is-disabled", "layui-disabled")):
            return True
    except Exception:
        pass
    try:
        return str(locator.get_attribute("aria-disabled", timeout=1000)).lower() == "true"
    except Exception:
        return False


def click_next_scene_page(page) -> bool:
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
    for selector in candidates:
        try:
            loc = page.locator(selector).last
            if loc.count() <= 0:
                continue
            if not loc.is_visible(timeout=1000):
                continue
            if _is_disabled(loc):
                continue
            loc.click(timeout=5000)
            page.wait_for_timeout(1500)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            return True
        except Exception:
            continue
    return False


def scan_scene_table_pages(
    page,
    parse_row: Callable[[Any, int], dict[str, Any] | None],
    *,
    max_pages: int = 0,
    status_path: str | Path | None = None,
    stop_when: Callable[[list[dict[str, Any]]], bool] | None = None,
) -> SceneTableScanResult:
    max_pages = default_scene_max_pages(max_pages)
    records: list[dict[str, Any]] = []
    signatures: set[str] = set()
    pages_scanned = 0
    row_count = 0
    stop_reason = ""

    while pages_scanned < max_pages:
        pages_scanned += 1
        rows = get_scene_table_rows(page)
        row_count += len(rows)
        first_text = row_text(rows[0])[:160] if rows else ""
        last_text = row_text(rows[-1])[:160] if rows else ""

        for row_index, row in enumerate(rows):
            parsed = parse_row(row, row_index)
            if not parsed:
                continue
            parsed = dict(parsed)
            parsed["page_no"] = pages_scanned
            parsed["row_index"] = row_index
            parsed["row_text"] = row_text(row)
            records.append(parsed)

        update_scene_status(
            status_path,
            state="SCANNING",
            pages_scanned=pages_scanned,
            candidate_count=len(records),
            row_count=row_count,
        )
        if stop_when and stop_when(records):
            stop_reason = "stop condition satisfied"
            break

        signature = f"{page.url}|{first_text}|{last_text}|{len(rows)}"
        if signature in signatures and pages_scanned > 1:
            stop_reason = "repeated page signature"
            break
        signatures.add(signature)

        if pages_scanned >= max_pages:
            stop_reason = f"reached max_pages={max_pages}"
            break
        if not click_next_scene_page(page):
            stop_reason = "no next page"
            break

    return SceneTableScanResult(records=records, pages_scanned=pages_scanned, stop_reason=stop_reason, row_count=row_count)


def select_scene_records(
    records: list[dict[str, Any]],
    *,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    max_scenes: int = 1,
    extra_filter: Callable[[dict[str, Any]], bool] | None = None,
    extra_skip_reason: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    max_scenes = max(1, int(max_scenes or 1))
    candidates: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        if item.get("data_available") != AVAILABLE:
            item["skip_reason"] = "数据列不是“有”，不可下载。"
        elif year and item.get("year") and item["year"] != str(year):
            item["skip_reason"] = f"年份 {item.get('year')} 不等于 {year}。"
        elif start_date and item.get("date") and item["date"] < start_date:
            item["skip_reason"] = f"日期早于 {start_date}。"
        elif end_date and item.get("date") and item["date"] > end_date:
            item["skip_reason"] = f"日期晚于 {end_date}。"
        elif extra_filter and not extra_filter(item):
            item["skip_reason"] = extra_skip_reason or "不满足产品筛选条件。"
        candidates.append(item)

    selected = sorted(
        [item for item in candidates if not item.get("skip_reason")],
        key=lambda item: item.get("date") or "",
        reverse=True,
    )[:max_scenes]
    return selected, candidates


def goto_scene_page(page, start_url: str, target_page_no: int, after_goto: Callable[[Any], None] | None = None) -> None:
    target = max(1, int(target_page_no or 1))
    page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_selector("table, .el-table, .ivu-table, .ant-table, tr", timeout=30_000)
    except Exception:
        pass
    if after_goto:
        after_goto(page)
    for _ in range(1, target):
        if not click_next_scene_page(page):
            raise RuntimeError(f"无法跳转到第 {target} 页。")
