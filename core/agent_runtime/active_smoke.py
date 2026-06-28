from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from unittest import mock
from uuid import uuid4

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point
from shapely.geometry import box

from core.data_semantics import attach_semantic_card_to_dataset, build_data_semantic_card
from core.agent_runtime.context import AgentRuntimeContext
from core.agent_runtime.config import AgentRuntimeConfig
from core.agent_runtime.runtime import GISAgentRuntime
from core.config import Settings
from core.service import GISWorkspaceService
from core.tools.registry import build_tools


CaseSetup = Callable[[GISWorkspaceService], dict[str, Any]]


EXTERNAL_TOOL_TOKENS = ("download", "gscloud", "commercial", "submit")


def _continue_current_step(plan, current_step, remaining_steps, execution_trace, user_request, **kwargs):
    if not current_step:
        return {"status": "ready", "decision": {"decision": "stop_success", "confidence": 0.9}}
    return {
        "status": "ready",
        "decision": {
            "decision": "continue",
            "next_step_id": current_step.get("step_id") or current_step.get("tool_name") or "",
            "selected_next_action": "run safe smoke step",
            "required_tool": current_step.get("tool_name") or "",
            "required_inputs": current_step.get("validated_tool_args") or current_step.get("args") or {},
            "reason": "deterministic smoke coordinator",
            "user_question": "",
            "confidence": 0.9,
        },
    }


@contextmanager
def _coordinator_patch(mode: str):
    normalized = str(mode or "").strip().lower()
    if normalized == "deterministic":
        with mock.patch("core.coordinated_executor.build_coordinator_decision", side_effect=_continue_current_step):
            yield
        return
    if normalized == "llm":
        yield
        return
    raise ValueError(f"unsupported coordinator_mode: {mode}")


def _active_map_generation(service: GISWorkspaceService) -> dict[str, Any]:
    service.manager.put_vector(
        "county",
        gpd.GeoDataFrame(
            {"pop_density": [10.0, 20.0], "geometry": [Point(0, 0), Point(1, 1)]},
            crs="EPSG:4326",
        ),
    )
    return {
        "prompt": "plot population density map",
        "frontend_context": {"active_dataset_id": "county"},
        "expected_tools": ["plot_dataset"],
    }


def _active_map_generation_secondary_vector(service: GISWorkspaceService) -> dict[str, Any]:
    service.manager.put_vector(
        "districts",
        gpd.GeoDataFrame(
            {"pop_density": [30.0, 40.0], "geometry": [Point(2, 2), Point(3, 3)]},
            crs="EPSG:4326",
        ),
    )
    return {
        "prompt": "plot population density map",
        "frontend_context": {"active_dataset_id": "districts"},
        "expected_tools": ["plot_dataset"],
    }


def _active_describe_vector(service: GISWorkspaceService) -> dict[str, Any]:
    service.manager.put_vector(
        "parcels",
        gpd.GeoDataFrame(
            {"area": [1.0, 2.0], "geometry": [Point(0, 0), Point(1, 1)]},
            crs="EPSG:4326",
        ),
    )
    return {
        "prompt": "check this dataset",
        "frontend_context": {"active_dataset_id": "parcels"},
        "expected_tools": ["describe_dataset"],
    }


def _active_describe_table(service: GISWorkspaceService) -> dict[str, Any]:
    service.manager.put_table("attributes.csv", pd.DataFrame({"name": ["a", "b"], "value": [1.0, 2.0]}))
    return {
        "prompt": "check this dataset",
        "frontend_context": {"active_dataset_id": "attributes.csv"},
        "expected_tools": ["describe_dataset"],
    }


def _workflow_priority_table_to_points(service: GISWorkspaceService) -> dict[str, Any]:
    service.manager.put_table("stations.csv", pd.DataFrame({"lon": [104.1], "lat": [30.6], "name": ["a"]}))
    return {
        "prompt": "convert table to points using lon and lat fields, output stations_points",
        "frontend_context": {"active_dataset_id": "stations.csv"},
        "expected_tools": ["table_to_points"],
    }


