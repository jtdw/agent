from __future__ import annotations

import os
from typing import Any


def normalize_refresh_attempts(value: Any, default: int = 3, maximum: int = 8) -> int:
    try:
        attempts = int(value)
    except Exception:
        attempts = int(default)
    return max(0, min(int(maximum), attempts))


def is_gscloud_transient_download_error(url: str = "", title: str = "", text: str = "") -> bool:
    haystack = "\n".join(str(part or "") for part in (url, title, text))
    lowered = haystack.lower()
    if "gscloud.cn" not in lowered:
        return False
    if "/sources/download" not in lowered and "bjdl.gscloud.cn" not in lowered:
        return False
    error_markers = (
        "http error 404",
        "err_http_response_code_failure",
        "找不到此",
        "找不到以下 web 地址",
        "找不到以下web地址",
        "this page could not be found",
        "404 not found",
    )
    return any(marker in lowered for marker in error_markers)


def current_page_is_gscloud_transient_download_error(page) -> bool:
    try:
        url = str(getattr(page, "url", "") or "")
    except Exception:
        url = ""
    try:
        title = str(page.title(timeout=1500) or "")
    except Exception:
        title = ""
    try:
        text = str(page.locator("body").inner_text(timeout=1500) or "")
    except Exception:
        text = ""
    return is_gscloud_transient_download_error(url, title, text)


def _click_browser_refresh_button(page) -> bool:
    selectors = (
        "button:has-text('刷新')",
        "button:has-text('重新加载')",
        "button:has-text('Reload')",
        "#reload-button",
    )
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() <= 0:
                continue
            item = loc.first
            if item.is_visible(timeout=800):
                item.click(timeout=1500)
                return True
        except Exception:
            continue
    return False


def recover_gscloud_download_from_error_page(
    page,
    *,
    timeout_ms: int,
    playwright_timeout_error: type[Exception] | tuple[type[Exception], ...],
    max_refreshes: int | None = None,
):
    attempts = normalize_refresh_attempts(
        os.getenv("GSCLOUD_DOWNLOAD_REFRESH_ATTEMPTS", "") if max_refreshes is None else max_refreshes
    )
    if attempts <= 0 or not current_page_is_gscloud_transient_download_error(page):
        return None

    per_attempt_timeout = max(8_000, min(int(timeout_ms or 30_000), 30_000))
    for attempt in range(1, attempts + 1):
        try:
            with page.expect_download(timeout=per_attempt_timeout) as dl_info:
                if not _click_browser_refresh_button(page):
                    try:
                        page.reload(wait_until="commit", timeout=per_attempt_timeout)
                    except Exception:
                        # A reload that turns into a download can interrupt navigation.
                        pass
            return dl_info.value
        except playwright_timeout_error:
            if attempt >= attempts or not current_page_is_gscloud_transient_download_error(page):
                return None
            continue
        except Exception:
            if attempt >= attempts:
                return None
            continue
    return None
