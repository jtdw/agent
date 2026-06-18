from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
from fastapi.testclient import TestClient
from shapely.geometry import Point

import api_server
from core.config import Settings
from core.service import GISWorkspaceService


class CheckpointMapLayerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict("os.environ", {"GIS_AGENT_ALLOW_ANONYMOUS": "1"})
        self.env.start()
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.service = GISWorkspaceService(Settings(api_key="", workdir=Path(self.tmp.name) / "workspace"))
        api_server._workspace_services.clear()
        api_server._workspace_services["anonymous"] = self.service
        self.client = TestClient(api_server.app)

    def tearDown(self) -> None:
        api_server._workspace_services.clear()
        self.tmp.cleanup()
        self.env.stop()

    def test_refresh_map_layer_from_artifact_id(self) -> None:
        gdf = gpd.GeoDataFrame({"value": [1], "geometry": [Point(104.0, 30.0)]}, crs="EPSG:4326")
        dataset_name = self.service.manager.put_vector("points", gdf)
        dataset_path = self.service.manager.get(dataset_name).path
        self.service.manager.register_artifact(
            artifact_id="artifact_points",
            path=str(dataset_path),
            type="geojson",
            title="points.geojson",
        )

        response = self.client.post("/api/map/layers/refresh", json={"artifact_id": "artifact_points"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["map_ready"])
        self.assertTrue(str(payload["dataset_name"]).startswith(dataset_name))
        self.assertEqual(payload["layer"]["artifact_id"], "artifact_points")

    def test_anonymous_map_layers_returns_empty_list(self) -> None:
        response = self.client.get("/api/map/layers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"layers": []})


if __name__ == "__main__":
    unittest.main()
