from __future__ import annotations

import json
from pathlib import Path


def _runtime(*, enabled: bool = True, mode: str = "shadow"):
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    class FakeTool:
        name = "generic_xgboost_workflow"
        description = "Train an XGBoost model"

    return GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[FakeTool()],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=enabled, mode=mode),
    )


def _runtime_with_tools(tool_names: list[str]):
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    class FakeTool:
        def __init__(self, name: str) -> None:
            self.name = name
            self.description = f"{name} description"

    return GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[FakeTool(name) for name in tool_names],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=True, mode="shadow"),
    )


def _planner_context() -> dict:
    return {
        "active_dataset": {"name": "stations", "type": "table"},
        "available_fields": ["soil_moisture", "ndvi"],
        "candidate_tool_cards": [{"tool_name": "generic_xgboost_workflow"}],
    }


class CapturingPlannerClient:
    def __init__(self) -> None:
        self.user_content = ""

    def invoke(self, messages):
        self.user_content = str(messages[-1][1])
        return json.dumps(
            {
                "task_type": "modeling",
                "goal": "Train XGBoost.",
                "selected_assets": [{"role": "training_table", "name": "stations", "evidence": ["active dataset"]}],
                "tools_read": ["generic_xgboost_workflow"],
                "planned_steps": [
                    {
                        "step_id": "train",
                        "tool_name": "generic_xgboost_workflow",
                        "args": {
                            "dataset_name": "stations",
                            "target_col": "soil_moisture",
                            "feature_cols": "ndvi",
                            "output_name": "runtime_shadow_xgb",
                        },
                    }
                ],
                "requires_confirmation": False,
                "clarification_question": "",
                "assumptions": [],
                "expected_outputs": ["model_metrics"],
                "forbidden_tools": [],
                "explanation": "Runtime shadow only.",
            },
            ensure_ascii=False,
        )


def test_runtime_planner_adapter_shadow_plan_merges_overlay_and_records_trace() -> None:
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="shadow")
    client = CapturingPlannerClient()

    result = RuntimePlannerAdapter(runtime).build_shadow_task_plan(
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
        client=client,
    )

    assert result["status"] == "ready"
    assert result["mode"] == "shadow"
    assert result["executes_tools"] is False
    assert result["runtime_adapter"]["mode"] == "shadow"
    assert result["runtime_adapter"]["executes_tools"] is False
    assert '"runtime"' in client.user_content
    assert '"current_user_id": "u_1"' in client.user_content
    assert [item["event"] for item in runtime.trace_snapshot()] == ["context_merge", "planner_shadow"]


def test_runtime_planner_adapter_is_disabled_when_runtime_is_disabled() -> None:
    from core.agent_runtime.planner import RuntimePlannerAdapter

    result = RuntimePlannerAdapter(_runtime(enabled=False, mode="legacy")).build_shadow_task_plan(
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
        client=CapturingPlannerClient(),
    )

    assert result["status"] == "disabled"
    assert result["mode"] == "shadow"
    assert result["planner_source"] == "runtime_disabled"
    assert result["executes_tools"] is False
    assert result["runtime_adapter"]["enabled"] is False
    assert result["runtime_adapter"]["mode"] == "legacy"
    assert result["runtime_adapter"]["executes_tools"] is False
    assert result["runtime_adapter"]["cutover_guard"]["active_effective"] is False


def test_runtime_planner_adapter_blocks_manual_active_mode_without_cutover_guard(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=False)

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        assert enabled is False
        return {"status": "disabled", "mode": "active", "planner_source": "active_cutover_blocked", "executes_tools": False}

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = RuntimePlannerAdapter(runtime).build_shadow_task_plan(
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
    )

    assert result["status"] == "disabled"
    assert result["runtime_adapter"]["cutover_guard"]["active_requested"] is True
    assert result["runtime_adapter"]["cutover_guard"]["active_effective"] is False


