from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _tool_names(plan: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for step in _as_list(plan.get("tool_plan")):
        if isinstance(step, dict) and str(step.get("tool_name") or "").strip():
            names.append(str(step["tool_name"]))
    names.extend(str(name) for name in _as_dict(plan.get("validated_tool_args")).keys() if str(name).strip())
    return list(dict.fromkeys(names))


def _error_codes(shadow_plan: dict[str, Any]) -> list[str]:
    codes = [
        str(item.get("code") or "")
        for item in _as_list(shadow_plan.get("errors"))
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    return list(dict.fromkeys(codes))


def summarize_shadow_plan(shadow_plan: Any) -> dict[str, Any]:
    payload = _as_dict(shadow_plan)
    plan = _as_dict(payload.get("plan")) or _as_dict(payload.get("fallback_plan"))
    return {
        "llm_planner_mode": str(payload.get("mode") or "shadow"),
        "llm_planner_source": str(payload.get("planner_source") or "unknown"),
        "llm_planner_status": str(payload.get("status") or "unknown"),
        "llm_planner_executes_tools": bool(payload.get("executes_tools")),
        "llm_planner_error_codes": _error_codes(payload),
        "llm_planner_has_plan": bool(payload.get("plan")),
        "llm_planner_requires_confirmation": bool(plan.get("requires_confirmation")),
        "llm_planner_should_ask_clarification": bool(plan.get("should_ask_clarification")),
        "llm_planner_tool_names": _tool_names(plan),
    }


def _load_meta(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def summarize_shadow_planner_messages(db_path: str | Path) -> dict[str, Any]:
    target = Path(db_path)
    if not target.exists():
        return {
            "database": str(target),
            "exists": False,
            "assistant_shadow_message_count": 0,
            "status_counts": {},
            "error_code_counts": {},
            "source_counts": {},
        }
    status_counts: Counter[str] = Counter()
    error_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    count = 0
    with sqlite3.connect(target) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT role, meta_json FROM conversation_messages WHERE role = 'assistant' ORDER BY message_id ASC"
        ).fetchall()
    for row in rows:
        meta = _load_meta(str(row["meta_json"] or "{}"))
        status = str(meta.get("llm_planner_status") or "")
        if not status and isinstance(meta.get("llm_shadow_plan"), dict):
            summary = summarize_shadow_plan(meta["llm_shadow_plan"])
            status = str(summary.get("llm_planner_status") or "")
            meta = {**meta, **summary}
        if not status:
            continue
        count += 1
        status_counts[status] += 1
        source = str(meta.get("llm_planner_source") or "unknown")
        source_counts[source] += 1
        for code in _as_list(meta.get("llm_planner_error_codes")):
            if str(code).strip():
                error_counts[str(code)] += 1
    return {
        "database": str(target),
        "exists": True,
        "assistant_shadow_message_count": count,
        "status_counts": dict(sorted(status_counts.items())),
        "error_code_counts": dict(sorted(error_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
    }
