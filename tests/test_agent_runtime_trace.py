from __future__ import annotations

from pathlib import Path


def _runtime(*, enabled: bool = True, mode: str = "shadow"):
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    class FakeTool:
        name = "describe_dataset"
        description = "Describe"

    return GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[FakeTool()],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=enabled, mode=mode),
    )


def test_runtime_trace_records_bounded_events() -> None:
    runtime = _runtime()

    runtime.record_trace_event("context_merge", {"step": 1})
    runtime.record_trace_event("tool_precheck", {"tool_name": "describe_dataset"})

    events = runtime.trace_snapshot()

    assert [item["event"] for item in events] == ["context_merge", "tool_precheck"]
    assert events[0]["payload"] == {"step": 1}
    assert events[0]["runtime_mode"] == "shadow"
    assert events[0]["current_session_id"] == "s_1"


def test_runtime_trace_snapshot_returns_copy() -> None:
    runtime = _runtime()
    runtime.record_trace_event("context_merge", {"step": 1})

    snapshot = runtime.trace_snapshot()
    snapshot[0]["payload"]["step"] = 99

    assert runtime.trace_snapshot()[0]["payload"] == {"step": 1}


def test_runtime_diagnostics_include_context_tool_counts_and_trace() -> None:
    runtime = _runtime()
    runtime.record_trace_event("context_merge", {"ok": True})

    diagnostics = runtime.diagnostics()

    assert diagnostics["enabled"] is True
    assert diagnostics["mode"] == "shadow"
    assert diagnostics["context"]["current_user_id"] == "u_1"
    assert diagnostics["tool_count"] == 1
    assert diagnostics["trace_events"][0]["event"] == "context_merge"


def test_runtime_records_trace_for_merge_precheck_and_refresh(tmp_path) -> None:
    runtime = _runtime()

    class Manager:
        current_user_id = "u_2"
        current_session_id = "s_2"
        workdir = tmp_path

    runtime.merge_context({"intent": {"intent": "data_processing"}})
    runtime.precheck_tool("describe_dataset")
    runtime.precheck_tool("missing_tool")
    runtime.refresh_context(Manager())

    events = runtime.trace_snapshot()

    assert [item["event"] for item in events] == [
        "context_merge",
        "tool_precheck",
        "tool_precheck",
        "context_refresh",
    ]
    assert events[1]["payload"]["tool_name"] == "describe_dataset"
    assert events[2]["payload"]["ok"] is False
    assert events[3]["current_session_id"] == "s_2"
