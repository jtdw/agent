from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any


_RECENT_USAGE: deque[dict[str, Any]] = deque(maxlen=200)


def record_llm_usage(
    *,
    provider: str,
    model: str,
    usage: dict[str, Any] | None = None,
    cached_tokens: int = 0,
    operation: str = "",
    latency_ms: int = 0,
    status: str = "",
    retry_count: int = 0,
) -> dict[str, Any]:
    payload = {
        "provider": str(provider or ""),
        "model": str(model or ""),
        "operation": str(operation or ""),
        "status": str(status or ""),
        "latency_ms": int(latency_ms or 0),
        "retry_count": int(retry_count or 0),
        "usage": usage if isinstance(usage, dict) else {},
        "cached_tokens": int(cached_tokens or 0),
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    _RECENT_USAGE.append(payload)
    return payload


def recent_llm_usage(limit: int = 20) -> list[dict[str, Any]]:
    return list(_RECENT_USAGE)[-max(1, int(limit or 1)) :]
