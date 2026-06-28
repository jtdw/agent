from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


TOOL_ALIASES: dict[str, set[str]] = {
    "make_map": {"plot_dataset"},
    "submit_download_job": {"submit_commercial_download_job"},
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _planned_tools(output: dict[str, Any]) -> list[str]:
    tools: list[str] = []
    steps = _as_list(output.get("planned_steps") or output.get("workflow_plan") or output.get("tool_plan"))
    if not steps and isinstance(output.get("plan"), dict):
        plan = _as_dict(output.get("plan"))
        steps = _as_list(plan.get("planned_steps") or plan.get("workflow_plan") or plan.get("tool_plan"))
    for step in steps:
        if not isinstance(step, dict):
            continue
        tool = _clean_text(step.get("tool_name") or step.get("tool") or step.get("name"))
        if tool:
            tools.append(tool)
    return tools


def _planner_value(output: dict[str, Any], key: str) -> Any:
    if key in output:
        return output.get(key)
    plan = _as_dict(output.get("plan"))
    return plan.get(key)


def _normalized_coordinator_decision(value: Any) -> str:
    decision = _clean_text(value)
    if decision in {"request_clarification", "request_confirmation"}:
        return "ask_user"
    return decision


def _tool_aliases(tool_name: str) -> set[str]:
    clean = _clean_text(tool_name)
    aliases = {clean}
    aliases.update(TOOL_ALIASES.get(clean, set()))
    for canonical, mapped in TOOL_ALIASES.items():
        if clean in mapped:
            aliases.add(canonical)
            aliases.update(mapped)
    return {item for item in aliases if item}


def _tool_matches(expected_tool: str, actual_tool: str) -> bool:
    expected = _clean_text(expected_tool)
    actual = _clean_text(actual_tool)
    if not expected or not actual:
        return expected == actual
    return bool(_tool_aliases(expected) & _tool_aliases(actual))


def _expected_tools_are_present(expected_tools: list[str], actual_tools: list[str]) -> bool:
    return all(any(_tool_matches(expected, actual) for actual in actual_tools) for expected in expected_tools)


def default_runtime_decision_eval_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "describe_uploaded_vector",
            "prompt": "Describe the uploaded vector layer and summarize its fields, CRS, and extent.",
            "context": {"active_dataset": {"name": "uploaded_vector", "type": "vector"}},
            "expected": {
                "task_type": "data_inspection",
                "planner_tools": ["describe_dataset"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "describe_dataset",
            },
        },
        {
            "case_id": "table_to_points",
            "prompt": "Convert my CSV table with longitude and latitude fields into a point layer.",
            "context": {"active_dataset": {"name": "stations.csv", "type": "table"}, "available_fields": ["lon", "lat", "value"]},
            "expected": {
                "task_type": "data_processing",
                "planner_tools": ["table_to_points"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "table_to_points",
            },
        },
        {
            "case_id": "soil_xgboost_modeling",
            "prompt": "Train an XGBoost model for soil moisture using station observations and raster features.",
            "context": {"active_dataset": {"name": "soil_training", "type": "table"}, "available_fields": ["soil_moisture", "ndvi"]},
            "expected": {
                "task_type": "modeling",
                "planner_tools": ["generic_xgboost_workflow"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "generic_xgboost_workflow",
            },
        },
        {
            "case_id": "artifact_download_safety",
            "prompt": "Download that previous result file for me.",
            "context": {"active_selection": {"selected_artifact": {"artifact_id": "a1"}}},
            "expected": {
                "task_type": "artifact_download",
                "planner_tools": [],
                "requires_confirmation": True,
                "coordinator_decision": "ask_user",
                "coordinator_tool": "",
            },
        },
        {
            "case_id": "vector_clip_by_boundary",
            "prompt": "Clip the parcels vector layer by the city boundary polygon.",
            "context": {
                "active_dataset": {"name": "parcels", "type": "vector"},
                "available_layers": [{"name": "city_boundary", "type": "vector"}],
            },
            "expected": {
                "task_type": "data_processing",
                "planner_tools": ["vector_clip_by_vector"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "vector_clip_by_vector",
            },
        },
        {
            "case_id": "raster_clip_by_boundary",
            "prompt": "Clip the DEM raster to the uploaded watershed boundary.",
            "context": {
                "active_dataset": {"name": "dem", "type": "raster"},
                "available_layers": [{"name": "watershed_boundary", "type": "vector"}],
            },
            "expected": {
                "task_type": "data_processing",
                "planner_tools": ["clip_raster_by_vector"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "clip_raster_by_vector",
            },
        },
        {
            "case_id": "reproject_vector_to_wgs84",
            "prompt": "Reproject the roads layer to EPSG:4326 for web mapping.",
            "context": {"active_dataset": {"name": "roads", "type": "vector", "crs": "EPSG:3857"}},
            "expected": {
                "task_type": "data_processing",
                "planner_tools": ["reproject_vector"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "reproject_vector",
            },
        },
        {
            "case_id": "raster_zonal_statistics",
            "prompt": "Calculate mean NDVI by each administrative polygon.",
            "context": {
                "active_dataset": {"name": "ndvi", "type": "raster"},
                "available_layers": [{"name": "admin_units", "type": "vector"}],
            },
            "expected": {
                "task_type": "analysis",
                "planner_tools": ["raster_zonal_stats"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "raster_zonal_stats",
            },
        },
        {
            "case_id": "map_cartography",
            "prompt": "Create a map image of the clipped land use layer colored by class.",
            "context": {
                "active_dataset": {"name": "clipped_landuse", "type": "vector"},
                "available_fields": ["class", "area"],
            },
            "expected": {
                "task_type": "cartography",
                "planner_tools": ["plot_dataset"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "plot_dataset",
            },
        },
        {
            "case_id": "gscloud_download_confirmation",
            "prompt": "Download high resolution GSCloud DEM tiles for Chengdu.",
            "context": {"download_candidates": [{"product_id": "gscloud_dem", "confirmation_required": True}]},
            "expected": {
                "task_type": "data_download",
                "planner_tools": ["submit_commercial_download_job"],
                "requires_confirmation": True,
                "coordinator_decision": "ask_user",
                "coordinator_tool": "",
            },
        },
    ]


def evaluate_runtime_planner_decisions(cases: list[dict[str, Any]], planner_outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    passed_count = 0
    for case in cases:
        case_id = _clean_text(_as_dict(case).get("case_id"))
        expected = _as_dict(_as_dict(case).get("expected"))
        output = _as_dict(planner_outputs.get(case_id))
        expected_tools = [str(item) for item in _as_list(expected.get("planner_tools"))]
        actual_tools = _planned_tools(output)
        mismatches: list[str] = []
        if _clean_text(_planner_value(output, "task_type")) != _clean_text(expected.get("task_type")):
            mismatches.append("task_type_mismatch")
        if not _expected_tools_are_present(expected_tools, actual_tools):
            mismatches.append("planner_tools_mismatch")
        if bool(_planner_value(output, "requires_confirmation")) != bool(expected.get("requires_confirmation")):
            mismatches.append("requires_confirmation_mismatch")
        passed = not mismatches
        passed_count += 1 if passed else 0
        rows.append(
            {
                "case_id": case_id,
                "passed": passed,
                "mismatches": mismatches,
                "expected_tools": expected_tools,
                "actual_tools": actual_tools,
            }
        )
    case_count = len(rows)
    return {
        "case_count": case_count,
        "passed_count": passed_count,
        "pass_rate": round(passed_count / case_count, 6) if case_count else 0.0,
        "cases": rows,
    }


def evaluate_runtime_coordinator_decisions(
    cases: list[dict[str, Any]],
    coordinator_outputs: dict[str, dict[str, Any]],
    *,
    allowed_tools_by_case: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    passed_count = 0
    for case in cases:
        case_id = _clean_text(_as_dict(case).get("case_id"))
        expected = _as_dict(_as_dict(case).get("expected"))
        output = _as_dict(coordinator_outputs.get(case_id))
        expected_decision = _normalized_coordinator_decision(expected.get("coordinator_decision"))
        actual_decision = _normalized_coordinator_decision(output.get("decision"))
        expected_tool = _clean_text(expected.get("coordinator_tool"))
        actual_tool = _clean_text(output.get("required_tool"))
        allowed_tools = [tool for tool in (allowed_tools_by_case or {}).get(case_id, []) if _clean_text(tool)]
        mismatches: list[str] = []
        if actual_decision != expected_decision:
            mismatches.append("coordinator_decision_mismatch")
        tool_matches = _tool_matches(expected_tool, actual_tool)
        if (
            not tool_matches
            and expected_decision == "continue"
            and actual_decision == "continue"
            and expected_tool
            and actual_tool
            and any(_tool_matches(allowed_tool, actual_tool) for allowed_tool in allowed_tools)
        ):
            tool_matches = True
        if not tool_matches:
            mismatches.append("coordinator_tool_mismatch")
        passed = not mismatches
        passed_count += 1 if passed else 0
        rows.append(
            {
                "case_id": case_id,
                "passed": passed,
                "mismatches": mismatches,
                "expected_decision": expected_decision,
                "actual_decision": actual_decision,
                "raw_expected_decision": _clean_text(expected.get("coordinator_decision")),
                "raw_actual_decision": _clean_text(output.get("decision")),
                "allowed_tools": allowed_tools,
            }
        )
    case_count = len(rows)
    return {
        "case_count": case_count,
        "passed_count": passed_count,
        "pass_rate": round(passed_count / case_count, 6) if case_count else 0.0,
        "cases": rows,
    }


def runtime_decision_eval_report(
    cases: list[dict[str, Any]] | None = None,
    outputs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    eval_cases = cases if isinstance(cases, list) else default_runtime_decision_eval_cases()
    output_map = outputs if isinstance(outputs, dict) else {}
    planner_outputs = {case_id: _as_dict(value).get("planner", {}) for case_id, value in output_map.items()}
    coordinator_outputs = {case_id: _as_dict(value).get("coordinator", {}) for case_id, value in output_map.items()}
    planner = evaluate_runtime_planner_decisions(eval_cases, planner_outputs)
    allowed_tools_by_case = {case_id: _planned_tools(_as_dict(output)) for case_id, output in planner_outputs.items()}
    coordinator = evaluate_runtime_coordinator_decisions(
        eval_cases,
        coordinator_outputs,
        allowed_tools_by_case=allowed_tools_by_case,
    )
    return {
        "schema_version": "runtime-decision-eval/v1",
        "case_count": len(eval_cases),
        "planner": planner,
        "coordinator": coordinator,
        "ready_for_cutover_eval": bool(eval_cases) and planner["pass_rate"] >= 0.8 and coordinator["pass_rate"] >= 0.8,
    }


def _decision_trace_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("decision_trace"), dict):
        return _as_dict(payload.get("decision_trace"))
    diagnostics = _as_dict(payload.get("diagnostics"))
    if isinstance(diagnostics.get("decision_trace"), dict):
        return _as_dict(diagnostics.get("decision_trace"))
    return payload


def _planner_tools_from_capture(planner: dict[str, Any]) -> list[str]:
    tools = [str(item) for item in _as_list(planner.get("planned_tools")) if _clean_text(item)]
    return tools or _planned_tools(planner)


def capture_runtime_decision_eval_output(case_id: str, trace_payload: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    trace = _decision_trace_from_payload(_as_dict(trace_payload))
    planner = _as_dict(trace.get("planner"))
    coordinator = _as_dict(trace.get("coordinator"))
    tools = _planner_tools_from_capture(planner)
    return {
        _clean_text(case_id): {
            "planner": {
                "task_type": _clean_text(planner.get("task_type")),
                "planned_steps": [{"tool_name": tool} for tool in tools],
                "requires_confirmation": bool(planner.get("requires_confirmation")),
            },
            "coordinator": {
                "decision": _clean_text(coordinator.get("decision")),
                "required_tool": _clean_text(coordinator.get("required_tool")),
            },
        }
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core.agent_runtime.decision_eval")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("fixtures", help="Print fixed runtime decision eval fixtures.")

    report = subcommands.add_parser("report", help="Score planner/coordinator outputs against fixed fixtures.")
    report.add_argument("--outputs", required=True, help="UTF-8 JSON file keyed by case_id with planner/coordinator outputs.")
    report.add_argument("--min-pass-rate", type=float, default=0.8)

    capture = subcommands.add_parser("capture", help="Convert a runtime decision trace JSON file into report-ready outputs.")
    capture.add_argument("--trace", required=True, help="UTF-8 JSON file containing decision_trace or diagnostics.decision_trace.")
    capture.add_argument("--case-id", required=True, help="Eval case id for the captured trace.")
    capture.add_argument("--output", required=True, help="UTF-8 JSON file to write report-ready outputs.")

    return parser


def _load_outputs(path_value: str) -> dict[str, dict[str, dict[str, Any]]]:
    path = Path(path_value).resolve(strict=False)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_json_file(path_value: str) -> dict[str, Any]:
    path = Path(path_value).resolve(strict=False)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_json_file(path_value: str, payload: dict[str, Any]) -> str:
    path = Path(path_value).resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path.name


def _with_operations(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "operations": {
            "llm_calls_performed": 0,
            "tool_calls_performed": 0,
            "live_execution": False,
        },
    }


def run_decision_eval_cli(argv: list[str] | tuple[str, ...]) -> tuple[int, dict[str, Any]]:
    args = _parser().parse_args(list(argv))
    if args.command == "fixtures":
        cases = default_runtime_decision_eval_cases()
        return 0, _with_operations(
            {
                "ok": True,
                "command": "fixtures",
                "schema_version": "runtime-decision-eval-fixtures/v1",
                "case_count": len(cases),
                "cases": cases,
            }
        )

    if args.command == "report":
        outputs = _load_outputs(args.outputs)
        report = runtime_decision_eval_report(outputs=outputs)
        min_pass_rate = float(args.min_pass_rate)
        ok = bool(report["planner"]["pass_rate"] >= min_pass_rate and report["coordinator"]["pass_rate"] >= min_pass_rate)
        report["ready_for_cutover_eval"] = ok
        return (0 if ok else 1), _with_operations(
            {
                "ok": ok,
                "command": "report",
                "schema_version": "runtime-decision-eval-report/v1",
                "outputs_filename": Path(str(args.outputs)).name,
                "thresholds": {"min_pass_rate": min_pass_rate},
                "report": report,
            }
        )

    if args.command == "capture":
        trace_payload = _load_json_file(args.trace)
        output = capture_runtime_decision_eval_output(args.case_id, trace_payload)
        output_filename = _write_json_file(args.output, output)
        return 0, _with_operations(
            {
                "ok": True,
                "command": "capture",
                "schema_version": "runtime-decision-eval-capture/v1",
                "case_count": len(output),
                "case_ids": sorted(output.keys()),
                "output_filename": output_filename,
            }
        )

    return 2, {"ok": False, "command": str(args.command or ""), "error_code": "UNKNOWN_COMMAND"}


def main(argv: list[str] | None = None) -> int:
    code, payload = run_decision_eval_cli(sys.argv[1:] if argv is None else argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
