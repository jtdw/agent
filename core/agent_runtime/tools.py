from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .context import AgentRuntimeContext


DOWNLOAD_HINTS = ("download", "gscloud", "commercial", "capture", "tile")
WRITE_HINTS = (
    "plot",
    "map",
    "export",
    "clip",
    "buffer",
    "overlay",
    "dissolve",
    "join",
    "reproject",
    "train",
    "workflow",
    "points",
    "raster",
)


@dataclass(frozen=True, slots=True)
class RuntimeToolSpec:
    name: str
    description: str
    permissions: frozenset[str]
    risk_level: str
    original_tool: Any

    def to_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permissions": sorted(self.permissions),
            "risk_level": self.risk_level,
        }


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "") or "").strip()


def _tool_description(tool: Any) -> str:
    return str(getattr(tool, "description", "") or "").strip()


def _classify_tool(name: str) -> tuple[str, frozenset[str]]:
    lowered = name.lower()
    if any(hint in lowered for hint in DOWNLOAD_HINTS):
        return "high", frozenset({"workspace:read", "workspace:write", "network:download"})
    if any(hint in lowered for hint in WRITE_HINTS):
        return "medium", frozenset({"workspace:read", "workspace:write"})
    return "low", frozenset({"workspace:read"})


def build_runtime_tool_specs(tools: Iterable[Any]) -> list[RuntimeToolSpec]:
    specs: list[RuntimeToolSpec] = []
    seen: set[str] = set()
    for tool in tools:
        name = _tool_name(tool)
        if not name or name in seen:
            continue
        seen.add(name)
        risk_level, permissions = _classify_tool(name)
        specs.append(
            RuntimeToolSpec(
                name=name,
                description=_tool_description(tool),
                permissions=permissions,
                risk_level=risk_level,
                original_tool=tool,
            )
        )
    return specs


def precheck_tool_spec(spec: RuntimeToolSpec, context: AgentRuntimeContext) -> dict[str, Any]:
    granted = set(context.permission_scope)
    missing = sorted(permission for permission in spec.permissions if permission not in granted and "*" not in granted)
    if missing:
        return {
            "ok": False,
            "tool_name": spec.name,
            "risk_level": spec.risk_level,
            "error_code": "TOOL_PERMISSION_DENIED",
            "missing_permissions": missing,
            "required_permissions": sorted(spec.permissions),
        }
    return {
        "ok": True,
        "tool_name": spec.name,
        "risk_level": spec.risk_level,
        "required_permissions": sorted(spec.permissions),
    }
