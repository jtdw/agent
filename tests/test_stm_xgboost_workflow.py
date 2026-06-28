from __future__ import annotations

import json
import zipfile
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as transform_coords

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
        service.manager.put_raster_path("dem", raster_path, meta={"crs": "EPSG:3857"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem",
                    "output_prefix": "stm_full",
                    "aggregate": "daily",
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        assert result["outputs"]["training_dataset"] == "stm_full_training"
        assert result["outputs"]["point_dataset"] == "stm_full_points"
        assert result["outputs"]["feature_dataset"] == "stm_full_features"
        assert result["outputs"]["model_result"]["ok"] is True
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
            "dem_terrain_derivatives",
            "table_to_points",
            "batch_register_points_to_rasters",
            "generic_xgboost_workflow",
        ]


def test_stm_xgboost_workflow_aligns_temporal_rasters_before_sampling() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        raster_path = service.manager.upload_dir / "ndvi_daily.tif"
        _write_temporal_covering_raster(raster_path)
        service.manager.put_raster_path("ndvi_daily", raster_path, meta={"crs": "EPSG:4326"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "ndvi_daily",
                    "output_prefix": "stm_temporal",
                    "aggregate": "daily",
                    "min_samples": 3,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["status"] == "modeled"
        assert result["outputs"]["training_dataset"] == "stm_temporal_aligned_training"
        assert result["outputs"]["temporal_alignment"]["selected_time_range"] == {"start": "2019-01-04", "end": "2019-01-13"}
        assert result["outputs"]["temporal_composites"]["ndvi_daily"] == "stm_temporal_ndvi_daily_composite"
        assert result["outputs"]["raster_features"] == ["stm_temporal_ndvi_daily_composite"]
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
            "build_temporal_covariate_composite",
        ]
        assert [step["tool_name"] for step in result["outputs"]["steps"]][3:5] == [
            "table_to_points",
            "batch_register_points_to_rasters",
        ]
        register_step = next(step for step in result["outputs"]["steps"] if step["tool_name"] == "batch_register_points_to_rasters")
        assert register_step["args"]["raster_names"] == "stm_temporal_ndvi_daily_composite"


def test_stm_xgboost_workflow_does_not_derive_terrain_for_non_dem_raster() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _service(tmp)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_many_day_station_archive(archive_path)
        raster_path = service.manager.upload_dir / "ndvi.tif"
        _write_covering_raster(raster_path)
        service.manager.put_raster_path("ndvi", raster_path, meta={"crs": "EPSG:4326"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "ndvi",
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
        service.manager.put_raster_path("dem", raster_path, meta={"crs": "EPSG:3857"})
        tool = {item.name: item for item in build_tools(service.manager)}["run_stm_soil_moisture_xgboost_workflow"]

        result = parse_tool_result(
            tool.invoke(
                {
                    "archive_path": str(archive_path),
                    "raster_names": "dem",
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
