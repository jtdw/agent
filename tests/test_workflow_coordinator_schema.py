from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from core.workflow_coordinator import CoordinatorDecision, build_coordinator_decision


class WorkflowCoordinatorSchemaTests(unittest.TestCase):
    def test_valid_decision_schema(self) -> None:
        decision = CoordinatorDecision.model_validate(
            {
                "decision": "continue",
                "next_step_id": "reproject_dem",
                "selected_next_action": "reproject raster before clipping",
                "required_tool": "raster_reproject",
                "required_inputs": {"raster_name": "dem", "target_crs": "EPSG:4326"},
                "reason": "CRS mismatch can be repaired by a planned reproject step.",
                "user_question": "",
                "confidence": 0.82,
            }
        )

        self.assertEqual(decision.decision, "continue")
        self.assertEqual(decision.required_tool, "raster_reproject")

    def test_invalid_decision_enum_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CoordinatorDecision.model_validate(
                {
                    "decision": "download_more_data",
                    "next_step_id": "x",
                    "selected_next_action": "",
                    "required_tool": "download_dem",
                    "required_inputs": {},
                    "reason": "bad",
                    "user_question": "",
                    "confidence": 0.9,
                }
            )

    def test_low_confidence_or_unavailable_client_stops_without_continue(self) -> None:
        plan = {"workflow_plan": [{"step_id": "describe", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": "points"}}]}
        trace = {"results": [], "remaining_step_ids": ["describe"], "executed_step_ids": []}

        unavailable = build_coordinator_decision(plan, current_step=None, remaining_steps=plan["workflow_plan"], execution_trace=trace, user_request="describe points")
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["decision"].decision, "stop_failure")

        low = build_coordinator_decision(
            plan,
            current_step=None,
            remaining_steps=plan["workflow_plan"],
            execution_trace=trace,
            user_request="describe points",
            client=lambda payload: json.dumps(
                {
                    "decision": "continue",
                    "next_step_id": "describe",
                    "selected_next_action": "",
                    "required_tool": "describe_dataset",
                    "required_inputs": {},
                    "reason": "maybe",
                    "user_question": "",
                    "confidence": 0.2,
                }
            ),
        )
        self.assertEqual(low["status"], "low_confidence")
        self.assertEqual(low["decision"].decision, "stop_failure")


if __name__ == "__main__":
    unittest.main()