def _write_smoke_raster(service: GISWorkspaceService, name: str = "dem") -> str:
    data = np.arange(100, dtype="float32").reshape(10, 10)
    path = service.manager.upload_dir / f"{name}.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0.0, 10.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)
    return service.manager.put_raster_path(name, path, meta={"crs": "EPSG:4326"})


def _active_raster_basic_stats(service: GISWorkspaceService) -> dict[str, Any]:
    raster_name = _write_smoke_raster(service, "dem")
    return {
        "prompt": "calculate basic raster statistics for the active DEM",
        "frontend_context": {"active_dataset_id": raster_name},
        "expected_tools": ["raster_basic_stats"],
    }


def _active_raster_clip_by_boundary(service: GISWorkspaceService) -> dict[str, Any]:
    raster_name = _write_smoke_raster(service, "dem")
    service.manager.put_vector(
        "watershed",
        gpd.GeoDataFrame({"name": ["a"], "geometry": [box(1.0, 1.0, 8.0, 8.0)]}, crs="EPSG:4326"),
    )
    return {
        "prompt": "clip raster DEM by the watershed vector boundary",
        "frontend_context": {"active_dataset_id": raster_name, "selected_layer_id": "watershed"},
        "expected_tools": ["clip_raster_by_vector"],
    }


def _active_vector_clip_map(service: GISWorkspaceService) -> dict[str, Any]:
    service.manager.put_vector(
        "parcels",
        gpd.GeoDataFrame(
            {
                "pop_density": [10.0, 20.0],
                "geometry": [box(0.0, 0.0, 2.0, 2.0), box(3.0, 3.0, 5.0, 5.0)],
            },
            crs="EPSG:4326",
        ),
    )
    service.manager.put_vector(
        "study_area",
        gpd.GeoDataFrame({"name": ["a"], "geometry": [box(-1.0, -1.0, 2.5, 2.5)]}, crs="EPSG:4326"),
    )
    return {
        "prompt": "clip this vector layer to the study area, then plot population density map",
        "frontend_context": {"active_dataset_id": "parcels", "selected_layer_id": "study_area"},
        "expected_tools": ["vector_clip_by_vector", "plot_dataset"],
    }


def _active_table_to_points_map(service: GISWorkspaceService) -> dict[str, Any]:
    service.manager.put_table(
        "stations.csv",
        pd.DataFrame({"lon": [104.1, 104.2], "lat": [30.6, 30.7], "pop_density": [12.0, 18.0]}),
    )
    return {
        "prompt": "plot population density map from the station table",
        "frontend_context": {"active_dataset_id": "stations.csv"},
        "expected_tools": ["table_to_points", "plot_dataset"],
    }


def _semantic_gcp_result_uncertainty_map(service: GISWorkspaceService) -> dict[str, Any]:
    dataset_name = service.manager.put_table(
        "xgb_gcp_predictions",
        pd.DataFrame(
            {
                "lon": [104.1, 104.2, 104.3],
                "lat": [30.6, 30.7, 30.8],
                "soil_moisture_mean": [0.18, 0.21, 0.2],
                "xgb_validation_prediction": [0.17, 0.2, 0.22],
                "xgb_validation_prediction_gcp_width": [0.04, 0.05, 0.03],
            }
        ),
    )
    attach_semantic_card_to_dataset(
        service.manager,
        dataset_name,
        build_data_semantic_card(
            dataset_name=dataset_name,
            source_kind="gcp_uncertainty_result",
            scientific_roles=["prediction_with_uncertainty", "gcp_result", "map_ready"],
            variables=[
                {"name": "soil_moisture_mean", "role": "observed"},
                {
                    "name": "xgb_validation_prediction",
                    "role": "prediction",
                    "interval_width": "xgb_validation_prediction_gcp_width",
                },
            ],
            spatial={"has_coordinates": True, "lon_col": "lon", "lat_col": "lat"},
            modeling={"uncertainty_output": True},
            row_count=3,
        ),
    )
    return {
        "prompt": "plot the GCP uncertainty map",
        "frontend_context": {"active_dataset_id": dataset_name},
        "expected_tools": ["table_to_points", "plot_dataset"],
    }


