from __future__ import annotations

import unittest

from domain.chat.actions import (
    ChatActionType,
    clarification_action,
    login_required_action,
    normalize_action,
)


class ChatActionContractTests(unittest.TestCase):
    def test_login_action_keeps_only_public_resume_fields(self) -> None:
        action = login_required_action(provider="gscloud", job_id="job_1")

        self.assertEqual(action["type"], ChatActionType.LOGIN_REQUIRED.value)
        self.assertEqual(action["provider"], "gscloud")
        self.assertEqual(action["job_id"], "job_1")
        self.assertNotIn("storage_state", action)

    def test_clarification_action_deduplicates_missing_parameters(self) -> None:
        action = clarification_action(
            ["region", "region", "resolution"],
            recommended_defaults={"resolution": "30m"},
            options=[{"id": "current_region", "label": "当前研究区"}],
        )

        self.assertEqual(action["missing_parameters"], ["region", "resolution"])
        self.assertEqual(action["recommended_defaults"]["resolution"], "30m")

    def test_unknown_action_is_rejected(self) -> None:
        self.assertIsNone(normalize_action({"type": "run_arbitrary_code", "command": "secret"}))


if __name__ == "__main__":
    unittest.main()
