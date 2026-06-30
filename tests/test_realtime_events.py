from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from core.durable_jobs import DurableJobStore
from core.realtime_events import TaskEventStore
from core.realtime_events import RealtimeEventHub


def test_event_store_replays_only_requested_session_after_version() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = TaskEventStore(Path(tmp) / "events.db")
        first = store.append(
            user_id="u1",
            session_id="s1",
            task_id="task-a",
            kind="task_status",
            status="queued",
            message="任务已排队。",
        )
        store.append(
            user_id="u1",
            session_id="s2",
            task_id="task-b",
            kind="task_status",
            status="running",
            message="另一会话任务。",
        )
        second = store.append(
            user_id="u1",
            session_id="s1",
            task_id="task-a",
            kind="task_progress",
            status="running",
            progress=35,
            message="正在处理。",
        )

        replay = store.list_events(user_id="u1", session_id="s1", after_version=first["version"])

        assert [event["event_id"] for event in replay] == [second["event_id"]]
        assert replay[0]["progress"] == 35
        assert replay[0]["session_id"] == "s1"


def test_durable_job_state_changes_publish_replayable_events() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "durable_jobs.db"
        jobs = DurableJobStore(db_path)
        created = jobs.submit_job(
            plan_id="plan-1",
            user_id="u1",
            session_id="s1",
            job_type="validated_task_plan",
            payload={"context": {"chat_task_id": "chat-task-1"}},
        )
        jobs.update_status(created["job_id"], "running", progress=42)

        events = TaskEventStore(db_path).list_events(user_id="u1", session_id="s1")

        assert [event["status"] for event in events] == ["queued", "running"]
        assert events[0]["task_id"] == "chat-task-1"
        assert events[1]["job_id"] == created["job_id"]
        assert events[1]["progress"] == 42


def test_durable_job_progress_events_include_phase_step_heartbeat_and_timeout_context() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "durable_jobs.db"
        jobs = DurableJobStore(db_path)
        created = jobs.submit_job(
            plan_id="plan-1",
            user_id="u1",
            session_id="s1",
            job_type="validated_task_plan",
            payload={"context": {"chat_task_id": "chat-task-1"}},
        )

        jobs.update_status(
            created["job_id"],
            "running",
            progress=37,
            phase="tool_execution",
            current_step="裁剪研究区 DEM",
        )
        jobs.update_status(
            created["job_id"],
            "failed",
            progress=100,
            phase="timeout",
            current_step="裁剪研究区 DEM",
            error_code="WORKER_RUNTIME_LIMIT_EXCEEDED",
            error_message="Worker runtime exceeded.",
            timeout_reason="max_runtime_seconds exceeded",
        )

        events = TaskEventStore(db_path).list_events(user_id="u1", session_id="s1")
        running = events[1]
        failed = events[2]

        assert running["phase"] == "tool_execution"
        assert running["current_step"] == "裁剪研究区 DEM"
        assert running["heartbeat_at"]
        assert running["started_at"]
        assert isinstance(running["elapsed_ms"], int)
        assert running["task_update"]["phase"] == "tool_execution"
        assert running["task_update"]["current_step"] == "裁剪研究区 DEM"
        assert running["task_update"]["progress"] == 37
        assert failed["phase"] == "timeout"
        assert failed["timeout_reason"] == "max_runtime_seconds exceeded"
        assert failed["task_update"]["timeout_reason"] == "max_runtime_seconds exceeded"


def test_replay_api_returns_sanitized_session_scoped_events() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        event = TaskEventStore(root / "durable_jobs.db").append(
            user_id="u1",
            session_id="s1",
            task_id="task-a",
            kind="task_progress",
            status="running",
            progress=60,
            message="正在处理。",
        )
        import api_server

        service = SimpleNamespace(manager=SimpleNamespace(workdir=root))
        with (
            mock.patch.object(api_server, "_scoped_workspace_service", return_value=service),
            mock.patch.object(api_server, "_require_request_user_if_present", return_value="u1"),
        ):
            client = TestClient(api_server.app)
            response = client.get("/api/chat/events/replay", params={"user_id": "u1", "session_id": "s1"})

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["events"][0]["event_id"] == event["event_id"]
        assert payload["events"][0]["progress"] == 60
        assert "user_id" not in payload["events"][0]
        assert "session_id" not in payload["events"][0]


