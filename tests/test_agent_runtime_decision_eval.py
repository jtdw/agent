from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_default_runtime_decision_eval_cases_cover_core_gis_workflows() -> None:
    from core.agent_runtime.decision_eval import default_runtime_decision_eval_cases

    cases = default_runtime_decision_eval_cases()
    case_ids = {case["case_id"] for case in cases}

    assert {
        "describe_uploaded_vector",
        "table_to_points",
        "soil_xgboost_modeling",
        "artifact_download_safety",
        "vector_clip_by_boundary",
        "raster_clip_by_boundary",
        "reproject_vector_to_wgs84",
        "raster_zonal_statistics",
        "map_cartography",
        "gscloud_download_confirmation",
    } <= case_ids
    assert all(case["prompt"] for case in cases)
    assert all(case["expected"]["task_type"] for case in cases)
    assert all(
        case["expected"].get("planner_tools") or case["expected"].get("coordinator_decision") == "ask_user"
        for case in cases
    )


def test_expanded_runtime_decision_eval_cases_use_existing_tool_names_and_confirmation_policy() -> None:
    from core.agent_runtime.decision_eval import default_runtime_decision_eval_cases

    cases = {case["case_id"]: case for case in default_runtime_decision_eval_cases()}

    assert cases["vector_clip_by_boundary"]["expected"]["planner_tools"] == ["vector_clip_by_vector"]
    assert cases["raster_clip_by_boundary"]["expected"]["planner_tools"] == ["clip_raster_by_vector"]
    assert cases["reproject_vector_to_wgs84"]["expected"]["planner_tools"] == ["reproject_vector"]
    assert cases["raster_zonal_statistics"]["expected"]["planner_tools"] == ["raster_zonal_stats"]
    assert cases["map_cartography"]["expected"]["planner_tools"] == ["plot_dataset"]
    assert cases["gscloud_download_confirmation"]["expected"]["planner_tools"] == ["submit_commercial_download_job"]
    assert cases["gscloud_download_confirmation"]["expected"]["requires_confirmation"] is True
    assert cases["gscloud_download_confirmation"]["expected"]["coordinator_decision"] == "ask_user"
    assert cases["artifact_download_safety"]["expected"]["planner_tools"] == []


def test_evaluate_runtime_planner_decisions_scores_task_type_and_tools() -> None:
    from core.agent_runtime.decision_eval import evaluate_runtime_planner_decisions

    cases = [
        {
            "case_id": "soil_xgboost_modeling",
            "expected": {
                "task_type": "modeling",
                "planner_tools": ["generic_xgboost_workflow"],
                "requires_confirmation": False,
            },
        },
        {
            "case_id": "table_to_points",
            "expected": {
                "task_type": "data_processing",
                "planner_tools": ["table_to_points"],
                "requires_confirmation": False,
            },
        },
    ]
    planner_outputs = {
        "soil_xgboost_modeling": {
            "task_type": "modeling",
            "planned_steps": [{"tool_name": "generic_xgboost_workflow"}],
            "requires_confirmation": False,
        },
        "table_to_points": {
            "task_type": "data_processing",
            "planned_steps": [{"tool_name": "describe_dataset"}],
            "requires_confirmation": False,
        },
    }

    result = evaluate_runtime_planner_decisions(cases, planner_outputs)

    assert result["case_count"] == 2
    assert result["passed_count"] == 1
    assert result["pass_rate"] == 0.5
    assert result["cases"][0]["passed"] is True
    assert result["cases"][1]["passed"] is False
    assert "planner_tools_mismatch" in result["cases"][1]["mismatches"]


def test_evaluate_runtime_planner_decisions_accepts_registered_tool_aliases() -> None:
    from core.agent_runtime.decision_eval import evaluate_runtime_planner_decisions

    cases = [
        {
            "case_id": "map_cartography",
            "expected": {
                "task_type": "cartography",
                "planner_tools": ["make_map"],
                "requires_confirmation": False,
            },
        },
        {
            "case_id": "gscloud_download_confirmation",
            "expected": {
                "task_type": "data_download",
                "planner_tools": ["submit_download_job"],
                "requires_confirmation": True,
            },
        },
    ]
    planner_outputs = {
        "map_cartography": {
            "task_type": "cartography",
            "planned_steps": [{"tool_name": "plot_dataset"}],
            "requires_confirmation": False,
        },
        "gscloud_download_confirmation": {
            "task_type": "data_download",
            "planned_steps": [{"tool_name": "submit_commercial_download_job"}],
            "requires_confirmation": True,
        },
    }

    result = evaluate_runtime_planner_decisions(cases, planner_outputs)

    assert result["passed_count"] == 2
    assert result["pass_rate"] == 1.0


