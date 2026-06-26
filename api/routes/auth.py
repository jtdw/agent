from __future__ import annotations

from typing import Any, Callable, Protocol

from fastapi import APIRouter, Request, Response

from api.schemas.auth import AuthIn, ValidateIn


class CommercialAuthService(Protocol):
    def register_user(self, email: str, password: str, *, plan: str) -> dict[str, Any]: ...

    def authenticate_user(self, email: str, password: str) -> dict[str, Any]: ...

    def validate_session(self, session_id: str, session_token: str) -> dict[str, Any]: ...


def create_auth_router(
    *,
    commercial_service: Callable[[], CommercialAuthService],
    set_session_cookies: Callable[[Response, dict[str, Any]], None],
    clear_session_cookies: Callable[[Response], None],
    request_session: Callable[[Request], tuple[str, str]],
    optional_authenticated_session: Callable[..., dict[str, Any]],
    audit: Callable[..., Any],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/login")
    def login(body: AuthIn, response: Response, request: Request):
        def run():
            session = commercial_service().authenticate_user(str(body.email), body.password)
            set_session_cookies(response, session)
            user_id = str(session["user"].get("user_id") or "")
            audit(request, user_id=user_id, action="auth.login", resource_type="user", resource_id=user_id)
            return {"user": session["user"], "expires_at": session.get("expires_at")}

        return guard(run)

    @router.post("/register")
    def register(body: AuthIn, response: Response, request: Request):
        def run():
            commercial_service().register_user(str(body.email), body.password, plan="basic")
            session = commercial_service().authenticate_user(str(body.email), body.password)
            set_session_cookies(response, session)
            user_id = str(session["user"].get("user_id") or "")
            audit(request, user_id=user_id, action="auth.register", resource_type="user", resource_id=user_id)
            return {"user": session["user"], "expires_at": session.get("expires_at")}

        return guard(run)

    @router.post("/validate")
    def validate(body: ValidateIn):
        return guard(lambda: commercial_service().validate_session(body.session_id, body.session_token))

    @router.get("/me")
    def me(request: Request):
        def run():
            session_id, session_token = request_session(request)
            return optional_authenticated_session(commercial_service(), session_id=session_id, session_token=session_token)

        return guard(run)

    @router.post("/logout")
    def logout(response: Response, request: Request):
        clear_session_cookies(response)
        audit(request, action="auth.logout")
        return {"ok": True}

    return router
