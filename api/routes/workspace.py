from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable, Protocol

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from api.schemas.workspace import ArtifactDeleteIn, ExportIn
from core.artifacts import assert_artifact_path_allowed, content_disposition_attachment, safe_download_filename, shapefile_zip_path
from core.task_outcome_advisor import build_task_outcome, format_task_outcome_markdown


_PRIVATE_MESSAGE_TEXT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s`'\"，。；;]+|/(?:tmp|home|var|etc|root|Users)/[^\s`'\"，。；;]+|workspace[\\/](?:users|sessions)[^\s`'\"，。；;]*|/api/(?:files/artifact|downloads/artifact)\?[^\s`'\"，。；;]+)",
    re.IGNORECASE,
)


def _public_user_message_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _PRIVATE_MESSAGE_TEXT_RE.sub("[已隐藏内部路径]", text)


class WorkspaceManager(Protocol):
    upload_dir: Path
    workdir: Path
    current_session_id: str

    def _unique_storage_name(self, filename: str) -> str: ...

    def list_datasets(self) -> list[dict[str, Any]]: ...

    def delete_result_file(self, *, artifact_id: str = "", path: str = "") -> dict[str, Any]: ...

    def assert_artifact_access(self, user_id: str, session_id: str, artifact_id: str) -> dict[str, Any]: ...


class WorkspaceService(Protocol):
    current_session_id: str
    manager: WorkspaceManager

    def upload_saved_files_batch(self, payload: list[tuple[Path, str]]) -> list[str]: ...

    def export_results(self, *, mode: str) -> dict[str, Any]: ...


