from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest


class WarningHygieneTests(unittest.TestCase):
    def run_python(self, code: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(code)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_fastapi_testclient_import_does_not_emit_deprecation_warning(self) -> None:
        result = self.run_python(
            """
            import warnings
            warnings.simplefilter("default")
            import tests.test_llm_config  # noqa: F401
            import tests.test_security_hardening  # noqa: F401
            import tests.test_real_backend_e2e  # noqa: F401
            """
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("StarletteDeprecationWarning", result.stderr)
        self.assertNotIn("on_event is deprecated", result.stderr)

    def test_shapefile_export_does_not_emit_gdal_laundering_warning_to_stderr(self) -> None:
        result = self.run_python(
            """
            import tempfile
            from pathlib import Path
            import geopandas as gpd
            from shapely.geometry import Point
            from core.config import Settings
            from core.gis_tools import build_tools

            root = Path(tempfile.mkdtemp())
            settings = Settings(api_key="", workdir=root / "workspace")
            settings.ensure_dirs()
            from core.service import GISWorkspaceService

            service = GISWorkspaceService(settings)
            service.manager.put_vector(
                "long_field_vector",
                gpd.GeoDataFrame(
                    {
                        "population_density": [1.0, 2.0],
                        "administrative_region_name": ["a", "b"],
                        "geometry": [Point(0, 0), Point(1, 1)],
                    },
                    crs="EPSG:4326",
                ),
            )
            tools = {tool.name: tool for tool in build_tools(service.manager)}
            target = service.manager.derived_dir / "exports" / "long_field_vector.shp"
            tools["export_dataset"].invoke({"dataset_name": "long_field_vector", "output_path": str(target)})
            """
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Normalized/laundered field name", result.stderr)
        self.assertNotIn("Column names longer than 10 characters", result.stderr)

    def test_put_vector_without_crs_does_not_emit_pyogrio_crs_warning_to_stderr(self) -> None:
        result = self.run_python(
            """
            import tempfile
            from pathlib import Path
            import geopandas as gpd
            from shapely.geometry import Point
            from core.data_manager import DataManager

            manager = DataManager(Path(tempfile.mkdtemp()) / "workspace")
            manager.put_vector(
                "missing_crs_points",
                gpd.GeoDataFrame({"value": [1], "geometry": [Point(0, 0)]}, crs=None),
            )
            """
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("'crs' was not provided", result.stderr)


if __name__ == "__main__":
    unittest.main()
