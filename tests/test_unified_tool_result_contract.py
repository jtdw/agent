from __future__ import annotations

import json
import unittest
from pathlib import Path

from core.tool_contracts import (
    aggregate_tool_results,
    normalize_tool_result,
    parse_tool_result,
    tool_result_awaiting_confirmation,
    tool_result_blocked,
    tool_result_error,
    tool_result_ok,
    tool_result_running,
)


class UnifiedToolResultContractTests(unittest.TestCase):
    def assert_canonical(self, result: dict, status: str) -> None:
        self.assertEqual(result["schema_version"], "tool-result/v1")
        self.assertEqual(result["status"], status)
        self.assertIn("success", result)
        self.assertIn("outputs", result)
        self.assertIn("artifacts", result)
        self.assertIn("map_layers", result)
        self.assertIn("tables", result)
        self.assertIn("images", result)
        self.assertIn("diagnostics", result)
        self.assertIn("warnings", result)
        self.assertIn("errors", result)
        self.assertIn("next_actions", result)
        self.assertIn("execution_id", result)
        self.assertIn("started_at", result)
        self.assertIn("finished_at", result)

    def test_success_error_running_confirmation_and_blocked_are_canonical(self) -> None:
        cases = [
            (tool_result_ok("describe_dataset", outputs={"dataset": "points"}).to_dict(), "succeeded", True),
            (tool_result_error("plot_dataset", error_code="FIELD_NOT_FOUND", user_message="Missing field.").to_dict(), "failed", False),
            (tool_result_running("download_gscloud", outputs={"job_id": "job_1"}).to_dict(), "running", False),
            (tool_result_awaiting_confirmation("download_gscloud", user_message="Login required.").to_dict(), "awaiting_confirmation", False),
            (tool_result_blocked("download_gscloud", error_code="QUOTA_EXHAUSTED", user_message="Quota exhausted.").to_dict(), "blocked", False),
        ]
        for payload, status, success in cases:
            with self.subTest(status=status):
                parsed = parse_tool_result(payload)
                self.assertIsNotNone(parsed)
                self.assert_canonical(parsed, status)
                self.assertEqual(parsed["success"], success)
                self.assertEqual(parsed["ok"], success)

    def test_parse_tool_result_normalizes_legacy_dict_and_json(self) -> None:
        legacy = {
            "ok": True,
            "tool_name": "plot_dataset",
            "task_id": "plot_dataset_legacy",
            "inputs": {"dataset_name": "points"},
            "outputs": {"path": "map.png"},
            "artifacts": [],
        }

        from_dict = parse_tool_result(legacy)
        from_json = parse_tool_result(json.dumps(legacy))

        self.assertEqual(from_dict["status"], "succeeded")
        self.assertEqual(from_json["status"], "succeeded")
        self.assertEqual(from_dict["success"], True)
        self.assertEqual(from_dict["task_id"], "plot_dataset_legacy")

    def test_invalid_free_text_is_not_accepted_as_tool_result(self) -> None:
        self.assertIsNone(parse_tool_result("finished successfully"))
        self.assertIsNone(parse_tool_result({"ok": True}))

    def test_artifact_existence_is_reported_without_fabricating_success(self) -> None:
        result = normalize_tool_result(
            {
                "ok": True,
                "tool_name": "export_dataset",
                "task_id": "export_1",
                "inputs": {},
                "outputs": {},
                "artifacts": [{"artifact_id": "a1", "path": str(Path("missing_file.tif")), "type": "raster", "title": "missing"}],
            }
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["artifacts"][0]["status"], "missing")
        self.assertTrue(any("missing" in warning.lower() for warning in result["warnings"]))

    def test_aggregate_tool_results_uses_canonical_status(self) -> None:
        ok = tool_result_ok("describe_dataset", outputs={"dataset": "points"}).to_dict()
        failed = tool_result_error("plot_dataset", error_code="FIELD_NOT_FOUND", user_message="Missing field.").to_dict()

        aggregate = aggregate_tool_results([ok, failed], tool_name="tool_executor")

        self.assertEqual(aggregate["status"], "failed")
        self.assertFalse(aggregate["success"])
        self.assertEqual(aggregate["error_code"], "FIELD_NOT_FOUND")
        self.assertEqual(aggregate["outputs"]["tool_results"][1]["status"], "failed")

    def test_normalize_tool_result_accepts_legacy_result_ref_aliases(self) -> None:
        result = normalize_tool_result(
            {
                "status": "ok",
                "tool_name": "legacy_gis_tool",
                "task_id": "legacy_1",
                "artifact_refs": [{"artifact_id": "artifact_dem", "title": "DEM.tif", "type": "raster"}],
                "files": [{"id": "artifact_report", "filename": "report.md", "kind": "report"}],
                "map_layer_refs": [{"layer_id": "layer_dem", "name": "DEM"}],
                "layers": [{"id": "layer_boundary", "title": "研究区边界"}],
                "table_refs": [{"table_id": "table_stats", "title": "统计表"}],
                "image_refs": [{"artifact_id": "artifact_preview", "title": "预览图"}],
                "suggestions": ["查看地图图层。"],
            }
        )

        self.assert_canonical(result, "succeeded")
        self.assertEqual([item["artifact_id"] for item in result["artifacts"]], ["artifact_dem", "artifact_report"])
        self.assertEqual([item["layer_id"] for item in result["map_layers"]], ["layer_dem", "layer_boundary"])
        self.assertEqual(result["tables"][0]["table_id"], "table_stats")
        self.assertEqual(result["images"][0]["artifact_id"], "artifact_preview")
        self.assertEqual(result["next_actions"], ["查看地图图层。"])

    def test_aggregate_tool_results_preserves_all_result_surfaces(self) -> None:
        first = normalize_tool_result(
            {
                "status": "succeeded",
                "tool_name": "make_dem",
                "artifacts": [{"artifact_id": "artifact_dem", "title": "DEM.tif", "type": "raster"}],
                "map_layers": [{"layer_id": "layer_dem", "name": "DEM"}],
            }
        )
        second = normalize_tool_result(
            {
                "status": "succeeded",
                "tool_name": "summarize_dem",
                "tables": [{"table_id": "table_stats", "title": "统计表"}],
                "images": [{"artifact_id": "artifact_chart", "title": "图表"}],
            }
        )

        aggregate = aggregate_tool_results([first, second], tool_name="workflow")

        self.assert_canonical(aggregate, "succeeded")
        self.assertEqual([item["layer_id"] for item in aggregate["map_layers"]], ["layer_dem"])
        self.assertEqual([item["table_id"] for item in aggregate["tables"]], ["table_stats"])
        self.assertEqual([item["artifact_id"] for item in aggregate["images"]], ["artifact_chart"])


if __name__ == "__main__":
    unittest.main()
