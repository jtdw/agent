from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class ReleaseCandidateGovernanceTests(unittest.TestCase):
    def test_capability_resources_default_to_draft_and_require_active_review(self) -> None:
        from core.capability_config import CapabilityConfigStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = CapabilityConfigStore(Path(tmp))
            created = store.upsert_knowledge(
                {
                    "knowledge_id": "rc_doc",
                    "title": "发布候选知识",
                    "source": "admin",
                    "language": "zh-CN",
                    "tags": ["发布候选"],
                    "applicable_scope": "general",
                    "reliability": "medium",
                    "version": "v1",
                    "content": "只有审核通过后才可进入 Planner 检索。",
                    "created_by": "author-a",
                    "change_summary": "initial draft",
                }
            )

            self.assertEqual(created["status"], "draft")
            self.assertEqual(store.retrieve_knowledge("发布候选", limit=3), [])

            pending = store.submit_for_review("knowledge", "rc_doc", actor="author-a", summary="ready")
            self.assertEqual(pending["status"], "pending_review")
            self.assertEqual(store.retrieve_knowledge("发布候选", limit=3), [])

            active = store.approve("knowledge", "rc_doc", actor="reviewer-a", summary="approved for rc")
            self.assertEqual(active["status"], "active")
            self.assertEqual(active["reviewed_by"], "reviewer-a")
            self.assertEqual(active["review_summary"], "approved for rc")
            self.assertEqual(store.retrieve_knowledge("发布候选", limit=1)[0]["knowledge_id"], "rc_doc")

            audit = store.list_audit_events()
            actions = [item["action"] for item in audit]
            self.assertIn("upsert", actions)
            self.assertIn("submit_for_review", actions)
            self.assertIn("approve", actions)

    def test_capability_rollback_creates_reviewable_draft_not_runtime_active(self) -> None:
        from core.capability_config import CapabilityConfigStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = CapabilityConfigStore(Path(tmp))
            first = store.upsert_knowledge(
                {
                    "knowledge_id": "rollback_doc",
                    "title": "Rollback",
                    "source": "admin",
                    "language": "en",
                    "tags": ["rollback"],
                    "applicable_scope": "general",
                    "reliability": "medium",
                    "version": "v1",
                    "status": "active",
                    "content": "first active version",
                }
            )
            store.upsert_knowledge({**first, "version": "v2", "content": "second active version"})
            store.approve("knowledge", "rollback_doc", actor="reviewer", summary="activate v2")

            restored = store.rollback("knowledge", "rollback_doc", "v1", actor="reviewer", summary="prepare rollback")

            self.assertEqual(restored["version"], "v1")
            self.assertEqual(restored["status"], "draft")
            self.assertEqual(store.retrieve_knowledge("first", limit=1), [])

    def test_compat_usage_stats_persist_and_report_last_callers(self) -> None:
        from core.compat_usage import CompatibilityUsageStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = Path(tmp) / "compat_usage.db"
            first = CompatibilityUsageStore(db_path)
            first.record("deprecated_raw_job_api_used", source="GET /api/downloads/jobs", caller="ui_test", request_id="r1", actor_type="automated_test")
            first.record("include_raw", source="GET /api/downloads/jobs", caller="ui_test", request_id="r1", actor_type="automated_test")
            first.record("legacy_download_url_used", source="trial-ui", caller="browser", request_id="r2", actor_type="trial_user")
            first.record_effective_request(source="chat", actor_type="automated_test")
            first.record_effective_request(source="chat", actor_type="trial_user")

            fresh = CompatibilityUsageStore(db_path)
            report = fresh.report()
            trial_report = fresh.report(exclude_actor_types={"automated_test"})

            self.assertEqual(report["counters"]["deprecated_raw_job_api_used"]["count"], 1)
            self.assertEqual(report["counters"]["include_raw"]["count"], 1)
            self.assertEqual(report["effective_request_count"], 2)
            self.assertEqual(report["counters"]["include_raw"]["last_source"], "GET /api/downloads/jobs")
            self.assertEqual(report["counters"]["include_raw"]["actor_type"], "automated_test")
            self.assertEqual(trial_report["counters"]["include_raw"]["count"], 0)
            self.assertEqual(trial_report["counters"]["legacy_download_url_used"]["count"], 1)
            self.assertEqual(trial_report["effective_request_count"], 1)
            self.assertTrue(report["observation_started_at"])
            self.assertTrue(report["generated_at"])


if __name__ == "__main__":
    unittest.main()
