from __future__ import annotations

import os
import sys
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


BACKEND_URL = os.getenv("GIS_AGENT_BACKEND_URL", "http://127.0.0.1:8765")
FRONTEND_URL = os.getenv("GIS_AGENT_FRONTEND_URL", "http://127.0.0.1:5173")


def check_backend() -> None:
    with urlopen(f"{BACKEND_URL}/api/status", timeout=10) as response:
        body = response.read().decode("utf-8", errors="replace")
    if '"ok":true' not in body.replace(" ", "").lower():
        raise RuntimeError(f"backend status did not report ok=true: {body[:300]}")


def check_frontend() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.goto(FRONTEND_URL, wait_until="domcontentloaded", timeout=30_000)
        body_text = page.locator("body").inner_text(timeout=10_000).strip()
        html = page.content()
        browser.close()
    if len(body_text) < 20:
        raise RuntimeError("frontend body text is unexpectedly short")
    lowered = html.lower()
    if "vite error" in lowered or "uncaught" in lowered:
        raise RuntimeError("frontend appears to contain a runtime error")


def main() -> int:
    check_backend()
    check_frontend()
    print("E2E smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
