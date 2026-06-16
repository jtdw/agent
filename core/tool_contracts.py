from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass
class ToolPrecondition:
    name: str
    required_inputs: list[str] = field(default_factory=list)
    required_dataset_type: str = ""
    required_fields: list[str] = field(default_factory=list)
    required_crs: str = ""
    required_geometry: str = ""
    optional_inputs: list[str] = field(default_factory=list)
    validation_errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactInfo:
    artifact_id: str
    path: str
    type: str
    title: str
    description: str = ""
    quality_status: str = "unchecked"
    preview_available: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolResult:
    ok: bool
    tool_name: str
    task_id: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    error_code: str = ""
    error_title: str = ""
    user_message: str = ""
    technical_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)


def _new_task_id(tool_name: str) -> str:
    return f"{tool_name}_{uuid4().hex[:10]}"


def tool_result_ok(
    tool_name: str,
    *,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    artifacts: list[ArtifactInfo | dict[str, Any]] | None = None,
    summary: str = "",
    diagnostics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    task_id: str | None = None,
) -> ToolResult:
    artifact_dicts = [item.to_dict() if isinstance(item, ArtifactInfo) else item for item in (artifacts or [])]
    return ToolResult(
        ok=True,
        tool_name=tool_name,
        task_id=task_id or _new_task_id(tool_name),
        inputs=inputs or {},
        outputs=outputs or {},
        artifacts=artifact_dicts,
        summary=summary,
        diagnostics=diagnostics or {},
        warnings=warnings or [],
        next_actions=next_actions or [],
    )


def tool_result_error(
    tool_name: str,
    *,
    inputs: dict[str, Any] | None = None,
    error_code: str = "TOOL_PRECONDITION_FAILED",
    error_title: str = "工具前置条件不满足",
    user_message: str = "工具执行前缺少必要条件。",
    technical_detail: str = "",
    diagnostics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    task_id: str | None = None,
) -> ToolResult:
    return ToolResult(
        ok=False,
        tool_name=tool_name,
        task_id=task_id or _new_task_id(tool_name),
        inputs=inputs or {},
        outputs={},
        artifacts=[],
        summary="",
        diagnostics=diagnostics or {},
        warnings=warnings or [],
        next_actions=next_actions or [],
        error_code=error_code,
        error_title=error_title,
        user_message=user_message,
        technical_detail=technical_detail,
    )


def parse_tool_result(value: Any) -> dict[str, Any] | None:
    if isinstance(value, ToolResult):
        return value.to_dict()
    if isinstance(value, dict):
        payload = value
    elif isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        return None

    if not isinstance(payload, dict):
        return None
    required = {"ok", "tool_name", "task_id", "inputs", "outputs", "artifacts"}
    if not required.issubset(payload):
        return None
    return payload
