from __future__ import annotations

import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from core.config import Settings
from core.data_manager import DataManager
from core.ismn_adapter import list_ismn_archives, profile_ismn_archive


class FakeISMNInterface:
    networks = ["NET_A"]
    stations = [
        {
            "network": "NET_A",
            "station": "ST_001",
            "latitude": 30.1,
            "longitude": 100.2,
            "sensors": [
                {
                    "variable": "soil_moisture",
                    "depth_from": 0.0,
                    "depth_to": 0.05,
                    "instrument": "probe",
                    "start": "2020-01-01",
                    "end": "2020-01-31",
                }
            ],
        }
    ]


def _write_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("readme.txt", "official ismn archive fixture")


def _write_stm_zip_with_mixed_station_dates(path: Path) -> None:
    station_a = "\n".join(
        [
            "NET_A sensor ST_A 30.1 100.2 410 0.050000 0.050000 sm",
            "2018-07-25 00:00 0.20 G",
            "2019-12-31 00:00 0.24 G",
        ]
    )
    station_b = "\n".join(
        [
            "NET_A sensor ST_B 30.2 100.3 420 0.050000 0.050000 sm",
            "2019-03-01 00:00 0.31 G",
            "2019-03-05 00:00 0.32 G",
        ]
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("NET_A/ST_A_sm_0.050000_0.050000_sensor.stm", station_a)
        archive.writestr("NET_A/ST_B_sm_0.050000_0.050000_sensor.stm", station_b)


def _write_stm_zip_with_multiple_depths(path: Path) -> None:
    shallow = "\n".join(
        [
            "NET_A sensor ST_A 30.1 100.2 410 0.050000 0.050000 sm",
            "2018-07-25 00:00 0.20 G",
        ]
    )
    deep = "\n".join(
        [
            "NET_A sensor ST_A 30.1 100.2 410 0.200000 0.200000 sm",
            "2019-01-01 00:00 0.28 G",
        ]
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("NET_A/ST_A_sm_0.050000_0.050000_sensor.stm", shallow)
        archive.writestr("NET_A/ST_A_sm_0.200000_0.200000_sensor.stm", deep)


def test_list_ismn_archives_finds_uploads_and_local_library_without_absolute_paths() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        manager = DataManager(Path(tmp) / "workspace")
        upload_archive = manager.upload_dir / "uploaded_ismn.zip"
        local_dir = manager.workdir / "local_library" / "data" / "ismn"
        local_dir.mkdir(parents=True, exist_ok=True)
        local_archive = local_dir / "library_ismn.zip"
        _write_zip(upload_archive)
        _write_zip(local_archive)

        archives = list_ismn_archives(manager)
        encoded = str(archives)

        assert {"uploaded_ismn.zip", "library_ismn.zip"}.issubset({item["filename"] for item in archives})
        assert all(item["archive_id"] for item in archives)
        assert all(not Path(item["location"]).is_absolute() for item in archives)
        assert str(manager.workdir) not in encoded


def test_profile_ismn_archive_reports_missing_optional_dependency(monkeypatch) -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        archive_path = Path(tmp) / "official_ismn.zip"
        _write_zip(archive_path)
        monkeypatch.setattr("core.ismn_adapter.load_ismn_interface_class", lambda: None)

        result = profile_ismn_archive(archive_path)

        assert result["ok"] is False
        assert result["error_code"] == "ISMN_DEPENDENCY_MISSING"
        assert "next_actions" in result


def test_profile_ismn_archive_accepts_injected_interface_factory() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        archive_path = Path(tmp) / "official_ismn.zip"
        _write_zip(archive_path)

        result = profile_ismn_archive(archive_path, interface_factory=lambda path: FakeISMNInterface())

        assert result["ok"] is True
        assert result["profile"]["networks"] == ["NET_A"]
        assert result["profile"]["station_count"] == 1
        assert result["profile"]["sensor_count"] == 1
        assert result["profile"]["variables"] == ["soil_moisture"]
        assert result["profile"]["depths"] == [{"depth_from": 0.0, "depth_to": 0.05}]


def test_profile_local_stm_archive_uses_actual_dates_and_station_ranges() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        archive_path = Path(tmp) / "official_ismn.zip"
        _write_stm_zip_with_mixed_station_dates(archive_path)

        result = profile_ismn_archive(archive_path)

        assert result["ok"] is True
        assert result["reader"] == "local_stm_adapter"
        profile = result["profile"]
        assert profile["time_range"] == {"start": "2018-07-25 00:00", "end": "2019-12-31 00:00"}
        ranges = profile["station_time_ranges"]
        assert ranges == [
            {
                "station_id": "ST_A",
                "depth_from": 0.05,
                "depth_to": 0.05,
                "start": "2018-07-25 00:00",
                "end": "2019-12-31 00:00",
                "row_count": 2,
            },
            {
                "station_id": "ST_B",
                "depth_from": 0.05,
                "depth_to": 0.05,
                "start": "2019-03-01 00:00",
                "end": "2019-03-05 00:00",
                "row_count": 2,
            },
        ]


def test_profile_local_stm_archive_reports_all_available_depths() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        archive_path = Path(tmp) / "official_ismn.zip"
        _write_stm_zip_with_multiple_depths(archive_path)

        result = profile_ismn_archive(archive_path)

        assert result["ok"] is True
        profile = result["profile"]
        assert profile["depths"] == [
            {"depth_from": 0.05, "depth_to": 0.05},
            {"depth_from": 0.2, "depth_to": 0.2},
        ]
        assert profile["sensor_count"] == 2
        assert profile["time_range"] == {"start": "2018-07-25 00:00", "end": "2019-01-01 00:00"}
        assert [item["depth_from"] for item in profile["station_time_ranges"]] == [0.05, 0.2]
