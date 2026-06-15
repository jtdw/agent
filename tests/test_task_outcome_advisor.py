from __future__ import annotations

import unittest

from core.task_outcome_advisor import build_task_outcome, format_task_outcome_markdown


class TaskOutcomeAdvisorTests(unittest.TestCase):
    def test_model_result_outcome_recommends_next_steps(self) -> None:
        dashboard = {
            "model_results": [
                {
                    "model": "XGBoost",
                    "output_prefix": "soil_xgb",
                    "metrics": {"R": 0.91, "RMSE": 0.12, "NSE": 0.8},
                    "artifacts": [{"label": "指标表", "display_path": "derived/soil_xgb_metrics.csv"}],
                    "recommendations": ["建议补做 GCP 不确定性分析。"],
                }
            ]
        }

        outcome = build_task_outcome("analysis", {"reply": "XGBoost 完成"}, dashboard=dashboard)

        self.assertEqual(outcome["task_type"], "analysis")
        self.assertTrue(outcome["has_results"])
        self.assertIn("XGBoost", outcome["summary"])
        self.assertIn("derived/soil_xgb_metrics.csv", "\n".join(outcome["result_paths"]))
        self.assertTrue(any("GCP" in item for item in outcome["recommendations"]))

    def test_download_outcome_recommends_map_ready_checks(self) -> None:
        result = {
            "job": {
                "job_id": "job_1",
                "status": "completed",
                "zip_path": "workspace/domestic_downloads/dem.zip",
                "download_url": "/api/downloads/artifact?job_id=job_1",
            }
        }

        outcome = build_task_outcome("download", result, dashboard={})

        self.assertTrue(outcome["has_results"])
        self.assertIn("workspace/domestic_downloads/dem.zip", "\n".join(outcome["result_paths"]))
        self.assertTrue(any("地图" in item or "裁剪" in item for item in outcome["recommendations"]))

    def test_upload_outcome_recommends_field_check(self) -> None:
        result = {"count": 2, "messages": ["已载入表格：station.csv", "已载入边界：basin.shp"]}
        dashboard = {"datasets": [{"name": "station", "type": "table"}, {"name": "basin", "type": "vector"}]}

        outcome = build_task_outcome("upload", result, dashboard=dashboard)

        self.assertTrue(outcome["has_results"])
        self.assertIn("station.csv", outcome["summary"])
        self.assertTrue(any("字段" in item for item in outcome["recommendations"]))

    def test_upload_outcome_omits_raw_dataset_brief(self) -> None:
        raw_message = (
            '已加载数据: demo_xgboost_soil_moisture_1\n'
            '[ { "name": "demo_xgboost_soil_moisture", "type": "table", '
            '"path": "workspace/users/u_1/uploads/demo.csv", "meta": { "rows": 48, '
            '"columns": [ "station_id", "lon", "lat" ] } } ]'
        )
        result = {"count": 1, "messages": [raw_message]}
        dashboard = {
            "datasets": [
                {
                    "name": "demo_xgboost_soil_moisture_1",
                    "type": "table",
                    "meta": {"rows": 48, "columns": ["station_id", "lon", "lat"]},
                }
            ]
        }

        outcome = build_task_outcome("upload", result, dashboard=dashboard)
        markdown = format_task_outcome_markdown(outcome)

        self.assertIn("已处理 1 个上传文件", markdown)
        self.assertIn("demo_xgboost_soil_moisture_1", markdown)
        self.assertNotIn('"path"', markdown)
        self.assertNotIn('"columns"', markdown)
        self.assertNotIn("[ {", markdown)

    def test_analysis_without_model_results_does_not_claim_result_files(self) -> None:
        outcome = build_task_outcome(
            "analysis",
            {"reply": "Current workspace has no analyzable data."},
            dashboard={"model_results": [], "artifacts": []},
        )

        self.assertEqual(outcome["task_type"], "analysis")
        self.assertFalse(outcome["has_results"])
        self.assertEqual(outcome["result_paths"], [])

    def test_result_panel_collects_downloadable_artifacts(self) -> None:
        from core.api_helpers import _build_result_panel

        response = {
            "task_outcome": {
                "summary": "XGBoost model finished",
                "result_paths": ["metrics: workspace/anonymous/derived/xgb_metrics.csv"],
                "recommendations": ["check metrics"],
            }
        }
        dashboard = {
            "model_results": [
                {
                    "model": "XGBoost",
                    "artifacts": [
                        {
                            "label": "metrics",
                            "path": "workspace/anonymous/derived/xgb_metrics.csv",
                            "download_url": "/api/files/artifact?path=derived/xgb_metrics.csv",
                        }
                    ],
                }
            ],
            "artifacts": [],
        }

        panel = _build_result_panel(response, dashboard)

        self.assertTrue(panel["has_results"])
        self.assertEqual(panel["title"], "XGBoost model finished")
        self.assertEqual(panel["files"][0]["label"], "metrics")
        self.assertEqual(panel["files"][0]["download_url"], "/api/files/artifact?path=derived/xgb_metrics.csv")


if __name__ == "__main__":
    unittest.main()