class _RuntimeOnlyAgent:
    def __init__(self, runtime: GISAgentRuntime) -> None:
        self.agent_runtime = runtime


def _attach_lightweight_runtime_agent(service: GISWorkspaceService) -> None:
    runtime = GISAgentRuntime.from_legacy_agent(
        model=None,
        tools=build_tools(service.manager),
        system_prompt="",
        legacy_agent=None,
        context=AgentRuntimeContext.from_manager(service.manager),
        config=AgentRuntimeConfig.from_env(),
    )
    service._agents[str(service.selected_model or "")] = _RuntimeOnlyAgent(runtime)


SMOKE_CASES: dict[str, CaseSetup] = {
    "active_describe_vector": _active_describe_vector,
    "active_describe_table": _active_describe_table,
    "active_map_generation": _active_map_generation,
    "active_map_generation_secondary_vector": _active_map_generation_secondary_vector,
    "workflow_priority_table_to_points": _workflow_priority_table_to_points,
    "active_raster_basic_stats": _active_raster_basic_stats,
    "active_raster_clip_by_boundary": _active_raster_clip_by_boundary,
    "active_vector_clip_map": _active_vector_clip_map,
    "active_table_to_points_map": _active_table_to_points_map,
    "semantic_gcp_result_uncertainty_map": _semantic_gcp_result_uncertainty_map,
}

DEFAULT_SMOKE_CASE_IDS = [
    "active_describe_vector",
    "active_describe_table",
    "active_map_generation",
    "active_map_generation_secondary_vector",
    "workflow_priority_table_to_points",
    "active_raster_basic_stats",
    "active_raster_clip_by_boundary",
    "active_vector_clip_map",
    "active_table_to_points_map",
]


def _latest_assistant_meta(service: GISWorkspaceService) -> dict[str, Any]:
    messages = service.manager.database.list_messages(service.current_session_id)
    for item in reversed(messages):
        if item.get("role") == "assistant" and isinstance(item.get("meta"), dict):
            return item["meta"]
    return {}


def _collect_tool_names(value: Any) -> list[str]:
    names: list[str] = []

    def add(name: Any) -> None:
        text = str(name or "").strip()
        if text and text not in names:
            names.append(text)

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            add(item.get("tool_name") or item.get("tool"))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return names


