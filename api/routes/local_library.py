from __future__ import annotations

import re
from typing import Any, Callable, Protocol

from fastapi import APIRouter, Query, Request

from api.schemas.local_library import LocalLibraryImportIn
from core.task_outcome_advisor import build_task_outcome, format_task_outcome_markdown


_PRIVATE_LIBRARY_KEYS = {"path", "absolute_path", "root", "data_dir", "manifest_path"}
_PRIVATE_LIBRARY_TEXT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:tmp|home|var|etc|root|Users)/|workspace[\\/](?:users|sessions)|/api/(?:files/artifact|downloads/artifact)\?)",
    re.IGNORECASE,
)
_PRIVATE_LIBRARY_MESSAGE_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s`'\"，。；;]+|/(?:tmp|home|var|etc|root|Users)/[^\s`'\"，。；;]+|workspace[\\/](?:users|sessions)[^\s`'\"，。；;]*|/api/(?:files/artifact|downloads/artifact)\?[^\s`'\"，。；;]+)",
    re.IGNORECASE,
)


def _public_library_message_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _PRIVATE_LIBRARY_MESSAGE_RE.sub("[已隐藏内部路径]", text)


def _public_library_value(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if str(key) in _PRIVATE_LIBRARY_KEYS:
                continue
            cleaned = _public_library_value(item)
            if cleaned in ({}, [], ""):
                continue
            clean[str(key)] = cleaned
        return clean
    if isinstance(value, list):
        output = [_public_library_value(item) for item in value]
        return [item for item in output if item not in ({}, [], "")]
    if isinstance(value, str):
        return "" if _PRIVATE_LIBRARY_TEXT_RE.search(value) else value
    return value


def _public_local_library_item(item: dict[str, Any]) -> dict[str, Any]:
    public = _public_library_value(dict(item))
    if not isinstance(public, dict):
        public = {}
    raw_path = str(item.get("path") or item.get("absolute_path") or "")
    basename = raw_path.replace("\\", "/").rsplit("/", 1)[-1] if raw_path else ""
    filename = str(item.get("filename") or basename or item.get("name") or "")
    if filename:
        public["filename"] = filename
    return public


def _public_local_library_response(data: Any) -> Any:
    if isinstance(data, list):
        return [_public_local_library_item(item) for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return data
    public = _public_library_value(dict(data))
    if not isinstance(public, dict):
        public = {}
    items = data.get("items")
    if isinstance(items, list):
        public["items"] = [_public_local_library_item(item) for item in items if isinstance(item, dict)]
    return public


class LocalLibraryService(Protocol):
    def list_items(self, **kwargs: Any) -> list[dict[str, Any]]: ...

    def rescan(self) -> dict[str, Any]: ...

    def resolve_paths(self, item_ids: list[str]) -> list[Any]: ...


def create_local_library_router(
    *,
    local_library: Callable[[], LocalLibraryService],
    scoped_workspace_service: Callable[[str, str], Any],
    require_request_user_if_present: Callable[[Request, str], str],
    decorate_dashboard: Callable[..., dict[str, Any]],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/local-library", tags=["local-library"])

    @router.get("")
    def list_local_library(
        query: str = Query(default=""),
        category: str = Query(default=""),
        data_type: str = Query(default=""),
        include_disabled: bool = Query(default=False),
        include_source_docs: bool = Query(default=False),
    ):
        return guard(lambda: _public_local_library_response(local_library().list_items(query=query, category=category, data_type=data_type, include_disabled=include_disabled, include_source_docs=include_source_docs)))

    @router.post("/rescan")
    def rescan_local_library():
        return guard(lambda: _public_local_library_response(local_library().rescan()))

    @router.post("/import")
    def import_local_library(body: LocalLibraryImportIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            if not body.item_ids:
                raise ValueError("Select at least one local library item.")
            service = scoped_workspace_service(user_id, body.session_id)
            messages: list[str] = []
            for item in local_library().resolve_paths(body.item_ids):
                messages.append(_public_library_message_text(service.import_local_library_item(item)))
            result = {"ok": True, "count": len(messages), "messages": messages}
            dashboard_data = decorate_dashboard(service, user_id=user_id)
            outcome = build_task_outcome("upload", result, dashboard=dashboard_data)
            return {**result, "dashboard": dashboard_data, "task_outcome": outcome, "outcome_markdown": format_task_outcome_markdown(outcome)}

        return guard(run)

    return router
