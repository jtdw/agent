from __future__ import annotations

import unittest

from core.conversation_state import ConversationState
from core.followup_resolver import resolve_followup


class FollowupResolverFrontendContextTests(unittest.TestCase):
    def test_selected_artifact_takes_priority_for_result_followup(self) -> None:
        state = ConversationState(
            active_artifacts=[{"name": "old_map.png", "path": "plots/old_map.png"}],
            selected_artifact={"id": "artifact_1", "type": "map", "path": "plots/current_map.png"},
        ).to_dict()

        resolved = resolve_followup("这个结果说明什么", state, {})

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["reason"], "matched_frontend_selected_artifact")
        self.assertEqual(resolved["referenced_object"]["source"], "frontend_context")
        self.assertEqual(resolved["referenced_object"]["type"], "artifact")
        self.assertIn("current_map.png", resolved["referenced_object"]["path"])

    def test_selected_artifact_id_resolves_matching_dashboard_record(self) -> None:
        state = ConversationState(
            selected_artifact={"id": "artifact_current", "type": "map", "path": "stale/path.png", "source": "frontend_context"},
        ).to_dict()
        dashboard = {
            "artifacts": [
                {"artifact_id": "artifact_old", "type": "map", "path": "plots/old.png"},
                {"artifact_id": "artifact_current", "type": "map", "path": "plots/current.png", "title": "Current map"},
            ]
        }

        resolved = resolve_followup("这个结果说明什么", state, dashboard)

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["reason"], "matched_frontend_selected_artifact")
        self.assertEqual(resolved["referenced_object"]["id"], "artifact_current")
        self.assertEqual(resolved["referenced_object"]["path"], "plots/current.png")
        self.assertEqual(resolved["referenced_object"]["data"]["title"], "Current map")

    def test_selected_feature_takes_priority_for_place_followup(self) -> None:
        state = ConversationState(
            selected_feature={
                "id": "feature_1",
                "layer_id": "soil_points",
                "properties": {"name": "Station A", "value": 0.42},
            }
        ).to_dict()

        resolved = resolve_followup("这个地方为什么异常", state, {})

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["reason"], "matched_frontend_selected_feature")
        self.assertEqual(resolved["referenced_object"]["type"], "feature")
        self.assertEqual(resolved["referenced_object"]["properties"]["name"], "Station A")

    def test_selected_model_result_takes_priority_for_model_followup(self) -> None:
        state = ConversationState(
            last_model_result={"model": "RF", "output_prefix": "old_rf"},
            selected_model_result={"id": "xgb_soil", "metrics": {"RMSE": 0.1}},
        ).to_dict()

        resolved = resolve_followup("模型效果怎么样", state, {"model_results": [{"model": "RF"}]})

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["reason"], "matched_frontend_selected_model_result")
        self.assertEqual(resolved["referenced_object"]["type"], "model_result")
        self.assertEqual(resolved["referenced_object"]["id"], "xgb_soil")

    def test_selected_model_result_id_resolves_matching_dashboard_record(self) -> None:
        state = ConversationState(selected_model_result={"id": "model_result_xgb_002", "source": "frontend_context"}).to_dict()
        dashboard = {
            "model_results": [
                {"model_result_id": "model_result_rf_001", "model": "RF", "metrics": {"RMSE": 0.4}},
                {"model_result_id": "model_result_xgb_002", "model": "XGBoost", "metrics": {"RMSE": 0.1}},
            ]
        }

        resolved = resolve_followup("模型效果怎么样", state, dashboard)

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["referenced_object"]["id"], "model_result_xgb_002")
        self.assertEqual(resolved["referenced_object"]["data"]["model"], "XGBoost")
        self.assertEqual(resolved["referenced_object"]["data"]["metrics"]["RMSE"], 0.1)

    def test_missing_selected_model_result_id_returns_missing_object(self) -> None:
        state = ConversationState(selected_model_result={"id": "missing_model", "source": "frontend_context"}).to_dict()

        resolved = resolve_followup("这个模型说明什么", state, {"model_results": []})

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["referenced_object"]["type"], "model_result")
        self.assertTrue(resolved["referenced_object"]["missing"])
        self.assertEqual(resolved["referenced_object"]["id"], "missing_model")

    def test_empty_frontend_context_falls_back_to_recent_artifact(self) -> None:
        state = ConversationState(active_artifacts=[{"name": "latest.png", "path": "plots/latest.png"}]).to_dict()

        resolved = resolve_followup("这个结果说明什么", state, {})

        self.assertTrue(resolved["resolved"])
        self.assertIn("artifact", resolved["referenced_object"]["type"])
        self.assertIn("latest.png", resolved["referenced_object"]["path"])


if __name__ == "__main__":
    unittest.main()