def _external_download_tools(names: Iterable[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        lowered = str(name or "").lower()
        if any(token in lowered for token in EXTERNAL_TOOL_TOKENS):
            out.append(str(name))
    return out


def _case_ok(result: dict[str, Any], expected_tools: list[str], executed_tools: list[str], status: str) -> bool:
    mode = str(result.get("mode") or "")
    if mode in {"clarification", "chat_only_blocked", "answer_only"}:
        return False
    if str(status or "").lower() in {"failed", "blocked", "error"}:
        return False
    if _external_download_tools(executed_tools):
        return False
    return all(tool in executed_tools for tool in expected_tools)


def _summarize_case(case_id: str, setup: dict[str, Any], result: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    executed_tools = _collect_tool_names({"result": result, "meta": meta})
    expected_tools = [str(item) for item in setup.get("expected_tools", []) if str(item or "").strip()]
    planner = meta.get("llm_planner") if isinstance(meta.get("llm_planner"), dict) else {}
    presentation = result.get("presentation_result") if isinstance(result.get("presentation_result"), dict) else {}
    execution_summary = result.get("execution_summary") if isinstance(result.get("execution_summary"), dict) else {}
    status = str(execution_summary.get("status") or presentation.get("status") or "")
    external_tools = _external_download_tools(executed_tools)
    return {
        "case_id": case_id,
        "ok": _case_ok(result, expected_tools, executed_tools, status),
        "mode": str(result.get("mode") or ""),
        "reason": str(result.get("reason") or ""),
        "status": status,
        "executed_tools": executed_tools,
        "expected_tools": expected_tools,
        "llm_planner": {
            "status": str(planner.get("status") or ""),
            "mode": str(planner.get("mode") or ""),
            "planner_source": str(planner.get("planner_source") or ""),
            "executes_tools": bool(planner.get("executes_tools")),
        },
        "safe_tool_execution": {
            "external_download_tools_executed": external_tools,
            "artifact_count": len(result.get("artifacts") or []),
            "image_count": len(result.get("images") or []),
        },
    }


def run_service_active_smoke(
    *,
    output_path: str | Path,
    workspace_dir: str | Path,
    coordinator_mode: str = "deterministic",
    runtime_agent: str = "lightweight",
    case_ids: list[str] | None = None,
) -> dict[str, Any]:
    selected_cases = case_ids or list(DEFAULT_SMOKE_CASE_IDS)
    unknown = [case_id for case_id in selected_cases if case_id not in SMOKE_CASES]
    if unknown:
        raise ValueError("unknown smoke case(s): " + ", ".join(unknown))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    workspace_root = Path(workspace_dir)
    workspace_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    run_workspace = workspace_root / f"run_{run_id}"
    run_workspace.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    smoke_env = {"GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING": "0"}
    with mock.patch.dict(os.environ, smoke_env, clear=False), _coordinator_patch(coordinator_mode):
        config = AgentRuntimeConfig.from_env()
        for case_id in selected_cases:
            case_workspace = run_workspace / case_id
            settings = Settings(workdir=case_workspace)
            settings.ensure_dirs()
            service = GISWorkspaceService(settings)
            service.set_request_context(user_id="phase21_smoke", create_if_missing=True)
            service.set_interaction_mode("tool_enabled")
            if runtime_agent == "lightweight":
                _attach_lightweight_runtime_agent(service)
            elif runtime_agent != "real":
                raise ValueError(f"unsupported runtime_agent: {runtime_agent}")
            setup = SMOKE_CASES[case_id](service)
            result = service.ask(
                str(setup["prompt"]),
                frontend_context=setup.get("frontend_context") if isinstance(setup.get("frontend_context"), dict) else None,
            )
            cases.append(_summarize_case(case_id, setup, result, _latest_assistant_meta(service)))

    failed = [case for case in cases if not case.get("ok")]
    report = {
        "schema_version": "agent-runtime-service-active-smoke/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "run_id": run_id,
            "enabled": config.enabled,
            "mode": config.mode,
            "cutover_guard": config.cutover_guard(),
            "coordinator_mode": coordinator_mode,
            "runtime_agent": runtime_agent,
        },
        "summary": {
            "case_count": len(cases),
            "passed": len(cases) - len(failed),
            "failed": len(failed),
            "ready_for_next_phase": not failed and bool(config.cutover_guard().get("active_effective")),
        },
        "cases": cases,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def run_active_smoke_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run guarded service-level Agent Runtime active smoke checks.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    service_parser = subparsers.add_parser("service")
    service_parser.add_argument("--output", default="outputs/agent_runtime_service_active_smoke.json")
    service_parser.add_argument("--workspace", default="outputs/agent_runtime_service_active_smoke_workspace")
    service_parser.add_argument("--coordinator-mode", choices=("deterministic", "llm"), default="deterministic")
    service_parser.add_argument("--runtime-agent", choices=("lightweight", "real"), default="lightweight")
    service_parser.add_argument("--case", action="append", dest="cases", choices=tuple(SMOKE_CASES))
    service_parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "service":
        report = run_service_active_smoke(
            output_path=args.output,
            workspace_dir=args.workspace,
            coordinator_mode=args.coordinator_mode,
            runtime_agent=args.runtime_agent,
            case_ids=args.cases,
        )
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        return 1 if args.fail_on_error and report["summary"]["failed"] else 0
    return 2


def main() -> None:
    raise SystemExit(run_active_smoke_cli())


if __name__ == "__main__":
    main()
