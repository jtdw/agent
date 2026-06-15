from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.context_builder import build_conversation_context
from core.conversation_state import recover_conversation_state
from core.followup_resolver import resolve_followup


@dataclass
class _Record:
    name: str
    data_type: str
    path: Path
    meta: dict[str, Any]


class _Database:
    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state = state or {}

    def get_conversation_state(self, session_id: str) -> dict[str, Any]:
        return dict(self.state)

    def set_conversation_state(self, session_id: str, state: dict[str, Any]) -> None:
        self.state = dict(state)


class _Manager:
    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.database = _Database(state)
        self.last_plot_path = "plots/latest_map.png"
        self.datasets = [
            {"name": "county_points", "type": "vector", "path": "uploads/county_points.geojson", "meta": {"columns": ["pop_density", "geometry"]}},
            {"name": "county_points_clipped", "type": "vector", "path": "derived/county_points_clipped.geojson", "meta": {"columns": ["pop_density", "geometry"]}},
        ]
        self.artifacts = [
            {"artifact_id": "map_001", "type": "map", "path": "plots/latest_map.png", "title": "Population density map"},
            {"artifact_id": "clip_001", "type": "vector_clip", "path": "derived/county_points_clipped.geojson", "dataset_id": "county_points_clipped"},
            {"artifact_id": "old_001", "type": "table", "path": "derived/old.csv"},
            {"artifact_id": "old_002", "type": "table", "path": "derived/old2.csv"},
        ]
        self.model_results = [
            {
                "model_result_id": "model_xgb_001",
                "model": "XGBoost",
                "metrics": {"R": 0.81, "RMSE": 2.4},
                "metrics_path": "derived/model_metrics.csv",
            }
        ]

    def list_dataset_names(self) -> list[str]:
        return [item["name"] for item in self.datasets]

    def list_datasets(self) -> list[dict[str, Any]]:
        return list(self.datasets)

    def list_artifacts(self) -> list[dict[str, Any]]:
        return list(self.artifacts)

    def list_model_results(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.model_results[:limit]

    def get(self, name: str) -> _Record:
        for item in self.datasets:
            if item["name"] == name:
                return _Record(item["name"], item["type"], Path(item["path"]), item.get("meta", {}))
        raise KeyError(name)

    def workspace_summary(self) -> dict[str, Any]:
        return {"dataset_count": len(self.datasets), "artifact_count": len(self.artifacts)}


class ConversationStateContextTests(unittest.TestCase):
    def test_recover_state_restores_recent_dataset_artifacts_map_and_model(self) -> None:
        manager = _Manager()

        state = recover_conversation_state(manager, "session_a")

        self.assertEqual(state.active_dataset, "county_points_clipped")
        self.assertEqual([item["artifact_id"] for item in state.active_artifacts], ["map_001", "clip_001", "old_001"])
        self.assertEqual(state.last_map_path, "plots/latest_map.png")
        self.assertEqual(state.last_model_result["model_result_id"], "model_xgb_001")

    def test_recover_state_keeps_persisted_selection_and_error(self) -> None:
        manager = _Manager(
            {
                "active_dataset": "county_points",
                "selected_artifact": {"id": "map_001", "path": "plots/latest_map.png"},
                "last_error": {"error_code": "FIELD_NOT_FOUND", "message": "missing field"},
            }
        )

        state = recover_conversation_state(manager, "session_a")

        self.assertEqual(state.active_dataset, "county_points")
        self.assertEqual(state.selected_artifact["id"], "map_001")
        self.assertEqual(state.last_error["error_code"], "FIELD_NOT_FOUND")

    def test_context_is_compact_and_prioritizes_referenced_model_result(self) -> None:
        manager = _Manager({"active_dataset": "county_points"})
        state = recover_conversation_state(manager, "session_a")
        state.referenced_object = {"type": "model_result", "data": manager.model_results[0], "source": "frontend_context"}
        dashboard = {"summary": manager.workspace_summary(), "artifacts": manager.artifacts, "model_results": manager.model_results}

        context = build_conversation_context("模型效果怎么样", {"intent": "result_analysis"}, state.to_dict(), manager, dashboard)

        self.assertEqual(context["recent_model_result"]["model_result_id"], "model_xgb_001")
        self.assertEqual(len(context["recent_artifacts"]), 3)
        self.assertIn("county_points", [item["name"] for item in context["available_datasets"]])
        self.assertNotIn("file_content", str(context))

    def test_context_limits_dataset_and_layer_indexes(self) -> None:
        manager = _Manager({"active_dataset": "dataset_29"})
        manager.datasets = [
            {"name": f"dataset_{index}", "type": "vector", "path": f"uploads/dataset_{index}.geojson", "meta": {"columns": ["value", "geometry"]}}
            for index in range(30)
        ]
        dashboard = {"summary": manager.workspace_summary(), "artifacts": manager.artifacts, "model_results": manager.model_results}
        state = recover_conversation_state(manager, "session_a")

        context = build_conversation_context("检查当前图层", {"intent": "data_upload_analysis"}, state.to_dict(), manager, dashboard)

        self.assertLessEqual(len(context["available_datasets"]), 12)
        self.assertLessEqual(len(context["available_layers"]), 12)
        self.assertEqual(context["active_dataset"]["name"], "dataset_29")

    def test_context_uses_explicit_dataset_mention_for_current_turn(self) -> None:
        manager = _Manager({"active_dataset": "county_points_clipped"})
        dashboard = {"summary": manager.workspace_summary(), "artifacts": manager.artifacts, "model_results": manager.model_results}
        state = recover_conversation_state(manager, "session_a")

        context = build_conversation_context(
            "检查 @{county_points} 的字段并画图",
            {"intent": "data_upload_analysis"},
            state.to_dict(),
            manager,
            dashboard,
        )

        self.assertEqual(context["active_dataset"]["name"], "county_points")
        self.assertEqual(context["available_fields"], ["pop_density", "geometry"])

    def test_real_chinese_followup_prefers_selected_feature(self) -> None:
        state = {
            "selected_feature": {
                "id": "feature_7",
                "layer_id": "county_layer",
                "properties": {"county": "A", "pop_density": 120},
            },
            "last_map_path": "plots/latest_map.png",
        }

        result = resolve_followup("这个区域为什么异常", state, {})

        self.assertTrue(result["resolved"])
        self.assertEqual(result["referenced_object"]["type"], "feature")
        self.assertEqual(result["referenced_object"]["id"], "feature_7")
        self.assertEqual(result["referenced_object"]["source"], "frontend_context")

    def test_real_chinese_followup_uses_last_error(self) -> None:
        state = {"last_error": {"error_code": "FIELD_NOT_FOUND", "message": "字段 pop 不存在"}}

        result = resolve_followup("为什么失败", state, {})

        self.assertTrue(result["resolved"])
        self.assertEqual(result["referenced_object"]["type"], "error")
        self.assertEqual(result["referenced_object"]["data"]["error_code"], "FIELD_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
