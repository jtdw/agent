from __future__ import annotations

import math
import zipfile
from pathlib import Path
from typing import Any


SUSPICIOUS_EXTS = {".exe", ".bat", ".cmd", ".ps1", ".sh", ".dll", ".so", ".pyd", ".env", ".sqlite", ".db", ".cookie", ".token"}


def _result(ok: bool, *, error_code: str = "", user_message: str = "", diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    status = "succeeded" if ok else "failed"
    return {
        "ok": ok,
        "status": status,
        "success": ok,
        "error_code": error_code,
        "user_message": user_message,
        "diagnostics": diagnostics or {},
    }


def validate_zip_upload(
    path: str | Path,
    *,
    max_files: int = 500,
    max_total_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024,
    max_compression_ratio: float = 200.0,
) -> dict[str, Any]:
    archive = Path(path)
    if not archive.exists():
        return _result(False, error_code="ZIP_MISSING", user_message="ZIP file does not exist.", diagnostics={"path": archive.name})
    if archive.suffix.lower() != ".zip":
        return _result(False, error_code="ZIP_UNSUPPORTED_TYPE", user_message="Only ZIP archives are accepted.", diagnostics={"suffix": archive.suffix.lower()})
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            infos = zf.infolist()
            if len(infos) > max_files:
                return _result(False, error_code="ZIP_TOO_MANY_FILES", user_message="ZIP contains too many files.", diagnostics={"file_count": len(infos), "max_files": max_files})
            total = 0
            compressed = 0
            suspicious: list[str] = []
            for member in infos:
                name = str(member.filename or "")
                normalized = name.replace("\\", "/")
                if normalized.startswith("/") or ".." in Path(normalized).parts:
                    return _result(False, error_code="ZIP_PATH_TRAVERSAL", user_message="ZIP contains unsafe relative paths.", diagnostics={"member": name})
                mode = member.external_attr >> 16
                if mode & 0o170000 == 0o120000:
                    return _result(False, error_code="ZIP_SYMLINK", user_message="ZIP contains symlinks, which are not allowed.", diagnostics={"member": name})
                suffix = Path(name).suffix.lower()
                if suffix in SUSPICIOUS_EXTS:
                    suspicious.append(name)
                total += int(member.file_size or 0)
                compressed += int(member.compress_size or 0)
            if suspicious:
                return _result(False, error_code="ZIP_SUSPICIOUS_EXTENSION", user_message="ZIP contains unsupported or sensitive file types.", diagnostics={"members": suspicious[:20]})
            if total > max_total_uncompressed_bytes:
                return _result(False, error_code="ZIP_TOO_LARGE", user_message="ZIP uncompressed size is too large.", diagnostics={"uncompressed_bytes": total})
            ratio = float(total) / max(1.0, float(compressed))
            if ratio > max_compression_ratio and total > 1024 * 1024:
                return _result(False, error_code="ZIP_COMPRESSION_BOMB", user_message="ZIP compression ratio is suspiciously high.", diagnostics={"compression_ratio": ratio})
            return _result(True, diagnostics={"file_count": len(infos), "uncompressed_bytes": total, "compression_ratio": ratio})
    except zipfile.BadZipFile:
        return _result(False, error_code="ZIP_CORRUPT", user_message="ZIP file is corrupt or unreadable.")


def validate_raster(path: str | Path) -> dict[str, Any]:
    try:
        import rasterio
        import numpy as np
    except Exception as exc:
        return _result(False, error_code="RASTER_VALIDATOR_UNAVAILABLE", user_message="Raster validation dependencies are unavailable.", diagnostics={"detail": str(exc)})
    raster = Path(path)
    if not raster.exists():
        return _result(False, error_code="RASTER_MISSING", user_message="Raster file does not exist.")
    try:
        with rasterio.open(raster) as src:
            diagnostics = {
                "crs": str(src.crs) if src.crs else "",
                "bounds": tuple(src.bounds),
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "resolution": src.res,
                "nodata": src.nodata,
                "dtypes": list(src.dtypes),
            }
            if not src.crs:
                return _result(False, error_code="RASTER_MISSING_CRS", user_message="Raster has no CRS.", diagnostics=diagnostics)
            if src.width <= 0 or src.height <= 0 or src.count <= 0:
                return _result(False, error_code="RASTER_EMPTY", user_message="Raster has no readable cells or bands.", diagnostics=diagnostics)
            sample = src.read(1, masked=True)
            if sample.size == 0 or bool(np.ma.is_masked(sample) and sample.count() == 0):
                return _result(False, error_code="RASTER_ALL_NODATA", user_message="Raster contains only NoData values.", diagnostics=diagnostics)
            return _result(True, diagnostics=diagnostics)
    except Exception as exc:
        return _result(False, error_code="RASTER_CORRUPT", user_message="Raster file is corrupt or unreadable.", diagnostics={"detail": str(exc)[:300]})


def validate_vector(path: str | Path) -> dict[str, Any]:
    try:
        import geopandas as gpd
    except Exception as exc:
        return _result(False, error_code="VECTOR_VALIDATOR_UNAVAILABLE", user_message="Vector validation dependencies are unavailable.", diagnostics={"detail": str(exc)})
    vector = Path(path)
    if not vector.exists():
        return _result(False, error_code="VECTOR_MISSING", user_message="Vector file does not exist.")
    try:
        gdf = gpd.read_file(vector)
        diagnostics = {
            "feature_count": int(len(gdf)),
            "columns": list(gdf.columns),
            "crs": str(gdf.crs) if gdf.crs else "",
            "bounds": tuple(gdf.total_bounds.tolist()) if not gdf.empty else (),
            "geometry_types": sorted({str(value) for value in gdf.geometry.geom_type.dropna().unique()}) if "geometry" in gdf else [],
        }
        if gdf.empty:
            return _result(False, error_code="VECTOR_EMPTY", user_message="Vector contains no features.", diagnostics=diagnostics)
        if not gdf.crs:
            return _result(False, error_code="VECTOR_MISSING_CRS", user_message="Vector has no CRS.", diagnostics=diagnostics)
        invalid_count = int((~gdf.geometry.is_valid).sum()) if "geometry" in gdf else len(gdf)
        if invalid_count:
            return _result(False, error_code="VECTOR_INVALID_GEOMETRY", user_message="Vector contains invalid geometries.", diagnostics={**diagnostics, "invalid_geometry_count": invalid_count})
        return _result(True, diagnostics=diagnostics)
    except Exception as exc:
        return _result(False, error_code="VECTOR_CORRUPT", user_message="Vector file is corrupt or unreadable.", diagnostics={"detail": str(exc)[:300]})


def validate_table(path: str | Path, *, lon_fields: tuple[str, ...] = ("lon", "lng", "longitude", "经度"), lat_fields: tuple[str, ...] = ("lat", "latitude", "纬度")) -> dict[str, Any]:
    try:
        import pandas as pd
    except Exception as exc:
        return _result(False, error_code="TABLE_VALIDATOR_UNAVAILABLE", user_message="Table validation dependencies are unavailable.", diagnostics={"detail": str(exc)})
    table = Path(path)
    if not table.exists():
        return _result(False, error_code="TABLE_MISSING", user_message="Table file does not exist.")
    try:
        df = pd.read_csv(table, encoding="utf-8-sig") if table.suffix.lower() == ".csv" else pd.read_excel(table)
        columns = [str(col) for col in df.columns]
        lower = {col.lower(): col for col in columns}
        lon = next((lower[field.lower()] for field in lon_fields if field.lower() in lower), "")
        lat = next((lower[field.lower()] for field in lat_fields if field.lower() in lower), "")
        diagnostics = {"row_count": int(len(df)), "columns": columns, "lon_field": lon, "lat_field": lat}
        if df.empty:
            return _result(False, error_code="TABLE_EMPTY", user_message="Table contains no rows.", diagnostics=diagnostics)
        if not lon or not lat:
            return _result(False, error_code="TABLE_COORD_FIELDS_MISSING", user_message="Table is missing longitude/latitude fields.", diagnostics=diagnostics)
        missing_rate = float(df[[lon, lat]].isna().any(axis=1).mean())
        duplicates = int(df.duplicated(subset=[lon, lat]).sum())
        if math.isclose(missing_rate, 1.0):
            return _result(False, error_code="TABLE_COORDS_ALL_MISSING", user_message="All coordinate rows are missing.", diagnostics={**diagnostics, "coordinate_missing_rate": missing_rate})
        return _result(True, diagnostics={**diagnostics, "coordinate_missing_rate": missing_rate, "duplicate_point_count": duplicates})
    except Exception as exc:
        return _result(False, error_code="TABLE_CORRUPT", user_message="Table file is corrupt or unreadable.", diagnostics={"detail": str(exc)[:300]})


def validate_modeling_inputs(*, target_column: str, feature_columns: list[str], row_count: int, min_rows: int = 20) -> dict[str, Any]:
    diagnostics = {"target_column": target_column, "feature_columns": feature_columns, "row_count": row_count, "min_rows": min_rows}
    if not target_column:
        return _result(False, error_code="MODEL_TARGET_MISSING", user_message="Modeling target column is missing.", diagnostics=diagnostics)
    if not feature_columns:
        return _result(False, error_code="MODEL_FEATURES_MISSING", user_message="No modeling feature columns were provided.", diagnostics=diagnostics)
    if int(row_count or 0) < int(min_rows):
        return _result(False, error_code="MODEL_SAMPLE_TOO_SMALL", user_message="Not enough samples for reliable model training.", diagnostics=diagnostics)
    return _result(True, diagnostics=diagnostics)


def validate_output_artifact(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return _result(False, error_code="ARTIFACT_MISSING", user_message="Output artifact does not exist.", diagnostics={"path": target.name})
    if target.is_file() and target.stat().st_size <= 0:
        return _result(False, error_code="ARTIFACT_EMPTY", user_message="Output artifact is empty.", diagnostics={"path": target.name})
    suffix = target.suffix.lower()
    if suffix in {".tif", ".tiff", ".img"}:
        return validate_raster(target)
    if suffix in {".shp", ".geojson", ".gpkg", ".json", ".kml"}:
        return validate_vector(target)
    if suffix in {".csv", ".xlsx", ".xls"}:
        table_result = validate_table(target)
        if table_result["ok"] or table_result["error_code"] == "TABLE_COORD_FIELDS_MISSING":
            # Non-point output tables are still valid artifacts if they can be read.
            return _result(True, diagnostics=table_result.get("diagnostics", {}))
        return table_result
    return _result(True, diagnostics={"path": target.name, "size_bytes": target.stat().st_size if target.is_file() else 0})
