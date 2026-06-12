from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.domestic_sources.gscloud_reliability import validate_download_artifact, validate_map_ready_artifact


class GSCloudOutputQualityTests(unittest.TestCase):
    def test_download_validation_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.zip"
            path.write_bytes(b"")

            with self.assertRaises(RuntimeError):
                validate_download_artifact(path)

    def test_download_validation_rejects_corrupt_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.zip"
            path.write_bytes(b"not a zip")

            with self.assertRaises(RuntimeError):
                validate_download_artifact(path)

    def test_download_validation_rejects_incomplete_shapefile_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shape.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("shape/boundary.shp", b"placeholder")

            with self.assertRaises(RuntimeError):
                validate_download_artifact(path)

    def test_download_validation_reads_csv_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.csv"
            path.write_text("lon,lat,value\n104.0,30.6,1\n", encoding="utf-8")

            quality = validate_download_artifact(path)

            self.assertTrue(quality["ok"])
            self.assertEqual(quality["header"], ["lon", "lat", "value"])

    def test_geojson_quality_validation_checks_bounds_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.geojson"
            path.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {},
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [104.06, 30.67],
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            ok = validate_map_ready_artifact(path, expected_bounds=(103.0, 30.0, 105.0, 31.5))
            self.assertTrue(ok["ok"])
            self.assertTrue(ok["bounds_overlap"])

            bad = validate_map_ready_artifact(path, expected_bounds=(110.0, 35.0, 111.0, 36.0))
            self.assertFalse(bad["bounds_overlap"])
            self.assertEqual(bad["reason"], "bounds_do_not_overlap")


if __name__ == "__main__":
    unittest.main()
