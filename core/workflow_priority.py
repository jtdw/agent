from __future__ import annotations

from typing import Any


LOW_RISK_WORKFLOW_ALLOWLIST = {
    "upload_vector_profile",
    "upload_raster_profile",
    "table_to_points",
    "raster_statistics",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def workflow_priority_route(plan: dict[str, Any], *, prompt: str = "") -> dict[str, Any]:
    template = _as_dict(plan.get("workflow_template"))
    executable = _as_dict(plan.get("executable_workflow"))
    workflow_id = str(template.get("workflow_id") or executable.get("workflow_id") or "")
    semantic = _as_dict(plan.get("semantic_parse"))
    confidence = float(plan.get("route_confidence") or semantic.get("confidence") or plan.get("confidence") or 0.0)
    if confidence <= 0:
        confidence = 0.8 if workflow_id else 0.0
    reason_parts: list[str] = []

    if not workflow_id:
        return {"ok": False, "reason": "no_registered_workflow", "confidence": confidence}
    if workflow_id not in LOW_RISK_WORKFLOW_ALLOWLIST:
        return {"ok": False, "reason": "workflow_not_in_low_risk_allowlist", "selected_workflow": workflow_id, "confidence": confidence}
    if plan.get("should_ask_clarification"):
        return {"ok": False, "reason": "needs_clarification", "selected_workflow": workflow_id, "confidence": confidence}
    if executable.get("status") != "ready":
        return {"ok": False, "reason": "workflow_not_ready", "selected_workflow": workflow_id, "confidence": confidence}
    if str(plan.get("task_type") or "") in {"modeling", "data_download"}:
        return {"ok": False, "reason": "high_impact_task_requires_planner", "selected_workflow": workflow_id, "confidence": confidence}
    if confidence < 0.72:
        return {"ok": False, "reason": "route_confidence_too_low", "selected_workflow": workflow_id, "confidence": confidence}

    reason_parts.append("registered_workflow_ready")
    reason_parts.append("low_risk_allowlist")
    reason_parts.append("parameters_complete")
    return {
        "ok": True,
        "schema_version": "workflow-priority-route/v1",
        "selected_workflow": workflow_id,
        "confidence": round(confidence, 3),
        "route_reason": ";".join(reason_parts),
        "prompt_preview": str(prompt or "")[:160],
    }
