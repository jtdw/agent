from __future__ import annotations

import json
from pathlib import Path

from core.workflows.soil_moisture_gcp_smoke import (
    build_compact_smoke_summary,
    run_cli,
    validate_smoke_summary,
)


def _write_phase45_fixture(root: Path) -> Path:
    derived = root / "workspace" / "derived"
    plots = root / "workspace" / "plots"
    derived.mkdir(parents=True)
    plots.mkdir(parents=True)
    cases = [
        ("summer_20190715", "2019-07-15", 742),
        ("spring_20190515", "2019-05-15", 742),
        ("early_window_20190115", "2019-01-15", 725),
    ]
    payload_cases = []
    for case_id, representative_date, valid_pixels in cases:
        (derived / f"phase45_{case_id}_prediction.tif").write_bytes(b"tif")
        (plots / f"phase45_{case_id}_prediction.png").write_bytes(b"png")
        (derived / f"phase45_{case_id}_gcp_gcp_report.md").write_text("report", encoding="utf-8")
        (derived / f"phase45_{case_id}_prediction_summary.json").write_text(
            json.dumps(
                {
                    "overall_ok": True,
                    "reference_source": "coarsest_feature_raster",
                    "reference_raster": f"phase45_{case_id}_raster_precip_daily_sum_3d_prediction_feature",
                    "prediction_stats": {"min": 0.1, "mean": 0.2, "median": 0.2, "max": 0.3},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        payload_cases.append(
            {
                "case_id": case_id,
                "representative_date": representative_date,
                "ok": True,
                "duration_seconds": 100.0,
                "workflow_status": "modeled",
                "row_count": 9513,
                "model_feature_count": 14,
                "study_area_filter": {
                    "boundary_dataset": "shandianhe_basin_boundary",
                    "filter_method": "study_area_boundary",
                    "removed_station_count": 7,
                    "removed_stations": ["L1", "L13", "L3", "L4", "L5", "M2", "M8"],
                },
                "prediction_status": "mapped",
                "prediction_valid_pixels": valid_pixels,
                "gcp_metrics": [
                    {
                        "method": "spatially_weighted_gcp",
                        "effective_method": "spatially_weighted_gcp",
                        "target_coverage": 0.9,
                        "empirical_coverage": 0.8919,
                        "mean_interval_width": 0.3145,
                        "n_target": 2045,
                        "fallback_code": "",
                    }
                ],
            }
        )
    source = root / "phase45_real_soil_gcp_three_sample_smoke.json"
    source.write_text(
        json.dumps(
            {
                "smoke_id": "phase45_real_soil_gcp_three_sample_smoke",
                "overall_ok": True,
                "input_archive": "stations.zip",
                "input_rasters": {
                    "dem": {"name": "dem.tif", "exists": True, "crs": "EPSG:32650", "count": 1},
                    "ndvi_daily": {"name": "ndvi.tif", "exists": True, "crs": "EPSG:4326", "count": 365},
                },
                "cases": payload_cases,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return source


def test_build_compact_smoke_summary_validates_three_real_cases(tmp_path: Path) -> None:
    source = _write_phase45_fixture(tmp_path)

    summary = build_compact_smoke_summary(source)
    validation = validate_smoke_summary(summary, min_cases=3, min_empirical_coverage=0.85)

    assert summary["overall_ok"] is True
    assert summary["runtime_summary"]["total_case_seconds"] == 300.0
    assert [case["case_id"] for case in summary["cases"]] == [
        "summer_20190715",
        "spring_20190515",
        "early_window_20190115",
    ]
    assert summary["cases"][0]["prediction"]["tif_exists"] is True
    assert summary["cases"][0]["prediction"]["png_exists"] is True
    assert summary["cases"][0]["gcp"]["report_exists"] is True
    assert validation["ok"] is True
    assert validation["failed_checks"] == []


def test_validate_smoke_summary_reports_coverage_failures(tmp_path: Path) -> None:
    source = _write_phase45_fixture(tmp_path)
    summary = build_compact_smoke_summary(source)

    validation = validate_smoke_summary(summary, min_cases=3, min_empirical_coverage=0.9)

    assert validation["ok"] is False
    assert any("empirical_coverage" in item for item in validation["failed_checks"])


def test_run_cli_recovers_and_validates_phase45_evidence(tmp_path: Path) -> None:
    source = _write_phase45_fixture(tmp_path)
    output = tmp_path / "compact.json"

    exit_code = run_cli(
        [
            "recover-phase45",
            "--source",
            str(source),
            "--output",
            str(output),
            "--validate",
            "--min-gcp-coverage",
            "0.85",
        ]
    )

    assert exit_code == 0
    recovered = json.loads(output.read_text(encoding="utf-8"))
    assert recovered["overall_ok"] is True
    assert recovered["validation"]["ok"] is True
