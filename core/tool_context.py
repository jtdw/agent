from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolRuntimeContext:
    current_user_id: str
    current_session_id: str
    workspace_dir: Path
    permission_scope: set[str] = field(default_factory=set)
    job_id: str = ""

    def has_permission(self, permission: str) -> bool:
        scope = {str(item).strip() for item in self.permission_scope if str(item).strip()}
        return "*" in scope or permission in scope

    def require_permission(self, permission: str) -> None:
        if not self.has_permission(permission):
            raise PermissionError(f"tool permission denied: {permission}")

    def to_metadata(self) -> dict[str, Any]:
        return {
            "current_user_id": self.current_user_id,
            "current_session_id": self.current_session_id,
            "workspace_dir": str(self.workspace_dir),
            "permission_scope": sorted(self.permission_scope),
            "job_id": self.job_id,
        }


def context_from_manager(manager: Any) -> ToolRuntimeContext:
    return ToolRuntimeContext(
        current_user_id=str(getattr(manager, "current_user_id", "") or ""),
        current_session_id=str(getattr(manager, "current_session_id", "") or ""),
        workspace_dir=Path(getattr(manager, "workdir", ".")),
        permission_scope={"workspace:read", "workspace:write", "database:read", "filesystem:read", "filesystem:write"},
    )
