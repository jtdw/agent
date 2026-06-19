from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PRIVATE_KEYS = {
    "path",
    "absolute_path",
    "relative_path",
    "display_path",
    "owner_user_id",
    "session_id",
    "user_id",
    "account_id",
    "status_path",
    "log_path",
    "storage_state_path",
    "cookie",
    "cookies",
    "token",
    "password",
}
RAW_DEBUG_KEYS = {
    "inputs",
    "input",
    "outputs",
    "output",
    "diagnostics",
    "raw_workflow_result",
    "workflow_execution",
    "tool_execution",
    "coordinator_execution",
    "execution_trace",
    "validated_tool_args",
    "plan",
}
MOJIBAKE_MARKERS = ("�", "锟斤拷", "Ã", "å", "æ", "ä")
WORKSPACE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s`'\"，。；;]+|workspace[\\/](?:users|sessions)[^\s`'\"，。；;]*)",
    re.IGNORECASE,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _redact_text(value: str, warnings: list[str]) -> str:
    text = str(value or "")
    if WORKSPACE_PATH_RE.search(text):
        warnings.append("已隐藏内部 workspace 路径。")
        text = WORKSPACE_PATH_RE.sub("[已隐藏内部路径]", text)
    if any(marker in text for marker in MOJIBAKE_MARKERS):
        warnings.append("检测到疑似乱码，已建议进行编码复核。")
    return text


def _safe_filename_from_item(item: dict[str, Any]) -> str:
    for key in ("filename", "name", "title"):
        value = str(item.get(key) or "").strip()
        if value and not any(sep in value for sep in ("\\", "/")):
            return value
    raw = str(item.get("path") or item.get("absolute_path") or item.get("relative_path") or "")
    return Path(raw).name if raw else "result"


def _artifact_status(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "")
    raw_path = str(item.get("path") or item.get("absolute_path") or "")
    if raw_path and not Path(raw_path).exists():
        return "missing"
    return status or "available"


def _sanitize(value: Any, warnings: list[str], *, inside_user_facing: bool = False) -> Any:
    if isinstance(value, str):
        return _redact_text(value, warnings)
    if isinstance(value, list):
        return [_sanitize(item, warnings, inside_user_facing=inside_user_facing) for item in value]
    if not isinstance(value, dict):
        return value

    output: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if key_text == "normalized_results" and isinstance(item, list):
            output[key_text] = [
                _sanitize_normalized_result(entry, warnings) if isinstance(entry, dict) else entry
                for entry in item
            ]
            continue
        if key_text in PRIVATE_KEYS:
            continue
        if key_text in RAW_DEBUG_KEYS and not inside_user_facing:
            continue
        next_inside = inside_user_facing or key_text in {"user_facing_result", "technical_details", "debug"}
        if next_inside and key_text in PRIVATE_KEYS:
            continue
        output[key_text] = _sanitize(item, warnings, inside_user_facing=next_inside)
    return output


