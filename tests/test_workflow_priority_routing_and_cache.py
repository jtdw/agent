from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from core.config import Settings
from core.service import GISWorkspaceService


class WorkflowPriorityRoutingAndCacheTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        service = GISWorkspaceService(settings)
        service.set_interaction_mode("tool_enabled")
        return service

    def test_ready_low_risk_registered_workflow_bypasses_llm_planner(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations.csv", pd.DataFrame({"lon": [104.1], "lat": [30.6], "name": ["a"]}))
            with mock.patch(
                "core.service.build_llm_task_plan",
                side_effect=AssertionError("LLM planner should not route ready low-risk workflow"),
            ):
                result = service.ask("convert table to points using lon and lat fields, output stations_points")

        self.assertEqual(result["mode"], "validated_workflow_executor")
        self.assertEqual(result["reason"], "workflow_priority_route")
        self.assertEqual(result["route"]["selected_workflow"], "table_to_points")
        self.assertGreaterEqual(result["route"]["confidence"], 0.8)
        self.assertTrue(result["presentation_result"]["artifact_refs"])

    def test_workflow_cache_is_scoped_and_expires(self) -> None:
        from core.workflow_cache import WorkflowCache

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = WorkflowCache(Path(tmp) / "workflow_cache.db")
            cache.set(
                user_id="u1",
                session_id="s1",
                namespace="dataset_profile",
                key_parts={"dataset": "stations", "hash": "abc"},
                value={"field_count": 3},
                ttl_seconds=1,
            )

            self.assertEqual(
                cache.get(user_id="u1", session_id="s1", namespace="dataset_profile", key_parts={"hash": "abc", "dataset": "stations"}),
                {"field_count": 3},
            )
            self.assertIsNone(cache.get(user_id="u2", session_id="s1", namespace="dataset_profile", key_parts={"dataset": "stations", "hash": "abc"}))
            self.assertIsNone(cache.get(user_id="u1", session_id="s2", namespace="dataset_profile", key_parts={"dataset": "stations", "hash": "abc"}))
            cache.set(
                user_id="u2",
                session_id="s1",
                namespace="dataset_profile",
                key_parts={"dataset": "stations", "hash": "abc"},
                value={"field_count": 9},
                ttl_seconds=30,
            )
            self.assertEqual(
                cache.get(user_id="u1", session_id="s1", namespace="dataset_profile", key_parts={"dataset": "stations", "hash": "abc"}),
                {"field_count": 3},
            )
            time.sleep(1.1)
            self.assertIsNone(cache.get(user_id="u1", session_id="s1", namespace="dataset_profile", key_parts={"dataset": "stations", "hash": "abc"}))

    def test_dataset_profile_reuses_scoped_cache_for_unchanged_dataset(self) -> None:
        from core.asset_profiler import profile_dataset

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.set_runtime_scope(user_id="u1", session_id="s1")
            service.manager.put_table("stations.csv", pd.DataFrame({"lon": [104.1], "lat": [30.6], "name": ["a"]}))

            with mock.patch("core.asset_profiler.build_modeling_profile", return_value={"cached_test": True}) as build_profile:
                first = profile_dataset(service.manager, "stations.csv")
                second = profile_dataset(service.manager, "stations.csv")

            self.assertEqual(first["modeling_profile"], {"cached_test": True})
            self.assertEqual(second["modeling_profile"], {"cached_test": True})
            self.assertEqual(build_profile.call_count, 1)

    def test_dynamic_area_resolution_reuses_scoped_cache(self) -> None:
        from core.area_resolver import resolve_area_candidates

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.set_runtime_scope(user_id="u1", session_id="s1")
            candidate = {
                "asset_id": "admin:city:test",
                "name": "test",
                "area_source": "local_admin_boundary",
                "dataset_name": "test_boundary",
                "schema_version": "area-resolver/v1",
            }
            with mock.patch("core.area_resolver._dynamic_admin_candidates", return_value=[candidate]) as dynamic:
                first = resolve_area_candidates("download test city dem", manager=service.manager)
            with mock.patch("core.area_resolver._dynamic_admin_candidates", side_effect=AssertionError("cached area should skip archive scan")):
                second = resolve_area_candidates("download test city dem", manager=service.manager)

            self.assertEqual(first, [candidate])
            self.assertEqual(second, [candidate])
            self.assertEqual(dynamic.call_count, 1)


if __name__ == "__main__":
    unittest.main()
