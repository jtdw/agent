import unittest

from core.domestic_sources.gscloud_landsat import parse_landsat_cells, select_landsat_records


class GSCloudLandsatTests(unittest.TestCase):
    def test_parse_landsat_row(self):
        row = parse_landsat_cells(
            ["1", "LC81290392020123LGN00", "129", "39", "2020-05-02", "12.5", "104.1", "30.7", "\u6709"],
            row_index=0,
        )

        self.assertIsNotNone(row)
        self.assertEqual(row["scene_id"], "LC81290392020123LGN00")
        self.assertEqual(row["path"], 129)
        self.assertEqual(row["row"], 39)
        self.assertEqual(row["date"], "2020-05-02")
        self.assertEqual(row["year"], "2020")
        self.assertEqual(row["cloud"], 12.5)
        self.assertEqual(row["longitude"], 104.1)
        self.assertEqual(row["latitude"], 30.7)
        self.assertEqual(row["data_available"], "\u6709")

    def test_select_landsat_prefers_nearest_low_cloud_record(self):
        records = [
            {
                "scene_id": "LC81290392020123LGN00",
                "date": "2020-05-02",
                "year": "2020",
                "cloud": 12.0,
                "longitude": 104.1,
                "latitude": 30.7,
                "data_available": "\u6709",
            },
            {
                "scene_id": "LC80010012020123LGN00",
                "date": "2020-05-03",
                "year": "2020",
                "cloud": 1.0,
                "longitude": 80.0,
                "latitude": 20.0,
                "data_available": "\u6709",
            },
        ]

        selected, candidates = select_landsat_records(records, region="成都", cloud_max=30, max_scenes=1)

        self.assertEqual(selected[0]["scene_id"], "LC81290392020123LGN00")
        self.assertEqual(len(candidates), 2)

    def test_select_landsat_skips_unavailable_and_high_cloud(self):
        records = [
            {"scene_id": "LC8_unavailable", "date": "2020-05-02", "year": "2020", "cloud": 1.0, "data_available": "\u65e0"},
            {"scene_id": "LC8_cloudy", "date": "2020-05-03", "year": "2020", "cloud": 80.0, "data_available": "\u6709"},
            {"scene_id": "LC8_clear", "date": "2020-05-04", "year": "2020", "cloud": 10.0, "data_available": "\u6709"},
        ]

        selected, candidates = select_landsat_records(records, region="成都", cloud_max=30, max_scenes=3)

        self.assertEqual([item["scene_id"] for item in selected], ["LC8_clear"])
        self.assertEqual(len([item for item in candidates if item.get("skip_reason")]), 2)


if __name__ == "__main__":
    unittest.main()
