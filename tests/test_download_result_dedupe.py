from __future__ import annotations

from core.map_layers import _download_dataset_dedupe_key, _layer_download_dedupe_key


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
