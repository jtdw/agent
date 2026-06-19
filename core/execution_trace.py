from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .tool_contracts import normalize_tool_result


TraceStatus = Literal["pending", "running", "succeeded", "failed", "blocked", "awaiting_confirmation"]


class NormalizedToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[Any] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    map_layers: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    next_actions: list[str] = Field(default_factory=list)
    step_id: str
    tool_name: str
    input_asset_ids: list[str] = Field(default_factory=list)


class ExecutionTrace(BaseModel):
    model_config = ConfigDict(extra="allow")

    plan_id: str
    results: list[NormalizedToolResult] = Field(default_factory=list)
    executed_step_ids: list[str] = Field(default_factory=list)
    remaining_step_ids: list[str] = Field(default_factory=list)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    elapsed_ms: int = 0
    status: TraceStatus = "pending"
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _plan_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    steps = _as_list(plan.get("workflow_plan"))
    if steps:
        return [step for step in steps if isinstance(step, dict)]
    tool_plan = _as_list(plan.get("tool_plan"))
    if tool_plan:
        out: list[dict[str, Any]] = []
        for index, step in enumerate(tool_plan):
            if not isinstance(step, dict):
                continue
            tool_name = str(step.get("tool_name") or "")
            out.append(
                {
                    "step_id": str(step.get("step_id") or tool_name or f"step_{index + 1}"),
                    "tool_name": tool_name,
                    "validated_tool_args": _as_dict(step.get("args")),
                }
            )
        return out
    validated = _as_dict(plan.get("validated_tool_args"))
    return [
        {"step_id": name, "tool_name": name, "validated_tool_args": args}
        for name, args in validated.items()
        if isinstance(args, dict)
    ]


def plan_step_ids(plan: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for index, step in enumerate(_plan_steps(plan)):
        step_id = str(step.get("step_id") or f"step_{index + 1}")
        ids.append(step_id)
    return ids


def _raw_candidates(raw_results: Any) -> list[dict[str, Any]]:
    raw = _as_dict(raw_results)
    candidates: list[dict[str, Any]] = []
    workflow_result = _as_dict(raw.get("workflow_result"))
    workflow_outputs = _as_dict(workflow_result.get("outputs"))
    candidates.extend(item for item in _as_list(workflow_outputs.get("step_results")) if isinstance(item, dict))
    for step in _as_list(workflow_result.get("steps")):
        step_dict = _as_dict(step)
        result = _as_dict(step_dict.get("tool_result"))
        if result:
            patched = dict(result)
            patched.setdefault("step_id", str(step_dict.get("step_id") or ""))
            patched.setdefault("tool_name", str(step_dict.get("tool_name") or ""))
            candidates.append(patched)
    candidates.extend(item for item in _as_list(raw.get("tool_results")) if isinstance(item, dict))
    download = _as_dict(raw.get("download_tool_result") or raw.get("tool_result"))
    if download:
        candidates.append(download)
    if not candidates and {"status", "tool_name"}.issubset(raw):
        candidates.append(raw)
    return candidates


def _normalize_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        normalized = normalize_tool_result(item)
    except Exception:
        return None
    step_id = str(normalized.get("step_id") or item.get("step_id") or normalized.get("tool_name") or "")
    if not step_id:
        return None
    return NormalizedToolResult(
        status=str(normalized.get("status") or ""),
        errors=[entry for entry in _as_list(normalized.get("errors")) if isinstance(entry, dict)],
        warnings=_as_list(normalized.get("warnings")),
        artifacts=[entry for entry in _as_list(normalized.get("artifacts")) if isinstance(entry, dict)],
        map_layers=[entry for entry in _as_list(normalized.get("map_layers")) if isinstance(entry, dict)],
        tables=[entry for entry in _as_list(normalized.get("tables")) if isinstance(entry, dict)],
        images=[entry for entry in _as_list(normalized.get("images")) if isinstance(entry, dict)],
        outputs=_as_dict(normalized.get("outputs")),
        diagnostics=_as_dict(normalized.get("diagnostics")),
        next_actions=[str(entry) for entry in _as_list(normalized.get("next_actions")) if str(entry).strip()],
        step_id=step_id,
        tool_name=str(normalized.get("tool_name") or ""),
        input_asset_ids=[str(entry) for entry in _as_list(normalized.get("input_asset_ids")) if str(entry).strip()],
    ).model_dump(mode="json")


def normalize_execution_results(plan: dict[str, Any], raw_results: Any) -> list[dict[str, Any]]:
    order = plan_step_ids(plan)
    order_index = {step_id: index for index, step_id in enumerate(order)}
    accepted: dict[str, dict[str, Any]] = {}
    for item in _raw_candidates(raw_results):
        normalized = _normalize_candidate(item)
        if not normalized:
            continue
        step_id = str(normalized.get("step_id") or "")
        if step_id in order_index:
            accepted[step_id] = normalized
    return [accepted[step_id] for step_id in order if step_id in accepted]


def build_execution_trace(
    plan: dict[str, Any],
    raw_results: Any | None = None,
    *,
    plan_id: str = "",
    retry_counts: dict[str, int] | None = None,
    started_at: str = "",
    elapsed_ms: int = 0,
) -> ExecutionTrace:
    order = plan_step_ids(plan)
    order_set = set(order)
    normalized = normalize_execution_results(plan, raw_results or {})
    known_ids = {str(item.get("step_id") or "") for item in normalized}
    unknown: list[dict[str, Any]] = []
    for item in _raw_candidates(raw_results or {}):
        maybe = _normalize_candidate(item)
        if maybe and str(maybe.get("step_id") or "") not in order_set:
            unknown.append(maybe)
    status = "pending"
    if normalized:
        last_status = str(normalized[-1].get("status") or "")
        if any(str(item.get("status")) == "awaiting_confirmation" for item in normalized):
            status = "awaiting_confirmation"
        elif any(str(item.get("status")) == "blocked" for item in normalized):
            status = "blocked"
        elif any(str(item.get("status")) == "failed" for item in normalized):
            status = "failed"
        elif len(known_ids) == len(order):
            status = "succeeded"
        else:
            status = "running" if last_status == "succeeded" else last_status or "running"
    return ExecutionTrace(
        plan_id=plan_id or str(plan.get("plan_id") or f"plan_{uuid4().hex[:10]}"),
        results=[NormalizedToolResult.model_validate(item) for item in normalized],
        executed_step_ids=[step_id for step_id in order if step_id in known_ids],
        remaining_step_ids=[step_id for step_id in order if step_id not in known_ids],
        retry_counts=retry_counts or {},
        started_at=started_at or datetime.now().isoformat(timespec="seconds"),
        elapsed_ms=int(elapsed_ms or 0),
        status=status,  # type: ignore[arg-type]
        diagnostics={"unknown_step_results": unknown},
    )
