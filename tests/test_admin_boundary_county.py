from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.admin_boundary import _cache_dir, extract_local_admin_boundary
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

    def test_builtin_admin_archive_cache_is_shared_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            base = Path(tmp) / "workspace"
            archive = base / "local_library" / "data" / "administrative" / "china_admin_county_2023.zip"
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(b"zip")
            first = DataManager(base / "users" / "u1")
            second = DataManager(base / "users" / "u1")
            first.set_runtime_scope("u1", "s1")
            second.set_runtime_scope("u1", "s2")

            self.assertEqual(_cache_dir(first, archive), _cache_dir(second, archive))
            self.assertNotIn("sessions", _cache_dir(first, archive).parts)


if __name__ == "__main__":
    unittest.main()
