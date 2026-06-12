from .service import CommercialService


def build_commercial_tools(manager, *, include_admin_tools: bool = False):
    from .tools import build_commercial_tools as _build
    return _build(manager, include_admin_tools=include_admin_tools)


__all__ = ["build_commercial_tools", "CommercialService"]
