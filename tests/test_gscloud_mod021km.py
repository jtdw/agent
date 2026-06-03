import unittest

from core.domestic_sources.gscloud_mod021km import parse_mod021km_cells
from core.domestic_sources.gscloud_products import MOD021KM_1KM_SURFACE_REFLECTANCE, match_gscloud_product


class GSCloudMOD021KMTests(unittest.TestCase):
    def test_product_aliases_match_mod021km_surface_reflectance(self):
        for text in [
            "下载 MOD021KM 1KM 地表反射率",
            "获取成都 MODISL1B 标准产品 1KM 反射率",
            "地理空间数据云 MOD021KM 数据",
        ]:
            product = match_gscloud_product(text)
            self.assertIsNotNone(product)
            self.assertEqual(product.key, "mod021km_1km_surface_reflectance")
            self.assertEqual(product.dataset_id, "293")
            self.assertEqual(product.pid, "291")
            self.assertEqual(product.resource_type, "mod021km_surface_reflectance")

    def test_parse_mod021km_row(self):
        row = parse_mod021km_cells(
            ["1", "MOD021KM.A2010228.1550.005", "2010-08-16", "95", "32", "\u6709"],
            row_index=0,
        )

        self.assertIsNotNone(row)
        self.assertEqual(row["scene_id"], "MOD021KM.A2010228.1550.005")
        self.assertEqual(row["date"], "2010-08-16")
        self.assertEqual(row["year"], "2010")
        self.assertEqual(row["longitude"], 95.0)
        self.assertEqual(row["latitude"], 32.0)
        self.assertEqual(row["data_available"], "\u6709")
        self.assertEqual(row["product_tag"], "MOD021KM")


if __name__ == "__main__":
    unittest.main()
