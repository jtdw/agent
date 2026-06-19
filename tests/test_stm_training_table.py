from __future__ import annotations

import json
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from core.config import Settings
from core.service import GISWorkspaceService
from core.station_data import stm_archive_to_training_dataframe
from core.tool_contracts import parse_tool_result
from core.tools.registry import build_tools


def _write_station_archive(path: Path) -> None:
    l1_005 = "\n".join(
        [
            "SMN-SDR SMN-SDR L1 41.55076 115.53885 1433.0 0.0500 0.0500 5TM",
            "2019/01/01 00:00 0.1000 D01,D03 M",
            "2019/01/01 01:00 0.2000 D01,D03 M",
            "2019/01/02 00:00 -9999 D01,D03 M",
            "2018/01/01 00:00 0.9000 D01,D03 M",
            "2020/01/01 00:00 0.8000 D01,D03 M",
            "",
        ]
    )
    l2_005 = "\n".join(
        [
            "SMN-SDR SMN-SDR L2 41.78007 115.60314 1401.0 0.0500 0.0500 5TM",
            "2019/01/01 00:00 0.3000 D01,D03 M",
            "2019/01/01 01:00 1.3000 D01,D03 M",
            "",
        ]
    )
    l1_010 = "\n".join(
        [
            "SMN-SDR SMN-SDR L1 41.55076 115.53885 1433.0 0.1000 0.1000 5TM",
            "2019/01/01 00:00 0.7000 D01,D03 M",
            "",
        ]
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SMN-SDR/L1/L1_sm_0.050000_0.050000_20190101_20191231.stm", l1_005)
        archive.writestr("SMN-SDR/L2/L2_sm_0.050000_0.050000_20190101_20191231.stm", l2_005)
        archive.writestr("SMN-SDR/L1/L1_sm_0.100000_0.100000_20190101_20191231.stm", l1_010)


def test_stm_archive_to_training_dataframe_daily_filters_depth_year_and_invalid_values() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        archive_path = Path(tmp) / "stations.zip"
        _write_station_archive(archive_path)

        df = stm_archive_to_training_dataframe(archive_path, preferred_depth="0.050000", year="2019", aggregate="daily")

        assert list(df.columns) == [
            "station_id",
            "lon",
            "lat",
            "elevation_m",
            "depth_m",
            "date",
            "soil_moisture_mean",
            "soil_moisture_min",
            "soil_moisture_max",
            "soil_moisture_count",
        ]
        assert len(df) == 2
        l1 = df[df["station_id"] == "L1"].iloc[0]
        assert l1["date"] == "2019-01-01"
        assert l1["soil_moisture_mean"] == 0.15
        assert l1["soil_moisture_count"] == 2
        assert set(df["station_id"]) == {"L1", "L2"}


def test_stm_archive_to_training_dataframe_hourly_outputs_raw_samples() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        archive_path = Path(tmp) / "stations.zip"
        _write_station_archive(archive_path)

        df = stm_archive_to_training_dataframe(archive_path, preferred_depth="0.050000", year="2019", aggregate="none")

        assert len(df) == 3
        assert {"date", "time", "soil_moisture"}.issubset(df.columns)
        assert df["soil_moisture"].max() == 0.3


def test_convert_stm_tool_registers_training_table() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(api_key="", workdir=Path(tmp) / "workspace")
        service = GISWorkspaceService(settings)
        archive_path = service.manager.upload_dir / "stations.zip"
        _write_station_archive(archive_path)
        tools = {tool.name: tool for tool in build_tools(service.manager)}

        raw = tools["convert_stm_station_archive_to_training_table"].invoke(
            {
                "archive_path": str(archive_path),
                "preferred_depth": "0.050000",
                "year": "2019",
                "output_name": "soil_training",
                "aggregate": "daily",
            }
        )
        result = parse_tool_result(raw)

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["result_dataset"] == "soil_training"
        assert result["outputs"]["row_count"] == 2
        assert "soil_training" in service.manager.datasets
        assert service.manager.get("soil_training").data_type == "table"
