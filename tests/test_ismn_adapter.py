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

        assert {item["filename"] for item in archives} == {"uploaded_ismn.zip", "library_ismn.zip"}
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
