from __future__ import annotations

from typing import Any

from core.tools.common_tools import build_common_tools
from core.tools.document_tools import build_document_tools
from core.tools.download_tools import build_download_tools
from core.tools.map_tools import build_map_tools
from core.tools.ml_tools import build_ml_tools
from core.tools.raster_tools import build_raster_tools
from core.tools.table_tools import build_table_tools
from core.tools.vector_tools import build_vector_tools


def build_tools(manager: Any, context: Any | None = None):
    if context is not None and hasattr(manager, "set_runtime_scope"):
        manager.set_runtime_scope(
            str(getattr(context, "current_user_id", "") or ""),
            str(getattr(context, "current_session_id", "") or ""),
        )

    tools: list[Any] = []
    tools.extend(build_common_tools(manager))
    tools.extend(build_document_tools(manager))
    tools.extend(build_table_tools(manager))
    tools.extend(build_vector_tools(manager))
    tools.extend(build_raster_tools(manager))
    tools.extend(build_map_tools(manager))
    tools.extend(build_ml_tools(manager))
    tools.extend(build_download_tools(manager))

    deduped: dict[str, Any] = {}
    for item in tools:
        name = str(getattr(item, "name", "") or "")
        if name and name not in deduped:
            deduped[name] = item
    return list(deduped.values())
