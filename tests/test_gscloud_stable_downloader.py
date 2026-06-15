from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.domestic_sources.gscloud_stable_downloader import (
    existing_gscloud_tile_downloads,
    per_tile_download_timeout_ms,
)


class GSCloudStableDownloaderTests(unittest.TestCase):
    def test_existing_valid_tiles_are_reused_for_resume(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            existing = root / "ASTGTM_N30E102.img.zip"
            existing.write_bytes(b"valid-enough-for-resume")
            (root / "unrelated.zip").write_bytes(b"other")

            found = existing_gscloud_tile_downloads(root, ["ASTGTM_N30E102", "ASTGTM_N30E103"])

            self.assertEqual(found, {"ASTGTM_N30E102": existing})

    def test_single_tile_wait_is_bounded(self) -> None:
        self.assertEqual(per_tile_download_timeout_ms(1800), 120_000)
        self.assertEqual(per_tile_download_timeout_ms(30), 30_000)


if __name__ == "__main__":
    unittest.main()
