from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.commercial.service import CommercialService
from core.workspace_db import WorkspaceDatabase
from scripts.reset_runtime_data import execute_runtime_reset


class RuntimeDataResetTests(unittest.TestCase):
    def test_reset_preserves_accounts_and_storage_state_but_removes_runtime_results(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            project = Path(temp_dir) / "project"
            workspace = project / "workspace"
            backup = Path(temp_dir) / "backup"
            commercial = CommercialService(workspace)
            commercial.register_user("user@example.com", "password1", user_id="u_1")
            commercial.register_user("audit.123@example.com", "password1", user_id="u_audit")
            commercial.submit_job(user_id="u_1", source_key="gscloud", resource_type="dem", region="成都")
            state = workspace / "domestic_auth" / "user_u_1_gscloud_storage_state.json"
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(json.dumps({"cookies": [{"name": "session", "value": "secret"}]}), encoding="utf-8")
            commercial.set_user_credential_storage_state("u_1", "gscloud", str(state))
            (workspace / "domestic_auth" / "login_jobs").mkdir()
            (workspace / "domestic_auth" / "login_jobs" / "login.json").write_text("{}", encoding="utf-8")
            (workspace / "users" / "u_1" / "derived").mkdir(parents=True)
            (workspace / "users" / "u_1" / "derived" / "result.tif").write_bytes(b"raster")
            root_db = WorkspaceDatabase(workspace / "workspace.db")
            with root_db._connect() as conn:
                conn.execute("INSERT INTO conversations(session_id,title,created_at,updated_at) VALUES('s1','old','now','now')")
            (workspace / "local_library").mkdir()
            (workspace / "local_library" / "obsolete.txt").write_text("old", encoding="utf-8")

            manifest_path = execute_runtime_reset(project, backup)

            preserved = CommercialService(workspace)
            self.assertEqual(preserved.get_user("u_1")["email"], "user@example.com")
            with self.assertRaises(ValueError):
                preserved.get_user("u_audit")
            self.assertEqual(preserved.list_jobs(user_id="u_1"), [])
            self.assertEqual(preserved.get_user_storage_state_path("u_1", "gscloud"), str(state))
            self.assertTrue(state.exists())
            self.assertFalse((workspace / "domestic_auth" / "login_jobs" / "login.json").exists())
            self.assertFalse((workspace / "users").exists())
            self.assertFalse((workspace / "local_library").exists())
            with sqlite3.connect(workspace / "workspace.db") as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 0)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "completed")
            self.assertNotIn('"value": "secret"', json.dumps(manifest))
            self.assertTrue((backup / "commercial.db").exists())


if __name__ == "__main__":
    unittest.main()
