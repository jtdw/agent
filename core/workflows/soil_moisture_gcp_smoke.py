from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


DEFAULT_CASE_IDS = ("summer_20190715", "spring_20190515", "early_window_20190115")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _exists_nonempty(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _compact_raster_meta(value: dict[str, Any]) -> dict[str, Any]:
    keep = ("name", "exists", "crs", "width", "height", "count", "res")
    return {key: value.get(key) for key in keep if key in value}


def _prediction_summary(derived: Path, case_id: str) -> dict[str, Any]:
    path = derived / f"phase45_{case_id}_prediction_summary.json"
    if not path.exists():
        return {}
    try:
        return _read_json(path)
    except Exception:
        return {}


def build_compact_smoke_summary(source_path: str | Path) -> dict[str, Any]:
    """Compress a full Phase 45 three-sample smoke report into a recurring gate summary."""
    source = Path(source_path)
    root = source.parent
    derived = root / "workspace" / "derived"
    plots = root / "workspace" / "plots"
    payload = _read_json(source)

    cases: list[dict[str, Any]] = []
    for case in payload.get("cases", []):
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "").strip()
        if not case_id:
            continue
        pred_summary = _prediction_summary(derived, case_id)
        metrics = case.get("gcp_metrics") or []
        gcp_metrics = metrics[0] if metrics and isinstance(metrics[0], dict) else {}
        tif = derived / f"phase45_{case_id}_prediction.tif"
        png = plots / f"phase45_{case_id}_prediction.png"
        gcp_report = derived / f"phase45_{case_id}_gcp_gcp_report.md"
        cases.append(
            {
                "case_id": case_id,
                "representative_date": case.get("representative_date"),
                "ok": bool(case.get("ok")),
                "duration_seconds": case.get("duration_seconds"),
                "workflow_status": case.get("workflow_status"),
                "training_rows": case.get("row_count"),
                "model_feature_count": case.get("model_feature_count"),
                "study_area_filter": case.get("study_area_filter") or {},
                "prediction": {
                    "status": case.get("prediction_status"),
                    "valid_pixels": case.get("prediction_valid_pixels"),
                    "reference_source": pred_summary.get("reference_source"),
                    "reference_raster": pred_summary.get("reference_raster"),
                    "stats": pred_summary.get("prediction_stats") or {},
                    "tif_exists": _exists_nonempty(tif),
                    "png_exists": _exists_nonempty(png),
                },
                "gcp": {
                    "method": gcp_metrics.get("effective_method") or gcp_metrics.get("method"),
                    "target_coverage": gcp_metrics.get("target_coverage"),
                    "empirical_coverage": gcp_metrics.get("empirical_coverage"),
                    "mean_interval_width": gcp_metrics.get("mean_interval_width"),
                    "n_target": gcp_metrics.get("n_target"),
                    "fallback_code": gcp_metrics.get("fallback_code"),
                    "report_exists": _exists_nonempty(gcp_report),
                },
            }
        )

    compact = {
        "evidence_id": "soil_moisture_gcp_recurring_smoke_summary",
        "created_at": _utc_now(),
        "source_evidence": source.as_posix(),
        "overall_ok": bool(payload.get("overall_ok")) and all(case.get("ok") for case in cases),
        "input_archive": payload.get("input_archive"),
        "input_rasters": {
            str(name): _compact_raster_meta(meta)
            for name, meta in (payload.get("input_rasters") or {}).items()
            if isinstance(meta, dict)
        },
        "cases": cases,
        "runtime_summary": {
            "total_case_seconds": round(sum(float(case.get("duration_seconds") or 0) for case in cases), 3),
            "max_case_seconds": max((float(case.get("duration_seconds") or 0) for case in cases), default=0.0),
            "recommended_recurring_mode": "full_chain_once_plus_date_specific_lightweight_checks",
            "bottleneck_note": (
                "Full three-case smoke repeats training, DEM derivatives, temporal composites, raster prediction, and GCP. "
                "Use it as strong regression evidence; keep routine smoke lighter."
            ),
        },
        "phase_conclusion": {
            "ready_for_next_decision": True,
            "recommended_next_step": "Formalize the lightweight recurring smoke gate before increasing staging exposure.",
        },
    }
    return compact


