from __future__ import annotations

import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from core.config import Settings
from core.data_manager import DataManager
from core.service import GISWorkspaceService
from core.tools.registry import build_tools
from core.workflows.data_package import ingest_data_package, plan_data_package_analysis


def _write_raster(path: Path, value: float = 10.0) -> None:
    data = np.full((3, 3), value, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(115.0, 43.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)


def _make_mixed_zip(root: Path) -> Path:
    station_csv = root / "stations.csv"
    pd.DataFrame(
        {
            "station_id": ["S1", "S2", "S3"],
            "lon": [115.5, 116.0, 116.5],
            "lat": [42.5, 42.0, 41.5],
            "date": ["2019-05-01", "2019-05-02", "2019-05-03"],
            "soil_moisture": [0.21, 0.24, 0.19],
        }
    ).to_csv(station_csv, index=False, encoding="utf-8")
    dem = root / "dem.tif"
    _write_raster(dem)
    readme = root / "README.md"
    readme.write_text("土壤水分测试数据包。", encoding="utf-8")

    archive_path = root / "mixed_package.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(station_csv, "tables/stations.csv")
        archive.write(dem, "rasters/dem.tif")
        archive.write(readme, "docs/README.md")
        archive.writestr(".env", "SECRET=blocked")
    return archive_path


def test_ingest_data_package_loads_all_supported_datasets_and_profiles_goal() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        manager = DataManager(root / "workspace")
        archive_path = _make_mixed_zip(manager.upload_dir)

        result = ingest_data_package(manager, str(archive_path), user_goal="使用 XGBoost 预测土壤水分")

        assert result["ok"] is True
        assert result["loaded_count"] == 3
        assert {item["data_type"] for item in result["loaded_datasets"]} == {"table", "raster", "document"}
        assert ".env" in result["skipped_members"]
        assert any(item["target_candidates"] == ["soil_moisture"] for item in result["profiles"] if item["data_type"] == "table")
        assert result["analysis_plan"]["intent"] == "modeling"
        assert "generic_xgboost_workflow" in result["analysis_plan"]["recommended_tools"]


def test_service_upload_batch_ingests_multi_dataset_zip() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        settings = Settings(api_key="", workdir=root / "workspace")
        service = GISWorkspaceService(settings)
        archive_path = _make_mixed_zip(root)
        payload = archive_path.read_bytes()

        messages = service.upload_bytes_batch([("mixed_package.zip", payload)])

        assert any("数据包入库完成" in message for message in messages)
        datasets = service.manager.list_datasets()
        assert {item["type"] for item in datasets} >= {"table", "raster", "document"}


def test_data_package_tools_are_registered() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        manager = DataManager(Path(tmp) / "workspace")

        names = {tool.name for tool in build_tools(manager)}

        assert "ingest_data_package" in names
        assert "plan_data_package_analysis" in names


def test_plan_data_package_analysis_prefers_spatial_modeling_when_points_and_rasters_exist() -> None:
    profiles = [
        {
            "name": "stations",
            "data_type": "table",
            "columns": ["lon", "lat", "soil_moisture", "date"],
            "numeric_fields": ["lon", "lat", "soil_moisture"],
            "x_candidates": ["lon"],
            "y_candidates": ["lat"],
            "time_candidates": ["date"],
            "target_candidates": ["soil_moisture"],
        },
        {"name": "dem", "data_type": "raster", "columns": [], "numeric_fields": []},
        {"name": "ndvi", "data_type": "raster", "columns": [], "numeric_fields": []},
    ]

    plan = plan_data_package_analysis(profiles, "预测土壤水分")

    assert plan["intent"] == "modeling"
    assert plan["primary_dataset"] == "stations"
    assert plan["target_col"] == "soil_moisture"
    assert plan["raster_features"] == ["dem", "ndvi"]
    assert plan["workflow_steps"][0]["tool_name"] == "table_to_points"
    assert plan["workflow_steps"][-1]["tool_name"] == "generic_xgboost_workflow"
