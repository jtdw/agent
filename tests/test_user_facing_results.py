from __future__ import annotations

import json
import unittest

from core.user_facing_results import build_user_facing_result, public_artifact_card


class UserFacingResultsTests(unittest.TestCase):
    def test_public_artifact_card_keeps_only_canonical_artifact_download_url(self) -> None:
        legacy = public_artifact_card(
            {
                "artifact_id": "artifact_metrics",
                "name": "metrics.csv",
                "download_url": "/api/files/artifact?path=derived/metrics.csv",
            },
            include_preview=False,
        )
        loose = public_artifact_card(
            {
                "artifact_id": "artifact_loose",
                "name": "loose.csv",
                "download_url": "/downloads/loose.csv",
            },
            include_preview=False,
        )
        canonical = public_artifact_card(
            {
                "artifact_id": "artifact_metrics",
                "name": "metrics.csv",
                "download_url": "/api/artifacts/artifact_metrics/download?user_id=u1&session_id=s1",
            },
            include_preview=False,
        )

        self.assertEqual(legacy["download_url"], "")
        self.assertEqual(loose["download_url"], "")
        self.assertEqual(canonical["download_url"], "/api/artifacts/artifact_metrics/download?user_id=u1&session_id=s1")

    def test_fallback_user_facing_result_hides_legacy_raw_payload_details(self) -> None:
        result = build_user_facing_result(
            {
                "summary": "旧结果已迁移",
                "path": r"E:\agent\workspace\users\u1\sessions\s1\derived\legacy.csv",
                "download_url": "/api/downloads/artifact?job_id=job_1&path=derived/legacy.csv",
                "storage_state_path": r"E:\agent\workspace\domestic_auth\storage_state.json",
                "nested": {
                    "output_path": r"E:\agent\workspace\users\u1\sessions\s1\derived\legacy.tif",
                    "message": "Traceback at storage_state.json",
                    "linux_log": "/tmp/secret/runtime.log",
                    "linux_report": "/home/app/private/report.json",
                },
                "linux_audit": "/var/log/gis-agent/audit.log",
            }
        )

        rendered = json.dumps(result, ensure_ascii=False)

        self.assertEqual(result["summary"], "旧结果已迁移")
        self.assertNotIn("raw_result", rendered)
        self.assertNotIn("download_url", rendered)
        self.assertNotIn("storage_state_path", rendered)
        self.assertNotIn("output_path", rendered)
        self.assertNotIn("E:\\agent", rendered)
        self.assertNotIn("/tmp/secret", rendered)
        self.assertNotIn("/home/app/private", rendered)
        self.assertNotIn("/var/log/gis-agent", rendered)
        self.assertNotIn("/api/downloads/artifact", rendered)
        self.assertNotIn("Traceback", rendered)


if __name__ == "__main__":
    unittest.main()
