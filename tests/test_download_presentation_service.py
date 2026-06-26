from __future__ import annotations

from services.downloads.presentation import DownloadPresentationService, assert_download_job_session, format_download_job_log_text


def test_assert_download_job_session_allows_legacy_unscoped_jobs_and_rejects_mismatch() -> None:
    assert_download_job_session({"session_id": ""}, "s1")
    assert_download_job_session({"session_id": "s1"}, "s1")

    try:
        assert_download_job_session({"session_id": "s2"}, "s1")
    except PermissionError as exc:
        assert "another session" in str(exc)
    else:
        raise AssertionError("expected session mismatch to fail")


def test_download_presentation_service_attaches_views_and_registered_artifacts() -> None:
    calls: list[tuple[str, object]] = []

    class FakeManager:
        pass

    def manager_for_job(user_id: str, job: dict):
        calls.append(("manager", (user_id, job["job_id"])))
        return FakeManager()

    service = DownloadPresentationService(
        manager_for_job=manager_for_job,
        list_scene_jobs=lambda limit=100: [{"job_id": "job1", "scene_job_id": "scene1"}],
        list_tile_jobs=lambda limit=100: [{"job_id": "job1", "tile_job_id": "tile1"}],
        attach_registered_download_artifacts=lambda manager, result, job, product: {**result, "registered": product["product_id"]},
    )
    payload = service.attach_download_tool_result(
        {
            "job": {"job_id": "job1", "user_id": "u1", "resource_type": "dem", "status": "completed"},
            "jobs": [{"job_id": "job1", "user_id": "u1", "resource_type": "dem"}],
            "scene_jobs": [{"stage": "scan", "status": "running"}],
            "tile_jobs": [{"stage": "tile", "status": "queued"}],
            "audit_events": [{"action": "download.submit", "status": "ok"}],
        }
    )

    assert payload["download_tool_result"]["registered"] == "dem"
    assert payload["management_view"]["task_id"] == "job1"
    assert payload["management_views"][0]["task_id"] == "job1"
    assert payload["diagnostic_event_views"]["scene_jobs"][0]["phase"] == "scan"
    assert ("manager", ("u1", "job1")) in calls


def test_format_download_job_log_text_contains_core_sections() -> None:
    text = format_download_job_log_text(
        {"job_id": "job1", "status": "running", "stage": "download", "progress": 50, "source_key": "gscloud", "resource_type": "dem", "region": "chengdu"},
        scene_jobs=[{"scene_job_id": "scene1", "state": "running", "message": "ok"}],
        tile_jobs=[],
        audit_events=[{"created_at": "now", "action": "download.submit", "status": "ok", "resource_id": "job1"}],
    )

    assert "Download job log: job1" in text
    assert "Scene jobs:" in text
    assert "Tile jobs:" in text
    assert "Recent audit events:" in text
