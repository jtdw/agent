from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from domain.artifacts.models import artifact_download_url


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


def relative_shared_download_url(base_workdir: str | Path, file_path: str | Path, user_id: str = "", job_id: str = "", session_id: str = "") -> str:
    path = Path(file_path or "").resolve()
    if not path.exists() or not path.is_file():
        return ""
    root = Path(base_workdir).resolve()
    try:
        rel = path.relative_to(root)
    except Exception:
        return ""
    rel_url_path = str(rel).replace("\\", "/")
    params = {"user_id": safe_key(user_id), "job_id": job_id, "path": rel_url_path}
    if str(session_id or "").strip():
        params["session_id"] = str(session_id).strip()
    return f"/api/downloads/artifact?{urlencode(params)}"


def build_result_panel(response: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any]:
    outcome = response.get("task_outcome") if isinstance(response.get("task_outcome"), dict) else {}
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    user_result = response.get("user_facing_result") if isinstance(response.get("user_facing_result"), dict) else {}

    def append_file(item: dict[str, Any]) -> None:
        artifact_id = str(item.get("artifact_id") or item.get("id") or "")
        url = artifact_download_url(artifact_id) if artifact_id else str(item.get("download_url") or "")
        if not artifact_id and url.startswith("/api/files/artifact?"):
            return
        label = str(item.get("title") or item.get("label") or item.get("filename") or item.get("name") or "result file")
        key = artifact_id or url or label
        if not key or key in seen:
            return
        seen.add(key)
        files.append(
            {
                "artifact_id": artifact_id,
                "label": label,
                "path": str(item.get("filename") or label),
                "download_url": url,
                "kind": str(item.get("artifact_type") or item.get("kind") or item.get("type") or "artifact"),
            }
        )

    if user_result:
        for item in user_result.get("primary_artifacts", []) if isinstance(user_result.get("primary_artifacts"), list) else []:
            if isinstance(item, dict):
                append_file(item)
        for group in user_result.get("grouped_artifacts", []) if isinstance(user_result.get("grouped_artifacts"), list) else []:
            if not isinstance(group, dict):
                continue
            for item in group.get("artifacts", []) if isinstance(group.get("artifacts"), list) else []:
                if isinstance(item, dict):
                    append_file(item)

    dashboard_sources: list[dict[str, Any]] = []
    for result in dashboard.get("model_results", []) if isinstance(dashboard.get("model_results"), list) else []:
        if isinstance(result, dict):
            dashboard_sources.extend([item for item in result.get("artifacts", []) if isinstance(item, dict)])
    dashboard_sources.extend([item for item in dashboard.get("artifacts", []) if isinstance(item, dict)] if isinstance(dashboard.get("artifacts"), list) else [])
    by_id = {str(item.get("artifact_id") or item.get("id") or ""): item for item in dashboard_sources if str(item.get("artifact_id") or item.get("id") or "")}
    by_path = {str(item.get("path") or item.get("display_path") or ""): item for item in dashboard_sources if str(item.get("path") or item.get("display_path") or "")}
    response_sources = [
        item
        for key in ("artifacts", "files")
        for item in (response.get(key) if isinstance(response.get(key), list) else [])
        if isinstance(item, dict)
    ]
    sources = [*response_sources, *dashboard_sources]
    for item in sources:
        artifact_id = str(item.get("artifact_id") or item.get("id") or "")
        path = str(item.get("path") or item.get("display_path") or "")
        match = by_id.get(artifact_id) or by_path.get(path) or {}
        merged = {**match, **item, "download_url": str(item.get("download_url") or match.get("download_url") or "")}
        append_file(merged)
    return {
        "has_results": bool(outcome.get("has_results") or files),
        "title": str(outcome.get("summary") or "Processing results"),
        "files": files[:20],
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
_build_result_panel = build_result_panel
_download_requires_login_result = download_requires_login_result
