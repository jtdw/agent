from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from core.context_builder import build_conversation_context
from core.service import GISWorkspaceService
from core.task_plan_schema import validate_llm_task_plan


pytestmark = pytest.mark.slow


def _phase2_plan(**overrides):
    plan = {
        "primary_goal": "soil_moisture_xgboost_regression",
        "intent": "modeling",
        "operation": "train_model",
        "input_assets": [
            {"role": "feature_raster", "name": "DEM", "source": "current_upload"},
            {"role": "feature_raster", "name": "NDVI", "source": "current_upload"},
            {"role": "feature_raster", "name": "LST", "source": "current_upload"},
            {"role": "target_station_archive", "name": "shandianhe2019_station_0_5cm", "source": "user_selected_default_library"},
        ],
        "asset_roles": {
            "DEM": "terrain_feature_raster",
            "NDVI": "vegetation_feature_raster",
            "LST": "temperature_feature_raster",
            "shandianhe2019_station_0_5cm": "soil_moisture_target_stations",
        },
        "requested_downloads": [],
        "study_area": "shandianhe",
        "time_range": {"year": "2019"},
        "spatial_resolution": "",
        "candidate_tools": ["run_stm_soil_moisture_xgboost_workflow"],
        "selected_tools": ["run_stm_soil_moisture_xgboost_workflow"],
        "workflow_steps": [
            {
                "step_id": "stm_xgb",
                "tool_name": "run_stm_soil_moisture_xgboost_workflow",
                "args": {
                    "archive_path": "local_library/data/stations/shandianhe2019_station_0_5cm.zip",
                    "raster_names": "DEM,NDVI,LST",
                    "preferred_depth": "0.050000",
                    "year": "2019",
                    "output_prefix": "shandian_soil_moisture_xgb",
                },
            }
        ],
        "expected_outputs": ["model_metrics", "prediction_table"],
        "requires_confirmation": False,
        "clarification_question": "",
        "confidence": 0.85,
        "source_attribution": {
            "DEM": "current_upload",
            "NDVI": "current_upload",
            "LST": "current_upload",
            "shandianhe2019_station_0_5cm": "user_selected_default_library",
        },
        "explicit_history_references": [],
    }
    plan.update(overrides)
    return plan


