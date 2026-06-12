from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.api_security import optional_authenticated_session, require_admin_token, require_authenticated_user, require_resource_owner
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

    def test_auth_me_probe_does_not_fail_when_logged_out(self):
        payload = optional_authenticated_session(self.service, session_id="", session_token="")

        self.assertEqual(payload, {"authenticated": False, "user": None})

    def test_auth_me_probe_returns_current_user_when_logged_in(self):
        payload = optional_authenticated_session(
            self.service,
            session_id=self.session["session_id"],
            session_token=self.session["session_token"],
        )

        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["user"]["user_id"], "u_alice")

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

    def test_default_cors_origins_cover_fallback_dev_ports(self):
        from core.api_helpers import _cors_origins

        origins = _cors_origins()

        self.assertIn("http://127.0.0.1:5173", origins)
        self.assertIn("http://127.0.0.1:5174", origins)
        self.assertIn("http://127.0.0.1:5175", origins)

    def test_request_session_ignores_query_tokens(self):
        from starlette.datastructures import Headers, QueryParams

        from core.api_helpers import _request_session

        class RequestStub:
            headers = Headers({})
            cookies = {}
            query_params = QueryParams("session_id=sid&session_token=secret")

        self.assertEqual(_request_session(RequestStub()), ("", ""))

    def test_request_admin_token_ignores_query_token(self):
        from starlette.datastructures import Headers, QueryParams

        from core.api_helpers import _request_admin_token

        class RequestStub:
            headers = Headers({})
            query_params = QueryParams("admin_token=secret")

        self.assertEqual(_request_admin_token(RequestStub()), "")


if __name__ == "__main__":
    unittest.main()
