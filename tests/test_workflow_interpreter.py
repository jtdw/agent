from __future__ import annotations

import unittest

from core.result_interpreter import interpret_result
from core.workflow_interpreter import interpret_workflow_result


def _tool_result(tool_name: str, *, ok: bool = True, outputs: dict | None = None, artifacts: list | None = None, summary: str = "", error_code: str = "", user_message: str = "") -> dict:
    return {
        "ok": ok,
        "tool_name": tool_name,
        "task_id": f"{tool_name}_task",
        "inputs": {},
        "outputs": outputs or {},
        "artifacts": artifacts or [],
        "summary": summary,
        "diagnostics": {},
        "warnings": [],
        "next_actions": ["review this step"],
        "error_code": error_code,
        "error_title": "step failed" if not ok else "",
        "user_message": user_message,
        "technical_detail": "ValueError: raw detail should not be primary",
    }


class WorkflowInterpreterTests(unittest.TestCase):
    def successful_clip_map_workflow(self) -> dict:
        return {
            "ok": True,
            "workflow_id": "workflow_demo",
            "steps": [
                {
                    "step_id": "check_dataset",
                    "tool_name": "describe_dataset",
                    "status": "success",
                    "validated_tool_args": {"dataset_name": "points"},
                    "tool_result": _tool_result("describe_dataset", outputs={"dataset_name": "points"}, summary="Dataset checked."),
                },
                {
                    "step_id": "clip_vector",
                    "tool_name": "vector_clip_by_vector",
                    "status": "success",
                    "validated_tool_args": {"dataset_name": "points", "clip_name": "study_area"},
                    "tool_result": _tool_result(
                        "vector_clip_by_vector",
                        outputs={"result_dataset": "points_clipped", "feature_count": 2, "path": "derived/points_clipped.geojson"},
                        artifacts=[{"type": "dataset", "title": "points_clipped", "path": "derived/points_clipped.geojson"}],
                        summary="Clipped vector created.",
                    ),
                },
                {
                    "step_id": "generate_map",
                    "tool_name": "plot_dataset",
                    "status": "success",
                    "validated_tool_args": {"dataset_name": "points_clipped", "column": "pop_density"},
                    "tool_result": _tool_result(
                        "plot_dataset",
                        outputs={"path": "plots/points_clipped_map.png", "column": "pop_density"},
                        artifacts=[{"type": "map", "title": "Population density map", "path": "plots/points_clipped_map.png"}],
                        summary="Map generated.",
                    ),
                },
            ],
            "final_artifacts": [
                {"type": "dataset", "title": "points_clipped", "path": "derived/points_clipped.geojson"},
                {"type": "map", "title": "Population density map", "path": "plots/points_clipped_map.png"},
            ],
            "final_summary": "Workflow completed successfully.",
            "failed_step": "",
            "diagnostics": {"executed_steps": ["check_dataset", "clip_vector", "generate_map"]},
            "next_actions": ["review map", "export result"],
        }

    def test_successful_clip_map_workflow_has_step_by_step_explanation(self) -> None:
        explanation = interpret_workflow_result(
            self.successful_clip_map_workflow(),
            prompt="这个流程做了什么",
            context={"active_dataset": {"name": "points"}},
        )

        self.assertIn("workflow_summary", explanation)
        self.assertIn("step_explanations", explanation)
        self.assertIn("final_interpretation", explanation)
        self.assertIn("user_next_actions", explanation)
        self.assertEqual([step["step_name"] for step in explanation["step_explanations"]], ["check_dataset", "clip_vector", "generate_map"])
        self.assertIn("空间分布", explanation["final_interpretation"])
        self.assertIn("generate_map", explanation["markdown_reply"])
        self.assertIn("Population density map", explanation["markdown_reply"])
        self.assertNotIn("plots/points_clipped_map.png", explanation["markdown_reply"])
        self.assertNotIn("derived/points_clipped.geojson", explanation["markdown_reply"])
        self.assertNotIn("path", explanation["step_explanations"][2]["output"])
        self.assertNotIn("path", explanation["workflow_summary"]["final_results"][0])

    def test_clip_failure_explains_completed_failed_and_skipped_steps(self) -> None:
        workflow = self.successful_clip_map_workflow()
        workflow["ok"] = False
        workflow["failed_step"] = "clip_vector"
        workflow["steps"][1]["status"] = "failed"
        workflow["steps"][1]["tool_result"] = _tool_result(
            "vector_clip_by_vector",
            ok=False,
            error_code="OBJECT_NOT_FOUND",
            user_message="clip layer study_area was not found",
        )
        workflow["steps"][2]["status"] = "skipped"
        workflow["steps"][2]["tool_result"] = _tool_result("plot_dataset", ok=False, error_code="WORKFLOW_DEPENDENCY_FAILED", user_message="previous step failed")
        workflow["final_artifacts"] = []
        workflow["next_actions"] = ["select a valid study area"]

        explanation = interpret_workflow_result(workflow, prompt="为什么失败")

        self.assertIn("clip_vector", explanation["markdown_reply"])
        self.assertIn("OBJECT_NOT_FOUND", explanation["markdown_reply"])
        self.assertIn("已完成步骤", explanation["markdown_reply"])
        self.assertIn("未执行步骤", explanation["markdown_reply"])
        self.assertIn("select a valid study area", explanation["markdown_reply"])

    def test_missing_map_field_failure_points_to_failed_step(self) -> None:
        workflow = self.successful_clip_map_workflow()
        workflow["ok"] = False
        workflow["failed_step"] = "generate_map"
        workflow["steps"][2]["status"] = "failed"
        workflow["steps"][2]["tool_result"] = _tool_result("plot_dataset", ok=False, error_code="FIELD_NOT_FOUND", user_message="field pop_density was not found")
        workflow["final_artifacts"] = workflow["final_artifacts"][:1]

        explanation = interpret_workflow_result(workflow, prompt="为什么失败")

        self.assertIn("generate_map", explanation["markdown_reply"])
        self.assertIn("FIELD_NOT_FOUND", explanation["markdown_reply"])
        self.assertIn("字段", explanation["markdown_reply"])

    def test_multiple_artifacts_are_listed(self) -> None:
        explanation = interpret_workflow_result(self.successful_clip_map_workflow())

        self.assertIn("points_clipped", explanation["markdown_reply"])
        self.assertIn("Population density map", explanation["markdown_reply"])
        self.assertNotIn("derived/points_clipped.geojson", explanation["markdown_reply"])
        self.assertNotIn("plots/points_clipped_map.png", explanation["markdown_reply"])

    def test_result_interpreter_delegates_workflow_results(self) -> None:
        workflow = self.successful_clip_map_workflow()
        import json

        reply = interpret_result("这个流程做了什么", {"intent": "result_analysis"}, {}, json.dumps(workflow, ensure_ascii=False), {"active_dataset": {"name": "points"}}, {})

        self.assertIn("canonical", reply.lower())
        self.assertNotIn("结果解读", reply)
        self.assertNotIn("推荐查看", reply)
        self.assertNotIn("input:", reply)
        self.assertNotIn("output:", reply)

    def test_result_interpreter_failure_followup_locates_failed_step(self) -> None:
        workflow = self.successful_clip_map_workflow()
        workflow["ok"] = False
        workflow["failed_step"] = "generate_map"
        workflow["steps"][2]["status"] = "failed"
        workflow["steps"][2]["tool_result"] = _tool_result("plot_dataset", ok=False, error_code="FIELD_NOT_FOUND", user_message="field pop_density was not found")
        import json

        reply = interpret_result("为什么失败", {"intent": "troubleshooting"}, {}, json.dumps(workflow, ensure_ascii=False), {"active_dataset": {"name": "points"}}, {})

        self.assertIn("canonical", reply.lower())
        self.assertNotIn("失败步骤: generate_map", reply)
        self.assertNotIn("field pop_density was not found", reply)
        self.assertIn("为什么", "为什么失败")


    def test_second_batch_tool_diagnostics_are_explained(self) -> None:
        workflow = {
            "ok": True,
            "workflow_id": "workflow_zonal",
            "steps": [
                {
                    "step_id": "zonal_stats",
                    "tool_name": "raster_zonal_stats",
                    "status": "success",
                    "validated_tool_args": {"raster_name": "dem", "polygon_name": "county", "stat": "mean"},
                    "tool_result": {
                        **_tool_result(
                            "raster_zonal_stats",
                            outputs={"result_dataset": "county_dem", "feature_count": 3, "fields_added": ["raster_mean"]},
                            artifacts=[{"type": "dataset", "title": "county_dem", "path": "derived/county_dem.geojson"}],
                            summary="Zonal statistics completed.",
                        ),
                        "diagnostics": {"polygon_count": 3, "non_null_count": 2, "stat": "mean", "band": 1},
                        "warnings": ["1 polygon had no raster coverage"],
                    },
                }
            ],
            "final_artifacts": [{"type": "dataset", "title": "county_dem", "path": "derived/county_dem.geojson"}],
            "final_summary": "Workflow completed successfully.",
            "failed_step": "",
            "diagnostics": {},
            "next_actions": [],
        }

        reply = interpret_workflow_result(workflow)["markdown_reply"]

        self.assertIn("fields_added=['raster_mean']", reply)
        self.assertIn("polygon_count=3", reply)
        self.assertIn("non_null_count=2", reply)
        self.assertIn("1 polygon had no raster coverage", reply)

    def test_export_workflow_explains_format_and_source(self) -> None:
        workflow = {
            "ok": True,
            "workflow_id": "workflow_export",
            "steps": [
                {
                    "step_id": "export_vector",
                    "tool_name": "export_dataset",
                    "status": "success",
                    "validated_tool_args": {"dataset_name": "county_dem", "output_path": "exports/county_dem.zip"},
                    "tool_result": _tool_result(
                        "export_dataset",
                        outputs={"path": "exports/county_dem.zip", "format": "zip", "source_dataset": "county_dem"},
                        artifacts=[{"type": "file", "title": "county_dem.zip", "path": "exports/county_dem.zip"}],
                        summary="Export completed.",
                    ),
                }
            ],
            "final_artifacts": [{"type": "file", "title": "county_dem.zip", "path": "exports/county_dem.zip"}],
            "final_summary": "Workflow completed successfully.",
            "failed_step": "",
            "diagnostics": {},
            "next_actions": [],
        }

        reply = interpret_workflow_result(workflow)["markdown_reply"]

        self.assertIn("format=zip", reply)
        self.assertIn("source_dataset=county_dem", reply)
        self.assertIn("county_dem.zip", reply)
        self.assertNotIn("exports/county_dem.zip", reply)
        self.assertNotIn("output_path", reply)


if __name__ == "__main__":
    unittest.main()
