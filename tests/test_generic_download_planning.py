from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest import mock

from core.area_resolver import resolve_area_candidates
from core.config import Settings
from core.product_catalog import list_product_catalog, product_catalog_context
from core.service import GISWorkspaceService
from core.task_plan_schema import validate_llm_task_plan
from core.plan_validator import validate_task_plan_before_execution
from core.llm_task_planner import build_llm_task_plan


def _context(prompt: str) -> dict:
    return {
        "response_language": "zh-CN",
        "candidate_tool_cards": [{"tool_name": "submit_commercial_download_job"}],
        "area_candidates": resolve_area_candidates(prompt),
        "download_candidates": product_catalog_context(prompt),
    }


def _download_plan(
    *,
    primary_goal: str,
    area_asset_id: str,
    area_source: str,
    product_id: str,
    requested_resolution: str = "",
    resolved_resolution: str = "",
    time_range: dict | None = None,
    clarification_question: str = "",
) -> dict:
    request = {
        "area_asset_id": area_asset_id,
        "area_source": area_source,
        "product_id": product_id,
        "requested_resolution": requested_resolution,
        "resolved_resolution": resolved_resolution,
        "time_range": time_range or {},
        "download_parameters": {},
        "source_attribution": {"area": area_source, "product": "product_catalog"},
        "expected_outputs": ["download_job", "artifact"],
        "requires_confirmation": False,
    }
    return {
        "primary_goal": primary_goal,
        "intent": "data_download",
        "operation": "download_data",
        "input_assets": [],
        "asset_roles": {},
        "requested_downloads": [request],
        "download_requests": [request],
        "study_area": area_asset_id,
        "time_range": time_range or {},
        "spatial_resolution": resolved_resolution,
        "candidate_tools": ["submit_commercial_download_job"],
        "selected_tools": ["submit_commercial_download_job"] if not clarification_question else [],
        "workflow_steps": (
            [
                {
                    "step_id": f"submit_{product_id}",
                    "tool_name": "submit_commercial_download_job",
                    "args": {"product_id": product_id, "area_asset_id": area_asset_id, "resolution": resolved_resolution},
                    "expected_outputs": ["download_job"],
                }
            ]
            if not clarification_question
            else []
        ),
        "expected_outputs": ["download_job", "artifact"],
        "requires_confirmation": False,
        "clarification_question": clarification_question,
        "confidence": 0.9,
        "source_attribution": {area_asset_id: "system_default", product_id: "system_default"},
        "explicit_history_references": [],
        "response_language": "zh-CN",
    }


