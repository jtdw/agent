from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DummySettings:
    model: str = "dummy-model"
    api_key: str = "dummy-key"
    base_url: str = "https://example.invalid"
    temperature: float = 0.0
    timeout: float = 30.0
    max_retries: int = 0


class DummyManager:
    workdir = Path("workspace")
    current_user_id = "u_1"
    current_session_id = "s_1"

    def dataset_brief(self) -> str:
        return "no datasets"

    def log_operation(self, *_args, **_kwargs) -> None:
        return None


def test_runtime_config_defaults_to_disabled(monkeypatch) -> None:
    monkeypatch.delenv("GIS_AGENT_RUNTIME_V2", raising=False)

    from core.agent_runtime.config import AgentRuntimeConfig

    config = AgentRuntimeConfig.from_env()

    assert config.enabled is False
    assert config.mode == "legacy"


def test_runtime_config_can_enable_shadow_mode(monkeypatch) -> None:
    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "shadow")

    from core.agent_runtime.config import AgentRuntimeConfig

    config = AgentRuntimeConfig.from_env()

    assert config.enabled is True
    assert config.mode == "shadow"


def test_runtime_config_blocks_active_mode_without_explicit_cutover_guard(monkeypatch) -> None:
    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.delenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", raising=False)

    from core.agent_runtime.config import AgentRuntimeConfig

    config = AgentRuntimeConfig.from_env()

    assert config.enabled is True
    assert config.active_requested is True
    assert config.active_cutover_allowed is False
    assert config.mode == "shadow"
    assert config.cutover_guard() == {
        "active_requested": True,
        "active_cutover_allowed": False,
        "active_effective": False,
        "fallback_mode": "shadow",
        "reason": "active_mode_requires_GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER",
    }


def test_runtime_config_allows_active_mode_only_with_explicit_cutover_guard(monkeypatch) -> None:
    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")

    from core.agent_runtime.config import AgentRuntimeConfig

    config = AgentRuntimeConfig.from_env()

    assert config.enabled is True
    assert config.active_requested is True
    assert config.active_cutover_allowed is True
    assert config.mode == "active"
    assert config.cutover_guard()["active_effective"] is True


