from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.area_resolver import area_by_asset_id
from core.product_catalog import product_by_id


SourceAttribution = Literal["current_upload", "user_selected_default_library", "explicit_history_reference", "system_default"]
SOURCE_ATTRIBUTION_VALUES = {"current_upload", "user_selected_default_library", "explicit_history_reference", "system_default"}


class LLMInputAsset(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    name: str
    source: SourceAttribution


class LLMWorkflowStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    step_id: str = ""
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    stop_on_failure: bool = True


class LLMTaskPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    primary_goal: str
    intent: str
    operation: str
    input_assets: list[LLMInputAsset] = Field(default_factory=list)
    asset_roles: dict[str, str] = Field(default_factory=dict)
    requested_downloads: list[dict[str, Any]] = Field(default_factory=list)
    download_requests: list[dict[str, Any]] = Field(default_factory=list)
    study_area: str | dict[str, Any] = ""
    time_range: dict[str, Any] = Field(default_factory=dict)
    spatial_resolution: str | dict[str, Any] = ""
    candidate_tools: list[str] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    workflow_steps: list[LLMWorkflowStep] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    execution_required: bool = True
    response_mode: str = ""
    clarification_question: str = ""
    confidence: float = 0.0
    source_attribution: dict[str, SourceAttribution] = Field(default_factory=dict)
    explicit_history_references: list[str] = Field(default_factory=list)
    response_language: str = ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in items if str(item or "").strip()]


