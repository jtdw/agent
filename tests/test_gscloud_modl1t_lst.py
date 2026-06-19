from __future__ import annotations

import unittest

from core.domestic_sources.gscloud_modl1d import parse_modl1d_cells
from core.domestic_sources.gscloud_products import MODL1T_CHINA_1KM_LST_COMPOSITE, match_gscloud_product
from core.domestic_sources.intent_router import route_gscloud_download_intent


class GSCloudMODL1TLSTTests(unittest.TestCase):
    def test_product_config_uses_10day_lst_endpoint(self) -> None:
        self.assertEqual(MODL1T_CHINA_1KM_LST_COMPOSITE.key, "modl1t_china_1km_lst_composite")
        self.assertEqual(MODL1T_CHINA_1KM_LST_COMPOSITE.resource_type, "modl1t_lst_composite")
        self.assertEqual(MODL1T_CHINA_1KM_LST_COMPOSITE.dataset_id, "337")
        self.assertEqual(MODL1T_CHINA_1KM_LST_COMPOSITE.pid, "333")
        self.assertEqual(MODL1T_CHINA_1KM_LST_COMPOSITE.access_url, "https://www.gscloud.cn/sources/accessdata/337?pid=333")
        self.assertIn("旬合成", MODL1T_CHINA_1KM_LST_COMPOSITE.name)

    def test_parser_accepts_modl1t_lst_avg_and_max_scene_ids(self) -> None:
        avg = parse_modl1d_cells(
            ["1", "MODL1T.20160512.CN.LTD.AVG.V2", "2016-05-12", "104.5003", "32.5004", "有"],
            row_index=1,
        )
        max_item = parse_modl1d_cells(
            ["2", "MODL1T.20160512.CN.LTN.MAX.V2", "2016-05-12", "104.5003", "32.5004", "有"],
            row_index=2,
        )

        self.assertIsNotNone(avg)
        self.assertIsNotNone(max_item)
        assert avg is not None
        assert max_item is not None
        self.assertEqual(avg["product_tag"], "LTD")
        self.assertEqual(avg["stat_tag"], "AVG")
        self.assertEqual(max_item["product_tag"], "LTN")
        self.assertEqual(max_item["stat_tag"], "MAX")
        self.assertEqual(avg["product_family"], "main")
        self.assertEqual(max_item["product_family"], "main")

    def test_parser_accepts_gscloud_modlt1t_scene_ids(self) -> None:
        row = parse_modl1d_cells(
            ["1", "MODLT1T.20160512.CN.LTD.AVG.V2", "2016-05-12", "104.5003", "32.5004", "有"],
            row_index=1,
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["scene_id"], "MODLT1T.20160512.CN.LTD.AVG.V2")
        self.assertEqual(row["product_tag"], "LTD")
        self.assertEqual(row["stat_tag"], "AVG")
        self.assertEqual(row["product_family"], "main")

    def test_lst_intent_routes_to_modl1t_composite_product(self) -> None:
        route = route_gscloud_download_intent("下载闪电河流域地表温度")

        self.assertEqual(route.kind, "matched")
        self.assertEqual(route.product_key, "modl1t_china_1km_lst_composite")
        self.assertEqual(route.resource_type, "modl1t_lst_composite")

    def test_product_match_prefers_modl1t_for_surface_temperature(self) -> None:
        product = match_gscloud_product("MODL1T 中国 1KM 地表温度旬合成产品")

        self.assertIs(product, MODL1T_CHINA_1KM_LST_COMPOSITE)


if __name__ == "__main__":
    unittest.main()
