from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.storage_cleanup import cleanup_storage_candidates, scan_storage_cleanup_candidates
from core.workspace_db import WorkspaceDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StorageCleanupTests(unittest.TestCase):
    def test_frontend_artifact_cleanup_script_is_scoped_to_generated_outputs(self) -> None:
        script = PROJECT_ROOT / "scripts" / "cleanup_frontend_artifacts.ps1"

        text = script.read_text(encoding="utf-8")

        self.assertIn("ui_next\\test-results", text)
        self.assertIn("ui_next\\dist", text)
        self.assertNotIn("workspace", text)
        self.assertIn("Remove-Item", text)

    def test_scan_finds_safe_cache_and_unreferenced_duplicates_without_flagging_referenced_files(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "workspace"
            (root / "uploads").mkdir(parents=True)
            (root / "derived").mkdir(parents=True)
            (root / "temp" / "map_previews").mkdir(parents=True)
            (root / "local_library").mkdir(parents=True)
            (root / "capability_config").mkdir(parents=True)
            referenced = root / "uploads" / "referenced.img"
            duplicate = root / "uploads" / "duplicate.img"
            referenced.write_bytes(b"same raster bytes")
            duplicate.write_bytes(b"same raster bytes")
            (root / "temp" / "map_previews" / "layer.png").write_bytes(b"preview")
            extract_cache = root / "derived" / "download_postprocess_extracts" / "old"
            extract_cache.mkdir(parents=True)
            (extract_cache / "tile.tif").write_bytes(b"tile")
            batch_cache = root / "derived" / "chengdu_gscloud_batch_20260623_123456"
            batch_cache.mkdir()
            (batch_cache / "tile.zip").write_bytes(b"zip")
            (root / "local_library" / "keep.bin").write_bytes(b"keep")
            (root / "capability_config" / "knowledge.json").write_text("{}", encoding="utf-8")
            db = WorkspaceDatabase(root / "workspace.db")
            db.register_raster("referenced", str(referenced), meta={})

            result = scan_storage_cleanup_candidates(root)

            categories = {item["category"] for item in result["candidates"]}
            self.assertIn("preview_cache", categories)
            self.assertIn("download_postprocess_extract_cache", categories)
            self.assertIn("timestamped_gscloud_batch_cache", categories)
            self.assertIn("unreferenced_duplicate_upload", categories)
            paths = {Path(item["path"]).name for item in result["candidates"]}
            self.assertIn("duplicate.img", paths)
            self.assertNotIn("referenced.img", paths)
            self.assertNotIn("keep.bin", paths)
            self.assertNotIn("knowledge.json", paths)

    def test_cleanup_deletes_only_selected_candidates_with_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "workspace"
            (root / "uploads").mkdir(parents=True)
            (root / "temp" / "map_previews").mkdir(parents=True)
            preview = root / "temp" / "map_previews" / "layer.png"
            keep = root / "uploads" / "keep.img"
            preview.write_bytes(b"preview")
            keep.write_bytes(b"keep")

            scan = scan_storage_cleanup_candidates(root)
            preview_id = next(item["candidate_id"] for item in scan["candidates"] if item["category"] == "preview_cache")
            result = cleanup_storage_candidates(root, candidate_ids=[preview_id], confirm_text="删除历史缓存")

            self.assertTrue(result["ok"])
            self.assertFalse(preview.exists())
            self.assertTrue(keep.exists())

    def test_cleanup_rejects_without_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "workspace"
            (root / "temp" / "map_previews").mkdir(parents=True)
            (root / "temp" / "map_previews" / "layer.png").write_bytes(b"preview")
            scan = scan_storage_cleanup_candidates(root)
            candidate_id = scan["candidates"][0]["candidate_id"]

            with self.assertRaises(ValueError):
                cleanup_storage_candidates(root, candidate_ids=[candidate_id], confirm_text="wrong")


if __name__ == "__main__":
    unittest.main()


class StorageCleanupApiTests(unittest.TestCase):
    def test_admin_storage_cleanup_api_requires_token_and_deletes_selected_candidate(self) -> None:
        import api_server
        from core.commercial.service import CommercialService

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            original_workdir = api_server.base_settings.workdir
            original_commercial = api_server.commercial_service
            original_services = dict(api_server._workspace_services)
            try:
                root = Path(tmp) / "workspace"
                api_server.base_settings.workdir = root
                api_server.base_settings.ensure_dirs()
                api_server._workspace_services.clear()
                api_server.commercial_service = CommercialService(root)
                preview_dir = root / "temp" / "map_previews"
                preview_dir.mkdir(parents=True, exist_ok=True)
                preview = preview_dir / "layer.png"
                preview.write_bytes(b"preview")

                with mock.patch.dict("os.environ", {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False):
                    client = TestClient(api_server.app)
                    denied = client.get("/api/admin/storage-cleanup/scan")
                    self.assertEqual(denied.status_code, 403)
                    scan = client.get("/api/admin/storage-cleanup/scan", headers={"x-admin-token": "secret"})
                    self.assertEqual(scan.status_code, 200, scan.text)
                    scan_payload = scan.json()
                    self.assertNotIn("root", scan_payload)
                    self.assertEqual(scan_payload["candidates"][0]["label"], "layer.png")
                    self.assertNotIn("path", scan_payload["candidates"][0])
                    self.assertNotIn(str(root), str(scan_payload))
                    candidate_id = scan_payload["candidates"][0]["candidate_id"]
                    deleted = client.post(
                        "/api/admin/storage-cleanup/delete",
                        headers={"x-admin-token": "secret"},
                        json={"candidate_ids": [candidate_id], "confirm_text": "删除历史缓存"},
                    )
                    self.assertEqual(deleted.status_code, 200, deleted.text)
                    deleted_payload = deleted.json()
                    self.assertEqual(deleted_payload["deleted"][0]["label"], "layer.png")
                    self.assertNotIn("path", deleted_payload["deleted"][0])
                    self.assertNotIn(str(root), str(deleted_payload))
                    self.assertFalse(preview.exists())
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial
