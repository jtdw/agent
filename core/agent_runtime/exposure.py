from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import _env_flag


def _as_percent(value: str | int | float | None) -> int:
    try:
        number = int(float(value if value is not None else 0))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))


def _smoke_report_status(path: str | Path | None) -> dict[str, Any]:
    clean = Path(path) if path else None
    if clean is None or not str(clean).strip():
        return {
            "required": True,
            "status": "missing_report",
            "report_filename": "",
            "passed": 0,
            "failed": 0,
            "ready_for_next_phase": False,
        }
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(clean.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "required": True,
            "status": "missing_report",
            "report_filename": clean.name,
            "passed": 0,
            "failed": 0,
            "ready_for_next_phase": False,
        }
    except (OSError, json.JSONDecodeError):
        return {
            "required": True,
            "status": "invalid_report",
            "report_filename": clean.name,
            "passed": 0,
            "failed": 0,
            "ready_for_next_phase": False,
        }
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    ready = bool(summary.get("ready_for_next_phase"))
    return {
        "required": True,
        "status": "passed" if ready and failed == 0 and passed > 0 else "failed",
        "report_filename": clean.name,
        "passed": passed,
        "failed": failed,
        "ready_for_next_phase": ready,
    }


def _human_reason(reason: str) -> str:
    labels = {
        "active_guard_not_effective": "Active guard is not effective. Check GIS_AGENT_RUNTIME_V2, GIS_AGENT_RUNTIME_MODE, and GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER.",
        "rollback_requested": "Rollback is requested. Keep user exposure blocked until GIS_AGENT_RUNTIME_ROLLBACK is cleared.",
        "observe_only_no_user_exposure": "Exposure percent is 0, so the runtime is observe-only.",
        "deterministic_smoke_not_passed": "Deterministic active smoke report is missing or failed.",
        "llm_smoke_not_passed": "LLM coordinator smoke is required but missing or failed.",
        "production_exposure_requires_override": "Production exposure requires GIS_AGENT_RUNTIME_ALLOW_PRODUCTION_EXPOSURE=1.",
        "staging_initial_exposure_limited_to_10_percent": "Initial staging exposure is limited to 10%.",
        "unknown_exposure_environment": "Exposure environment must be local, staging, or production.",
    }
    return labels.get(reason, reason)


def _next_actions(reasons: list[str], eligible: bool, environment: str) -> list[str]:
    if eligible:
        if environment == "staging":
            return ["Continue staging rollout at the requested percentage.", "Keep rollback ready with GIS_AGENT_RUNTIME_ROLLBACK=1."]
        if environment == "production":
            return ["Proceed only after production approval and rollback window are confirmed."]
        return ["Continue observe-only validation."]
    actions: list[str] = []
    if "deterministic_smoke_not_passed" in reasons:
        actions.append("Run scripts/test_agent_runtime_active_smoke.ps1 and point GIS_AGENT_RUNTIME_SMOKE_REPORT to the passing report.")
    if "active_guard_not_effective" in reasons:
        actions.append("Enable guarded active mode before staging exposure.")
    if "rollback_requested" in reasons:
        actions.append("Clear GIS_AGENT_RUNTIME_ROLLBACK only after the incident or validation issue is resolved.")
    if "observe_only_no_user_exposure" in reasons:
        actions.append("Set GIS_AGENT_RUNTIME_EXPOSURE_PERCENT to 1 for the first staging dry-run.")
    if "llm_smoke_not_passed" in reasons:
        actions.append("Run scripts/test_agent_runtime_active_smoke.ps1 -IncludeLlmCoordinatorSmoke or disable the LLM smoke requirement.")
    if not actions:
        actions.append("Review blocking reasons and keep user exposure disabled.")
    return actions