def create_workspace_router(
    *,
    scoped_workspace_service: Callable[[str, str], WorkspaceService],
    require_request_user_if_present: Callable[[Request, str], str],
    decorate_dashboard: Callable[..., dict[str, Any]],
    build_workspace_mentions: Callable[[list[dict[str, Any]]], dict[str, Any]],
    local_library_items: Callable[[], list[dict[str, Any]]],
    artifact_download_url: Callable[..., str],
    public_artifact_or_error: Callable[..., dict[str, Any]],
    audit: Callable[..., Any],
    guard: Callable[[Callable[[], Any]], Any],
    max_upload_files: int | Callable[[], int],
    max_upload_bytes: int | Callable[[], int],
) -> APIRouter:
    router = APIRouter(tags=["workspace"])

    def _limit(value: int | Callable[[], int]) -> int:
        return int(value() if callable(value) else value)

    @router.post("/api/files/upload")
    async def upload_files(request: Request, user_id: str = Form(default=""), session_id: str = Form(default=""), files: list[UploadFile] = File(...)):
        authorized_user_id = require_request_user_if_present(request, user_id)
        service = scoped_workspace_service(authorized_user_id, session_id)

        async def save_streamed_uploads() -> list[tuple[Path, str]]:
            upload_file_limit = _limit(max_upload_files)
            upload_byte_limit = _limit(max_upload_bytes)
            if len(files) > upload_file_limit:
                raise ValueError(f"单次最多上传 {upload_file_limit} 个文件。")
            saved: list[tuple[Path, str]] = []
            total_size = 0
            chunk_size = 1024 * 1024
            try:
                for file in files:
                    original = file.filename or "uploaded.bin"
                    target = service.manager.upload_dir / service.manager._unique_storage_name(original)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    file_size = 0
                    with target.open("wb") as out:
                        while True:
                            chunk = await file.read(chunk_size)
                            if not chunk:
                                break
                            file_size += len(chunk)
                            total_size += len(chunk)
                            if total_size > upload_byte_limit:
                                raise ValueError(f"单次上传总大小不能超过 {upload_byte_limit // 1024 // 1024} MB。")
                            out.write(chunk)
                    if file_size:
                        saved.append((target, original))
                    else:
                        target.unlink(missing_ok=True)
                return saved
            except Exception:
                for path, _ in saved:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        pass
                try:
                    if "target" in locals():
                        target.unlink(missing_ok=True)
                except Exception:
                    pass
                raise

        async def run_async():
            payload = await save_streamed_uploads()
            if not payload:
                raise HTTPException(status_code=400, detail="没有读取到有效上传文件。")
            try:
                messages = [_public_user_message_text(item) for item in service.upload_saved_files_batch(payload)]
            except Exception:
                for path, _ in payload:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        pass
                raise
            result = {"ok": True, "count": len(payload), "messages": messages}
            dashboard_data = decorate_dashboard(service, user_id=authorized_user_id)
            outcome = build_task_outcome("upload", result, dashboard=dashboard_data)
            return {**result, "dashboard": dashboard_data, "task_outcome": outcome, "outcome_markdown": format_task_outcome_markdown(outcome)}

        try:
            return await run_async()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/api/workspace/dashboard")
    def dashboard(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            data = decorate_dashboard(scoped_workspace_service(authorized_user_id, session_id), user_id=authorized_user_id)
            data["local_library"] = local_library_items()
            return data

        return guard(run)

    @router.get("/api/workspace/mentions")
    def workspace_mentions(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            service = scoped_workspace_service(authorized_user_id, session_id)
            return build_workspace_mentions(service.manager.list_datasets())

        return guard(run)

    @router.post("/api/workspace/export")
    def export_workspace(body: ExportIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            service = scoped_workspace_service(user_id, body.session_id)
            result = service.export_results(mode=body.mode)
            artifact_id = str(result.get("artifact_id") or "")
            public_result = {
                "artifact_id": artifact_id,
                "download_url": artifact_download_url(artifact_id, user_id=user_id, session_id=service.current_session_id),
                "file_count": int(result.get("file_count") or 0),
                "mode": str(result.get("mode") or body.mode),
            }
            audit(request, user_id=user_id, action="workspace.export", resource_type="artifact", resource_id=str(result.get("zip_path") or ""), detail={"mode": body.mode, "file_count": result.get("file_count")})
            return public_result

        return guard(run)

    @router.post("/api/workspace/artifacts/delete")
    def delete_workspace_artifact(body: ArtifactDeleteIn, request: Request):
        def run():
            user_id = require_request_user_if_present(request, body.user_id)
            service = scoped_workspace_service(user_id, body.session_id)
            artifact_id = str(body.artifact_id or "").strip()
            if not artifact_id:
                raise HTTPException(status_code=400, detail="artifact_id is required for workspace artifact deletion.")
            service.manager.assert_artifact_access(user_id, body.session_id or service.current_session_id, artifact_id)
            result = service.manager.delete_result_file(artifact_id=artifact_id, path="")
            audit(
                request,
                user_id=user_id,
                action="artifact.delete",
                resource_type="artifact",
                resource_id=artifact_id,
                detail={k: result.get(k) for k in ("path", "deleted_files", "deleted_artifacts", "deleted_datasets")},
            )
            deleted_artifacts = result.get("deleted_artifacts", [])
            deleted_datasets = result.get("deleted_datasets", [])
            status = "deleted" if result.get("deleted_files") or deleted_artifacts or deleted_datasets else "not_found"
            return {
                "ok": status == "deleted",
                "artifact_id": artifact_id,
                "status": status,
                "file_deleted": bool(result.get("deleted_files")),
                "deleted_artifacts": deleted_artifacts,
                "deleted_datasets": deleted_datasets,
                "dashboard": decorate_dashboard(service, user_id=user_id),
            }

        return guard(run)

    @router.get("/api/artifacts/{artifact_id}")
    def artifact_metadata(artifact_id: str, request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            service = scoped_workspace_service(authorized_user_id, session_id)
            return public_artifact_or_error(service, artifact_id, user_id=authorized_user_id, session_id=session_id)

        return guard(run)

    @router.delete("/api/artifacts/{artifact_id}")
    def delete_artifact(artifact_id: str, request: Request, user_id: str = Query(default=""), session_id: str = Query(default=""), delete_file: bool = Query(default=True)):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            service = scoped_workspace_service(authorized_user_id, session_id)
            service.manager.assert_artifact_access(authorized_user_id, session_id or service.current_session_id, artifact_id)
            result = service.manager.delete_result_file(artifact_id=artifact_id if delete_file else "", path="")
            status = "deleted" if result.get("deleted_files") or result.get("deleted_artifacts") or result.get("deleted_datasets") else "not_found"
            audit(
                request,
                user_id=authorized_user_id,
                action="artifact.delete",
                resource_type="artifact",
                resource_id=artifact_id,
                detail={k: result.get(k) for k in ("deleted_files", "deleted_artifacts", "deleted_datasets")},
            )
            return {
                "ok": status == "deleted",
                "artifact_id": artifact_id,
                "status": status,
                "file_deleted": bool(result.get("deleted_files")),
                "deleted_artifacts": result.get("deleted_artifacts", []),
                "deleted_datasets": result.get("deleted_datasets", []),
            }

        return guard(run)

    @router.get("/api/artifacts/{artifact_id}/download")
    def artifact_download(artifact_id: str, request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            service = scoped_workspace_service(authorized_user_id, session_id)
            artifact = service.manager.assert_artifact_access(authorized_user_id, session_id or service.current_session_id, artifact_id)
            public = public_artifact_or_error(service, artifact_id, user_id=authorized_user_id, session_id=session_id)
            target = assert_artifact_path_allowed(service.manager.workdir, str(artifact.get("path") or ""))
            if target.suffix.lower() == ".shp":
                target = shapefile_zip_path(service.manager.workdir, target, artifact_id)
            if not target.exists() or not target.is_file():
                raise FileNotFoundError("文件已清理、无访问权限或下载链接已失效。")
            if target.stat().st_size <= 0:
                raise FileNotFoundError("文件已清理、无访问权限或下载链接已失效。")
            audit(request, user_id=authorized_user_id, action="artifact.download", resource_type="artifact", resource_id=artifact_id)
            return FileResponse(
                str(target),
                media_type=str(public.get("mime_type") or "application/octet-stream"),
                filename=safe_download_filename(str(public.get("filename") or target.name)),
                headers={"Content-Disposition": content_disposition_attachment(str(public.get("filename") or target.name))},
            )

        return guard(run)

    @router.get("/api/files/artifact")
    def artifact(request: Request, user_id: str = Query(default=""), session_id: str = Query(default=""), path: str = Query(default="")):
        raise HTTPException(
            status_code=410,
            detail="Deprecated artifact path downloads are disabled. Use /api/artifacts/{artifact_id}/download.",
        )

    return router
