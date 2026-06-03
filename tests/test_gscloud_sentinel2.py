import unittest

from core.domestic_sources.gscloud_products import SENTINEL2_MSI, match_gscloud_product
from core.domestic_sources.gscloud_sentinel2 import parse_sentinel2_cells


class GSCloudSentinel2Tests(unittest.TestCase):
    def test_product_aliases_match_sentinel2(self):
        for text in [
            "下载 Sentinel-2 数据",
            "获取成都 S2 MSI L2A 影像",
            "地理空间数据云 sentinel2 数据",
        ]:
            product = match_gscloud_product(text)
            self.assertIsNotNone(product)
            self.assertEqual(product.key, "sentinel2_msi")
            self.assertEqual(product.dataset_id, "448")
            self.assertEqual(product.pid, "446")
            self.assertEqual(product.resource_type, "sentinel2_msi")

    def test_parse_sentinel2_l2a_row(self):
        row = parse_sentinel2_cells(
            [
                "1",
                "S2C_MSIL2A_20251123T060201_N0511_R091_T43SDC_20251123T093615.SAFE",
                "2025-11-23",
                "73.9297",
                "38.6235",
                "\u6709",
            ],
            row_index=0,
        )

        self.assertIsNotNone(row)
        self.assertEqual(row["scene_id"], "S2C_MSIL2A_20251123T060201_N0511_R091_T43SDC_20251123T093615.SAFE")
        self.assertEqual(row["date"], "2025-11-23")
        self.assertEqual(row["year"], "2025")
        self.assertEqual(row["longitude"], 73.9297)
        self.assertEqual(row["latitude"], 38.6235)
        self.assertEqual(row["data_available"], "\u6709")
        self.assertEqual(row["processing_level"], "MSIL2A")
        self.assertEqual(row["tile_id"], "T43SDC")


if __name__ == "__main__":
    unittest.main()
