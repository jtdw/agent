from __future__ import annotations

from pathlib import Path


def _runtime(*, enabled: bool = True, mode: str = "shadow"):
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    class FakeTool:
        name = "describe_dataset"
        description = "Describe a dataset"

    return GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[FakeTool()],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=enabled, mode=mode),
    )


def test_runtime_planner_input_output_schema_avoids_prompt_and_context_leakage() -> None:
    from core.agent_runtime.decision_trace import runtime_planner_input_schema, runtime_planner_output_schema

    context = {
        "intent": {"intent": "data_processing"},
        "active_dataset": {"name": "secret_dataset", "path": "E:/secret/data.shp"},
        "runtime_tool_metadata": [{"name": "describe_dataset"}],
        "rag_trace": {"vector_rag_status": "api_embedding_persistent", "full_vector_rag": True},
    }

    input_schema = runtime_planner_input_schema(
        "describe E:/secret/data.shp",
        context,
        {"task_type": "describe_dataset", "workflow_plan": [{"step_id": "s1"}]},
        runtime_enabled=True,
        runtime_mode="shadow",
    )
    output_schema = runtime_planner_output_schema(
        {
            "status": "ready",
            "planner_source": "llm_shadow",
            "task_type": "describe_dataset",
            "planned_steps": [{"step_id": "s1", "tool_name": "describe_dataset", "path": "E:/secret/data.shp"}],
            "requires_confirmation": False,
            "executes_tools": False,
        }
    )

    rendered = str({"input": input_schema, "output": output_schema})
    assert input_schema["schema_version"] == "runtime-planner-input/v1"
    assert input_schema["prompt_length"] > 0
    assert input_schema["task_type"] == "describe_dataset"
    assert input_schema["tool_metadata_count"] == 1
    assert input_schema["rag"]["vector_rag_status"] == "api_embedding_persistent"
    assert output_schema["schema_version"] == "runtime-planner-output/v1"
    assert output_schema["step_count"] == 1
    assert output_schema["planned_tools"] == ["describe_dataset"]
    assert output_schema["executes_tools"] is False
    assert "E:/secret" not in rendered
    assert "secret_dataset" not in rendered


def test_runtime_planner_output_schema_reads_nested_plan_steps() -> None:
    from core.agent_runtime.decision_trace import runtime_planner_output_schema

    output_schema = runtime_planner_output_schema(
        {
            "status": "ready",
            "planner_source": "runtime_active:deterministic_fallback",
            "plan": {
                "task_type": "data_processing",
                "workflow_plan": [{"step_id": "points", "tool_name": "table_to_points"}],
                "requires_confirmation": False,
            },
            "executes_tools": False,
        }
    )

    assert output_schema["task_type"] == "data_processing"
    assert output_schema["step_count"] == 1
    assert output_schema["planned_tools"] == ["table_to_points"]


def test_runtime_coordinator_schema_captures_decision_without_executing_tools() -> None:
    from core.agent_runtime.decision_trace import runtime_coordinator_input_schema, runtime_coordinator_output_schema

    input_schema = runtime_coordinator_input_schema(
        {"workflow_plan": [{"step_id": "describe"}]},
        {"step_id": "describe", "tool_name": "describe_dataset"},
        [],
        {"results": [{"ok": True}]},
        "describe my data",
        tool_cards=[{"name": "describe_dataset"}],
        knowledge_snippets=[{"knowledge_id": "map"}],
    )
    output_schema = runtime_coordinator_output_schema(
        {
            "status": "ready",
            "decision": type(
                "Decision",
                (),
                {
                    "decision": "continue",
                    "next_step_id": "describe",
                    "required_tool": "describe_dataset",
                    "confidence": 0.9,
                },
            )(),
            "executes_tools": False,
        }
    )

    assert input_schema["schema_version"] == "runtime-coordinator-input/v1"
    assert input_schema["current_step_id"] == "describe"
    assert input_schema["tool_card_count"] == 1
    assert input_schema["knowledge_snippet_count"] == 1
    assert output_schema["schema_version"] == "runtime-coordinator-output/v1"
    assert output_schema["decision"] == "continue"
    assert output_schema["required_tool"] == "describe_dataset"
    assert output_schema["executes_tools"] is False


def test_runtime_decision_trace_aggregates_planner_coordinator_tools_and_rag_readiness() -> None:
    from core.agent_runtime.decision_trace import build_runtime_decision_trace

    runtime = _runtime(enabled=True, mode="shadow")
    runtime.record_trace_event("planner_shadow", {"input": {"schema_version": "runtime-planner-input/v1"}, "output": {"status": "ready"}})
    runtime.record_trace_event("coordinator_diagnostic", {"output": {"decision": "continue", "required_tool": "describe_dataset"}})
    runtime.precheck_tool("describe_dataset")

    trace = build_runtime_decision_trace(
        runtime,
        rag_readiness={"ready": False, "status": "not_ready", "reasons": ["index_not_fresh"]},
    )

    assert trace["schema_version"] == "runtime-decision-trace/v1"
    assert trace["runtime"]["enabled"] is True
    assert trace["runtime"]["mode"] == "shadow"
    assert trace["executes_tools"] is False
    assert trace["planner"]["status"] == "ready"
    assert trace["coordinator"]["decision"] == "continue"
    assert trace["tool_prechecks"]["passed"] == 1
    assert trace["tool_risk_summary"]["low"] == 1
    assert trace["rag_readiness"]["status"] == "not_ready"


def test_runtime_diagnostics_include_unified_decision_trace() -> None:
    runtime = _runtime(enabled=True, mode="shadow")
    runtime.record_trace_event("planner_shadow", {"output": {"status": "ready", "planner_source": "test"}})

    diagnostics = runtime.diagnostics()

    assert diagnostics["decision_trace"]["schema_version"] == "runtime-decision-trace/v1"
    assert diagnostics["decision_trace"]["planner"]["status"] == "ready"
