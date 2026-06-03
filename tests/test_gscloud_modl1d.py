import unittest

from core.domestic_sources.gscloud_products import match_gscloud_product
from core.domestic_sources.gscloud_modl1d import parse_modl1d_cells


class GSCloudMODL1DTests(unittest.TestCase):
    def test_product_aliases_match_modl1d_land_surface_temperature(self):
        for text in [
            "下载 MODL1D 中国 1KM 地表温度每天产品",
            "获取成都 LST 每天产品",
            "地理空间数据云 1KM 地表温度数据",
        ]:
            product = match_gscloud_product(text)
            self.assertIsNotNone(product)
            self.assertEqual(product.key, "modl1d_china_1km_lst_daily")
            self.assertEqual(product.dataset_id, "334")
            self.assertEqual(product.pid, "333")

    def test_parse_modl1d_main_and_quality_rows(self):
        main = parse_modl1d_cells(
            ["1", "MODL1D.20160517.CN.LTD.V2", "2016-05-17", "104.5003", "32.5004", "有"],
            row_index=0,
        )
        quality = parse_modl1d_cells(
            ["2", "MODL1D.20160517.CN.QCD.V2", "2016-05-17", "104.5003", "32.5004", "有"],
            row_index=1,
        )

        self.assertEqual(main["scene_id"], "MODL1D.20160517.CN.LTD.V2")
        self.assertEqual(main["date"], "2016-05-17")
        self.assertEqual(main["year"], "2016")
        self.assertEqual(main["longitude"], 104.5003)
        self.assertEqual(main["latitude"], 32.5004)
        self.assertEqual(main["data_available"], "有")
        self.assertEqual(main["product_tag"], "LTD")
        self.assertEqual(main["product_family"], "main")
        self.assertEqual(quality["product_tag"], "QCD")
        self.assertEqual(quality["product_family"], "quality")


if __name__ == "__main__":
    unittest.main()
