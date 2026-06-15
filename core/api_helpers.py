from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


SESSION_COOKIE_ID = "gis_agent_session_id"
SESSION_COOKIE_TOKEN = "gis_agent_session_token"


def safe_key(value: str | None) -> str:
    raw = (value or "anonymous").strip() or "anonymous"
    return re.sub(r"[^A-Za-z0-9_.@-]+", "_", raw)[:96]


def cors_origins(raw_extra: str | None = None) -> list[str]:
    defaults = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]
    extra_raw = os.getenv("GIS_AGENT_CORS_ORIGINS", "") if raw_extra is None else raw_extra
    extra = [item.strip() for item in str(extra_raw or "").split(",") if item.strip()]
    return list(dict.fromkeys([*defaults, *extra]))


def request_session(request: Any) -> tuple[str, str]:
    headers = getattr(request, "headers", {}) or {}
    cookies = getattr(request, "cookies", {}) or {}
    return (
        str(headers.get("x-session-id") or cookies.get(SESSION_COOKIE_ID) or "").strip(),
        str(headers.get("x-session-token") or cookies.get(SESSION_COOKIE_TOKEN) or "").strip(),
    )


def request_admin_token(request: Any) -> str:
    headers = getattr(request, "headers", {}) or {}
    value = str(headers.get("x-admin-token") or "").strip()
    if value:
        return value
    auth = str(headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


def relative_artifact_url(artifact_id: str, user_id: str = "") -> str:
    clean_id = str(artifact_id or "").strip()
    if not clean_id:
        return ""
    url = f"/api/artifacts/{clean_id}/download"
    if str(user_id or "").strip():
        url = f"{url}?{urlencode({'user_id': safe_key(user_id)})}"
    return url


def relative_shared_download_url(base_workdir: str | Path, file_path: str | Path, user_id: str = "", job_id: str = "") -> str:
    from .artifacts import assert_artifact_path_allowed

    path = Path(file_path or "").resolve()
    if not path.exists() or not path.is_file():
        return ""
    root = Path(base_workdir).resolve()
    try:
        assert_artifact_path_allowed(root, path)
    except (PermissionError, ValueError):
        return ""
    try:
        rel = path.relative_to(root)
    except Exception:
        return ""
    rel_url_path = str(rel).replace("\\", "/")
    return f"/api/downloads/artifact?{urlencode({'user_id': safe_key(user_id), 'job_id': job_id, 'path': rel_url_path})}"


def build_workspace_mentions(datasets: list[Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for raw in datasets or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        columns = meta.get("columns") if isinstance(meta.get("columns"), list) else []
        path = Path(str(raw.get("path") or ""))
        items.append(
            {
                "id": name,
                "name": name,
                "mention": f"@{{{name}}}",
                "type": str(raw.get("type") or raw.get("data_type") or "file"),
                "filename": path.name if path.name else name,
                "row_count": meta.get("rows") if meta.get("rows") is not None else raw.get("row_count"),
                "column_count": len(columns) if columns else None,
                "crs": str(meta.get("crs") or ""),
            }
        )
    return {"items": items, "count": len(items)}


def build_result_panel(response: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any]:
    outcome = response.get("task_outcome") if isinstance(response.get("task_outcome"), dict) else {}
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for result in dashboard.get("model_results", []) if isinstance(dashboard.get("model_results"), list) else []:
        if isinstance(result, dict):
            sources.extend([item for item in result.get("artifacts", []) if isinstance(item, dict)])
    sources.extend([item for item in dashboard.get("artifacts", []) if isinstance(item, dict)] if isinstance(dashboard.get("artifacts"), list) else [])
    for item in sources:
        path = str(item.get("path") or item.get("display_path") or "")
        url = str(item.get("download_url") or "")
        key = url or path
        if not key or key in seen:
            continue
        seen.add(key)
        files.append(
            {
                "artifact_id": str(item.get("artifact_id") or item.get("id") or ""),
                "label": str(item.get("label") or item.get("name") or Path(path).name or "result file"),
                "path": path,
                "download_url": url,
                "kind": str(item.get("category") or item.get("type") or "artifact"),
            }
        )
    return {
        "has_results": bool(outcome.get("has_results") or files),
        "title": str(outcome.get("summary") or "Processing results"),
        "files": files[:12],
        "result_paths": outcome.get("result_paths") if isinstance(outcome.get("result_paths"), list) else [],
        "recommendations": outcome.get("recommendations") if isinstance(outcome.get("recommendations"), list) else [],
    }


def download_requires_login_result(prompt: str) -> dict[str, str]:
    request = str(prompt or "").strip()
    return {
        "reply": (
            "这个请求需要有效的数据源登录态后才能继续下载。"
            "请先登录或更新 Cookie/storage state，然后重新提交同一句请求。"
            f"\n\nDetected request: {request or 'download data'}"
        ),
        "model": "direct-router",
        "reason": "download_requires_login",
    }


_safe_key = safe_key
_cors_origins = cors_origins
_request_session = request_session
_request_admin_token = request_admin_token
_build_workspace_mentions = build_workspace_mentions
_build_result_panel = build_result_panel
_download_requires_login_result = download_requires_login_result
