from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.domestic_sources.gscloud_reliability import validate_map_ready_artifact


class GSCloudOutputQualityTests(unittest.TestCase):
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
