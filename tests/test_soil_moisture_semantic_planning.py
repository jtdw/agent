from __future__ import annotations

from core.task_planner import build_task_plan


def _intent(intent: str, confidence: float = 0.86) -> dict:
    return {"intent": intent, "confidence": confidence, "secondary_intents": []}


def _ismn_card(*, variables: list[dict] | None = None) -> dict:
    return {
        "schema_version": "gis-data-semantic-card/v1",
        "dataset_name": "ismn_training_table",
        "source_kind": "ismn_archive",
        "scientific_roles": [
            "soil_moisture_observation",
            "model_target_candidate",
            "gcp_calibration_candidate",
        ],
        "variables": variables
        or [
            {"name": "soil_moisture_mean", "standard_name": "soil_moisture", "role": "target"},
            {"name": "ndvi", "standard_name": "normalized_difference_vegetation_index", "role": "feature"},
            {"name": "elevation", "standard_name": "surface_altitude", "role": "feature"},
        ],
        "spatial": {"has_coordinates": True, "lon_col": "lon", "lat_col": "lat", "crs": "EPSG:4326"},
        "temporal": {"has_time": True, "time_col": "date_time"},
        "modeling": {
            "can_train_xgboost": True,
            "can_calibrate_gcp": True,
            "recommended_target": "soil_moisture_mean",
        },
        "row_count": 128,
    }


def test_ismn_semantic_card_seeds_generic_xgboost_arguments() -> None:
    context = {
        "workspace": {"dataset_count": 1},
        "active_dataset": {"name": "ismn_training_table", "type": "table"},
        "available_fields": ["station_id", "lon", "lat", "date_time", "soil_moisture_mean", "ndvi", "elevation"],
        "numeric_fields": ["lon", "lat", "soil_moisture_mean", "ndvi", "elevation"],
        "data_semantic_cards": [_ismn_card()],
    }

    plan = build_task_plan("run soil moisture xgboost analysis", _intent("modeling"), context)

    assert plan["should_ask_clarification"] is False
    args = plan["validated_tool_args"]["generic_xgboost_workflow"]
    assert args["dataset_name"] == "ismn_training_table"
    assert args["target_col"] == "soil_moisture_mean"
    assert args["feature_cols"] == "ndvi,elevation"
    assert args["lon_col"] == "lon"
    assert args["lat_col"] == "lat"
    assert args["date_col"] == "date_time"
    assert args["split_method"] == "auto"


def test_ismn_semantic_card_does_not_fabricate_model_features() -> None:
    context = {
        "workspace": {"dataset_count": 1},
        "active_dataset": {"name": "ismn_training_table", "type": "table"},
        "available_fields": ["station_id", "lon", "lat", "date_time", "soil_moisture_mean"],
        "numeric_fields": ["lon", "lat", "soil_moisture_mean"],
        "data_semantic_cards": [
            _ismn_card(variables=[{"name": "soil_moisture_mean", "standard_name": "soil_moisture", "role": "target"}])
        ],
    }

    plan = build_task_plan("run soil moisture xgboost analysis", _intent("modeling"), context)

    assert plan["should_ask_clarification"] is True
    assert "generic_xgboost_workflow" not in plan["validated_tool_args"]
    assert "feature columns" in plan["missing_inputs"]


def test_prediction_semantic_card_routes_gcp_without_recent_model_result() -> None:
    context = {
        "workspace": {"dataset_count": 1},
        "active_dataset": {"name": "xgb_predictions", "type": "table"},
        "available_fields": [
            "soil_moisture_mean",
            "xgb_validation_prediction",
            "xgb_validation_fold",
            "date_time",
            "lon",
            "lat",
        ],
        "numeric_fields": ["soil_moisture_mean", "xgb_validation_prediction", "lon", "lat"],
        "data_semantic_cards": [
            {
                "schema_version": "gis-data-semantic-card/v1",
                "dataset_name": "xgb_predictions",
                "source_kind": "xgboost_prediction_result",
                "scientific_roles": ["model_prediction_result", "gcp_calibration_candidate"],
                "variables": [
                    {"name": "soil_moisture_mean", "role": "observed", "standard_name": "soil_moisture"},
                    {"name": "xgb_validation_prediction", "role": "prediction"},
                ],
                "spatial": {"has_coordinates": True, "lon_col": "lon", "lat_col": "lat"},
                "temporal": {"has_time": True, "time_col": "date_time"},
                "modeling": {
                    "can_calibrate_gcp": True,
                    "target_column": "soil_moisture_mean",
                    "cv_prediction_column": "xgb_validation_prediction",
                    "cv_fold_column": "xgb_validation_fold",
                },
            }
        ],
    }

    plan = build_task_plan("run GCP uncertainty analysis", _intent("modeling"), context)

    assert plan["should_ask_clarification"] is False
    args = plan["validated_tool_args"]["geographical_conformal_prediction"]
    assert args["calibration_dataset"] == "xgb_predictions"
    assert args["observed_col"] == "soil_moisture_mean"
    assert args["predicted_cols"] == "xgb_validation_prediction"
    assert args["date_col"] == "date_time"
    assert args["lon_col"] == "lon"
    assert args["lat_col"] == "lat"
    assert args["fold_col"] == "xgb_validation_fold"


