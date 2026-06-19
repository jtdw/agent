from __future__ import annotations

import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from starlette.exceptions import StarletteDeprecationWarning

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
    from starlette.testclient import TestClient


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class RealBackendChatE2ETests(unittest.TestCase):
    def test_upload_check_map_and_followup_use_real_backend_chat_chain(self) -> None:
        import api_server

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"county": "A", "pop_density": 10.0},
                    "geometry": {"type": "Point", "coordinates": [100.0, 30.0]},
                },
                {
                    "type": "Feature",
                    "properties": {"county": "B", "pop_density": 25.0},
                    "geometry": {"type": "Point", "coordinates": [101.0, 31.0]},
                },
            ],
        }

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.dict(
            "os.environ",
            {"GIS_AGENT_ALLOW_ANONYMOUS": "1", "LLM_PROVIDER": "fake", "GIS_AGENT_E2E_LLM_FIXTURES": "1"},
            clear=False,
        ):
            root = Path(tmp) / "workspace"
            root.mkdir(parents=True, exist_ok=True)
            api_server._workspace_services.clear()
            api_server.base_settings.workdir = root
            api_server.base_settings.ensure_dirs()
            client = TestClient(api_server.app)

            upload = client.post(
                "/api/files/upload",
                files={"files": ("counties.geojson", json.dumps(geojson).encode("utf-8"), "application/geo+json")},
            )
            self.assertEqual(upload.status_code, 200, upload.text)
            self.assertTrue(upload.json()["dashboard"]["datasets"])

            check = client.post("/api/chat/ask", json={"prompt": "check this dataset"})
            self.assertEqual(check.status_code, 200, check.text)
            check_body = check.json()
            self.assertEqual(check_body["mode"], "coordinated_workflow")
            self.assertEqual(check_body["presentation_result"]["status"], "succeeded")
            self.assertEqual(check_body["execution_summary"]["status"], "succeeded")
            session_id = check_body["current_session_id"]

            map_response = client.post(
                "/api/chat/ask",
                json={"prompt": "plot population density map", "session_id": session_id},
            )
            self.assertEqual(map_response.status_code, 200, map_response.text)
            map_body = map_response.json()
            self.assertEqual(map_body["mode"], "coordinated_workflow")
            self.assertEqual(map_body["presentation_result"]["status"], "succeeded")
            refs = map_body["presentation_result"]["artifact_refs"]
            self.assertTrue(refs)
            artifact_id = refs[0]["artifact_id"]
            artifact_meta = client.get(f"/api/artifacts/{artifact_id}", params={"session_id": session_id})
            self.assertEqual(artifact_meta.status_code, 200, artifact_meta.text)
            self.assertTrue(artifact_meta.json().get("download_url"))

            followup = client.post(
                "/api/chat/ask",
                json={
                    "prompt": "这个结果说明什么",
                    "session_id": session_id,
                    "frontend_context": {
                        "selected_artifact_id": artifact_id,
                        "selected_artifact_type": refs[0].get("type", ""),
                    },
                },
            )
            self.assertEqual(followup.status_code, 200, followup.text)
            followup_body = followup.json()
            self.assertIn(followup_body["mode"], {"coordinated_workflow", "clarification", "builtin", "deterministic_context"})

    def test_csv_upload_converts_table_to_points_then_maps_and_explains(self) -> None:
        import api_server

        csv_bytes = (FIXTURE_DIR / "e2e_points.csv").read_bytes()

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.dict(
            "os.environ",
            {"GIS_AGENT_ALLOW_ANONYMOUS": "1", "LLM_PROVIDER": "fake", "GIS_AGENT_E2E_LLM_FIXTURES": "1"},
            clear=False,
        ):
            root = Path(tmp) / "workspace"
            root.mkdir(parents=True, exist_ok=True)
            api_server._workspace_services.clear()
            api_server.base_settings.workdir = root
            api_server.base_settings.ensure_dirs()
            client = TestClient(api_server.app)

            upload = client.post(
                "/api/files/upload",
                files={"files": ("e2e_points.csv", csv_bytes, "text/csv")},
            )
            self.assertEqual(upload.status_code, 200, upload.text)
            self.assertEqual(upload.json()["dashboard"]["datasets"][0]["type"], "table")

            map_response = client.post("/api/chat/ask", json={"prompt": "plot population density map"})
            self.assertEqual(map_response.status_code, 200, map_response.text)
            map_body = map_response.json()
            self.assertEqual(map_body["mode"], "coordinated_workflow")
            self.assertEqual(map_body["presentation_result"]["status"], "succeeded")
            session_id = map_body["current_session_id"]
            refs = map_body["presentation_result"]["artifact_refs"]
            self.assertTrue(refs)
            self.assertTrue(any(str(step.get("tool_name")) == "table_to_points" for step in map_body["presentation_result"]["executed_steps"]))
            artifact_id = refs[0]["artifact_id"]
            artifact_meta = client.get(f"/api/artifacts/{artifact_id}", params={"session_id": session_id})
            self.assertEqual(artifact_meta.status_code, 200, artifact_meta.text)
            self.assertTrue(artifact_meta.json().get("download_url"))

            followup = client.post(
                "/api/chat/ask",
                json={
                    "prompt": "这个结果说明什么",
                    "session_id": session_id,
                    "frontend_context": {
                        "selected_artifact_id": artifact_id,
                        "selected_artifact_type": refs[0].get("type", ""),
                    },
                },
            )
            self.assertEqual(followup.status_code, 200, followup.text)
            followup_body = followup.json()
            self.assertIn(followup_body["mode"], {"coordinated_workflow", "clarification", "builtin", "deterministic_context"})

    def test_llm_unavailable_returns_clarification_and_zero_tool_execution(self) -> None:
        import api_server
        from core.service import execute_validated_tool_plan, execute_workflow_plan

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.dict(
            "os.environ",
            {"GIS_AGENT_ALLOW_ANONYMOUS": "1", "LLM_PROVIDER": "fake", "GIS_AGENT_E2E_LLM_FIXTURES": "0"},
            clear=False,
        ):
            root = Path(tmp) / "workspace"
            root.mkdir(parents=True, exist_ok=True)
            api_server._workspace_services.clear()
            api_server.base_settings.workdir = root
            api_server.base_settings.ensure_dirs()
            client = TestClient(api_server.app)

            with mock.patch("core.service.execute_workflow_plan", wraps=execute_workflow_plan) as workflow_mock:
                with mock.patch("core.service.execute_validated_tool_plan", wraps=execute_validated_tool_plan) as tool_mock:
                    response = client.post("/api/chat/ask", json={"prompt": "plot population density map"})

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["mode"], "clarification")
            self.assertFalse(workflow_mock.called)
            self.assertFalse(tool_mock.called)


if __name__ == "__main__":
    unittest.main()
