from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowTemplate:
    workflow_id: str
    title: str
    trigger_terms: tuple[str, ...]
    required_tools: tuple[str, ...]
    description: str
    required_params: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_TEMPLATES: tuple[WorkflowTemplate, ...] = (
    WorkflowTemplate(
        "upload_vector_profile",
        "上传矢量数据识别",
        ("上传矢量", "边界", "shp", "geojson", "字段", "坐标系"),
        ("describe_dataset",),
        "识别矢量字段、CRS、范围、几何类型和要素数量。",
    ),
    WorkflowTemplate(
        "upload_raster_profile",
        "上传栅格数据识别",
        ("上传栅格", "tif", "dem", "分辨率", "nodata", "crs"),
        ("describe_dataset", "raster_basic_stats"),
        "识别栅格分辨率、范围、NoData、CRS 和基础统计。",
    ),
    WorkflowTemplate(
        "vector_clip_vector",
        "矢量裁剪矢量",
        ("矢量裁剪", "裁剪矢量", "clip vector", "clip", "study area", "裁剪"),
        ("vector_clip_by_vector",),
        "使用面边界裁剪矢量数据并注册结果。",
    ),
    WorkflowTemplate(
        "vector_clip_raster",
        "矢量裁剪栅格",
        ("裁剪栅格", "矢量裁剪栅格", "clip raster"),
        ("clip_raster_by_vector",),
        "使用矢量边界裁剪栅格并生成 map-ready 输出。",
    ),
    WorkflowTemplate(
        "table_to_points",
        "表格转点数据",
        ("表格转点", "经纬度", "坐标字段", "points"),
        ("detect_coordinate_fields", "table_to_points"),
        "识别坐标字段并生成点图层。",
    ),
    WorkflowTemplate(
        "raster_statistics",
        "栅格统计",
        ("栅格统计", "分区统计", "zonal"),
        ("raster_basic_stats", "raster_zonal_stats"),
        "执行基础栅格统计或矢量分区统计。",
    ),
    WorkflowTemplate(
        "map_export",
        "制图并导出图片",
        ("制图", "出图", "地图", "png"),
        ("plot_dataset",),
        "生成可下载地图图片 artifact。",
    ),
    WorkflowTemplate(
        "processing_report",
        "生成处理报告",
        ("报告", "总结", "处理报告"),
        ("generate_stage_report",),
        "汇总处理过程、输出和下一步建议。",
    ),
)


@dataclass(frozen=True)
class ExecutableWorkflow:
    workflow_id: str
    title: str
    status: str
    workflow_plan: list[dict[str, Any]] = field(default_factory=list)
    required_params: list[str] = field(default_factory=list)
    missing_params: list[str] = field(default_factory=list)
    frontend_payload: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_workflow_templates() -> list[dict[str, Any]]:
    return [item.to_dict() for item in _TEMPLATES]


def match_workflow_template(prompt: str) -> dict[str, Any] | None:
    text = str(prompt or "").lower()
    best: tuple[int, int, WorkflowTemplate] | None = None
    for template in _TEMPLATES:
        hits = [term for term in template.trigger_terms if term.lower() in text]
        if not hits:
            continue
        score = (len(hits), max(len(term) for term in hits), template)
        if best is None or score[:2] > best[:2]:
            best = score
    return best[2].to_dict() if best else None


def _template(workflow_id: str) -> WorkflowTemplate | None:
    return next((item for item in _TEMPLATES if item.workflow_id == workflow_id), None)


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    return params if isinstance(params, dict) else {}


def _missing(params: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [key for key in required if params.get(key) in (None, "")]


def _step(step_id: str, tool_name: str, args: dict[str, Any], *, depends_on: list[str] | None = None, expected_outputs: list[str] | None = None) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "tool_name": tool_name,
        "step_type": "tool",
        "validated_tool_args": args,
        "depends_on": depends_on or [],
        "expected_outputs": expected_outputs or [],
        "stop_on_failure": True,
    }


def _frontend_payload(workflow_id: str, params: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "display": "workflow",
        "refresh": ["artifacts", "map_layers", "workspace"],
        "primary_dataset": params.get("dataset_name") or params.get("raster_name") or params.get("vector_name") or "",
        "expected_tools": [step["tool_name"] for step in steps],
    }


