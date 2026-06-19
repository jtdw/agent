from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import Settings
from core.area_resolver import resolve_area_candidates
from core.data_manager import DataManager
from core.download_request_executor import execute_download_requests
from core.management_views import download_job_to_management_view
from core.service import GISWorkspaceService
from core.task_plan_schema import validate_llm_task_plan
from core.tool_context import ToolRuntimeContext


def _request(product_id: str, status: str, *, time_range: dict | None = None) -> dict:
    return {
        "area_asset_id": "library:basin:shandianhe",
        "area_source": "user_selected_default_library",
        "product_id": product_id,
        "requested_resolution": "",
        "resolved_resolution": "250m" if "evi" in product_id else "10m",
        "time_range": time_range or {"start": "2020-06-01", "end": "2020-08-31"},
        "download_parameters": {"fixture_status": status, "account_mode": "own"},
        "source_attribution": {"area": "user_selected_default_library", "product": "product_catalog"},
        "expected_outputs": ["download_job", "artifact"],
        "requires_confirmation": False,
    }


class GenericDownloadExecutionTests(unittest.TestCase):
    def test_dynamic_area_resolver_materializes_city_boundary_asset(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            candidates = resolve_area_candidates("下载资阳市30m DEM", manager=manager)

            self.assertTrue(candidates)
            first = candidates[0]
            self.assertEqual(first["area_source"], "local_admin_boundary")
            self.assertEqual(first["admin_level"], "city")
            self.assertEqual(first["name"], "资阳市")
            self.assertTrue(first["geometry_asset_id"])
            self.assertIn(first["geometry_asset_id"], manager.list_dataset_names())
            self.assertGreaterEqual(first["feature_count"], 1)
            self.assertEqual(first["crs"], "EPSG:4326")
            self.assertEqual(first["dissolve_method"], "county_units_dissolve")

    def test_dynamic_area_resolver_returns_real_ambiguous_county_candidates(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            candidates = resolve_area_candidates("市中区", manager=manager, limit=5)

            self.assertGreaterEqual(len(candidates), 2)
            self.assertEqual({item["name"] for item in candidates}, {"市中区"})
            self.assertGreaterEqual(len({item["province"] + item["city"] for item in candidates}), 2)
            self.assertTrue(all(item["geometry_asset_id"] in manager.list_dataset_names() for item in candidates))

    def test_multi_product_executor_returns_independent_canonical_results(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            manager.set_runtime_scope("u_download", "s_download")
            context = {
                "response_language": "zh-CN",
                "candidate_tool_cards": [{"tool_name": "submit_commercial_download_job"}],
                "area_candidates": resolve_area_candidates("下载闪电河流域EVI和Sentinel", manager=manager),
            }
            plan_payload = {
                "primary_goal": "download_multiple_products",
                "intent": "data_download",
                "operation": "download_data",
                "input_assets": [],
                "asset_roles": {},
                "download_requests": [
                    _request("gscloud_evi_250m_10day", "succeeded"),
                    _request("gscloud_sentinel2_msi", "waiting_login"),
                ],
                "requested_downloads": [
                    _request("gscloud_evi_250m_10day", "succeeded"),
                    _request("gscloud_sentinel2_msi", "waiting_login"),
                ],
                "study_area": "library:basin:shandianhe",
                "time_range": {"start": "2020-06-01", "end": "2020-08-31"},
                "spatial_resolution": "",
                "candidate_tools": ["submit_commercial_download_job"],
                "selected_tools": ["submit_commercial_download_job"],
                "workflow_steps": [],
                "expected_outputs": ["download_job", "artifact"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {"library:basin:shandianhe": "user_selected_default_library"},
                "explicit_history_references": [],
                "response_language": "zh-CN",
            }
            validated = validate_llm_task_plan(plan_payload, context)
            self.assertTrue(validated["ok"], validated.get("errors"))

            result = execute_download_requests(
                manager,
                validated["plan"],
                context=context,
                runtime_context=ToolRuntimeContext(
                    current_user_id="u_download",
                    current_session_id="s_download",
                    workspace_dir=manager.workdir,
                    permission_scope={"workspace:read", "workspace:write"},
                ),
            )

            self.assertTrue(result["executed"])
            self.assertIn("execution_trace", result)
            self.assertEqual(len(result["tool_results"]), 2)
            statuses = {item["outputs"]["product_id"]: item["status"] for item in result["tool_results"]}
            self.assertEqual(statuses["gscloud_evi_250m_10day"], "succeeded")
            self.assertEqual(statuses["gscloud_sentinel2_msi"], "awaiting_confirmation")
            successful = next(item for item in result["tool_results"] if item["status"] == "succeeded")
            self.assertTrue(successful["artifacts"])
            self.assertTrue(manager.get_artifact(successful["artifacts"][0]["artifact_id"]))
            views = [download_job_to_management_view(item["outputs"]["job"], tool_result=item) for item in result["tool_results"]]
            self.assertEqual({view["status"] for view in views}, {"succeeded", "awaiting_confirmation"})
            self.assertTrue(any(view["artifact_refs"] for view in views))

    def test_chat_service_executes_validated_download_requests_with_presentation_result(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            settings = Settings(api_key="", workdir=Path(tmp) / "workspace")
            settings.ensure_dirs()
            service = GISWorkspaceService(settings)
            service.current_user_id = "u_download"
            service.current_session_id = service.create_new_session()
            request = _request("gscloud_evi_250m_10day", "succeeded")
            plan_payload = {
                "primary_goal": "download_evi",
                "intent": "data_download",
                "operation": "download_data",
                "input_assets": [],
                "asset_roles": {},
                "download_requests": [request],
                "requested_downloads": [request],
                "study_area": "library:basin:shandianhe",
                "time_range": {"start": "2020-06-01", "end": "2020-08-31"},
                "spatial_resolution": "250m",
                "candidate_tools": ["submit_commercial_download_job"],
                "selected_tools": ["submit_commercial_download_job"],
                "workflow_steps": [],
                "expected_outputs": ["download_job", "artifact"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {"library:basin:shandianhe": "user_selected_default_library"},
                "explicit_history_references": [],
                "response_language": "zh-CN",
            }

            with mock.patch(
                "core.service.build_llm_task_plan",
                return_value={"status": "ready", "mode": "active", "executes_tools": True, "plan": plan_payload},
            ):
                result = service.ask("下载闪电河流域2020年6月至8月的EVI数据")

            self.assertEqual(result["mode"], "validated_download_executor")
            self.assertIn("presentation_result", result)
            self.assertTrue(result["download_management_views"])
            assistant = [item for item in service.manager.database.list_messages(service.current_session_id) if item["role"] == "assistant"][-1]
            self.assertEqual(assistant["meta"]["mode"], "validated_download_executor")
            self.assertIn("execution_trace", assistant["meta"])
            self.assertFalse(assistant["meta"]["deprecated_raw_job_api_used"])


if __name__ == "__main__":
    unittest.main()
