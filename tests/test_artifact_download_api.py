from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from core.config import Settings
from core.service import GISWorkspaceService


class ArtifactDownloadApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.service = GISWorkspaceService(Settings(api_key="", workdir=self.root / "workspace"))
        api_server._workspace_services.clear()
        api_server._workspace_services["anonymous"] = self.service
        self.client = TestClient(api_server.app)

    def tearDown(self) -> None:
        api_server._workspace_services.clear()
        self.tmp.cleanup()

    def test_artifact_metadata_and_download_use_artifact_id(self) -> None:
        path = self.service.manager.derived_dir / "result.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_csv_result",
            path=str(path),
            type="csv",
            title="result.csv",
            task_id="task_1",
            meta={"tool_name": "export_dataset", "workflow_id": "workflow_1", "message_id": 9},
        )

        meta_response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}")

        self.assertEqual(meta_response.status_code, 200)
        payload = meta_response.json()
        self.assertEqual(payload["artifact_id"], "artifact_csv_result")
        self.assertEqual(payload["filename"], "result.csv")
        self.assertEqual(payload["mime_type"], "text/csv")
        self.assertEqual(payload["source"]["tool_name"], "export_dataset")
        self.assertNotIn(str(self.service.manager.workdir), str(payload))

        download = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content.replace(b"\r\n", b"\n"), b"a,b\n1,2\n")
        self.assertIn("attachment", download.headers.get("content-disposition", ""))
        self.assertIn("result.csv", download.headers.get("content-disposition", ""))

    def test_artifact_download_blocks_sensitive_files(self) -> None:
        secret = self.service.manager.workdir / ".env"
        secret.write_text("TOKEN=secret\n", encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_secret",
            path=str(secret),
            type="txt",
            title=".env",
        )

        response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["error_code"], "ARTIFACT_FORBIDDEN")

    def test_artifact_download_blocks_configuration_files(self) -> None:
        config = self.service.manager.derived_dir / "runtime.yaml"
        config.write_text("api_key: secret\n", encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_config",
            path=str(config),
            type="yaml",
            title="runtime.yaml",
        )

        response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["error_code"], "ARTIFACT_FORBIDDEN")

    def test_legacy_path_download_is_gone_for_workspace_database(self) -> None:
        response = self.client.get("/api/files/artifact", params={"path": "workspace.db"})

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"]["error_code"], "LEGACY_ARTIFACT_DOWNLOAD_DISABLED")
        self.assertNotEqual(response.content, self.service.manager.database.db_path.read_bytes())

    def test_legacy_path_download_is_gone_for_path_traversal(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("secret", encoding="utf-8")

        response = self.client.get("/api/files/artifact", params={"path": "../../outside.txt"})

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"]["error_code"], "LEGACY_ARTIFACT_DOWNLOAD_DISABLED")
        self.assertNotIn("secret", response.text)

    def test_artifact_download_blocks_path_escape(self) -> None:
        outside = self.root / "outside.csv"
        outside.write_text("no", encoding="utf-8")
        self.service.manager.database.upsert_artifact(
            {
                "artifact_id": "artifact_outside",
                "path": str(outside),
                "type": "csv",
                "title": "outside.csv",
            }
        )

        response = self.client.get("/api/artifacts/artifact_outside")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["error_code"], "ARTIFACT_FORBIDDEN")

    def test_artifact_delete_removes_registered_result_file(self) -> None:
        path = self.service.manager.derived_dir / "delete_me.geojson"
        path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_delete_me",
            path=str(path),
            type="geojson",
            title="delete_me.geojson",
        )

        response = self.client.delete(f"/api/artifacts/{artifact['artifact_id']}", params={"delete_file": "true"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["artifact_id"], "artifact_delete_me")
        self.assertTrue(payload["file_deleted"])
        self.assertFalse(path.exists())
        self.assertIsNone(self.service.manager.get_artifact("artifact_delete_me"))

    def test_artifact_delete_removes_dataset_catalog_entry_for_same_path(self) -> None:
        path = self.service.manager.derived_dir / "delete_dataset.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        dataset_name = self.service.manager.load_path(str(path), name="delete_dataset")
        dataset_path = self.service.manager.get(dataset_name).path
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_delete_dataset",
            path=str(dataset_path),
            type="csv",
            title="delete_dataset.csv",
        )

        response = self.client.delete(f"/api/artifacts/{artifact['artifact_id']}", params={"delete_file": "true"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(dataset_path.exists())
        self.assertNotIn(dataset_name, self.service.manager.datasets)
        self.assertNotIn(dataset_name, {item["dataset_name"] for item in self.service.manager.database.list_catalog()})

    def test_artifact_delete_removes_scanned_result_file(self) -> None:
        path = self.service.manager.derived_dir / "scanned_result.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        artifact = next(item for item in self.service.manager.list_artifacts() if item["path"] == str(path))

        response = self.client.delete(f"/api/artifacts/{artifact['artifact_id']}", params={"delete_file": "true"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["artifact_id"], artifact["artifact_id"])
        self.assertTrue(payload["file_deleted"])
        self.assertFalse(path.exists())
        self.assertNotIn(artifact["artifact_id"], {item["artifact_id"] for item in self.service.manager.list_artifacts()})

    def test_artifact_batch_delete_removes_multiple_result_files(self) -> None:
        paths = []
        for index in range(2):
            path = self.service.manager.derived_dir / f"batch_delete_{index}.csv"
            path.write_text("a,b\n1,2\n", encoding="utf-8")
            paths.append(path)
        artifact_ids = [
            item["artifact_id"]
            for item in self.service.manager.list_artifacts()
            if item["path"] in {str(path) for path in paths}
        ]

        response = self.client.post(
            "/api/artifacts/delete-batch",
            json={"artifact_ids": artifact_ids, "delete_file": True},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["deleted_count"], 2)
        self.assertEqual({item["artifact_id"] for item in payload["results"]}, set(artifact_ids))
        self.assertTrue(all(item["ok"] for item in payload["results"]))
        self.assertTrue(all(not path.exists() for path in paths))

    def test_deleted_model_artifact_is_removed_from_dashboard_results(self) -> None:
        path = self.service.manager.derived_dir / "model_metrics.csv"
        path.write_text("scope,R,RMSE,NSE\noverall,0.8,0.12,0.7\n", encoding="utf-8")
        self.service.manager.register_model_result(
            model_result_id="model_result_delete_artifact",
            model_name="XGBoost",
            output_prefix="model",
            metrics_dataset="model_metrics",
            metrics_path=str(path),
            artifacts=[{"artifact_id": "artifact_model_metrics", "path": str(path), "type": "metrics"}],
            metrics={"R": 0.8, "RMSE": 0.12},
        )

        response = self.client.delete("/api/artifacts/artifact_model_metrics", params={"delete_file": "true"})

        self.assertEqual(response.status_code, 200)
        dashboard = self.client.get("/api/workspace/dashboard").json()
        result = next(item for item in dashboard["model_results"] if item["model_result_id"] == "model_result_delete_artifact")
        self.assertEqual(result.get("artifacts"), [])
        panel_artifact_ids = {
            file.get("artifact_id")
            for result in dashboard["model_results"]
            for file in result.get("artifacts", [])
            if isinstance(file, dict)
        }
        self.assertNotIn("artifact_model_metrics", panel_artifact_ids)

    def test_artifact_delete_blocks_sensitive_registered_path(self) -> None:
        secret = self.service.manager.workdir / "workspace.db"
        self.service.manager.database.upsert_artifact(
            {
                "artifact_id": "artifact_delete_db",
                "path": str(secret),
                "type": "db",
                "title": "workspace.db",
            }
        )

        response = self.client.delete("/api/artifacts/artifact_delete_db", params={"delete_file": "true"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["error_code"], "ARTIFACT_FORBIDDEN")
        self.assertTrue(secret.exists())

    def test_shapefile_artifact_downloads_as_zip(self) -> None:
        shp_dir = self.service.manager.derived_dir / "shape"
        shp_dir.mkdir(parents=True, exist_ok=True)
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            (shp_dir / f"demo{suffix}").write_text(suffix, encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_shape",
            path=str(shp_dir / "demo.shp"),
            type="dataset",
            title="demo.shp",
        )

        response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(response.status_code, 200)
        self.assertIn("demo.zip", response.headers.get("content-disposition", ""))
        archive_path = self.root / "downloaded.zip"
        archive_path.write_bytes(response.content)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("demo.shp", archive.namelist())
            self.assertIn("demo.dbf", archive.namelist())


if __name__ == "__main__":
    unittest.main()
