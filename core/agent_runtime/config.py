from __future__ import annotations

import os
from dataclasses import dataclass


TRUE_VALUES = {"1", "true", "yes", "on"}
VALID_MODES = {"legacy", "shadow", "active"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in TRUE_VALUES


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    enabled: bool = False
    mode: str = "legacy"
    active_requested: bool = False
    active_cutover_allowed: bool = False

    @classmethod
    def from_env(cls) -> "AgentRuntimeConfig":
        enabled = _env_flag("GIS_AGENT_RUNTIME_V2", default=False)
        raw_mode = os.getenv("GIS_AGENT_RUNTIME_MODE", "").strip().lower()
        active_requested = bool(enabled and raw_mode == "active")
        active_cutover_allowed = _env_flag("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", default=False)
        mode = raw_mode if raw_mode in VALID_MODES else ("shadow" if enabled else "legacy")
        if active_requested and not active_cutover_allowed:
            mode = "shadow"
        if not enabled:
            mode = "legacy"
            active_requested = False
            active_cutover_allowed = False
        return cls(
            enabled=enabled,
            mode=mode,
            active_requested=active_requested,
            active_cutover_allowed=active_cutover_allowed,
        )

    def cutover_guard(self) -> dict[str, object]:
        active_effective = bool(self.enabled and self.mode == "active" and self.active_cutover_allowed)
        fallback_mode = "shadow" if self.enabled else "legacy"
        reason = "active_mode_allowed" if active_effective else ""
        if self.active_requested and not self.active_cutover_allowed:
            reason = "active_mode_requires_GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER"
        elif not self.active_requested:
            reason = "active_mode_not_requested"
        return {
            "active_requested": bool(self.active_requested),
            "active_cutover_allowed": bool(self.active_cutover_allowed),
            "active_effective": active_effective,
            "fallback_mode": fallback_mode,
            "reason": reason,
        }
