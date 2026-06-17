from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock


@dataclass
class ChatTaskState:
    task_id: str
    user_id: str = ""
    session_id: str = ""
    status: str = "running"
    cancel_requested: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    reason: str = ""


_LOCK = Lock()
_TASKS: dict[str, ChatTaskState] = {}


def start_chat_task(task_id: str, *, user_id: str = "", session_id: str = "") -> ChatTaskState:
    clean = str(task_id or "").strip()
    if not clean:
        raise ValueError("task_id is required")
    with _LOCK:
        state = ChatTaskState(task_id=clean, user_id=str(user_id or ""), session_id=str(session_id or ""))
        _TASKS[clean] = state
        return state


def finish_chat_task(task_id: str, status: str = "completed") -> None:
    clean = str(task_id or "").strip()
    if not clean:
        return
    with _LOCK:
        state = _TASKS.get(clean)
        if state:
            state.status = "canceled" if state.cancel_requested else status
            state.updated_at = datetime.now().isoformat(timespec="seconds")


def cancel_chat_task(task_id: str, *, user_id: str = "", reason: str = "") -> dict[str, object]:
    clean = str(task_id or "").strip()
    if not clean:
        return {"ok": False, "status": "missing", "message": "task_id is required"}
    with _LOCK:
        state = _TASKS.get(clean)
        if state is None:
            return {"ok": False, "status": "not_found", "message": "任务不存在或已结束。"}
        if state.user_id and user_id and state.user_id != user_id:
            return {"ok": False, "status": "forbidden", "message": "无权取消该任务。"}
        state.cancel_requested = True
        state.status = "cancel_requested"
        state.reason = str(reason or "用户取消任务。")
        state.updated_at = datetime.now().isoformat(timespec="seconds")
        return {"ok": True, "status": state.status, "task_id": clean}


def is_chat_task_canceled(task_id: str) -> bool:
    clean = str(task_id or "").strip()
    if not clean:
        return False
    with _LOCK:
        state = _TASKS.get(clean)
        return bool(state and state.cancel_requested)
