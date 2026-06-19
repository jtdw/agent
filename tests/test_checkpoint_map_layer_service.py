from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from core.config import Settings
from core.map_layers import MapLayerService
from core.service import GISWorkspaceService


class CheckpointMapLayerServiceTests(unittest.TestCase):
    def test_workspace_layers_include_local_shandian_boundary_fallback(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))

            payload = MapLayerService(service).workspace_layers(user_id="u_test")

            layer = next((item for item in payload["layers"] if item["id"] == "local_library_shandianhe_basin_boundary"), None)
            self.assertIsNotNone(layer)
            self.assertEqual(layer["kind"], "boundary")
            self.assertEqual(layer["name"], "闪电河流域边界")

    def test_shandian_boundary_is_not_hidden_by_admin_boundary(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            admin = gpd.GeoDataFrame({"name": ["admin"], "geometry": [Point(104.0, 30.0)]}, crs="EPSG:4326")
            service.manager.put_vector("china_admin_county_2023", admin)

            payload = MapLayerService(service).workspace_layers(user_id="u_test")
            ids = [item["id"] for item in payload["layers"]]

            self.assertIn("local_library_shandianhe_basin_boundary", ids)
            self.assertIn("dataset_china_admin_county_2023", ids)

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
            self.assertEqual(layer["meta"]["artifact_id"], artifact["artifact_id"])

    def test_workspace_layers_promotes_unloaded_vector_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            path = service.manager.derived_dir / "downloaded_points.geojson"
            gdf = gpd.GeoDataFrame({"name": ["sample"], "geometry": [Point(104.0, 30.0)]}, crs="EPSG:4326")
            gdf.to_file(path, driver="GeoJSON")
            artifact = service.manager.register_artifact(
                artifact_id="artifact_downloaded_points",
                path=str(path),
                type="geojson",
                title="downloaded_points.geojson",
            )

            payload = MapLayerService(service).workspace_layers(user_id="u_test")

            layer = next((item for item in payload["layers"] if item["artifact_id"] == artifact["artifact_id"]), None)
            self.assertIsNotNone(layer)
            self.assertEqual(layer["type"], "vector")
            self.assertTrue(layer["map_ready"])

    def test_workspace_layers_promotes_unloaded_raster_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            path = service.manager.derived_dir / "downloaded_dem.tif"
            path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                height=2,
                width=2,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(104.0, 31.0, 0.1, 0.1),
            ) as dst:
                dst.write(np.array([[1, 2], [3, 4]], dtype="float32"), 1)
            artifact = service.manager.register_artifact(
                artifact_id="artifact_downloaded_dem",
                path=str(path),
                type="raster",
                title="downloaded_dem.tif",
            )

            payload = MapLayerService(service).workspace_layers(user_id="u_test")

            layer = next((item for item in payload["layers"] if item["artifact_id"] == artifact["artifact_id"]), None)
            self.assertIsNotNone(layer)
            self.assertEqual(layer["type"], "raster")
            self.assertTrue(layer["map_ready"])
            self.assertTrue(layer["preview_url"].startswith("/api/map/raster-preview?"))

    def test_large_county_admin_vector_layer_is_not_truncated(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            gdf = gpd.GeoDataFrame(
                {"name": [f"county_{i}" for i in range(2105)], "geometry": [Point(73 + i * 0.001, 30.0) for i in range(2105)]},
                crs="EPSG:4326",
            )

            layer = MapLayerService(service).vector_map_layer("china_admin_county_2023", gdf, dataset_name="china_admin_county_2023")

            self.assertIsNotNone(layer)
            self.assertEqual(layer["feature_count"], 2105)
            self.assertEqual(layer["meta"]["feature_count"], 2105)
            self.assertEqual(len(layer["geojson"]["features"]), 2105)


if __name__ == "__main__":
    unittest.main()
