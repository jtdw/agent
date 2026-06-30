from __future__ import annotations

from typing import Any

from .presentation_result import build_presentation_bundle, format_presentation_reply
from .response_language import normalize_response_language


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    for marker in (
        "workspace\\",
        "workspace/",
        ":\\",
        "/tmp/",
        "/home/",
        "/var/",
        "/etc/",
        "/root/",
        "/users/",
        "\\users\\",
        "session_",
        "user_id",
        "session_id",
        "Traceback",
    ):
        if marker in text:
            return ""
    return text[:limit]


def _plan_summary(plan: dict[str, Any], intent: dict[str, Any] | None = None) -> dict[str, Any]:
    intent = intent or {}
    return {
        "primary_goal": _clean_text(plan.get("primary_goal") or plan.get("task_type") or intent.get("intent"), 160),
        "intent": _clean_text(plan.get("intent") or intent.get("intent"), 100),
        "operation": _clean_text(plan.get("operation"), 100),
        "response_language": _clean_text(plan.get("response_language"), 20),
    }


def interpret_canonical_result(
    *,
    task_goal: str,
    task_plan_summary: dict[str, Any],
    coordinator_status: str,
    normalized_results: list[Any],
    llm_client: Any | None = None,
    min_confidence: float = 0.65,
) -> dict[str, Any]:
    """Build the canonical presentation bundle from normalized execution facts only."""

    return build_presentation_bundle(
        task_goal=task_goal,
        task_plan_summary=task_plan_summary,
        coordinator_status=coordinator_status,
        normalized_results=normalized_results,
        llm_client=llm_client,
        min_confidence=min_confidence,
    )


def interpret_result(
    prompt: str,
    intent: dict[str, Any],
    plan: dict[str, Any],
    raw_reply: str,
    context: dict[str, Any],
    dashboard: Any,
) -> str:
    """Compatibility text fallback.

    This function intentionally does not parse raw workflow/tool/download payloads.
    New execution result rendering must call interpret_canonical_result() with
    ExecutionTrace.results-derived normalized ToolResults.
    """

    raw = _clean_text(raw_reply)
    response_language = normalize_response_language(plan.get("response_language") or context.get("response_language"), prompt)
    active_dataset = _as_dict(context.get("active_dataset"))
    if plan.get("should_ask_clarification") and (plan.get("clarification_question") or raw) and not active_dataset:
        return _clean_text(plan.get("clarification_question") or raw, 600)

    if raw.startswith("{") or raw.startswith("["):
        raw = ""

    referenced = _as_dict(context.get("referenced_object"))
    if referenced.get("type") == "model_result" and referenced.get("missing"):
        ref_id = _clean_text(referenced.get("id") or referenced.get("label") or "selected model result", 120)
        return (
            f"No canonical execution facts are available for the selected model result {ref_id}; 找不到该结果记录。 "
            "The referenced result record is missing, so no metrics or artifacts were inferred."
        )

    recent_error = _as_dict(context.get("recent_error"))
    if str(intent.get("intent") or plan.get("task_type") or "") == "troubleshooting" and recent_error:
        message = _clean_text(recent_error.get("message") or recent_error.get("error"), 300)
        return (
            f"Recent failure: {message or 'No safe error message was recorded.'}\n"
            "下一步建议: rerun the validated plan after fixing the missing input, field, permission, or CRS issue."
        )

    model = _as_dict(context.get("recent_model_result"))
    dashboard_dict = _as_dict(dashboard)
    if not model:
        for item in _as_list(dashboard_dict.get("model_results")):
            if isinstance(item, dict):
                model = item
                break
    if str(intent.get("intent") or plan.get("task_type") or "") == "result_analysis" and model:
        metrics = _as_dict(model.get("metrics"))
        parts = [f"{key}={value}" for key, value in metrics.items() if isinstance(value, (int, float, str))]
        recommendations = [_clean_text(item, 120) for item in _as_list(model.get("recommendations")) if _clean_text(item, 120)]
        return "\n".join(
            [
                "Canonical result context is not available; using the selected model summary from conversation context.",
                "Metrics: " + (", ".join(parts) if parts else "not recorded"),
                "特征重要性 / Feature importance and residual spatial distribution should be reviewed against the registered artifacts.",
                "Next actions: " + ("; ".join(recommendations) if recommendations else "inspect model artifacts and residuals."),
            ]
        )

    normalized_results = _as_list(plan.get("normalized_results"))
    if normalized_results:
        summary = _plan_summary(plan, intent)
        summary["response_language"] = response_language
        bundle = interpret_canonical_result(
            task_goal=_clean_text(plan.get("primary_goal") or plan.get("task_type") or prompt, 160),
            task_plan_summary=summary,
            coordinator_status=str(plan.get("coordinator_status") or plan.get("status") or ""),
            normalized_results=normalized_results,
        )
        return format_presentation_reply(_as_dict(bundle.get("presentation_result")))

    goal = _clean_text(plan.get("primary_goal") or plan.get("task_type") or intent.get("intent") or prompt, 160)
    if raw:
        return raw
    if active_dataset:
        dataset_name = _clean_text(active_dataset.get("name") or active_dataset.get("id"), 120)
        return (
            f"No canonical execution facts are available yet. Active dataset: {dataset_name or 'unknown'}.\n"
            "下一步建议: ask for a concrete GIS operation such as profiling, clipping, mapping, table-to-points, modeling, or export."
        )
    return (
        f"No canonical execution facts are available for {goal or 'this request'}. "
        "The result interpreter did not read legacy raw workflow, tool, or download job structures."
    )
