from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.domestic_sources.gscloud_stable_downloader import (
    existing_gscloud_tile_downloads,
    extract_gscloud_tile_id_from_name,
    normalize_gscloud_tile_id,
    validate_gscloud_tile_downloads_for_scheme,
    _tile_search_terms,
)


class GSCloudTileIdentifierCaseTests(unittest.TestCase):
    def test_srtm_utm_identifiers_are_lowercase_for_case_sensitive_site_search(self) -> None:
        self.assertEqual(
            normalize_gscloud_tile_id("UTM_SRTM_57_06", tile_scheme="srtm_utm_5deg"),
            "utm_srtm_57_06",
        )
        self.assertEqual(
            _tile_search_terms("UTM_SRTM_57_06", tile_scheme="srtm_utm_5deg"),
            ["utm_srtm_57_06", "57_06"],
        )

    def test_astgtm_identifiers_remain_uppercase_for_existing_aster_downloads(self) -> None:
        self.assertEqual(
            normalize_gscloud_tile_id("astgtm_n30e103", tile_scheme="astgtm_1deg"),
            "ASTGTM_N30E103",
        )
        self.assertEqual(
            _tile_search_terms("astgtm_n30e103", tile_scheme="astgtm_1deg"),
            ["ASTGTM_N30E103", "N30E103"],
        )

    def test_srtm_existing_download_and_validation_are_case_insensitive_but_canonicalize_lowercase(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            target = Path(tmp)
            downloaded = target / "UTM_SRTM_57_06.img.zip"
            downloaded.write_bytes(b"zip")

            self.assertEqual(
                extract_gscloud_tile_id_from_name(downloaded.name, tile_scheme="srtm_utm_5deg"),
                "utm_srtm_57_06",
            )
            self.assertEqual(
                existing_gscloud_tile_downloads(target, ["UTM_SRTM_57_06"], tile_scheme="srtm_utm_5deg"),
                {"utm_srtm_57_06": downloaded},
            )

            validation = validate_gscloud_tile_downloads_for_scheme(
                [downloaded],
                ["UTM_SRTM_57_06"],
                tile_scheme="srtm_utm_5deg",
            )

            self.assertTrue(validation["valid"])
            self.assertEqual(validation["expected_tile_ids"], ["utm_srtm_57_06"])
            self.assertEqual(validation["downloaded_tile_ids"], ["utm_srtm_57_06"])


if __name__ == "__main__":
    unittest.main()
