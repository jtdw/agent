from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            dataset = service.manager.get(layer["dataset_name"])
            self.assertEqual(dataset.path.resolve(), path.resolve())
            self.assertEqual(list(service.manager.upload_dir.glob("*.tif")), [])

    def test_raster_preview_palette_generates_distinct_pngs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            path = service.manager.derived_dir / "palette_dem.tif"
            path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                height=3,
                width=3,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(104.0, 31.0, 0.1, 0.1),
            ) as dst:
                dst.write(np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype="float32"), 1)
            dataset_name = service.manager.register_raster_reference(path, name="palette_dem")
            layer_service = MapLayerService(service)

            terrain = layer_service.ensure_raster_preview(dataset_name, palette="terrain")
            magma = layer_service.ensure_raster_preview(dataset_name, palette="magma")

            self.assertIn("palette=terrain", terrain["preview_url"])
            self.assertIn("palette=magma", magma["preview_url"])
            self.assertNotEqual(terrain["preview_path"], magma["preview_path"])
            self.assertNotEqual(Path(terrain["preview_path"]).read_bytes(), Path(magma["preview_path"]).read_bytes())

    def test_raster_preview_reuses_cached_metadata_without_reopening_source(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            path = service.manager.derived_dir / "cached_dem.tif"
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
            dataset_name = service.manager.register_raster_reference(path, name="cached_dem")
            layer_service = MapLayerService(service)
            first = layer_service.ensure_raster_preview(dataset_name, user_id="u1", session_id="s1", palette="terrain")

            with mock.patch("rasterio.open", side_effect=AssertionError("cached preview should not reopen raster source")):
                second = layer_service.ensure_raster_preview(dataset_name, user_id="u1", session_id="s1", palette="terrain")

            self.assertEqual(second["preview_path"], first["preview_path"])
            self.assertEqual(second["bounds"], first["bounds"])
            self.assertEqual(second["meta"], first["meta"])

    def test_image_artifact_layer_uses_artifact_download_route_not_legacy_download_url(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            artifact = {
                "artifact_id": "artifact_image_001",
                "path": str(service.manager.plot_dir / "legacy_map.png"),
                "title": "legacy_map.png",
                "type": "image",
                "download_url": "/api/files/artifact?path=plots/legacy_map.png",
                "meta": {"bounds": [100.0, 20.0, 101.0, 21.0]},
            }

            with mock.patch.object(service.manager, "list_artifacts", return_value=[artifact]):
                payload = MapLayerService(service).workspace_layers(user_id="u_test", session_id="s1")

            layer = next(item for item in payload["layers"] if item.get("artifact_id") == "artifact_image_001")
            self.assertEqual(layer["preview_url"], "/api/artifacts/artifact_image_001/download?user_id=u_test&session_id=s1")
            self.assertNotIn("/api/files/artifact", layer["preview_url"])

    def test_refresh_raster_artifact_references_existing_file_without_upload_copy(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            path = service.manager.derived_dir / "downloads" / "job_demo" / "downloaded_dem.tif"
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
                artifact_id="artifact_job_demo_tif",
                path=str(path),
                type="raster",
                title="downloaded_dem.tif",
            )

            refreshed = MapLayerService(service).refresh_artifact(artifact["artifact_id"], user_id="u_test")

            dataset = service.manager.get(refreshed["dataset_name"])
            self.assertEqual(dataset.path.resolve(), path.resolve())
            self.assertEqual(list(service.manager.upload_dir.glob("*.tif")), [])

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
