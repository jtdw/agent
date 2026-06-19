from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.llm_task_planner import build_shadow_llm_task_plan


class _CaseClient:
    def __init__(self, payload: Any):
        self.payload = payload

    def invoke(self, messages: Any) -> Any:
        del messages
        return json.dumps(self.payload, ensure_ascii=False, default=str)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _error(code: str, message: str, **detail: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **detail}


def load_llm_planner_cases(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {target}:{line_no}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid JSONL at {target}:{line_no}: case must be an object")
        for field in ("id", "user_prompt", "context", "deterministic_plan", "model_output", "expected"):
            if field not in payload:
                raise ValueError(f"Invalid case {payload.get('id') or line_no}: missing {field}")
        cases.append(payload)
    return cases


def _tools_used(plan: dict[str, Any]) -> set[str]:
    tools = {str(step.get("tool_name") or "") for step in _as_list(plan.get("tool_plan")) if isinstance(step, dict)}
    tools.update(str(name) for name in _as_dict(plan.get("validated_tool_args")).keys())
    return {tool for tool in tools if tool}


def _selected_asset_names(plan: dict[str, Any]) -> set[str]:
    selected = _as_list(_as_dict(plan.get("resolved_objects")).get("selected_assets"))
    return {str(item.get("name") or "") for item in selected if isinstance(item, dict) and item.get("name")}


def _check_expectations(case: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = _as_dict(case.get("expected"))
    errors: list[dict[str, Any]] = []
    status = str(result.get("status") or "")
    if expected.get("status") and status != str(expected["status"]):
        errors.append(_error("STATUS_MISMATCH", "Planner status did not match expectation.", expected=expected["status"], actual=status))

    plan = _as_dict(result.get("plan")) or _as_dict(result.get("fallback_plan"))
    used_tools = _tools_used(plan)
    for tool_name in [str(item) for item in _as_list(expected.get("forbidden_tools_not_used")) if str(item).strip()]:
        if tool_name in used_tools:
            errors.append(_error("FORBIDDEN_TOOL_USED", "Planner used a forbidden tool for this case.", tool_name=tool_name))

    for tool_name in [str(item) for item in _as_list(expected.get("required_tools_used")) if str(item).strip()]:
        if tool_name not in used_tools:
            errors.append(_error("REQUIRED_TOOL_MISSING", "Planner did not use an expected tool.", tool_name=tool_name))

    if "should_ask_clarification" in expected:
        actual = bool(plan.get("should_ask_clarification") or result.get("status") == "invalid_plan")
        if actual != bool(expected["should_ask_clarification"]):
            errors.append(_error("CLARIFICATION_MISMATCH", "Clarification behavior did not match.", expected=bool(expected["should_ask_clarification"]), actual=actual))

    if expected.get("requires_confirmation") is not None:
        actual = bool(plan.get("requires_confirmation"))
        if actual != bool(expected["requires_confirmation"]):
            errors.append(_error("CONFIRMATION_MISMATCH", "Confirmation requirement did not match.", expected=bool(expected["requires_confirmation"]), actual=actual))

    for asset_name in [str(item) for item in _as_list(expected.get("selected_assets_include")) if str(item).strip()]:
        if asset_name not in _selected_asset_names(plan):
            errors.append(_error("SELECTED_ASSET_MISSING", "Planner did not select the expected asset.", asset_name=asset_name))

    for asset_name in [str(item) for item in _as_list(expected.get("selected_assets_exclude")) if str(item).strip()]:
        if asset_name in _selected_asset_names(plan):
            errors.append(_error("STALE_ASSET_SELECTED", "Planner selected a stale or disallowed asset.", asset_name=asset_name))

    for code in [str(item) for item in _as_list(expected.get("expected_error_codes")) if str(item).strip()]:
        actual_codes = {str(item.get("code") or "") for item in _as_list(result.get("errors")) if isinstance(item, dict)}
        if code not in actual_codes:
            errors.append(_error("EXPECTED_ERROR_MISSING", "Expected validation error was not reported.", expected_code=code, actual_codes=sorted(actual_codes)))

    return errors


def evaluate_llm_planner_cases(path: str | Path, *, use_real_llm: bool = False) -> dict[str, Any]:
    cases = load_llm_planner_cases(path)
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for case in cases:
        result = build_shadow_llm_task_plan(
            str(case["user_prompt"]),
            _as_dict(case.get("context")),
            _as_dict(case.get("deterministic_plan")),
            client=None if use_real_llm else _CaseClient(case.get("model_output")),
            enabled=True,
        )
        errors = _check_expectations(case, result)
        passed = not errors
        row = {
            "case_id": str(case.get("id")),
            "status": result.get("status"),
            "passed": passed,
            "errors": errors,
        }
        rows.append(row)
        if not passed:
            failures.append(row)
    case_count = len(cases)
    passed_count = sum(1 for row in rows if row["passed"])
    return {
        "case_count": case_count,
        "passed": passed_count,
        "failed": case_count - passed_count,
        "accuracy": round(passed_count / case_count, 4) if case_count else 0.0,
        "cases": rows,
        "failures": failures,
    }
