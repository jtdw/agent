from __future__ import annotations

from typing import Any

from core.resource_tools import build_resource_tools


def build_download_tools(manager: Any) -> list[Any]:
    return build_resource_tools(manager)
