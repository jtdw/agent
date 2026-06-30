from __future__ import annotations

from queue import Empty
from threading import Event, Thread
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from api.schemas.chat import AskIn, ChatConfirmIn


def create_chat_actions_router(
    *,
    scoped_workspace_service: Callable[[str, str], Any],
    require_request_user_if_present: Callable[[Request, str], str],
    attach_result_panel: Callable[[Any, str, dict[str, Any]], dict[str, Any]],
    attach_chat_state: Callable[[Any, dict[str, Any]], dict[str, Any]],
    build_chat_response: Callable[..., dict[str, Any]],
    start_chat_task: Callable[..., Any],
    finish_chat_task: Callable[[str], Any],
    is_commercial_download_status_prompt: Callable[[str], bool],
    download_requires_login_result: Callable[[str], dict[str, Any]],
    format_commercial_download_status: Callable[[str, str], dict[str, Any]],
    attach_download_tool_result: Callable[[dict[str, Any]], dict[str, Any]],
    realtime_event_hub: Any,
    task_event_store_for_service: Callable[[Any], Any],
    stream_task_update: Callable[[dict[str, Any]], dict[str, Any]],
    sse_event: Callable[[dict[str, Any]], str],
    task_id_factory: Callable[[], str],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/chat", tags=["chat-actions"])

    @router.post("/ask")
    def ask(body: AskIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            service = scoped_workspace_service(user_id, body.session_id)
            task_id = str(body.task_id or "").strip()
            if task_id:
                start_chat_task(task_id, user_id=user_id, session_id=body.session_id)

            def finalize(response: dict[str, Any]) -> dict[str, Any]:
                if task_id:
                    finish_chat_task(task_id)
                return attach_result_panel(service, user_id, response)

            service.apply_frontend_context(body.frontend_context)
            if is_commercial_download_status_prompt(body.prompt):
                if not user_id:
                    return finalize(build_chat_response(service, user_prompt=body.prompt, result=download_requires_login_result(body.prompt)))
                result = format_commercial_download_status(body.prompt, user_id)
                result = attach_download_tool_result(result)
                if result.get("presentation_reply"):
                    result["reply"] = str(result["presentation_reply"])
                return finalize(
                    build_chat_response(
                        service,
                        user_prompt=body.prompt,
                        result=result,
                        meta_keys=(
                            "model",
                            "reason",
                            "normalized_results",
                            "presentation_result",
                            "execution_summary",
                            "result_rendering_path",
                            "presentation_source",
                            "tool_result",
                            "job",
                            "tile_job",
                            "scene_job",
                        ),
                    )
                )
            return finalize(
                attach_chat_state(
                    service,
                    service.ask(
                        body.prompt,
                        visible_prompt=body.prompt,
                        frontend_context=body.frontend_context,
                        extra_assistant_meta={"active_task_id": task_id} if task_id else None,
                    ),
                )
            )

        return guard(run)

    @router.post("/stream")
    def stream_chat(body: AskIn, request: Request):
        authorized_user_id = require_request_user_if_present(request, body.user_id)
        service = scoped_workspace_service(authorized_user_id, body.session_id)
        session_id = body.session_id or service.current_session_id
        task_id = str(body.task_id or "").strip() or task_id_factory()
        completed = Event()
        emitted_deltas: list[str] = []

        def on_delta(delta: str) -> None:
            emitted_deltas.append(delta)
            realtime_event_hub.publish_model_token(
                user_id=authorized_user_id,
                session_id=session_id,
                task_id=task_id,
                delta=delta,
            )

        def run_chat() -> None:
            start_chat_task(task_id, user_id=authorized_user_id, session_id=session_id)
            try:
                service.apply_frontend_context(body.frontend_context)
                result = attach_chat_state(
                    service,
                    service.ask(
                        body.prompt,
                        visible_prompt=body.prompt,
                        frontend_context=body.frontend_context,
                        extra_assistant_meta={"active_task_id": task_id},
                        stream_callback=on_delta,
                    ),
                )
                result = attach_result_panel(service, authorized_user_id, result)
                presentation = result.get("presentation_result") if isinstance(result.get("presentation_result"), dict) else {}
                task_update = stream_task_update(result)
                mode = str(result.get("mode") or "")
                final_reply = str(result.get("reply") or "")
                final_delta = final_reply[:2000] if mode == "answer_only" else ("" if emitted_deltas else final_reply[:2000])
                status = str(
                    presentation.get("status")
                    or task_update.get("status")
                    or ("succeeded" if mode == "answer_only" else "running")
                )
                if status not in {"planning", "awaiting_confirmation", "queued", "running", "waiting_login", "paused", "succeeded", "failed", "cancelled"}:
                    status = "running"
                realtime_event_hub.publish(
                    user_id=authorized_user_id,
                    session_id=session_id,
                    kind="model_complete",
                    task_id=task_id,
                    status=status,
                    message="Response generated." if mode == "answer_only" else (final_reply or "Task status updated.")[:1200],
                    delta=final_delta,
                    management_view=task_update.get("management_view") if isinstance(task_update.get("management_view"), dict) else {},
                    presentation_result=presentation,
                    task_update=task_update,
                )
            except Exception:
                realtime_event_hub.publish(
                    user_id=authorized_user_id,
                    session_id=session_id,
                    kind="error",
                    task_id=task_id,
                    status="failed",
                    message="Request could not be completed.",
                )
            finally:
                finish_chat_task(task_id)
                completed.set()

        def event_stream():
            channel = realtime_event_hub.subscribe(user_id=authorized_user_id, session_id=session_id)
            worker = Thread(target=run_chat, name=f"chat-stream-{task_id}", daemon=True)
            worker.start()
            try:
                while not completed.is_set() or not channel.empty():
                    try:
                        event = channel.get(timeout=0.75)
                        if str(event.get("task_id") or "") == task_id:
                            yield sse_event(event)
                    except Empty:
                        yield ": keepalive\n\n"
            finally:
                realtime_event_hub.unsubscribe(channel)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/confirm")
    def confirm_chat_action(body: ChatConfirmIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            service = scoped_workspace_service(user_id, body.session_id)
            task_id = str(body.task_id or "").strip()
            if task_id:
                start_chat_task(task_id, user_id=user_id, session_id=body.session_id)

            def finalize(response: dict[str, Any]) -> dict[str, Any]:
                if task_id:
                    finish_chat_task(task_id)
                return attach_result_panel(service, user_id, response)

            service.apply_frontend_context(body.frontend_context)
            token = str(body.confirmation_id or "").strip()
            prompt = f"{str(body.confirmation_prompt or 'Confirm execution').strip()} confirmed_action_id={token}".strip()
            return finalize(
                attach_chat_state(
                    service,
                    service.ask(
                        prompt,
                        frontend_context=body.frontend_context,
                        record_user_message=False,
                        extra_assistant_meta={
                            "active_task_id": task_id,
                            "confirmed_pending_confirmation_id": token,
                            "confirmation_submission": "structured",
                        }
                        if task_id
                        else {
                            "confirmed_pending_confirmation_id": token,
                            "confirmation_submission": "structured",
                        },
                    ),
                )
            )

        return guard(run)

    return router
