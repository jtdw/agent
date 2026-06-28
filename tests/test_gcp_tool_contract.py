from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from core.config import Settings
from core.gcp_uncertainty import run_gcp_uncertainty_analysis
from core.service import GISWorkspaceService
from core.tool_contracts import parse_tool_result
from core.tools.registry import build_tools


def _prediction_frame(rows: int = 36, *, with_coords: bool = True) -> pd.DataFrame:
    payload = {
        "observed": [float(i) for i in range(rows)],
        "pred": [float(i) + (0.25 if i % 2 else -0.15) for i in range(rows)],
        "fold": [i % 4 for i in range(rows)],
    }
    if with_coords:
        payload["lon"] = [100.0 + (i % 9) * 0.01 for i in range(rows)]
        payload["lat"] = [30.0 + (i // 9) * 0.01 for i in range(rows)]
    return pd.DataFrame(payload)


def test_gcp_core_reports_explicit_methods_and_fallback_diagnostics() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        spatial = run_gcp_uncertainty_analysis(
            data=_prediction_frame(with_coords=True),
            observed_col="observed",
            predicted_col="pred",
            output_name="gcp_spatial",
            output_dir=Path(tmp),
            lon_col="lon",
            lat_col="lat",
            spatial_weighting=True,
        )
        fallback = run_gcp_uncertainty_analysis(
            data=_prediction_frame(with_coords=False),
            observed_col="observed",
            predicted_col="pred",
            output_name="gcp_fallback",
            output_dir=Path(tmp),
            lon_col="lon",
            lat_col="lat",
            spatial_weighting=True,
        )

        assert spatial["metrics"]["method"] == "spatially_weighted_gcp"
        assert spatial["fallback_diagnostics"]["used_fallback"] is False
        assert {"gcp_local_quantile", "gcp_method", "gcp_interval_score"}.issubset(spatial["predictions"].columns)

        assert fallback["metrics"]["method"] == "global_split_conformal_fallback"
        assert fallback["fallback_diagnostics"]["used_fallback"] is True
        assert fallback["fallback_diagnostics"]["code"] == "GCP_COORDINATES_MISSING_GLOBAL_FALLBACK"
        assert set(fallback["predictions"]["gcp_fallback_code"].dropna().unique()) == {"GCP_COORDINATES_MISSING_GLOBAL_FALLBACK"}


def test_geographical_conformal_prediction_attaches_result_semantic_card() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
        service.manager.put_table("prediction_table", _prediction_frame(with_coords=False))
        tools = {tool.name: tool for tool in build_tools(service.manager)}

        result = parse_tool_result(
            tools["geographical_conformal_prediction"].invoke(
                {
                    "calibration_dataset": "prediction_table",
                    "observed_col": "observed",
                    "predicted_cols": "pred",
                    "output_name": "gcp_contract",
                    "lon_col": "lon",
                    "lat_col": "lat",
                    "spatial_weighting": True,
                    "alpha": 0.1,
                }
            )
        )

        assert result is not None
        assert result["ok"] is True, result
        outputs = result["outputs"]
        record = service.manager.get(outputs["result_dataset"])
        card = record.meta["data_semantic_card"]

        assert outputs["methods"] == ["global_split_conformal_fallback"]
        assert outputs["fallback_diagnostics"][0]["code"] == "GCP_COORDINATES_MISSING_GLOBAL_FALLBACK"
        assert outputs["semantic_card"]["dataset_name"] == outputs["result_dataset"]
        assert "gcp_result" in card["scientific_roles"]
        assert "prediction_with_uncertainty" in card["scientific_roles"]
        assert card["modeling"]["gcp_method"] == "global_split_conformal_fallback"
