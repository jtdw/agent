from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.object_resolver import resolve_object_reference


@dataclass
class _Record:
    name: str
    data_type: str
    path: Path
    meta: dict[str, Any]


class _Manager:
    def __init__(self) -> None:
        self.datasets = {
            "county_points": _Record("county_points", "vector", Path("county_points.geojson"), {"columns": ["pop_density", "area", "geometry"]}),
            "study_area": _Record("study_area", "vector", Path("study_area.geojson"), {"columns": ["name", "geometry"]}),
            "county_boundary": _Record("county_boundary", "vector", Path("county_boundary.geojson"), {"columns": ["county", "geometry"]}),
        }
        self.artifacts = [
            {
                "artifact_id": "clip_001",
                "name": "county_points_clipped.geojson",
                "path": "derived/county_points_clipped.geojson",
                "type": "dataset",
                "dataset_id": "county_points_clipped",
                "description": "vector_clip_by_vector clipped result",
                "meta": {"tool_name": "vector_clip_by_vector"},
            }
        ]

    def list_dataset_names(self) -> list[str]:
        return list(self.datasets)

    def list_datasets(self) -> list[dict[str, Any]]:
        return [{"name": item.name, "type": item.data_type, "path": str(item.path), "meta": item.meta} for item in self.datasets.values()]

    def get(self, name: str) -> _Record:
        return self.datasets[name]

    def list_artifacts(self) -> list[dict[str, Any]]:
        return list(self.artifacts)


class ObjectResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _Manager()
        self.context = {
            "active_dataset": {"name": "county_points", "type": "vector", "path": "county_points.geojson"},
            "available_fields": ["pop_density", "area", "geometry"],
            "recent_artifacts": self.manager.list_artifacts(),
            "available_datasets": self.manager.list_datasets(),
        }

    def test_this_data_resolves_to_active_dataset(self) -> None:
        result = resolve_object_reference("这个数据", self.context, manager=self.manager, object_type="dataset")

        self.assertTrue(result["ok"])
        self.assertEqual(result["type"], "dataset")
        self.assertEqual(result["name"], "county_points")
        self.assertEqual(result["source"], "active_dataset")

    def test_latest_clipped_result_resolves_to_clipped_artifact(self) -> None:
        result = resolve_object_reference("刚才裁剪后的结果", self.context, manager=self.manager, object_type="artifact")

        self.assertTrue(result["ok"])
        self.assertEqual(result["type"], "artifact")
        self.assertEqual(result["id"], "clip_001")
        self.assertEqual(result["data"]["dataset_id"], "county_points_clipped")

    def test_study_area_resolves_to_boundary_layer(self) -> None:
        result = resolve_object_reference("把这个 shp 裁剪到研究区", self.context, manager=self.manager, object_type="clip_boundary")

        self.assertTrue(result["ok"])
        self.assertEqual(result["type"], "dataset")
        self.assertEqual(result["name"], "study_area")

    def test_population_density_resolves_to_real_field(self) -> None:
        result = resolve_object_reference("人口密度", self.context, manager=self.manager, object_type="field")

        self.assertTrue(result["ok"])
        self.assertEqual(result["type"], "field")
        self.assertEqual(result["name"], "pop_density")

    def test_multiple_field_candidates_require_clarification(self) -> None:
        context = dict(self.context)
        context["available_fields"] = ["population", "pop_total", "geometry"]

        result = resolve_object_reference("人口", context, manager=self.manager, object_type="field")

        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_clarification"])
        self.assertGreaterEqual(len(result["candidates"]), 2)

    def test_missing_object_does_not_invent_name(self) -> None:
        result = resolve_object_reference("土壤盐分", self.context, manager=self.manager, object_type="field")

        self.assertFalse(result["ok"])
        self.assertEqual(result["name"], "")
        self.assertEqual(result["candidates"], [])


    def test_real_chinese_this_data_resolves_to_active_dataset(self) -> None:
        result = resolve_object_reference("这个数据", self.context, manager=self.manager, object_type="dataset")

        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "county_points")
        self.assertEqual(result["source"], "active_dataset")

    def test_real_chinese_latest_clipped_result_resolves_to_artifact(self) -> None:
        artifact = dict(self.manager.artifacts[0])
        artifact["description"] = "裁剪结果"
        context = dict(self.context)
        context["recent_artifacts"] = [artifact]

        result = resolve_object_reference("刚才裁剪后的结果", context, manager=self.manager, object_type="artifact")

        self.assertTrue(result["ok"])
        self.assertEqual(result["id"], "clip_001")
        self.assertEqual(result["data"]["dataset_id"], "county_points_clipped")

    def test_real_chinese_study_area_resolves_to_boundary_layer(self) -> None:
        result = resolve_object_reference("把这个 shp 裁剪到研究区", self.context, manager=self.manager, object_type="clip_boundary")

        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "study_area")

    def test_real_chinese_population_density_resolves_to_field(self) -> None:
        result = resolve_object_reference("人口密度", self.context, manager=self.manager, object_type="field")

        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "pop_density")


if __name__ == "__main__":
    unittest.main()
