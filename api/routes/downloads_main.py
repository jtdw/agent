from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from api.schemas.downloads import DownloadActionIn, DownloadDeleteIn, DownloadIn, DownloadPreflightIn


_PRIVATE_RESPONSE_KEYS = {
    "path",
    "source_path",
    "display_path",
    "absolute_path",
    "relative_path",
    "output_path",
    "zip_path",
    "download_url",
    "url",
    "direct_url",
    "preview_path",
    "status_path",
    "log_path",
    "metrics_path",
    "storage_state_path",
    "state_path",
    "local_file_path",
}


def _looks_private_response_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith(("file:", "/api/files/artifact", "/api/downloads/artifact")):
        return True
    if re.search(r"[A-Za-z]:[\\/]", text):
        return True
    normalized = text.replace("\\", "/").lower()
    if "workspace/users/" in normalized or "workspace/sessions/" in normalized:
        return True
    return bool(re.search(r"/(?:tmp|home|var|etc|root|users)/", normalized))


def _public_download_payload(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _PRIVATE_RESPONSE_KEYS:
                continue
            cleaned = _public_download_payload(item)
            if cleaned in ({}, [], ""):
                continue
            output[key_text] = cleaned
        return output
    if isinstance(value, list):
        output = [_public_download_payload(item) for item in value]
        return [item for item in output if item not in ({}, [], "")]
    if isinstance(value, str):
        return "" if _looks_private_response_text(value) else value
    return value


def _available_actions(views: list[dict[str, Any]]) -> list[str]:
    return sorted({action for view in views for action in (view.get("available_actions") if isinstance(view.get("available_actions"), list) else [])})


def _filter_jobs_for_session(jobs: list[dict[str, Any]], session_id: str = "") -> list[dict[str, Any]]:
    requested = str(session_id or "").strip()
    if not requested:
        return jobs
    filtered: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        actual = str(job.get("session_id") or "").strip()
        if not actual or actual == requested:
            filtered.append(job)
    return filtered


def create_downloads_main_router(
    *,
    commercial_service: Callable[[], Any],
    require_request_user: Callable[[Request, str], str],
    scoped_workspace_service: Callable[[str, str], Any],
    maybe_start_gscloud_auto_download: Callable[..., dict[str, Any]],
    attach_download_tool_result: Callable[[dict[str, Any]], dict[str, Any]],
    download_tool_result_for_job: Callable[..., dict[str, Any]],
    download_job_to_management_view: Callable[..., dict[str, Any]],
    require_resource_owner: Callable[..., dict[str, Any]],
    assert_download_job_session: Callable[[dict[str, Any], str], None],
    relative_shared_download_url: Callable[..., str],
    list_gscloud_scene_jobs: Callable[..., list[dict[str, Any]]] | None,
    list_gscloud_tile_jobs: Callable[..., list[dict[str, Any]]] | None,
    format_download_job_log_text: Callable[[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]], str],
    content_disposition_attachment: Callable[[str], str],
    resolve_child_path: Callable[[Path, str], Path],
    assert_artifact_path_allowed: Callable[[Path, Path], Path],
    preflight_service: Callable[[], Any],
    workdir: str | Path | Callable[[], str | Path],
    audit: Callable[..., Any],
    compat_usage_store: Callable[[], Any],
    compat_actor_type: Callable[[Request], str],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/downloads", tags=["downloads-main"])

    def current_workdir() -> Path:
        value = workdir() if callable(workdir) else workdir
        return Path(value)

    def service() -> Any:
        return commercial_service()

    def record_raw_usage(request: Request, source: str, request_id: str) -> None:
        compat_usage_store().record("deprecated_raw_job_api_used", source=source, caller=str(request.headers.get("user-agent") or ""), request_id=request_id, actor_type=compat_actor_type(request))
        compat_usage_store().record("include_raw", source=source, caller=str(request.headers.get("user-agent") or ""), request_id=request_id, actor_type=compat_actor_type(request))

    @router.post("/submit")
    def submit_download(body: DownloadIn, request: Request):
        def run():
            user_id = require_request_user(request, body.user_id)
            if body.session_id:
                scoped_workspace_service(user_id, body.session_id)
            payload = body.model_dump()
            payload["user_id"] = user_id
            job = service().submit_job(**payload)
            auto = maybe_start_gscloud_auto_download(job, region=body.region)
            audit(request, user_id=user_id, action="download.submit", resource_type="download_job", resource_id=job["job_id"], detail={"source_key": job.get("source_key"), "resource_type": job.get("resource_type"), "auto_started": auto.get("auto_started")})
            result_payload = attach_download_tool_result({"job": service().get_job(job["job_id"]), **auto})
            if body.include_raw:
                result_payload["deprecated_raw_job_api"] = True
                record_raw_usage(request, "POST /api/downloads/submit", str(job.get("job_id") or ""))
                return result_payload
            return {
                "ok": result_payload.get("ok", True),
                "auto_supported": result_payload.get("auto_supported"),
                "auto_started": result_payload.get("auto_started"),
                "reason": result_payload.get("reason"),
                "management_view": result_payload.get("management_view"),
                "presentation_result": result_payload.get("presentation_result"),
                "execution_summary": result_payload.get("execution_summary"),
                "artifact_refs": (result_payload.get("management_view") or {}).get("artifact_refs") if isinstance(result_payload.get("management_view"), dict) else [],
                "available_actions": (result_payload.get("management_view") or {}).get("available_actions") if isinstance(result_payload.get("management_view"), dict) else [],
                "deprecated_raw_job_api": False,
            }

        return guard(run)

    @router.post("/preflight")
    def preflight_download(body: DownloadPreflightIn, request: Request):
        def run():
            user_id = require_request_user(request, body.user_id)
            if body.session_id:
                scoped_workspace_service(user_id, body.session_id)
            scoped_body = body.model_copy(update={"user_id": user_id})
            result = preflight_service().preflight(scoped_body)
            return _public_download_payload({
                **result,
                "user_id": user_id,
                "session_id": body.session_id,
            })

        return guard(run)

    @router.get("/login-health")
    def download_login_health(request: Request, user_id: str = Query(...), source_key: str = Query(default="gscloud"), account_mode: str = Query(default="platform")):
        def run():
            authorized_user_id = require_request_user(request, user_id)
            result = preflight_service().login_health(authorized_user_id, source_key, account_mode)
            audit(request, user_id=authorized_user_id, action="download.login_health", resource_type="storage_state", detail={"source_key": result["source_key"], "account_mode": result["account_mode"], "ok": result["login_health"].get("ok")})
            return _public_download_payload(result)

        return guard(run)

    @router.get("/jobs")
    def list_jobs(request: Request, user_id: str = "", session_id: str = "", include_raw: bool = Query(default=False)):
        def run():
            authorized_user_id = require_request_user(request, user_id)
            if session_id:
                scoped_workspace_service(authorized_user_id, session_id)
            jobs = _filter_jobs_for_session(service().list_jobs(user_id=authorized_user_id, session_id=session_id), session_id)
            scene_by_job: dict[str, dict] = {}
            if list_gscloud_scene_jobs is not None:
                for item in list_gscloud_scene_jobs(service().workdir, limit=100):
                    jid = str(item.get("job_id") or "")
                    if jid and jid not in scene_by_job:
                        scene_by_job[jid] = item
            for job in jobs:
                if isinstance(job, dict):
                    scene = scene_by_job.get(str(job.get("job_id") or ""))
                    if scene:
                        job["scene_status"] = scene
                        for key in ("pages_scanned", "candidate_count", "selected_count", "downloaded_count", "current_scene", "scan_stop_reason", "failure_diagnostic", "login_health", "region_resolution", "artifact_quality"):
                            if scene.get(key) is not None:
                                job[key] = scene.get(key)
                    for target in (job.get("zip_path"), job.get("output_path")):
                        url = relative_shared_download_url(str(target or ""), user_id=authorized_user_id, job_id=str(job.get("job_id") or ""), session_id=str(job.get("session_id") or ""))
                        if url:
                            job["download_url"] = url
                            break
            for job in jobs:
                if isinstance(job, dict):
                    job["tool_result"] = download_tool_result_for_job(job, user_id=authorized_user_id)
                    job["management_view"] = download_job_to_management_view(job, tool_result=job["tool_result"])
            management_views = [job["management_view"] for job in jobs if isinstance(job, dict) and isinstance(job.get("management_view"), dict)]
            payload = {
                "management_views": management_views,
                "artifact_refs": [artifact for view in management_views for artifact in (view.get("artifact_refs") if isinstance(view.get("artifact_refs"), list) else []) if isinstance(artifact, dict)],
                "available_actions": _available_actions(management_views),
                "deprecated_raw_job_api": bool(include_raw),
            }
            if include_raw:
                record_raw_usage(request, "GET /api/downloads/jobs", authorized_user_id)
                payload["jobs"] = jobs
            return payload

        return guard(run)

    @router.get("/jobs/log")
    def download_job_log(request: Request, user_id: str = Query(...), job_id: str = Query(...), session_id: str = Query(default=""), include_raw: bool = Query(default=False)):
        def run():
            authorized_user_id = require_request_user(request, user_id)
            if session_id:
                scoped_workspace_service(authorized_user_id, session_id)
            job = require_resource_owner(service().get_job(job_id), user_id=authorized_user_id, resource_name="download job")
            assert_download_job_session(job, session_id)
            tile_jobs = list_gscloud_tile_jobs(service().workdir, limit=100) if list_gscloud_tile_jobs is not None else []
            scene_jobs = list_gscloud_scene_jobs(service().workdir, limit=100) if list_gscloud_scene_jobs is not None else []
            tile_jobs = [item for item in tile_jobs if item.get("job_id") == job_id]
            scene_jobs = [item for item in scene_jobs if item.get("job_id") == job_id]
            payload = attach_download_tool_result({"job": job, "scene_jobs": scene_jobs, "tile_jobs": tile_jobs, "audit_events": service().list_audit_events(user_id=authorized_user_id, limit=20)})
            if not include_raw:
                return {
                    "management_view": payload.get("management_view"),
                    "diagnostic_event_views": payload.get("diagnostic_event_views"),
                    "artifact_refs": (payload.get("management_view") or {}).get("artifact_refs") if isinstance(payload.get("management_view"), dict) else [],
                    "available_actions": (payload.get("management_view") or {}).get("available_actions") if isinstance(payload.get("management_view"), dict) else [],
                    "deprecated_raw_job_api": False,
                }
            payload["deprecated_raw_job_api"] = True
            record_raw_usage(request, "GET /api/downloads/jobs/log", job_id)
            return payload

        return guard(run)

    @router.get("/jobs/log-download")
    def download_job_log_file(request: Request, user_id: str = Query(...), job_id: str = Query(...), session_id: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user(request, user_id)
            if session_id:
                scoped_workspace_service(authorized_user_id, session_id)
            job = require_resource_owner(service().get_job(job_id), user_id=authorized_user_id, resource_name="download job")
            assert_download_job_session(job, session_id)
            tile_jobs = list_gscloud_tile_jobs(service().workdir, limit=100) if list_gscloud_tile_jobs is not None else []
            scene_jobs = list_gscloud_scene_jobs(service().workdir, limit=100) if list_gscloud_scene_jobs is not None else []
            tile_jobs = [item for item in tile_jobs if item.get("job_id") == job_id]
            scene_jobs = [item for item in scene_jobs if item.get("job_id") == job_id]
            text = format_download_job_log_text(job, scene_jobs, tile_jobs, service().list_audit_events(user_id=authorized_user_id, limit=20))
            audit(request, user_id=authorized_user_id, action="download.log_download", resource_type="download_job", resource_id=job_id)
            return PlainTextResponse(text, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": content_disposition_attachment(f"{job_id}_log.txt")})

        return guard(run)

    @router.post("/jobs/delete")
    def delete_download_job(body: DownloadDeleteIn, request: Request):
        def run():
            user_id = require_request_user(request, body.user_id)
            if body.session_id:
                scoped_workspace_service(user_id, body.session_id)
                job = require_resource_owner(service().get_job(body.job_id), user_id=user_id, resource_name="download job")
                assert_download_job_session(job, body.session_id)
            result = service().delete_job(body.job_id, user_id=user_id)
            jobs = _filter_jobs_for_session(service().list_jobs(user_id=user_id, session_id=body.session_id), body.session_id)
            management_views = [download_job_to_management_view(job, tool_result=download_tool_result_for_job(job)) for job in jobs if isinstance(job, dict)]
            audit(request, user_id=user_id, action="download.delete", resource_type="download_job", resource_id=body.job_id)
            return {**result, "management_views": management_views, "available_actions": _available_actions(management_views), "deprecated_raw_job_api": False}

        return guard(run)

    @router.post("/jobs/cancel")
    def cancel_download_job(body: DownloadActionIn, request: Request):
        def run():
            user_id = require_request_user(request, body.user_id)
            if body.session_id:
                scoped_workspace_service(user_id, body.session_id)
                job = require_resource_owner(service().get_job(body.job_id), user_id=user_id, resource_name="download job")
                assert_download_job_session(job, body.session_id)
            result = service().cancel_job(body.job_id, user_id=user_id, reason=body.reason)
            jobs = _filter_jobs_for_session(service().list_jobs(user_id=user_id, session_id=body.session_id), body.session_id)
            audit(request, user_id=user_id, action="download.cancel", resource_type="download_job", resource_id=body.job_id)
            payload = attach_download_tool_result({**result, "job": result, "jobs": jobs})
            views = payload.get("management_views") if isinstance(payload.get("management_views"), list) else []
            return {"ok": payload.get("ok"), "management_view": payload.get("management_view"), "management_views": payload.get("management_views"), "available_actions": _available_actions(views), "deprecated_raw_job_api": False}

        return guard(run)

    @router.post("/jobs/retry")
    def retry_download_job(body: DownloadActionIn, request: Request):
        def run():
            user_id = require_request_user(request, body.user_id)
            if body.session_id:
                scoped_workspace_service(user_id, body.session_id)
                job = require_resource_owner(service().get_job(body.job_id), user_id=user_id, resource_name="download job")
                assert_download_job_session(job, body.session_id)
            retry = service().retry_job(body.job_id, user_id=user_id, session_id=body.session_id)
            auto = maybe_start_gscloud_auto_download(retry, region=str(retry.get("region") or ""))
            jobs = _filter_jobs_for_session(service().list_jobs(user_id=user_id, session_id=body.session_id), body.session_id)
            audit(request, user_id=user_id, action="download.retry", resource_type="download_job", resource_id=retry["job_id"], detail={"retried_from": body.job_id, "auto_started": auto.get("auto_started")})
            payload = attach_download_tool_result({"job": service().get_job(retry["job_id"]), **auto, "jobs": jobs})
            views = payload.get("management_views") if isinstance(payload.get("management_views"), list) else []
            return {"ok": payload.get("ok", True), "auto_supported": payload.get("auto_supported"), "auto_started": payload.get("auto_started"), "reason": payload.get("reason"), "management_view": payload.get("management_view"), "management_views": payload.get("management_views"), "available_actions": _available_actions(views), "deprecated_raw_job_api": False}

        return guard(run)

    @router.get("/artifact")
    def download_job_artifact(request: Request, user_id: str = Query(...), job_id: str = Query(...), path: str = Query(...), session_id: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user(request, user_id)
            if session_id:
                scoped_workspace_service(authorized_user_id, session_id)
            job = require_resource_owner(service().get_job(job_id), user_id=authorized_user_id, resource_name="download job")
            assert_download_job_session(job, session_id)
            target = resolve_child_path(current_workdir(), path)
            target = assert_artifact_path_allowed(current_workdir(), target)
            allowed = {str(job.get("zip_path") or ""), str(job.get("output_path") or "")}
            if str(target.resolve()) not in {str(Path(item).resolve()) for item in allowed if item}:
                audit(request, user_id=authorized_user_id, action="download.artifact", status="denied", resource_type="download_job", resource_id=job_id, detail={"path": path})
                raise PermissionError("Download path does not belong to this job.")
            audit(request, user_id=authorized_user_id, action="download.artifact", resource_type="download_job", resource_id=job_id, detail={"path": path})
            return FileResponse(str(target), filename=target.name, headers={"Content-Disposition": content_disposition_attachment(target.name)})

        return guard(run)

    return router
