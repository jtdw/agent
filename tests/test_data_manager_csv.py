from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.data_manager import DataManager


class DataManagerCsvTests(unittest.TestCase):
    def test_station_like_csv_falls_back_to_whitespace_parser(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            manager = DataManager(root / "workspace")
            source = manager.upload_dir / "station_like.csv"
            rows = ["SMN-SDR SMN-SDR L2 41.78007 115.60314 1401.0 0.0500 0.0500 5TM"]
            rows.extend(f"2019/01/{day:02d} 00:00 0.12 D01 M" for day in range(1, 32))
            rows.append("2019/02/01 00:00 0.13 D01,D03 M")
            source.write_text("\n".join(rows), encoding="utf-8")

            name = manager.load_path(str(source))
            table = manager.get_table(name)

            self.assertEqual(list(table.columns), ["date", "time", "value", "quality_flags", "mode"])
            self.assertEqual(len(table), 32)
            self.assertEqual(table.iloc[-1]["quality_flags"], "D01,D03")


if __name__ == "__main__":
    unittest.main()
