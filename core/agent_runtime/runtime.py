from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AgentRuntimeConfig
from .context import AgentRuntimeContext
from .trace import RuntimeTraceBuffer
from .tools import RuntimeToolSpec, build_runtime_tool_specs, precheck_tool_spec


@dataclass(slots=True)
class GISAgentRuntime:
    config: AgentRuntimeConfig
    model: Any
    tools: list[Any]
    system_prompt: str
    legacy_agent: Any
    context: AgentRuntimeContext
    tool_specs: list[RuntimeToolSpec]
    trace: RuntimeTraceBuffer

    @classmethod
    def from_legacy_agent(
        cls,
        *,
        model: Any,
        tools: list[Any],
        system_prompt: str,
        legacy_agent: Any,
        context: AgentRuntimeContext,
        config: AgentRuntimeConfig | None = None,
    ) -> "GISAgentRuntime":
        return cls(
            config=config or AgentRuntimeConfig.from_env(),
            model=model,
            tools=list(tools),
            system_prompt=system_prompt,
            legacy_agent=legacy_agent,
            context=context,
            tool_specs=build_runtime_tool_specs(tools),
            trace=RuntimeTraceBuffer(),
        )

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def mode(self) -> str:
        return self.config.mode

    def tool_metadata(self) -> list[dict[str, Any]]:
        return [spec.to_metadata() for spec in self.tool_specs]

    def get_tool_spec(self, tool_name: str) -> RuntimeToolSpec | None:
        clean = str(tool_name or "").strip()
        for spec in self.tool_specs:
            if spec.name == clean:
                return spec
        return None

    def precheck_tool(self, tool_name: str) -> dict[str, Any]:
        spec = self.get_tool_spec(tool_name)
        if spec is None:
            result = {
                "ok": False,
                "tool_name": str(tool_name or "").strip(),
                "error_code": "TOOL_NOT_REGISTERED",
            }
            self.record_trace_event("tool_precheck", result)
            return result
        result = precheck_tool_spec(spec, self.context)
        self.record_trace_event("tool_precheck", result)
        return result

    def precheck_all_tools(self) -> list[dict[str, Any]]:
        return [self.precheck_tool(spec.name) for spec in self.tool_specs]

    def tool_precheck_summary(self) -> dict[str, int]:
        results = self.precheck_all_tools()
        failed = sum(1 for item in results if not bool(item.get("ok")))
        return {
            "total": len(results),
            "failed": failed,
            "passed": len(results) - failed,
        }

    def tool_risk_summary(self) -> dict[str, int]:
        summary = {"high": 0, "low": 0, "medium": 0}
        for spec in self.tool_specs:
            risk = spec.risk_level if spec.risk_level in summary else "medium"
            summary[risk] += 1
        return summary

    def refresh_context(self, manager: Any) -> None:
        self.context = AgentRuntimeContext.from_manager(manager)
        self.record_trace_event("context_refresh", self.context.to_metadata())

    def record_trace_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        self.trace.record(
            event,
            payload,
            runtime_mode=self.mode,
            current_session_id=self.context.current_session_id,
        )

    def trace_snapshot(self) -> list[dict[str, Any]]:
        return self.trace.snapshot()

    def diagnostics(self) -> dict[str, Any]:
        from .chains import RuntimeChainAdapter
        from .decision_trace import build_runtime_decision_trace
        from .exposure import AgentRuntimeExposurePolicy
        from .planner import RuntimePlannerAdapter

        cutover_guard = self.config.cutover_guard()
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "context": self.context.to_metadata(),
            "tool_count": len(self.tool_specs),
            "tool_risk_summary": self.tool_risk_summary(),
            "tools": self.tool_metadata(),
            "cutover_guard": cutover_guard,
            "exposure_policy": AgentRuntimeExposurePolicy.from_env().evaluate(cutover_guard),
            "planner_adapter": RuntimePlannerAdapter(self).diagnostics(),
            "chain_adapter": RuntimeChainAdapter().diagnostics(),
            "decision_trace": build_runtime_decision_trace(self),
            "trace_events": self.trace_snapshot(),
        }

    def context_overlay(self) -> dict[str, Any]:
        return {
            "runtime": {
                "enabled": self.enabled,
                "mode": self.mode,
                "current_user_id": self.context.current_user_id,
                "current_session_id": self.context.current_session_id,
            },
            "runtime_tool_metadata": self.tool_metadata(),
        }

    def merge_context(self, context: dict[str, Any]) -> dict[str, Any]:
        merged = dict(context)
        if not self.enabled:
            self.record_trace_event("context_merge", {"enabled": False, "merged": False})
            return merged
        merged.update(self.context_overlay())
        self.record_trace_event("context_merge", {"enabled": True, "merged": True})
        return merged

    def invoke(self, payload: dict[str, Any]) -> Any:
        return self.legacy_agent.invoke(payload)
