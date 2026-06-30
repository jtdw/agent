from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from core.diagnostic_views import diagnostic_event_views
from core.management_views import download_job_to_management_view
from core.presentation_result import build_presentation_bundle
from core.response_language import detect_response_language
from core.tool_contracts import download_job_to_tool_result


def _safe_file_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _safe_log_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[A-Za-z]:[\\/][^\s'\"<>]+", "[internal_path]", text)
    text = re.sub(r"/(?:Users|home|var|tmp|etc|root)/[^\s'\"<>]+", "[internal_path]", text)
    for token in ("storage_state", "cookie", "token", "authorization", "Traceback"):
        text = re.sub(token, "[redacted]", text, flags=re.IGNORECASE)
    return text[:500]


def assert_download_job_session(job: dict[str, Any], session_id: str = "") -> None:
    requested = str(session_id or "").strip()
    if not requested:
        return
    actual = str(job.get("session_id") or "").strip()
    if not actual:
        return
    if actual != requested:
        raise PermissionError("download job belongs to another session")


def format_download_job_log_text(job: dict[str, Any], scene_jobs: list[dict[str, Any]], tile_jobs: list[dict[str, Any]], audit_events: list[dict[str, Any]]) -> str:
    lines = [
        f"Download job log: {job.get('job_id')}",
        f"status: {job.get('status')}",
        f"stage: {job.get('stage')}",
        f"progress: {job.get('progress')}%",
        f"source_key: {job.get('source_key')}",
        f"resource_type: {job.get('resource_type')}",
        f"region: {job.get('region')}",
        f"output_file: {_safe_file_label(job.get('output_path'))}",
        f"archive_file: {_safe_file_label(job.get('zip_path'))}",
        f"error_message: {_safe_log_text(job.get('error_message'))}",
        "",
        "Scene jobs:",
    ]
    if scene_jobs:
        for item in scene_jobs:
            lines.append(f"- {item.get('scene_job_id') or ''} state={item.get('state') or ''} message={_safe_log_text(item.get('message'))}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Tile jobs:")
    if tile_jobs:
        for item in tile_jobs:
            lines.append(f"- {item.get('tile_job_id') or ''} state={item.get('state') or ''} message={_safe_log_text(item.get('message'))}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Recent audit events:")
    if audit_events:
        for item in audit_events:
            lines.append(f"- {item.get('created_at') or ''} {item.get('action') or ''} {item.get('status') or ''} {item.get('resource_id') or ''}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


@dataclass
class DownloadPresentationService:
    manager_for_job: Callable[[str, dict[str, Any]], Any | None]
    list_scene_jobs: Callable[..., list[dict[str, Any]]]
    list_tile_jobs: Callable[..., list[dict[str, Any]]]
    attach_registered_download_artifacts: Callable[[Any, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]

    def download_tool_result_for_job(self, job: dict[str, Any], *, user_id: str = "") -> dict[str, Any]:
        job_id = str((job or {}).get("job_id") or "")
        scene_job = None
        tile_job = None
        if job_id:
            scene_job = next((item for item in self.list_scene_jobs(limit=100) if item.get("job_id") == job_id), None)
            tile_job = next((item for item in self.list_tile_jobs(limit=100) if item.get("job_id") == job_id), None)
        tool_result = download_job_to_tool_result(job, scene_job=scene_job, tile_job=tile_job)
        manager = self.manager_for_job(user_id, job)
        if manager is not None:
            product = {
                "product_id": str(job.get("output_name") or job.get("resource_type") or "download"),
                "resource_type": str(job.get("resource_type") or "download"),
            }
            tool_result = self.attach_registered_download_artifacts(manager, tool_result, job, product)
        return tool_result

    def attach_download_tool_result(self, payload: dict[str, Any], job_key: str = "job") -> dict[str, Any]:
        patched = dict(payload or {})
        job = patched.get(job_key)
        if isinstance(job, dict):
            tool_result = self.download_tool_result_for_job(job, user_id=str(job.get("user_id") or ""))
            step_result = {**tool_result, "step_id": "download_job"}
            response_language = detect_response_language(job.get("request_text") or job.get("region") or "")
            bundle = build_presentation_bundle(
                task_goal="download_status",
                task_plan_summary={
                    "primary_goal": "download_status",
                    "intent": "download",
                    "operation": "status",
                    "response_language": response_language,
                },
                coordinator_status=str(tool_result.get("status") or ""),
                normalized_results=[step_result],
                response_language=response_language,
            )
            patched["tool_result"] = tool_result
            patched["download_tool_result"] = tool_result
            patched["normalized_results"] = bundle["normalized_results"]
            patched["presentation_result"] = bundle["presentation_result"]
            patched["execution_summary"] = bundle["execution_summary"]
            patched["presentation_reply"] = bundle["reply"]
            patched["result_rendering_path"] = "presentation_result"
            patched["presentation_source"] = bundle.get("presentation_source")
            patched["management_view"] = download_job_to_management_view(job, tool_result=tool_result)
            patched["deprecated_raw_job_api"] = True
        jobs = patched.get("jobs")
        if isinstance(jobs, list):
            patched["management_views"] = [
                download_job_to_management_view(item, tool_result=self.download_tool_result_for_job(item, user_id=str(item.get("user_id") or "")))
                for item in jobs
                if isinstance(item, dict)
            ]
        if any(isinstance(patched.get(key), list) for key in ("scene_jobs", "tile_jobs", "audit_events")):
            patched["diagnostic_event_views"] = {
                "scene_jobs": diagnostic_event_views(patched.get("scene_jobs") if isinstance(patched.get("scene_jobs"), list) else [], default_phase="scene"),
                "tile_jobs": diagnostic_event_views(patched.get("tile_jobs") if isinstance(patched.get("tile_jobs"), list) else [], default_phase="tile"),
                "audit_events": diagnostic_event_views(patched.get("audit_events") if isinstance(patched.get("audit_events"), list) else [], default_phase="audit"),
            }
        return patched
