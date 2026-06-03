from __future__ import annotations

import math
import re
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import mean
from typing import Any

MISSING_LIMIT = -100.0


@dataclass
class StationPoint:
    station_id: str
    name: str
    longitude: float
    latitude: float
    elevation_m: float | None
    depth_m: float | None
    depth_label: str
    sample_count: int
    mean_sm: float | None
    min_sm: float | None
    max_sm: float | None
    first_time: str
    last_time: str
    source_file: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = self.station_id
        data["lng"] = self.longitude
        data["lat"] = self.latitude
        data["value"] = "--" if self.mean_sm is None else f"{self.mean_sm:.3f} m³/m³"
        if self.mean_sm is None:
            data["risk"] = "unknown"
        elif self.mean_sm < 0.10:
            data["risk"] = "low"
        elif self.mean_sm < 0.18:
            data["risk"] = "mid"
        else:
            data["risk"] = "high"
        return data


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _choose_depth_files(names: list[str], preferred_depth: str = "0.050000") -> list[str]:
    stm = [name for name in names if name.lower().endswith(".stm") and "/" in name]
    if not stm:
        return []
    preferred = [name for name in stm if f"_sm_{preferred_depth}_{preferred_depth}_" in name]
    if preferred:
        return sorted(preferred)
    # Fall back to the shallowest soil moisture files in ISMN naming.
    def depth_key(name: str) -> tuple[float, str]:
        m = re.search(r"_sm_([0-9.]+)_([0-9.]+)_", name)
        if not m:
            return (999.0, name)
        return (float(m.group(1)), name)
    stm.sort(key=depth_key)
    first_depth = depth_key(stm[0])[0]
    return [name for name in stm if abs(depth_key(name)[0] - first_depth) < 1e-9]


def parse_ismn_station_zip(zip_path: str | Path, preferred_depth: str = "0.050000", year: str = "2019") -> dict[str, Any]:
    """Parse an ISMN/SMN-SDR station archive and return station points.

    The uploaded Shandian River archive stores one .stm time series per station and depth.
    Header format example:
        SMN-SDR SMN-SDR L2 41.78007 115.60314 1401.0 0.0500 0.0500 5TM
    Rows example:
        2019/01/01 00:00 0.0699 D01,D03 M
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"站点压缩包不存在：{zip_path}")

    stations: list[StationPoint] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        selected = _choose_depth_files(names, preferred_depth=preferred_depth)
        for name in selected:
            try:
                raw = zf.read(name).decode("utf-8", errors="replace")
            except Exception:
                continue
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            if not lines:
                continue
            header = lines[0].split()
            if len(header) < 9:
                continue
            station_id = header[2]
            lat = _safe_float(header[3])
            lon = _safe_float(header[4])
            elev = _safe_float(header[5])
            depth_from = _safe_float(header[6])
            depth_to = _safe_float(header[7])
            if lat is None or lon is None:
                continue
            values: list[float] = []
            first_time = ""
            last_time = ""
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
                values.append(value)
                stamp = f"{date_part} {time_part}".strip()
                if not first_time:
                    first_time = stamp
                last_time = stamp
            avg = mean(values) if values else None
            station = StationPoint(
                station_id=station_id,
                name=f"站点 {station_id}",
                longitude=float(lon),
                latitude=float(lat),
                elevation_m=elev,
                depth_m=depth_from,
                depth_label=f"{depth_from:.2f} m" if depth_from is not None else "0-5 cm",
                sample_count=len(values),
                mean_sm=round(float(avg), 6) if avg is not None else None,
                min_sm=round(float(min(values)), 6) if values else None,
                max_sm=round(float(max(values)), 6) if values else None,
                first_time=first_time,
                last_time=last_time,
                source_file=name,
            )
            stations.append(station)

    stations.sort(key=lambda s: s.station_id)
    points = [s.to_dict() for s in stations]
    if points:
        west = min(p["longitude"] for p in points)
        east = max(p["longitude"] for p in points)
        south = min(p["latitude"] for p in points)
        north = max(p["latitude"] for p in points)
        valid_means = [p["mean_sm"] for p in points if p.get("mean_sm") is not None]
        center = [(west + east) / 2, (south + north) / 2]
        bounds = [west, south, east, north]
        mean_sm = round(float(mean(valid_means)), 6) if valid_means else None
    else:
        center = [116.18, 41.78]
        bounds = [115.5, 41.5, 116.5, 42.5]
        mean_sm = None
    return {
        "source": str(zip_path),
        "source_name": zip_path.name,
        "preferred_depth": preferred_depth,
        "year": year,
        "count": len(points),
        "bounds": bounds,
        "center": center,
        "mean_sm": mean_sm,
        "stations": points,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {k: v for k, v in p.items() if k not in {"longitude", "latitude", "lng", "lat"}},
                    "geometry": {"type": "Point", "coordinates": [p["longitude"], p["latitude"]]},
                }
                for p in points
            ],
        },
    }


def find_station_archives(*roots: str | Path) -> list[Path]:
    candidates: list[Path] = []
    keywords = ["shandian", "闪电河", "soil", "moisture", "station", "SMN-SDR", "smn-sdr", "2019"]
    for root in roots:
        if not root:
            continue
        base = Path(root)
        if not base.exists():
            continue
        for path in base.rglob("*.zip"):
            name = path.name
            lower = name.lower()
            if not any(k.lower() in lower for k in keywords):
                continue
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    if not any(item.lower().endswith(".stm") for item in zf.namelist()):
                        continue
            except Exception:
                continue
            candidates.append(path)
    # stable order: explicit station archives first, newest later
    def sort_key(path: Path) -> tuple[int, int, float]:
        text = str(path).lower()
        station_hit = ("station" in text) or ("stations" in text) or ("站点" in text)
        shandian_hit = ("shandian" in text) or ("闪电河" in str(path))
        return (0 if station_hit else 1, 0 if shandian_hit else 1, -path.stat().st_mtime)

    seen: set[str] = set()
    unique: list[Path] = []
    for path in sorted(candidates, key=sort_key):
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique
