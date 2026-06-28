from __future__ import annotations

import json
from pathlib import Path


def _passing_smoke_report(tmp_path: Path) -> Path:
    report = tmp_path / "active_smoke.json"
    report.write_text(
        json.dumps({"summary": {"case_count": 9, "passed": 9, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )
    return report


def test_traffic_router_is_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    from core.agent_runtime.exposure import AgentRuntimeExposurePolicy
    from core.agent_runtime.traffic import AgentRuntimeTrafficRouter

    monkeypatch.delenv("GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING", raising=False)
    policy = AgentRuntimeExposurePolicy(
        environment="staging",
        requested_percent=1,
        deterministic_smoke_report=_passing_smoke_report(tmp_path),
    )

    decision = AgentRuntimeTrafficRouter.from_env().decide(
        policy.evaluate({"active_effective": True}),
        user_id="u_1",
        session_id="s_1",
        request_text="make a map",
    )

    assert decision["routing_enforced"] is False
    assert decision["use_active_runtime"] is True
    assert decision["reason"] == "routing_not_enforced"


def test_traffic_router_blocks_when_policy_is_not_eligible(monkeypatch, tmp_path: Path) -> None:
    from core.agent_runtime.exposure import AgentRuntimeExposurePolicy
    from core.agent_runtime.traffic import AgentRuntimeTrafficRouter

    monkeypatch.setenv("GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING", "1")
    policy = AgentRuntimeExposurePolicy(
        environment="staging",
        requested_percent=100,
        rollback_requested=True,
        deterministic_smoke_report=_passing_smoke_report(tmp_path),
    )

    decision = AgentRuntimeTrafficRouter.from_env().decide(
        policy.evaluate({"active_effective": True}),
        user_id="u_1",
        session_id="s_1",
        request_text="make a map",
    )

    assert decision["routing_enforced"] is True
    assert decision["use_active_runtime"] is False
    assert decision["reason"] == "exposure_policy_not_eligible"
    assert "rollback_requested" in decision["policy_reasons"]


def test_traffic_router_uses_stable_percentage_bucket(monkeypatch, tmp_path: Path) -> None:
    from core.agent_runtime.exposure import AgentRuntimeExposurePolicy
    from core.agent_runtime.traffic import AgentRuntimeTrafficRouter

    monkeypatch.setenv("GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_SALT", "test-salt-2")
    policy = AgentRuntimeExposurePolicy(
        environment="staging",
        requested_percent=10,
        deterministic_smoke_report=_passing_smoke_report(tmp_path),
    ).evaluate({"active_effective": True})

    router = AgentRuntimeTrafficRouter.from_env()
    first = router.decide(policy, user_id="u_1", session_id="s_1", request_text="make a map")
    second = router.decide(policy, user_id="u_1", session_id="s_1", request_text="make a map")

    assert first["use_active_runtime"] is True
    assert first["bucket"] == second["bucket"]
    assert first["bucket_key"] == second["bucket_key"]
    assert 0 <= first["bucket"] <= 99
