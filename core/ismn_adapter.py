from __future__ import annotations

import hashlib
import math
import re
import zipfile
from pathlib import Path
from statistics import mean
from typing import Any, Callable

import pandas as pd

from core.data_semantics import attach_semantic_card_to_dataset, build_data_semantic_card

MISSING_LIMIT = -100.0


def load_ismn_interface_class() -> Any | None:
    try:
        from ismn.interface import ISMN_Interface  # type: ignore

        return ISMN_Interface
    except Exception:
        return None


def _archive_id(path: Path) -> str:
    resolved = str(path.resolve(strict=False)).encode("utf-8", errors="ignore")
    return f"ismn_{hashlib.sha256(resolved).hexdigest()[:12]}"


def _candidate_roots(manager: Any) -> list[Path]:
    workdir = Path(getattr(manager, "workdir", "") or ".")
    roots: list[Path] = []
    for attr in ("upload_dir", "derived_dir"):
        raw = getattr(manager, attr, None)
        if raw:
            roots.append(Path(raw))
    roots.extend(
        [
            workdir / "local_library" / "data" / "ismn",
            workdir.parent / "local_library" / "data" / "ismn",
            Path.cwd() / "local_library" / "data" / "ismn",
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve(strict=False))
        except Exception:
            key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _safe_location(manager: Any, path: Path) -> str:
    workdir = Path(getattr(manager, "workdir", "") or ".")
    try:
        return str(path.resolve(strict=False).relative_to(workdir.resolve(strict=False))).replace("\\", "/")
    except Exception:
        return path.name


def _is_zip(path: Path) -> bool:
    if path.suffix.lower() != ".zip" or not path.is_file():
        return False
    try:
        with zipfile.ZipFile(path, "r") as archive:
            archive.namelist()
        return True
    except Exception:
        return False


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _stm_names(names: list[str]) -> list[str]:
    return [name for name in names if name.lower().endswith(".stm") and "/" in name]


def _choose_stm_depth_files(names: list[str], preferred_depth: str = "0.050000") -> list[str]:
    stm = _stm_names(names)
    if not stm:
        return []
    preferred = [name for name in stm if f"_sm_{preferred_depth}_{preferred_depth}_" in name]
    if preferred:
        return sorted(preferred)

    def depth_key(name: str) -> tuple[float, str]:
        match = re.search(r"_sm_([0-9.]+)_([0-9.]+)_", name)
        if not match:
            return (999.0, name)
        return (float(match.group(1)), name)

    stm.sort(key=depth_key)
    first_depth = depth_key(stm[0])[0]
    return [name for name in stm if abs(depth_key(name)[0] - first_depth) < 1e-9]


def _parse_stm_rows(raw: str, source_file: str, *, year: str = "") -> list[dict[str, Any]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].split()
    if len(header) < 9:
        return []
    station_id = header[2]
    lat = _safe_float(header[3])
    lon = _safe_float(header[4])
    elevation = _safe_float(header[5])
    depth_from = _safe_float(header[6])
    depth_to = _safe_float(header[7])
    if lat is None or lon is None:
        return []

    rows: list[dict[str, Any]] = []
    for row in lines[1:]:
        parts = row.split()
        if len(parts) < 3:
            continue
        date_part = parts[0]
        time_part = parts[1] if len(parts) > 1 else ""
        if year and not date_part.startswith(str(year)):
            continue
        value = _safe_float(parts[2])
        if value is None or value <= MISSING_LIMIT or value < 0 or value > 1.2:
            continue
        rows.append(
            {
                "network": header[0],
                "station_id": station_id,
                "station": station_id,
                "lon": float(lon),
                "lat": float(lat),
                "elevation_m": elevation,
                "depth_m": depth_from,
                "depth_from": depth_from,
                "depth_to": depth_to,
                "date": date_part.replace("/", "-").replace(".", "-"),
                "time": time_part,
                "date_time": f"{date_part.replace('/', '-').replace('.', '-')} {time_part}".strip(),
                "soil_moisture": float(value),
                "source_file": source_file,
            }
        )
    return rows


def _empty_observation_dataframe(aggregate: str) -> pd.DataFrame:
    if str(aggregate or "daily").strip().lower() == "daily":
        return pd.DataFrame(
            columns=[
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
        )
    return pd.DataFrame(
        columns=["network", "station_id", "station", "lon", "lat", "elevation_m", "depth_m", "date", "time", "date_time", "soil_moisture", "source_file"]
    )


def ismn_archive_to_observation_dataframe(
    archive_path: str | Path,
    *,
    preferred_depth: str = "0.050000",
    year: str = "2019",
    aggregate: str = "daily",
) -> pd.DataFrame:
    """Read local ISMN-style STM observations into a modeling table.

    This is the local archive adapter path used for legacy STM-compatible
    official ISMN packages. It does not download data and does not depend on
    the older station-data parser module.
    """
    path = Path(archive_path)
    if not path.exists():
        raise FileNotFoundError(f"ISMN archive not found: {path}")
    mode = str(aggregate or "daily").strip().lower()
    if mode not in {"daily", "none", "hourly", "raw"}:
        raise ValueError("aggregate must be one of: daily, none, hourly, raw")

    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(path, "r") as archive:
        for name in _choose_stm_depth_files(archive.namelist(), preferred_depth=preferred_depth):
            try:
                raw = archive.read(name).decode("utf-8", errors="replace")
            except Exception:
                continue
            rows.extend(_parse_stm_rows(raw, name, year=year))
    if not rows:
        return _empty_observation_dataframe(mode)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["date"].notna()].copy()
    df = df.sort_values(["station_id", "date", "time"]).reset_index(drop=True)
    if mode in {"none", "hourly", "raw"}:
        return df[["network", "station_id", "station", "lon", "lat", "elevation_m", "depth_m", "date", "time", "date_time", "soil_moisture", "source_file"]]

    grouped = (
        df.groupby(["station_id", "lon", "lat", "elevation_m", "depth_m", "date"], dropna=False)["soil_moisture"]
        .agg(["mean", "min", "max", "count"])
        .reset_index()
        .rename(
            columns={
                "mean": "soil_moisture_mean",
                "min": "soil_moisture_min",
                "max": "soil_moisture_max",
                "count": "soil_moisture_count",
            }
        )
    )
    grouped["soil_moisture_mean"] = grouped["soil_moisture_mean"].round(6)
    grouped["soil_moisture_min"] = grouped["soil_moisture_min"].round(6)
    grouped["soil_moisture_max"] = grouped["soil_moisture_max"].round(6)
    grouped["soil_moisture_count"] = grouped["soil_moisture_count"].astype(int)
    return grouped[
        [
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
    ]


def find_local_ismn_archives(*roots: str | Path) -> list[Path]:
    candidates: list[Path] = []
    keywords = ("ismn", "soil", "moisture", "station", "SMN-SDR", "smn-sdr", "2019")
    for root in roots:
        if not root:
            continue
        base = Path(root)
        if not base.exists():
            continue
        for path in base.rglob("*.zip"):
            lower = path.name.lower()
            if not any(token.lower() in lower for token in keywords):
                continue
            try:
                with zipfile.ZipFile(path, "r") as archive:
                    names = archive.namelist()
                    if not _stm_names(names):
                        continue
            except Exception:
                continue
            candidates.append(path)

    def sort_key(path: Path) -> tuple[int, int, float]:
        text = str(path).lower()
        ismn_hit = "ismn" in text
        station_hit = "station" in text or "stations" in text
        return (0 if ismn_hit else 1, 0 if station_hit else 1, -path.stat().st_mtime)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in sorted(candidates, key=sort_key):
        key = str(path.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def ismn_archive_to_station_collection(
    archive_path: str | Path,
    *,
    preferred_depth: str = "0.050000",
    year: str = "2019",
) -> dict[str, Any]:
    path = Path(archive_path)
    df = ismn_archive_to_observation_dataframe(path, preferred_depth=preferred_depth, year=year, aggregate="none")
    stations: list[dict[str, Any]] = []
    if not df.empty:
        grouped = df.groupby(["station_id", "lon", "lat", "elevation_m", "depth_m"], dropna=False)
        for key, group in grouped:
            station_id, lon, lat, elevation_m, depth_m = key
            values = pd.to_numeric(group["soil_moisture"], errors="coerce").dropna().tolist()
            first_time = str(group["date_time"].iloc[0]) if "date_time" in group else ""
            last_time = str(group["date_time"].iloc[-1]) if "date_time" in group else ""
            mean_value = round(float(mean(values)), 6) if values else None
            if mean_value is None:
                risk = "unknown"
                display_value = "--"
            elif mean_value < 0.10:
                risk = "low"
                display_value = f"{mean_value:.3f} m3/m3"
            elif mean_value < 0.18:
                risk = "mid"
                display_value = f"{mean_value:.3f} m3/m3"
            else:
                risk = "high"
                display_value = f"{mean_value:.3f} m3/m3"
            stations.append(
                {
                    "id": str(station_id),
                    "station_id": str(station_id),
                    "name": f"Station {station_id}",
                    "longitude": float(lon),
                    "latitude": float(lat),
                    "lng": float(lon),
                    "lat": float(lat),
                    "elevation_m": None if pd.isna(elevation_m) else float(elevation_m),
                    "depth_m": None if pd.isna(depth_m) else float(depth_m),
                    "depth_label": f"{float(depth_m):.2f} m" if not pd.isna(depth_m) else "",
                    "sample_count": int(len(values)),
                    "mean_sm": mean_value,
                    "min_sm": round(float(min(values)), 6) if values else None,
                    "max_sm": round(float(max(values)), 6) if values else None,
                    "first_time": first_time,
                    "last_time": last_time,
                    "source_file": str(group["source_file"].iloc[0]) if "source_file" in group else "",
                    "value": display_value,
                    "risk": risk,
                }
            )
    stations.sort(key=lambda item: str(item.get("station_id") or ""))
    if stations:
        west = min(float(item["longitude"]) for item in stations)
        east = max(float(item["longitude"]) for item in stations)
        south = min(float(item["latitude"]) for item in stations)
        north = max(float(item["latitude"]) for item in stations)
        valid_means = [float(item["mean_sm"]) for item in stations if item.get("mean_sm") is not None]
        center = [(west + east) / 2, (south + north) / 2]
        bounds = [west, south, east, north]
        mean_sm = round(float(mean(valid_means)), 6) if valid_means else None
    else:
        center = [116.18, 41.78]
        bounds = [115.5, 41.5, 116.5, 42.5]
        mean_sm = None
    return {
        "source": path.name,
        "source_name": path.name,
        "preferred_depth": preferred_depth,
        "year": year,
        "count": len(stations),
        "bounds": bounds,
        "center": center,
        "mean_sm": mean_sm,
        "stations": stations,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {key: value for key, value in item.items() if key not in {"longitude", "latitude", "lng", "lat"}},
                    "geometry": {"type": "Point", "coordinates": [item["longitude"], item["latitude"]]},
                }
                for item in stations
            ],
        },
    }
    try:
        with zipfile.ZipFile(path, "r") as archive:
            archive.namelist()
        return True
    except Exception:
        return False


