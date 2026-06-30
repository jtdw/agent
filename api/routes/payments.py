from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import APIRouter, Request

from api.schemas.payments import PaymentIn


_PRIVATE_PAYMENT_KEYS = {
    "path",
    "debug_path",
    "db_path",
    "state_path",
    "storage_state_path",
    "status_path",
    "log_path",
    "absolute_path",
    "relative_path",
    "download_url",
    "url",
    "password",
    "password_hash",
    "token",
    "token_hash",
    "session_token",
    "cookie",
    "cookies",
    "encrypted_username",
    "encrypted_password",
    "encrypted_cookie",
    "secret",
    "secret_key",
    "secret_key_source",
}
_PRIVATE_PAYMENT_TEXT_RE = re.compile(
    r"(?:/(?:tmp|home|var|etc|root|Users)/|workspace[\\/](?:users|sessions))",
    re.IGNORECASE,
)


def _public_payment_payload(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _PRIVATE_PAYMENT_KEYS:
                continue
            cleaned = _public_payment_payload(item)
            if cleaned in ({}, [], ""):
                continue
            output[key_text] = cleaned
        return output
    if isinstance(value, list):
        output = [_public_payment_payload(item) for item in value]
        return [item for item in output if item not in ({}, [], "")]
    if isinstance(value, str):
        lowered = value.lower()
        if (
            ":/" in value
            or ":\\" in value
            or "storage_state" in lowered
            or "/api/downloads/artifact" in lowered
            or "/api/files/artifact" in lowered
            or _PRIVATE_PAYMENT_TEXT_RE.search(value)
        ):
            return ""
    return value


def create_payments_router(
    *,
    commercial_service: Callable[[], Any],
    require_payment_user: Callable[[Request, str], str],
    plan_presets: dict[str, dict[str, Any]],
    audit: Callable[..., Any],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/payments/simulate")
    def simulate_payment(body: PaymentIn, request: Request):
        def run():
            user_id = require_payment_user(request, body.user_id)
            preset = plan_presets.get(body.plan, plan_presets["pro"])
            amount = int(preset.get("price_cents", 2000)) if "price_cents" in preset else {"basic": 900, "pro": 2000, "team": 5900}.get(body.plan, 2000)
            result = commercial_service().simulate_payment(
                user_id=user_id,
                plan=body.plan,
                amount_cents=amount,
                platform_quota=int(preset.get("platform_monthly_quota", 30)),
                days=int(preset.get("days", 30)),
                note="Web 前端模拟支付",
            )
            audit(
                request,
                user_id=user_id,
                action="payment.simulate",
                resource_type="payment",
                resource_id=str((result.get("payment") or {}).get("payment_id") or ""),
                detail={"plan": body.plan},
            )
            return _public_payment_payload(result)

        return guard(run)

    return router
