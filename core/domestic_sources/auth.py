from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .base import DomesticSource


def source_state_dir(workdir: Path) -> Path:
    path = Path(workdir) / "domestic_auth"
    path.mkdir(parents=True, exist_ok=True)
    return path


def source_download_dir(workdir: Path, source_key: str) -> Path:
    path = Path(workdir) / "domestic_downloads" / source_key
    path.mkdir(parents=True, exist_ok=True)
    return path


def storage_state_path(workdir: Path, source: DomesticSource) -> Path:
    return source_state_dir(workdir) / source.storage_file_name


def credential_status(source: DomesticSource) -> dict[str, Any]:
    username = os.getenv(source.username_env or "") if source.username_env else None
    password = os.getenv(source.password_env or "") if source.password_env else None
    return {
        "source_key": source.key,
        "source_name": source.name,
        "username_env": source.username_env,
        "password_env": source.password_env,
        "has_username": bool(username),
        "has_password": bool(password),
        "username_preview": _mask(username),
        "password_preview": "***" if password else "",
    }


def _mask(value: str | None) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "***" + value[-2:]


def load_cookies_from_storage_state(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        return cookies if isinstance(cookies, list) else []
    except Exception:
        return []


def open_manual_login_window(source: DomesticSource, workdir: Path, timeout_seconds: int = 300, headless: bool = False) -> dict[str, Any]:
    """打开浏览器，让用户手动登录，并保存 Playwright storage_state。

    说明：不自动破解验证码、不绕过权限。若网站有验证码，用户在浏览器中正常输入即可。
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "缺少 Playwright。请先执行: pip install playwright && python -m playwright install chromium"
        ) from exc

    state_path = storage_state_path(workdir, source)
    timeout_seconds = max(20, int(timeout_seconds or 300))
    url = source.login_url or source.home_url

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_kwargs: dict[str, Any] = {"accept_downloads": True}
        if state_path.exists():
            context_kwargs["storage_state"] = str(state_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        # 这里不使用 input()，避免在 Streamlit / 桌面 GUI 里阻塞无法操作。
        # 用户在 timeout 秒内完成登录即可，到时自动保存 Cookie。
        page.bring_to_front()
        time.sleep(timeout_seconds)
        context.storage_state(path=str(state_path))
        browser.close()

    return {
        "source_key": source.key,
        "source_name": source.name,
        "storage_state_path": str(state_path),
        "exists": state_path.exists(),
        "timeout_seconds": timeout_seconds,
        "message": "已保存浏览器登录状态。若未完成登录，请延长 timeout_seconds 后重新执行。",
    }
