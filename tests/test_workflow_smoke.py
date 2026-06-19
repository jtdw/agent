import unittest
import importlib.util
from tempfile import TemporaryDirectory

from core.task_planner import build_task_plan
from core.gis_tools import build_tools as compat_build_tools
from core.tools.document_tools import build_document_tools
from core.tools.map_tools import build_map_tools
from core.tools.ml_tools import build_ml_tools
from core.tools.raster_tools import build_raster_tools
from core.tools.registry import build_tools as build_registry_tools
from core.tools.table_tools import build_table_tools
from core.tools.vector_tools import build_vector_tools
from core.workflow_executor import SUPPORTED_WORKFLOW_TOOLS, VIRTUAL_WORKFLOW_TOOLS
from core.workflows.registry import build_executable_workflow, list_workflow_templates, match_workflow_template


class WorkflowSmokeTests(unittest.TestCase):
    def test_common_gis_workflows_are_registered(self) -> None:
        ids = {item["workflow_id"] for item in list_workflow_templates()}
        self.assertIn("upload_vector_profile", ids)
        self.assertIn("vector_clip_raster", ids)
        self.assertIn("table_to_points", ids)
        self.assertIn("processing_report", ids)

    def test_prompt_matches_table_to_points_workflow(self) -> None:
        matched = match_workflow_template("识别经纬度坐标字段，并把表格转点")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["workflow_id"], "table_to_points")

    def test_planner_prioritizes_registered_workflow_template(self) -> None:
        context = {
            "active_dataset": {"name": "stations.csv", "type": "table"},
            "available_fields": ["lon", "lat", "name"],
            "available_datasets": [{"name": "stations.csv", "type": "table"}],
            "workspace": {"dataset_count": 1},
        }
        plan = build_task_plan(
            "识别经纬度坐标字段，并把表格转点",
            {"intent": "data_processing", "confidence": 0.92},
            context,
        )

        self.assertEqual(plan.get("workflow_template", {}).get("workflow_id"), "table_to_points")
        self.assertEqual(plan.get("recommended_tools", [])[:2], ["detect_coordinate_fields", "table_to_points"])

    def test_planner_attaches_executable_workflow_when_params_are_available(self) -> None:
        context = {
            "active_dataset": {"name": "stations.csv", "type": "table"},
            "available_fields": ["lon", "lat", "name"],
            "available_datasets": [{"name": "stations.csv", "type": "table"}],
            "workspace": {"dataset_count": 1},
        }
        plan = build_task_plan(
            "用 lon 和 lat 坐标字段，把表格转点，输出 stations_points",
            {"intent": "data_processing", "confidence": 0.92},
            context,
        )

        self.assertEqual(plan.get("workflow_template", {}).get("workflow_id"), "table_to_points")
        self.assertEqual(plan.get("executable_workflow", {}).get("status"), "ready")
        self.assertEqual(plan.get("workflow_plan", [])[1]["tool_name"], "table_to_points")

    def test_modular_tool_registry_keeps_core_tools_unique(self) -> None:
        with TemporaryDirectory() as tmpdir:
            class StubManager:
                operation_log: list[dict] = []
                workdir = tmpdir

                def workspace_summary(self):
                    return {}

                def list_datasets(self):
                    return []

                def list_artifacts(self):
                    return []

            names = [tool.name for tool in build_registry_tools(StubManager())]
        self.assertIn("describe_dataset", names)
        self.assertIn("table_to_points", names)
        self.assertIn("download_backend_status", names)
        self.assertEqual(len(names), len(set(names)))

    def test_category_builders_define_tools_without_legacy_pool(self) -> None:
        class StubManager:
            operation_log: list[dict] = []

        self.assertIn("table_to_points", {tool.name for tool in build_table_tools(StubManager())})
        self.assertIn("vector_clip_by_vector", {tool.name for tool in build_vector_tools(StubManager())})
        self.assertIn("raster_basic_stats", {tool.name for tool in build_raster_tools(StubManager())})
        self.assertIn("plot_dataset", {tool.name for tool in build_map_tools(StubManager())})
        self.assertIn("generate_stage_report", {tool.name for tool in build_document_tools(StubManager())})
        self.assertIn("train_xgboost_fusion_model", {tool.name for tool in build_ml_tools(StubManager())})

    def test_legacy_gis_tools_module_removed_but_compat_import_works(self) -> None:
        self.assertIsNone(importlib.util.find_spec("core.tools.legacy_gis_tools"))
        self.assertIs(compat_build_tools, build_registry_tools)

    def test_registry_builds_executable_workflow_plan(self) -> None:
        workflow = build_executable_workflow(
            "table_to_points",
            {
                "dataset_name": "stations.csv",
                "x_col": "lon",
                "y_col": "lat",
                "crs": "EPSG:4326",
                "output_name": "stations_points",
            },
        )

        self.assertEqual(workflow["workflow_id"], "table_to_points")
        self.assertEqual(workflow["status"], "ready")
        self.assertEqual([step["tool_name"] for step in workflow["workflow_plan"]], ["describe_dataset", "table_to_points"])
        self.assertEqual(workflow["workflow_plan"][1]["validated_tool_args"]["output_name"], "stations_points")
        self.assertIn("frontend_payload", workflow)

    def test_built_workflow_steps_are_enabled_for_execution(self) -> None:
        enabled = set(SUPPORTED_WORKFLOW_TOOLS) | set(VIRTUAL_WORKFLOW_TOOLS)
        sample_params = {
            "upload_vector_profile": {"dataset_name": "points"},
            "upload_raster_profile": {"dataset_name": "dem"},
            "vector_clip_vector": {"dataset_name": "points", "clip_name": "boundary", "output_name": "points_clip"},
            "vector_clip_raster": {"raster_name": "dem", "vector_name": "boundary", "output_name": "dem_clip"},
            "table_to_points": {"dataset_name": "stations.csv", "x_col": "lon", "y_col": "lat", "crs": "EPSG:4326", "output_name": "stations_points"},
            "raster_statistics": {"raster_name": "dem"},
            "map_export": {"dataset_name": "points", "output_name": "points_map"},
            "processing_report": {"report_title": "soil moisture report"},
        }
        missing = {
            workflow_id: sorted({step["tool_name"] for step in build_executable_workflow(workflow_id, params)["workflow_plan"]} - enabled)
            for workflow_id, params in sample_params.items()
            if {step["tool_name"] for step in build_executable_workflow(workflow_id, params)["workflow_plan"]} - enabled
        }
        not_ready = {
            workflow_id: build_executable_workflow(workflow_id, params)["missing_params"]
            for workflow_id, params in sample_params.items()
            if build_executable_workflow(workflow_id, params)["status"] != "ready"
        }

        self.assertEqual(not_ready, {})
        self.assertEqual(missing, {})

    def test_registered_workflow_required_tools_are_registered_or_executable(self) -> None:
        with TemporaryDirectory() as tmpdir:
            class StubManager:
                operation_log: list[dict] = []
                workdir = tmpdir

                def workspace_summary(self):
                    return {}

                def list_datasets(self):
                    return []

                def list_artifacts(self):
                    return []

            registered = {tool.name for tool in build_registry_tools(StubManager())}
        enabled_or_registered = set(SUPPORTED_WORKFLOW_TOOLS) | set(VIRTUAL_WORKFLOW_TOOLS) | registered
        missing = {
            template["workflow_id"]: sorted(set(template["required_tools"]) - enabled_or_registered)
            for template in list_workflow_templates()
            if set(template["required_tools"]) - enabled_or_registered
        }

        self.assertEqual(missing, {})

    def test_processing_report_workflow_uses_generate_stage_report_contract(self) -> None:
        workflow = build_executable_workflow("processing_report", {"report_title": "soil moisture report"})

        self.assertEqual(workflow["status"], "ready")
        step = workflow["workflow_plan"][0]
        self.assertEqual(step["tool_name"], "generate_stage_report")
        self.assertEqual(step["validated_tool_args"]["stage"], "proposal")
        self.assertEqual(step["validated_tool_args"]["topic"], "soil moisture report")

    def test_registry_executable_workflow_reports_missing_params(self) -> None:
        workflow = build_executable_workflow("vector_clip_vector", {"dataset_name": "points"})

        self.assertEqual(workflow["status"], "needs_params")
        self.assertEqual(workflow["error"]["error_code"], "WORKFLOW_PARAMS_REQUIRED")
        self.assertIn("clip_name", workflow["missing_params"])
        self.assertIn("output_name", workflow["missing_params"])


if __name__ == "__main__":
    unittest.main()