def test_gis_agent_keeps_legacy_harness_and_attaches_runtime(monkeypatch) -> None:
    import core.agent as agent_module

    created = object()

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeTool:
        name = "describe_dataset"
        description = "Describe the active dataset"

    fake_tool = FakeTool()

    def fake_create_agent(**kwargs):
        assert kwargs["tools"] == [fake_tool]
        return created

    monkeypatch.delenv("GIS_AGENT_RUNTIME_V2", raising=False)
    monkeypatch.setattr(agent_module, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(agent_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(agent_module, "build_tools", lambda manager: [fake_tool])
    monkeypatch.setattr(agent_module, "validate_llm_config", lambda: {"status": "valid", "errors": []})

    agent = agent_module.GISAgent(DummySettings(), DummyManager())

    assert agent.agent is created
    assert agent.agent_runtime.enabled is False
    assert agent.agent_runtime.legacy_agent is created
    assert agent.agent_runtime.tools == [fake_tool]
    assert [item.name for item in agent.agent_runtime.tool_specs] == ["describe_dataset"]
    assert agent.agent_runtime.tool_specs[0].risk_level == "low"
    assert agent.agent_runtime.tool_metadata() == [
        {
            "name": "describe_dataset",
            "description": "Describe the active dataset",
            "permissions": ["workspace:read"],
            "risk_level": "low",
        }
    ]
    assert agent.agent_runtime.context_overlay() == {
        "runtime": {
            "enabled": False,
            "mode": "legacy",
            "current_user_id": "u_1",
            "current_session_id": "s_1",
        },
        "runtime_tool_metadata": agent.agent_runtime.tool_metadata(),
    }
    assert agent.agent_runtime.context.current_user_id == "u_1"
    assert agent.agent_runtime.context.current_session_id == "s_1"
    assert agent.agent_runtime.get_tool_spec("describe_dataset").name == "describe_dataset"
    assert agent.agent_runtime.get_tool_spec("missing_tool") is None
    assert agent.agent_runtime.precheck_tool("describe_dataset") == {
        "ok": True,
        "tool_name": "describe_dataset",
        "risk_level": "low",
        "required_permissions": ["workspace:read"],
    }
    assert agent.agent_runtime.precheck_tool("missing_tool") == {
        "ok": False,
        "tool_name": "missing_tool",
        "error_code": "TOOL_NOT_REGISTERED",
    }


def test_runtime_context_preserves_manager_scope_and_tool_context(tmp_path) -> None:
    from core.agent_runtime.context import AgentRuntimeContext

    manager = DummyManager()
    manager.workdir = tmp_path

    context = AgentRuntimeContext.from_manager(manager)
    tool_context = context.to_tool_context()

    assert context.current_user_id == "u_1"
    assert context.current_session_id == "s_1"
    assert context.workspace_dir == tmp_path.resolve()
    assert tool_context.current_user_id == "u_1"
    assert tool_context.current_session_id == "s_1"
    assert tool_context.has_permission("workspace:read")


def test_runtime_context_rejects_paths_outside_workspace(tmp_path) -> None:
    from core.agent_runtime.context import AgentRuntimeContext

    context = AgentRuntimeContext(
        current_user_id="u_1",
        current_session_id="s_1",
        workspace_dir=tmp_path,
    )

    inside = tmp_path / "derived" / "result.geojson"
    outside = tmp_path.parent / "secret.env"

    assert context.resolve_workspace_path(inside) == inside.resolve(strict=False)

    try:
        context.resolve_workspace_path(outside)
    except PermissionError as exc:
        assert "outside workspace" in str(exc)
    else:
        raise AssertionError("outside workspace path should be rejected")


def test_tool_adapter_builds_read_only_metadata_without_wrapping_execution() -> None:
    from core.agent_runtime.tools import RuntimeToolSpec, build_runtime_tool_specs

    class FakeTool:
        name = "plot_dataset"
        description = "Render a dataset map"

    specs = build_runtime_tool_specs([FakeTool()])

    assert specs == [
        RuntimeToolSpec(
            name="plot_dataset",
            description="Render a dataset map",
            permissions=frozenset({"workspace:read", "workspace:write"}),
            risk_level="medium",
            original_tool=specs[0].original_tool,
        )
    ]
    assert specs[0].original_tool.__class__ is FakeTool


def test_tool_adapter_deduplicates_and_classifies_download_tools() -> None:
    from core.agent_runtime.tools import build_runtime_tool_specs

    class FakeTool:
        def __init__(self, name: str):
            self.name = name
            self.description = ""

    specs = build_runtime_tool_specs(
        [
            FakeTool("submit_commercial_download_job"),
            FakeTool("submit_commercial_download_job"),
            FakeTool("describe_dataset"),
        ]
    )

    assert [item.name for item in specs] == ["submit_commercial_download_job", "describe_dataset"]
    assert specs[0].risk_level == "high"
    assert "network:download" in specs[0].permissions
    assert specs[1].risk_level == "low"


def test_tool_spec_metadata_does_not_expose_original_tool_object() -> None:
    from core.agent_runtime.tools import build_runtime_tool_specs

    class FakeTool:
        name = "export_dataset"
        description = "Export a dataset"

    spec = build_runtime_tool_specs([FakeTool()])[0]

    assert spec.to_metadata() == {
        "name": "export_dataset",
        "description": "Export a dataset",
        "permissions": ["workspace:read", "workspace:write"],
        "risk_level": "medium",
    }


def test_tool_precheck_requires_permissions_before_high_risk_download() -> None:
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.tools import build_runtime_tool_specs, precheck_tool_spec

    class FakeTool:
        name = "submit_commercial_download_job"
        description = "Start download"

    context = AgentRuntimeContext(
        current_user_id="u_1",
        current_session_id="s_1",
        workspace_dir=Path("workspace"),
        permission_scope=frozenset({"workspace:read", "workspace:write"}),
    )
    spec = build_runtime_tool_specs([FakeTool()])[0]

    result = precheck_tool_spec(spec, context)

    assert result["ok"] is False
    assert result["error_code"] == "TOOL_PERMISSION_DENIED"
    assert result["missing_permissions"] == ["network:download"]


def test_tool_precheck_passes_when_required_permissions_exist() -> None:
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.tools import build_runtime_tool_specs, precheck_tool_spec

    class FakeTool:
        name = "submit_commercial_download_job"
        description = "Start download"

    context = AgentRuntimeContext(
        current_user_id="u_1",
        current_session_id="s_1",
        workspace_dir=Path("workspace"),
        permission_scope=frozenset({"workspace:read", "workspace:write", "network:download"}),
    )
    spec = build_runtime_tool_specs([FakeTool()])[0]

    result = precheck_tool_spec(spec, context)

    assert result == {
        "ok": True,
        "tool_name": "submit_commercial_download_job",
        "risk_level": "high",
        "required_permissions": ["network:download", "workspace:read", "workspace:write"],
    }


def test_format_context_for_agent_preserves_runtime_overlay() -> None:
    import json

    from core.context_builder import format_context_for_agent

    formatted = format_context_for_agent(
        {
            "intent": {"intent": "data_processing"},
            "runtime": {"enabled": False, "mode": "legacy", "current_user_id": "u_1", "current_session_id": "s_1"},
            "runtime_tool_metadata": [
                {
                    "name": "describe_dataset",
                    "description": "Describe the active dataset",
                    "permissions": ["workspace:read"],
                    "risk_level": "low",
                }
            ],
        }
    )
    payload = json.loads(formatted)

    assert payload["runtime"]["mode"] == "legacy"
    assert payload["runtime_tool_metadata"][0]["name"] == "describe_dataset"


def test_runtime_merge_context_is_noop_when_disabled() -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    runtime = GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=False, mode="legacy"),
    )
    context = {"intent": {"intent": "data_processing"}}

    assert runtime.merge_context(context) == context
    assert runtime.merge_context(context) is not context


