import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.domestic_sources.gscloud_reliability import (
    classify_gscloud_failure,
    find_existing_scene_download,
    inspect_storage_state,
    resolve_download_region,
    validate_download_artifact,
)


class GSCloudReliabilityTests(unittest.TestCase):
    def test_inspect_storage_state_rejects_missing_file(self):
        result = inspect_storage_state(Path("missing-storage-state.json"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "missing_storage_state")
        self.assertEqual(result["action"], "relogin")
        self.assertNotIn("path", result)

    def test_inspect_storage_state_accepts_gscloud_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                json.dumps({"cookies": [{"name": "sid", "domain": ".gscloud.cn", "expires": 4102444800}]}),
                encoding="utf-8",
            )

            result = inspect_storage_state(path)

            self.assertTrue(result["ok"])
            self.assertEqual(result["reason"], "storage_state_ready")
            self.assertNotIn("path", result)

    def test_inspect_storage_state_rejects_expired_gscloud_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                json.dumps({"cookies": [{"name": "sid", "domain": ".gscloud.cn", "expires": 1}]}),
                encoding="utf-8",
            )

            result = inspect_storage_state(path)

            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "expired_gscloud_cookies")

    def test_classifies_common_failures(self):
        self.assertEqual(classify_gscloud_failure("Timeout 30000ms exceeded")["code"], "download_timeout")
        self.assertEqual(classify_gscloud_failure("Internal server error")["code"], "source_server_error")
        self.assertEqual(classify_gscloud_failure("未找到可用地理空间数据云登录态")["code"], "login_required")
        self.assertEqual(classify_gscloud_failure("未找到满足条件的 Landsat 8 可下载记录")["code"], "no_matching_scene")

    def test_validate_download_artifact_rejects_html_error_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "download.zip"
            path.write_text("<html>Internal server error</html>", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                validate_download_artifact(path)

    def test_validate_download_artifact_accepts_valid_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("scene.txt", "ok")

            result = validate_download_artifact(path)

            self.assertTrue(result["ok"])
            self.assertEqual(result["suffix"], ".zip")

    def test_find_existing_scene_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            existing = target / "LC81280302021365LGN00.zip"
            with zipfile.ZipFile(existing, "w") as zf:
                zf.writestr("scene.txt", "ok")

            found = find_existing_scene_download(target, "LC81280302021365LGN00")

            self.assertEqual(found, existing)

    def test_resolve_download_region_marks_ambiguous_region(self):
        result = resolve_download_region("下载植被数据", "")

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "missing_region")
        self.assertIn("区域", result["message"])

    def test_resolve_download_region_adds_known_bounds(self):
        result = resolve_download_region("下载成都 Landsat", "")

        self.assertTrue(result["ok"])
        self.assertEqual(result["region"], "成都")
        self.assertEqual(result["boundary_source"], "builtin_bbox")
        self.assertEqual(len(result["bounds"]), 4)


if __name__ == "__main__":
    unittest.main()
