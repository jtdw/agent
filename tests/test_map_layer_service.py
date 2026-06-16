from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from core.config import Settings
from core.map_layers import MapLayerService
from core.service import GISWorkspaceService


class MapLayerServiceTests(unittest.TestCase):
    def test_dataset_layer_includes_artifact_identity_when_paths_match(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            gdf = gpd.GeoDataFrame({"name": ["sample"], "geometry": [Point(104.0, 30.0)]}, crs="EPSG:4326")
            dataset_name = service.manager.put_vector("sample_points", gdf)
            dataset_path = service.manager.get(dataset_name).path
            artifact = service.manager.register_artifact(
                artifact_id="artifact_sample_points",
                path=str(dataset_path),
                type="geojson",
                title="sample_points.geojson",
            )

            payload = MapLayerService(service).workspace_layers(user_id="u_test")

            layer = next(item for item in payload["layers"] if item["id"] == f"dataset_{dataset_name}")
            self.assertEqual(layer["dataset_name"], dataset_name)
            self.assertEqual(layer["artifact_id"], artifact["artifact_id"])
            self.assertTrue(layer["map_ready"])
            self.assertEqual(layer["meta"]["dataset_name"], dataset_name)
            self.assertEqual(layer["meta"]["artifact_id"], artifact["artifact_id"])
            self.assertEqual(layer["meta"]["crs"], "EPSG:4326")
            self.assertEqual(layer["meta"]["geometry_type"], "Point")

    def test_refresh_artifact_loads_spatial_file_and_updates_artifact_metadata(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            source_path = service.manager.derived_dir / "artifact_points.geojson"
            gpd.GeoDataFrame({"id": [1], "geometry": [Point(105.0, 31.0)]}, crs="EPSG:4326").to_file(source_path, driver="GeoJSON")
            service.manager.register_artifact(
                artifact_id="artifact_points",
                path=str(source_path),
                type="geojson",
                title="artifact_points.geojson",
            )

            refreshed = MapLayerService(service).refresh_artifact("artifact_points", user_id="u_test")

            self.assertTrue(refreshed["map_ready"])
            self.assertEqual(refreshed["artifact_id"], "artifact_points")
            self.assertTrue(refreshed["dataset_name"])
            self.assertTrue(refreshed["map_layer_id"].startswith("dataset_"))
            artifact = service.manager.get_artifact("artifact_points")
            self.assertIsNotNone(artifact)
            meta = artifact["meta"]
            self.assertTrue(meta["map_ready"])
            self.assertEqual(meta["dataset_name"], refreshed["dataset_name"])
            self.assertEqual(meta["map_layer_id"], refreshed["map_layer_id"])
            self.assertEqual(meta["layer_kind"], "boundary")


if __name__ == "__main__":
    unittest.main()
