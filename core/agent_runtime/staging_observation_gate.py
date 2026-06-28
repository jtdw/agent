from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    safe = case.get("safe_tool_execution") if isinstance(case.get("safe_tool_execution"), dict) else {}
    presentation = case.get("presentation_contract") if isinstance(case.get("presentation_contract"), dict) else {}
    return {
        "case_id": case.get("case_id"),
        "ok": bool(case.get("ok")),
        "status": case.get("status"),
        "executed_tools": case.get("executed_tools") if isinstance(case.get("executed_tools"), list) else [],
        "external_download_tools_executed": safe.get("external_download_tools_executed") if isinstance(safe.get("external_download_tools_executed"), list) else [],
        "artifact_count": int(safe.get("artifact_count") or 0),
        "image_count": int(safe.get("image_count") or 0),
        "presentation_status": presentation.get("status"),
        "artifact_types": presentation.get("artifact_types") if isinstance(presentation.get("artifact_types"), list) else [],
        "has_prediction_raster": bool(presentation.get("has_prediction_raster")),
        "has_summary_json": bool(presentation.get("has_summary_json")),
        "result_highlights": presentation.get("result_highlights") if isinstance(presentation.get("result_highlights"), list) else [],
    }


def build_observation_gate_summary(
    *,
    phase49_path: str | Path,
    phase50_path: str | Path,
    phase51_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    phase49 = _read_json(phase49_path)
    phase50 = _read_json(phase50_path)
    phase51 = _read_json(phase51_path)
    task_cases = [_case_summary(case) for case in phase51.get("cases", []) if isinstance(case, dict)]
    phase50_cases = phase50.get("cases") if isinstance(phase50.get("cases"), list) else []
    phase51_summary = phase51.get("summary") if isinstance(phase51.get("summary"), dict) else {}

    checks = {
        "phase49_policy_and_routing_ok": bool(phase49.get("ok")),
        "phase50_service_routing_ok": bool(phase50.get("ok")),
        "phase51_quality_window_ok": bool(phase51_summary.get("ready_for_next_phase")) and int(phase51_summary.get("failed") or 0) == 0,
        "phase51_has_three_cases": int(phase51_summary.get("case_count") or 0) >= 3,
        "no_external_download_tools": all(not case["external_download_tools_executed"] for case in task_cases),
        "all_cases_have_artifacts": all(int(case["artifact_count"] or 0) > 0 for case in task_cases),
        "xgboost_case_has_prediction_raster": any(
            case["case_id"] == "xgboost_raster_prediction_map"
            and case["has_prediction_raster"]
            and case["has_summary_json"]
            for case in task_cases
        ),
    }
    report = {
        "schema_version": "phase52-staging10-observation-gate/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "staging_10_percent_observation_gate",
        "inputs": {
            "phase49_observation": Path(phase49_path).name,
            "phase50_routed_request_smoke": Path(phase50_path).name,
            "phase51_task_window": Path(phase51_path).name,
        },
        "exposure": phase49.get("admin_exposure") if isinstance(phase49.get("admin_exposure"), dict) else {},
        "routing": {
            "phase49_sample_count": (phase49.get("routing_sample") or {}).get("sample_count") if isinstance(phase49.get("routing_sample"), dict) else None,
            "phase49_selected_percent": (phase49.get("routing_sample") or {}).get("selected_percent") if isinstance(phase49.get("routing_sample"), dict) else None,
            "phase50_inside_active": bool(((phase50_cases[0] if len(phase50_cases) > 0 and isinstance(phase50_cases[0], dict) else {}).get("routing") or {}).get("use_active_runtime")),
            "phase50_outside_active": bool(((phase50_cases[1] if len(phase50_cases) > 1 and isinstance(phase50_cases[1], dict) else {}).get("routing") or {}).get("use_active_runtime")),
        },
        "task_window": {
            "summary": phase51_summary,
            "cases": task_cases,
        },
        "checks": checks,
        "rollback": phase49.get("rollback") if isinstance(phase49.get("rollback"), dict) else {},
    }
    report["ok"] = all(checks.values())
    _write_json(output_path, report)
    return report


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build staging 10% observation gate summaries.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize = subparsers.add_parser("summarize", help="Summarize Phase49/50/51 observation evidence.")
    summarize.add_argument("--phase49", required=True)
    summarize.add_argument("--phase50", required=True)
    summarize.add_argument("--phase51", required=True)
    summarize.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    if args.command == "summarize":
        report = build_observation_gate_summary(
            phase49_path=args.phase49,
            phase50_path=args.phase50,
            phase51_path=args.phase51,
            output_path=args.output,
        )
        print(json.dumps({"ok": report["ok"], "output_filename": Path(args.output).name, "checks": report["checks"]}, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    return 2


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