class GenericDownloadPlanningTests(unittest.TestCase):
    def test_catalog_lists_real_supported_products_and_rules(self) -> None:
        catalog = {item["product_id"]: item for item in list_product_catalog()}

        self.assertIn("gscloud_dem_30m", catalog)
        self.assertIn("gscloud_dem_90m", catalog)
        self.assertIn("gscloud_ndvi_500m_10day", catalog)
        self.assertIn("gscloud_lst_1km_10day", catalog)
        self.assertIn("gscloud_evi_250m_10day", catalog)
        self.assertIn("gscloud_surface_reflectance_1km", catalog)
        self.assertIn("gscloud_sentinel2_msi", catalog)
        self.assertIn("gscloud_landsat8_oli_tirs", catalog)
        self.assertEqual(catalog["gscloud_dem_30m"]["temporal_requirement"], "none")
        self.assertIn("30m", catalog["gscloud_dem_30m"]["supported_resolutions"])
        self.assertEqual(catalog["gscloud_ndvi_500m_10day"]["temporal_requirement"], "date_range")
        self.assertEqual(catalog["gscloud_lst_1km_10day"]["temporal_requirement"], "date_range")
        self.assertEqual(catalog["gscloud_surface_reflectance_1km"]["source_product_key"], "mod021km_1km_surface_reflectance")
        self.assertEqual(catalog["gscloud_landsat8_oli_tirs"]["source_product_key"], "landsat8_oli_tirs")

    def test_catalog_context_finds_landsat_and_mod021km_scene_products(self) -> None:
        landsat = product_catalog_context("下载成都 2020 年 Landsat 8 OLI_TIRS 数据")
        mod021km = product_catalog_context("下载闪电河流域 2020 年 MOD021KM 1KM 地表反射率")

        self.assertEqual(landsat[0]["product_id"], "gscloud_landsat8_oli_tirs")
        self.assertEqual(mod021km[0]["product_id"], "gscloud_surface_reflectance_1km")

    def test_area_resolver_returns_chengdu_city_candidate(self) -> None:
        candidates = resolve_area_candidates("下载成都市30m的DEM数据")
        first = candidates[0]

        self.assertEqual(first["asset_id"], "admin:city:四川省:成都市")
        self.assertEqual(first["area_source"], "local_admin_boundary")
        self.assertEqual(first["name"], "成都市")
        self.assertEqual(first["admin_level"], "city")

    def test_chengdu_30m_dem_plan_validates_without_clarification(self) -> None:
        context = _context("下载成都市30m的DEM数据")
        plan = _download_plan(
            primary_goal="下载成都市30m DEM",
            area_asset_id="admin:city:四川省:成都市",
            area_source="local_admin_boundary",
            product_id="gscloud_dem_30m",
            requested_resolution="30m",
            resolved_resolution="30m",
        )

        result = validate_llm_task_plan(plan, context)
        self.assertTrue(result["ok"], result.get("errors"))
        gate = validate_task_plan_before_execution(result["plan"], context)
        self.assertTrue(gate["ok"], gate.get("errors"))

    def test_unavailable_llm_uses_catalog_backed_download_plan_not_planner_failure(self) -> None:
        context = _context("下载成都市30m的DEM数据")

        with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
            result = build_llm_task_plan("下载成都市30m的DEM数据", context, client=None)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["planner_source"], "catalog_download_planner")
        plan = result["plan"]
        self.assertEqual(plan["primary_goal"], "下载成都市30m DEM")
        self.assertEqual(plan["operation"], "download_data")
        self.assertEqual(plan["download_requests"][0]["area_asset_id"], "admin:city:四川省:成都市")
        self.assertEqual(plan["download_requests"][0]["product_id"], "gscloud_dem_30m")
        self.assertEqual(plan["download_requests"][0]["resolved_resolution"], "30m")
        self.assertTrue(plan["requires_confirmation"])
        gate = validate_task_plan_before_execution(plan, context)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["errors"][0]["code"], "CONFIRMATION_REQUIRED")

    def test_provider_timeout_uses_catalog_backed_download_plan_when_context_is_sufficient(self) -> None:
        class TimeoutClient:
            def invoke(self, messages):
                from core.zhipu_json_client import LLMProviderError

                raise LLMProviderError("timeout", "timeout")

        context = _context("下载成都市30m的DEM数据")

        result = build_llm_task_plan("下载成都市30m的DEM数据", context, client=TimeoutClient())

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["planner_source"], "catalog_download_planner")
        plan = result["plan"]
        self.assertEqual(plan["download_requests"][0]["product_id"], "gscloud_dem_30m")
        self.assertEqual(plan["download_requests"][0]["area_asset_id"], "admin:city:四川省:成都市")
        self.assertTrue(plan["requires_confirmation"])

    def test_ndvi_date_download_catalog_recovery_keeps_requested_date(self) -> None:
        context = _context("下载成都市2016-05-11的NDVI数据")

        with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
            result = build_llm_task_plan("下载成都市2016-05-11的NDVI数据", context, client=None)

        self.assertEqual(result["status"], "ready")
        plan = result["plan"]
        request = plan["download_requests"][0]
        self.assertEqual(request["product_id"], "gscloud_ndvi_500m_10day")
        self.assertEqual(request["time_range"]["start"], "2016-05-11")
        self.assertEqual(request["time_range"]["end"], "2016-05-11")
        self.assertTrue(plan["requires_confirmation"])
        self.assertIn("确认", plan["clarification_question"])

    def test_chat_download_request_asks_confirmation_when_llm_returns_bad_schema(self) -> None:
        class BadPlannerClient:
            def plan_task(self, prompt, context, deterministic_plan):
                return {
                    "primary_goal": "下载成都市30m DEM",
                    "intent": "data_download",
                    "operation": "download_data",
                    "asset_roles": [],
                    "time_range": "",
                    "source_attribution": [],
                    "workflow_steps": [{"tool_name": "submit_commercial_download_job", "step_id": 1}],
                    "confidence": 0.9,
                }

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            service.set_interaction_mode("tool_enabled")
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=BadPlannerClient()):
                result = service.ask("下载成都市30m的DEM数据")

        self.assertNotIn("LLM Planner 在生成可验证计划前失败", result["reply"])
        self.assertIn("确认", result["reply"])
        self.assertEqual(result["mode"], "awaiting_confirmation")
        self.assertEqual(result["reason"], "download_requires_confirmation")
        self.assertTrue(result["confirmation_id"])

    def test_chat_ndvi_download_timeout_asks_confirmation_not_timeout_failure(self) -> None:
        class TimeoutPlannerClient:
            def invoke(self, messages):
                from core.zhipu_json_client import LLMProviderError

                raise LLMProviderError("timeout", "timeout")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            service.set_interaction_mode("tool_enabled")
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=TimeoutPlannerClient()):
                with mock.patch("core.service.execute_download_requests") as download_mock:
                    result = service.ask("下载成都市2016-05-11的NDVI数据")

        self.assertEqual(result["mode"], "awaiting_confirmation")
        self.assertEqual(result["reason"], "download_requires_confirmation")
        self.assertIn("成都市", result["reply"])
        self.assertIn("NDVI", result["reply"])
        self.assertIn("确认", result["reply"])
        self.assertNotIn("模型服务响应超时", result["reply"])
        self.assertFalse(download_mock.called)
        self.assertTrue(result["confirmation_id"])

    def test_mianyang_90m_dem_plan_validates_when_resolution_supported(self) -> None:
        context = _context("下载绵阳市90m DEM")
        plan = _download_plan(
            primary_goal="下载绵阳市90m DEM",
            area_asset_id="admin:city:四川省:绵阳市",
            area_source="local_admin_boundary",
            product_id="gscloud_dem_90m",
            requested_resolution="90m",
            resolved_resolution="90m",
        )

        result = validate_llm_task_plan(plan, context)
        self.assertTrue(result["ok"], result.get("errors"))

    def test_shandianhe_90m_dem_uses_library_basin_not_history_area(self) -> None:
        context = _context("下载闪电河流域90m DEM")
        context["active_selection"] = {"selected_layer": {"name": "成都市"}}
        plan = _download_plan(
            primary_goal="下载闪电河流域90m DEM",
            area_asset_id="library:basin:shandianhe",
            area_source="user_selected_default_library",
            product_id="gscloud_dem_90m",
            requested_resolution="90m",
            resolved_resolution="90m",
        )

        result = validate_llm_task_plan(plan, context)
        self.assertTrue(result["ok"], result.get("errors"))
        self.assertEqual(result["plan"]["download_requests"][0]["area_asset_id"], "library:basin:shandianhe")
        self.assertEqual(result["plan"]["explicit_history_references"], [])

    def test_lst_without_time_is_blocked_with_single_chinese_question(self) -> None:
        context = _context("下载闪电河流域LST")
        plan = _download_plan(
            primary_goal="下载闪电河流域LST",
            area_asset_id="library:basin:shandianhe",
            area_source="user_selected_default_library",
            product_id="gscloud_lst_1km_10day",
            resolved_resolution="1km",
            clarification_question="请提供要下载 LST 的具体时间范围，例如 2020年6月至8月。",
        )

        result = validate_llm_task_plan(plan, context)
        self.assertFalse(result["plan"]["workflow_plan"])
        gate = validate_task_plan_before_execution(result["plan"], context)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["errors"][0]["code"], "DOWNLOAD_TIME_RANGE_REQUIRED")
        self.assertIn("时间", result["plan"]["clarification_question"])

    def test_multi_product_time_range_validates_independent_requests(self) -> None:
        context = _context("分别下载闪电河流域2016年5月11日的EVI、2010年8月16日的地表反射率和2020年6月1日的Sentinel数据")
        evi_time_range = {"start": "2016-05-11", "end": "2016-05-11"}
        requests = [
            ("gscloud_evi_250m_10day", "250m", evi_time_range),
            ("gscloud_surface_reflectance_1km", "1km", {"start": "2010-08-16", "end": "2010-08-16"}),
            ("gscloud_sentinel2_msi", "10m", {"start": "2020-06-01", "end": "2020-06-01"}),
        ]
        plan = _download_plan(
            primary_goal="下载闪电河流域多产品",
            area_asset_id="library:basin:shandianhe",
            area_source="user_selected_default_library",
            product_id="gscloud_evi_250m_10day",
            resolved_resolution="250m",
            time_range=evi_time_range,
        )
        plan["download_requests"] = []
        plan["requested_downloads"] = []
        plan["workflow_steps"] = []
        for product_id, resolution, request_time_range in requests:
            req = {
                "area_asset_id": "library:basin:shandianhe",
                "area_source": "user_selected_default_library",
                "product_id": product_id,
                "requested_resolution": resolution,
                "resolved_resolution": resolution,
                "time_range": request_time_range,
                "download_parameters": {},
                "source_attribution": {"area": "user_selected_default_library", "product": "product_catalog"},
                "expected_outputs": ["download_job", "artifact"],
                "requires_confirmation": False,
            }
            plan["download_requests"].append(req)
            plan["requested_downloads"].append(req)
            plan["workflow_steps"].append(
                {
                    "step_id": f"submit_{product_id}",
                    "tool_name": "submit_commercial_download_job",
                    "args": {"product_id": product_id, "area_asset_id": "library:basin:shandianhe", "resolution": resolution},
                    "expected_outputs": ["download_job"],
                }
            )

        result = validate_llm_task_plan(plan, context)
        self.assertTrue(result["ok"], result.get("errors"))
        gate = validate_task_plan_before_execution(result["plan"], context)
        self.assertTrue(gate["ok"], gate.get("errors"))
        self.assertEqual(len(result["plan"]["download_requests"]), 3)


if __name__ == "__main__":
    unittest.main()
