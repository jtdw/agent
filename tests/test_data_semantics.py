from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from core.config import Settings
from core.context_builder import build_conversation_context, format_context_for_agent
from core.data_manager import DataManager
from core.data_semantics import (
    attach_semantic_card_to_dataset,
    build_data_semantic_card,
    list_semantic_cards,
    sanitize_semantic_card_for_planner,
)


def test_semantic_card_sanitizer_removes_paths_rows_and_secrets() -> None:
    card = build_data_semantic_card(
        dataset_name="ismn_daily",
        source_kind="ismn_archive",
        scientific_roles=["soil_moisture_observation", "model_target_candidate"],
        variables=[
            {
                "name": "soil_moisture",
                "standard_name": "soil_moisture",
                "unit": "m3/m3",
                "role": "target",
            }
        ],
        spatial={"has_coordinates": True, "lon_col": "lon", "lat_col": "lat", "crs": "EPSG:4326"},
        temporal={"has_time": True, "time_col": "date_time", "start": "2020-01-01", "end": "2020-01-31"},
        quality={"policy": "good_or_usable_only"},
        modeling={"can_train_xgboost": True, "recommended_target": "soil_moisture"},
        lineage={
            "source_archive_path": r"E:\secret\official_ismn.zip",
            "created_by_tool": "import_ismn_soil_moisture_archive",
            "api_token": "secret-token-value",
        },
        row_count=10,
        raw_rows=[{"soil_moisture": 0.22, "cookie": "session-cookie"}],
    )

    safe = sanitize_semantic_card_for_planner(card)
    encoded = json.dumps(safe, ensure_ascii=False)

    assert safe["schema_version"] == "gis-data-semantic-card/v1"
    assert safe["dataset_name"] == "ismn_daily"
    assert safe["scientific_roles"] == ["soil_moisture_observation", "model_target_candidate"]
    assert safe["variables"][0]["name"] == "soil_moisture"
    assert safe["row_count"] == 10
    assert "E:\\secret" not in encoded
    assert "source_archive_path" not in encoded
    assert "secret-token-value" not in encoded
    assert "session-cookie" not in encoded
    assert "raw_rows" not in encoded


def test_attach_semantic_card_to_dataset_meta_and_catalog() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        manager = DataManager(Path(tmp) / "workspace")
        dataset_name = manager.put_table(
            "soil_obs",
            pd.DataFrame({"lon": [100.0], "lat": [30.0], "soil_moisture": [0.2]}),
        )
        card = build_data_semantic_card(
            dataset_name=dataset_name,
            source_kind="ismn_archive",
            scientific_roles=["soil_moisture_observation"],
            variables=[{"name": "soil_moisture", "unit": "m3/m3", "role": "target"}],
            spatial={"has_coordinates": True, "lon_col": "lon", "lat_col": "lat"},
            temporal={"has_time": False},
            modeling={"can_train_xgboost": True},
        )

        attached = attach_semantic_card_to_dataset(manager, dataset_name, card)
        cards = list_semantic_cards(manager)

        assert attached["dataset_name"] == dataset_name
        assert manager.get(dataset_name).meta["data_semantic_card"]["schema_version"] == "gis-data-semantic-card/v1"
        assert len(cards) == 1
        assert cards[0]["dataset_name"] == dataset_name
        assert cards[0]["source_kind"] == "ismn_archive"


def test_context_builder_exposes_only_sanitized_semantic_cards() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(api_key="", workdir=Path(tmp) / "workspace")
        manager = DataManager(settings.workdir)
        dataset_name = manager.put_table(
            "soil_obs",
            pd.DataFrame({"lon": [100.0], "lat": [30.0], "soil_moisture": [0.2]}),
        )
        card = build_data_semantic_card(
            dataset_name=dataset_name,
            source_kind="ismn_archive",
            scientific_roles=["soil_moisture_observation", "gcp_calibration_candidate"],
            variables=[{"name": "soil_moisture", "unit": "m3/m3", "role": "target"}],
            spatial={"has_coordinates": True, "lon_col": "lon", "lat_col": "lat"},
            temporal={"has_time": True, "time_col": "date_time"},
            modeling={"can_train_xgboost": True, "can_calibrate_gcp": True},
            lineage={"source_archive_path": r"E:\secret\official_ismn.zip"},
            raw_rows=[{"soil_moisture": 0.2}],
        )
        attach_semantic_card_to_dataset(manager, dataset_name, card)

        context = build_conversation_context(
            "train soil moisture model",
            {"intent": "modeling", "confidence": 0.9},
            {"active_dataset": dataset_name},
            manager,
            {"summary": {"dataset_count": 1}},
        )
        payload = json.loads(format_context_for_agent(context))
        encoded = json.dumps(payload, ensure_ascii=False)
        semantic_encoded = json.dumps(payload["data_semantic_cards"], ensure_ascii=False)

        assert payload["data_semantic_cards"][0]["dataset_name"] == dataset_name
        assert payload["data_semantic_cards"][0]["scientific_roles"] == [
            "soil_moisture_observation",
            "gcp_calibration_candidate",
        ]
        assert "E:\\secret" not in encoded
        assert "source_archive_path" not in semantic_encoded
        assert "raw_rows" not in semantic_encoded
