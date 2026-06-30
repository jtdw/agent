from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from core.commercial.service import CommercialService


class CheckpointArtifactApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_workdir = api_server.base_settings.workdir
        self.original_commercial = api_server.commercial_service
        self.original_services = dict(api_server._workspace_services)
        root = Path(self.tmp.name) / "workspace"
        api_server._workspace_services.clear()
        api_server.base_settings.workdir = root
        api_server.base_settings.ensure_dirs()
        api_server.commercial_service = CommercialService(root)
        self.client = TestClient(api_server.app)
        self.user_id = self.client.post("/api/auth/register", json={"email": "artifact@example.com", "password": "password1"}).json()["user"]["user_id"]
        self.service = api_server.workspace_for(self.user_id)
        self.service.set_request_context(self.user_id, self.service.current_session_id)

    def tearDown(self) -> None:
        api_server._workspace_services.clear()
        api_server._workspace_services.update(self.original_services)
        api_server.base_settings.workdir = self.original_workdir
        api_server.commercial_service = self.original_commercial
        self.tmp.cleanup()

    def test_artifact_metadata_and_download_use_artifact_id(self) -> None:
        path = self.service.manager.derived_dir / "result.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_csv_result",
            path=str(path),
            type="csv",
            title="result.csv",
            meta={"tool_name": "export_dataset", "workflow_id": "workflow_1", "message_id": 9},
        )

        meta_response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}")
        download = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(meta_response.status_code, 200)
        payload = meta_response.json()
        self.assertEqual(payload["artifact_id"], "artifact_csv_result")
        self.assertEqual(payload["filename"], "result.csv")
        self.assertEqual(payload["source"]["tool_name"], "export_dataset")
        self.assertNotIn(str(self.service.manager.workdir), str(payload))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content.replace(b"\r\n", b"\n"), b"a,b\n1,2\n")

    def test_artifact_download_blocks_sensitive_files(self) -> None:
        secret = self.service.manager.workdir / "workspace.db"
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_db",
            path=str(secret),
            type="db",
            title="workspace.db",
        )

        response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(response.status_code, 403)

    def test_artifact_download_reports_cleaned_or_empty_file_in_chinese(self) -> None:
        empty = self.service.manager.derived_dir / "empty.csv"
        empty.write_text("", encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_empty",
            path=str(empty),
            type="csv",
            title="empty.csv",
        )

        response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(response.status_code, 404)
        self.assertIn("文件已清理、无访问权限或下载链接已失效", str(response.json()))

    def test_delete_artifact_removes_registered_file(self) -> None:
        path = self.service.manager.derived_dir / "delete_me.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        self.service.manager.register_artifact(
            artifact_id="artifact_delete_me",
            path=str(path),
            type="csv",
            title="delete_me.csv",
        )

        response = self.client.delete("/api/artifacts/artifact_delete_me?delete_file=true")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["file_deleted"])
        self.assertNotIn("deleted_files", payload)
        self.assertNotIn(str(self.service.manager.workdir), str(payload))
        self.assertFalse(path.exists())

    def test_workspace_dashboard_does_not_expose_workdir(self) -> None:
        response = self.client.get(f"/api/workspace/dashboard?user_id={self.user_id}&session_id={self.service.current_session_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("workdir", payload)
        self.assertNotIn("db_path", payload.get("database", {}))
        self.assertNotIn("root", payload.get("local_library", {}))
        self.assertNotIn("data_dir", payload.get("local_library", {}))
        self.assertNotIn("manifest_path", payload.get("local_library", {}))
        self.assertNotIn(str(self.service.manager.workdir), str(payload))

    def test_workspace_dashboard_artifacts_use_public_projection(self) -> None:
        path = self.service.manager.derived_dir / "dashboard_result.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        self.service.manager.register_artifact(
            artifact_id="artifact_dashboard_result",
            path=str(path),
            type="csv",
            title="dashboard_result.csv",
            meta={"owner_user_id": self.user_id, "session_id": self.service.current_session_id},
        )

        response = self.client.get(f"/api/workspace/dashboard?user_id={self.user_id}&session_id={self.service.current_session_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        artifact = next(item for item in payload["artifacts"] if item["artifact_id"] == "artifact_dashboard_result")
        rendered = json.dumps(artifact, ensure_ascii=False)
        self.assertEqual(artifact["filename"], "dashboard_result.csv")
        self.assertIn("/api/artifacts/artifact_dashboard_result/download", artifact["download_url"])
        for key in ("path", "absolute_path", "relative_path", "display_path", "owner_user_id", "session_id"):
            self.assertNotIn(key, artifact)
        self.assertNotIn("owner_user_id", artifact.get("meta", {}))
        self.assertNotIn("session_id", artifact.get("meta", {}))
        self.assertNotIn(str(self.service.manager.workdir), rendered)

    def test_workspace_dashboard_datasets_do_not_expose_raw_paths_or_owner_metadata(self) -> None:
        source = self.service.manager.upload_dir / "points.csv"
        source.write_text("lon,lat\n1,2\n", encoding="utf-8")
        self.service.manager.load_path(str(source), name="points")

        response = self.client.get(f"/api/workspace/dashboard?user_id={self.user_id}&session_id={self.service.current_session_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        dataset = next(item for item in payload["datasets"] if item["name"] == "points")
        rendered = json.dumps(dataset, ensure_ascii=False)
        self.assertEqual(dataset["type"], "table")
        self.assertEqual(dataset["filename"], "points.csv")
        self.assertNotIn("path", dataset)
        self.assertNotIn("owner_user_id", dataset.get("meta", {}))
        self.assertNotIn("session_id", dataset.get("meta", {}))
        self.assertNotIn(str(self.service.manager.workdir), rendered)

    def test_workspace_dashboard_activity_and_summary_do_not_expose_internal_paths(self) -> None:
        plot_path = self.service.manager.derived_dir / "plot.png"
        plot_path.write_bytes(b"fake-png")
        self.service.manager.last_plot_path = str(plot_path)
        self.service.manager.log_operation("生成地图", f"结果保存到 {plot_path}", "plot")

        response = self.client.get(f"/api/workspace/dashboard?user_id={self.user_id}&session_id={self.service.current_session_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        rendered = json.dumps({"summary": payload.get("summary"), "activity": payload.get("activity")}, ensure_ascii=False)
        self.assertEqual(payload["summary"]["last_plot"], "plot.png")
        self.assertIn("plot.png", payload["activity"][0]["detail"])
        self.assertNotIn(str(self.service.manager.workdir), rendered)
        self.assertNotIn("workspace/users", rendered.replace("\\", "/"))

    def test_workspace_dashboard_latest_pipeline_uses_public_projection(self) -> None:
        metrics = self.service.manager.derived_dir / "pipeline_metrics.csv"
        figure = self.service.manager.derived_dir / "pipeline_figure.png"
        metrics.write_text("RMSE,R\n0.1,0.9\n", encoding="utf-8")
        figure.write_bytes(b"fake-png")
        self.service.manager.start_pipeline_run(
            "run_dashboard_private",
            "legacy_pipeline",
            "file",
            str(metrics),
            "legacy_out",
            {"raw_path": str(metrics), "download_url": "/api/files/artifact?path=derived/pipeline_metrics.csv"},
        )
        self.service.manager.add_pipeline_step(
            "run_dashboard_private",
            1,
            "legacy_step",
            "succeeded",
            input_summary=str(metrics),
            output_summary=f"output={figure}",
            detail={"output_path": str(figure), "download_url": "/api/files/artifact?path=derived/pipeline_figure.png"},
        )
        self.service.manager.finish_pipeline_run(
            "run_dashboard_private",
            "succeeded",
            {"final_path": str(figure), "reports": {"metrics_dataset": "pipeline_metrics"}},
        )

        response = self.client.get(f"/api/workspace/dashboard?user_id={self.user_id}&session_id={self.service.current_session_id}")

        self.assertEqual(response.status_code, 200)
        pipeline = response.json()["latest_pipeline"]
        rendered = json.dumps(pipeline, ensure_ascii=False)
        self.assertEqual(pipeline["source_value"], "pipeline_metrics.csv")
        self.assertEqual(pipeline["summary"]["final_path"], "pipeline_figure.png")
        self.assertEqual(pipeline["steps"][0]["input_summary"], "pipeline_metrics.csv")
        self.assertEqual(pipeline["steps"][0]["output_summary"], "output=pipeline_figure.png")
        self.assertNotIn(str(self.service.manager.workdir), rendered)
        self.assertNotIn("/api/files/artifact", rendered)
        self.assertNotIn("output_path", rendered)
        self.assertNotIn("download_url", rendered)

    def test_workspace_dashboard_model_results_use_public_projection(self) -> None:
        metrics = self.service.manager.derived_dir / "model_metrics.csv"
        figure = self.service.manager.derived_dir / "model_figure.png"
        metrics.write_text("RMSE,R\n0.1,0.9\n", encoding="utf-8")
        figure.write_bytes(b"fake-png")
        self.service.manager.register_model_result(
            model_result_id="model_dashboard_private",
            model_name="XGBoost",
            output_prefix="legacy",
            result_dataset="pred",
            metrics_dataset="model_metrics",
            metrics_path=str(metrics),
            figure_path=str(figure),
            artifacts=[{"artifact_id": "artifact_model_metrics", "path": str(metrics), "type": "csv", "title": "model_metrics.csv"}],
            diagnostics={"output_path": str(figure), "download_url": "/api/files/artifact?path=derived/model_figure.png"},
        )

        response = self.client.get(f"/api/workspace/dashboard?user_id={self.user_id}&session_id={self.service.current_session_id}")

        self.assertEqual(response.status_code, 200)
        model = next(item for item in response.json()["model_results"] if item["model_result_id"] == "model_dashboard_private")
        rendered = json.dumps(model, ensure_ascii=False)
        self.assertEqual(model["model_name"], "XGBoost")
        self.assertEqual(model["metrics_dataset"], "model_metrics")
        self.assertIn("/api/artifacts/artifact_model_metrics/download", model["artifacts"][0]["download_url"])
        for key in ("metrics_path", "figure_path", "owner_user_id", "session_id", "diagnostics"):
            self.assertNotIn(key, model)
        self.assertNotIn(str(self.service.manager.workdir), rendered)
        self.assertNotIn("/api/files/artifact", rendered)


if __name__ == "__main__":
    unittest.main()
