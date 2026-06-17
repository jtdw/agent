from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.domestic_sources.gscloud_stable_downloader import (
    _tile_search_terms,
    existing_gscloud_tile_downloads,
    extract_gscloud_tile_id_from_name,
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

    def test_existing_srtm_utm_tiles_are_reused_for_resume(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            existing = root / "utm_srtm_57_06.img.zip"
            existing.write_bytes(b"valid-enough-for-resume")
            (root / "ASTGTM_N30E102.img.zip").write_bytes(b"other")

            found = existing_gscloud_tile_downloads(root, ["utm_srtm_57_06"], tile_scheme="srtm_utm_5deg")

            self.assertEqual(found, {"utm_srtm_57_06": existing})
            self.assertEqual(extract_gscloud_tile_id_from_name(existing.name, tile_scheme="srtm_utm_5deg"), "utm_srtm_57_06")

    def test_single_tile_wait_is_bounded(self) -> None:
        self.assertEqual(per_tile_download_timeout_ms(1800), 120_000)
        self.assertEqual(per_tile_download_timeout_ms(30), 30_000)

    def test_tile_search_tries_full_identifier_then_coordinate_code(self) -> None:
        self.assertEqual(
            _tile_search_terms("astgtm_n30e104"),
            ["ASTGTM_N30E104", "N30E104"],
        )

    def test_srtm_tile_search_keeps_site_identifier(self) -> None:
        self.assertEqual(_tile_search_terms("utm_srtm_57_06", tile_scheme="srtm_utm_5deg"), ["utm_srtm_57_06", "57_06"])


if __name__ == "__main__":
    unittest.main()
