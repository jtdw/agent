from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

from .config import _env_flag


def _bucket_for_key(key: str) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


@dataclass(frozen=True, slots=True)
class AgentRuntimeTrafficRouter:
    routing_enforced: bool = False
    salt: str = "agent-runtime-exposure-v1"

    @classmethod
    def from_env(cls) -> "AgentRuntimeTrafficRouter":
        return cls(
            routing_enforced=_env_flag("GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING", default=False),
            salt=os.getenv("GIS_AGENT_RUNTIME_EXPOSURE_SALT", "agent-runtime-exposure-v1").strip() or "agent-runtime-exposure-v1",
        )

    def decide(
        self,
        exposure_report: dict[str, Any],
        *,
        user_id: str = "",
        session_id: str = "",
        request_text: str = "",
    ) -> dict[str, Any]:
        if not self.routing_enforced:
            return {
                "schema_version": "agent-runtime-traffic-routing/v1",
                "routing_enforced": False,
                "use_active_runtime": True,
                "reason": "routing_not_enforced",
                "requested_percent": int(exposure_report.get("requested_percent") or 0),
                "bucket": None,
                "bucket_key": "",
                "policy_reasons": list(exposure_report.get("reasons") or []),
            }

        requested_percent = int(exposure_report.get("requested_percent") or 0)
        policy_reasons = [str(item) for item in exposure_report.get("reasons") or []]
        bucket_key = "|".join(
            [
                self.salt,
                str(user_id or "anonymous"),
                str(session_id or "no-session"),
                str(request_text or "")[:256],
            ]
        )
        bucket = _bucket_for_key(bucket_key)
        if not bool(exposure_report.get("eligible_for_user_exposure")):
            return {
                "schema_version": "agent-runtime-traffic-routing/v1",
                "routing_enforced": True,
                "use_active_runtime": False,
                "reason": "exposure_policy_not_eligible",
                "requested_percent": requested_percent,
                "bucket": bucket,
                "bucket_key": hashlib.sha256(bucket_key.encode("utf-8")).hexdigest()[:12],
                "policy_reasons": policy_reasons,
            }
        use_active = bucket < requested_percent
        return {
            "schema_version": "agent-runtime-traffic-routing/v1",
            "routing_enforced": True,
            "use_active_runtime": use_active,
            "reason": "selected_for_active_runtime" if use_active else "outside_exposure_bucket",
            "requested_percent": requested_percent,
            "bucket": bucket,
            "bucket_key": hashlib.sha256(bucket_key.encode("utf-8")).hexdigest()[:12],
            "policy_reasons": policy_reasons,
        }