def test_gcp_result_semantic_card_satisfies_result_analysis_context() -> None:
    context = {
        "workspace": {"dataset_count": 1},
        "active_dataset": {"name": "xgb_gcp_predictions", "type": "table"},
        "available_fields": ["soil_moisture_mean", "xgb_validation_prediction_gcp_width", "lon", "lat"],
        "numeric_fields": ["soil_moisture_mean", "xgb_validation_prediction_gcp_width", "lon", "lat"],
        "data_semantic_cards": [
            {
                "schema_version": "gis-data-semantic-card/v1",
                "dataset_name": "xgb_gcp_predictions",
                "source_kind": "gcp_uncertainty_result",
                "scientific_roles": ["prediction_with_uncertainty", "gcp_result", "map_ready"],
                "variables": [
                    {"name": "soil_moisture_mean", "role": "observed"},
                    {
                        "name": "xgb_validation_prediction",
                        "role": "prediction",
                        "interval_width": "xgb_validation_prediction_gcp_width",
                    },
                ],
                "spatial": {"has_coordinates": True, "lon_col": "lon", "lat_col": "lat"},
                "modeling": {"uncertainty_output": True},
            }
        ],
    }

    plan = build_task_plan("explain the GCP uncertainty result", _intent("result_analysis"), context)

    assert plan["should_ask_clarification"] is False
    assert "result object" not in plan["missing_inputs"]
    assert plan["recommended_tools"] == ["workspace_status"]


def test_gcp_result_semantic_card_seeds_uncertainty_map_field() -> None:
    context = {
        "workspace": {"dataset_count": 1},
        "active_dataset": {"name": "xgb_gcp_predictions", "type": "table"},
        "available_fields": ["soil_moisture_mean", "xgb_validation_prediction_gcp_width", "lon", "lat"],
        "numeric_fields": ["soil_moisture_mean", "xgb_validation_prediction_gcp_width", "lon", "lat"],
        "data_semantic_cards": [
            {
                "schema_version": "gis-data-semantic-card/v1",
                "dataset_name": "xgb_gcp_predictions",
                "source_kind": "gcp_uncertainty_result",
                "scientific_roles": ["prediction_with_uncertainty", "gcp_result", "map_ready"],
                "variables": [
                    {"name": "soil_moisture_mean", "role": "observed"},
                    {
                        "name": "xgb_validation_prediction",
                        "role": "prediction",
                        "interval_width": "xgb_validation_prediction_gcp_width",
                    },
                ],
                "spatial": {"has_coordinates": True, "lon_col": "lon", "lat_col": "lat"},
                "modeling": {"uncertainty_output": True},
            }
        ],
    }

    plan = build_task_plan("plot the GCP uncertainty map", _intent("map_generation"), context)

    assert plan["should_ask_clarification"] is False
    args = plan["validated_tool_args"]["plot_dataset"]
    assert args["column"] == "xgb_validation_prediction_gcp_width"
    assert plan["validated_tool_args"]["table_to_points"]["dataset_name"] == "xgb_gcp_predictions"
    assert [step["tool_name"] for step in plan["workflow_plan"]] == ["table_to_points", "plot_dataset"]
    assert "generic_xgboost_workflow" not in plan["validated_tool_args"]


def test_gcp_result_map_prompt_overrides_modeling_intent_from_gcp_keywords() -> None:
    context = {
        "workspace": {"dataset_count": 1},
        "active_dataset": {"name": "xgb_gcp_predictions", "type": "table"},
        "available_fields": ["soil_moisture_mean", "xgb_validation_prediction_gcp_width", "lon", "lat"],
        "numeric_fields": ["soil_moisture_mean", "xgb_validation_prediction_gcp_width", "lon", "lat"],
        "data_semantic_cards": [
            {
                "schema_version": "gis-data-semantic-card/v1",
                "dataset_name": "xgb_gcp_predictions",
                "source_kind": "gcp_uncertainty_result",
                "scientific_roles": ["prediction_with_uncertainty", "gcp_result", "map_ready"],
                "variables": [
                    {"name": "soil_moisture_mean", "role": "observed"},
                    {
                        "name": "xgb_validation_prediction",
                        "role": "prediction",
                        "interval_width": "xgb_validation_prediction_gcp_width",
                    },
                ],
                "spatial": {"has_coordinates": True, "lon_col": "lon", "lat_col": "lat"},
                "modeling": {"uncertainty_output": True},
            }
        ],
    }

    plan = build_task_plan("plot the GCP uncertainty map", _intent("modeling"), context)

    assert plan["task_type"] == "map_generation"
    assert plan["should_ask_clarification"] is False
    assert [step["tool_name"] for step in plan["workflow_plan"]] == ["table_to_points", "plot_dataset"]
