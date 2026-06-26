from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request

from api.schemas.payments import PaymentIn


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
            return result

        return guard(run)

    return router