def list_ismn_archives(manager: Any) -> list[dict[str, Any]]:
    archives: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in _candidate_roots(manager):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.zip")):
            if not _is_zip(path):
                continue
            resolved = path.resolve(strict=False)
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            source_kind = "local_library" if "local_library" in key.replace("\\", "/").lower() else "workspace"
            archives.append(
                {
                    "archive_id": _archive_id(resolved),
                    "filename": path.name,
                    "location": _safe_location(manager, resolved),
                    "source_kind": source_kind,
                    "size_bytes": int(path.stat().st_size),
                }
            )
    return archives


def resolve_ismn_archive(manager: Any, archive: str) -> Path | None:
    text = str(archive or "").strip()
    if not text:
        archives = list_ismn_archives(manager)
        if len(archives) == 1:
            text = str(archives[0]["archive_id"])
        else:
            return None
    candidate = Path(text)
    if candidate.exists() and candidate.is_file():
        return candidate
    for item in list_ismn_archives(manager):
        if text in {str(item.get("archive_id") or ""), str(item.get("filename") or ""), str(item.get("location") or "")}:
            for root in _candidate_roots(manager):
                path = root / str(item.get("filename") or "")
                if path.exists():
                    return path
                location_path = Path(getattr(manager, "workdir", "") or ".") / str(item.get("location") or "")
                if location_path.exists():
                    return location_path
    return None


