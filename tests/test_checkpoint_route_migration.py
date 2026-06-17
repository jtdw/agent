from __future__ import annotations

import unittest

import api_server


class CheckpointRouteMigrationTests(unittest.TestCase):
    def test_gscloud_account_routes_are_modularized(self) -> None:
        expected = {
            "/api/data-sources/gscloud/status",
            "/api/data-sources/gscloud/login/start",
            "/api/data-sources/gscloud/login/complete",
            "/api/data-sources/gscloud/logout",
        }
        modules = {
            route.path: route.endpoint.__module__
            for route in api_server.app.routes
            if getattr(route, "path", "") in expected
        }

        self.assertEqual(set(modules), expected)
        self.assertEqual(set(modules.values()), {"api.routes.data_sources"})

    def test_download_resume_route_is_modularized(self) -> None:
        route = next(route for route in api_server.app.routes if getattr(route, "path", "") == "/api/download-jobs/{job_id}/resume")

        self.assertEqual(route.endpoint.__module__, "api.routes.downloads")


if __name__ == "__main__":
    unittest.main()
