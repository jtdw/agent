from __future__ import annotations

import unittest

from domain.downloads.policies import is_active, is_retryable, is_terminal
from domain.downloads.status import DownloadJobStatus, normalize_status, storage_status


class DownloadDomainStatusTests(unittest.TestCase):
    def test_legacy_database_values_normalize_to_public_states(self) -> None:
        self.assertEqual(normalize_status("completed"), DownloadJobStatus.SUCCESS)
        self.assertEqual(normalize_status("canceled"), DownloadJobStatus.CANCELLED)
        self.assertEqual(storage_status(DownloadJobStatus.SUCCESS), "completed")
        self.assertEqual(storage_status(DownloadJobStatus.CANCELLED), "canceled")

    def test_waiting_states_are_active_but_never_running(self) -> None:
        for status in (DownloadJobStatus.WAITING_LOGIN, DownloadJobStatus.WAITING_PARAMETERS):
            self.assertTrue(is_active(status))
            self.assertTrue(is_retryable(status))
            self.assertNotEqual(status, DownloadJobStatus.RUNNING)

    def test_success_failed_and_cancelled_are_terminal(self) -> None:
        self.assertTrue(is_terminal("success"))
        self.assertTrue(is_terminal("completed"))
        self.assertTrue(is_terminal("failed"))
        self.assertTrue(is_terminal("cancelled"))


if __name__ == "__main__":
    unittest.main()