def test_evaluate_runtime_planner_decisions_reads_nested_raw_plan_tool_plan() -> None:
    from core.agent_runtime.decision_eval import evaluate_runtime_planner_decisions

    cases = [
        {
            "case_id": "table_to_points",
            "expected": {
                "task_type": "data_processing",
                "planner_tools": ["table_to_points"],
                "requires_confirmation": False,
            },
        }
    ]
    planner_outputs = {
        "table_to_points": {
            "status": "ready",
            "plan": {
                "task_type": "data_processing",
                "tool_plan": [{"tool_name": "table_to_points", "args": {"dataset_name": "stations"}}],
                "requires_confirmation": False,
            },
        }
    }

    result = evaluate_runtime_planner_decisions(cases, planner_outputs)

    assert result["passed_count"] == 1
    assert result["cases"][0]["actual_tools"] == ["table_to_points"]


def test_evaluate_runtime_coordinator_decisions_scores_decision_and_tool() -> None:
    from core.agent_runtime.decision_eval import evaluate_runtime_coordinator_decisions

    cases = [
        {
            "case_id": "describe_uploaded_vector",
            "expected": {
                "coordinator_decision": "continue",
                "coordinator_tool": "describe_dataset",
            },
        },
        {
            "case_id": "artifact_download_safety",
            "expected": {
                "coordinator_decision": "ask_user",
                "coordinator_tool": "",
            },
        },
    ]
    coordinator_outputs = {
        "describe_uploaded_vector": {"decision": "continue", "required_tool": "describe_dataset"},
        "artifact_download_safety": {"decision": "continue", "required_tool": "download_artifact"},
    }

    result = evaluate_runtime_coordinator_decisions(cases, coordinator_outputs)

    assert result["case_count"] == 2
    assert result["passed_count"] == 1
    assert result["pass_rate"] == 0.5
    assert result["cases"][1]["passed"] is False
    assert result["cases"][1]["mismatches"] == ["coordinator_decision_mismatch", "coordinator_tool_mismatch"]


def test_evaluate_runtime_coordinator_decisions_normalizes_ask_user_to_runtime_schema() -> None:
    from core.agent_runtime.decision_eval import evaluate_runtime_coordinator_decisions

    cases = [
        {
            "case_id": "artifact_download_safety",
            "expected": {
                "coordinator_decision": "ask_user",
                "coordinator_tool": "",
            },
        },
        {
            "case_id": "gscloud_download_confirmation",
            "expected": {
                "coordinator_decision": "ask_user",
                "coordinator_tool": "",
            },
        },
    ]
    coordinator_outputs = {
        "artifact_download_safety": {"decision": "request_clarification", "required_tool": ""},
        "gscloud_download_confirmation": {"decision": "request_confirmation", "required_tool": ""},
    }

    result = evaluate_runtime_coordinator_decisions(cases, coordinator_outputs)

    assert result["case_count"] == 2
    assert result["passed_count"] == 2
    assert result["pass_rate"] == 1.0
    assert all(case["passed"] for case in result["cases"])


def test_evaluate_runtime_coordinator_decisions_accepts_registered_tool_aliases() -> None:
    from core.agent_runtime.decision_eval import evaluate_runtime_coordinator_decisions

    cases = [
        {
            "case_id": "map_cartography",
            "expected": {
                "coordinator_decision": "continue",
                "coordinator_tool": "make_map",
            },
        },
        {
            "case_id": "gscloud_download_confirmation",
            "expected": {
                "coordinator_decision": "ask_user",
                "coordinator_tool": "",
            },
        },
    ]
    coordinator_outputs = {
        "map_cartography": {"decision": "continue", "required_tool": "plot_dataset"},
        "gscloud_download_confirmation": {"decision": "request_confirmation", "required_tool": ""},
    }

    result = evaluate_runtime_coordinator_decisions(cases, coordinator_outputs)

    assert result["passed_count"] == 2
    assert result["pass_rate"] == 1.0


