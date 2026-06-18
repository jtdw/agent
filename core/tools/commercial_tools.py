from __future__ import annotations

from typing import Any

from core.commercial import build_commercial_tools as _build_commercial_tools


def build_commercial_tools(manager: Any) -> list[Any]:
    return _build_commercial_tools(manager)
