from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.api_security import require_admin_token, require_authenticated_user, require_resource_owner
from core.commercial.service import CommercialService


class ApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = CommercialService(Path(self.tmp.name))
        self.service.register_user("alice@example.com", "password1", plan="basic", user_id="u_alice")
        self.service.register_user("bob@example.com", "password1", plan="basic", user_id="u_bob")
        self.session = self.service.authenticate_user("alice@example.com", "password1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_authenticated_user_must_match_requested_user(self):
        user_id = require_authenticated_user(
            self.service,
            requested_user_id="u_alice",
            session_id=self.session["session_id"],
            session_token=self.session["session_token"],
        )

        self.assertEqual(user_id, "u_alice")

    def test_authenticated_user_rejects_cross_user_request(self):
        with self.assertRaises(PermissionError):
            require_authenticated_user(
                self.service,
                requested_user_id="u_bob",
                session_id=self.session["session_id"],
                session_token=self.session["session_token"],
            )

    def test_authenticated_user_requires_session(self):
        with self.assertRaises(PermissionError):
            require_authenticated_user(self.service, requested_user_id="u_alice", session_id="", session_token="")

    def test_admin_token_requires_configured_secret_and_match(self):
        with self.assertRaises(PermissionError):
            require_admin_token("", "anything")
        with self.assertRaises(PermissionError):
            require_admin_token("expected", "wrong")

        self.assertTrue(require_admin_token("expected", "expected"))

    def test_resource_owner_must_match_authenticated_user(self):
        job = {"job_id": "job_1", "user_id": "u_alice"}

        self.assertIs(require_resource_owner(job, user_id="u_alice", resource_name="download job"), job)
        with self.assertRaises(PermissionError):
            require_resource_owner(job, user_id="u_bob", resource_name="download job")


if __name__ == "__main__":
    unittest.main()
