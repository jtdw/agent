from __future__ import annotations

import unittest

from core.area_resolver import resolve_area_candidates
from core.product_catalog import list_product_catalog, product_catalog_context
from core.task_plan_schema import validate_llm_task_plan
from core.plan_validator import validate_task_plan_before_execution


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
        self.assertIn("gscloud_lst_1km_10day", catalog)
        self.assertIn("gscloud_evi_250m_10day", catalog)
        self.assertIn("gscloud_surface_reflectance_1km", catalog)
        self.assertIn("gscloud_sentinel2_msi", catalog)
        self.assertEqual(catalog["gscloud_dem_30m"]["temporal_requirement"], "none")
        self.assertIn("30m", catalog["gscloud_dem_30m"]["supported_resolutions"])
        self.assertEqual(catalog["gscloud_lst_1km_10day"]["temporal_requirement"], "date_range")

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
        context = _context("下载闪电河流域2020年6月至8月的EVI、地表反射率和Sentinel数据")
        time_range = {"start": "2020-06-01", "end": "2020-08-31"}
        requests = [
            ("gscloud_evi_250m_10day", "250m"),
            ("gscloud_surface_reflectance_1km", "1km"),
            ("gscloud_sentinel2_msi", "10m"),
        ]
        plan = _download_plan(
            primary_goal="下载闪电河流域多产品",
            area_asset_id="library:basin:shandianhe",
            area_source="user_selected_default_library",
            product_id="gscloud_evi_250m_10day",
            resolved_resolution="250m",
            time_range=time_range,
        )
        plan["download_requests"] = []
        plan["requested_downloads"] = []
        plan["workflow_steps"] = []
        for product_id, resolution in requests:
            req = {
                "area_asset_id": "library:basin:shandianhe",
                "area_source": "user_selected_default_library",
                "product_id": product_id,
                "requested_resolution": resolution,
                "resolved_resolution": resolution,
                "time_range": time_range,
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
