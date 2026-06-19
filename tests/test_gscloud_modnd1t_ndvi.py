from __future__ import annotations

import unittest

from core.domestic_sources.gscloud_modnd1d import parse_modnd1d_cells
from core.domestic_sources.gscloud_products import MODND1T_CHINA_500M_NDVI_10DAY, match_gscloud_product
from core.domestic_sources.intent_router import route_gscloud_download_intent


class GSCloudMODND1TNDVITests(unittest.TestCase):
    def test_product_config_uses_10day_ndvi_endpoint(self) -> None:
        self.assertEqual(MODND1T_CHINA_500M_NDVI_10DAY.key, "modnd1t_china_500m_ndvi_10day")
        self.assertEqual(MODND1T_CHINA_500M_NDVI_10DAY.resource_type, "modnd1t_ndvi_10day")
        self.assertEqual(MODND1T_CHINA_500M_NDVI_10DAY.dataset_id, "346")
        self.assertEqual(MODND1T_CHINA_500M_NDVI_10DAY.pid, "333")
        self.assertEqual(MODND1T_CHINA_500M_NDVI_10DAY.access_url, "https://www.gscloud.cn/sources/accessdata/346?pid=333")
        self.assertIn("旬合成", MODND1T_CHINA_500M_NDVI_10DAY.name)

    def test_parser_accepts_modnd1t_ndvi_max_scene_id(self) -> None:
        parsed = parse_modnd1d_cells(
            ["1", "MODND1T.20160511.CN.NDVI.MAX.V2", "2016-05-11", "104.5003", "32.5004", "有", "", ""],
            row_index=3,
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["scene_id"], "MODND1T.20160511.CN.NDVI.MAX.V2")
        self.assertEqual(parsed["date"], "2016-05-11")
        self.assertEqual(parsed["product_tag"], "NDVI")

    def test_ndvi_intent_routes_to_modnd1t_10day_product(self) -> None:
        route = route_gscloud_download_intent("下载闪电河流域的ndvi")

        self.assertEqual(route.kind, "matched")
        self.assertEqual(route.product_key, "modnd1t_china_500m_ndvi_10day")
        self.assertEqual(route.resource_type, "modnd1t_ndvi_10day")

    def test_product_match_prefers_modnd1t_for_ndvi(self) -> None:
        product = match_gscloud_product("MODND1T 中国 500M NDVI 旬合成产品")

        self.assertIs(product, MODND1T_CHINA_500M_NDVI_10DAY)


if __name__ == "__main__":
    unittest.main()