class LLMOrchestrationPhase2Tests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        service = GISWorkspaceService(settings)
        service.set_interaction_mode("tool_enabled")
        return service

    def test_phase2_task_plan_schema_converts_to_legacy_execution_plan(self) -> None:
        context = {
            "candidate_tool_cards": [{"tool_name": "run_stm_soil_moisture_xgboost_workflow"}],
            "available_datasets": [
                {"name": "DEM", "type": "raster"},
                {"name": "NDVI", "type": "raster"},
                {"name": "LST", "type": "raster"},
            ],
        }

        result = validate_llm_task_plan(_phase2_plan(), context)

        self.assertTrue(result["ok"], result.get("errors"))
        plan = result["plan"]
        self.assertEqual(plan["primary_goal"], "soil_moisture_xgboost_regression")
        self.assertEqual(plan["task_type"], "modeling")
        self.assertEqual(plan["operation"], "train_model")
        self.assertEqual(plan["download_plan"].get("requested_downloads"), [])
        self.assertEqual(plan["workflow_plan"][0]["tool_name"], "run_stm_soil_moisture_xgboost_workflow")
        self.assertEqual(plan["workflow_plan"][0]["validated_tool_args"]["raster_names"], "DEM,NDVI,LST")

    def test_plan_validator_blocks_download_tool_when_no_requested_downloads(self) -> None:
        from core.plan_validator import validate_task_plan_before_execution

        plan = validate_llm_task_plan(
            _phase2_plan(
                selected_tools=["download_backend_status"],
                workflow_steps=[{"step_id": "download", "tool_name": "download_backend_status", "args": {}}],
            ),
            {"candidate_tool_cards": [{"tool_name": "download_backend_status"}]},
        )["plan"]

        result = validate_task_plan_before_execution(plan, {"download_candidates": []})

        self.assertFalse(result["ok"])
        self.assertIn("DOWNLOAD_TOOL_WITHOUT_REQUESTED_DOWNLOADS", {error["code"] for error in result["errors"]})
        self.assertEqual(result["execution_plan"]["workflow_plan"], [])
        self.assertIn("download_backend_status", result["blocked_tools"])

    def test_active_llm_planner_rejects_low_confidence_without_tools(self) -> None:
        from core.llm_task_planner import build_llm_task_plan

        class LowConfidenceClient:
            def invoke(self, messages):
                return json.dumps(_phase2_plan(confidence=0.2), ensure_ascii=False)

        result = build_llm_task_plan(
            "DEM NDVI LST",
            {"candidate_tool_cards": [{"tool_name": "run_stm_soil_moisture_xgboost_workflow"}]},
            client=LowConfidenceClient(),
        )

        self.assertEqual(result["status"], "low_confidence")
        self.assertFalse(result["executes_tools"])
        self.assertTrue(result["plan"]["should_ask_clarification"])

    def test_chat_ask_routes_download_prompt_through_service_not_direct_gscloud_submit(self) -> None:
        import api_server

        client = TestClient(api_server.app)
        service_result = {
            "reply": "planner gate reached",
            "model": "conversation-coordinator",
            "mode": "clarification",
            "reason": "llm_planner_unavailable",
            "images": [],
        }

        with mock.patch.dict("os.environ", {"GIS_AGENT_ALLOW_ANONYMOUS": "1"}, clear=False):
            with mock.patch.object(GISWorkspaceService, "ask", return_value=service_result) as ask_mock:
                response = client.post("/api/chat/ask", json={"prompt": "下载文县 30 米 DEM"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["reply"], "planner gate reached")
        self.assertTrue(ask_mock.called)

    def test_service_uses_active_llm_plan_and_records_gate_trace_without_downloads(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.current_session_id = service.create_new_session()
            service.set_interaction_mode("tool_enabled")
            active_plan = {
                "status": "ready",
                "mode": "active",
                "planner_source": "test_client",
                "executes_tools": False,
                "plan": validate_llm_task_plan(
                    _phase2_plan(),
                    {"candidate_tool_cards": [{"tool_name": "run_stm_soil_moisture_xgboost_workflow"}]},
                )["plan"],
            }

            with mock.patch("core.service.build_llm_task_plan", return_value=active_plan):
                with mock.patch("core.service.execute_workflow_plan", return_value={"executed": False}) as workflow_mock:
                    result = service.ask("使用我上传的 DEM、NDVI、LST，并自动使用文件库默认 STM 站点包运行 XGBoost")

            assistant = [item for item in service.manager.database.list_messages(service.current_session_id) if item["role"] == "assistant"][-1]
            self.assertIn("llm_task_plan", assistant["meta"])
            self.assertIn("plan_validation", assistant["meta"])
            self.assertEqual(assistant["meta"]["llm_task_plan"]["primary_goal"], "soil_moisture_xgboost_regression")
            self.assertEqual(assistant["meta"]["plan_validation"]["trace"]["requested_downloads"], [])
            self.assertIn("coordinator_decisions", assistant["meta"])
            self.assertFalse(workflow_mock.called)
            self.assertNotEqual(result.get("reason"), "deterministic_gscloud_dem_download")

    def test_service_does_not_execute_tools_when_llm_planner_unavailable(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.current_session_id = service.create_new_session()
            service.set_interaction_mode("tool_enabled")
            unavailable = {
                "status": "unavailable",
                "mode": "active",
                "planner_source": "default_llm",
                "executes_tools": False,
                "reason": "llm_planner_client_unavailable",
                "plan": {
                    "task_type": "unclear_request",
                    "should_ask_clarification": True,
                    "clarification_question": "LLM planner is unavailable.",
                    "workflow_plan": [],
                    "tool_plan": [],
                    "validated_tool_args": {},
                },
            }

            with mock.patch("core.service.build_llm_task_plan", return_value=unavailable):
                with mock.patch("core.service.execute_workflow_plan") as workflow_mock:
                    with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                        result = service.ask("DEM NDVI LST")

            self.assertEqual(result["reason"], "unavailable")
            self.assertFalse(workflow_mock.called)
            self.assertFalse(tool_mock.called)

    def test_context_builder_excludes_history_without_explicit_reference(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            state = {
                "selected_layer": {"name": "old_layer"},
                "last_model_result": {"model_result_id": "old_model"},
                "active_artifacts": [{"artifact_id": "old_artifact"}],
            }
            dashboard = {"artifacts": [{"artifact_id": "dash_artifact"}], "model_results": [{"model_result_id": "dash_model"}]}

            context = build_conversation_context("训练一个新模型", {"intent": "modeling"}, state, service.manager, dashboard)

            self.assertEqual(context["active_selection"], {})
            self.assertEqual(context["recent_artifacts"], [])
            self.assertIsNone(context["recent_model_result"])
            self.assertFalse(context["context_sources"]["explicit_history_reference"])

    def test_plan_validator_blocks_download_replacing_current_upload_same_role(self) -> None:
        from core.plan_validator import validate_task_plan_before_execution

        plan = validate_llm_task_plan(
            _phase2_plan(
                requested_downloads=[{"role": "feature_raster", "resource_type": "feature_raster"}],
                selected_tools=["download_backend_status"],
                workflow_steps=[{"step_id": "download", "tool_name": "download_backend_status", "args": {}}],
            ),
            {"candidate_tool_cards": [{"tool_name": "download_backend_status"}]},
        )["plan"]

        result = validate_task_plan_before_execution(plan, {"available_datasets": [{"name": "DEM"}]})

        self.assertFalse(result["ok"])
        self.assertIn("CURRENT_UPLOAD_SUPERSEDES_DOWNLOAD", {error["code"] for error in result["errors"]})


if __name__ == "__main__":
    unittest.main()
