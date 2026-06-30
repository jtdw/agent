from __future__ import annotations

import json
import unittest

from core.agent import GISAgent


class AgentReplySelectionTests(unittest.TestCase):
    def test_tool_json_is_not_selected_as_final_reply(self) -> None:
        agent = object.__new__(GISAgent)
        messages = [
            {"role": "user", "content": "检查当前上传数据的字段"},
            {
                "role": "tool",
                "content": json.dumps(
                    {
                        "x_candidates": [{"field": "lon", "numeric_ratio": 1.0}],
                        "y_candidates": [{"field": "lat", "numeric_ratio": 1.0}],
                        "dataset": "demo_xgboost_soil_moisture",
                        "suggestion": "建议优先尝试 x=lon, y=lat。",
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        self.assertEqual(agent._last_nonempty_reply(messages), "")

    def test_tool_json_can_be_converted_to_user_readable_summary(self) -> None:
        agent = object.__new__(GISAgent)
        messages = [
            {"role": "user", "content": "检查当前上传数据的字段"},
            {
                "role": "tool",
                "content": json.dumps(
                    {
                        "x_candidates": [{"field": "lon", "numeric_ratio": 1.0}],
                        "y_candidates": [{"field": "lat", "numeric_ratio": 1.0}],
                        "dataset": "demo_xgboost_soil_moisture",
                        "suggestion": "建议优先尝试 x=lon, y=lat。",
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        reply = agent._latest_tool_result_summary(messages)

        self.assertIn("demo_xgboost_soil_moisture", reply)
        self.assertIn("lon", reply)
        self.assertIn("lat", reply)
        self.assertIn("建议优先尝试", reply)
        self.assertFalse(reply.lstrip().startswith("{"))

    def test_tool_result_json_can_be_converted_to_user_readable_summary(self) -> None:
        agent = object.__new__(GISAgent)
        messages = [
            {"role": "user", "content": "画人口密度图"},
            {
                "role": "tool",
                "content": json.dumps(
                    {
                        "ok": False,
                        "tool_name": "plot_dataset",
                        "task_id": "task_123",
                        "inputs": {"dataset_name": "population_layer", "column": "population"},
                        "outputs": {},
                        "artifacts": [],
                        "summary": "",
                        "diagnostics": {"available_fields": ["density"]},
                        "warnings": [],
                        "next_actions": ["请选择 density 字段，或先计算人口字段。"],
                        "error_code": "FIELD_NOT_FOUND",
                        "error_title": "字段不存在",
                        "user_message": "未找到字段 population。",
                        "technical_detail": "ValueError: population missing",
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        reply = agent._latest_tool_result_summary(messages)

        self.assertIn("plot_dataset", reply)
        self.assertIn("FIELD_NOT_FOUND", reply)
        self.assertIn("未找到字段 population", reply)
        self.assertIn("请选择 density 字段", reply)
        self.assertFalse(reply.lstrip().startswith("{"))

    def test_tool_result_summary_uses_artifact_refs_not_raw_paths(self) -> None:
        agent = object.__new__(GISAgent)
        messages = [
            {"role": "user", "content": "导出结果"},
            {
                "role": "tool",
                "content": json.dumps(
                    {
                        "ok": True,
                        "tool_name": "export_dataset",
                        "task_id": "task_123",
                        "inputs": {"dataset_name": "soil_points"},
                        "outputs": {"path": r"E:\agent\workspace\users\u1\sessions\s1\derived\soil_points.csv"},
                        "artifacts": [
                            {
                                "artifact_id": "artifact_soil_points",
                                "title": "soil_points.csv",
                                "type": "file",
                                "path": r"E:\agent\workspace\users\u1\sessions\s1\derived\soil_points.csv",
                            }
                        ],
                        "summary": "导出完成。",
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        reply = agent._latest_tool_result_summary(messages)

        self.assertIn("artifact_soil_points", reply)
        self.assertIn("soil_points.csv", reply)
        self.assertNotIn("E:\\agent", reply)
        self.assertNotIn("derived\\soil_points.csv", reply)

    def test_tool_result_summary_redacts_legacy_paths_in_summary_text(self) -> None:
        agent = object.__new__(GISAgent)
        messages = [
            {"role": "user", "content": "裁剪栅格"},
            {
                "role": "tool",
                "content": json.dumps(
                    {
                        "ok": True,
                        "tool_name": "clip_raster_by_vector",
                        "task_id": "task_123",
                        "inputs": {"raster_name": "dem", "vector_name": "boundary"},
                        "outputs": {"result_dataset": "clipped_dem"},
                        "artifacts": [{"artifact_id": "artifact_clipped_dem", "title": "clipped_dem.tif"}],
                        "summary": (
                            "裁剪完成，结果栅格: clipped_dem，保存路径: "
                            r"E:\agent\workspace\users\u1\sessions\s1\derived\clipped_dem.tif"
                        ),
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        reply = agent._latest_tool_result_summary(messages)

        self.assertIn("clipped_dem", reply)
        self.assertIn("artifact_clipped_dem", reply)
        self.assertNotIn("E:\\agent", reply)
        self.assertNotIn("workspace\\users", reply)
        self.assertNotIn("保存路径", reply)


if __name__ == "__main__":
    unittest.main()
