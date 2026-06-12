from __future__ import annotations

import hmac
from typing import Any, Protocol


class SessionValidator(Protocol):
    def validate_session(self, session_id: str, session_token: str) -> dict[str, Any]:
        ...


def require_authenticated_user(
    service: SessionValidator,
    *,
    requested_user_id: str,
    session_id: str,
    session_token: str,
) -> str:
    user_id = str(requested_user_id or "").strip()
    if not user_id:
        raise PermissionError("请先登录账号。")
    if not str(session_id or "").strip() or not str(session_token or "").strip():
        raise PermissionError("缺少登录凭据，请重新登录。")
    payload = service.validate_session(session_id, session_token)
    user = payload.get("user") if isinstance(payload, dict) else None
    actual = str((user or {}).get("user_id") or "").strip()
    if not actual or actual != user_id:
        raise PermissionError("无权访问其他用户的数据或任务。")
    return actual


def optional_authenticated_session(service: SessionValidator, *, session_id: str, session_token: str) -> dict[str, Any]:
    if not str(session_id or "").strip() or not str(session_token or "").strip():
        return {"authenticated": False, "user": None}
    try:
        payload = service.validate_session(session_id, session_token)
    except PermissionError:
        return {"authenticated": False, "user": None}
    if not isinstance(payload, dict):
        return {"authenticated": False, "user": None}
    return {"authenticated": True, **payload}


def require_admin_token(configured_token: str, provided_token: str) -> bool:
    expected = str(configured_token or "").strip()
    actual = str(provided_token or "").strip()
    if not expected:
        raise PermissionError("管理员接口未配置 GIS_AGENT_ADMIN_TOKEN，已拒绝执行。")
    if not actual or not hmac.compare_digest(expected, actual):
        raise PermissionError("管理员令牌无效。")
    return True


def require_resource_owner(resource: dict[str, Any], *, user_id: str, resource_name: str = "resource") -> dict[str, Any]:
    owner = str((resource or {}).get("user_id") or "").strip()
    actual = str(user_id or "").strip()
    if not owner or not actual or owner != actual:
        raise PermissionError(f"access denied for {resource_name}")
    return resource
