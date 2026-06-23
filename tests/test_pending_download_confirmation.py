from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from core.config import Settings
from core.service import GISWorkspaceService


pytestmark = pytest.mark.slow


def _chengdu_dem_plan(*, product_id: str = "gscloud_dem_30m", resolution: str = "30m") -> dict:
    request = {
        "area_asset_id": "admin:city:chengdu",
        "area_source": "local_admin_boundary",
        "product_id": product_id,
        "requested_resolution": resolution,
        "resolved_resolution": resolution,
        "time_range": {},
        "download_parameters": {"fixture_status": "waiting_login", "output_name": f"chengdu_dem_{resolution}"},
        "source_attribution": {"area": "system_default", "product": "system_default"},
        "expected_outputs": ["download_job", "artifact"],
        "requires_confirmation": True,
    }
    return {
        "task_type": "data_download",
        "primary_goal": f"下载成都市 {resolution} DEM",
        "intent": "data_download",
        "operation": "download_data",
        "input_assets": [],
        "asset_roles": {},
        "download_requests": [request],
        "requested_downloads": [request],
        "study_area": "admin:city:chengdu",
        "time_range": {},
        "spatial_resolution": resolution,
        "candidate_tools": ["submit_commercial_download_job"],
        "selected_tools": ["submit_commercial_download_job"],
        "workflow_steps": [
            {
                "step_id": "download_gscloud_dem_30m",
                "tool_name": "submit_commercial_download_job",
                "args": {
                    "product_id": product_id,
                    "area_asset_id": "admin:city:chengdu",
                    "resolution": resolution,
                    "output_name": f"chengdu_dem_{resolution}",
                },
            }
        ],
        "expected_outputs": ["download_job", "artifact"],
        "requires_confirmation": True,
        "clarification_question": "该任务需要使用数据源账号或登录态并可能消耗配额，请确认是否继续。",
        "confidence": 0.9,
        "source_attribution": {"admin:city:chengdu": "system_default", product_id: "system_default"},
        "explicit_history_references": [],
        "response_language": "zh-CN",
    }


class PendingDownloadConfirmationTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        service = GISWorkspaceService(settings)
        service.current_user_id = "u_confirm"
        service.current_session_id = service.create_new_session()
        service.set_interaction_mode("tool_enabled")
        return service

    def test_download_request_creates_pending_confirmation_without_job(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "ready", "plan": _chengdu_dem_plan()}):
                with mock.patch("core.service.execute_download_requests") as execute_mock:
                    result = service.ask("下载成都市 30m DEM")

            self.assertEqual(result["mode"], "awaiting_confirmation")
            self.assertIn("confirmation_id", result)
            self.assertIn("成都市行政区边界", result["reply"])
            self.assertNotIn("上传成都市边界", result["reply"])
            self.assertFalse(execute_mock.called)

    def test_natural_language_continue_consumes_original_plan_without_replanning(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "ready", "plan": _chengdu_dem_plan()}):
                first = service.ask("下载成都市 30m DEM")
            confirmation_id = first["confirmation_id"]

            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                second = service.ask("继续")

            self.assertEqual(second["mode"], "validated_download_executor")
            self.assertEqual(second["reason"], "confirmed_pending_download")
            meta = service.manager.database.list_messages(service.current_session_id)[-1]["meta"]
            self.assertEqual(meta["confirmed_pending_confirmation_id"], confirmation_id)
            plan = meta["plan"]
            self.assertEqual(plan["download_requests"][0]["area_asset_id"], "admin:city:chengdu")
            self.assertEqual(plan["download_requests"][0]["product_id"], "gscloud_dem_30m")

    def test_button_confirmation_uses_confirmation_id_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "ready", "plan": _chengdu_dem_plan()}):
                first = service.ask("下载成都市 30m DEM")
            confirmation_id = first["confirmation_id"]

            prompt = f"下载成都市 30m DEM confirmed_action_id={confirmation_id}"
            with mock.patch("core.service.build_llm_task_plan", side_effect=AssertionError("ordinary planner must not be called")):
                second = service.ask(prompt)
                third = service.ask(prompt)

            self.assertEqual(second["mode"], "validated_download_executor")
            self.assertEqual(third["mode"], "validated_download_executor")
            first_job = second["download_management_views"][0]["task_id"]
            second_job = third["download_management_views"][0]["task_id"]
            self.assertEqual(first_job, second_job)

    def test_continue_without_pending_confirmation_clarifies_in_chinese(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.service.execute_download_requests") as execute_mock:
                result = service.ask("继续")

            self.assertEqual(result["mode"], "clarification")
            self.assertIn("没有待确认", result["reply"])
            self.assertFalse(execute_mock.called)

    def test_same_region_followup_consumes_pending_plan(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "ready", "plan": _chengdu_dem_plan()}):
                first = service.ask("下载成都市 30m DEM")

            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                second = service.ask("下载该区域的 DEM 数据")

            self.assertEqual(second["mode"], "validated_download_executor")
            meta = service.manager.database.list_messages(service.current_session_id)[-1]["meta"]
            self.assertEqual(meta["confirmed_pending_confirmation_id"], first["confirmation_id"])
            self.assertEqual(meta["plan"]["download_requests"][0]["area_asset_id"], "admin:city:chengdu")

    def test_modification_request_creates_new_plan_and_invalidates_old_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "ready", "plan": _chengdu_dem_plan()}):
                first = service.ask("下载成都市 30m DEM")
            old_confirmation_id = first["confirmation_id"]
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "ready", "plan": _chengdu_dem_plan(product_id="gscloud_dem_90m", resolution="90m")}):
                second = service.ask("改为 90m DEM")

            self.assertEqual(second["mode"], "awaiting_confirmation")
            self.assertNotEqual(second["confirmation_id"], old_confirmation_id)
            assistant_meta = service.manager.database.list_messages(service.current_session_id)[-1]["meta"]
            self.assertEqual(assistant_meta["pending_confirmation"]["product_ids"], ["gscloud_dem_90m"])


if __name__ == "__main__":
    unittest.main()