def _station_items(interface: Any) -> list[dict[str, Any]]:
    stations = getattr(interface, "stations", [])
    if isinstance(stations, dict):
        stations = list(stations.values())
    return [dict(item) for item in stations if isinstance(item, dict)]


def _unique_sorted(values: list[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if key in seen or value in (None, ""):
            continue
        seen.add(key)
        output.append(value)
    return sorted(output, key=lambda item: str(item))


def _profile_from_interface(interface: Any) -> dict[str, Any]:
    station_rows = _station_items(interface)
    networks = list(getattr(interface, "networks", []) or [])
    sensors: list[dict[str, Any]] = []
    station_names: list[str] = []
    for station in station_rows:
        station_names.append(str(station.get("station") or station.get("name") or ""))
        if station.get("network"):
            networks.append(station.get("network"))
        for sensor in station.get("sensors") or []:
            if isinstance(sensor, dict):
                sensors.append(sensor)
    variables = _unique_sorted([sensor.get("variable") or sensor.get("name") for sensor in sensors])
    depths: list[dict[str, Any]] = []
    seen_depths: set[tuple[Any, Any]] = set()
    for sensor in sensors:
        key = (sensor.get("depth_from"), sensor.get("depth_to"))
        if key in seen_depths:
            continue
        seen_depths.add(key)
        depths.append({"depth_from": sensor.get("depth_from"), "depth_to": sensor.get("depth_to")})
    starts = [sensor.get("start") for sensor in sensors if sensor.get("start")]
    ends = [sensor.get("end") for sensor in sensors if sensor.get("end")]
    return {
        "networks": _unique_sorted(networks),
        "stations": _unique_sorted(station_names),
        "station_count": len(station_rows),
        "sensor_count": len(sensors),
        "variables": variables,
        "depths": depths,
        "time_range": {"start": min(starts) if starts else "", "end": max(ends) if ends else ""},
    }


def profile_ismn_archive(
    archive_path: str | Path,
    *,
    interface_factory: Callable[[Path], Any] | None = None,
) -> dict[str, Any]:
    path = Path(archive_path)
    if not path.exists():
        return {
            "ok": False,
            "error_code": "ISMN_ARCHIVE_NOT_FOUND",
            "user_message": "The ISMN archive was not found.",
            "next_actions": ["Upload an official ISMN zip archive or place it under local_library/data/ismn."],
        }
    if path.suffix.lower() != ".zip":
        return {
            "ok": False,
            "error_code": "ISMN_ARCHIVE_UNSUPPORTED",
            "user_message": "Only official ISMN zip archives are supported.",
            "next_actions": ["Use the official archive zip downloaded from ISMN."],
        }
    try:
        with zipfile.ZipFile(path, "r") as archive:
            selected = _choose_stm_depth_files(archive.namelist())
        if selected:
            df = ismn_archive_to_observation_dataframe(path, aggregate="none")
            depths = []
            if not df.empty:
                depth_pairs = df[["depth_m"]].drop_duplicates().to_dict(orient="records") if "depth_m" in df else []
                depths = [{"depth_from": item.get("depth_m"), "depth_to": item.get("depth_m")} for item in depth_pairs]
            profile = {
                "networks": sorted([str(item) for item in df.get("network", pd.Series(dtype=str)).dropna().unique()]) if not df.empty else [],
                "stations": sorted([str(item) for item in df.get("station_id", pd.Series(dtype=str)).dropna().unique()]) if not df.empty else [],
                "station_count": int(df["station_id"].nunique()) if not df.empty and "station_id" in df else 0,
                "sensor_count": len(selected),
                "variables": ["soil_moisture"],
                "depths": depths,
                "time_range": {
                    "start": str(df["date_time"].min()) if not df.empty and "date_time" in df else "",
                    "end": str(df["date_time"].max()) if not df.empty and "date_time" in df else "",
                },
            }
            return {"ok": True, "profile": profile, "archive": {"filename": path.name, "archive_id": _archive_id(path)}, "reader": "local_stm_adapter"}
    except Exception:
        pass
    factory = interface_factory
    if factory is None:
        interface_class = load_ismn_interface_class()
        if interface_class is None:
            return {
                "ok": False,
                "error_code": "ISMN_DEPENDENCY_MISSING",
                "user_message": "The optional TUW-GEO ismn package is not installed.",
                "next_actions": ["Install the optional ismn package in the project virtual environment before importing ISMN archives."],
            }
        factory = interface_class
    try:
        interface = factory(path)
        profile = _profile_from_interface(interface)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "ISMN_ARCHIVE_UNSUPPORTED",
            "user_message": "Failed to profile the ISMN archive.",
            "technical_detail": f"{type(exc).__name__}: {exc}",
            "next_actions": ["Confirm the file is an official ISMN archive zip."],
        }
    return {"ok": True, "profile": profile, "archive": {"filename": path.name, "archive_id": _archive_id(path)}}


def import_ismn_soil_moisture_archive(
    manager: Any,
    archive_path: str | Path,
    *,
    output_name: str = "ismn_soil_moisture",
    interface_factory: Callable[[Path], Any] | None = None,
    **filters: Any,
) -> dict[str, Any]:
    profile = profile_ismn_archive(archive_path, interface_factory=interface_factory)
    if not profile.get("ok"):
        return profile
    aggregate = str(filters.get("aggregate") or "daily")
    preferred_depth = str(filters.get("preferred_depth") or filters.get("depth") or "0.050000")
    year = str(filters.get("year") or "")
    try:
        df = ismn_archive_to_observation_dataframe(
            archive_path,
            preferred_depth=preferred_depth,
            year=year,
            aggregate=aggregate,
        )
    except Exception:
        df = pd.DataFrame(columns=["network", "station", "date_time", "soil_moisture", "lon", "lat"])
    dataset_name = manager.put_table(output_name, df)
    target_col = "soil_moisture_mean" if aggregate.strip().lower() == "daily" else "soil_moisture"
    card = build_data_semantic_card(
        dataset_name=dataset_name,
        source_kind="ismn_archive",
        scientific_roles=["soil_moisture_observation", "model_target_candidate", "gcp_calibration_candidate"],
        variables=[{"name": target_col, "standard_name": "soil_moisture", "unit": "m3/m3", "role": "target"}],
        spatial={"has_coordinates": True, "lon_col": "lon", "lat_col": "lat", "crs": "EPSG:4326"},
        temporal={"has_time": True, "time_col": "date_time" if "date_time" in df.columns else "date"},
        quality={"policy": str(filters.get("quality_policy") or "good_or_usable_only")},
        modeling={"can_train_xgboost": True, "can_calibrate_gcp": True, "recommended_target": target_col},
        row_count=int(len(df)),
        lineage={"created_by_tool": "import_ismn_soil_moisture_archive"},
    )
    safe_card = attach_semantic_card_to_dataset(manager, dataset_name, card)
    warnings = []
    if df.empty and profile.get("reader") != "local_stm_adapter":
        warnings.append("ISMN profile was read, but time-series row import requires the optional TUW-GEO ismn reader for this archive layout.")
    return {
        "ok": True,
        "dataset_name": dataset_name,
        "row_count": int(len(df)),
        "target_col": target_col,
        "semantic_card": safe_card,
        "profile": profile.get("profile", {}),
        "warnings": warnings,
    }
