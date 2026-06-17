from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.reset_agent_data import build_reset_plan, reset_agent_data


class ResetAgentDataScriptTests(unittest.TestCase):
    def test_dry_run_does_not_delete_files(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp)
            uploads = workdir / "uploads"
            uploads.mkdir()
            marker = uploads / "source.txt"
            marker.write_text("source", encoding="utf-8")

            result = reset_agent_data(workdir, "keep-accounts", yes=False)

            self.assertTrue(result["dry_run"])
            self.assertTrue(marker.exists())
            self.assertIn(str(uploads.resolve()), result["plan"]["paths"])

    def test_keep_accounts_preserves_commercial_users_and_removes_runtime_tables(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp)
            db_path = workdir / "commercial.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE commercial_users (
                        user_id TEXT PRIMARY KEY,
                        platform_monthly_used INTEGER DEFAULT 0,
                        login_failed_count INTEGER DEFAULT 0,
                        locked_until TEXT,
                        last_login_at TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE download_jobs (job_id TEXT PRIMARY KEY);
                    CREATE TABLE login_sessions (session_id TEXT PRIMARY KEY);
                    """
                )
                conn.execute("INSERT INTO commercial_users (user_id, platform_monthly_used, login_failed_count) VALUES ('u1', 3, 2)")
                conn.execute("INSERT INTO download_jobs (job_id) VALUES ('j1')")
                conn.execute("INSERT INTO login_sessions (session_id) VALUES ('s1')")

            result = reset_agent_data(workdir, "keep-accounts", yes=True)

            self.assertFalse(result["dry_run"])
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM commercial_users").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT platform_monthly_used, login_failed_count FROM commercial_users").fetchone(), (0, 0))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM download_jobs").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM login_sessions").fetchone()[0], 0)

    def test_custom_uploads_only_removes_uploads(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp)
            uploads = workdir / "uploads"
            derived = workdir / "derived"
            uploads.mkdir()
            derived.mkdir()
            (uploads / "a.txt").write_text("a", encoding="utf-8")
            (derived / "b.txt").write_text("b", encoding="utf-8")

            result = reset_agent_data(workdir, "custom", {"uploads"}, yes=True)

            self.assertFalse((uploads / "a.txt").exists())
            self.assertTrue((derived / "b.txt").exists())
            self.assertEqual(build_reset_plan(workdir, "custom", {"uploads"})["mode"], "custom")
            self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
