from __future__ import annotations

import unittest

from api_server import AskIn
from core.frontend_context import apply_frontend_context_to_state, sanitize_frontend_context
from core.conversation_state import ConversationState


class FrontendContextPayloadTests(unittest.TestCase):
    def test_sanitizes_selected_objects_and_bounds(self) -> None:
        payload = sanitize_frontend_context(
            {
                "session_id": "session_1",
                "active_dataset_id": "soil_points",
                "selected_artifact_id": "artifact_1",
                "selected_artifact_type": "map",
                "selected_artifact_path": "plots/soil_map.png",
                "selected_layer_id": "result_soil_point",
                "selected_feature_id": "station_001",
                "selected_feature_properties": {"name": "A", "value": 0.12},
                "selected_map_bounds": [100, 20, 101, 21],
                "selected_model_result_id": "xgb_soil",
                "active_task_id": "task_1",
                "last_visible_panel": "analysis",
                "user_focus_hint": "checking anomaly",
            }
        )

        self.assertEqual(payload["selected_artifact_path"], "plots/soil_map.png")
        self.assertEqual(payload["selected_map_bounds"], [100.0, 20.0, 101.0, 21.0])
        self.assertEqual(payload["selected_feature_properties"]["value"], 0.12)

    def test_large_feature_properties_are_truncated_and_sensitive_keys_filtered(self) -> None:
        payload = sanitize_frontend_context(
            {
                "selected_feature_properties": {
                    "name": "A" * 300,
                    "token": "secret",
                    "raw_content": "x" * 1000,
                    **{f"k{i}": i for i in range(20)},
                }
            }
        )

        props = payload["selected_feature_properties"]
        self.assertLessEqual(len(props), 12)
        self.assertLessEqual(len(props["name"]), 200)
        self.assertNotIn("token", props)
        self.assertNotIn("raw_content", props)

    def test_large_file_content_is_not_allowed_in_payload(self) -> None:
        payload = sanitize_frontend_context(
            {
                "selected_artifact_id": "a1",
                "file_content": "x" * 10000,
                "base64_image": "abcd",
                "selected_feature_properties": {"html": "<b>large</b>", "safe": "ok"},
            }
        )

        self.assertNotIn("file_content", payload)
        self.assertNotIn("base64_image", payload)
        self.assertEqual(payload["selected_feature_properties"], {"safe": "ok"})

    def test_top_level_context_values_do_not_keep_obvious_secrets(self) -> None:
        payload = sanitize_frontend_context(
            {
                "user_focus_hint": "please inspect token=sk-secret-value",
                "active_task_id": "task_cookie=session-secret",
                "selected_layer_id": "safe_layer",
            }
        )

        self.assertNotIn("user_focus_hint", payload)
        self.assertNotIn("active_task_id", payload)
        self.assertEqual(payload["selected_layer_id"], "safe_layer")

    def test_selected_artifact_path_rejects_large_or_escaping_payload_values(self) -> None:
        for bad_path in (
            "data:image/png;base64," + "a" * 500,
            "../outside/secret.png",
            "%2e%2e/outside/secret.png",
            "/api/files/artifact?path=../outside/secret.png",
            "/api/files/artifact?path=%2e%2e%2Foutside%2Fsecret.png",
            "C:/Users/example/secret.png",
            "https://example.com/remote.png",
        ):
            with self.subTest(path=bad_path[:24]):
                payload = sanitize_frontend_context({"selected_artifact_id": "a1", "selected_artifact_path": bad_path})

                self.assertEqual(payload.get("selected_artifact_id"), "a1")
                self.assertNotIn("selected_artifact_path", payload)

    def test_askin_accepts_legacy_payload_without_frontend_context(self) -> None:
        body = AskIn(prompt="hello")

        self.assertEqual(body.frontend_context, {})

    def test_apply_frontend_context_updates_conversation_state(self) -> None:
        state = ConversationState()
        payload = sanitize_frontend_context(
            {
                "active_dataset_id": "soil_points",
                "selected_artifact_id": "artifact_1",
                "selected_artifact_type": "map",
                "selected_artifact_path": "plots/soil_map.png",
                "selected_layer_id": "layer_1",
                "selected_feature_id": "feature_1",
                "selected_feature_properties": {"name": "Station A"},
                "selected_map_bounds": [100, 20, 101, 21],
                "selected_model_result_id": "xgb_soil",
                "active_task_id": "task_1",
            }
        )

        apply_frontend_context_to_state(state, payload)

        self.assertEqual(state.active_dataset, "soil_points")
        self.assertEqual(state.selected_artifact["id"], "artifact_1")
        self.assertEqual(state.selected_feature["properties"]["name"], "Station A")
        self.assertEqual(state.selected_map_bounds, [100.0, 20.0, 101.0, 21.0])
        self.assertEqual(state.selected_model_result["id"], "xgb_soil")
        self.assertEqual(state.active_task["id"], "task_1")


if __name__ == "__main__":
    unittest.main()
