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


def _all_true(values: object) -> bool:
    if not isinstance(values, dict) or not values:
        return False
    return all(bool(value) for value in values.values())


def _admin_exposure(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("admin_exposure")
    return value if isinstance(value, dict) else {}


def _reasons(payload: dict[str, Any]) -> list[str]:
    reasons = _admin_exposure(payload).get("reasons")
    return [str(item) for item in reasons] if isinstance(reasons, list) else []


def _baseline_ready(payload: dict[str, Any]) -> bool:
    exposure = _admin_exposure(payload)
    return (
        payload.get("schema_version") == "phase53-remote-staging10-baseline/v1"
        and bool(payload.get("ok"))
        and _all_true(payload.get("checks"))
        and exposure.get("environment") == "staging"
        and int(exposure.get("requested_percent") or 0) == 10
        and bool(exposure.get("eligible_for_user_exposure"))
        and exposure.get("recommendation") == "allow_staging_exposure"
    )


def _observation_gate_ok(payload: dict[str, Any]) -> bool:
    return (
        payload.get("schema_version") == "phase52-staging10-observation-gate/v1"
        and bool(payload.get("ok"))
        and _all_true(payload.get("checks"))
    )


def _rollback_probe_confirms_block(payload: dict[str, Any]) -> bool:
    exposure = _admin_exposure(payload)
    return (
        payload.get("schema_version") == "phase53-remote-staging10-baseline/v1"
        and not bool(payload.get("ok"))
        and bool(exposure.get("rollback_requested"))
        and not bool(exposure.get("eligible_for_user_exposure"))
        and "rollback_requested" in _reasons(payload)
    )


def build_phase53_evidence_summary(
    *,
    baseline_path: str | Path,
    observation_gate_path: str | Path,
    rollback_probe_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    baseline = _read_json(baseline_path)
    observation_gate = _read_json(observation_gate_path)
    rollback_probe = _read_json(rollback_probe_path)

    checks = {
        "baseline_ready_for_staging10": _baseline_ready(baseline),
        "observation_gate_ok": _observation_gate_ok(observation_gate),
        "rollback_probe_confirms_block": _rollback_probe_confirms_block(rollback_probe),
    }
    report = {
        "schema_version": "phase53-remote-staging-evidence/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "remote_staging_10_percent_observation",
        "evidence_files": {
            "baseline": Path(baseline_path).name,
            "observation_gate": Path(observation_gate_path).name,
            "rollback_probe": Path(rollback_probe_path).name,
        },
        "checks": checks,
        "baseline": {
            "environment": _admin_exposure(baseline).get("environment"),
            "requested_percent": _admin_exposure(baseline).get("requested_percent"),
            "eligible_for_user_exposure": _admin_exposure(baseline).get("eligible_for_user_exposure"),
            "recommendation": _admin_exposure(baseline).get("recommendation"),
        },
        "observation_gate": {
            "schema_version": observation_gate.get("schema_version"),
            "ok": bool(observation_gate.get("ok")),
            "task_summary": (observation_gate.get("task_window") or {}).get("summary")
            if isinstance(observation_gate.get("task_window"), dict)
            else {},
        },
        "rollback_probe": {
            "rollback_requested": bool(_admin_exposure(rollback_probe).get("rollback_requested")),
            "eligible_for_user_exposure": bool(_admin_exposure(rollback_probe).get("eligible_for_user_exposure")),
            "reasons": _reasons(rollback_probe),
        },
    }
    report["ok"] = all(checks.values())
    _write_json(output_path, report)
    return report


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 53 remote staging observation evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize = subparsers.add_parser("summarize", help="Summarize Phase 53 remote staging evidence.")
    summarize.add_argument("--baseline", required=True)
    summarize.add_argument("--observation-gate", required=True)
    summarize.add_argument("--rollback-probe", required=True)
    summarize.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    if args.command == "summarize":
        report = build_phase53_evidence_summary(
            baseline_path=args.baseline,
            observation_gate_path=args.observation_gate,
            rollback_probe_path=args.rollback_probe,
            output_path=args.output,
        )
        print(json.dumps({"ok": report["ok"], "output_filename": Path(args.output).name, "checks": report["checks"]}, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    return 2


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