def _sanitize_artifact(item: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    artifact = dict(item)
    filename = _safe_filename_from_item(artifact)
    status = _artifact_status(artifact)
    cleaned = _sanitize(artifact, warnings, inside_user_facing=True)
    if isinstance(cleaned, dict):
        cleaned["filename"] = filename
        cleaned.setdefault("name", filename)
        cleaned["status"] = status
        cleaned.pop("owner_user_id", None)
        cleaned.pop("session_id", None)
        return cleaned
    return {"filename": filename, "name": filename, "status": status}


def _sanitize_normalized_result(item: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    allowed = {
        "status",
        "errors",
        "warnings",
        "artifacts",
        "map_layers",
        "tables",
        "images",
        "outputs",
        "diagnostics",
        "next_actions",
        "step_id",
        "tool_name",
        "input_asset_ids",
    }
    payload = {key: value for key, value in item.items() if key in allowed}
    cleaned = _sanitize(payload, warnings, inside_user_facing=True)
    return cleaned if isinstance(cleaned, dict) else {}


def _sanitize_normalized_results(container: dict[str, Any], warnings: list[str]) -> None:
    if isinstance(container.get("normalized_results"), list):
        container["normalized_results"] = [
            _sanitize_normalized_result(item, warnings) if isinstance(item, dict) else item
            for item in container["normalized_results"]
        ]


def _sanitize_artifact_lists(container: dict[str, Any], warnings: list[str]) -> None:
    for key in ("artifacts", "files", "primary_artifacts", "secondary_artifacts", "preview_artifacts"):
        if isinstance(container.get(key), list):
            container[key] = [_sanitize_artifact(item, warnings) if isinstance(item, dict) else item for item in container[key]]
    if isinstance(container.get("grouped_artifacts"), list):
        groups = []
        for group in container["grouped_artifacts"]:
            if not isinstance(group, dict):
                groups.append(group)
                continue
            patched = dict(group)
            if isinstance(patched.get("artifacts"), list):
                patched["artifacts"] = [_sanitize_artifact(item, warnings) if isinstance(item, dict) else item for item in patched["artifacts"]]
            groups.append(patched)
        container["grouped_artifacts"] = groups
    bundle = container.get("download_bundle")
    if isinstance(bundle, dict):
        container["download_bundle"] = {
            key: _sanitize_artifact(item, warnings) if isinstance(item, dict) else item
            for key, item in bundle.items()
        }


def validate_tool_response(result: dict[str, Any]) -> dict[str, Any]:
    patched = dict(result or {})
    warnings = [str(item) for item in _as_list(patched.get("warnings")) if str(item).strip()]
    if patched.get("ok") and not _as_list(patched.get("artifacts")):
        warnings.append("工具执行成功，但没有注册可下载 artifact。")
    if not patched.get("ok"):
        summary = str(patched.get("summary") or "")
        if "成功" in summary or "已完成" in summary:
            patched["summary"] = str(patched.get("user_message") or patched.get("error_title") or "工具执行失败。")
    patched["warnings"] = list(dict.fromkeys(warnings))
    return patched


def validate_workflow_result(result: dict[str, Any]) -> dict[str, Any]:
    patched = dict(result or {})
    warnings = [str(item) for item in _as_list(patched.get("warnings")) if str(item).strip()]
    if patched.get("ok") and not _as_list(patched.get("final_artifacts")):
        warnings.append("工作流执行成功，但没有最终 artifact。")
    if not patched.get("ok"):
        summary = str(patched.get("final_summary") or "")
        if "成功" in summary or "已完成" in summary:
            patched["final_summary"] = "工作流执行失败。"
    if warnings:
        diagnostics = dict(_as_dict(patched.get("diagnostics")))
        diagnostics["quality_warnings"] = list(dict.fromkeys(warnings))
        patched["diagnostics"] = diagnostics
    return patched


def validate_response_before_send(response: dict[str, Any], *, user_id: str = "", session_id: str = "") -> dict[str, Any]:
    del user_id, session_id
    warnings: list[str] = []
    cleaned = _sanitize(dict(response or {}), warnings)
    if not isinstance(cleaned, dict):
        return {}

    _sanitize_artifact_lists(cleaned, warnings)
    _sanitize_normalized_results(cleaned, warnings)
    user_result = cleaned.get("user_facing_result")
    if isinstance(user_result, dict):
        _sanitize_artifact_lists(user_result, warnings)
        existing = [str(item) for item in _as_list(user_result.get("quality_warnings")) if str(item).strip()]
        merged = list(dict.fromkeys([*existing, *warnings]))
        if merged:
            user_result["quality_warnings"] = merged
        cleaned["user_facing_result"] = user_result

    messages = []
    for message in _as_list(cleaned.get("messages")):
        if not isinstance(message, dict):
            messages.append(message)
            continue
        patched = dict(message)
        if isinstance(patched.get("content"), str):
            patched["content"] = _redact_text(str(patched["content"]), warnings)
        meta = _as_dict(patched.get("meta"))
        if meta:
            _sanitize_artifact_lists(meta, warnings)
            _sanitize_normalized_results(meta, warnings)
            if isinstance(meta.get("user_facing_result"), dict):
                _sanitize_artifact_lists(meta["user_facing_result"], warnings)
            patched["meta"] = _sanitize(meta, warnings)
        messages.append(patched)
    if messages:
        cleaned["messages"] = messages

    return cleaned
