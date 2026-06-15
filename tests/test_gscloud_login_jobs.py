from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.commercial.login_jobs import request_gscloud_login_stop, start_gscloud_login_process


class GSCloudLoginJobTests(unittest.TestCase):
    def test_start_reuses_live_login_job_for_same_user(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp)
            with (
                patch("core.commercial.login_jobs._process_is_alive", return_value=True),
                patch("core.commercial.login_jobs.subprocess.Popen") as popen,
            ):
                popen.return_value.pid = 4321
                first = start_gscloud_login_process(
                    workdir=workdir,
                    subject_type="customer",
                    subject_id="user-1",
                    state_path=workdir / "state.json",
                )
                second = start_gscloud_login_process(
                    workdir=workdir,
                    subject_type="customer",
                    subject_id="user-1",
                    state_path=workdir / "state.json",
                )

            self.assertEqual(second["login_job_id"], first["login_job_id"])
            self.assertTrue(second["reused"])
            self.assertEqual(popen.call_count, 1)

    def test_stop_request_is_persisted_for_worker(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp)
            jobs = workdir / "domestic_auth" / "login_jobs"
            jobs.mkdir(parents=True)
            path = jobs / "login_one.json"
            path.write_text(json.dumps({"login_job_id": "login_one", "state": "BROWSER_OPEN"}), encoding="utf-8")

            stopped = request_gscloud_login_stop(workdir, "login_one")

            self.assertEqual(stopped["state"], "STOP_REQUESTED")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "STOP_REQUESTED")


if __name__ == "__main__":
    unittest.main()
