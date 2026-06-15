from __future__ import annotations

import mimetypes
import re
import zipfile
from pathlib import Path
from typing import Any


SENSITIVE_EXACT_NAMES = {
    ".env",
    "workspace.db",
    "cookies.json",
    "cookie.json",
    "storage_state.json",
}
SENSITIVE_EXTS = {".db", ".sqlite", ".sqlite3", ".ini", ".toml", ".cfg", ".conf", ".yaml", ".yml"}
SENSITIVE_MARKERS = ("secret", "secrets", "token", "cookie", "storage_state")
SHAPE_SIDE_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix"}


def artifact_download_url(artifact_id: str, user_id: str = "") -> str:
    clean_id = str(artifact_id or "").strip()
    if not clean_id:
        return ""
    url = f"/api/artifacts/{clean_id}/download"
    if str(user_id or "").strip():
        from urllib.parse import urlencode

        url = f"{url}?{urlencode({'user_id': str(user_id).strip()})}"
    return url


def artifact_meta_url(artifact_id: str, user_id: str = "") -> str:
    clean_id = str(artifact_id or "").strip()
    if not clean_id:
        return ""
    url = f"/api/artifacts/{clean_id}"
    if str(user_id or "").strip():
        from urllib.parse import urlencode

        url = f"{url}?{urlencode({'user_id': str(user_id).strip()})}"
    return url


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


def public_artifact_payload(artifact: dict[str, Any], *, workdir: str | Path, user_id: str = "") -> dict[str, Any]:
    path = assert_artifact_path_allowed(workdir, str(artifact.get("path") or ""))
    artifact_id = str(artifact.get("artifact_id") or "")
    artifact_type = str(artifact.get("type") or artifact.get("category") or "artifact")
    filename = safe_download_filename(str(artifact.get("title") or artifact.get("name") or path.name))
    if path.suffix.lower() == ".shp":
        filename = safe_download_filename(f"{path.stem}.zip")
        artifact_type = "shp_zip"
    stat = path.stat() if path.exists() and path.is_file() else None
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    return {
        "artifact_id": artifact_id,
        "filename": filename,
        "name": filename,
        "title": str(artifact.get("title") or filename),
        "type": artifact_type,
        "kind": artifact_type,
        "display_path": str(artifact.get("display_path") or path.name),
        "size_bytes": int(stat.st_size) if stat else int(float(artifact.get("size_bytes") or 0)),
        "size_kb": round((int(stat.st_size) if stat else int(float(artifact.get("size_bytes") or 0))) / 1024, 2),
        "mime_type": artifact_mime_type(filename, artifact_type),
        "created_at": str(artifact.get("created_at") or artifact.get("modified") or ""),
        "updated_at": str(artifact.get("updated_at") or artifact.get("modified") or ""),
        "source": {
            "tool_name": str(meta.get("tool_name") or artifact.get("tool_name") or ""),
            "workflow_id": str(meta.get("workflow_id") or artifact.get("workflow_id") or ""),
            "message_id": str(meta.get("message_id") or artifact.get("message_id") or ""),
        },
        "preview_available": bool(artifact.get("preview_available")),
        "download_url": artifact_download_url(artifact_id, user_id=user_id),
        "metadata_url": artifact_meta_url(artifact_id, user_id=user_id),
    }