def validate_smoke_summary(
    summary: dict[str, Any],
    *,
    min_cases: int = 3,
    min_empirical_coverage: float = 0.85,
    require_study_area_filter: bool = True,
) -> dict[str, Any]:
    failed: list[str] = []
    cases = [case for case in summary.get("cases", []) if isinstance(case, dict)]
    if not summary.get("overall_ok"):
        failed.append("summary.overall_ok is not true")
    if len(cases) < int(min_cases):
        failed.append(f"case_count {len(cases)} is below required {int(min_cases)}")

    seen_case_ids = {str(case.get("case_id") or "") for case in cases}
    missing_expected = [case_id for case_id in DEFAULT_CASE_IDS if case_id not in seen_case_ids]
    if int(min_cases) >= len(DEFAULT_CASE_IDS) and missing_expected:
        failed.append(f"missing expected cases: {', '.join(missing_expected)}")

    for case in cases:
        label = str(case.get("case_id") or "<unknown>")
        prediction = case.get("prediction") or {}
        gcp = case.get("gcp") or {}
        study_area = case.get("study_area_filter") or {}
        if not case.get("ok"):
            failed.append(f"{label}: case ok is not true")
        if case.get("workflow_status") != "modeled":
            failed.append(f"{label}: workflow_status is not modeled")
        if prediction.get("status") != "mapped":
            failed.append(f"{label}: prediction status is not mapped")
        if int(prediction.get("valid_pixels") or 0) <= 0:
            failed.append(f"{label}: prediction valid_pixels is zero")
        if not prediction.get("tif_exists"):
            failed.append(f"{label}: prediction tif is missing")
        if not prediction.get("png_exists"):
            failed.append(f"{label}: prediction png is missing")
        if not gcp.get("report_exists"):
            failed.append(f"{label}: GCP report is missing")
        coverage = gcp.get("empirical_coverage")
        if coverage is None or float(coverage) < float(min_empirical_coverage):
            failed.append(f"{label}: empirical_coverage {coverage} is below {float(min_empirical_coverage)}")
        if require_study_area_filter and study_area.get("filter_method") != "study_area_boundary":
            failed.append(f"{label}: study area boundary filter was not recorded")
    return {
        "ok": not failed,
        "checked_at": _utc_now(),
        "case_count": len(cases),
        "thresholds": {
            "min_cases": int(min_cases),
            "min_empirical_coverage": float(min_empirical_coverage),
            "require_study_area_filter": bool(require_study_area_filter),
        },
        "failed_checks": failed,
    }


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Soil moisture XGBoost/GCP smoke evidence utility.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    recover = subparsers.add_parser("recover-phase45", help="Compact and optionally validate a Phase 45 full smoke report.")
    recover.add_argument("--source", required=True, help="Path to phase45_real_soil_gcp_three_sample_smoke.json.")
    recover.add_argument("--output", required=True, help="Path for compact recurring smoke summary JSON.")
    recover.add_argument("--validate", action="store_true", help="Attach validation results and fail on validation errors.")
    recover.add_argument("--min-cases", type=int, default=3)
    recover.add_argument("--min-gcp-coverage", type=float, default=0.85)
    recover.add_argument("--allow-missing-study-area-filter", action="store_true")

    validate_cmd = subparsers.add_parser("validate-summary", help="Validate an existing compact smoke summary JSON.")
    validate_cmd.add_argument("--summary", required=True, help="Path to compact recurring smoke summary JSON.")
    validate_cmd.add_argument("--min-cases", type=int, default=3)
    validate_cmd.add_argument("--min-gcp-coverage", type=float, default=0.85)
    validate_cmd.add_argument("--allow-missing-study-area-filter", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "recover-phase45":
        summary = build_compact_smoke_summary(args.source)
        if args.validate:
            summary["validation"] = validate_smoke_summary(
                summary,
                min_cases=args.min_cases,
                min_empirical_coverage=args.min_gcp_coverage,
                require_study_area_filter=not args.allow_missing_study_area_filter,
            )
        _write_json(Path(args.output), summary)
        if args.validate and not summary["validation"]["ok"]:
            return 1
        return 0

    if args.command == "validate-summary":
        summary = _read_json(Path(args.summary))
        validation = validate_smoke_summary(
            summary,
            min_cases=args.min_cases,
            min_empirical_coverage=args.min_gcp_coverage,
            require_study_area_filter=not args.allow_missing_study_area_filter,
        )
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 0 if validation["ok"] else 1

    return 2


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
