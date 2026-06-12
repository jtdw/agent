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


if __name__ == "__main__":
    unittest.main()
