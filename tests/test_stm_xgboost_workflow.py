from __future__ import annotations

import json
import zipfile
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as transform_coords
from shapely.geometry import box

from core.config import Settings
from core.service import GISWorkspaceService
from core.tool_contracts import parse_tool_result
from core.tools.registry import build_tools
from core.workflows.registry import build_executable_workflow, list_workflow_templates
from core.workflows.stm_soil_moisture import resolve_default_station_archive


def _write_many_day_station_archive(path: Path, days: int = 16) -> None:
    lines = ["SMN-SDR SMN-SDR L1 41.55076 115.53885 1433.0 0.0500 0.0500 5TM"]
    start = date(2019, 1, 1)
    for idx in range(days):
        current = start + timedelta(days=idx)
        value = 0.10 + idx * 0.01
        lines.append(f"{current:%Y/%m/%d} 00:00 {value:.4f} D01,D03 M")
        lines.append(f"{current:%Y/%m/%d} 12:00 {value + 0.01:.4f} D01,D03 M")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SMN-SDR/L1/L1_sm_0.050000_0.050000_20190101_20191231.stm", "\n".join(lines))


def _write_two_station_archive(path: Path, days: int = 12) -> None:
    start = date(2019, 1, 1)
    stations = [
        ("INSIDE", 41.55076, 115.53885, 1433.0, 0.10),
        ("OUTSIDE", 41.55076, 115.54885, 1433.0, 0.20),
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for station_id, lat, lon, elev, base_value in stations:
            lines = [f"SMN-SDR SMN-SDR {station_id} {lat:.5f} {lon:.5f} {elev:.1f} 0.0500 0.0500 5TM"]
            for idx in range(days):
                current = start + timedelta(days=idx)
                value = base_value + idx * 0.005
                lines.append(f"{current:%Y/%m/%d} 00:00 {value:.4f} D01,D03 M")
                lines.append(f"{current:%Y/%m/%d} 12:00 {value + 0.002:.4f} D01,D03 M")
            archive.writestr(f"SMN-SDR/{station_id}/{station_id}_sm_0.050000_0.050000_20190101_20191231.stm", "\n".join(lines))


def _write_covering_raster(path: Path) -> None:
    data = np.arange(100, dtype="float32").reshape(10, 10)
    x, y = transform_coords("EPSG:4326", "EPSG:3857", [115.53885], [41.55076])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(x[0] - 500.0, y[0] + 500.0, 100.0, 100.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)


def _write_temporal_covering_raster(path: Path) -> None:
    band_dates = [date(2019, 1, 4) + timedelta(days=idx) for idx in range(10)]
    data = np.stack([np.full((10, 10), 0.2 + idx * 0.01, dtype="float32") for idx in range(len(band_dates))])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=len(band_dates),
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(115.53885 - 0.05, 41.55076 + 0.05, 0.01, 0.01),
        nodata=-9999.0,
    ) as dst:
        dst.write(data)
        for index, current in enumerate(band_dates, start=1):
            dst.set_band_description(index, f"{current:%Y_%m_%d}_{current:%Y_%m_%d}_NDVI")


def _write_daily_multiband_raster(path: Path, *, token: str, base: float, step: float, days: int = 16, scale: float = 1.0) -> None:
    band_dates = [date(2019, 1, 1) + timedelta(days=idx) for idx in range(days)]
    data = np.stack([np.full((10, 10), base + idx * step, dtype="float32") for idx in range(days)])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=days,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(115.53885 - 0.05, 41.55076 + 0.05, 0.01, 0.01),
        nodata=-9999.0,
    ) as dst:
        dst.write(data)
        dst.scales = tuple([scale] * days)
        dst.offsets = tuple([0.0] * days)
        for index, current in enumerate(band_dates, start=1):
            dst.set_band_description(index, f"{current:%Y_%m_%d}_{current:%Y_%m_%d}_{token}")


def _write_netcdf_style_daily_raster(path: Path, *, token: str, base: float, step: float, days: int = 16, scale: float = 1.0) -> None:
    data = np.stack([np.full((10, 10), base + idx * step, dtype="float32") for idx in range(days)])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=days,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(115.53885 - 0.05, 41.55076 + 0.05, 0.01, 0.01),
        nodata=-9999.0,
    ) as dst:
        dst.write(data)
        dst.scales = tuple([scale] * days)
        dst.offsets = tuple([0.0] * days)
        dst.update_tags(**{"time#units": "days since 2019-01-01 00:00:00"})
        for index in range(1, days + 1):
            dst.update_tags(index, NETCDF_VARNAME=token, NETCDF_DIM_time=str(index - 1), units="mm day-1")


