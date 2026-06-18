from __future__ import annotations

import unittest

from core.semantic_parser import parse_user_semantics


class SemanticParserTests(unittest.TestCase):
    def test_dem_download_strips_processing_verb_from_region(self) -> None:
        parsed = parse_user_semantics("\u5e2e\u6211\u8fdb\u884c\u8d44\u9633\u5e02\u7684 DEM \u4e0b\u8f7d")

        self.assertEqual(parsed["intent"], "data_download")
        self.assertEqual(parsed["action"], "download")
        self.assertEqual(parsed["resource_type"], "DEM")
        self.assertEqual(parsed["region_raw"], "\u8d44\u9633\u5e02")
        self.assertEqual(parsed["region_standard"], "\u56db\u5ddd\u7701\u8d44\u9633\u5e02")
        self.assertEqual(parsed["admin_level"], "prefecture_city")
        self.assertFalse(parsed["needs_clarification"])

    def test_dem_download_normalizes_short_prefecture_name(self) -> None:
        parsed = parse_user_semantics("\u4e0b\u8f7d\u8d44\u9633 DEM")

        self.assertEqual(parsed["region_raw"], "\u8d44\u9633")
        self.assertEqual(parsed["region"], "\u8d44\u9633\u5e02")
        self.assertEqual(parsed["region_standard"], "\u56db\u5ddd\u7701\u8d44\u9633\u5e02")

    def test_dem_download_normalizes_province_prefecture_phrase(self) -> None:
        parsed = parse_user_semantics("\u83b7\u53d6\u56db\u5ddd\u8d44\u9633 90m DEM")

        self.assertEqual(parsed["resolution"], "90m")
        self.assertEqual(parsed["region"], "\u8d44\u9633\u5e02")
        self.assertEqual(parsed["region_standard"], "\u56db\u5ddd\u7701\u8d44\u9633\u5e02")

    def test_unknown_region_requests_clarification_without_inventing_place(self) -> None:
        parsed = parse_user_semantics("\u4e0b\u8f7d\u4e0d\u5b58\u5728\u5730\u533a DEM")

        self.assertEqual(parsed["intent"], "data_download")
        self.assertTrue(parsed["needs_clarification"])
        self.assertIn("region", parsed["missing_slots"])
        self.assertNotEqual(parsed["region"], "\u4e0d\u5b58\u5728\u5730\u533a")

    def test_boundary_download_is_data_download(self) -> None:
        parsed = parse_user_semantics("\u8bf7\u4e0b\u8f7d\u6210\u90fd\u5e02\u884c\u653f\u533a\u8fb9\u754c")

        self.assertEqual(parsed["intent"], "data_download")
        self.assertEqual(parsed["resource_type"], "admin_boundary")
        self.assertEqual(parsed["region"], "\u6210\u90fd\u5e02")


if __name__ == "__main__":
    unittest.main()
