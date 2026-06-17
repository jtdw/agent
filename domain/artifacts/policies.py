from __future__ import annotations

import mimetypes
import re
import zipfile
from pathlib import Path


SENSITIVE_EXACT_NAMES = {".env", "workspace.db", "cookies.json", "cookie.json", "storage_state.json"}
SENSITIVE_EXTS = {".db", ".sqlite", ".sqlite3", ".ini", ".toml", ".cfg", ".conf", ".yaml", ".yml"}
SENSITIVE_MARKERS = ("secret", "secrets", "token", "cookie", "storage_state")
SHAPE_SIDE_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix"}


def safe_download_filename(filename: str) -> str:
    clean = Path(str(filename or "artifact").replace("\x00", "")).name.strip()
    clean = re.sub(r"[\r\n]+", "", clean)
    clean = re.sub(r'[<>:"/\\|?*]+', "_", clean).strip(" .")
    return clean[:160] or "artifact"


def artifact_mime_type(path: str | Path, artifact_type: str = "") -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    if suffix == ".geojson":
        return "application/geo+json"
    if suffix == ".json":
        return "application/json"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".zip" or str(artifact_type or "").lower() in {"shapefile", "shp_zip"}:
        return "application/zip"
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def assert_artifact_path_allowed(workdir: str | Path, path: str | Path) -> Path:
    root = Path(workdir).resolve()
    target = Path(path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError("Artifact is outside the current workspace.") from exc

    lowered_parts = [part.lower() for part in target.parts]
    name = target.name.lower()
    if name in SENSITIVE_EXACT_NAMES or target.suffix.lower() in SENSITIVE_EXTS:
        raise PermissionError("Artifact type is not allowed for download.")
    if any(marker in part for part in lowered_parts for marker in SENSITIVE_MARKERS):
        raise PermissionError("Artifact path contains sensitive material.")
    return target


def shapefile_zip_path(workdir: str | Path, shp_path: str | Path, artifact_id: str) -> Path:
    shp = assert_artifact_path_allowed(workdir, shp_path)
    if shp.suffix.lower() != ".shp":
        return shp
    if not shp.exists():
        raise FileNotFoundError(f"Artifact file does not exist: {shp.name}")
    temp_dir = Path(workdir).resolve() / "temp" / "artifact_downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = temp_dir / safe_download_filename(f"{Path(shp).stem}.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for sidecar in sorted(shp.parent.glob(f"{shp.stem}.*")):
            if sidecar.suffix.lower() in SHAPE_SIDE_EXTS and sidecar.is_file():
                archive.write(sidecar, arcname=sidecar.name)
    return zip_path
