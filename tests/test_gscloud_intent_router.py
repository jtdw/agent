import unittest

from core.domestic_sources.intent_router import route_gscloud_download_intent


class GSCloudIntentRouterTests(unittest.TestCase):
    def test_routes_common_typos_to_sentinel2(self):
        route = route_gscloud_download_intent("下载 sentinal2 数据")

        self.assertEqual(route.kind, "matched")
        self.assertEqual(route.product_key, "sentinel2_msi")
        self.assertEqual(route.resource_type, "sentinel2_msi")
        self.assertGreaterEqual(route.confidence, 0.75)

    def test_routes_partial_mod021km_reflectance_request(self):
        route = route_gscloud_download_intent("获取 mod21km 地表反射")

        self.assertEqual(route.kind, "matched")
        self.assertEqual(route.product_key, "mod021km_1km_surface_reflectance")
        self.assertEqual(route.resource_type, "mod021km_surface_reflectance")

    def test_routes_short_evi_5day_request(self):
        route = route_gscloud_download_intent("下载五天evi")

        self.assertEqual(route.kind, "matched")
        self.assertEqual(route.product_key, "modev1f_china_250m_evi_5day")
        self.assertEqual(route.resource_type, "modev1f_evi_5day")

    def test_routes_surface_temperature_request(self):
        route = route_gscloud_download_intent("获取地表温度")

        self.assertEqual(route.kind, "matched")
        self.assertEqual(route.product_key, "modl1d_china_1km_lst_daily")

    def test_ambiguous_vegetation_request_asks_clarification(self):
        route = route_gscloud_download_intent("下载植被数据")

        self.assertEqual(route.kind, "clarify")
        self.assertEqual(route.product_key, "")
        self.assertIn("NDVI", route.clarification)
        self.assertIn("EVI", route.clarification)

    def test_ambiguous_remote_sensing_image_request_asks_clarification(self):
        route = route_gscloud_download_intent("下载遥感影像")

        self.assertEqual(route.kind, "clarify")
        self.assertIn("Sentinel-2", route.clarification)
        self.assertIn("Landsat 8", route.clarification)

    def test_low_confidence_prompt_returns_none(self):
        route = route_gscloud_download_intent("帮我分析这个结果为什么不稳定")

        self.assertEqual(route.kind, "none")
        self.assertEqual(route.product_key, "")


    def test_clear_product_without_region_asks_region_clarification(self):
        route = route_gscloud_download_intent("下载 Landsat 8")

        self.assertEqual(route.kind, "clarify")
        self.assertIn("区域", route.clarification)


if __name__ == "__main__":
    unittest.main()
