from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.capability_config import CapabilityConfigStore
from core.commercial.scene_jobs import gscloud_scene_jobs_dir, list_gscloud_scene_jobs
from core.commercial.service import CommercialService
from core.commercial.tile_jobs import gscloud_tile_jobs_dir, list_gscloud_tile_jobs
from core.config import Settings
from core.durable_jobs import DurableJobStore
from core.lifecycle_cleanup import cleanup_session_private_state
from core.map_layers import MapLayerService
from core.service import GISWorkspaceService


class SessionHardDeleteTests(unittest.TestCase):
    def test_hard_delete_removes_private_knowledge_and_durable_job_payloads_after_restart(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            config_root = root / "capability"
            jobs_db = root / "durable_jobs.db"
            store = CapabilityConfigStore(config_root)
            store.upsert_knowledge(
                {
                    "knowledge_id": "private_doc",
                    "title": "Private Doc",
                    "source": "user_upload",
                    "language": "en",
                    "tags": ["private"],
                    "applicable_scope": "general",
                    "reliability": "untrusted",
                    "version": "v1",
                    "status": "enabled",
                    "content": "private retained memory",
                    "owner_user_id": "u1",
                    "session_id": "s1",
                    "scope": "private",
                }
            )
            store.upsert_knowledge(
                {
                    "knowledge_id": "system_doc",
                    "title": "System Doc",
                    "source": "admin",
                    "language": "en",
                    "tags": ["system"],
                    "applicable_scope": "general",
                    "reliability": "medium",
                    "version": "v1",
                    "status": "enabled",
                    "content": "system retained knowledge",
                    "scope": "system",
                }
            )
            jobs = DurableJobStore(jobs_db)
            durable = jobs.submit_job(
                plan_id="plan_private",
                user_id="u1",
                session_id="s1",
                job_type="modeling",
                payload={"secret_input": "private retained memory"},
            )
            jobs.update_status(durable["job_id"], "running", result={"artifact": "private.csv"})

            cleanup = cleanup_session_private_state("u1", "s1", capability_root=config_root, durable_job_db=jobs_db)

            self.assertIn("private_doc", cleanup["hard_deleted_private_knowledge"])
            self.assertIn(durable["job_id"], cleanup["hard_deleted_durable_jobs"])
            fresh_store = CapabilityConfigStore(config_root)
            self.assertFalse(fresh_store.retrieve_knowledge("private", limit=5))
            self.assertEqual(fresh_store.retrieve_knowledge("system", limit=1)[0]["knowledge_id"], "system_doc")
            with self.assertRaises(FileNotFoundError):
                DurableJobStore(jobs_db).get_job(durable["job_id"])
            raw = (config_root / "knowledge.json").read_text(encoding="utf-8")
            self.assertNotIn("private retained memory", raw)

    def test_hard_delete_removes_workspace_artifacts_layers_and_model_context_after_restart(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(workdir=Path(tmp)))
            service.current_user_id = "u1"
            session_id = service.create_new_session("hard-delete")
            service.manager.set_runtime_scope("u1", session_id)
            artifact_path = service.manager.derived_dir / "result.txt"
            artifact_path.write_text("private artifact", encoding="utf-8")
            artifact = service.manager.register_artifact(path=str(artifact_path), type="file", title="private result")
            service.manager.register_model_result(
                model_result_id="model_private",
                model_name="xgb",
                output_prefix="private",
                artifacts=[artifact],
                metrics={"r2": 0.9},
            )
            self.assertIsNotNone(service.manager.get_artifact(artifact["artifact_id"]))
            self.assertTrue(service.manager.database.list_model_results())

            service.delete_session(session_id)

            restarted = GISWorkspaceService(Settings(workdir=Path(tmp)))
            restarted.current_user_id = "u1"
            self.assertFalse((Path(tmp) / "sessions" / session_id).exists())
            restarted.manager.set_runtime_scope("u1", session_id)
            self.assertIsNone(restarted.manager.get_artifact(artifact["artifact_id"]))
            self.assertFalse(restarted.manager.database.list_model_results())
            layers = MapLayerService(restarted).workspace_layers(user_id="u1", session_id=session_id)
            self.assertFalse(any(layer.get("artifact_id") == artifact["artifact_id"] for layer in layers["layers"]))

    def test_commercial_scene_tile_and_download_jobs_are_hard_deleted_for_session(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            commercial = CommercialService(root)
            commercial.create_user("u1@example.invalid", plan="basic", user_id="u1")
            job = commercial.submit_job(user_id="u1", source_key="fixture", resource_type="dem", region="test", account_mode="own", session_id="s1")
            scene_path = gscloud_scene_jobs_dir(root) / "scene_private.json"
            scene_log = scene_path.with_suffix(".log")
            scene_path.write_text(json.dumps({"scene_job_id": "scene_private", "job_id": job["job_id"], "session_id": "s1"}), encoding="utf-8")
            scene_log.write_text("private log", encoding="utf-8")
            tile_path = gscloud_tile_jobs_dir(root) / "tile_private.json"
            tile_log = tile_path.with_suffix(".log")
            tile_path.write_text(json.dumps({"tile_job_id": "tile_private", "job_id": job["job_id"], "session_id": "s1"}), encoding="utf-8")
            tile_log.write_text("private log", encoding="utf-8")

            cleanup = commercial.hard_delete_session_jobs("u1", "s1")

            self.assertIn(job["job_id"], cleanup["deleted_download_jobs"])
            self.assertFalse(scene_path.exists())
            self.assertFalse(scene_log.exists())
            self.assertFalse(tile_path.exists())
            self.assertFalse(tile_log.exists())
            self.assertEqual(commercial.list_jobs("u1", session_id="s1"), [])
            self.assertFalse(any(item.get("job_id") == job["job_id"] for item in list_gscloud_scene_jobs(root, limit=20)))
            self.assertFalse(any(item.get("job_id") == job["job_id"] for item in list_gscloud_tile_jobs(root, limit=20)))


if __name__ == "__main__":
    unittest.main()
