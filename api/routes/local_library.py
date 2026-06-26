from __future__ import annotations

from typing import Any, Callable, Protocol

from fastapi import APIRouter, Query, Request

from api.schemas.local_library import LocalLibraryImportIn
from core.task_outcome_advisor import build_task_outcome, format_task_outcome_markdown


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
        return guard(lambda: local_library().list_items(query=query, category=category, data_type=data_type, include_disabled=include_disabled, include_source_docs=include_source_docs))

    @router.post("/rescan")
    def rescan_local_library():
        return guard(lambda: local_library().rescan())

    @router.post("/import")
    def import_local_library(body: LocalLibraryImportIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            if not body.item_ids:
                raise ValueError("Select at least one local library item.")
            service = scoped_workspace_service(user_id, "")
            messages: list[str] = []
            for item in local_library().resolve_paths(body.item_ids):
                messages.append(service.import_local_library_item(item))
            result = {"ok": True, "count": len(messages), "messages": messages}
            dashboard_data = decorate_dashboard(service, user_id=user_id)
            outcome = build_task_outcome("upload", result, dashboard=dashboard_data)
            return {**result, "dashboard": dashboard_data, "task_outcome": outcome, "outcome_markdown": format_task_outcome_markdown(outcome)}

        return guard(run)

    return router
