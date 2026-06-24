from __future__ import annotations

from core.domestic_sources.gscloud_landsat import parse_landsat_cells
from core.domestic_sources.gscloud_mod021km import parse_mod021km_cells
from core.domestic_sources.gscloud_modev1f import parse_modev1f_cells
from core.domestic_sources.gscloud_modl1d import parse_modl1d_cells
from core.domestic_sources.gscloud_modnd1d import parse_modnd1d_cells
from core.domestic_sources.gscloud_sentinel2 import parse_sentinel2_cells


def test_modis_scene_parsers_normalize_datetime_cells_to_dates() -> None:
    cases = [
        (
            parse_modnd1d_cells,
            ["1", "MODND1T.20160511.CN.NDVI.MAX.V2", "2016-05-11 00:00:00", "104.5003", "32.5004", "有"],
        ),
        (
            parse_modl1d_cells,
            ["1", "MODL1D.20160517.CN.LTD.V2", "2016-05-17 00:00:00", "104.5003", "32.5004", "有"],
        ),
        (
            parse_modev1f_cells,
            ["1", "MODEV1T.20160511.CN.EVI.MAX.V2", "2016-05-11 00:00:00", "104.5003", "32.5004", "有"],
        ),
        (
            parse_mod021km_cells,
            ["1", "MOD021KM.A2010228.1550.005", "2010-08-16 00:00:00", "95", "32", "有"],
        ),
    ]

    for parser, cells in cases:
        row = parser(cells, row_index=0)
        assert row is not None
        assert row["date"].count("-") == 2
        assert len(row["date"]) == 10
        assert row["year"] == row["date"][:4]


def test_scene_parsers_fallback_to_identifier_dates_when_date_cell_missing() -> None:
    modnd = parse_modnd1d_cells(["1", "MODND1T.20160511.CN.NDVI.MAX.V2", "", "104.5003", "32.5004", "有"], row_index=0)
    evi = parse_modev1f_cells(["1", "MODEV1T.20160511.CN.EVI.MAX.V2", "", "104.5003", "32.5004", "有"], row_index=0)
    mod021 = parse_mod021km_cells(["1", "MOD021KM.A2010228.1550.005", "", "95", "32", "有"], row_index=0)

    assert modnd is not None
    assert evi is not None
    assert mod021 is not None
    assert modnd["date"] == "2016-05-11"
    assert evi["date"] == "2016-05-11"
    assert mod021["date"] == "2010-08-16"


def test_satellite_scene_parsers_normalize_datetime_cells_to_dates() -> None:
    sentinel = parse_sentinel2_cells(
        [
            "1",
            "S2C_MSIL2A_20251123T060201_N0511_R091_T43SDC_20251123T093615.SAFE",
            "2025-11-23 00:00:00",
            "73.9297",
            "38.6235",
            "有",
        ],
        row_index=0,
    )
    landsat = parse_landsat_cells(
        ["1", "LC81290392020123LGN00", "129", "39", "2020-05-02 00:00:00", "12.5", "104.1", "30.7", "有"],
        row_index=0,
    )

    assert sentinel is not None
    assert landsat is not None
    assert sentinel["date"] == "2025-11-23"
    assert sentinel["year"] == "2025"
    assert landsat["date"] == "2020-05-02"
    assert landsat["year"] == "2020"
