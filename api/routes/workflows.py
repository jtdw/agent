from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request

from api.schemas.workflows import WorkflowIn
from core.response_quality import validate_response_before_send


def create_workflows_router(
    *,
    require_request_user_if_present: Callable[[Request, str], str],
    scoped_workspace_service: Callable[[str, str], Any],
    workflow_prompt: str | Callable[[], str],
    attach_chat_state: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
    attach_result_panel: Callable[[Any, str, dict[str, Any]], dict[str, Any]] | None = None,
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/workflows/shandian-soil-moisture")
    def shandian_soil_moisture_workflow(body: WorkflowIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            prompt = workflow_prompt() if callable(workflow_prompt) else workflow_prompt
            if body.run_now:
                service = scoped_workspace_service(user_id, body.session_id)
                result = service.ask(prompt)
                if attach_chat_state is not None:
                    result = attach_chat_state(service, result)
                if attach_result_panel is not None:
                    result = attach_result_panel(service, user_id, result)
                session_id = body.session_id or str(getattr(service, "current_session_id", "") or "")
                return validate_response_before_send(result, user_id=user_id, session_id=session_id)
            return {"prompt": prompt}

        return guard(run)

    return router