def test_sse_api_streams_public_event_once() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        event = TaskEventStore(root / "durable_jobs.db").append(
            user_id="u1",
            session_id="s1",
            task_id="task-a",
            kind="task_status",
            status="queued",
            message="任务已排队。",
        )
        import api_server

        service = SimpleNamespace(manager=SimpleNamespace(workdir=root), current_session_id="s1")
        with (
            mock.patch.object(api_server, "_scoped_workspace_service", return_value=service),
            mock.patch.object(api_server, "_require_request_user_if_present", return_value="u1"),
        ):
            client = TestClient(api_server.app)
            with client.stream("GET", "/api/chat/events", params={"user_id": "u1", "session_id": "s1", "once": "true"}) as response:
                body = "".join(response.iter_text())

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert f"id: {event['version']}" in body
        assert '"user_id"' not in body
        assert '"session_id"' not in body


def test_chat_stream_api_forwards_model_deltas_and_completion() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        import api_server

        class StreamService:
            current_session_id = "s1"
            manager = SimpleNamespace(workdir=root)

            def apply_frontend_context(self, _context):
                return None

            def ask(self, _prompt, **kwargs):
                kwargs["stream_callback"]("你好")
                kwargs["stream_callback"]("，GIS")
                return {"reply": "你好，GIS", "mode": "answer_only", "reason": "valid_answer_only"}

        service = StreamService()
        decorated = {
            "reply": "你好，GIS",
            "mode": "answer_only",
            "messages": [{"role": "assistant", "content": "你好，GIS", "meta": {"mode": "answer_only", "interaction_type": "chat_answer"}}],
        }
        with (
            mock.patch.object(api_server, "_scoped_workspace_service", return_value=service),
            mock.patch.object(api_server, "_require_request_user_if_present", return_value="u1"),
            mock.patch.object(api_server, "attach_chat_state", side_effect=lambda _service, result: {**decorated, **result}),
            mock.patch.object(api_server, "_attach_result_panel", side_effect=lambda _service, _user, result: result),
        ):
            client = TestClient(api_server.app)
            with client.stream("POST", "/api/chat/stream", json={"prompt": "什么是 GIS？", "user_id": "u1", "session_id": "s1", "task_id": "chat-a"}) as response:
                body = "".join(response.iter_text())

        assert response.status_code == 200
        assert '"kind":"model_token"' in body
        assert '"delta":"你好"' in body
        assert '"kind":"model_complete"' in body
        assert '"delta":"你好，GIS"' in body
        assert '"mode":"answer_only"' in body
        assert '"response_mode":"answer_only"' in body
        assert '"interaction_type":"chat_answer"' in body
        assert '"user_id"' not in body
        assert '"session_id"' not in body


def test_answer_only_chat_stream_does_not_replay_generic_planning_event() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        import api_server

        class StreamService:
            current_session_id = "s1"
            manager = SimpleNamespace(workdir=root)

            def apply_frontend_context(self, _context):
                return None

            def ask(self, _prompt, **_kwargs):
                return {"reply": "Plain answer", "mode": "answer_only", "reason": "chat_only_direct_answer"}

        service = StreamService()
        decorated = {
            "reply": "Plain answer",
            "mode": "answer_only",
            "messages": [
                {
                    "role": "assistant",
                    "content": "Plain answer",
                    "meta": {
                        "mode": "answer_only",
                        "interaction_type": "chat_answer",
                        "reason": "chat_only_direct_answer",
                    },
                }
            ],
        }
        with (
            mock.patch.object(api_server, "_scoped_workspace_service", return_value=service),
            mock.patch.object(api_server, "_require_request_user_if_present", return_value="u1"),
            mock.patch.object(api_server, "attach_chat_state", side_effect=lambda _service, result: {**decorated, **result}),
            mock.patch.object(api_server, "_attach_result_panel", side_effect=lambda _service, _user, result: result),
        ):
            client = TestClient(api_server.app)
            with client.stream(
                "POST",
                "/api/chat/stream",
                json={"prompt": "What is GIS?", "user_id": "u1", "session_id": "s1", "task_id": "chat-a"},
            ) as response:
                body = "".join(response.iter_text())
            replay = client.get("/api/chat/events/replay", params={"user_id": "u1", "session_id": "s1"})

        assert response.status_code == 200
        assert '"kind":"model_complete"' in body
        assert replay.status_code == 200
        events = replay.json()["events"]
        assert not [
            event
            for event in events
            if event["kind"] == "task_status"
            and event["status"] == "planning"
            and event["message"] == "Preparing response or task plan."
        ]


