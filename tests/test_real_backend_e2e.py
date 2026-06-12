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
        from core.service import GISWorkspaceService

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

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
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

            with mock.patch.object(GISWorkspaceService, "_get_agent", side_effect=AssertionError("LLM should not be called")):
                check = client.post("/api/chat/ask", json={"prompt": "check this dataset"})
                self.assertEqual(check.status_code, 200, check.text)
                check_body = check.json()
                self.assertEqual(check_body["mode"], "deterministic_tool")
                session_id = check_body["current_session_id"]

                map_response = client.post(
                    "/api/chat/ask",
                    json={"prompt": "plot population density map", "session_id": session_id},
                )
                self.assertEqual(map_response.status_code, 200, map_response.text)
                map_body = map_response.json()
                self.assertEqual(map_body["mode"], "deterministic_tool")
                files = map_body["result_panel"]["files"]
                self.assertTrue(files)
                self.assertTrue(files[0].get("artifact_id"), files[0])
                self.assertTrue(files[0].get("download_url"), files[0])

                followup = client.post(
                    "/api/chat/ask",
                    json={
                        "prompt": "这个结果说明什么",
                        "session_id": session_id,
                        "frontend_context": {
                            "selected_artifact_id": files[0]["artifact_id"],
                            "selected_artifact_type": files[0]["kind"],
                            "selected_artifact_path": files[0]["path"],
                        },
                    },
                )
                self.assertEqual(followup.status_code, 200, followup.text)
                followup_body = followup.json()
                self.assertIn(followup_body["mode"], {"builtin", "deterministic_context", "deterministic_tool", "deterministic_workflow"})
                self.assertIn(files[0]["artifact_id"], followup_body["reply"])

    def test_csv_upload_converts_table_to_points_then_maps_and_explains(self) -> None:
        import api_server
        from core.service import GISWorkspaceService

        csv_bytes = (FIXTURE_DIR / "e2e_points.csv").read_bytes()

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
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

            with mock.patch.object(GISWorkspaceService, "_get_agent", side_effect=AssertionError("LLM should not be called")):
                map_response = client.post("/api/chat/ask", json={"prompt": "plot population density map"})
                self.assertEqual(map_response.status_code, 200, map_response.text)
                map_body = map_response.json()
                self.assertEqual(map_body["mode"], "deterministic_workflow")
                session_id = map_body["current_session_id"]
                files = map_body["result_panel"]["files"]
                self.assertTrue(files)
                self.assertTrue(files[0].get("artifact_id"), files[0])
                self.assertTrue(any(item.get("kind") == "derived" and str(item.get("path", "")).endswith(".geojson") for item in files))

                followup = client.post(
                    "/api/chat/ask",
                    json={
                        "prompt": "这个结果说明什么",
                        "session_id": session_id,
                        "frontend_context": {
                            "selected_artifact_id": files[0]["artifact_id"],
                            "selected_artifact_type": files[0]["kind"],
                            "selected_artifact_path": files[0]["path"],
                        },
                    },
                )
                self.assertEqual(followup.status_code, 200, followup.text)
                followup_body = followup.json()
                self.assertIn(followup_body["mode"], {"deterministic_context", "deterministic_tool", "deterministic_workflow"})
                self.assertIn(files[0]["artifact_id"], followup_body["reply"])


if __name__ == "__main__":
    unittest.main()
