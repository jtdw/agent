from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from core.diagnostic_views import DiagnosticEventView, diagnostic_event_view, diagnostic_event_views


class DiagnosticEventViewTests(unittest.TestCase):
    def test_schema_rejects_raw_extra_fields(self) -> None:
        with self.assertRaises(ValidationError):
            DiagnosticEventView.model_validate(
                {
                    "timestamp": "",
                    "phase": "download",
                    "level": "info",
                    "summary": "ok",
                    "error_code": "",
                    "next_action": "",
                    "session_id": "s_1",
                }
            )

    def test_diagnostic_event_view_filters_internal_details(self) -> None:
        raw = {
            "updated_at": "2026-06-21T10:00:00",
            "stage": "download",
            "status": "failed",
            "message": r"Traceback in E:\\agent\\workspace\\secret.log with token=abc",
            "failure_diagnostic": {
                "user_message": "请重新登录后重试。",
                "next_action": "login_required",
                "code": "LOGIN_REQUIRED",
            },
            "user_id": "u_1",
            "session_id": "s_1",
        }

        view = diagnostic_event_view(raw)
        rendered = json.dumps(view, ensure_ascii=False)

        self.assertEqual(view["level"], "error")
        self.assertEqual(view["summary"], "请重新登录后重试。")
        self.assertEqual(view["error_code"], "LOGIN_REQUIRED")
        self.assertNotIn("user_id", rendered)
        self.assertNotIn("session_id", rendered)
        self.assertNotIn("token", rendered.lower())
        self.assertNotIn("Traceback", rendered)
        self.assertNotIn("E:", rendered)

    def test_batch_keeps_only_safe_standard_fields(self) -> None:
        views = diagnostic_event_views([{"stage": "scan", "status": "running", "pages_scanned": 3}])

        self.assertEqual(len(views), 1)
        self.assertEqual(set(views[0]), {"schema_version", "timestamp", "phase", "level", "summary", "error_code", "next_action"})


if __name__ == "__main__":
    unittest.main()
