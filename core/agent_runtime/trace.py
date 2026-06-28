from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


DEFAULT_TRACE_LIMIT = 50


@dataclass(slots=True)
class RuntimeTraceBuffer:
    max_events: int = DEFAULT_TRACE_LIMIT
    _events: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        event: str,
        payload: dict[str, Any] | None = None,
        *,
        runtime_mode: str = "",
        current_session_id: str = "",
    ) -> None:
        item = {
            "event": str(event or "").strip(),
            "payload": deepcopy(payload or {}),
            "runtime_mode": str(runtime_mode or ""),
            "current_session_id": str(current_session_id or ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._events.append(item)
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]

    def snapshot(self) -> list[dict[str, Any]]:
        return deepcopy(self._events)
