from __future__ import annotations

from queue import Empty
from typing import Any, Callable, Iterable

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from api.schemas.chat import ChatCancelIn, ChatModelIn, ChatRetryIn, ChatSessionIn


def create_chat_state_router(
    *,
    scoped_workspace_service: Callable[[str, str], Any],
    require_request_user_if_present: Callable[[Request, str], str],
    decorate_response_artifacts: Callable[[Any, str, dict[str, Any]], dict[str, Any]],
    public_task_events: Callable[..., list[dict[str, Any]]],
    sse_event: Callable[[dict[str, Any]], str],
    realtime_event_hub: Any,
    cancel_chat_task: Callable[..., dict[str, Any]],
    workspace_services: Callable[[], Iterable[Any]],
    durable_job_store_factory: Callable[[Any], Any],
    cancel_session_jobs: Callable[..., list[dict[str, Any]]],
    hard_delete_session_jobs: Callable[[str, str], list[dict[str, Any]]],
    compat_usage_store: Callable[[], Any],
    compat_actor_type: Callable[[Request], str],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/chat", tags=["chat-state"])

    @router.get("/messages")
    def messages(request: Request, user_id: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            service = scoped_workspace_service(authorized_user_id, "")
            return decorate_response_artifacts(service, authorized_user_id, {"messages": service.current_messages()})

        return guard(run)

    @router.get("/events/replay")
    def replay_chat_events(
        request: Request,
        user_id: str = Query(default=""),
        session_id: str = Query(default=""),
        after_version: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            service = scoped_workspace_service(authorized_user_id, session_id)
            return {
                "schema_version": "task-progress-event-replay/v1",
                "events": public_task_events(
                    service,
                    user_id=authorized_user_id,
                    session_id=session_id or service.current_session_id,
                    after_version=after_version,
                    limit=limit,
                ),
            }

        return guard(run)

    @router.get("/events")
    def stream_chat_events(
        request: Request,
        user_id: str = Query(default=""),
        session_id: str = Query(default=""),
        after_version: int = Query(default=0, ge=0),
        once: bool = Query(default=False),
    ):
        authorized_user_id = require_request_user_if_present(request, user_id)
        service = scoped_workspace_service(authorized_user_id, session_id)
        scoped_session_id = session_id or service.current_session_id

        def event_stream():
            version = max(0, int(after_version or 0))
            subscription = realtime_event_hub.subscribe(user_id=authorized_user_id, session_id=scoped_session_id)
            try:
                while True:
                    events = public_task_events(service, user_id=authorized_user_id, session_id=scoped_session_id, after_version=version)
                    for event in events:
                        version = max(version, int(event.get("version") or 0))
                        yield sse_event(event)
                    transient_events: list[dict[str, Any]] = []
                    try:
                        transient_events.append(subscription.get(timeout=0.8 if not events else 0.01))
                        while True:
                            transient_events.append(subscription.get_nowait())
                    except Empty:
                        pass
                    for event in transient_events:
                        yield sse_event(event)
                    if once:
                        return
                    if not events and not transient_events:
                        yield ": keepalive\n\n"
            finally:
                realtime_event_hub.unsubscribe(subscription)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/sessions")
    def chat_sessions(request: Request, user_id: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            service = scoped_workspace_service(authorized_user_id, "")
            if not service.current_session_id:
                service.set_request_context(authorized_user_id, create_if_missing=True)
            return decorate_response_artifacts(
                service,
                authorized_user_id,
                {
                    "sessions": service.list_sessions(),
                    "current_session_id": service.current_session_id,
                    "messages": service.current_messages(),
                },
            )

        return guard(run)

    @router.post("/sessions")
    def create_chat_session(body: ChatSessionIn, request: Request):
        def run():
            service = scoped_workspace_service(require_request_user_if_present(request, body.user_id), "")
            session_id = service.create_new_session(body.title or None)
            return {
                "session_id": session_id,
                "sessions": service.list_sessions(),
                "current_session_id": service.current_session_id,
                "messages": service.current_messages(),
            }

        return guard(run)

    @router.post("/sessions/switch")
    def switch_chat_session(body: ChatSessionIn, request: Request):
        def run():
            service = scoped_workspace_service(require_request_user_if_present(request, body.user_id), body.session_id)
            service.switch_session(body.session_id)
            return {
                "sessions": service.list_sessions(),
                "current_session_id": service.current_session_id,
                "messages": service.current_messages(),
            }

        return guard(run)

    @router.post("/sessions/rename")
    def rename_chat_session(body: ChatSessionIn, request: Request):
        def run():
            service = scoped_workspace_service(require_request_user_if_present(request, body.user_id), body.session_id)
            service.rename_session(body.session_id, body.title)
            return {"sessions": service.list_sessions(), "current_session_id": service.current_session_id}

        return guard(run)

    @router.post("/sessions/delete")
    def delete_chat_session(body: ChatSessionIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            compat_usage_store().record_effective_request(source="POST /api/chat/ask", actor_type=compat_actor_type(request))
            service = scoped_workspace_service(user_id, body.session_id)
            cancelled_download_jobs = cancel_session_jobs(user_id, body.session_id, reason="Session deleted.")
            current = service.delete_session(body.session_id)
            hard_deleted_downloads = hard_delete_session_jobs(user_id, body.session_id)
            return {
                "current_session_id": current,
                "sessions": service.list_sessions(),
                "messages": service.current_messages(),
                "cancelled_download_jobs": cancelled_download_jobs,
                "hard_deleted_downloads": hard_deleted_downloads,
            }

        return guard(run)

    @router.post("/sessions/mode")
    def set_chat_interaction_mode(body: ChatSessionIn, request: Request):
        def run():
            service = scoped_workspace_service(require_request_user_if_present(request, body.user_id), body.session_id)
            mode = service.set_interaction_mode(body.interaction_mode or "chat_only", body.session_id or service.current_session_id)
            return {
                "interaction_mode": mode,
                "sessions": service.list_sessions(),
                "current_session_id": service.current_session_id,
                "messages": service.current_messages(),
            }

        return guard(run)

    @router.post("/sessions/clear")
    def clear_chat_session(body: ChatSessionIn, request: Request):
        def run():
            service = scoped_workspace_service(require_request_user_if_present(request, body.user_id), body.session_id)
            service.clear_current_chat()
            return {
                "current_session_id": service.current_session_id,
                "sessions": service.list_sessions(),
                "messages": service.current_messages(),
            }

        return guard(run)

    @router.post("/retry")
    def retry_chat_message(body: ChatRetryIn, request: Request):
        def run():
            service = scoped_workspace_service(require_request_user_if_present(request, body.user_id), body.session_id)
            result = service.edit_user_message_and_retry(body.message_id, body.content)
            return {**result, "messages": service.current_messages(), "sessions": service.list_sessions(), "current_session_id": service.current_session_id}

        return guard(run)

    @router.get("/models")
    def chat_models(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
        def run():
            service = scoped_workspace_service(require_request_user_if_present(request, user_id), session_id)
            return service.chat_model_state(session_id or service.current_session_id)

        return guard(run)

    @router.post("/models/select")
    def select_chat_model(body: ChatModelIn, request: Request):
        def run():
            service = scoped_workspace_service(require_request_user_if_present(request, body.user_id), body.session_id)
            return service.select_chat_model(body.model, body.session_id or service.current_session_id)

        return guard(run)

    @router.post("/cancel")
    def cancel_chat(body: ChatCancelIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            result = cancel_chat_task(body.task_id, user_id=user_id, reason=body.reason)
            cancelled_durable_jobs: list[str] = []
            for service in list(workspace_services()):
                try:
                    store = durable_job_store_factory(service.manager.workdir / "durable_jobs.db")
                    if store is None:
                        continue
                    jobs = store.list_jobs(user_id=user_id, statuses=["queued", "running"], job_type="validated_task_plan", limit=100)
                    for job in jobs:
                        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
                        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
                        if str(context.get("chat_task_id") or "") == body.task_id:
                            store.cancel_job(str(job.get("job_id") or ""), user_id=user_id, reason=body.reason or "User cancelled task.")
                            cancelled_durable_jobs.append(str(job.get("job_id") or ""))
                except Exception:
                    continue
            return {**result, "cancelled_durable_jobs": cancelled_durable_jobs}

        return guard(run)

    return router
