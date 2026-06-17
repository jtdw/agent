from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ConversationState:
    active_dataset: str = ""
    active_artifacts: list[dict[str, Any]] = field(default_factory=list)
    last_task_type: str = ""
    last_user_goal: str = ""
    last_tool_results: list[dict[str, Any]] = field(default_factory=list)
    last_map_path: str = ""
    last_model_result: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None
    pending_clarification: dict[str, Any] | None = None
    referenced_object: dict[str, Any] | None = None
    selected_artifact: dict[str, Any] | None = None
    selected_layer: dict[str, Any] | None = None
    selected_feature: dict[str, Any] | None = None
    selected_map_bounds: list[float] | None = None
    selected_model_result: dict[str, Any] | None = None
    active_task: dict[str, Any] | None = None
    frontend_context: dict[str, Any] = field(default_factory=dict)
    model_route_mode: str = "auto"
    selected_chat_model: str = ""
    last_active_chat_model: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "ConversationState":
        if not isinstance(data, dict):
            return cls()
        active_artifacts = data.get("active_artifacts")
        last_tool_results = data.get("last_tool_results")
        return cls(
            active_dataset=str(data.get("active_dataset") or ""),
            active_artifacts=active_artifacts if isinstance(active_artifacts, list) else [],
            last_task_type=str(data.get("last_task_type") or ""),
            last_user_goal=str(data.get("last_user_goal") or ""),
            last_tool_results=last_tool_results if isinstance(last_tool_results, list) else [],
            last_map_path=str(data.get("last_map_path") or ""),
            last_model_result=data.get("last_model_result") if isinstance(data.get("last_model_result"), dict) else None,
            last_error=data.get("last_error") if isinstance(data.get("last_error"), dict) else None,
            pending_clarification=data.get("pending_clarification") if isinstance(data.get("pending_clarification"), dict) else None,
            referenced_object=data.get("referenced_object") if isinstance(data.get("referenced_object"), dict) else None,
            selected_artifact=data.get("selected_artifact") if isinstance(data.get("selected_artifact"), dict) else None,
            selected_layer=data.get("selected_layer") if isinstance(data.get("selected_layer"), dict) else None,
            selected_feature=data.get("selected_feature") if isinstance(data.get("selected_feature"), dict) else None,
            selected_map_bounds=data.get("selected_map_bounds") if isinstance(data.get("selected_map_bounds"), list) else None,
            selected_model_result=data.get("selected_model_result") if isinstance(data.get("selected_model_result"), dict) else None,
            active_task=data.get("active_task") if isinstance(data.get("active_task"), dict) else None,
            frontend_context=data.get("frontend_context") if isinstance(data.get("frontend_context"), dict) else {},
            model_route_mode=str(data.get("model_route_mode") or "auto"),
            selected_chat_model=str(data.get("selected_chat_model") or ""),
            last_active_chat_model=str(data.get("last_active_chat_model") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _latest_dataset_name(manager: Any) -> str:
    names = []
    try:
        names = list(manager.list_dataset_names())
    except Exception:
        return ""
    return str(names[-1]) if names else ""


def _latest_artifacts(manager: Any, limit: int = 3) -> list[dict[str, Any]]:
    try:
        artifacts = manager.list_artifacts()
    except Exception:
        return []
    return [item for item in artifacts[:limit] if isinstance(item, dict)]


def _latest_map_path(manager: Any, artifacts: list[dict[str, Any]]) -> str:
    last_plot = str(getattr(manager, "last_plot_path", "") or "")
    if last_plot:
        return last_plot
    for item in artifacts:
        path = str(item.get("path") or "")
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            return path
    return ""


def _latest_model_result(manager: Any) -> dict[str, Any] | None:
    try:
        results = manager.list_model_results(limit=1)
    except Exception:
        return None
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return None


def load_conversation_state(manager: Any, session_id: str) -> ConversationState:
    data = {}
    try:
        data = manager.database.get_conversation_state(session_id)
    except Exception:
        data = {}
    return ConversationState.from_dict(data)


def save_conversation_state(manager: Any, session_id: str, state: ConversationState | dict[str, Any]) -> None:
    payload = state.to_dict() if isinstance(state, ConversationState) else ConversationState.from_dict(state).to_dict()
    manager.database.set_conversation_state(session_id, payload)


def recover_conversation_state(manager: Any, session_id: str) -> ConversationState:
    state = load_conversation_state(manager, session_id)
    if not state.active_dataset:
        state.active_dataset = _latest_dataset_name(manager)
    if not state.active_artifacts:
        state.active_artifacts = _latest_artifacts(manager)
    if not state.last_map_path:
        state.last_map_path = _latest_map_path(manager, state.active_artifacts)
    if not state.last_model_result:
        state.last_model_result = _latest_model_result(manager)
    return state
