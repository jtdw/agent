from __future__ import annotations

import unittest

from core.download_candidates import candidate_download_products


class DownloadCandidatesTests(unittest.TestCase):
    def test_candidate_download_products_prioritizes_query_matches_and_is_metadata_only(self) -> None:
        candidates = candidate_download_products("download Sentinel-2 DEM", limit=4)
        keys = [item["product_key"] for item in candidates]

        self.assertIn("sentinel2_msi", keys[:2])
        self.assertIn("gscloud_dem", keys[:2])
        for item in candidates:
            self.assertEqual(item["source_key"], "gscloud")
            self.assertTrue(item["confirmation_required"])
            self.assertEqual(item["source"], "download_candidate_catalog")
            self.assertNotIn("submit", item)


if __name__ == "__main__":
    unittest.main()