def test_answer_only_stream_task_update_strips_stale_task_card_fields() -> None:
    from api_server import _stream_task_update

    response = {
        "mode": "answer_only",
        "response_mode": "answer_only",
        "messages": [
            {
                "role": "assistant",
                "content": "Plain answer",
                "meta": {
                    "mode": "answer_only",
                    "response_mode": "answer_only",
                    "interaction_type": "chat_answer",
                    "reason": "chat_only_direct_answer",
                    "status": "planning",
                    "task_card": {"task_id": "chat-a", "status": "planning"},
                    "management_view": {"task_id": "chat-a"},
                    "download_management_view": {"task_id": "chat-a"},
                    "action_required": {"type": "confirmation_required"},
                },
            }
        ],
    }

    update = _stream_task_update(response)

    assert update == {
        "mode": "answer_only",
        "response_mode": "answer_only",
        "interaction_type": "chat_answer",
        "reason": "chat_only_direct_answer",
    }


def test_transient_model_tokens_are_scoped_and_not_persisted() -> None:
    hub = RealtimeEventHub()
    subscription = hub.subscribe(user_id="u1", session_id="s1")
    hub.publish_model_token(user_id="u1", session_id="s1", task_id="chat-a", delta="你好")
    hub.publish_model_token(user_id="u1", session_id="s2", task_id="chat-b", delta="不应收到")

    event = subscription.get(timeout=0.1)

    assert event["kind"] == "model_token"
    assert event["delta"] == "你好"
    assert "user_id" not in event
    assert "session_id" not in event
    hub.unsubscribe(subscription)


def test_event_checkpoint_prevents_duplicate_download_status_events() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = TaskEventStore(Path(tmp) / "events.db")
        first = store.append_if_changed(
            checkpoint_key="download:job-1",
            fingerprint="running:20:2026-06-24T10:00:00",
            user_id="u1",
            session_id="s1",
            task_id="job-1",
            job_id="job-1",
            kind="task_progress",
            status="running",
            progress=20,
            message="正在下载。",
        )
        duplicate = store.append_if_changed(
            checkpoint_key="download:job-1",
            fingerprint="running:20:2026-06-24T10:00:00",
            user_id="u1",
            session_id="s1",
            task_id="job-1",
            job_id="job-1",
            kind="task_progress",
            status="running",
            progress=20,
            message="正在下载。",
        )

        assert first is not None
        assert duplicate is None
        assert len(store.list_events(user_id="u1", session_id="s1")) == 1


def test_replay_bridge_converts_commercial_download_to_task_event() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        import api_server

        service = SimpleNamespace(manager=SimpleNamespace(workdir=root), current_session_id="s1")
        raw_job = {
            "job_id": "download-1",
            "user_id": "u1",
            "session_id": "s1",
            "status": "running",
            "progress": 45,
            "stage": "downloading",
            "updated_at": "2026-06-24T10:00:00",
            "source_key": "gscloud",
            "resource_type": "dem",
            "region": "成都市",
        }
        with (
            mock.patch.object(api_server, "_scoped_workspace_service", return_value=service),
            mock.patch.object(api_server, "_require_request_user_if_present", return_value="u1"),
            mock.patch.object(api_server.commercial_service, "list_jobs", return_value=[raw_job]),
        ):
            client = TestClient(api_server.app)
            response = client.get("/api/chat/events/replay", params={"user_id": "u1", "session_id": "s1"})

        assert response.status_code == 200, response.text
        event = response.json()["events"][0]
        assert event["task_id"] == "download-1"
        assert event["status"] == "running"
        assert event["management_view"]["task_id"] == "download-1"
        assert event["task_update"]["interaction_type"] == "tool_task"
