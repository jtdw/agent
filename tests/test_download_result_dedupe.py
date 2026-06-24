from __future__ import annotations

from core.data_manager import DataManager
from core.map_layers import _download_dataset_dedupe_key, _layer_download_dedupe_key
from core.tools.common_helpers import _save_markdown_artifact


def test_download_dataset_dedupe_key_collapses_suffixes_and_mosaic_names() -> None:
    items = [
        {"name": "成都市_gscloud_dem_30m_1", "path": r"uploads\a_成都市_gscloud_dem_30m\成都市_gscloud_dem_30m_mosaic.tif"},
        {"name": "成都市_gscloud_dem_30m_mosaic_31_2", "path": r"uploads\b_成都市_gscloud_dem_30m_mosaic_31_2.tif"},
        {"name": "成都市_gscloud_dem_30m_35", "path": r"uploads\c_成都市_gscloud_dem_30m_35.tif"},
    ]

    keys = {_download_dataset_dedupe_key(item) for item in items}

    assert keys == {"成都市_gscloud_dem_30m"}


def test_layer_download_dedupe_key_uses_dataset_name() -> None:
    first = {"dataset_name": "成都市_gscloud_dem_30m_mosaic_36_1", "type": "raster", "meta": {}}
    second = {"dataset_name": "成都市_gscloud_dem_30m_36", "type": "raster", "meta": {}}

    assert _layer_download_dedupe_key(first) == _layer_download_dedupe_key(second)


def test_save_markdown_artifact_does_not_register_duplicate_document_datasets(tmp_path) -> None:
    manager = DataManager(tmp_path)

    first_path = _save_markdown_artifact(manager, "model_report", "# report")
    second_path = _save_markdown_artifact(manager, "model_report", "# report updated")

    docs = [item for item in manager.list_datasets() if item["type"] == "document"]
    assert first_path == second_path
    assert len(docs) == 1
