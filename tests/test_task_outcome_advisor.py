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
                    "artifacts": [{"artifact_id": "artifact_metrics", "label": "指标表", "display_path": "derived/soil_xgb_metrics.csv"}],
                    "recommendations": ["建议补做 GCP 不确定性分析。"],
                }
            ]
        }

        outcome = build_task_outcome("analysis", {"reply": "XGBoost 完成"}, dashboard=dashboard)
        markdown = format_task_outcome_markdown(outcome)

        self.assertEqual(outcome["task_type"], "analysis")
        self.assertTrue(outcome["has_results"])
        self.assertIn("XGBoost", outcome["summary"])
        self.assertIn("指标表", "\n".join(outcome["result_paths"]))
        self.assertNotIn("derived/soil_xgb_metrics.csv", "\n".join(outcome["result_paths"]))
        self.assertIn("结果引用：", markdown)
        self.assertNotIn("结果位置：", markdown)
        self.assertNotIn("derived/soil_xgb_metrics.csv", markdown)
        self.assertTrue(any("GCP" in item for item in outcome["recommendations"]))

    def test_general_outcome_uses_artifact_refs_not_paths(self) -> None:
        dashboard = {
            "artifacts": [
                {"artifact_id": "artifact_report", "title": "分析报告", "path": "workspace/users/u1/sessions/s1/derived/report.md"},
                {"artifact_id": "artifact_map", "display_path": "plots/internal_map.png"},
            ]
        }

        outcome = build_task_outcome("general", {"reply": "任务完成"}, dashboard=dashboard)
        rendered = "\n".join(outcome["result_paths"])

        self.assertIn("分析报告", rendered)
        self.assertIn("artifact_map", rendered)
        self.assertNotIn("workspace/users", rendered)
        self.assertNotIn("plots/internal_map.png", rendered)

    def test_result_panel_does_not_forward_raw_result_paths(self) -> None:
        from core.api_helpers import _build_result_panel

        panel = _build_result_panel(
            {
                "task_outcome": {
                    "summary": "XGBoost model finished",
                    "result_paths": ["metrics: workspace/anonymous/derived/xgb_metrics.csv", "/api/files/artifact?path=derived/x.csv"],
                    "recommendations": ["check metrics"],
                }
            },
            {"model_results": [], "artifacts": []},
        )

        self.assertEqual(panel["result_paths"], [])

    def test_model_result_outcome_does_not_report_legacy_download_url_as_path(self) -> None:
        dashboard = {
            "model_results": [
                {
                    "model": "XGBoost",
                    "metrics": {"RMSE": 0.12},
                    "artifacts": [
                        {
                            "label": "指标表",
                            "download_url": "/api/files/artifact?path=derived/soil_xgb_metrics.csv",
                        }
                    ],
                }
            ]
        }

        outcome = build_task_outcome("analysis", {"reply": "XGBoost 完成"}, dashboard=dashboard)

        self.assertTrue(outcome["has_results"])
        self.assertEqual(outcome["result_paths"], [])

    def test_download_outcome_recommends_map_ready_checks(self) -> None:
        result = {
            "management_view": {
                "task_id": "job_1",
                "status": "succeeded",
                "artifact_refs": [{"artifact_id": "artifact_dem_zip", "title": "dem.zip"}],
                "user_message": "下载任务已完成。",
            },
            "tool_result": {
                "status": "succeeded",
                "artifacts": [{"artifact_id": "artifact_dem_zip", "title": "dem.zip"}],
            },
        }

        outcome = build_task_outcome("download", result, dashboard={})

        self.assertTrue(outcome["has_results"])
        self.assertIn("dem.zip", "\n".join(outcome["result_paths"]))
        self.assertTrue(any("地图" in item or "裁剪" in item for item in outcome["recommendations"]))

    def test_upload_outcome_is_brief_without_recommendations(self) -> None:
        result = {"count": 2, "messages": ["已载入表格：station.csv", "已载入边界：basin.shp"]}
        dashboard = {"datasets": [{"name": "station", "type": "table"}, {"name": "basin", "type": "vector"}]}

        outcome = build_task_outcome("upload", result, dashboard=dashboard)

        self.assertTrue(outcome["has_results"])
        self.assertIn("station.csv", outcome["summary"])
        self.assertEqual(outcome["recommendations"], [])

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
                            "artifact_id": "artifact_xgb_metrics",
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
        self.assertNotIn("download_url", panel["files"][0])
        self.assertNotIn("path", panel["files"][0])

    def test_result_panel_filters_legacy_path_download_without_artifact_id(self) -> None:
        from core.api_helpers import _build_result_panel

        panel = _build_result_panel(
            {"task_outcome": {"summary": "legacy result", "has_results": True}},
            {
                "model_results": [
                    {
                        "artifacts": [
                            {
                                "label": "legacy metrics",
                                "path": "derived/xgb_metrics.csv",
                                "download_url": "/api/files/artifact?path=derived/xgb_metrics.csv",
                            }
                        ]
                    }
                ],
                "artifacts": [],
            },
        )

        self.assertEqual(panel["files"], [])

    def test_result_panel_filters_raw_job_download_without_artifact_id(self) -> None:
        from core.api_helpers import _build_result_panel

        panel = _build_result_panel(
            {"task_outcome": {"summary": "raw job result", "has_results": True}},
            {
                "model_results": [],
                "artifacts": [
                    {
                        "label": "raw job zip",
                        "download_url": "/api/downloads/artifact?user_id=u1&job_id=job_1&path=derived/downloads/job_1/result.zip",
                    }
                ],
            },
        )

        self.assertEqual(panel["files"], [])

    def test_result_panel_filters_unregistered_download_url_without_artifact_id(self) -> None:
        from core.api_helpers import _build_result_panel

        panel = _build_result_panel(
            {"task_outcome": {"summary": "unregistered result", "has_results": True}},
            {
                "model_results": [],
                "artifacts": [
                    {
                        "label": "loose csv",
                        "download_url": "/downloads/loose.csv",
                    }
                ],
            },
        )

        self.assertEqual(panel["files"], [])

    def test_result_panel_prefers_current_response_artifacts(self) -> None:
        from core.api_helpers import _build_result_panel

        response = {
            "task_outcome": {"summary": "XGBoost model finished"},
            "artifacts": [
                {
                    "artifact_id": "artifact_current_predictions",
                    "title": "current_predictions.csv",
                    "path": "derived/current_predictions.csv",
                    "download_url": "/api/artifacts/artifact_current_predictions/download",
                    "type": "csv",
                }
            ],
        }
        dashboard = {
            "model_results": [
                {
                    "model": "XGBoost",
                    "artifacts": [
                        {
                            "artifact_id": "artifact_old_metrics",
                            "label": "old_metrics.csv",
                            "path": "derived/old_metrics.csv",
                            "download_url": "/api/artifacts/artifact_old_metrics/download",
                        }
                    ],
                }
            ],
            "artifacts": [],
        }

        panel = _build_result_panel(response, dashboard)

        self.assertEqual(panel["files"][0]["artifact_id"], "artifact_current_predictions")
        self.assertNotIn("download_url", panel["files"][0])
        self.assertNotIn("path", panel["files"][0])


if __name__ == "__main__":
    unittest.main()
