from __future__ import annotations

import unittest

from core.domestic_sources.gscloud_product_registry import get_scene_product_config, list_scene_product_configs


class GSCloudProductRegistryTests(unittest.TestCase):
    def test_registry_covers_frontend_scene_products(self):
        keys = {item.resource_type for item in list_scene_product_configs()}

        self.assertIn("landsat8_oli_tirs", keys)
        self.assertIn("modnd1t_ndvi_10day", keys)
        self.assertIn("modl1t_lst_composite", keys)
        self.assertIn("modev1t_evi_10day", keys)
        self.assertIn("mod021km_surface_reflectance", keys)
        self.assertIn("sentinel2_msi", keys)

    def test_lookup_accepts_product_key_or_resource_type(self):
        by_resource = get_scene_product_config("sentinel2_msi")
        by_key = get_scene_product_config("sentinel2_msi")

        self.assertEqual(by_resource.product_key, by_key.product_key)
        self.assertEqual(by_resource.default_output_name, "sentinel2_msi")


if __name__ == "__main__":
    unittest.main()
