from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TrialMonitoringTests(unittest.TestCase):
    def test_trial_metrics_are_persisted_sanitized_and_reportable(self) -> None:
        from core.trial_monitoring import TrialMonitoringStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = Path(tmp) / "trial_monitoring.db"
            store = TrialMonitoringStore(db_path)
            store.record_metric(
                "validator_blocked",
                status="blocked",
                reason_code="CRS_MISSING",
                actor_type="trial_user",
                severity="P1",
                detail={"path": r"E:\secret\workspace\file.tif", "token": "abc", "summary": "CRS missing"},
            )
            store.record_metric(
                "planner_success",
                status="succeeded",
                reason_code="OK",
                actor_type="automated_test",
                detail={"prompt": "不要保存用户原文全文"},
            )

            report = TrialMonitoringStore(db_path).report(exclude_actor_types={"automated_test"})

            self.assertEqual(report["metrics"]["validator_blocked"]["count"], 1)
            self.assertEqual(report["metrics"].get("planner_success", {}).get("count", 0), 0)
            self.assertEqual(report["alerts"]["P1"], 1)
            rendered = str(report)
            self.assertNotIn("E:\\secret", rendered)
            self.assertNotIn("abc", rendered)
            self.assertNotIn("不要保存用户原文全文", rendered)


if __name__ == "__main__":
    unittest.main()