def _workflow_missing_result(template: WorkflowTemplate, params: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    return ExecutableWorkflow(
        workflow_id=template.workflow_id,
        title=template.title,
        status="needs_params",
        required_params=list(template.required_params),
        missing_params=missing,
        frontend_payload={"workflow_id": template.workflow_id, "display": "form", "missing_params": missing},
        error={
            "error_code": "WORKFLOW_PARAMS_REQUIRED",
            "message": "Workflow parameters are incomplete.",
            "suggestion": f"Provide: {', '.join(missing)}",
            "failed_step": "parameter_validation",
        },
    ).to_dict()


def build_executable_workflow(workflow_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    template = _template(workflow_id)
    if template is None:
        return {
            "workflow_id": workflow_id,
            "title": "",
            "status": "unsupported",
            "workflow_plan": [],
            "required_params": [],
            "missing_params": [],
            "frontend_payload": {"workflow_id": workflow_id, "display": "error"},
            "error": {
                "error_code": "WORKFLOW_NOT_FOUND",
                "message": f"Unknown workflow: {workflow_id}",
                "suggestion": "Use list_workflow_templates() to choose a supported workflow.",
                "failed_step": "workflow_lookup",
            },
        }

    payload = _clean_params(params)
    required: dict[str, tuple[str, ...]] = {
        "upload_vector_profile": ("dataset_name",),
        "upload_raster_profile": ("dataset_name",),
        "vector_clip_vector": ("dataset_name", "clip_name", "output_name"),
        "vector_clip_raster": ("raster_name", "vector_name", "output_name"),
        "table_to_points": ("dataset_name", "x_col", "y_col", "crs", "output_name"),
        "raster_statistics": ("raster_name",),
        "map_export": ("dataset_name", "output_name"),
        "processing_report": ("report_title",),
    }
    required_params = required.get(workflow_id, ())
    missing = _missing(payload, required_params)
    if missing:
        template_with_params = WorkflowTemplate(
            template.workflow_id,
            template.title,
            template.trigger_terms,
            template.required_tools,
            template.description,
            required_params,
        )
        return _workflow_missing_result(template_with_params, payload, missing)

    if workflow_id == "upload_vector_profile":
        steps = [
            _step("describe", "describe_dataset", {"dataset_name": payload["dataset_name"]}, expected_outputs=["dataset_summary"]),
        ]
    elif workflow_id == "upload_raster_profile":
        steps = [
            _step("describe", "describe_dataset", {"dataset_name": payload["dataset_name"]}, expected_outputs=["dataset_summary"]),
            _step("stats", "raster_basic_stats", {"raster_name": payload["dataset_name"], "output_name": payload.get("output_name", "")}, depends_on=["describe"], expected_outputs=["raster_statistics"]),
        ]
    elif workflow_id == "vector_clip_vector":
        steps = [
            _step("describe", "describe_dataset", {"dataset_name": payload["dataset_name"]}, expected_outputs=["dataset_summary"]),
            _step("clip", "vector_clip_by_vector", {"dataset_name": payload["dataset_name"], "clip_name": payload["clip_name"], "output_name": payload["output_name"]}, depends_on=["describe"], expected_outputs=["artifact", "map_layer"]),
        ]
    elif workflow_id == "vector_clip_raster":
        steps = [
            _step("describe", "describe_dataset", {"dataset_name": payload["raster_name"]}, expected_outputs=["dataset_summary"]),
            _step("clip", "clip_raster_by_vector", {"raster_name": payload["raster_name"], "vector_name": payload["vector_name"], "output_name": payload["output_name"]}, depends_on=["describe"], expected_outputs=["artifact", "map_layer"]),
        ]
    elif workflow_id == "table_to_points":
        steps = [
            _step("describe", "describe_dataset", {"dataset_name": payload["dataset_name"]}, expected_outputs=["dataset_summary"]),
            _step("points", "table_to_points", {"dataset_name": payload["dataset_name"], "x_col": payload["x_col"], "y_col": payload["y_col"], "crs": payload["crs"], "output_name": payload["output_name"]}, depends_on=["describe"], expected_outputs=["artifact", "map_layer"]),
        ]
    elif workflow_id == "raster_statistics":
        steps = [
            _step("stats", "raster_basic_stats", {"raster_name": payload["raster_name"], "output_name": payload.get("output_name", "")}, expected_outputs=["raster_statistics"]),
        ]
    elif workflow_id == "map_export":
        steps = [
            _step("map", "plot_dataset", {"dataset_name": payload["dataset_name"], "column": payload.get("column", ""), "output_name": payload["output_name"]}, expected_outputs=["map_artifact"]),
        ]
    elif workflow_id == "processing_report":
        steps = [
            _step("report", "generate_stage_report", {"report_title": payload["report_title"], "output_name": payload.get("output_name", "")}, expected_outputs=["report_artifact"]),
        ]
    else:
        steps = []
    return ExecutableWorkflow(
        workflow_id=template.workflow_id,
        title=template.title,
        status="ready",
        workflow_plan=steps,
        required_params=list(required_params),
        missing_params=[],
        frontend_payload=_frontend_payload(workflow_id, payload, steps),
        error=None,
    ).to_dict()
