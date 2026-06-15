from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .policies import artifact_mime_type, assert_artifact_path_allowed, safe_download_filename


def artifact_download_url(artifact_id: str, user_id: str = "") -> str:
    clean_id = str(artifact_id or "").strip()
    if not clean_id:
        return ""
    url = f"/api/artifacts/{clean_id}/download"
    return f"{url}?{urlencode({'user_id': str(user_id).strip()})}" if str(user_id or "").strip() else url


def artifact_meta_url(artifact_id: str, user_id: str = "") -> str:
    clean_id = str(artifact_id or "").strip()
    if not clean_id:
        return ""
    url = f"/api/artifacts/{clean_id}"
    return f"{url}?{urlencode({'user_id': str(user_id).strip()})}" if str(user_id or "").strip() else url


def public_artifact_payload(artifact: dict[str, Any], *, workdir: str | Path, user_id: str = "") -> dict[str, Any]:
    path = assert_artifact_path_allowed(workdir, str(artifact.get("path") or ""))
    artifact_id = str(artifact.get("artifact_id") or "")
    artifact_type = str(artifact.get("type") or artifact.get("category") or "artifact")
    filename = safe_download_filename(str(artifact.get("title") or artifact.get("name") or path.name))
    if path.suffix.lower() == ".shp":
        filename = safe_download_filename(f"{path.stem}.zip")
        artifact_type = "shp_zip"
    stat = path.stat() if path.exists() and path.is_file() else None
    size_bytes = int(stat.st_size) if stat else int(float(artifact.get("size_bytes") or 0))
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    return {
        "artifact_id": artifact_id,
        "filename": filename,
        "name": filename,
        "title": str(artifact.get("title") or filename),
        "type": artifact_type,
        "kind": artifact_type,
        "display_path": str(artifact.get("display_path") or path.name),
        "size_bytes": size_bytes,
        "size_kb": round(size_bytes / 1024, 2),
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
