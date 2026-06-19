import unittest

from core.domestic_sources.gscloud_modev1f import parse_modev1f_cells
from core.domestic_sources.gscloud_products import MODEV1F_CHINA_250M_EVI_5DAY, MODEV1T_CHINA_250M_EVI_10DAY, match_gscloud_product


class GSCloudMODEV1FTests(unittest.TestCase):
    def test_product_aliases_match_modev1t_evi_10day(self):
        for text in [
            "下载 MODEV1T 中国 250M EVI 旬合成产品",
            "获取成都 EVI 旬合成数据",
            "地理空间数据云 250M EVI 数据",
        ]:
            product = match_gscloud_product(text)
            self.assertIsNotNone(product)
            self.assertEqual(product.key, "modev1t_china_250m_evi_10day")
            self.assertEqual(product.dataset_id, "353")
            self.assertEqual(product.pid, "333")
            self.assertEqual(product.resource_type, "modev1t_evi_10day")

    def test_legacy_modev1f_constant_points_to_modev1t_product(self):
        self.assertIs(MODEV1F_CHINA_250M_EVI_5DAY, MODEV1T_CHINA_250M_EVI_10DAY)

    def test_parse_modev1t_evi_row(self):
        row = parse_modev1f_cells(
            ["1", "MODEV1T.20160511.CN.EVI.MAX.V2", "2016-05-11", "104.5003", "32.5004", "有"],
            row_index=0,
        )

        self.assertIsNotNone(row)
        self.assertEqual(row["scene_id"], "MODEV1T.20160511.CN.EVI.MAX.V2")
        self.assertEqual(row["date"], "2016-05-11")
        self.assertEqual(row["year"], "2016")
        self.assertEqual(row["longitude"], 104.5003)
        self.assertEqual(row["latitude"], 32.5004)
        self.assertEqual(row["data_available"], "有")
        self.assertEqual(row["product_tag"], "EVI")


if __name__ == "__main__":
    unittest.main()
