from __future__ import annotations

import unittest

from core.execution_trace import build_execution_trace, normalize_execution_results


class ExecutionTraceAdapterTests(unittest.TestCase):
    def plan(self) -> dict:
        return {
            "workflow_plan": [
                {"step_id": "clip", "tool_name": "clip_raster_by_vector", "validated_tool_args": {}},
                {"step_id": "stats", "tool_name": "raster_zonal_stats", "validated_tool_args": {}},
            ]
        }

    def test_normalizes_workflow_step_results_in_plan_order(self) -> None:
        raw = {
            "workflow_result": {
                "outputs": {
                    "step_results": [
                        {
                            "status": "succeeded",
                            "tool_name": "raster_zonal_stats",
                            "step_id": "stats",
                            "outputs": {"table": "stats"},
                            "artifacts": [],
                            "errors": [],
                            "warnings": [],
                            "next_actions": [],
                            "input_asset_ids": ["r1"],
                        },
                        {
                            "status": "succeeded",
                            "tool_name": "clip_raster_by_vector",
                            "step_id": "clip",
                            "outputs": {"result_dataset": "dem_clip"},
                            "artifacts": [],
                            "errors": [],
                            "warnings": [],
                            "next_actions": [],
                            "input_asset_ids": ["r1", "b1"],
                        },
                    ]
                }
            }
        }

        results = normalize_execution_results(self.plan(), raw)

        self.assertEqual([item["step_id"] for item in results], ["clip", "stats"])
        self.assertEqual(results[0]["tool_name"], "clip_raster_by_vector")
        self.assertEqual(
            set(results[0]),
            {
                "status",
                "errors",
                "warnings",
                "artifacts",
                "map_layers",
                "tables",
                "images",
                "outputs",
                "diagnostics",
                "next_actions",
                "step_id",
                "tool_name",
                "input_asset_ids",
            },
        )

    def test_unknown_step_results_go_to_trace_diagnostics(self) -> None:
        raw = {
            "tool_results": [
                {
                    "status": "succeeded",
                    "tool_name": "plot_dataset",
                    "step_id": "unexpected",
                    "outputs": {},
                    "artifacts": [],
                    "errors": [],
                    "warnings": [],
                    "next_actions": [],
                    "input_asset_ids": [],
                }
            ]
        }

        trace = build_execution_trace(self.plan(), raw_results=raw)

        self.assertEqual(trace.results, [])
        self.assertEqual(trace.diagnostics["unknown_step_results"][0]["step_id"], "unexpected")
        self.assertEqual(trace.remaining_step_ids, ["clip", "stats"])


if __name__ == "__main__":
    unittest.main()