def _write_lulc_mask_raster(path: Path) -> None:
    data = np.array([[10, 0]], dtype="uint8")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=1,
        width=2,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(115.53385, 41.55576, 0.01, 0.01),
    ) as dst:
        dst.write(data, 1)


def _put_covering_boundary(service: GISWorkspaceService, name: str = "study_area") -> str:
    boundary = gpd.GeoDataFrame(
        {"name": [name]},
        geometry=[box(115.0, 41.0, 116.0, 42.0)],
        crs="EPSG:4326",
    )
    return service.manager.put_vector(name, boundary)


def _put_inside_only_boundary(service: GISWorkspaceService, name: str = "inside_boundary") -> str:
    boundary = gpd.GeoDataFrame(
        {"name": [name]},
        geometry=[box(115.535, 41.548, 115.542, 41.554)],
        crs="EPSG:4326",
    )
    return service.manager.put_vector(name, boundary)


def _write_shandian_boundary_library(manager, tmp_root: Path, *, inside_only: bool = True) -> None:
    boundary_dir = manager.workdir / "local_library" / "data" / "boundary"
    boundary_dir.mkdir(parents=True, exist_ok=True)
    source_dir = tmp_root / "source_boundary"
    source_dir.mkdir(parents=True, exist_ok=True)
    geom = box(115.535, 41.548, 115.542, 41.554) if inside_only else box(115.0, 41.0, 116.0, 42.0)
    gdf = gpd.GeoDataFrame({"name": ["shandianhe"]}, geometry=[geom], crs="EPSG:4326")
    shp_path = source_dir / "shandianhe_basin_boundary.shp"
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    with zipfile.ZipFile(boundary_dir / "shandianhe_basin_boundary_full.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_dir.glob("shandianhe_basin_boundary.*"):
            archive.write(path, arcname=path.name)


def _service(tmp: str) -> GISWorkspaceService:
    return GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))


def test_stm_xgboost_workflow_stops_after_training_table_when_no_raster_features() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "output_prefix": "stm_demo",
                    "aggregate": "daily",
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "needs_raster_features"
        assert result["outputs"]["training_dataset"] == "stm_demo_training"
        assert "stm_demo_training" in service.manager.datasets
        assert "generic_xgboost_workflow" not in [step["tool_name"] for step in result["outputs"]["steps"]]