def test_runtime_merge_context_adds_overlay_when_enabled() -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    class FakeTool:
        name = "describe_dataset"
        description = "Describe"

    runtime = GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[FakeTool()],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=True, mode="shadow"),
    )
    context = {"intent": {"intent": "data_processing"}}

    merged = runtime.merge_context(context)

    assert merged["intent"] == {"intent": "data_processing"}
    assert merged["runtime"]["mode"] == "shadow"
    assert merged["runtime_tool_metadata"][0]["name"] == "describe_dataset"


def test_runtime_diagnostics_include_active_cutover_guard() -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    runtime = GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=True, mode="shadow", active_requested=True, active_cutover_allowed=False),
    )

    diagnostics = runtime.diagnostics()

    assert diagnostics["cutover_guard"]["active_requested"] is True
    assert diagnostics["cutover_guard"]["active_cutover_allowed"] is False
    assert diagnostics["cutover_guard"]["active_effective"] is False


def test_runtime_refresh_context_updates_cached_manager_scope(tmp_path) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    class Manager:
        current_user_id = "u_old"
        current_session_id = "s_old"
        workdir = tmp_path

    manager = Manager()
    runtime = GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext.from_manager(manager),
        config=AgentRuntimeConfig(enabled=True, mode="shadow"),
    )

    manager.current_user_id = "u_new"
    manager.current_session_id = "s_new"
    runtime.refresh_context(manager)

    assert runtime.context.current_user_id == "u_new"
    assert runtime.context.current_session_id == "s_new"
    assert runtime.context.workspace_dir == tmp_path.resolve()


def test_runtime_summarizes_tool_risks_and_prechecks_all_tools() -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    class DescribeTool:
        name = "describe_dataset"
        description = "Describe"

    class DownloadTool:
        name = "submit_commercial_download_job"
        description = "Download"

    runtime = GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[DescribeTool(), DownloadTool()],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(
            current_user_id="u_1",
            current_session_id="s_1",
            workspace_dir=Path("workspace"),
            permission_scope=frozenset({"workspace:read", "workspace:write"}),
        ),
        config=AgentRuntimeConfig(enabled=True, mode="shadow"),
    )

    assert runtime.tool_risk_summary() == {"high": 1, "low": 1, "medium": 0}

    prechecks = runtime.precheck_all_tools()

    assert [item["tool_name"] for item in prechecks] == ["describe_dataset", "submit_commercial_download_job"]
    assert prechecks[0]["ok"] is True
    assert prechecks[1]["ok"] is False
    assert prechecks[1]["missing_permissions"] == ["network:download"]
    assert runtime.tool_precheck_summary()["failed"] == 1
    assert runtime.tool_precheck_summary()["total"] == 2


def test_service_get_agent_refreshes_cached_runtime_context() -> None:
    from core.service import GISWorkspaceService

    class Runtime:
        def __init__(self) -> None:
            self.refreshed_with = []

        def refresh_context(self, manager) -> None:
            self.refreshed_with.append(manager)

    class Agent:
        def __init__(self) -> None:
            self.agent_runtime = Runtime()

    manager = object()
    agent = Agent()
    service = object.__new__(GISWorkspaceService)
    service.manager = manager
    service._agents = {"dummy-model": agent}

    returned = GISWorkspaceService._get_agent(service, "dummy-model")

    assert returned is agent
    assert agent.agent_runtime.refreshed_with == [manager]


def test_service_exposes_agent_runtime_diagnostics_for_cached_agent() -> None:
    from core.service import GISWorkspaceService

    class Runtime:
        def __init__(self) -> None:
            self.refreshed_with = []

        def refresh_context(self, manager) -> None:
            self.refreshed_with.append(manager)

        def diagnostics(self) -> dict:
            return {"enabled": True, "mode": "shadow", "tool_count": 1}

    class Agent:
        def __init__(self) -> None:
            self.agent_runtime = Runtime()

    manager = object()
    agent = Agent()
    service = object.__new__(GISWorkspaceService)
    service.manager = manager
    service.selected_model = "dummy-model"
    service._agents = {"dummy-model": agent}

    diagnostics = GISWorkspaceService.agent_runtime_diagnostics(service)

    assert diagnostics == {"available": True, "enabled": True, "mode": "shadow", "tool_count": 1}
    assert agent.agent_runtime.refreshed_with == [manager]