def _available_dataset_names_for_normalization(context: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    active = _as_dict(context.get("active_dataset"))
    if active.get("name"):
        names.add(str(active["name"]))
    for item in _as_list(context.get("available_datasets")):
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    return names


def _normalize_source_value(value: Any, fallback: str = "system_default") -> str:
    source = str(value or "").strip()
    return source if source in SOURCE_ATTRIBUTION_VALUES else fallback


def _source_for_name(name: str, raw_source_attribution: Any, available_dataset_names: set[str]) -> str:
    if isinstance(raw_source_attribution, dict):
        source = raw_source_attribution.get(name)
        if source:
            return _normalize_source_value(source, "system_default")
    if isinstance(raw_source_attribution, list) and len(raw_source_attribution) == 1:
        return _normalize_source_value(raw_source_attribution[0], "current_upload" if name in available_dataset_names else "system_default")
    if name in available_dataset_names:
        return "current_upload"
    return "system_default"


def _normalize_phase2_payload(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Repair JSON-mode type drift without inventing tools, fields, or products."""
    normalized = dict(data)
    context_intent = str(_as_dict(context.get("intent")).get("intent") or "").strip()
    if not str(normalized.get("primary_goal") or "").strip():
        normalized["primary_goal"] = str(normalized.get("goal") or normalized.get("task_type") or normalized.get("operation") or context_intent or "GIS task")
    if not str(normalized.get("intent") or "").strip():
        normalized["intent"] = str(normalized.get("task_type") or context_intent or normalized.get("operation") or "data_processing")
    if not str(normalized.get("operation") or "").strip():
        normalized["operation"] = str(normalized.get("task_type") or normalized.get("intent") or context_intent or "data_processing")
    available_dataset_names = _available_dataset_names_for_normalization(context)
    asset_roles = _as_dict(normalized.get("asset_roles"))
    raw_source_attribution = normalized.get("source_attribution")

    input_assets: list[dict[str, Any]] = []
    for item in _coerce_list(normalized.get("input_assets")):
        if isinstance(item, dict):
            asset = dict(item)
            name = str(asset.get("name") or asset.get("dataset_name") or "").strip()
            if not name:
                continue
            asset["name"] = name
            asset["role"] = str(asset.get("role") or asset_roles.get(name) or "input_asset")
            asset["source"] = _normalize_source_value(asset.get("source"), _source_for_name(name, raw_source_attribution, available_dataset_names))
            input_assets.append(asset)
        else:
            name = str(item or "").strip()
            if not name:
                continue
            input_assets.append(
                {
                    "role": str(asset_roles.get(name) or "input_asset"),
                    "name": name,
                    "source": _source_for_name(name, raw_source_attribution, available_dataset_names),
                }
            )
    normalized["input_assets"] = input_assets

    normalized["requested_downloads"] = _as_list(normalized.get("requested_downloads"))
    normalized["download_requests"] = _as_list(normalized.get("download_requests"))
    normalized["time_range"] = _as_dict(normalized.get("time_range"))
    if normalized.get("study_area") is None:
        normalized["study_area"] = ""
    if normalized.get("spatial_resolution") is None:
        normalized["spatial_resolution"] = ""
    normalized["candidate_tools"] = _coerce_string_list(normalized.get("candidate_tools"))
    normalized["selected_tools"] = _coerce_string_list(normalized.get("selected_tools"))
    normalized["expected_outputs"] = _coerce_string_list(normalized.get("expected_outputs"))
    normalized["explicit_history_references"] = _coerce_string_list(normalized.get("explicit_history_references"))
    normalized["response_mode"] = "" if normalized.get("response_mode") is None else str(normalized.get("response_mode") or "")
    normalized["clarification_question"] = "" if normalized.get("clarification_question") is None else str(normalized.get("clarification_question") or "")
    try:
        normalized["confidence"] = float(normalized.get("confidence") or 0.0)
    except Exception:
        normalized["confidence"] = 0.0

    steps: list[dict[str, Any]] = []
    for index, item in enumerate(_coerce_list(normalized.get("workflow_steps"))):
        if not isinstance(item, dict):
            continue
        step = dict(item)
        step["step_id"] = str(step.get("step_id") or f"step_{index + 1}")
        step["tool_name"] = str(step.get("tool_name") or "")
        step["args"] = _as_dict(step.get("args"))
        step["depends_on"] = _coerce_string_list(step.get("depends_on"))
        step["expected_outputs"] = _coerce_string_list(step.get("expected_outputs"))
        steps.append(step)
    normalized["workflow_steps"] = steps

    source_attribution: dict[str, str] = {}
    if isinstance(raw_source_attribution, dict):
        for key, value in raw_source_attribution.items():
            source_attribution[str(key)] = _normalize_source_value(value, "system_default")
    elif isinstance(raw_source_attribution, list) and len(raw_source_attribution) == 1:
        source = _normalize_source_value(raw_source_attribution[0], "current_upload")
        for key in [*(asset.get("name") for asset in input_assets), *asset_roles.keys()]:
            if str(key or "").strip():
                source_attribution[str(key)] = source
    for asset in input_assets:
        name = str(asset.get("name") or "")
        if name:
            source_attribution.setdefault(name, str(asset.get("source") or "system_default"))
    normalized["source_attribution"] = source_attribution
    return normalized


def _error(code: str, message: str, **detail: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **detail}


def _is_phase2_payload(data: dict[str, Any]) -> bool:
    return any(key in data for key in ("primary_goal", "operation", "input_assets", "workflow_steps", "selected_tools", "execution_required", "response_mode"))


def _is_answer_only_plan(model: LLMTaskPlan) -> bool:
    intent = str(model.intent or "").strip()
    response_mode = str(model.response_mode or "").strip()
    return (
        model.execution_required is False
        or response_mode == "answer_only"
        or intent in {"knowledge_qa", "capability_question", "usage_help", "result_explanation"}
    )


def _candidate_tools(context: dict[str, Any]) -> set[str]:
    tools: set[str] = set()
    for card in _as_list(context.get("candidate_tool_cards")):
        if isinstance(card, dict) and card.get("tool_name"):
            tools.add(str(card["tool_name"]))
    return tools


def _available_fields(context: dict[str, Any]) -> set[str]:
    fields = {str(field) for field in _as_list(context.get("available_fields")) if str(field or "").strip()}
    active = _as_dict(context.get("active_dataset"))
    profile = _as_dict(active.get("asset_profile"))
    fields.update(str(field) for field in _as_list(profile.get("fields")) if str(field or "").strip())
    return fields


def _download_candidate_product_keys(context: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in _as_list(context.get("download_candidates")):
        if isinstance(item, dict):
            key = str(item.get("product_id") or item.get("product_key") or "").strip()
            if key:
                keys.add(key)
            legacy = str(item.get("product_key") or "").strip()
            if legacy:
                keys.add(legacy)
    return keys


def _download_candidates_by_product_key(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for item in _as_list(context.get("download_candidates")):
        if not isinstance(item, dict):
            continue
        product_key = str(item.get("product_id") or item.get("product_key") or "").strip()
        if product_key:
            candidates[product_key] = item
        legacy = str(item.get("product_key") or "").strip()
        if legacy:
            candidates[legacy] = item
    return candidates


def _split_fields(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def _fields_referenced_by_args(args: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for key in ("target_col", "observed_col", "x_col", "y_col", "lon_col", "lat_col", "date_col", "group_col"):
        value = str(args.get(key) or "").strip()
        if value:
            fields.append(value)
    for key in ("feature_cols", "predicted_cols"):
        fields.extend(_split_fields(args.get(key)))
    return list(dict.fromkeys(fields))


def _product_keys_from_mapping(value: Any) -> list[str]:
    mapping = _as_dict(value)
    key = str(mapping.get("product_key") or "").strip()
    return [key] if key else []


def _product_keys_referenced_by_plan(data: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    keys.extend(_product_keys_from_mapping(data.get("download_plan")))
    for asset in _as_list(data.get("selected_assets")):
        keys.extend(_product_keys_from_mapping(asset))
    for step in _as_list(data.get("planned_steps")):
        if isinstance(step, dict):
            keys.extend(_product_keys_from_mapping(_as_dict(step.get("args"))))
    for request in _as_list(data.get("download_requests")) + _as_list(data.get("requested_downloads")):
        if isinstance(request, dict):
            key = str(request.get("product_id") or request.get("product_key") or "").strip()
            if key:
                keys.append(key)
    return list(dict.fromkeys(keys))


def _context_area_asset_ids(context: dict[str, Any]) -> set[str]:
    return {
        str(item.get("asset_id") or "")
        for item in _as_list(context.get("area_candidates"))
        if isinstance(item, dict) and str(item.get("asset_id") or "").strip()
    }


def _validate_download_requests(requests: list[Any], context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    product_keys = _download_candidate_product_keys(context)
    area_ids = _context_area_asset_ids(context)
    for index, raw in enumerate(requests):
        if not isinstance(raw, dict):
            errors.append(_error("DOWNLOAD_REQUEST_INVALID", "download_requests items must be objects.", index=index))
            continue
        req = dict(raw)
        product_id = str(req.get("product_id") or req.get("product_key") or "").strip()
        area_asset_id = str(req.get("area_asset_id") or "").strip()
        if not product_id:
            errors.append(_error("DOWNLOAD_PRODUCT_REQUIRED", "download request is missing product_id.", index=index))
            continue
        product = product_by_id(product_id)
        if not product or (product_keys and product_id not in product_keys):
            errors.append(_error("DOWNLOAD_PRODUCT_NOT_IN_CONTEXT", "Download product is not in Product Catalog candidates.", product_id=product_id, index=index))
            continue
        if not area_asset_id:
            errors.append(_error("DOWNLOAD_AREA_REQUIRED", "download request is missing area_asset_id.", product_id=product_id, index=index))
            continue
        if area_ids and area_asset_id not in area_ids:
            errors.append(_error("DOWNLOAD_AREA_NOT_IN_CONTEXT", "Download area was not resolved by AreaResolver.", area_asset_id=area_asset_id, product_id=product_id, index=index))
            continue
        if not area_by_asset_id(area_asset_id) and not area_ids:
            errors.append(_error("DOWNLOAD_AREA_NOT_FOUND", "Download area asset does not exist.", area_asset_id=area_asset_id, product_id=product_id, index=index))
            continue
        requested_resolution = str(req.get("requested_resolution") or "").strip()
        resolved_resolution = str(req.get("resolved_resolution") or requested_resolution or "").strip()
        supported = {str(item) for item in product.get("supported_resolutions", [])}
        if resolved_resolution and supported and resolved_resolution not in supported:
            errors.append(
                _error(
                    "DOWNLOAD_RESOLUTION_UNSUPPORTED",
                    "Requested resolution is not supported by the selected product.",
                    product_id=product_id,
                    requested_resolution=requested_resolution,
                    supported_resolutions=sorted(supported),
                    index=index,
                )
            )
            continue
        if not resolved_resolution and supported:
            req["resolved_resolution"] = sorted(supported)[0]
        else:
            req["resolved_resolution"] = resolved_resolution
        req["product_id"] = product_id
        req["product_key"] = product_id
        req["source_key"] = product.get("source", "")
        req["resource_type"] = product.get("resource_type", "")
        req["product_display_name_zh"] = product.get("display_name_zh", "")
        req["temporal_requirement"] = product.get("temporal_requirement", "")
        req["download_adapter"] = product.get("download_adapter", "")
        normalized.append(req)
    return normalized, errors


def _normalize_download_plan(
    raw_plan: Any,
    requested_product_keys: list[str],
    download_candidates_by_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selected = dict(_as_dict(raw_plan))
    if requested_product_keys and not str(selected.get("product_key") or "").strip():
        selected["product_key"] = requested_product_keys[0]

    product_key = str(selected.get("product_key") or "").strip()
    candidate = download_candidates_by_key.get(product_key)
    if not candidate:
        return selected

    metadata_keys = (
        "product_key",
        "source_key",
        "name",
        "resource_type",
        "confirmation_required",
        "license_note",
        "source",
    )
    normalized = {key: candidate[key] for key in metadata_keys if key in candidate}
    normalized.update(selected)
    normalized["product_key"] = product_key
    if "confirmation_required" in candidate:
        normalized["confirmation_required"] = bool(candidate.get("confirmation_required"))
    return normalized


def _fallback_plan(task_type: str, errors: list[dict[str, Any]], response_language: str = "en-US") -> dict[str, Any]:
    question = (
        "请先提供或确认缺失、无效或不可信的计划输入，然后才能执行工具。"
        if str(response_language).startswith("zh")
        else "Please provide or confirm the missing or untrusted LLM plan inputs before execution."
    )
    missing = sorted({str(error.get("field") or error.get("tool_name") or error.get("code") or "") for error in errors if error})
    return {
        "task_type": task_type or "unclear_request",
        "required_inputs": [],
        "missing_inputs": [item for item in missing if item],
        "recommended_tools": [],
        "tool_preconditions": {},
        "execution_steps": [],
        "expected_outputs": [],
        "should_ask_clarification": True,
        "clarification_question": question,
        "resolved_fields": {},
        "resolved_objects": {},
        "slots": {},
        "tool_plan": [],
        "validated_tool_args": {},
        "workflow_plan": [],
        "slot_validation_errors": errors,
        "semantic_parse": {},
        "download_plan": {},
        "requested_downloads": [],
        "download_requests": [],
        "response_language": response_language,
    }


def _validate_phase2_task_plan(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    data = _normalize_phase2_payload(data, context)
    response_language = str(data.get("response_language") or context.get("response_language") or "en-US")
    try:
        model = LLMTaskPlan.model_validate(data)
    except ValidationError as exc:
        errors = [
            _error(
                "TASK_PLAN_SCHEMA_INVALID",
                "LLM TaskPlan failed Pydantic validation.",
                field=".".join(str(part) for part in error.get("loc", [])),
                detail=str(error.get("msg") or ""),
            )
            for error in exc.errors()
        ]
        return {"ok": False, "errors": errors, "fallback_plan": _fallback_plan(str(data.get("intent") or "unclear_request"), errors, response_language)}

    errors: list[dict[str, Any]] = []
    candidate_tools = _candidate_tools(context)
    selected_tools = [item for item in dict.fromkeys(str(tool).strip() for tool in model.selected_tools if str(tool).strip())]
    workflow_steps: list[dict[str, Any]] = []
    tool_plan: list[dict[str, Any]] = []
    validated_args: dict[str, dict[str, Any]] = {}

    if _is_answer_only_plan(model):
        if selected_tools or model.workflow_steps:
            errors.append(
                _error(
                    "ANSWER_ONLY_PLAN_HAS_TOOLS",
                    "Answer-only TaskPlan must not select tools or workflow steps.",
                    tools=selected_tools,
                )
            )
        raw = model.model_dump(mode="json")
        expected_outputs = list(model.expected_outputs) or ["chat_answer"]
        if errors:
            return {"ok": False, "errors": errors, "fallback_plan": _fallback_plan(model.intent, errors, response_language)}
        plan = {
            "task_type": model.intent,
            "primary_goal": model.primary_goal,
            "operation": model.operation or "answer_question",
            "execution_required": False,
            "response_mode": "answer_only",
            "required_inputs": [],
            "missing_inputs": [],
            "recommended_tools": [],
            "candidate_tools": [],
            "selected_tools": [],
            "tool_preconditions": {},
            "execution_steps": [],
            "expected_outputs": expected_outputs,
            "should_ask_clarification": bool(str(model.clarification_question or "").strip()),
            "clarification_question": str(model.clarification_question or ""),
            "resolved_fields": {},
            "resolved_objects": {"selected_assets": []},
            "input_assets": [],
            "asset_roles": {},
            "slots": {"goal": model.primary_goal, "confidence": float(model.confidence)},
            "tool_plan": [],
            "validated_tool_args": {},
            "workflow_plan": [],
            "slot_validation_errors": [],
            "semantic_parse": {"intent": model.intent, "operation": model.operation or "answer_question"},
            "download_plan": {"requested_downloads": []},
            "requested_downloads": [],
            "download_requests": [],
            "study_area": raw.get("study_area"),
            "time_range": raw.get("time_range", {}),
            "spatial_resolution": raw.get("spatial_resolution"),
            "requires_confirmation": False,
            "confidence": float(model.confidence),
            "source_attribution": raw.get("source_attribution", {}),
            "explicit_history_references": raw.get("explicit_history_references", []),
            "response_language": response_language,
            "forbidden_tools": [],
            "llm_explanation": str(data.get("explanation") or ""),
            "llm_task_plan": {
                **raw,
                "execution_required": False,
                "response_mode": "answer_only",
                "candidate_tools": [],
                "selected_tools": [],
                "workflow_steps": [],
                "expected_outputs": expected_outputs,
                "download_requests": [],
                "requested_downloads": [],
            },
        }
        return {"ok": True, "errors": [], "plan": plan}

    for tool_name in selected_tools:
        if candidate_tools and tool_name not in candidate_tools:
            errors.append(_error("TOOL_NOT_IN_CANDIDATE_CARDS", "Selected tool was not among retrieved candidate Tool Cards.", tool_name=tool_name))

    for index, step in enumerate(model.workflow_steps):
        tool_name = str(step.tool_name or "").strip()
        if not tool_name:
            errors.append(_error("TOOL_NAME_MISSING", "Workflow step is missing tool_name."))
            continue
        if candidate_tools and tool_name not in candidate_tools:
            errors.append(_error("TOOL_NOT_IN_CANDIDATE_CARDS", "Workflow tool was not among retrieved candidate Tool Cards.", tool_name=tool_name))
        if selected_tools and tool_name not in selected_tools:
            errors.append(_error("WORKFLOW_TOOL_NOT_SELECTED", "Workflow step uses a tool not present in selected_tools.", tool_name=tool_name))
        step_id = str(step.step_id or f"step_{index + 1}")
        args = dict(step.args)
        workflow_steps.append(
            {
                "step_id": step_id,
                "tool_name": tool_name,
                "validated_tool_args": args,
                "depends_on": list(step.depends_on),
                "expected_outputs": list(step.expected_outputs),
                "stop_on_failure": bool(step.stop_on_failure),
            }
        )
        tool_plan.append({"tool_name": tool_name, "args": args})
        validated_args[tool_name] = args

    if errors:
        return {"ok": False, "errors": errors, "fallback_plan": _fallback_plan(model.intent, errors, response_language)}

    raw = model.model_dump(mode="json")
    raw_download_requests = raw.get("download_requests") or raw.get("requested_downloads") or []
    strict_download_requests = any(
        isinstance(item, dict) and (item.get("product_id") or item.get("area_asset_id"))
        for item in _as_list(raw_download_requests)
    )
    download_requests, download_errors = _validate_download_requests(_as_list(raw_download_requests), context)
    if strict_download_requests:
        errors.extend(download_errors)
    else:
        download_requests = _as_list(raw_download_requests)
    if errors:
        return {"ok": False, "errors": errors, "fallback_plan": _fallback_plan(model.intent, errors, response_language)}
    plan = {
        "task_type": model.intent,
        "primary_goal": model.primary_goal,
        "operation": model.operation,
        "required_inputs": [],
        "missing_inputs": [],
        "recommended_tools": selected_tools,
        "candidate_tools": list(model.candidate_tools),
        "selected_tools": selected_tools,
        "tool_preconditions": {},
        "execution_steps": [step["step_id"] for step in workflow_steps],
        "expected_outputs": list(model.expected_outputs),
        "should_ask_clarification": bool(str(model.clarification_question or "").strip()),
        "clarification_question": str(model.clarification_question or ""),
        "resolved_fields": {},
        "resolved_objects": {"selected_assets": raw.get("input_assets", [])},
        "input_assets": raw.get("input_assets", []),
        "asset_roles": dict(model.asset_roles),
        "slots": {"goal": model.primary_goal, "confidence": float(model.confidence)},
        "tool_plan": tool_plan,
        "validated_tool_args": validated_args,
        "workflow_plan": workflow_steps,
        "slot_validation_errors": [],
        "semantic_parse": {"intent": model.intent, "operation": model.operation},
        "confirmation_id": raw.get("confirmation_id"),
        "download_plan": {"requested_downloads": download_requests},
        "requested_downloads": download_requests,
        "download_requests": download_requests,
        "study_area": raw.get("study_area"),
        "time_range": raw.get("time_range", {}),
        "spatial_resolution": raw.get("spatial_resolution"),
        "requires_confirmation": bool(model.requires_confirmation),
        "confidence": float(model.confidence),
        "source_attribution": raw.get("source_attribution", {}),
        "explicit_history_references": raw.get("explicit_history_references", []),
        "response_language": response_language,
        "forbidden_tools": [],
        "llm_explanation": str(data.get("explanation") or ""),
        "llm_task_plan": {**raw, "download_requests": download_requests, "requested_downloads": download_requests},
    }
    return {"ok": True, "errors": [], "plan": plan}


def validate_llm_task_plan(payload: Any, context: dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(payload)
    response_language = str(data.get("response_language") or context.get("response_language") or "en-US")
    if _is_phase2_payload(data):
        return _validate_phase2_task_plan(data, context)

    errors: list[dict[str, Any]] = []
    task_type = str(data.get("task_type") or _as_dict(context.get("intent")).get("intent") or "unclear_request")
    candidate_tools_for_repair = _candidate_tools(context)
    planned_tools_for_repair = [
        str(step.get("tool_name") or "").strip()
        for step in _as_list(data.get("planned_steps"))
        if isinstance(step, dict) and str(step.get("tool_name") or "").strip()
    ]
    if (
        "tools_read" not in data
        and candidate_tools_for_repair
        and planned_tools_for_repair
        and all(tool_name in candidate_tools_for_repair for tool_name in planned_tools_for_repair)
    ):
        data = {**data, "tools_read": list(dict.fromkeys(planned_tools_for_repair))}

    for key in ("goal", "selected_assets", "tools_read", "planned_steps", "requires_confirmation", "expected_outputs"):
        if key not in data:
            errors.append(_error("TASK_PLAN_FIELD_MISSING", f"Missing TaskPlan field: {key}", field=key))

    tools_read = {str(item) for item in _as_list(data.get("tools_read")) if str(item or "").strip()}
    candidate_tools = _candidate_tools(context)
    available_fields = _available_fields(context)
    candidate_product_keys = _download_candidate_product_keys(context)
    download_candidates_by_key = _download_candidates_by_product_key(context)
    requested_product_keys = _product_keys_referenced_by_plan(data)
    steps: list[dict[str, Any]] = []
    validated_args: dict[str, dict[str, Any]] = {}

    for raw_step in _as_list(data.get("planned_steps")):
        if not isinstance(raw_step, dict):
            errors.append(_error("STEP_INVALID", "Each planned step must be an object."))
            continue
        tool_name = str(raw_step.get("tool_name") or "").strip()
        args = _as_dict(raw_step.get("args"))
        if not tool_name:
            errors.append(_error("TOOL_NAME_MISSING", "Planned step is missing tool_name."))
            continue
        if candidate_tools and tool_name not in candidate_tools:
            errors.append(_error("TOOL_NOT_IN_CANDIDATE_CARDS", "Tool was not among retrieved candidate Tool Cards.", tool_name=tool_name))
        if tool_name not in tools_read:
            errors.append(_error("TOOL_CARD_NOT_READ", "LLM selected a tool without listing it in tools_read.", tool_name=tool_name))
        for field in _fields_referenced_by_args(args):
            if available_fields and field not in available_fields:
                errors.append(_error("FIELD_NOT_IN_CONTEXT", "LLM referenced a field not present in context metadata.", field=field, tool_name=tool_name))
        steps.append({"tool_name": tool_name, "args": args})
        validated_args[tool_name] = args

    for product_key in requested_product_keys:
        if candidate_product_keys and product_key not in candidate_product_keys:
            errors.append(
                _error(
                    "DOWNLOAD_PRODUCT_NOT_IN_CONTEXT",
                    "LLM referenced a download product that was not present in context download_candidates.",
                    product_key=product_key,
                )
            )

    for product_key in requested_product_keys:
        candidate = download_candidates_by_key.get(product_key)
        if candidate and candidate.get("confirmation_required") is True and not bool(data.get("requires_confirmation")):
            errors.append(
                _error(
                    "DOWNLOAD_PRODUCT_REQUIRES_CONFIRMATION",
                    "LLM referenced a download product that requires confirmation but did not mark requires_confirmation.",
                    product_key=product_key,
                )
            )

    if errors:
        return {
            "ok": False,
            "errors": errors,
            "fallback_plan": _fallback_plan(task_type, errors, response_language),
        }

    selected_download_plan = _normalize_download_plan(data.get("download_plan"), requested_product_keys, download_candidates_by_key)
    raw_requests = _as_list(data.get("download_requests")) or _as_list(data.get("requested_downloads"))
    strict_download_requests = any(isinstance(item, dict) and (item.get("product_id") or item.get("area_asset_id")) for item in raw_requests)
    download_requests, download_errors = _validate_download_requests(raw_requests, context)
    if strict_download_requests and download_errors:
        return {"ok": False, "errors": download_errors, "fallback_plan": _fallback_plan(task_type, download_errors, response_language)}
    if not strict_download_requests:
        download_requests = raw_requests

    plan = {
        "task_type": task_type,
        "required_inputs": [],
        "missing_inputs": [],
        "recommended_tools": list(dict.fromkeys([step["tool_name"] for step in steps])),
        "tool_preconditions": {},
        "execution_steps": [str(step.get("step_id") or step.get("tool_name") or "") for step in _as_list(data.get("planned_steps"))],
        "expected_outputs": [str(item) for item in _as_list(data.get("expected_outputs")) if str(item or "").strip()],
        "should_ask_clarification": bool(str(data.get("clarification_question") or "").strip()),
        "clarification_question": str(data.get("clarification_question") or ""),
        "resolved_fields": {},
        "resolved_objects": {"selected_assets": _as_list(data.get("selected_assets"))},
        "slots": {"goal": str(data.get("goal") or ""), "assumptions": _as_list(data.get("assumptions"))},
        "tool_plan": steps,
        "validated_tool_args": validated_args,
        "workflow_plan": [],
        "slot_validation_errors": [],
        "semantic_parse": {},
        "download_plan": selected_download_plan,
        "requested_downloads": download_requests or _as_list(selected_download_plan.get("requested_downloads")),
        "download_requests": download_requests or _as_list(selected_download_plan.get("requested_downloads")),
        "requires_confirmation": bool(data.get("requires_confirmation")),
        "forbidden_tools": [str(item) for item in _as_list(data.get("forbidden_tools")) if str(item or "").strip()],
        "llm_explanation": str(data.get("explanation") or ""),
        "response_language": response_language,
    }
    return {"ok": True, "errors": [], "plan": plan}
