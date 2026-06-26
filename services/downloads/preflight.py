from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable


@dataclass
class DownloadPreflightService:
    commercial_service: Callable[[], Any]
    products: dict[str, Any]
    resolve_download_region: Callable[[str, str], dict[str, Any]]
    inspect_storage_state: Callable[[str], dict[str, Any]]
    verify_gscloud_scene_download: Callable[..., dict[str, Any]]
    workdir: str | Path | Callable[[], str | Path]

    def current_workdir(self) -> Path:
        value = self.workdir() if callable(self.workdir) else self.workdir
        return Path(value)

    def scoped_verification_dir(self, body: Any) -> Path:
        user_id = _safe_segment(getattr(body, "user_id", "") or "anonymous")
        session_id = _safe_segment(getattr(body, "session_id", "") or "default")
        return self.current_workdir() / "gscloud_download_verification" / "users" / user_id / "sessions" / session_id

    def product_key_from_resource(self, value: str) -> str:
        text = str(value or "").strip().lower()
        for product in self.products.values():
            if text in {str(product.key).lower(), str(product.resource_type).lower()}:
                return str(product.key)
        return text

    def resolve_storage_state(self, body: Any) -> str:
        source_key = str(getattr(body, "source_key", "") or "gscloud").lower()
        commercial = self.commercial_service()
        mode = commercial.resolve_account_mode(getattr(body, "user_id", ""), getattr(body, "account_mode", "auto"), source_key)
        if mode in {"own", "user", "user_account", "manual_cookie"}:
            return commercial.get_user_storage_state_path(getattr(body, "user_id", ""), source_key)
        check = commercial._select_platform_account(source_key)
        if not check.ok or not check.account_id:
            raise PermissionError(check.reason or "No available platform account.")
        account = commercial.get_platform_account_private(check.account_id)
        return str(account.get("storage_state_path") or "")

    def login_health(self, user_id: str, source_key: str = "gscloud", account_mode: str = "platform") -> dict[str, Any]:
        source = str(source_key or "gscloud").lower()
        mode = str(account_mode or "platform").lower()
        commercial = self.commercial_service()
        if mode == "own":
            state_path = commercial.get_user_storage_state_path(user_id, source)
        else:
            check = commercial._select_platform_account(source)
            if not check.ok or not check.account_id:
                raise PermissionError(check.reason or "No available platform account.")
            account = commercial.get_platform_account_private(check.account_id)
            state_path = str(account.get("storage_state_path") or "")
        return {"source_key": source, "account_mode": mode, "login_health": self.inspect_storage_state(state_path)}

    def preflight(self, body: Any) -> dict[str, Any]:
        if str(getattr(body, "source_key", "") or "").lower() != "gscloud":
            raise ValueError("Current preflight endpoint only supports GSCloud scene products.")
        product_key = self.product_key_from_resource(getattr(body, "product_key", "") or getattr(body, "resource_type", ""))
        if product_key not in self.products:
            raise ValueError(f"Unsupported GSCloud preflight product: {getattr(body, 'product_key', '') or getattr(body, 'resource_type', '')}")
        region = self.resolve_download_region(str(getattr(body, "request_text", "") or ""), str(getattr(body, "region", "") or ""))
        if not region.get("ok"):
            return {
                "state": "NEEDS_REGION",
                "ok": False,
                "product_key": product_key,
                "region_resolution": region,
                "message": region["message"],
            }
        state_path = self.resolve_storage_state(body)
        login_health = self.inspect_storage_state(state_path)
        if not login_health.get("ok"):
            return {
                "state": "NEEDS_LOGIN",
                "ok": False,
                "product_key": product_key,
                "login_health": login_health,
                "message": "Current GSCloud login state is unavailable. Please log in again or update the platform account cookie.",
            }
        result = self.verify_gscloud_scene_download(
            product_key=product_key,
            storage_state_path=state_path,
            download_dir=self.scoped_verification_dir(body),
            execute_download=False,
            max_pages=max(1, int(getattr(body, "max_pages", 1) or 1)),
            timeout_seconds=600,
            headless=True,
            options={
                "region": region["region"],
                "start_date": getattr(body, "start_date", ""),
                "end_date": getattr(body, "end_date", ""),
                "cloud_max": getattr(body, "cloud_max", 30.0),
                "processing_level": getattr(body, "processing_level", ""),
            },
        )
        return {"ok": True, **result, "region_resolution": region}


def _safe_segment(value: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value or "").strip()).strip("._-")
    return clean[:80] or "default"
