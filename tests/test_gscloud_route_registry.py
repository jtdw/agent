from __future__ import annotations

import unittest

from core.gscloud_route_registry import (
    GSCloudDirectDownloadRoute,
    route_by_product_key,
    match_direct_download_route,
    validate_unique_product_keys,
)


class GSCloudRouteRegistryTests(unittest.TestCase):
    def test_route_registry_matches_prompt_and_product_key(self) -> None:
        routes = (
            GSCloudDirectDownloadRoute(
                product_key="a",
                matches=lambda prompt: "alpha" in prompt,
                submit=lambda user_id, prompt, session_id="": {"route": "a"},
                result_meta_keys=("model", "reason"),
            ),
            GSCloudDirectDownloadRoute(
                product_key="b",
                matches=lambda prompt: "beta" in prompt,
                submit=lambda user_id, prompt, session_id="": {"route": "b"},
                result_meta_keys=("model", "reason", "job"),
            ),
        )

        self.assertEqual(match_direct_download_route(routes, "use beta").product_key, "b")
        self.assertEqual(route_by_product_key(routes, "a").product_key, "a")
        self.assertIsNone(match_direct_download_route(routes, "none"))
        self.assertIsNone(route_by_product_key(routes, "missing"))

    def test_route_registry_rejects_duplicate_product_keys(self) -> None:
        routes = (
            GSCloudDirectDownloadRoute(
                product_key="dup",
                matches=lambda prompt: False,
                submit=lambda user_id, prompt, session_id="": {},
                result_meta_keys=("model",),
            ),
            GSCloudDirectDownloadRoute(
                product_key="dup",
                matches=lambda prompt: False,
                submit=lambda user_id, prompt, session_id="": {},
                result_meta_keys=("model",),
            ),
        )

        with self.assertRaises(ValueError):
            validate_unique_product_keys(routes)


if __name__ == "__main__":
    unittest.main()
