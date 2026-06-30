from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request

from services.downloads.resume import DownloadResumeService


def create_downloads_router(
    *,
    resume_service: Callable[[], DownloadResumeService],
    authenticated_user: Callable[[Request], str],
    audit: Callable[..., Any],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/download-jobs", tags=["downloads"])

    @router.post("/{job_id}/resume")
    def resume_download_job(job_id: str, request: Request):
        def run():
            user_id = authenticated_user(request)
            result = resume_service().resume(user_id, job_id)
            public_result = dict(result)
            public_result.pop("job", None)
            audit(
                request,
                user_id=user_id,
                action="download.resume",
                resource_type="download_job",
                resource_id=job_id,
                detail={"auto_started": result.get("auto_started")},
            )
            return public_result

        return guard(run)

    return router