def test_stm_xgboost_workflow_runs_full_pipeline_when_raster_features_exist() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        raster_path = service.manager.upload_dir / "dem.tif"
        _write_covering_raster(raster_path)
        boundary_name = _put_covering_boundary(service)
        service.manager.put_raster_path("dem", raster_path, meta={"crs": "EPSG:3857"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem",
                    "boundary_name": boundary_name,
                    "output_prefix": "stm_full",
                    "aggregate": "daily",
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        assert result["outputs"]["training_dataset"] == "stm_full_unified_training"
        assert result["outputs"]["point_dataset"] == "stm_full_points"
        assert result["outputs"]["feature_dataset"] == "stm_full_features"
        assert result["outputs"]["model_result"]["ok"] is True
        assert result["outputs"]["unified_preprocessing"]["removed_row_count"] == 0
        assert result["outputs"]["raster_features"] == [
            "dem",
            "stm_full_dem_slope",
            "stm_full_dem_terrain",
            "stm_full_dem_twi",
        ]
        assert {"raster_dem", "raster_stm_full_dem_slope", "raster_stm_full_dem_terrain", "raster_stm_full_dem_twi"}.issubset(
            set(result["outputs"]["feature_cols"])
        )
        assert "raster_stm_full_dem_aspect" not in result["outputs"]["feature_cols"]
        assert "raster_stm_full_dem_twi" in result["outputs"]["model_feature_cols"]
        assert [step["tool_name"] for step in result["outputs"]["steps"]] == [
            "convert_stm_station_archive_to_training_table",
            "prepare_study_area_training_samples",
            "table_to_points",
            "batch_register_points_to_rasters",
            "prepare_unified_training_samples",
            "dem_terrain_derivatives",
            "table_to_points",
            "batch_register_points_to_rasters",
            "generic_xgboost_workflow",
            "predict_xgboost_raster_map",
        ]
        assert result["outputs"]["prediction_result"]["ok"] is True
        assert result["outputs"]["prediction_raster"] == "stm_full_prediction"
        assert service.manager.get(result["outputs"]["prediction_raster"]).data_type == "raster"
        assert Path(result["outputs"]["prediction_preview"]).exists()
        assert Path(result["outputs"]["prediction_summary"]).exists()


def test_stm_xgboost_workflow_filters_lulc_zero_before_derivatives() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_two_station_archive(archive_path)
        dem_path = service.manager.upload_dir / "dem.tif"
        lulc_path = service.manager.upload_dir / "lulc.tif"
        _write_covering_raster(dem_path)
        _write_lulc_mask_raster(lulc_path)
        boundary_name = _put_covering_boundary(service)
        service.manager.put_raster_path("dem", dem_path, meta={"crs": "EPSG:3857"})
        service.manager.put_raster_path("lulc", lulc_path, meta={"crs": "EPSG:4326", "dataset_type": "landcover"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem,lulc",
                    "boundary_name": boundary_name,
                    "output_prefix": "stm_filtered",
                    "aggregate": "daily",
                    "min_samples": 8,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        assert result["outputs"]["training_dataset"] == "stm_filtered_unified_training"
        assert result["outputs"]["unified_preprocessing"]["removed_row_count"] == 12
        assert result["outputs"]["unified_preprocessing"]["removed_station_count"] == 1
        assert result["outputs"]["unified_preprocessing"]["removed_stations"] == ["OUTSIDE"]
        assert "raster_lulc" in result["outputs"]["model_result"]["diagnostics"]["categorical_features"]
        unified = service.manager.get_table("stm_filtered_unified_training")
        assert set(unified["station_id"]) == {"INSIDE"}
        derivative_index = [step["tool_name"] for step in result["outputs"]["steps"]].index("dem_terrain_derivatives")
        unified_index = [step["tool_name"] for step in result["outputs"]["steps"]].index("prepare_unified_training_samples")
        assert unified_index < derivative_index


def test_stm_xgboost_workflow_filters_stations_by_explicit_study_area_before_raster_sampling() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_two_station_archive(archive_path)
        dem_path = service.manager.upload_dir / "dem.tif"
        _write_covering_raster(dem_path)
        boundary_name = _put_inside_only_boundary(service)
        service.manager.put_raster_path("dem", dem_path, meta={"crs": "EPSG:3857"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem",
                    "boundary_name": boundary_name,
                    "output_prefix": "stm_boundary",
                    "aggregate": "daily",
                    "min_samples": 8,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        preprocessing = result["outputs"]["unified_preprocessing"]
        assert preprocessing["filter_method"] == "study_area_boundary"
        assert preprocessing["boundary_dataset"] == boundary_name
        assert preprocessing["study_area_filter"]["removed_row_count"] == 12
        assert preprocessing["study_area_filter"]["removed_station_count"] == 1
        assert preprocessing["study_area_filter"]["removed_stations"] == ["OUTSIDE"]
        assert set(service.manager.get_table("stm_boundary_unified_training")["station_id"]) == {"INSIDE"}
        step_names = [step["tool_name"] for step in result["outputs"]["steps"]]
        assert step_names.index("prepare_study_area_training_samples") < step_names.index("batch_register_points_to_rasters")


def test_stm_xgboost_workflow_asks_for_study_area_when_area_cannot_be_inferred() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        raster_path = service.manager.upload_dir / "dem.tif"
        _write_covering_raster(raster_path)
        service.manager.put_raster_path("dem", raster_path, meta={"crs": "EPSG:3857"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem",
                    "output_prefix": "stm_missing_area",
                    "aggregate": "daily",
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "needs_study_area"
        assert result["outputs"]["study_area_resolution"]["status"] == "missing"
        assert "generic_xgboost_workflow" not in [step["tool_name"] for step in result["outputs"]["steps"]]


def test_stm_xgboost_workflow_resolves_shandianhe_boundary_from_local_library() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "shandianhe_stations.zip"
        _write_two_station_archive(archive_path)
        _write_shandian_boundary_library(service.manager, Path(tmp))
        raster_path = service.manager.upload_dir / "dem.tif"
        _write_covering_raster(raster_path)
        service.manager.put_raster_path("dem", raster_path, meta={"crs": "EPSG:3857"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem",
                    "study_area": "shandianhe",
                    "output_prefix": "stm_shandian",
                    "aggregate": "daily",
                    "min_samples": 8,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        assert result["outputs"]["unified_preprocessing"]["boundary_dataset"] == "shandianhe_basin_boundary"
        assert result["outputs"]["unified_preprocessing"]["study_area_filter"]["removed_stations"] == ["OUTSIDE"]


def test_stm_xgboost_workflow_aligns_temporal_rasters_before_sampling() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        raster_path = service.manager.upload_dir / "ndvi_daily.tif"
        _write_temporal_covering_raster(raster_path)
        boundary_name = _put_covering_boundary(service)
        service.manager.put_raster_path("ndvi_daily", raster_path, meta={"crs": "EPSG:4326"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "ndvi_daily",
                    "boundary_name": boundary_name,
                    "output_prefix": "stm_temporal",
                    "aggregate": "daily",
                    "min_samples": 3,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        assert result["outputs"]["training_dataset"] == "stm_temporal_unified_training"
        assert result["outputs"]["temporal_alignment"]["selected_time_range"] == {"start": "2019-01-04", "end": "2019-01-13"}
        assert result["outputs"]["temporal_composites"] == {}
        assert "raster_ndvi_daily_window_max_7d" in result["outputs"]["temporal_feature_cols"]
        assert "raster_ndvi_daily_window_max_7d" in result["outputs"]["model_feature_cols"]
        assert result["outputs"]["unified_preprocessing"]["removed_row_count"] == 0
        aligned = service.manager.get_table("stm_temporal_aligned_training")
        assert aligned["date"].tolist() == [
            "2019-01-04",
            "2019-01-05",
            "2019-01-06",
            "2019-01-07",
            "2019-01-08",
            "2019-01-09",
            "2019-01-10",
            "2019-01-11",
            "2019-01-12",
            "2019-01-13",
        ]
        assert [step["tool_name"] for step in result["outputs"]["steps"]][:3] == [
            "convert_stm_station_archive_to_training_table",
            "align_station_raster_time_window",
            "prepare_study_area_training_samples",
        ]
        step_names = [step["tool_name"] for step in result["outputs"]["steps"]]
        assert step_names.index("generic_xgboost_workflow") < step_names.index("build_temporal_covariate_composite")
        assert result["outputs"]["prediction_status"] == "prediction_feature_mapping_incomplete"
        assert "elevation_m" in result["outputs"]["prediction_result"]["outputs"]["missing_features"]
        assert "extract_temporal_station_covariates" in [step["tool_name"] for step in result["outputs"]["steps"]]


def test_stm_xgboost_workflow_derives_observation_window_temporal_features() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        dem_path = service.manager.upload_dir / "dem.tif"
        ndvi_path = service.manager.upload_dir / "ndvi_daily.tif"
        lst_path = service.manager.upload_dir / "lst_daily.tif"
        precip_path = service.manager.upload_dir / "precip_daily.tif"
        _write_covering_raster(dem_path)
        _write_daily_multiband_raster(ndvi_path, token="NDVI", base=0.10, step=0.01)
        _write_daily_multiband_raster(lst_path, token="LST", base=20.0, step=1.0)
        _write_daily_multiband_raster(precip_path, token="PRECIP", base=100.0, step=100.0, scale=0.01)
        boundary_name = _put_covering_boundary(service)
        service.manager.put_raster_path("dem", dem_path, meta={"crs": "EPSG:3857"})
        service.manager.put_raster_path("ndvi_daily", ndvi_path, meta={"crs": "EPSG:4326"})
        service.manager.put_raster_path("lst_daily", lst_path, meta={"crs": "EPSG:4326"})
        service.manager.put_raster_path("precip_daily", precip_path, meta={"crs": "EPSG:4326"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem,ndvi_daily,lst_daily,precip_daily",
                    "boundary_name": boundary_name,
                    "output_prefix": "stm_window",
                    "aggregate": "daily",
                    "min_samples": 8,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        expected_fields = {
            "raster_ndvi_daily_window_max_7d",
            "raster_lst_daily_window_median_7d",
            "raster_precip_daily_sum_3d",
            "raster_precip_daily_sum_7d",
            "raster_precip_daily_sum_14d",
            "raster_precip_daily_sum_30d",
        }
        assert expected_fields.issubset(set(result["outputs"]["temporal_feature_cols"]))
        assert expected_fields.issubset(set(result["outputs"]["model_feature_cols"]))
        step_names = [step["tool_name"] for step in result["outputs"]["steps"]]
        assert step_names.index("generic_xgboost_workflow") < step_names.index("build_temporal_covariate_composite")
        assert "predict_xgboost_raster_map" in step_names
        assert result["outputs"]["prediction_result"]["tool_name"] == "predict_xgboost_raster_map"
        assert result["outputs"]["prediction_status"] in {"mapped", "failed"}
        features = service.manager.get_vector(result["outputs"]["feature_dataset"]).drop(columns=["geometry"], errors="ignore")
        jan4 = features.loc[features["date"] == "2019-01-04"].iloc[0]
        assert np.isclose(jan4["raster_ndvi_daily_window_max_7d"], 0.16)
        assert np.isclose(jan4["raster_lst_daily_window_median_7d"], 23.0)
        assert np.isclose(jan4["raster_precip_daily_sum_3d"], 9.0)
        assert np.isclose(jan4["raster_precip_daily_sum_7d"], 10.0)


def test_stm_xgboost_workflow_reads_netcdf_time_tags_for_precipitation_windows() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        precip_path = service.manager.upload_dir / "china_1km_prep_2019.nc"
        _write_netcdf_style_daily_raster(precip_path, token="prep", base=100.0, step=100.0, scale=0.01)
        boundary_name = _put_covering_boundary(service)
        service.manager.put_raster_path("china_1km_prep_2019", precip_path, meta={"crs": "EPSG:4326"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "china_1km_prep_2019",
                    "boundary_name": boundary_name,
                    "output_prefix": "stm_netcdf_precip",
                    "aggregate": "daily",
                    "min_samples": 8,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        assert "china_1km_prep_2019" in result["outputs"]["temporal_alignment"]["raster_time_ranges"][0]["raster_name"]
        assert "raster_china_1km_prep_2019_sum_30d" in result["outputs"]["temporal_feature_cols"]
        features = service.manager.get_vector(result["outputs"]["feature_dataset"]).drop(columns=["geometry"], errors="ignore")
        jan4 = features.loc[features["date"] == "2019-01-04"].iloc[0]
        assert np.isclose(jan4["raster_china_1km_prep_2019_sum_3d"], 9.0)


def test_stm_xgboost_workflow_does_not_derive_terrain_for_non_dem_raster() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        raster_path = service.manager.upload_dir / "ndvi.tif"
        _write_covering_raster(raster_path)
        boundary_name = _put_covering_boundary(service)
        service.manager.put_raster_path("ndvi", raster_path, meta={"crs": "EPSG:4326"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "ndvi",
                    "boundary_name": boundary_name,
                    "output_prefix": "stm_ndvi",
                    "aggregate": "daily",
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        assert result["outputs"]["raster_features"] == ["ndvi"]
        assert "dem_terrain_derivatives" not in [step["tool_name"] for step in result["outputs"]["steps"]]
        assert "engineer_aspect_circular_features" not in [step["tool_name"] for step in result["outputs"]["steps"]]


def test_stm_xgboost_workflow_uses_dem_only_derivatives_without_aspect_engineering() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        raster_path = service.manager.upload_dir / "dem.tif"
        _write_covering_raster(raster_path)
        boundary_name = _put_covering_boundary(service)
        service.manager.put_raster_path("dem", raster_path, meta={"crs": "EPSG:3857"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem",
                    "boundary_name": boundary_name,
                    "output_prefix": "stm_no_circular",
                    "aggregate": "daily",
                    "encode_aspect_circular": False,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["model_dataset"] == result["outputs"]["feature_dataset"]
        assert "raster_stm_no_circular_dem_twi" in result["outputs"]["model_feature_cols"]
        assert "raster_stm_no_circular_dem_aspect" not in result["outputs"]["model_feature_cols"]
        assert "engineer_aspect_circular_features" not in [step["tool_name"] for step in result["outputs"]["steps"]]


def test_stm_xgboost_workflow_is_registered_as_executable_template() -> None:
    ids = {item["workflow_id"] for item in list_workflow_templates()}
    workflow = build_executable_workflow(
        "stm_soil_moisture_xgboost",
        {"archive_path": "stations.zip", "raster_names": "dem", "output_prefix": "demo"},
    )

    assert "stm_soil_moisture_xgboost" in ids
    assert workflow["status"] == "ready"
    assert workflow["workflow_plan"][0]["tool_name"] == "run_stm_soil_moisture_xgboost_workflow"


def test_soil_moisture_workflow_resolves_default_ismn_archive_from_local_library() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        station_dir = service.manager.workdir / "local_library" / "data" / "ismn"
        station_dir.mkdir(parents=True, exist_ok=True)
        archive_path = station_dir / "shandianhe2019_ismn_0_5cm.zip"
        _write_many_day_station_archive(archive_path)

        resolved = resolve_default_station_archive(service.manager)
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]
        result = parse_tool_result(tool.invoke({"archive_path": "", "output_prefix": "default_station"}))

        assert resolved == archive_path
        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["source_archive"] == str(archive_path)
        assert result["outputs"]["status"] == "needs_raster_features"


def test_stm_xgboost_workflow_template_allows_default_archive() -> None:
    workflow = build_executable_workflow("stm_soil_moisture_xgboost", {"output_prefix": "default_station"})

    assert workflow["status"] == "ready"
    assert workflow["missing_params"] == []
    assert workflow["workflow_plan"][0]["validated_tool_args"]["archive_path"] == ""
