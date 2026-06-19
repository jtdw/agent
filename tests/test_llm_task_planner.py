from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from core.config import Settings
from core.context_builder import build_conversation_context
from core.conversation_state import ConversationState
from core.llm_task_planner import build_default_llm_task_planner_client, build_shadow_llm_task_plan
from core.service import GISWorkspaceService
from core.task_plan_schema import validate_llm_task_plan


class LLMTaskPlannerTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_validates_llm_task_plan_against_context_tools_and_fields(self) -> None:
        context = {
            "active_dataset": {"name": "stations", "type": "table"},
            "available_fields": ["lon", "lat", "soil_moisture", "ndvi"],
            "candidate_tool_cards": [{"tool_name": "generic_xgboost_workflow"}],
        }
        payload = {
            "task_type": "modeling",
            "goal": "Train XGBoost from station metadata.",
            "selected_assets": [{"role": "training_table", "name": "stations", "evidence": ["active dataset"]}],
            "tools_read": ["generic_xgboost_workflow"],
            "planned_steps": [
                {
                    "step_id": "train",
                    "tool_name": "generic_xgboost_workflow",
                    "args": {
                        "dataset_name": "stations",
                        "target_col": "soil_moisture",
                        "feature_cols": "ndvi,lon,lat",
                        "output_name": "soil_xgb",
                    },
                }
            ],
            "requires_confirmation": False,
            "clarification_question": "",
            "assumptions": [],
            "expected_outputs": ["model_metrics"],
            "forbidden_tools": ["download_backend_status"],
            "explanation": "Use real table fields only.",
        }

        result = validate_llm_task_plan(payload, context)

        self.assertTrue(result["ok"])
        plan = result["plan"]
        self.assertEqual(plan["task_type"], "modeling")
        self.assertEqual(plan["tool_plan"][0]["tool_name"], "generic_xgboost_workflow")
        self.assertEqual(plan["validated_tool_args"]["generic_xgboost_workflow"]["target_col"], "soil_moisture")
        self.assertFalse(plan["should_ask_clarification"])

    def test_rejects_llm_task_plan_with_unread_tool_or_fake_field(self) -> None:
        context = {
            "active_dataset": {"name": "stations", "type": "table"},
            "available_fields": ["lon", "lat", "soil_moisture"],
            "candidate_tool_cards": [{"tool_name": "generic_xgboost_workflow"}],
        }
        payload = {
            "task_type": "modeling",
            "goal": "Train model.",
            "selected_assets": [{"role": "training_table", "name": "stations", "evidence": ["active dataset"]}],
            "tools_read": ["plot_dataset"],
            "planned_steps": [
                {
                    "step_id": "train",
                    "tool_name": "generic_xgboost_workflow",
                    "args": {
                        "dataset_name": "stations",
                        "target_col": "fake_target",
                        "feature_cols": "lon,lat",
                        "output_name": "bad",
                    },
                }
            ],
            "requires_confirmation": False,
            "clarification_question": "",
            "assumptions": [],
            "expected_outputs": [],
            "forbidden_tools": [],
            "explanation": "",
        }

        result = validate_llm_task_plan(payload, context)

        self.assertFalse(result["ok"])
        self.assertIn("TOOL_CARD_NOT_READ", {error["code"] for error in result["errors"]})
        self.assertIn("FIELD_NOT_IN_CONTEXT", {error["code"] for error in result["errors"]})
        self.assertTrue(result["fallback_plan"]["should_ask_clarification"])

    def test_rejects_download_product_key_not_in_context_candidates(self) -> None:
        context = {
            "candidate_tool_cards": [{"tool_name": "download_backend_status"}],
            "download_candidates": [{"product_key": "sentinel2_msi", "confirmation_required": True}],
        }
        payload = {
            "task_type": "data_download",
            "goal": "Download a fake product.",
            "selected_assets": [{"role": "download_product", "name": "made_up_product", "product_key": "made_up_product", "evidence": ["user"]}],
            "tools_read": ["download_backend_status"],
            "planned_steps": [
                {
                    "step_id": "prepare",
                    "tool_name": "download_backend_status",
                    "args": {"product_key": "made_up_product"},
                }
            ],
            "download_plan": {"product_key": "made_up_product"},
            "requires_confirmation": True,
            "clarification_question": "",
            "assumptions": [],
            "expected_outputs": [],
            "forbidden_tools": [],
            "explanation": "",
        }

        result = validate_llm_task_plan(payload, context)

        self.assertFalse(result["ok"])
        self.assertIn("DOWNLOAD_PRODUCT_NOT_IN_CONTEXT", {error["code"] for error in result["errors"]})
        self.assertTrue(result["fallback_plan"]["should_ask_clarification"])

    def test_accepts_download_product_key_from_context_candidates(self) -> None:
        context = {
            "candidate_tool_cards": [{"tool_name": "download_backend_status"}],
            "download_candidates": [
                {
                    "product_key": "sentinel2_msi",
                    "source_key": "gscloud",
                    "name": "Sentinel-2 MSI",
                    "resource_type": "satellite_imagery",
                    "confirmation_required": True,
                    "license_note": "Requires account/login state and user confirmation.",
                }
            ],
        }
        payload = {
            "task_type": "data_download",
            "goal": "Download Sentinel-2.",
            "selected_assets": [{"role": "download_product", "name": "Sentinel-2", "product_key": "sentinel2_msi", "evidence": ["download_candidates"]}],
            "tools_read": ["download_backend_status"],
            "planned_steps": [
                {
                    "step_id": "prepare",
                    "tool_name": "download_backend_status",
                    "args": {"product_key": "sentinel2_msi"},
                }
            ],
            "download_plan": {"product_key": "sentinel2_msi"},
            "requires_confirmation": True,
            "clarification_question": "",
            "assumptions": [],
            "expected_outputs": [],
            "forbidden_tools": [],
            "explanation": "",
        }

        result = validate_llm_task_plan(payload, context)

        self.assertTrue(result["ok"], result.get("errors"))
        self.assertEqual(result["plan"]["download_plan"]["product_key"], "sentinel2_msi")
        self.assertEqual(result["plan"]["download_plan"]["source_key"], "gscloud")
        self.assertEqual(result["plan"]["download_plan"]["name"], "Sentinel-2 MSI")
        self.assertEqual(result["plan"]["download_plan"]["resource_type"], "satellite_imagery")
        self.assertTrue(result["plan"]["download_plan"]["confirmation_required"])
        self.assertIn("license_note", result["plan"]["download_plan"])

    def test_rejects_confirmation_required_download_candidate_without_plan_confirmation(self) -> None:
        context = {
            "candidate_tool_cards": [{"tool_name": "download_backend_status"}],
            "download_candidates": [{"product_key": "sentinel2_msi", "confirmation_required": True}],
        }
        payload = {
            "task_type": "data_download",
            "goal": "Download Sentinel-2.",
            "selected_assets": [{"role": "download_product", "name": "Sentinel-2", "product_key": "sentinel2_msi", "evidence": ["download_candidates"]}],
            "tools_read": ["download_backend_status"],
            "planned_steps": [
                {
                    "step_id": "prepare",
                    "tool_name": "download_backend_status",
                    "args": {"product_key": "sentinel2_msi"},
                }
            ],
            "download_plan": {"product_key": "sentinel2_msi"},
            "requires_confirmation": False,
            "clarification_question": "",
            "assumptions": [],
            "expected_outputs": [],
            "forbidden_tools": [],
            "explanation": "",
        }

        result = validate_llm_task_plan(payload, context)

        self.assertFalse(result["ok"])
        self.assertIn("DOWNLOAD_PRODUCT_REQUIRES_CONFIRMATION", {error["code"] for error in result["errors"]})
        self.assertTrue(result["fallback_plan"]["should_ask_clarification"])

    def test_shadow_llm_task_planner_uses_fake_client_and_never_executes_tools(self) -> None:
        class FakePlannerClient:
            def invoke(self, messages):
                return json.dumps(
                    {
                        "task_type": "modeling",
                        "goal": "Train XGBoost.",
                        "selected_assets": [{"role": "training_table", "name": "stations", "evidence": ["active dataset"]}],
                        "tools_read": ["generic_xgboost_workflow"],
                        "planned_steps": [
                            {
                                "step_id": "train",
                                "tool_name": "generic_xgboost_workflow",
                                "args": {
                                    "dataset_name": "stations",
                                    "target_col": "soil_moisture",
                                    "feature_cols": "ndvi",
                                    "output_name": "shadow_xgb",
                                },
                            }
                        ],
                        "requires_confirmation": False,
                        "clarification_question": "",
                        "assumptions": [],
                        "expected_outputs": ["model_metrics"],
                        "forbidden_tools": [],
                        "explanation": "Shadow only.",
                    },
                    ensure_ascii=False,
                )

        context = {
            "active_dataset": {"name": "stations", "type": "table"},
            "available_fields": ["soil_moisture", "ndvi"],
            "candidate_tool_cards": [{"tool_name": "generic_xgboost_workflow"}],
            "knowledge_snippets": [],
            "agent_policy": {"policy": "policy"},
        }

        result = build_shadow_llm_task_plan(
            "用站点数据做 XGBoost",
            context,
            {"task_type": "modeling"},
            client=FakePlannerClient(),
            enabled=True,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["mode"], "shadow")
        self.assertEqual(result["planner_source"], "injected_client")
        self.assertFalse(result["executes_tools"])
        self.assertEqual(result["plan"]["validated_tool_args"]["generic_xgboost_workflow"]["output_name"], "shadow_xgb")

    def test_shadow_llm_task_planner_marks_disabled_and_unavailable_sources(self) -> None:
        disabled = build_shadow_llm_task_plan("", {}, {}, enabled=False)

        self.assertEqual(disabled["status"], "disabled")
        self.assertEqual(disabled["planner_source"], "disabled")

        with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
            unavailable = build_shadow_llm_task_plan("", {}, {}, enabled=True)

        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["planner_source"], "default_llm")

    def test_default_llm_task_planner_client_uses_provider_config(self) -> None:
        captured: dict[str, object] = {}

        class FakeChatModel:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        client = build_default_llm_task_planner_client(
            chat_model_cls=FakeChatModel,
            env={
                "LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "test-key",
                "LLM_MODEL": "planner-model",
                "LLM_BASE_URL": "https://example.test/v1",
                "LLM_TIMEOUT": "12",
                "LLM_MAX_RETRIES": "1",
            },
        )

        self.assertIsInstance(client, FakeChatModel)
        self.assertEqual(captured["model"], "planner-model")
        self.assertEqual(captured["api_key"], "test-key")
        self.assertEqual(captured["base_url"], "https://example.test/v1")
        self.assertEqual(captured["temperature"], 0)

    def test_shadow_llm_task_planner_uses_default_client_when_no_client_is_injected(self) -> None:
        class FakeChatModel:
            def invoke(self, messages):
                return json.dumps(
                    {
                        "task_type": "modeling",
                        "goal": "Train XGBoost.",
                        "selected_assets": [{"role": "training_table", "name": "stations", "evidence": ["active dataset"]}],
                        "tools_read": ["generic_xgboost_workflow"],
                        "planned_steps": [
                            {
                                "step_id": "train",
                                "tool_name": "generic_xgboost_workflow",
                                "args": {
                                    "dataset_name": "stations",
                                    "target_col": "soil_moisture",
                                    "feature_cols": "ndvi",
                                    "output_name": "default_client_xgb",
                                },
                            }
                        ],
                        "requires_confirmation": False,
                        "clarification_question": "",
                        "assumptions": [],
                        "expected_outputs": ["model_metrics"],
                        "forbidden_tools": [],
                        "explanation": "Default client path.",
                    },
                    ensure_ascii=False,
                )

        context = {
            "active_dataset": {"name": "stations", "type": "table"},
            "available_fields": ["soil_moisture", "ndvi"],
            "candidate_tool_cards": [{"tool_name": "generic_xgboost_workflow"}],
        }
        with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=FakeChatModel()):
            result = build_shadow_llm_task_plan("xgboost", context, {"task_type": "modeling"}, enabled=True)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["planner_source"], "default_llm")
        self.assertEqual(result["plan"]["validated_tool_args"]["generic_xgboost_workflow"]["output_name"], "default_client_xgb")

    def test_shadow_llm_task_planner_sends_download_candidates_to_client(self) -> None:
        captured: dict[str, object] = {}

        class CapturingPlannerClient:
            def invoke(self, messages):
                captured["messages"] = messages
                return json.dumps(
                    {
                        "task_type": "data_download",
                        "goal": "Plan download.",
                        "selected_assets": [],
                        "tools_read": ["download_backend_status"],
                        "planned_steps": [],
                        "requires_confirmation": True,
                        "clarification_question": "",
                        "assumptions": [],
                        "expected_outputs": [],
                        "forbidden_tools": [],
                        "explanation": "Need confirmation.",
                    },
                    ensure_ascii=False,
                )

        context = {
            "candidate_tool_cards": [{"tool_name": "download_backend_status"}],
            "download_candidates": [
                {
                    "product_key": "sentinel2_msi",
                    "source_key": "gscloud",
                    "confirmation_required": True,
                }
            ],
        }

        result = build_shadow_llm_task_plan("download sentinel", context, {"task_type": "data_download"}, client=CapturingPlannerClient(), enabled=True)

        self.assertEqual(result["status"], "ready")
        rendered = json.dumps(captured["messages"], ensure_ascii=False, default=str)
        self.assertIn("download_candidates", rendered)
        self.assertIn("sentinel2_msi", rendered)

    def test_service_records_shadow_plan_in_assistant_meta_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"lon": [1.0], "lat": [2.0], "soil_moisture": [0.1]}))
            service.current_session_id = service.create_new_session()

            shadow = {"status": "ready", "mode": "shadow", "executes_tools": False, "plan": {"task_type": "map_generation"}}
            with mock.patch.dict("os.environ", {"GIS_AGENT_ENABLE_LLM_PLANNER_SHADOW": "1"}, clear=False):
                with mock.patch("core.service.build_shadow_llm_task_plan", return_value=shadow):
                    service.ask("画一张地图")

            assistant_messages = [item for item in service.manager.database.list_messages(service.current_session_id) if item["role"] == "assistant"]
            self.assertTrue(assistant_messages)
            self.assertEqual(assistant_messages[-1]["meta"]["llm_shadow_plan"], shadow)


if __name__ == "__main__":
    unittest.main()
