from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from core.context_builder import build_conversation_context, format_context_for_agent
from core.field_semantics import match_user_field_concept, normalize_field_name, rank_candidate_fields
from core.task_planner import build_task_plan
from core.task_slots import extract_task_slots


@dataclass
class _Record:
    name: str
    data_type: str
    path: Path
    meta: dict[str, Any]


class _Manager:
    def __init__(self) -> None:
        self.df = pd.DataFrame({"county": ["A"], "pop_density": [12.5], "category": ["urban"]})

    def get(self, name: str) -> _Record:
        return _Record(name=name, data_type="table", path=Path("county.csv"), meta={"columns": list(self.df.columns)})

    def get_table(self, name: str) -> pd.DataFrame:
        return self.df.copy()

    def list_datasets(self) -> list[dict[str, Any]]:
        return [{"name": "county", "type": "table", "path": "county.csv", "meta": {"columns": list(self.df.columns)}}]

    def workspace_summary(self) -> dict[str, Any]:
        return {"dataset_count": 1}


class FieldSemanticsTests(unittest.TestCase):
    def test_normalize_field_name_handles_case_separators_and_spaces(self) -> None:
        self.assertEqual(normalize_field_name(" Pop_Density "), "popdensity")
        self.assertEqual(normalize_field_name("土地-利用"), "土地利用")

    def test_population_density_matches_pop_density(self) -> None:
        result = match_user_field_concept("画人口密度图", ["county", "pop_density", "geometry"])

        self.assertEqual(result["best_field"], "pop_density")
        self.assertGreaterEqual(result["confidence"], 0.78)

    def test_population_matches_population_aliases(self) -> None:
        result = match_user_field_concept("按人口分级制图", ["id", "population", "pop", "常住人口"])

        self.assertIn(result["best_field"], {"population", "pop", "常住人口"})
        self.assertGreaterEqual(result["confidence"], 0.78)

    def test_area_matches_area_or_shape_area(self) -> None:
        result = match_user_field_concept("统计面积", ["name", "shape_area", "area"])

        self.assertIn(result["best_field"], {"shape_area", "area"})
        self.assertGreaterEqual(result["confidence"], 0.78)

    def test_elevation_matches_elevation_aliases(self) -> None:
        result = match_user_field_concept("高程分布", ["dem", "elevation", "height"])

        self.assertIn(result["best_field"], {"dem", "elevation", "height"})
        self.assertGreaterEqual(result["confidence"], 0.78)

    def test_precipitation_matches_rainfall_aliases(self) -> None:
        result = match_user_field_concept("降水空间分布", ["rainfall", "precipitation", "rain"])

        self.assertIn(result["best_field"], {"rainfall", "precipitation", "rain"})
        self.assertGreaterEqual(result["confidence"], 0.78)

    def test_county_boundary_aliases_match_real_fields(self) -> None:
        county = match_user_field_concept("县域统计", ["county", "district", "name"])
        boundary = match_user_field_concept("边界字段", ["boundary", "border", "geometry"])

        self.assertIn(county["best_field"], {"county", "district"})
        self.assertIn(boundary["best_field"], {"boundary", "border", "geometry"})

    def test_multiple_candidate_fields_are_ranked(self) -> None:
        candidates = rank_candidate_fields("人口密度", ["density", "pop_density", "density_pop"])

        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["field"], "pop_density")
        self.assertGreaterEqual(candidates[0]["score"], candidates[1]["score"])

    def test_no_candidate_does_not_invent_field(self) -> None:
        result = match_user_field_concept("人口密度", ["station_id", "name", "category"])

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["best_field"], "")

    def test_planner_uses_high_confidence_map_field_candidate(self) -> None:
        intent = {"intent": "map_generation", "confidence": 0.86, "secondary_intents": []}
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "county", "type": "vector"},
            "available_fields": ["county", "pop_density", "geometry"],
            "numeric_fields": ["pop_density"],
            "semantic_field_candidates": match_user_field_concept(
                "画人口密度图",
                ["county", "pop_density", "geometry"],
            ),
        }

        plan = build_task_plan("画人口密度图", intent, context)

        self.assertFalse(plan["should_ask_clarification"])
        self.assertEqual(plan["resolved_fields"]["map_field"], "pop_density")
        self.assertIn("pop_density", " ".join(plan["execution_steps"]))

    def test_task_slots_reuse_semantic_field_candidate(self) -> None:
        slots = extract_task_slots(
            "plot population density map",
            {"intent": "map_generation", "confidence": 0.86},
            {"active_dataset": "county"},
            {"dataset_count": 1, "available_fields": ["county", "pop_density", "geometry"]},
        )

        self.assertEqual(slots["target_field"], "pop_density")
        self.assertEqual(slots["candidate_fields"][0]["field"], "pop_density")

    def test_context_builder_adds_field_summary_and_semantic_candidates(self) -> None:
        manager = _Manager()
        intent = {"intent": "map_generation", "confidence": 0.86}

        context = build_conversation_context(
            "画人口密度图",
            intent,
            {"active_dataset": "county"},
            manager,
            {"summary": {"dataset_count": 1}},
        )

        self.assertIn("pop_density", context["available_fields"])
        self.assertIn("pop_density", context["numeric_fields"])
        self.assertEqual(context["semantic_field_candidates"]["best_field"], "pop_density")
        formatted = format_context_for_agent(context)
        self.assertIn("semantic_field_candidates", formatted)

    def test_planner_asks_when_multiple_map_field_candidates_are_close(self) -> None:
        intent = {"intent": "map_generation", "confidence": 0.86, "secondary_intents": []}
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "county", "type": "vector"},
            "available_fields": ["population", "pop_total", "geometry"],
            "numeric_fields": ["population", "pop_total"],
            "semantic_field_candidates": {
                "concept": "人口",
                "best_field": "population",
                "confidence": 0.72,
                "needs_clarification": True,
                "candidates": [
                    {"field": "population", "score": 0.72, "concept": "人口"},
                    {"field": "pop_total", "score": 0.69, "concept": "人口"},
                ],
            },
        }

        plan = build_task_plan("画人口图", intent, context)

        self.assertTrue(plan["should_ask_clarification"])
        self.assertIn("population", plan["clarification_question"])
        self.assertIn("pop_total", plan["clarification_question"])


    def test_real_chinese_population_density_matches_pop_density(self) -> None:
        result = match_user_field_concept("画人口密度图", ["county", "pop_density", "geometry"])

        self.assertEqual(result["best_field"], "pop_density")
        self.assertGreaterEqual(result["confidence"], 0.78)

    def test_real_chinese_county_boundary_aliases_match_fields(self) -> None:
        county = match_user_field_concept("县域统计", ["county", "district", "name"])
        boundary = match_user_field_concept("县域边界", ["boundary", "border", "geometry"])

        self.assertIn(county["best_field"], {"county", "district"})
        self.assertIn(boundary["best_field"], {"boundary", "border", "geometry"})


if __name__ == "__main__":
    unittest.main()
