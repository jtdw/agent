from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4


PENDING_CONFIRMATION_STORE_KEY = "pending_confirmations:v1"
CONFIRMATION_STATUSES = {"awaiting_confirmation", "confirmed", "cancelled", "expired", "consumed"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat() + "Z"


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(_safe_json(plan).encode("utf-8")).hexdigest()


def _load(database: Any) -> list[dict[str, Any]]:
    raw = ""
    try:
        raw = database._get_state(PENDING_CONFIRMATION_STORE_KEY) or ""
    except Exception:
        raw = ""
    try:
        data = json.loads(raw) if raw else []
    except Exception:
        data = []
    return [item for item in data if isinstance(item, dict)]


def _save(database: Any, records: list[dict[str, Any]]) -> None:
    database._set_state(PENDING_CONFIRMATION_STORE_KEY, json.dumps(records, ensure_ascii=False, default=str))


def _record_matches(record: dict[str, Any], *, user_id: str, session_id: str, conversation_id: str) -> bool:
    return (
        str(record.get("user_id") or "") == str(user_id or "")
        and str(record.get("session_id") or "") == str(session_id or "")
        and str(record.get("conversation_id") or "") == str(conversation_id or "")
    )


def _mark_expired(record: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = now or _now()
    expires_at = _parse_iso(record.get("expires_at"))
    if str(record.get("status") or "") == "awaiting_confirmation" and expires_at and expires_at <= current:
        record = dict(record)
        record["status"] = "expired"
        record["updated_at"] = _iso(current)
    return record


def extract_confirmation_id(prompt: str) -> str:
    match = re.search(r"\b(?:confirmation_id|confirmed_action_id)\s*=\s*([A-Za-z0-9_.:-]+)", str(prompt or ""))
    return match.group(1) if match else ""


def is_confirmation_message(prompt: str) -> bool:
    text = re.sub(r"\b(?:confirmation_id|confirmed_action_id)\s*=\s*[A-Za-z0-9_.:-]+", " ", str(prompt or "")).strip().lower()
    compact = re.sub(r"\s+", "", text)
    return compact in {"继续", "确认", "开始", "开始下载", "继续下载", "可以", "执行", "确认下载", "proceed", "continue", "confirm", "start"}


def is_plan_modification_message(prompt: str) -> bool:
    text = str(prompt or "")
    return any(token in text for token in ("改为", "改成", "换成", "不要", "取消", "90m", "90米", "30m", "30米")) and not is_confirmation_message(text)


def create_pending_confirmation(
    database: Any,
    *,
    user_id: str,
    session_id: str,
    conversation_id: str,
    plan: dict[str, Any],
    reason: str,
    ttl_minutes: int = 60,
) -> dict[str, Any]:
    now = _now()
    records = [_mark_expired(item, now) for item in _load(database)]
    plan_id = str(plan.get("plan_id") or plan.get("id") or "plan_" + plan_hash(plan)[:16])
    requests = _as_list(plan.get("download_requests")) or _as_list(plan.get("requested_downloads"))
    stable = {
        "user_id": user_id,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "plan_hash": plan_hash(plan),
        "requested_downloads": requests,
    }
    idempotency_key = "confirm:" + hashlib.sha256(_safe_json(stable).encode("utf-8")).hexdigest()
    for item in records:
        if (
            _record_matches(item, user_id=user_id, session_id=session_id, conversation_id=conversation_id)
            and str(item.get("status") or "") == "awaiting_confirmation"
            and str(item.get("idempotency_key") or "") == idempotency_key
        ):
            return item
    record = {
        "confirmation_id": "pc_" + uuid4().hex,
        "user_id": str(user_id or ""),
        "session_id": str(session_id or ""),
        "conversation_id": str(conversation_id or ""),
        "plan_id": plan_id,
        "validated_task_plan_snapshot": plan,
        "plan_hash": plan_hash(plan),
        "area_asset_ids": [str(item.get("area_asset_id") or "") for item in requests if isinstance(item, dict) and item.get("area_asset_id")],
        "product_ids": [str(item.get("product_id") or item.get("product_key") or "") for item in requests if isinstance(item, dict) and (item.get("product_id") or item.get("product_key"))],
        "requested_downloads": requests,
        "requires_confirmation_reason": reason,
        "created_at": _iso(now),
        "updated_at": _iso(now),
        "expires_at": _iso(now + timedelta(minutes=ttl_minutes)),
        "status": "awaiting_confirmation",
        "idempotency_key": idempotency_key,
    }
    records.append(record)
    _save(database, records)
    return record


def latest_awaiting_confirmation(database: Any, *, user_id: str, session_id: str, conversation_id: str) -> dict[str, Any] | None:
    now = _now()
    records = [_mark_expired(item, now) for item in _load(database)]
    _save(database, records)
    candidates = [
        item
        for item in records
        if _record_matches(item, user_id=user_id, session_id=session_id, conversation_id=conversation_id)
        and str(item.get("status") or "") == "awaiting_confirmation"
    ]
    candidates.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return candidates[0] if candidates else None


def get_confirmation(database: Any, confirmation_id: str, *, user_id: str, session_id: str, conversation_id: str) -> dict[str, Any] | None:
    now = _now()
    records = [_mark_expired(item, now) for item in _load(database)]
    _save(database, records)
    for item in records:
        if str(item.get("confirmation_id") or "") == str(confirmation_id or "") and _record_matches(
            item,
            user_id=user_id,
            session_id=session_id,
            conversation_id=conversation_id,
        ):
            return item
    return None


def update_confirmation_status(database: Any, confirmation_id: str, status: str) -> dict[str, Any] | None:
    if status not in CONFIRMATION_STATUSES:
        raise ValueError(f"unsupported pending confirmation status: {status}")
    records = _load(database)
    now = _iso(_now())
    updated: dict[str, Any] | None = None
    for index, item in enumerate(records):
        if str(item.get("confirmation_id") or "") == str(confirmation_id or ""):
            item = dict(item)
            item["status"] = status
            item["updated_at"] = now
            records[index] = item
            updated = item
            break
    _save(database, records)
    return updated


def cancel_awaiting_confirmations(database: Any, *, user_id: str, session_id: str, conversation_id: str, reason: str = "") -> int:
    records = _load(database)
    count = 0
    now = _iso(_now())
    for index, item in enumerate(records):
        if _record_matches(item, user_id=user_id, session_id=session_id, conversation_id=conversation_id) and str(item.get("status") or "") == "awaiting_confirmation":
            item = dict(item)
            item["status"] = "cancelled"
            item["updated_at"] = now
            if reason:
                item["cancel_reason"] = reason
            records[index] = item
            count += 1
    _save(database, records)
    return count


def confirmation_plan(record: dict[str, Any]) -> dict[str, Any]:
    plan = _as_dict(record.get("validated_task_plan_snapshot"))
    requests = []
    for item in _as_list(plan.get("download_requests")) or _as_list(plan.get("requested_downloads")):
        if not isinstance(item, dict):
            continue
        req = dict(item)
        params = _as_dict(req.get("download_parameters"))
        params["idempotency_key"] = str(record.get("idempotency_key") or "")
        req["download_parameters"] = params
        requests.append(req)
    plan = dict(plan)
    plan["requires_confirmation"] = False
    plan["should_ask_clarification"] = False
    plan["clarification_question"] = ""
    plan["download_requests"] = requests
    plan["requested_downloads"] = requests
    return plan
