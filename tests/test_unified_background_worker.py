from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.tool_contracts import tool_result_ok


class UnifiedBackgroundWorkerTests(unittest.TestCase):
    def _plan(self) -> dict:
        return {
            "plan_id": "plan_worker_1",
            "primary_goal": "worker_test",
            "operation": "make_map",
            "selected_tools": ["plot_dataset"],
            "candidate_tools": ["plot_dataset"],
            "requested_downloads": [],
            "workflow_plan": [
                {
                    "step_id": "plot",
                    "tool_name": "plot_dataset",
                    "validated_tool_args": {"dataset_name": "demo"},
                    "depends_on": [],
                }
            ],
            "validated_tool_args": {"plot_dataset": {"dataset_name": "demo"}},
        }

    def test_enqueue_is_idempotent_and_resource_limited(self) -> None:
        from core.background_worker import UnifiedBackgroundWorker, WorkerResourceLimits
        from core.durable_jobs import DurableJobStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = DurableJobStore(Path(tmp) / "jobs.db")
            worker = UnifiedBackgroundWorker(
                store,
                manager=None,
                limits=WorkerResourceLimits(max_queue_per_user=1, max_concurrent_per_user=1),
            )

            first = worker.enqueue_validated_plan(self._plan(), context={}, user_id="u1", session_id="s1")
            duplicate = worker.enqueue_validated_plan(self._plan(), context={}, user_id="u1", session_id="s1")
            blocked = worker.enqueue_validated_plan({**self._plan(), "plan_id": "plan_worker_2"}, context={}, user_id="u1", session_id="s1")

            self.assertEqual(first["job_id"], duplicate["job_id"])
            self.assertEqual(first["status"], "queued")
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["tool_result"]["error_code"], "WORKER_QUEUE_LIMIT_EXCEEDED")

    def test_worker_executes_verified_plan_and_persists_canonical_trace(self) -> None:
        from core.background_worker import UnifiedBackgroundWorker, WorkerResourceLimits
        from core.durable_jobs import DurableJobStore

        calls: list[dict] = []

        def fake_executor(manager, step, *, completed_results=None, context=None, cancellation_token=None):
            calls.append(step)
            if cancellation_token:
                cancellation_token.raise_if_cancelled()
            return {
                "executed": True,
                "ok": True,
                "tool_result": tool_result_ok(
                    "plot_dataset",
                    outputs={"result_dataset": "demo_map"},
                    artifacts=[{"artifact_id": "artifact_map", "type": "map", "title": "demo map"}],
                    map_layers=[{"layer_id": "layer_demo", "name": "demo"}],
                ).to_dict(),
            }

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = DurableJobStore(Path(tmp) / "jobs.db")
            worker = UnifiedBackgroundWorker(
                store,
                manager=None,
                limits=WorkerResourceLimits(max_queue_per_user=2),
                step_executor=fake_executor,
            )
            job = worker.enqueue_validated_plan(self._plan(), context={}, user_id="u1", session_id="s1")

            result = worker.run_next_job()
            stored = store.get_job(job["job_id"])

            self.assertEqual(len(calls), 1)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(stored["status"], "succeeded")
            self.assertEqual(stored["result"]["execution_trace"]["status"], "succeeded")
            self.assertEqual(stored["result"]["normalized_results"][0]["tool_name"], "plot_dataset")
            self.assertEqual(stored["result"]["normalized_results"][0]["artifacts"][0]["artifact_id"], "artifact_map")

    def test_cancelled_job_does_not_execute_or_register_success(self) -> None:
        from core.background_worker import UnifiedBackgroundWorker, WorkerResourceLimits
        from core.durable_jobs import DurableJobStore

        calls: list[dict] = []

        def fake_executor(*args, **kwargs):
            calls.append({})
            return {"executed": True, "tool_result": tool_result_ok("plot_dataset").to_dict()}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = DurableJobStore(Path(tmp) / "jobs.db")
            worker = UnifiedBackgroundWorker(
                store,
                manager=None,
                limits=WorkerResourceLimits(max_queue_per_user=2),
                step_executor=fake_executor,
            )
            job = worker.enqueue_validated_plan(self._plan(), context={}, user_id="u1", session_id="s1")
            cancelled = worker.cancel_job(job["job_id"], user_id="u1", reason="用户点击停止。")

            result = worker.run_next_job()
            stored = store.get_job(job["job_id"])

            self.assertEqual(calls, [])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(result["status"], "idle")
            self.assertEqual(stored["status"], "cancelled")
            self.assertEqual(stored["tool_result"]["error_code"], "JOB_CANCELLED")

    def test_chat_service_queues_explicit_background_plan_without_sync_execution(self) -> None:
        from core.config import Settings
        from core.durable_jobs import DurableJobStore
        from core.service import GISWorkspaceService

        plan = {
            **self._plan(),
            "intent": "map_generation",
            "task_type": "map_generation",
            "execution_mode": "background",
            "response_language": "zh-CN",
            "confidence": 0.9,
            "input_assets": [],
            "source_attribution": {},
            "explicit_history_references": [],
        }

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            settings = Settings(api_key="", workdir=Path(tmp) / "workspace")
            settings.ensure_dirs()
            service = GISWorkspaceService(settings)
            service.set_request_context("u1", "")
            service.set_interaction_mode("tool_enabled")

            with mock.patch.dict("os.environ", {"GIS_WORKER_AUTOSTART": "0"}, clear=False):
                with mock.patch("core.service.build_llm_task_plan", return_value={"status": "ready", "plan": plan}):
                    with mock.patch("core.service.run_coordinated_execution") as coordinated:
                        result = service.ask("后台执行这个已验证计划", extra_assistant_meta={"active_task_id": "task_1"})

            jobs = DurableJobStore(service.manager.workdir / "durable_jobs.db").list_jobs(user_id="u1", session_id=service.current_session_id, statuses=["queued"], job_type="validated_task_plan")
            self.assertFalse(coordinated.called)
            self.assertEqual(result["mode"], "background_worker")
            self.assertEqual(result["presentation_result"]["status"], "running")
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["payload"]["context"]["chat_task_id"], "task_1")

    def test_chat_cancel_endpoint_cancels_matching_durable_worker_job(self) -> None:
        from starlette.testclient import TestClient

        import api_server
        from core.durable_jobs import DurableJobStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            api_server._workspace_services.clear()
            api_server.base_settings.workdir = Path(tmp) / "workspace"
            api_server.base_settings.ensure_dirs()
            service = api_server.workspace_for("")
            store = DurableJobStore(service.manager.workdir / "durable_jobs.db")
            job = store.submit_job(
                user_id="",
                session_id=service.current_session_id,
                job_type="validated_task_plan",
                payload={"context": {"chat_task_id": "task_cancel_1"}, "plan": self._plan()},
            )

            with mock.patch.dict("os.environ", {"GIS_AGENT_ALLOW_ANONYMOUS": "1"}, clear=False):
                response = TestClient(api_server.app).post(
                    "/api/chat/cancel",
                    json={"task_id": "task_cancel_1", "reason": "用户点击停止。"},
                )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertIn(job["job_id"], body["cancelled_durable_jobs"])
            self.assertEqual(store.get_job(job["job_id"])["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
