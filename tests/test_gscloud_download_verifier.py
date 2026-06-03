import tempfile
import unittest
import zipfile
from pathlib import Path

from core.domestic_sources.gscloud_download_verifier import build_verification_result, validate_downloaded_file


class GSCloudDownloadVerifierTests(unittest.TestCase):
    def test_builds_preflight_result_without_download_file(self):
        result = build_verification_result(
            product_key="landsat8_oli_tirs",
            execute_download=False,
            scene={"scene_id": "LC81280302021365LGN00", "page_no": 1},
            pages_scanned=1,
            candidate_count=10,
            download_selector_hits=[".download-img:1"],
        )

        self.assertEqual(result["state"], "READY_TO_DOWNLOAD")
        self.assertFalse(result["execute_download"])
        self.assertEqual(result["downloaded_file"], None)
        self.assertEqual(result["download_selector_hits"], [".download-img:1"])

    def test_validate_downloaded_file_rejects_missing_file(self):
        with self.assertRaises(RuntimeError):
            validate_downloaded_file(Path("missing-download.zip"))

    def test_validate_downloaded_file_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.zip"
            path.write_bytes(b"")

            with self.assertRaises(RuntimeError):
                validate_downloaded_file(path)

    def test_validate_downloaded_file_accepts_non_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("scene.txt", "ok")

            result = validate_downloaded_file(path)

            self.assertEqual(result["path"], str(path))
            self.assertGreater(result["size_bytes"], 3)
            self.assertEqual(result["suffix"], ".zip")


if __name__ == "__main__":
    unittest.main()
