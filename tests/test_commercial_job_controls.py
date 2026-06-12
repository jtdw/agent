from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from core.commercial.service import CommercialService


class CommercialJobControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp.name)
        self.service = CommercialService(self.workdir)
        self.user = self.service.create_user("user@example.com", plan="pro", user_id="u_test")
        self.account = self.service.add_platform_account("gscloud", label="pool", daily_limit=2, monthly_limit=2)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_platform_job_reserves_quota_on_submit_and_success_does_not_double_charge(self):
        job = self.service.submit_job(
            user_id=self.user["user_id"],
            source_key="gscloud",
            resource_type="landsat8_oli_tirs",
            region="成都",
            account_mode="platform",
        )

        reserved_user = self.service.get_user(self.user["user_id"])
        reserved_account = self.service.list_platform_accounts("gscloud")[0]
        self.assertEqual(reserved_user["platform_monthly_used"], 1)
        self.assertEqual(reserved_account["used_today"], 1)
        self.assertEqual(job["quota_reserved"], 1)

        result_path = self.workdir / "downloads" / "result.zip"
        result_path.parent.mkdir()
        with zipfile.ZipFile(result_path, "w") as archive:
            archive.writestr("result.txt", "ok")
        done = self.service.run_job_with_result(job["job_id"], {"path": str(result_path)})
        charged_user = self.service.get_user(self.user["user_id"])
        charged_account = self.service.list_platform_accounts("gscloud")[0]

        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["charged"], 1)
        self.assertEqual(done["quota_reserved"], 0)
        self.assertEqual(charged_user["platform_monthly_used"], 1)
        self.assertEqual(charged_account["used_today"], 1)

    def test_failed_or_canceled_reserved_job_releases_quota(self):
        failed_job = self.service.submit_job(
            user_id=self.user["user_id"],
            source_key="gscloud",
            resource_type="sentinel2_msi",
            region="成都",
            account_mode="platform",
        )
        self.service.fail_job(failed_job["job_id"], "source failed")
        self.assertEqual(self.service.get_user(self.user["user_id"])["platform_monthly_used"], 0)

        canceled_job = self.service.submit_job(
            user_id=self.user["user_id"],
            source_key="gscloud",
            resource_type="sentinel2_msi",
            region="成都",
            account_mode="platform",
        )
        result = self.service.cancel_job(canceled_job["job_id"], user_id=self.user["user_id"], reason="user canceled")

        self.assertEqual(result["status"], "canceled")
        self.assertEqual(result["quota_reserved"], 0)
        self.assertEqual(self.service.get_user(self.user["user_id"])["platform_monthly_used"], 0)

    def test_retry_job_clones_failed_job_with_new_id_and_reserves_again(self):
        job = self.service.submit_job(
            user_id=self.user["user_id"],
            source_key="gscloud",
            resource_type="modev1f_evi_5day",
            region="成都",
            account_mode="platform",
            request_text="下载成都 EVI",
            output_name="chengdu_evi",
        )
        self.service.fail_job(job["job_id"], "temporary error")

        retry = self.service.retry_job(job["job_id"], user_id=self.user["user_id"])

        self.assertNotEqual(retry["job_id"], job["job_id"])
        self.assertEqual(retry["resource_type"], "modev1f_evi_5day")
        self.assertEqual(retry["region"], "成都")
        self.assertEqual(retry["request_text"], "下载成都 EVI")
        self.assertEqual(retry["retried_from_job_id"], job["job_id"])
        self.assertEqual(retry["quota_reserved"], 1)

    def test_running_job_must_be_canceled_before_delete(self):
        job = self.service.submit_job(
            user_id=self.user["user_id"],
            source_key="gscloud",
            resource_type="sentinel2_msi",
            region="成都",
            account_mode="platform",
        )
        self.service._update_job(job["job_id"], status="running", stage="downloading")

        with self.assertRaises(ValueError):
            self.service.delete_job(job["job_id"], user_id=self.user["user_id"])

        self.service.cancel_job(job["job_id"], user_id=self.user["user_id"])
        result = self.service.delete_job(job["job_id"], user_id=self.user["user_id"])
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
