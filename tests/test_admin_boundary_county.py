from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.admin_boundary import extract_local_admin_boundary
from core.data_manager import DataManager


class AdminBoundaryCountyTests(unittest.TestCase):
    def test_extracts_single_county_boundary_from_builtin_archive(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            gdf, dataset_name, source = extract_local_admin_boundary(manager, "阿坝县")

            self.assertIsNotNone(gdf)
            self.assertEqual(source, "local_library_admin_boundary")
            self.assertTrue(dataset_name.endswith("_boundary"))
            self.assertEqual(len(gdf), 1)
            self.assertEqual(str(gdf.iloc[0]["县级"]), "阿坝县")
            self.assertIn(dataset_name, manager.list_dataset_names())

    def test_suffix_alias_matches_banner_names(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            gdf, _, _ = extract_local_admin_boundary(manager, "阿巴嘎")

            self.assertIsNotNone(gdf)
            self.assertEqual(len(gdf), 1)
            self.assertEqual(str(gdf.iloc[0]["县级"]), "阿巴嘎旗")

    def test_prefecture_alias_does_not_pull_same_named_county_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            gdf, _, _ = extract_local_admin_boundary(manager, "\u8d44\u9633")

            self.assertIsNotNone(gdf)
            self.assertEqual(len(gdf), 3)
            self.assertEqual(set(gdf["地级"].astype(str)), {"\u8d44\u9633\u5e02"})

    def test_region_query_strips_processing_verb_prefix(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            gdf, _, _ = extract_local_admin_boundary(manager, "\u8fdb\u884c\u8d44\u9633\u5e02")

            self.assertIsNotNone(gdf)
            self.assertEqual(len(gdf), 3)
            self.assertEqual(set(gdf["\u5730\u7ea7"].astype(str)), {"\u8d44\u9633\u5e02"})


if __name__ == "__main__":
    unittest.main()
