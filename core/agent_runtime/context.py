from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.tool_context import ToolRuntimeContext


DEFAULT_PERMISSION_SCOPE = frozenset(
    {
        "workspace:read",
        "workspace:write",
        "database:read",
        "filesystem:read",
        "filesystem:write",
    }
)


@dataclass(frozen=True, slots=True)
class AgentRuntimeContext:
    current_user_id: str
    current_session_id: str
    workspace_dir: Path
    permission_scope: frozenset[str] = field(default_factory=lambda: DEFAULT_PERMISSION_SCOPE)
    job_id: str = ""
    artifact_registry_available: bool = False
    map_layer_registry_available: bool = False

    @classmethod
    def from_manager(cls, manager: Any) -> "AgentRuntimeContext":
        return cls(
            current_user_id=str(getattr(manager, "current_user_id", "") or ""),
            current_session_id=str(getattr(manager, "current_session_id", "") or ""),
            workspace_dir=Path(getattr(manager, "workdir", ".")).resolve(strict=False),
            artifact_registry_available=callable(getattr(manager, "register_artifact", None))
            or callable(getattr(manager, "list_artifacts", None)),
            map_layer_registry_available=callable(getattr(manager, "list_map_layers", None))
            or callable(getattr(manager, "register_map_layer", None)),
        )

    def to_tool_context(self) -> ToolRuntimeContext:
        return ToolRuntimeContext(
            current_user_id=self.current_user_id,
            current_session_id=self.current_session_id,
            workspace_dir=self.workspace_dir,
            permission_scope=set(self.permission_scope),
            job_id=self.job_id,
        )

    def resolve_workspace_path(self, path: str | Path) -> Path:
        resolved = Path(path).resolve(strict=False)
        workspace = self.workspace_dir.resolve(strict=False)
        try:
            resolved.relative_to(workspace)
        except ValueError as exc:
            raise PermissionError(f"path is outside workspace: {resolved}") from exc
        return resolved

    def to_metadata(self) -> dict[str, Any]:
        return {
            "current_user_id": self.current_user_id,
            "current_session_id": self.current_session_id,
            "workspace_dir": str(self.workspace_dir),
            "permission_scope": sorted(self.permission_scope),
            "job_id": self.job_id,
            "artifact_registry_available": self.artifact_registry_available,
            "map_layer_registry_available": self.map_layer_registry_available,
        }