def test_runtime_decision_eval_report_combines_planner_and_coordinator_scores() -> None:
    from core.agent_runtime.decision_eval import runtime_decision_eval_report

    cases = [
        {
            "case_id": "describe_uploaded_vector",
            "prompt": "describe uploaded vector",
            "expected": {
                "task_type": "data_inspection",
                "planner_tools": ["describe_dataset"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "describe_dataset",
            },
        }
    ]
    outputs = {
        "describe_uploaded_vector": {
            "planner": {
                "task_type": "data_inspection",
                "planned_steps": [{"tool_name": "describe_dataset"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "describe_dataset"},
        }
    }

    report = runtime_decision_eval_report(cases, outputs)

    assert report["schema_version"] == "runtime-decision-eval/v1"
    assert report["case_count"] == 1
    assert report["planner"]["pass_rate"] == 1.0
    assert report["coordinator"]["pass_rate"] == 1.0
    assert report["ready_for_cutover_eval"] is True


def test_runtime_decision_eval_report_allows_coordinator_to_choose_a_planned_step_tool() -> None:
    from core.agent_runtime.decision_eval import runtime_decision_eval_report

    cases = [
        {
            "case_id": "raster_clip_by_boundary",
            "prompt": "clip dem",
            "expected": {
                "task_type": "data_processing",
                "planner_tools": ["clip_raster_by_vector"],
                "requires_confirmation": False,
                "coordinator_decision": "continue",
                "coordinator_tool": "clip_raster_by_vector",
            },
        }
    ]
    outputs = {
        "raster_clip_by_boundary": {
            "planner": {
                "task_type": "data_processing",
                "planned_steps": [{"tool_name": "describe_dataset"}, {"tool_name": "clip_raster_by_vector"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "describe_dataset"},
        }
    }

    report = runtime_decision_eval_report(cases, outputs)

    assert report["planner"]["pass_rate"] == 1.0
    assert report["coordinator"]["pass_rate"] == 1.0
    assert report["coordinator"]["cases"][0]["allowed_tools"] == ["describe_dataset", "clip_raster_by_vector"]


def test_runtime_decision_eval_cli_outputs_fixtures_without_running_decisions() -> None:
    from core.agent_runtime.decision_eval import run_decision_eval_cli

    code, payload = run_decision_eval_cli(["fixtures"])

    assert code == 0
    assert payload["command"] == "fixtures"
    assert payload["case_count"] >= 4
    assert payload["operations"]["llm_calls_performed"] == 0
    assert payload["operations"]["tool_calls_performed"] == 0


def test_runtime_decision_eval_cli_report_scores_outputs_file() -> None:
    from core.agent_runtime.decision_eval import run_decision_eval_cli

    outputs = {
        "describe_uploaded_vector": {
            "planner": {
                "task_type": "data_inspection",
                "planned_steps": [{"tool_name": "describe_dataset"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "describe_dataset"},
        },
        "table_to_points": {
            "planner": {
                "task_type": "data_processing",
                "planned_steps": [{"tool_name": "table_to_points"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "table_to_points"},
        },
        "soil_xgboost_modeling": {
            "planner": {
                "task_type": "modeling",
                "planned_steps": [{"tool_name": "generic_xgboost_workflow"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "generic_xgboost_workflow"},
        },
        "artifact_download_safety": {
            "planner": {
                "task_type": "artifact_download",
                "planned_steps": [],
                "requires_confirmation": True,
            },
            "coordinator": {"decision": "ask_user", "required_tool": ""},
        },
        "vector_clip_by_boundary": {
            "planner": {
                "task_type": "data_processing",
                "planned_steps": [{"tool_name": "vector_clip_by_vector"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "vector_clip_by_vector"},
        },
        "raster_clip_by_boundary": {
            "planner": {
                "task_type": "data_processing",
                "planned_steps": [{"tool_name": "clip_raster_by_vector"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "clip_raster_by_vector"},
        },
        "reproject_vector_to_wgs84": {
            "planner": {
                "task_type": "data_processing",
                "planned_steps": [{"tool_name": "reproject_vector"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "reproject_vector"},
        },
        "raster_zonal_statistics": {
            "planner": {
                "task_type": "analysis",
                "planned_steps": [{"tool_name": "raster_zonal_stats"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "raster_zonal_stats"},
        },
        "map_cartography": {
            "planner": {
                "task_type": "cartography",
                "planned_steps": [{"tool_name": "plot_dataset"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "plot_dataset"},
        },
        "gscloud_download_confirmation": {
            "planner": {
                "task_type": "data_download",
                "planned_steps": [{"tool_name": "submit_commercial_download_job"}],
                "requires_confirmation": True,
            },
            "coordinator": {"decision": "ask_user", "required_tool": ""},
        },
    }

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "outputs.json"
        path.write_text(json.dumps(outputs), encoding="utf-8")
        code, payload = run_decision_eval_cli(["report", "--outputs", str(path), "--min-pass-rate", "0.8"])

    assert code == 0
    assert payload["command"] == "report"
    assert payload["report"]["ready_for_cutover_eval"] is True
    assert payload["operations"]["llm_calls_performed"] == 0
    assert payload["operations"]["tool_calls_performed"] == 0
    assert str(path) not in str(payload)


def test_runtime_decision_eval_cli_report_returns_failure_code_below_threshold() -> None:
    from core.agent_runtime.decision_eval import run_decision_eval_cli

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "outputs.json"
        path.write_text("{}", encoding="utf-8")
        code, payload = run_decision_eval_cli(["report", "--outputs", str(path), "--min-pass-rate", "0.8"])

    assert code == 1
    assert payload["ok"] is False
    assert payload["report"]["ready_for_cutover_eval"] is False
    assert payload["thresholds"]["min_pass_rate"] == 0.8


def test_capture_runtime_decision_eval_output_from_decision_trace() -> None:
    from core.agent_runtime.decision_eval import capture_runtime_decision_eval_output

    trace = {
        "schema_version": "runtime-decision-trace/v1",
        "planner": {
            "task_type": "data_inspection",
            "planned_tools": ["describe_dataset"],
            "requires_confirmation": False,
        },
        "coordinator": {
            "decision": "continue",
            "required_tool": "describe_dataset",
        },
        "executes_tools": False,
    }

    output = capture_runtime_decision_eval_output("describe_uploaded_vector", trace)

    assert output == {
        "describe_uploaded_vector": {
            "planner": {
                "task_type": "data_inspection",
                "planned_steps": [{"tool_name": "describe_dataset"}],
                "requires_confirmation": False,
            },
            "coordinator": {"decision": "continue", "required_tool": "describe_dataset"},
        }
    }


def test_runtime_decision_eval_cli_capture_writes_report_ready_outputs() -> None:
    from core.agent_runtime.decision_eval import run_decision_eval_cli

    trace = {
        "decision_trace": {
            "planner": {
                "task_type": "data_inspection",
                "planned_tools": ["describe_dataset"],
                "requires_confirmation": False,
            },
            "coordinator": {
                "decision": "continue",
                "required_tool": "describe_dataset",
            },
            "executes_tools": False,
        }
    }

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        trace_path = Path(tmp) / "trace.json"
        out_path = Path(tmp) / "captured.json"
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        code, payload = run_decision_eval_cli(
            [
                "capture",
                "--trace",
                str(trace_path),
                "--case-id",
                "describe_uploaded_vector",
                "--output",
                str(out_path),
            ]
        )
        captured = json.loads(out_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["command"] == "capture"
    assert payload["case_count"] == 1
    assert payload["operations"]["llm_calls_performed"] == 0
    assert payload["operations"]["tool_calls_performed"] == 0
    assert str(trace_path) not in str(payload)
    assert "describe_uploaded_vector" in captured
    assert captured["describe_uploaded_vector"]["planner"]["planned_steps"] == [{"tool_name": "describe_dataset"}]
