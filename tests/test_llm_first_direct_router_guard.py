from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from core.domestic_sources.intent_router import GSCloudIntentRoute
from core.chat_response import build_chat_response
from core.config import Settings
from core.service import GISWorkspaceService


class LLMFirstDirectRouterGuardTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_gscloud_chat_download_requires_confirmation_before_submit(self) -> None:
        from api_server import _gscloud_chat_download_confirmation_result

        route = GSCloudIntentRoute(kind="matched", product_key="gscloud_dem", resource_type="dem", confidence=0.9)

        result = _gscloud_chat_download_confirmation_result("download DEM for Chengdu", "gscloud_dem", route)

        self.assertIsNotNone(result)
        self.assertEqual(result["model"], "direct-router")
        self.assertEqual(result["reason"], "commercial_download_requires_confirmation")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["download_guard"], "llm_first_confirmation")
        self.assertEqual(result["action_required"]["type"], "confirmation_required")
        self.assertEqual(result["action_required"]["confirmed_action_id"], result["confirmed_action_id"])
        self.assertEqual(result["intent_route"]["product_key"], "gscloud_dem")
        self.assertIn(result["confirmed_action_id"], result["reply"])

    def test_gscloud_chat_download_confirmation_token_allows_submit_path(self) -> None:
        from api_server import _gscloud_chat_download_confirmation_id, _gscloud_chat_download_confirmation_result

        prompt = "download DEM for Chengdu"
        token = _gscloud_chat_download_confirmation_id(prompt, "gscloud_dem")

        result = _gscloud_chat_download_confirmation_result(f"{prompt} confirmed_action_id={token}", "gscloud_dem")

        self.assertIsNone(result)

    def test_chat_response_persists_download_confirmation_action_required(self) -> None:
        from api_server import _gscloud_chat_download_confirmation_result

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            result = _gscloud_chat_download_confirmation_result("download DEM for Chengdu", "gscloud_dem")

            response = build_chat_response(
                service,
                user_prompt="download DEM for Chengdu",
                result=result or {},
                meta_keys=("model", "reason", "requires_confirmation", "confirmed_action_id", "download_guard", "intent_route", "action_required"),
            )

            assistant = response["messages"][-1]
            action = assistant["meta"]["action_required"]
            self.assertEqual(action["type"], "confirmation_required")
            self.assertEqual(action["confirmed_action_id"], result["confirmed_action_id"])
            self.assertEqual(action["confirmation_prompt"], "download DEM for Chengdu")

    def test_confirmation_chat_response_helper_persists_required_meta(self) -> None:
        from api_server import _build_gscloud_confirmation_chat_response, _gscloud_chat_download_confirmation_result, GSCLOUD_CONFIRMATION_META_KEYS

        self.assertIn("action_required", GSCLOUD_CONFIRMATION_META_KEYS)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            confirmation = _gscloud_chat_download_confirmation_result("download DEM for Chengdu", "gscloud_dem")

            response = _build_gscloud_confirmation_chat_response(
                service,
                user_prompt="download DEM for Chengdu",
                confirmation=confirmation or {},
            )

            assistant = response["messages"][-1]
            self.assertEqual(assistant["meta"]["reason"], "commercial_download_requires_confirmation")
            self.assertEqual(assistant["meta"]["download_guard"], "llm_first_confirmation")
            self.assertEqual(assistant["meta"]["action_required"]["type"], "confirmation_required")

    def test_gscloud_direct_download_routes_are_table_driven_and_unique(self) -> None:
        from api_server import GSCLOUD_DIRECT_DOWNLOAD_ROUTES, _match_gscloud_direct_download_route

        product_keys = [route["product_key"] for route in GSCLOUD_DIRECT_DOWNLOAD_ROUTES]

        self.assertIn("gscloud_dem", product_keys)
        self.assertEqual(len(product_keys), len(set(product_keys)))
        for route in GSCLOUD_DIRECT_DOWNLOAD_ROUTES:
            self.assertTrue(callable(route["matches"]))
            self.assertTrue(callable(route["submit"]))
            self.assertIsInstance(route["result_meta_keys"], tuple)

        import api_server

        original_routes = api_server.GSCLOUD_DIRECT_DOWNLOAD_ROUTES
        try:
            api_server.GSCLOUD_DIRECT_DOWNLOAD_ROUTES = (
                {
                    "product_key": "test_product",
                    "matches": lambda prompt: prompt == "match me",
                    "submit": lambda user_id, prompt, session_id="": {"ok": True},
                    "result_meta_keys": ("model", "reason"),
                },
            )
            matched = _match_gscloud_direct_download_route("match me")
            missed = _match_gscloud_direct_download_route("ignore me")
        finally:
            api_server.GSCLOUD_DIRECT_DOWNLOAD_ROUTES = original_routes

        self.assertIsNotNone(matched)
        self.assertEqual(matched["product_key"], "test_product")
        self.assertIsNone(missed)

    def test_gscloud_intent_route_submit_uses_route_registry(self) -> None:
        import api_server
        from api_server import _gscloud_direct_download_route_by_product_key, _submit_gscloud_intent_route_from_chat

        original_routes = api_server.GSCLOUD_DIRECT_DOWNLOAD_ROUTES
        calls: list[tuple[str, str, str]] = []
        try:
            api_server.GSCLOUD_DIRECT_DOWNLOAD_ROUTES = (
                {
                    "product_key": "test_product",
                    "matches": lambda prompt: False,
                    "submit": lambda user_id, prompt, session_id="": calls.append((user_id, prompt, session_id)) or {"reply": "ok", "model": "direct-router", "reason": "test_submit"},
                    "result_meta_keys": ("model", "reason"),
                },
            )
            route = GSCloudIntentRoute(kind="matched", product_key="test_product", resource_type="test", confidence=0.9)

            matched = _gscloud_direct_download_route_by_product_key("test_product")
            result = _submit_gscloud_intent_route_from_chat("u_1", "download test", route, session_id="s_1")
        finally:
            api_server.GSCLOUD_DIRECT_DOWNLOAD_ROUTES = original_routes

        self.assertIsNotNone(matched)
        self.assertEqual(result["reason"], "test_submit")
        self.assertEqual(calls, [("u_1", "download test", "s_1")])


if __name__ == "__main__":
    unittest.main()
