from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


class ReliabilityLifecycleTests(unittest.TestCase):
    def test_configured_product_rejects_unknown_adapter(self) -> None:
        from core.capability_config import CapabilityConfigStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = CapabilityConfigStore(Path(tmp))
            with self.assertRaisesRegex(ValueError, "download_adapter"):
                store.upsert_product(
                    {
                        "product_id": "evil_product",
                        "display_name_zh": "恶意产品",
                        "source": "gscloud",
                        "resource_type": "dem",
                        "supported_resolutions": ["30m"],
                        "temporal_requirement": "none",
                        "tool_card": "submit_commercial_download_job",
                        "download_adapter": "os.system:curl http://example.invalid",
                    }
                )

    def test_configured_asset_rejects_unverified_client_path(self) -> None:
        from core.capability_config import CapabilityConfigStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = CapabilityConfigStore(Path(tmp))
            with self.assertRaisesRegex(ValueError, "verified"):
                store.upsert_asset(
                    {
                        "asset_id": "public:basin:unsafe",
                        "name": "Unsafe",
                        "source": "admin_upload",
                        "asset_type": "boundary",
                        "path": "C:/Users/alice/Desktop/private.shp",
                        "crs": "EPSG:4326",
                        "bounds": [100, 30, 101, 31],
                        "geometry_type": "Polygon",
                        "permission": "public",
                        "version": "v1",
                        "status": "enabled",
                        "asset_profile": {"feature_count": 1},
                    }
                )

    def test_capability_config_persists_across_store_instances(self) -> None:
        from core.capability_config import CapabilityConfigStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            CapabilityConfigStore(root).upsert_knowledge(
                {
                    "knowledge_id": "persisted",
                    "title": "Persisted",
                    "source": "admin",
                    "language": "en",
                    "tags": ["soil"],
                    "applicable_scope": "general",
                    "reliability": "medium",
                    "version": "v1",
                    "status": "enabled",
                    "content": "soil moisture matching",
                }
            )
            fresh = CapabilityConfigStore(root)
            self.assertEqual(fresh.retrieve_knowledge("soil", limit=1)[0]["knowledge_id"], "persisted")

    def test_durable_job_store_idempotency_cancel_and_restart_recovery(self) -> None:
        from core.durable_jobs import DurableJobStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = DurableJobStore(Path(tmp) / "jobs.db")
            first = store.submit_job(
                plan_id="plan_a",
                user_id="u1",
                session_id="s1",
                job_type="modeling",
                idempotency_key="same-plan",
                payload={"tool": "xgb"},
            )
            duplicate = store.submit_job(
                plan_id="plan_a",
                user_id="u1",
                session_id="s1",
                job_type="modeling",
                idempotency_key="same-plan",
                payload={"tool": "xgb"},
            )
            self.assertEqual(first["job_id"], duplicate["job_id"])
            running = store.update_status(first["job_id"], "running", progress=10)
            self.assertEqual(running["status"], "running")
            cancelled = store.cancel_job(first["job_id"], user_id="u1", reason="user requested")
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertIn("CANCELLED", cancelled["tool_result"]["error_code"])

            second = store.submit_job(plan_id="plan_b", user_id="u1", session_id="s1", job_type="download", payload={})
            store.update_status(second["job_id"], "running", progress=40)
            recovered = DurableJobStore(Path(tmp) / "jobs.db").recover_interrupted_jobs()
            self.assertEqual(recovered["count"], 1)
            recovered_job = store.get_job(second["job_id"])
            self.assertEqual(recovered_job["status"], "awaiting_confirmation")
            self.assertEqual(recovered_job["error_code"], "JOB_RECOVERED_AFTER_RESTART")

    def test_quality_checker_rejects_zip_bomb_and_traversal(self) -> None:
        from core.data_quality import validate_zip_upload

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            traversal = root / "traversal.zip"
            with zipfile.ZipFile(traversal, "w") as zf:
                zf.writestr("../evil.txt", "bad")
            result = validate_zip_upload(traversal)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "ZIP_PATH_TRAVERSAL")

            too_many = root / "too_many.zip"
            with zipfile.ZipFile(too_many, "w") as zf:
                for index in range(6):
                    zf.writestr(f"file_{index}.txt", "x")
            result = validate_zip_upload(too_many, max_files=5)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "ZIP_TOO_MANY_FILES")

    def test_output_artifact_quality_requires_existing_nonempty_file(self) -> None:
        from core.data_quality import validate_output_artifact

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            missing = validate_output_artifact(root / "missing.tif")
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["error_code"], "ARTIFACT_MISSING")

            empty = root / "empty.tif"
            empty.write_bytes(b"")
            empty_result = validate_output_artifact(empty)
            self.assertFalse(empty_result["ok"])
            self.assertEqual(empty_result["error_code"], "ARTIFACT_EMPTY")

            valid = root / "valid.txt"
            valid.write_text("ok", encoding="utf-8")
            ok = validate_output_artifact(valid)
            self.assertTrue(ok["ok"])
            self.assertEqual(ok["status"], "succeeded")

    def test_session_cleanup_removes_private_knowledge_and_marks_jobs_cancelled(self) -> None:
        from core.capability_config import CapabilityConfigStore
        from core.durable_jobs import DurableJobStore
        from core.lifecycle_cleanup import cleanup_session_private_state

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            configs = root / "capability"
            jobs_db = root / "jobs.db"
            store = CapabilityConfigStore(configs)
            store.upsert_knowledge(
                {
                    "knowledge_id": "private_doc",
                    "title": "Private",
                    "source": "user_upload",
                    "language": "en",
                    "tags": ["private"],
                    "applicable_scope": "general",
                    "reliability": "untrusted",
                    "version": "v1",
                    "status": "enabled",
                    "content": "private session knowledge",
                    "owner_user_id": "u1",
                    "session_id": "s1",
                    "scope": "private",
                }
            )
            store.upsert_knowledge(
                {
                    "knowledge_id": "system_doc",
                    "title": "System",
                    "source": "admin",
                    "language": "en",
                    "tags": ["system"],
                    "applicable_scope": "general",
                    "reliability": "medium",
                    "version": "v1",
                    "status": "enabled",
                    "content": "system knowledge",
                    "scope": "system",
                }
            )
            jobs = DurableJobStore(jobs_db)
            job = jobs.submit_job(plan_id="plan", user_id="u1", session_id="s1", job_type="download", payload={})
            cleanup = cleanup_session_private_state("u1", "s1", capability_root=configs, durable_job_db=jobs_db)
            self.assertIn("private_doc", cleanup["disabled_private_knowledge"])
            self.assertIn(job["job_id"], cleanup["cancelled_jobs"])
            self.assertFalse(store.retrieve_knowledge("private", limit=1))
            self.assertEqual(store.retrieve_knowledge("system", limit=1)[0]["knowledge_id"], "system_doc")


if __name__ == "__main__":
    unittest.main()
