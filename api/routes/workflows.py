from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request

from api.schemas.workflows import WorkflowIn


def create_workflows_router(
    *,
    require_request_user_if_present: Callable[[Request, str], str],
    scoped_workspace_service: Callable[[str, str], Any],
    workflow_prompt: str | Callable[[], str],
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
                return service.ask(prompt)
            return {"prompt": prompt}

        return guard(run)

    return router
