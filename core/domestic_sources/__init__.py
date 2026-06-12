from .registry import DOMESTIC_RESOURCE_CATALOG, DOMESTIC_SOURCES


def build_domestic_tools(manager):
    from .tools import build_domestic_tools as _build
    return _build(manager)

__all__ = ["DOMESTIC_RESOURCE_CATALOG", "DOMESTIC_SOURCES", "build_domestic_tools"]
