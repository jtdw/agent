from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request

from api.schemas.data_sources import GSCloudLoginCompleteIn, GSCloudLoginStartIn
from services.data_sources.gscloud_accounts import GSCloudAccountService


def create_data_sources_router(
    *,
    account_service: Callable[[], GSCloudAccountService],
    authenticated_user: Callable[[Request], str],
    audit: Callable[..., Any],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/data-sources", tags=["data-sources"])

    @router.get("/gscloud/status")
    def gscloud_account_status(request: Request):
        return guard(lambda: account_service().status(authenticated_user(request)))

    @router.post("/gscloud/login/start")
    def gscloud_login_start(body: GSCloudLoginStartIn, request: Request):
        def run():
            user_id = authenticated_user(request)
            result = account_service().start_login(user_id, timeout_seconds=body.timeout_seconds)
            audit(request, user_id=user_id, action="data_source.login_start", resource_type="data_source", resource_id="gscloud")
            return result

        return guard(run)

    @router.post("/gscloud/login/complete")
    def gscloud_login_complete(body: GSCloudLoginCompleteIn, request: Request):
        def run():
            user_id = authenticated_user(request)
            result = account_service().complete_login(user_id, body.login_session_id)
            if result.get("logged_in"):
                audit(request, user_id=user_id, action="data_source.login_complete", resource_type="data_source", resource_id="gscloud")
            return result

        return guard(run)

    @router.delete("/gscloud/logout")
    def gscloud_account_logout(request: Request):
        def run():
            user_id = authenticated_user(request)
            result = account_service().logout(user_id)
            audit(request, user_id=user_id, action="data_source.logout", resource_type="data_source", resource_id="gscloud")
            return result

        return guard(run)

    return router
