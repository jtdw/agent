from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import api_server


class AdminAgentRuntimeDiagnosticsTests(unittest.TestCase):
    def test_agent_runtime_diagnostics_requires_admin_token(self) -> None:
        with mock.patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False):
            response = TestClient(api_server.app).get("/api/admin/agent-runtime/diagnostics")

        self.assertEqual(response.status_code, 403)

    def test_agent_runtime_diagnostics_returns_sanitized_payload_for_admin(self) -> None:
        class FakeService:
            def agent_runtime_diagnostics(self) -> dict:
                return {
                    "available": True,
                    "mode": "shadow",
                    "context": {"workspace_dir": "E:/secret/workspace", "current_session_id": "s1"},
                    "trace_events": [{"payload": {"token": "secret", "path": "E:/secret/file.env", "ok": True}}],
                }

        with (
            mock.patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False),
            mock.patch.object(api_server, "workspace_for", return_value=FakeService()),
        ):
            response = TestClient(api_server.app).get(
                "/api/admin/agent-runtime/diagnostics",
                headers={"x-admin-token": "secret"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["available"])
        self.assertNotIn("workspace_dir", payload["context"])
        self.assertNotIn("secret", str(payload))
        self.assertNotIn("E:/secret", str(payload))

    def test_agent_runtime_rag_readiness_requires_admin_token(self) -> None:
        with mock.patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False):
            response = TestClient(api_server.app).get("/api/admin/agent-runtime/rag-readiness")

        self.assertEqual(response.status_code, 403)

    def test_agent_runtime_exposure_requires_admin_token(self) -> None:
        with mock.patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False):
            response = TestClient(api_server.app).get("/api/admin/agent-runtime/exposure")

        self.assertEqual(response.status_code, 403)

    def test_agent_runtime_exposure_is_read_only_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            report_path = Path(tmp) / "active_smoke.json"
            report_path.write_text(
                '{"summary":{"passed":3,"failed":0,"ready_for_next_phase":true}}',
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {
                    "GIS_AGENT_ADMIN_TOKEN": "secret",
                    "GIS_AGENT_RUNTIME_V2": "1",
                    "GIS_AGENT_RUNTIME_MODE": "active",
                    "GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER": "1",
                    "GIS_AGENT_RUNTIME_EXPOSURE_ENV": "staging",
                    "GIS_AGENT_RUNTIME_EXPOSURE_PERCENT": "5",
                    "GIS_AGENT_RUNTIME_SMOKE_REPORT": str(report_path),
                    "GIS_AGENT_RUNTIME_ROLLBACK": "0",
                },
                clear=False,
            ):
                response = TestClient(api_server.app).get(
                    "/api/admin/agent-runtime/exposure",
                    headers={"x-admin-token": "secret"},
                )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        rendered = str(payload)
        self.assertEqual(payload["schema_version"], "agent-runtime-exposure-policy/v1")
        self.assertEqual(payload["environment"], "staging")
        self.assertEqual(payload["requested_percent"], 5)
        self.assertTrue(payload["eligible_for_user_exposure"])
        self.assertEqual(payload["deterministic_smoke"]["report_filename"], "active_smoke.json")
        self.assertNotIn(str(report_path), rendered)
        self.assertNotIn(str(Path(tmp)), rendered)

    def test_agent_runtime_rag_readiness_is_read_only_sanitized_and_no_embedding_cost(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store_path = Path(tmp) / "vectors.json"
            store_path.write_text(
                """
{
  "schema_version": "agent-runtime-vector-rag/v1",
  "backend": "api_embedding_persistent",
  "manifest": {
    "created_at": "2026-06-27T00:00:00+00:00",
    "document_count": 3,
    "source_hashes": {"soil": "hash"}
  },
  "documents": []
}
""".strip(),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "GIS_AGENT_ADMIN_TOKEN": "secret",
                        "GIS_AGENT_VECTOR_RAG_BACKEND": "api",
                        "GIS_AGENT_EMBEDDING_API_KEY": "secret-key",
                        "GIS_AGENT_EMBEDDING_BASE_URL": "https://api.example/v1",
                        "GIS_AGENT_VECTOR_RAG_STORE": str(store_path),
                    },
                    clear=False,
                ),
                mock.patch("core.agent_runtime.vector_rag.APIEmbeddingClient.embed_texts") as embed_texts,
            ):
                response = TestClient(api_server.app).get(
                    "/api/admin/agent-runtime/rag-readiness",
                    headers={"x-admin-token": "secret"},
                )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        rendered = str(payload)
        self.assertEqual(payload["schema_version"], "agent-runtime-rag-readiness/v1")
        self.assertEqual(payload["mode"], "read_only_no_embedding")
        self.assertEqual(payload["operations"]["embedding_calls_performed"], 0)
        self.assertFalse(payload["operations"]["rebuild_available"])
        self.assertEqual(payload["eval"]["status"], "not_run_no_embedding_cost")
        self.assertGreaterEqual(payload["eval"]["case_count"], 3)
        self.assertFalse(payload["readiness"]["ready"])
        self.assertTrue(payload["provider"]["credential_configured"])
        self.assertTrue(payload["vector_store"]["configured"])
        self.assertTrue(payload["vector_store"]["exists"])
        self.assertEqual(payload["vector_store"]["document_count"], 3)
        self.assertNotIn("secret-key", rendered)
        self.assertNotIn(str(store_path), rendered)
        embed_texts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