@dataclass(frozen=True, slots=True)
class AgentRuntimeExposurePolicy:
    environment: str = "local"
    requested_percent: int = 0
    rollback_requested: bool = False
    deterministic_smoke_report: str | Path | None = None
    require_llm_smoke: bool = False
    llm_smoke_reports: tuple[str | Path, ...] = ()
    allow_production_exposure: bool = False

    @classmethod
    def from_env(cls) -> "AgentRuntimeExposurePolicy":
        llm_reports = tuple(
            item.strip()
            for item in os.getenv("GIS_AGENT_RUNTIME_LLM_SMOKE_REPORTS", "").split(",")
            if item.strip()
        )
        return cls(
            environment=(os.getenv("GIS_AGENT_RUNTIME_EXPOSURE_ENV", "local").strip().lower() or "local"),
            requested_percent=_as_percent(os.getenv("GIS_AGENT_RUNTIME_EXPOSURE_PERCENT")),
            rollback_requested=_env_flag("GIS_AGENT_RUNTIME_ROLLBACK", default=False),
            deterministic_smoke_report=os.getenv("GIS_AGENT_RUNTIME_SMOKE_REPORT", "").strip() or None,
            require_llm_smoke=_env_flag("GIS_AGENT_RUNTIME_REQUIRE_LLM_SMOKE", default=False),
            llm_smoke_reports=llm_reports,
            allow_production_exposure=_env_flag("GIS_AGENT_RUNTIME_ALLOW_PRODUCTION_EXPOSURE", default=False),
        )

    def evaluate(self, cutover_guard: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        deterministic = _smoke_report_status(self.deterministic_smoke_report)
        llm_reports = [_smoke_report_status(path) for path in self.llm_smoke_reports]
        llm_passed = bool(llm_reports) and all(item["status"] == "passed" for item in llm_reports)

        if not bool(cutover_guard.get("active_effective")):
            reasons.append("active_guard_not_effective")
        if self.rollback_requested:
            reasons.append("rollback_requested")
        if self.requested_percent <= 0:
            reasons.append("observe_only_no_user_exposure")
        if deterministic["status"] != "passed":
            reasons.append("deterministic_smoke_not_passed")
        if self.require_llm_smoke and not llm_passed:
            reasons.append("llm_smoke_not_passed")
        if self.environment == "production" and not self.allow_production_exposure:
            reasons.append("production_exposure_requires_override")
        if self.environment == "staging" and self.requested_percent > 10:
            reasons.append("staging_initial_exposure_limited_to_10_percent")
        if self.environment not in {"local", "staging", "production"}:
            reasons.append("unknown_exposure_environment")

        eligible = len(reasons) == 0
        recommendation = "allow_staging_exposure" if eligible and self.environment == "staging" else "observe_only"
        if eligible and self.environment == "production":
            recommendation = "allow_production_exposure"
        if reasons:
            recommendation = "do_not_expose_users"
        llm_status = "passed" if llm_passed else ("missing_report" if self.require_llm_smoke else "not_required")

        return {
            "schema_version": "agent-runtime-exposure-policy/v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "environment": self.environment,
            "requested_percent": _as_percent(self.requested_percent),
            "rollback_requested": bool(self.rollback_requested),
            "eligible_for_user_exposure": eligible,
            "recommendation": recommendation,
            "reasons": reasons,
            "blocking_reasons_human": [_human_reason(reason) for reason in reasons],
            "required_reports": {
                "deterministic_smoke": True,
                "llm_smoke": bool(self.require_llm_smoke),
            },
            "deterministic_smoke": deterministic,
            "llm_smoke": {
                "required": bool(self.require_llm_smoke),
                "status": llm_status,
                "reports": llm_reports,
            },
            "next_actions": _next_actions(reasons, eligible, self.environment),
        }


def agent_runtime_exposure_report() -> dict[str, Any]:
    from .config import AgentRuntimeConfig

    config = AgentRuntimeConfig.from_env()
    return AgentRuntimeExposurePolicy.from_env().evaluate(config.cutover_guard())


def run_staging_exposure_dry_run(
    *,
    output_path: str | Path,
    environment: str = "staging",
    percent: int = 1,
    smoke_report: str | Path = "outputs/agent_runtime_service_active_smoke_guard.json",
    cutover_guard: dict[str, Any] | None = None,
    require_llm_smoke: bool = False,
    llm_smoke_reports: tuple[str | Path, ...] = (),
) -> dict[str, Any]:
    if cutover_guard is None:
        from .config import AgentRuntimeConfig

        cutover_guard = AgentRuntimeConfig.from_env().cutover_guard()
    exposure = AgentRuntimeExposurePolicy(
        environment=environment,
        requested_percent=percent,
        rollback_requested=False,
        deterministic_smoke_report=smoke_report,
        require_llm_smoke=require_llm_smoke,
        llm_smoke_reports=llm_smoke_reports,
        allow_production_exposure=False,
    ).evaluate(cutover_guard)
    evidence = {
        "schema_version": "agent-runtime-staging-exposure-dry-run/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "exposure": exposure,
        "operations": {
            "llm_calls_performed": 0,
            "tool_calls_performed": 0,
            "live_traffic_changed": False,
        },
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return evidence


def run_exposure_cli(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = argparse.ArgumentParser(prog="python -m core.agent_runtime.exposure")
    subcommands = parser.add_subparsers(dest="command", required=True)
    dry_run = subcommands.add_parser("staging-dry-run")
    dry_run.add_argument("--output", required=True)
    dry_run.add_argument("--environment", default="staging")
    dry_run.add_argument("--percent", type=int, default=1)
    dry_run.add_argument("--smoke-report", default="outputs/agent_runtime_service_active_smoke_guard.json")
    dry_run.add_argument("--active-effective", action="store_true")
    dry_run.add_argument("--require-llm-smoke", action="store_true")
    dry_run.add_argument("--llm-smoke-report", action="append", dest="llm_smoke_reports", default=[])
    args = parser.parse_args(argv)

    if args.command == "staging-dry-run":
        guard = {"active_effective": True} if args.active_effective else None
        evidence = run_staging_exposure_dry_run(
            output_path=args.output,
            environment=args.environment,
            percent=args.percent,
            smoke_report=args.smoke_report,
            cutover_guard=guard,
            require_llm_smoke=bool(args.require_llm_smoke),
            llm_smoke_reports=tuple(args.llm_smoke_reports or ()),
        )
        payload = {
            "ok": bool(evidence["exposure"].get("eligible_for_user_exposure")),
            "schema_version": "agent-runtime-staging-exposure-dry-run-cli/v1",
            "output_filename": Path(args.output).name,
            "eligible_for_user_exposure": bool(evidence["exposure"].get("eligible_for_user_exposure")),
            "recommendation": evidence["exposure"].get("recommendation"),
            "operations": evidence["operations"],
        }
        return (0 if payload["ok"] else 1), payload
    return 2, {"ok": False, "error": "unknown_command"}


def main() -> None:
    code, payload = run_exposure_cli()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
