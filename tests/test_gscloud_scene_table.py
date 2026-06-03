import unittest

from core.domestic_sources.gscloud_scene_table import DOWNLOAD_BUTTON_SELECTORS, find_scene_row_by_id, select_scene_records


def _record(scene_id: str, date: str, page_no: int, data_available: str = "\u6709", level: str = "MSIL2A"):
    return {
        "scene_id": scene_id,
        "date": date,
        "year": date[:4],
        "data_available": data_available,
        "processing_level": level,
        "page_no": page_no,
        "row_index": 0,
        "row_text": scene_id,
    }


class GSCloudSceneTableTests(unittest.TestCase):
    def test_download_button_selectors_cover_gscloud_image_button(self):
        selectors = ", ".join(DOWNLOAD_BUTTON_SELECTORS)

        self.assertIn(".download-img", selectors)
        self.assertIn("img[title*='下载']", selectors)
        self.assertIn("img[value*='下载']", selectors)

    def test_finds_scene_row_by_id(self):
        class FakeRow:
            def __init__(self, text: str):
                self.text = text

            def inner_text(self, timeout=3000):
                return self.text

        rows = [
            FakeRow("1 MOD021KM.A2010228.0635.005 2010-08-16"),
            FakeRow("2 MOD021KM.A2010228.1550.005 2010-08-16"),
        ]

        found = find_scene_row_by_id(rows, "MOD021KM.A2010228.1550.005")

        self.assertIs(found, rows[1])

    def test_returns_none_when_scene_row_missing(self):
        class FakeRow:
            def inner_text(self, timeout=3000):
                return "MODEV1F.20160516.CN.EVI.MAX.V2"

        self.assertIsNone(find_scene_row_by_id([FakeRow()], "MODEV1F.20160511.CN.EVI.MAX.V2"))

    def test_selects_records_across_pages(self):
        records = [
            _record("S2A_MSIL2A_old.SAFE", "2024-01-01", 1),
            _record("S2B_MSIL2A_new.SAFE", "2024-02-01", 3),
        ]

        selected, candidates = select_scene_records(records, max_scenes=2)

        self.assertEqual([item["scene_id"] for item in selected], ["S2B_MSIL2A_new.SAFE", "S2A_MSIL2A_old.SAFE"])
        self.assertEqual(len(candidates), 2)
        self.assertEqual(selected[0]["page_no"], 3)

    def test_skips_unavailable_rows(self):
        records = [
            _record("S2A_MSIL2A_available.SAFE", "2024-01-01", 1, data_available="\u6709"),
            _record("S2B_MSIL2A_unavailable.SAFE", "2024-02-01", 2, data_available="\u65e0"),
        ]

        selected, candidates = select_scene_records(records, max_scenes=5)

        self.assertEqual([item["scene_id"] for item in selected], ["S2A_MSIL2A_available.SAFE"])
        skipped = [item for item in candidates if item.get("skip_reason")]
        self.assertEqual(len(skipped), 1)
        self.assertIn("数据", skipped[0]["skip_reason"])

    def test_respects_processing_level_filter(self):
        records = [
            _record("S2A_MSIL1C_scene.SAFE", "2024-02-01", 1, level="MSIL1C"),
            _record("S2B_MSIL2A_scene.SAFE", "2024-01-01", 2, level="MSIL2A"),
        ]

        selected, _ = select_scene_records(
            records,
            max_scenes=5,
            extra_filter=lambda item: item.get("processing_level") == "MSIL2A",
            extra_skip_reason="处理级别不是 MSIL2A。",
        )

        self.assertEqual([item["scene_id"] for item in selected], ["S2B_MSIL2A_scene.SAFE"])

    def test_limits_selected_count(self):
        records = [
            _record("S2A_MSIL2A_1.SAFE", "2024-01-01", 1),
            _record("S2B_MSIL2A_2.SAFE", "2024-02-01", 2),
            _record("S2C_MSIL2A_3.SAFE", "2024-03-01", 3),
        ]

        selected, _ = select_scene_records(records, max_scenes=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["scene_id"], "S2C_MSIL2A_3.SAFE")


if __name__ == "__main__":
    unittest.main()
