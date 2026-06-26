from __future__ import annotations

from types import SimpleNamespace

from services.downloads.preflight import DownloadPreflightService


def test_download_preflight_service_resolves_product_key_and_storage_state() -> None:
    calls: list[tuple[str, object]] = []

    class Product:
        key = "landsat"
        resource_type = "landsat8_oli_tirs"

    class FakeCommercial:
        def resolve_account_mode(self, user_id: str, account_mode: str, source_key: str) -> str:
            calls.append(("mode", (user_id, account_mode, source_key)))
            return "own"

        def get_user_storage_state_path(self, user_id: str, source_key: str) -> str:
            calls.append(("user_state", (user_id, source_key)))
            return "user-state.json"

    service = DownloadPreflightService(
        commercial_service=lambda: FakeCommercial(),
        products={"landsat": Product()},
        resolve_download_region=lambda request_text, region: {"ok": True, "region": region},
        inspect_storage_state=lambda path: {"ok": True, "path": path},
        verify_gscloud_scene_download=lambda **kwargs: {"verified": True, "storage_state_path": kwargs["storage_state_path"], "download_dir": str(kwargs["download_dir"])},
        workdir=lambda: "E:/work",
    )

    body = SimpleNamespace(user_id="u1", session_id="s1", account_mode="own", source_key="gscloud", resource_type="landsat8_oli_tirs", product_key="", region="chengdu", request_text="", start_date="", end_date="", max_pages=1, cloud_max=30.0, processing_level="")

    assert service.product_key_from_resource("landsat8_oli_tirs") == "landsat"
    assert service.resolve_storage_state(body) == "user-state.json"
    preflight = service.preflight(body)
    assert preflight["storage_state_path"] == "user-state.json"
    assert "users/u1/sessions/s1" in str(preflight["download_dir"]).replace("\\", "/")
    assert ("user_state", ("u1", "gscloud")) in calls


def test_download_preflight_service_uses_platform_account_and_reports_login_health() -> None:
    class Check:
        ok = True
        account_id = "acct1"
        reason = ""

    class FakeCommercial:
        def resolve_account_mode(self, user_id: str, account_mode: str, source_key: str) -> str:
            return "platform"

        def _select_platform_account(self, source_key: str) -> Check:
            return Check()

        def get_platform_account_private(self, account_id: str) -> dict:
            return {"account_id": account_id, "storage_state_path": "platform-state.json"}

    service = DownloadPreflightService(
        commercial_service=lambda: FakeCommercial(),
        products={},
        resolve_download_region=lambda request_text, region: {"ok": True, "region": region},
        inspect_storage_state=lambda path: {"ok": bool(path), "path": path},
        verify_gscloud_scene_download=lambda **kwargs: {"verified": True},
        workdir=lambda: "E:/work",
    )

    body = SimpleNamespace(user_id="u1", account_mode="auto", source_key="gscloud")

    assert service.resolve_storage_state(body) == "platform-state.json"
    health = service.login_health("u1", "gscloud", "platform")
    assert health["account_mode"] == "platform"
    assert health["login_health"]["path"] == "platform-state.json"


def test_download_preflight_service_returns_needs_region_or_login_without_verification() -> None:
    verify_calls: list[bool] = []

    class Product:
        key = "landsat"
        resource_type = "landsat8_oli_tirs"

    class FakeCommercial:
        def resolve_account_mode(self, user_id: str, account_mode: str, source_key: str) -> str:
            return "own"

        def get_user_storage_state_path(self, user_id: str, source_key: str) -> str:
            return "missing-state.json"

    service = DownloadPreflightService(
        commercial_service=lambda: FakeCommercial(),
        products={"landsat": Product()},
        resolve_download_region=lambda request_text, region: {"ok": False, "message": "need region"},
        inspect_storage_state=lambda path: {"ok": False, "path": path},
        verify_gscloud_scene_download=lambda **kwargs: verify_calls.append(True) or {"verified": True},
        workdir=lambda: "E:/work",
    )
    body = SimpleNamespace(user_id="u1", account_mode="own", source_key="gscloud", resource_type="landsat", product_key="", region="", request_text="", start_date="", end_date="", max_pages=1, cloud_max=30.0, processing_level="")

    assert service.preflight(body)["state"] == "NEEDS_REGION"
    assert verify_calls == []

    service.resolve_download_region = lambda request_text, region: {"ok": True, "region": "chengdu"}
    assert service.preflight(body)["state"] == "NEEDS_LOGIN"
    assert verify_calls == []