def test_runtime_planner_adapter_builds_guarded_active_plan_when_cutover_allowed(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        assert enabled is True
        assert context["agent_policy"]["runtime"]["mode"] == "active"
        return {
            "status": "ready",
            "mode": "shadow",
            "planner_source": "runtime_test",
            "executes_tools": False,
            "plan": {"task_type": "modeling", "workflow_plan": [{"tool_name": "generic_xgboost_workflow"}]},
        }

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = RuntimePlannerAdapter(runtime).build_active_task_plan(
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
    )

    assert result["status"] == "ready"
    assert result["mode"] == "active"
    assert result["planner_source"] == "runtime_active:runtime_test"
    assert result["plan"]["task_type"] == "modeling"
    assert result["runtime_adapter"]["cutover_guard"]["active_effective"] is True
    assert runtime.trace_snapshot()[-1]["event"] == "planner_active"


def test_runtime_planner_adapter_active_plan_falls_back_to_deterministic_plan_when_llm_plan_is_not_ready(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)
    deterministic_plan = {
        "task_type": "data_processing",
        "workflow_plan": [{"step_id": "points", "tool_name": "table_to_points", "validated_tool_args": {"dataset_name": "stations"}}],
        "requires_confirmation": False,
    }

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {"status": "invalid_plan", "mode": "shadow", "planner_source": "runtime_test", "errors": [{"code": "bad"}]}

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = RuntimePlannerAdapter(runtime).build_active_task_plan(
        "convert table",
        _planner_context(),
        deterministic_plan,
    )

    assert result["status"] == "ready"
    assert result["planner_source"] == "runtime_active:deterministic_fallback"
    assert result["plan"] == deterministic_plan
    assert result["active_fallback"]["llm_status"] == "invalid_plan"
    assert result["executes_tools"] is False


def test_runtime_planner_adapter_active_plan_falls_back_when_llm_ready_plan_has_no_action(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)
    deterministic_plan = {
        "task_type": "data_processing",
        "workflow_plan": [{"step_id": "points", "tool_name": "table_to_points", "validated_tool_args": {"dataset_name": "stations"}}],
        "requires_confirmation": False,
    }

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {
            "status": "ready",
            "mode": "shadow",
            "planner_source": "runtime_test",
            "plan": {"task_type": "data_processing", "workflow_plan": [], "tool_plan": [], "requires_confirmation": False},
        }

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = RuntimePlannerAdapter(runtime).build_active_task_plan(
        "convert table",
        _planner_context(),
        deterministic_plan,
    )

    assert result["status"] == "ready"
    assert result["planner_source"] == "runtime_active:deterministic_fallback"
    assert result["active_fallback"]["llm_status"] == "ready"
    assert result["plan"]["workflow_plan"][0]["tool_name"] == "table_to_points"


def test_runtime_planner_adapter_active_plan_falls_back_when_llm_ready_plan_requests_clarification(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)
    deterministic_plan = {
        "task_type": "data_processing",
        "workflow_plan": [{"step_id": "describe", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": "parcels"}}],
        "requires_confirmation": False,
    }

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {
            "status": "ready",
            "mode": "shadow",
            "planner_source": "runtime_test",
            "plan": {
                "task_type": "data_processing",
                "workflow_plan": [],
                "tool_plan": [],
                "requires_confirmation": False,
                "should_ask_clarification": True,
                "clarification_question": "Which dataset should I inspect?",
            },
        }

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = RuntimePlannerAdapter(runtime).build_active_task_plan(
        "check this dataset",
        _planner_context(),
        deterministic_plan,
    )

    assert result["status"] == "ready"
    assert result["planner_source"] == "runtime_active:deterministic_fallback"
    assert result["active_fallback"]["llm_status"] == "ready"
    assert result["plan"]["workflow_plan"][0]["tool_name"] == "describe_dataset"


def test_runtime_planner_adapter_active_plan_falls_back_when_llm_skips_table_to_points_prerequisite(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)
    deterministic_plan = {
        "task_type": "map_generation",
        "resolved_fields": {"map_field": "xgb_validation_prediction_gcp_width"},
        "workflow_plan": [
            {
                "step_id": "make_points",
                "tool_name": "table_to_points",
                "validated_tool_args": {"dataset_name": "xgb_gcp_predictions", "x_col": "lon", "y_col": "lat"},
            },
            {
                "step_id": "generate_map",
                "tool_name": "plot_dataset",
                "validated_tool_args": {
                    "dataset_name": "$steps.make_points.outputs.result_dataset",
                    "column": "xgb_validation_prediction_gcp_width",
                },
            },
        ],
        "requires_confirmation": False,
    }

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {
            "status": "ready",
            "mode": "shadow",
            "planner_source": "runtime_test",
            "plan": {
                "task_type": "map_generation",
                "workflow_plan": [
                    {
                        "step_id": "map",
                        "tool_name": "plot_dataset",
                        "validated_tool_args": {
                            "dataset_name": "xgb_gcp_predictions",
                            "column": "xgb_validation_prediction_gcp_width",
                        },
                    }
                ],
                "tool_plan": [
                    {
                        "tool_name": "plot_dataset",
                        "args": {
                            "dataset_name": "xgb_gcp_predictions",
                            "column": "xgb_validation_prediction_gcp_width",
                        },
                    }
                ],
                "requires_confirmation": False,
            },
        }

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = RuntimePlannerAdapter(runtime).build_active_task_plan(
        "plot the GCP uncertainty map",
        _planner_context(),
        deterministic_plan,
    )

    assert result["status"] == "ready"
    assert result["planner_source"] == "runtime_active:deterministic_fallback"
    assert [step["tool_name"] for step in result["plan"]["workflow_plan"]] == ["table_to_points", "plot_dataset"]


def test_runtime_planner_adapter_active_plan_keeps_llm_clarification_when_deterministic_plan_has_no_action(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)
    deterministic_plan = {
        "task_type": "data_download",
        "workflow_plan": [],
        "tool_plan": [],
        "validated_tool_args": {},
        "requires_confirmation": True,
        "should_ask_clarification": True,
        "clarification_question": "Please confirm whether to use the platform account.",
    }

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {
            "status": "ready",
            "mode": "shadow",
            "planner_source": "runtime_test",
            "plan": {
                "task_type": "data_download",
                "workflow_plan": [],
                "tool_plan": [],
                "requires_confirmation": True,
                "clarification_question": "Please confirm whether to continue.",
            },
        }

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = RuntimePlannerAdapter(runtime).build_active_task_plan(
        "download dem with platform account",
        _planner_context(),
        deterministic_plan,
    )

    assert result["status"] == "ready"
    assert result["planner_source"] == "runtime_active:runtime_test"
    assert result["plan"]["clarification_question"] == "Please confirm whether to continue."


def test_runtime_planner_adapter_active_plan_promotes_ready_executable_workflow(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.planner import RuntimePlannerAdapter

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)
    deterministic_plan = {
        "task_type": "data_processing",
        "workflow_template": {"workflow_id": "vector_clip_raster"},
        "executable_workflow": {
            "status": "ready",
            "workflow_plan": [
                {"step_id": "describe", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": "dem"}},
                {
                    "step_id": "clip",
                    "tool_name": "clip_raster_by_vector",
                    "validated_tool_args": {"raster_name": "dem", "vector_name": "watershed", "output_name": "dem_clipped"},
                },
            ],
        },
        "workflow_plan": [],
        "tool_plan": [],
        "validated_tool_args": {},
        "requires_confirmation": False,
    }

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {"status": "invalid_plan", "mode": "shadow", "planner_source": "runtime_test"}

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = RuntimePlannerAdapter(runtime).build_active_task_plan(
        "clip raster",
        _planner_context(),
        deterministic_plan,
    )

    assert result["status"] == "ready"
    assert result["planner_source"] == "runtime_active:deterministic_fallback"
    assert [step["tool_name"] for step in result["plan"]["workflow_plan"]] == ["describe_dataset", "clip_raster_by_vector"]
    assert result["plan"]["validated_tool_args"]["clip_raster_by_vector"]["raster_name"] == "dem"


def test_runtime_planner_adapter_coordinator_decision_is_diagnostic_only() -> None:
    from core.agent_runtime.planner import RuntimePlannerAdapter

    captured_payload: dict = {}

    def coordinator_client(payload: dict) -> str:
        captured_payload.update(payload)
        return json.dumps(
            {
                "decision": "continue",
                "next_step_id": "describe",
                "selected_next_action": "describe active dataset",
                "required_tool": "describe_dataset",
                "required_inputs": {},
                "reason": "Step is validated.",
                "user_question": "",
                "confidence": 0.9,
            }
        )

    runtime = _runtime(enabled=True, mode="shadow")
    result = RuntimePlannerAdapter(runtime).build_coordinator_decision_diagnostic(
        {"workflow_plan": [{"step_id": "describe", "tool_name": "describe_dataset"}]},
        current_step=None,
        remaining_steps=[{"step_id": "describe", "tool_name": "describe_dataset"}],
        execution_trace={"results": [], "remaining_step_ids": ["describe"]},
        user_request="describe data",
        client=coordinator_client,
    )

    assert result["status"] == "ready"
    assert result["executes_tools"] is False
    assert result["runtime_adapter"]["executes_tools"] is False
    assert captured_payload["tool_cards"][0]["name"] == "generic_xgboost_workflow"
    assert runtime.trace_snapshot()[-1]["event"] == "coordinator_diagnostic"


def test_runtime_planner_adapter_coordinator_defaults_to_plan_scoped_tool_cards() -> None:
    from core.agent_runtime.planner import RuntimePlannerAdapter

    captured_payload: dict = {}

    def coordinator_client(payload: dict) -> str:
        captured_payload.update(payload)
        return json.dumps(
            {
                "decision": "continue",
                "next_step_id": "clip",
                "selected_next_action": "clip raster",
                "required_tool": "clip_raster_by_vector",
                "required_inputs": {},
                "reason": "Step is validated.",
                "user_question": "",
                "confidence": 0.9,
            }
        )

    runtime = _runtime_with_tools(["describe_dataset", "clip_raster_by_vector", "make_map"])
    result = RuntimePlannerAdapter(runtime).build_coordinator_decision_diagnostic(
        {"workflow_plan": [{"step_id": "clip", "tool_name": "clip_raster_by_vector"}]},
        current_step=None,
        remaining_steps=[{"step_id": "clip", "tool_name": "clip_raster_by_vector"}],
        execution_trace={"results": [], "remaining_step_ids": ["clip"]},
        user_request="clip dem",
        client=coordinator_client,
    )

    assert result["status"] == "ready"
    assert [card["name"] for card in captured_payload["tool_cards"]] == ["clip_raster_by_vector"]


def test_runtime_planner_adapter_coordinator_fills_missing_required_tool_from_next_step() -> None:
    from core.agent_runtime.planner import RuntimePlannerAdapter

    def coordinator_client(payload: dict) -> str:
        return json.dumps(
            {
                "decision": "continue",
                "next_step_id": "points",
                "selected_next_action": "convert table",
                "required_tool": "",
                "required_inputs": {},
                "reason": "Step is validated.",
                "user_question": "",
                "confidence": 0.9,
            }
        )

    runtime = _runtime_with_tools(["table_to_points"])
    result = RuntimePlannerAdapter(runtime).build_coordinator_decision_diagnostic(
        {"workflow_plan": [{"step_id": "points", "tool_name": "table_to_points"}]},
        current_step=None,
        remaining_steps=[{"step_id": "points", "tool_name": "table_to_points"}],
        execution_trace={"results": [], "remaining_step_ids": ["points"]},
        user_request="convert table",
        client=coordinator_client,
    )

    assert result["status"] == "ready"
    assert result["decision"].required_tool == "table_to_points"


def test_service_shadow_plan_helper_preserves_legacy_shadow_path_when_runtime_disabled(monkeypatch) -> None:
    from core.service import GISWorkspaceService

    service = object.__new__(GISWorkspaceService)
    expected = {"status": "disabled", "mode": "shadow", "planner_source": "disabled", "executes_tools": False}

    monkeypatch.delenv("GIS_AGENT_RUNTIME_V2", raising=False)
    monkeypatch.setattr("core.service.build_shadow_llm_task_plan", lambda prompt, context, plan: expected)

    result = GISWorkspaceService._build_shadow_task_plan(
        service,
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
    )

    assert result == expected


def test_service_shadow_plan_helper_uses_runtime_adapter_when_runtime_enabled(monkeypatch) -> None:
    from core.service import GISWorkspaceService

    runtime = _runtime(enabled=True, mode="shadow")

    class Agent:
        agent_runtime = runtime

    service = object.__new__(GISWorkspaceService)
    service.selected_model = "dummy-model"
    service._get_agent = lambda model_name: Agent()

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        assert context["agent_policy"]["runtime"]["mode"] == "shadow"
        assert enabled is True
        return {"status": "ready", "mode": "shadow", "planner_source": "runtime_test", "executes_tools": False}

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "shadow")
    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = GISWorkspaceService._build_shadow_task_plan(
        service,
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
    )

    assert result["status"] == "ready"
    assert result["runtime_adapter"]["enabled"] is True
    assert result["runtime_adapter"]["mode"] == "shadow"
    assert result["runtime_adapter"]["executes_tools"] is False
    assert result["runtime_adapter"]["cutover_guard"]["active_requested"] is False
    assert [item["event"] for item in runtime.trace_snapshot()] == ["context_merge", "planner_shadow"]
    assert runtime.diagnostics()["decision_trace"]["planner"]["status"] == "ready"
    assert runtime.diagnostics()["decision_trace"]["executes_tools"] is False


def test_service_active_plan_helper_falls_back_to_legacy_when_cutover_guard_blocks(monkeypatch) -> None:
    from core.service import GISWorkspaceService

    service = object.__new__(GISWorkspaceService)
    expected = {"status": "ready", "mode": "active", "planner_source": "legacy_test", "plan": {"task_type": "legacy"}}

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.delenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", raising=False)
    monkeypatch.setattr("core.service.build_llm_task_plan", lambda prompt, context: expected)

    result = GISWorkspaceService._build_active_task_plan(
        service,
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
    )

    assert result == expected


def test_service_active_plan_helper_uses_runtime_adapter_when_cutover_allowed(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.service import GISWorkspaceService

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)

    class Agent:
        agent_runtime = runtime

    service = object.__new__(GISWorkspaceService)
    service.selected_model = "dummy-model"
    service._get_agent = lambda model_name: Agent()

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        assert enabled is True
        return {
            "status": "ready",
            "mode": "shadow",
            "planner_source": "runtime_test",
            "executes_tools": False,
            "plan": {"task_type": "modeling", "workflow_plan": [{"tool_name": "generic_xgboost_workflow"}]},
        }

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING", "0")
    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = GISWorkspaceService._build_active_task_plan(
        service,
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
    )

    assert result["status"] == "ready"
    assert result["mode"] == "active"
    assert result["planner_source"] == "runtime_active:runtime_test"
    assert result["runtime_adapter"]["cutover_guard"]["active_effective"] is True
    assert runtime.diagnostics()["decision_trace"]["planner"]["status"] == "ready"


def test_service_active_plan_helper_uses_legacy_when_exposure_routing_misses(monkeypatch, tmp_path: Path) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.service import GISWorkspaceService

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)
    smoke = tmp_path / "active_smoke.json"
    smoke.write_text(
        json.dumps({"summary": {"case_count": 9, "passed": 9, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )

    class Agent:
        agent_runtime = runtime

    service = object.__new__(GISWorkspaceService)
    service.selected_model = "dummy-model"
    service.current_user_id = "u_1"
    service.current_session_id = "s_1"
    service._get_agent = lambda model_name: Agent()

    expected = {"status": "ready", "mode": "active", "planner_source": "legacy_test", "plan": {"task_type": "legacy"}}

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_ENV", "staging")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_PERCENT", "0")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_SMOKE_REPORT", str(smoke))
    monkeypatch.setattr("core.service.build_llm_task_plan", lambda prompt, context: expected)

    result = GISWorkspaceService._build_active_task_plan(
        service,
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
    )

    assert result["planner_source"] == "legacy_test"
    assert result["runtime_exposure_routing"]["routing_enforced"] is True
    assert result["runtime_exposure_routing"]["use_active_runtime"] is False


def test_service_active_plan_helper_uses_runtime_when_exposure_routing_hits(monkeypatch, tmp_path: Path) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.service import GISWorkspaceService

    runtime = _runtime(enabled=True, mode="active")
    runtime.config = AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True)
    smoke = tmp_path / "active_smoke.json"
    smoke.write_text(
        json.dumps({"summary": {"case_count": 9, "passed": 9, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )

    class Agent:
        agent_runtime = runtime

    service = object.__new__(GISWorkspaceService)
    service.selected_model = "dummy-model"
    service.current_user_id = "u_1"
    service.current_session_id = "s_1"
    service._get_agent = lambda model_name: Agent()

    def fake_shadow(prompt, context, deterministic_plan, *, client=None, enabled=None):
        assert enabled is True
        return {
            "status": "ready",
            "mode": "shadow",
            "planner_source": "runtime_test",
            "executes_tools": False,
            "plan": {"task_type": "modeling", "workflow_plan": [{"tool_name": "generic_xgboost_workflow"}]},
        }

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_ENV", "staging")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_PERCENT", "10")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_SALT", "test-salt-7")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_SMOKE_REPORT", str(smoke))
    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", fake_shadow)

    result = GISWorkspaceService._build_active_task_plan(
        service,
        "train xgboost",
        _planner_context(),
        {"task_type": "modeling"},
    )

    assert result["planner_source"] == "runtime_active:runtime_test"
    assert result["runtime_exposure_routing"]["routing_enforced"] is True
    assert result["runtime_exposure_routing"]["use_active_runtime"] is True
