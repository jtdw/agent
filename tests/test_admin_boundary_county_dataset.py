from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.admin_boundary import ADMIN_ZIP_NAMES, extract_local_admin_boundary
from core.config import Settings
from core.data_manager import DataManager


class CountyAdminBoundaryTests(unittest.TestCase):
    def test_only_current_county_archive_is_supported(self) -> None:
        self.assertEqual(ADMIN_ZIP_NAMES, {"china_admin_county_2023.zip"})

    def test_county_city_and_province_names_resolve_from_local_county_archive(self) -> None:
        archive = Path(__file__).resolve().parents[1] / "local_library" / "data" / "administrative" / "china_admin_county_2023.zip"
        if not archive.exists():
            self.skipTest("local county boundary archive is not installed")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            settings = Settings(api_key="", workdir=Path(tmp) / "workspace")
            settings.ensure_dirs()
            manager = DataManager(settings.workdir)

            county, _, _ = extract_local_admin_boundary(manager, "武侯区")
            city, _, _ = extract_local_admin_boundary(manager, "成都市")
            province, _, _ = extract_local_admin_boundary(manager, "四川省")

            self.assertIsNotNone(county)
            self.assertEqual(len(county), 1)
            self.assertEqual(county.iloc[0]["县级"], "武侯区")
            self.assertIsNotNone(city)
            self.assertGreater(len(city), 10)
            self.assertTrue((city["地级"] == "成都市").all())
            self.assertIsNotNone(province)
            self.assertGreater(len(province), 100)
            self.assertTrue((province["省级"] == "四川省").all())


if __name__ == "__main__":
    unittest.main()
