from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.routes.admin_capabilities import create_capabilities_router
from api.routes.admin_operations import create_admin_operations_router
from api.routes.admin_platform import create_admin_platform_router
from api.routes.chat_actions import create_chat_actions_router
from api.routes.chat_state import create_chat_state_router
from api.routes.data_sources import create_data_sources_router
from api.routes.downloads import create_downloads_router
from api.routes.downloads_main import create_downloads_main_router
from api.routes.auth import create_auth_router
from api.routes.local_library import create_local_library_router
from api.routes.map import create_map_router
from api.routes.payments import create_payments_router
from api.routes.system import create_system_router
from api.routes.workflows import create_workflows_router
from api.routes.workspace import create_workspace_router


class RouteModulesBehaviorTests(unittest.TestCase):
    def test_downloads_main_routes_cover_job_lifecycle_and_artifact_policy(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeCommercialService:
            workdir = "."

            def __init__(self) -> None:
                self.job = {
                    "job_id": "job1",
                    "user_id": "u1",
                    "session_id": "s1",
                    "source_key": "gscloud",
                    "resource_type": "dem",
                    "region": "chengdu",
                    "status": "queued",
                    "output_path": "result.txt",
                    "zip_path": "",
                    "diagnostic": "/tmp/secret/download.log",
                }

            def submit_job(self, **payload) -> dict:
                calls.append(("submit", payload["user_id"]))
                self.job.update(payload)
                return dict(self.job)

            def get_job(self, job_id: str) -> dict:
                calls.append(("get_job", job_id))
                return dict(self.job)

            def list_jobs(self, *, user_id: str, session_id: str = "", **kwargs) -> list[dict]:
                calls.append(("list_jobs", (user_id, session_id)))
                return [dict(self.job)]

            def list_audit_events(self, *, user_id: str, limit: int) -> list[dict]:
                calls.append(("audit_events", (user_id, limit)))
                return [{"action": "download.submit"}]

            def delete_job(self, job_id: str, *, user_id: str) -> dict:
                calls.append(("delete", (job_id, user_id)))
                return {"ok": True, "deleted": job_id}

            def cancel_job(self, job_id: str, *, user_id: str, reason: str = "") -> dict:
                calls.append(("cancel", (job_id, reason)))
                return {**self.job, "ok": True, "status": "cancelled"}

            def retry_job(self, job_id: str, *, user_id: str, session_id: str = "") -> dict:
                calls.append(("retry", (job_id, session_id)))
                return {**self.job, "job_id": "job2", "status": "queued"}

            def get_user_storage_state_path(self, user_id: str, source: str) -> str:
                calls.append(("user_state", (user_id, source)))
                return "state.json"

        service = FakeCommercialService()
        app = FastAPI()
        app.include_router(
            create_downloads_main_router(
                commercial_service=lambda: service,
                require_request_user=lambda request, user_id: user_id or "u1",
                scoped_workspace_service=lambda user_id, session_id="": calls.append(("workspace", (user_id, session_id))),
                maybe_start_gscloud_auto_download=lambda job, region="": {"auto_supported": True, "auto_started": False, "reason": "test"},
                attach_download_tool_result=lambda payload: {**payload, "management_view": {"available_actions": ["cancel"], "artifact_refs": [{"artifact_id": "a1"}]}, "management_views": [{"available_actions": ["cancel"]}]},
                download_tool_result_for_job=lambda job, user_id="": {"ok": True, "job_id": job["job_id"]},
                download_job_to_management_view=lambda job, tool_result=None: {"job_id": job["job_id"], "available_actions": ["cancel"], "artifact_refs": [{"artifact_id": "a1"}]},
                require_resource_owner=lambda resource, user_id="", resource_name="": resource,
                assert_download_job_session=lambda job, session_id="": calls.append(("assert_session", session_id)),
                relative_shared_download_url=lambda path, **kwargs: f"/download/{path}" if path else "",
                list_gscloud_scene_jobs=lambda workdir, limit=100: [{"job_id": "job1", "downloaded_count": 1}],
                list_gscloud_tile_jobs=lambda workdir, limit=100: [{"job_id": "job1", "tile_job_id": "tile1"}],
                format_download_job_log_text=lambda job, scene_jobs, tile_jobs, audit_events: "job log",
                content_disposition_attachment=lambda filename: f"attachment; filename={filename}",
                resolve_child_path=lambda base, path: __import__("pathlib").Path(base) / path,
                assert_artifact_path_allowed=lambda base, target: target,
                preflight_service=lambda: type(
                    "PreflightService",
                    (),
                    {
                        "preflight": lambda self, body: {"ok": True, "verified": True},
                        "login_health": lambda self, user_id, source_key, account_mode: {
                            "source_key": source_key,
                            "account_mode": account_mode,
                            "login_health": {
                                "ok": True,
                                "path": r"E:\agent\workspace\domestic_auth\state.json",
                                "storage_state_path": r"E:\agent\workspace\domestic_auth\state.json",
                                "download_url": "/api/files/artifact?path=domestic_auth/state.json",
                                "diagnostic": "/var/log/secret/domestic-auth.log",
                            },
                        },
                    },
                )(),
                workdir=lambda: ".",
                audit=lambda request, **kwargs: calls.append(("audit", kwargs["action"])),
                compat_usage_store=lambda: type("Store", (), {"record": lambda self, *args, **kwargs: calls.append(("compat", args[0]))})(),
                compat_actor_type=lambda request: "automated_test",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        submitted = client.post("/api/downloads/submit", json={"user_id": "u1", "session_id": "s1", "region": "chengdu"}).json()
        self.assertEqual(submitted["auto_supported"], True)
        preflight = client.post("/api/downloads/preflight", json={"user_id": "u1", "region": "chengdu"}).json()
        login_health = client.get("/api/downloads/login-health?user_id=u1&account_mode=own").json()
        public_jobs = client.get("/api/downloads/jobs?user_id=u1&session_id=s1").json()
        public_text = json.dumps({"preflight": preflight, "login_health": login_health, "jobs": public_jobs}, ensure_ascii=False)
        self.assertEqual(preflight["verified"], True)
        self.assertTrue(login_health["login_health"]["ok"])
        self.assertNotIn("path", public_text)
        self.assertNotIn("storage_state_path", public_text)
        self.assertNotIn("download_url", public_text)
        self.assertNotIn("output_path", public_text)
        self.assertNotIn("zip_path", public_text)
        self.assertNotIn("E:\\agent", public_text)
        self.assertNotIn("/tmp/secret", public_text)
        self.assertNotIn("/var/log/secret", public_text)
        self.assertNotIn("/api/files/artifact", public_text)
        self.assertNotIn("jobs", public_jobs)
        jobs = client.get("/api/downloads/jobs?user_id=u1&session_id=s1&include_raw=true").json()
        self.assertEqual(jobs["jobs"][0]["download_url"], "/download/result.txt")
        self.assertEqual(client.get("/api/downloads/jobs/log?user_id=u1&job_id=job1&session_id=s1").json()["artifact_refs"], [{"artifact_id": "a1"}])
        self.assertIn("job log", client.get("/api/downloads/jobs/log-download?user_id=u1&job_id=job1&session_id=s1").text)
        self.assertEqual(client.post("/api/downloads/jobs/delete", json={"user_id": "u1", "session_id": "s1", "job_id": "job1"}).json()["deleted"], "job1")
        self.assertEqual(client.post("/api/downloads/jobs/cancel", json={"user_id": "u1", "session_id": "s1", "job_id": "job1", "reason": "stop"}).json()["ok"], True)
        self.assertEqual(client.post("/api/downloads/jobs/retry", json={"user_id": "u1", "session_id": "s1", "job_id": "job1"}).json()["auto_supported"], True)

        self.assertIn(("submit", "u1"), calls)
        self.assertIn(("audit", "download.submit"), calls)
        self.assertIn(("compat", "include_raw"), calls)

    def test_downloads_main_preflight_and_job_views_are_session_scoped(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeCommercialService:
            workdir = "."

            def __init__(self) -> None:
                self.jobs = [
                    {"job_id": "job_s1", "user_id": "authorized_u1", "session_id": "s1", "status": "completed", "resource_type": "dem"},
                    {"job_id": "job_s2", "user_id": "authorized_u1", "session_id": "s2", "status": "completed", "resource_type": "dem"},
                ]

            def list_jobs(self, *, user_id: str, session_id: str = "", **kwargs) -> list[dict]:
                calls.append(("list_jobs", (user_id, session_id)))
                return [dict(item) for item in self.jobs]

            def get_job(self, job_id: str) -> dict:
                return next(dict(item) for item in self.jobs if item["job_id"] == job_id)

            def list_audit_events(self, *, user_id: str, limit: int) -> list[dict]:
                return []

            def cancel_job(self, job_id: str, *, user_id: str, reason: str = "") -> dict:
                calls.append(("cancel", (job_id, user_id, reason)))
                return dict(self.get_job(job_id))

        class FakePreflightService:
            def preflight(self, body) -> dict:
                calls.append(("preflight", (body.user_id, body.session_id)))
                return {"ok": True, "state": "READY"}

            def login_health(self, user_id, source_key, account_mode) -> dict:
                return {"source_key": source_key, "account_mode": account_mode, "login_health": {"ok": True}}

        def attach_download_tool_result(payload: dict) -> dict:
            jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
            calls.append(("presentation_jobs", [job["job_id"] for job in jobs]))
            return {
                **payload,
                "ok": True,
                "management_view": {"task_id": payload.get("job", {}).get("job_id", ""), "available_actions": ["view_artifacts"], "artifact_refs": [{"artifact_id": f"artifact_{payload.get('job', {}).get('job_id', '')}"}]},
                "management_views": [
                    {"task_id": job["job_id"], "available_actions": ["view_artifacts"], "artifact_refs": [{"artifact_id": f"artifact_{job['job_id']}"}]}
                    for job in jobs
                ],
                "presentation_result": {
                    "schema_version": "presentation-result/v1",
                    "status": "succeeded",
                    "artifact_refs": [{"artifact_id": f"artifact_{payload.get('job', {}).get('job_id', '')}"}],
                },
            }

        service = FakeCommercialService()
        app = FastAPI()
        app.include_router(
            create_downloads_main_router(
                commercial_service=lambda: service,
                require_request_user=lambda request, user_id: f"authorized_{user_id}",
                scoped_workspace_service=lambda user_id, session_id="": calls.append(("workspace", (user_id, session_id))),
                maybe_start_gscloud_auto_download=lambda job, region="": {"auto_supported": True, "auto_started": False},
                attach_download_tool_result=attach_download_tool_result,
                download_tool_result_for_job=lambda job, user_id="": {"ok": True, "job_id": job["job_id"], "artifacts": [{"artifact_id": f"artifact_{job['job_id']}"}]},
                download_job_to_management_view=lambda job, tool_result=None: {"task_id": job["job_id"], "available_actions": ["view_artifacts"], "artifact_refs": [{"artifact_id": f"artifact_{job['job_id']}"}]},
                require_resource_owner=lambda resource, user_id="", resource_name="": resource,
                assert_download_job_session=lambda job, session_id="": calls.append(("assert_session", (job["job_id"], session_id))),
                relative_shared_download_url=lambda path, **kwargs: "",
                list_gscloud_scene_jobs=lambda workdir, limit=100: [],
                list_gscloud_tile_jobs=lambda workdir, limit=100: [],
                format_download_job_log_text=lambda job, scene_jobs, tile_jobs, audit_events: "",
                content_disposition_attachment=lambda filename: f"attachment; filename={filename}",
                resolve_child_path=lambda base, path: __import__("pathlib").Path(base) / path,
                assert_artifact_path_allowed=lambda base, target: target,
                preflight_service=lambda: FakePreflightService(),
                workdir=lambda: ".",
                audit=lambda request, **kwargs: calls.append(("audit", kwargs["action"])),
                compat_usage_store=lambda: type("Store", (), {"record": lambda self, *args, **kwargs: None})(),
                compat_actor_type=lambda request: "automated_test",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        preflight = client.post("/api/downloads/preflight", json={"user_id": "u1", "session_id": "s1", "region": "chengdu"}).json()
        jobs = client.get("/api/downloads/jobs?user_id=u1&session_id=s1&include_raw=true").json()
        cancelled = client.post("/api/downloads/jobs/cancel", json={"user_id": "u1", "session_id": "s1", "job_id": "job_s1"}).json()

        self.assertEqual(preflight["user_id"], "authorized_u1")
        self.assertEqual(preflight["session_id"], "s1")
        self.assertEqual(jobs["jobs"][0]["job_id"], "job_s1")
        self.assertEqual([view["task_id"] for view in jobs["management_views"]], ["job_s1"])
        self.assertEqual(jobs["artifact_refs"], [{"artifact_id": "artifact_job_s1"}])
        self.assertEqual([view["task_id"] for view in cancelled["management_views"]], ["job_s1"])
        self.assertNotIn("artifact_job_s2", str(jobs))
        self.assertNotIn("artifact_job_s2", str(cancelled))
        self.assertIn(("workspace", ("authorized_u1", "s1")), calls)
        self.assertIn(("preflight", ("authorized_u1", "s1")), calls)
        self.assertIn(("presentation_jobs", ["job_s1"]), calls)

    def test_admin_platform_routes_manage_accounts_login_health_and_status(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeCommercialService:
            def __init__(self) -> None:
                self.accounts: dict[str, dict] = {}

            def _platform_public(self, account: dict) -> dict:
                public = dict(account)
                public["has_password"] = bool(public.get("password"))
                public.pop("password", None)
                public.pop("storage_state_path", None)
                return public

            def list_platform_accounts(self, *, source_key: str, include_inactive: bool) -> list[dict]:
                calls.append(("list", (source_key, include_inactive)))
                return list(self.accounts.values())

            def upsert_platform_account(self, **kwargs) -> dict:
                calls.append(("upsert", kwargs))
                account = {"account_id": "acct1", "status": "active", **kwargs, "storage_state_path": "E:/secret/state.json"}
                self.accounts["acct1"] = account
                return account

            def get_platform_account_private(self, account_id: str) -> dict:
                calls.append(("private", account_id))
                return dict(self.accounts[account_id])

            def write_audit_event(self, **kwargs) -> None:
                calls.append(("audit", kwargs["action"]))

            def set_platform_account_status(self, account_id: str, status: str) -> dict:
                calls.append(("set_status", (account_id, status)))
                self.accounts[account_id]["status"] = status
                return dict(self.accounts[account_id])

        service = FakeCommercialService()
        app = FastAPI()
        app.include_router(
            create_admin_platform_router(
                commercial_service=lambda: service,
                require_capability_admin=lambda request: (_ for _ in ()).throw(PermissionError("admin required")) if request.headers.get("x-admin-token") != "secret" else calls.append(("admin", True)),
                inspect_storage_state=lambda path: {
                    "ok": bool(path),
                    "reason": "checked",
                    "path": path,
                    "storage_state_path": path,
                    "status_path": "E:/should/not/leak-status.json",
                    "log_path": "E:/should/not/leak.log",
                    "diagnostics": {
                        "runtime_log": "/tmp/should/not/leak-runtime.log",
                        "home_state": "/home/app/should/not/leak-state.json",
                    },
                },
                gscloud_platform_state_path=lambda workdir, account_id, source_key: f"{workdir}/{source_key}/{account_id}.json",
                start_gscloud_login_process=lambda **kwargs: {
                    "login_job_id": "login1",
                    "state": "BROWSER_OPENING",
                    "message": "opening",
                    "timeout_seconds": kwargs["timeout_seconds"],
                    "created_at": "now",
                    "updated_at": "now",
                    "status_path": "E:/should/not/leak.json",
                    "log_path": "E:/should/not/leak.log",
                },
                workdir=lambda: "E:/work",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        self.assertEqual(client.get("/api/admin/platform-accounts").status_code, 403)
        created = client.post(
            "/api/admin/platform-accounts",
            headers={"x-admin-token": "secret"},
            json={"source_key": "gscloud", "username": "demo", "password": "secret", "label": "Platform", "daily_limit": 3, "monthly_limit": 9},
        ).json()
        self.assertEqual(created["account"]["account_id"], "acct1")
        self.assertNotIn("password", created["account"])
        self.assertNotIn("storage_state_path", created["account"])
        listed = client.get("/api/admin/platform-accounts?include_inactive=true", headers={"x-admin-token": "secret"}).json()
        self.assertTrue(listed["accounts"][0]["login_health"]["ok"])
        self.assertNotIn("path", listed["accounts"][0]["login_health"])
        self.assertNotIn("storage_state_path", listed["accounts"][0]["login_health"])
        self.assertNotIn("status_path", listed["accounts"][0]["login_health"])
        self.assertNotIn("log_path", listed["accounts"][0]["login_health"])
        login = client.post("/api/admin/platform-accounts/acct1/login", headers={"x-admin-token": "secret"}, json={"timeout_seconds": 60, "headless": True}).json()
        self.assertEqual(login["login_job"]["login_job_id"], "login1")
        self.assertNotIn("status_path", login["login_job"])
        health = client.get("/api/admin/platform-accounts/acct1/health", headers={"x-admin-token": "secret"}).json()
        self.assertTrue(health["login_health"]["ok"])
        self.assertNotIn("path", health["login_health"])
        self.assertNotIn("storage_state_path", health["login_health"])
        self.assertNotIn("status_path", health["login_health"])
        self.assertNotIn("log_path", health["login_health"])
        self.assertNotIn("E:/should/not/leak", str({"listed": listed, "login": login, "health": health}))
        self.assertNotIn("/tmp/should/not/leak", str({"listed": listed, "login": login, "health": health}))
        self.assertNotIn("/home/app/should/not/leak", str({"listed": listed, "login": login, "health": health}))
        disabled = client.post("/api/admin/platform-accounts/acct1/status", headers={"x-admin-token": "secret"}, json={"status": "disabled"}).json()
        self.assertEqual(disabled["account"]["status"], "disabled")

        self.assertIn(("set_status", ("acct1", "disabled")), calls)
        self.assertIn(("audit", "admin.platform_account.login_started"), calls)

    def test_admin_operations_routes_cover_dataset_reports_reset_and_cleanup(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeDatasetStore:
            def list_profiles(self, *, include_inactive: bool = False) -> list[dict]:
                calls.append(("list_profiles", include_inactive))
                return [{"product_id": "p1", "status": "active"}]

            def upsert_profile(self, body: dict) -> dict:
                calls.append(("upsert_profile", body))
                return dict(body)

            def set_status(self, product_id: str, status: str, *, actor: str = "", summary: str = "") -> dict:
                calls.append(("set_status", (product_id, status, actor, summary)))
                return {"product_id": product_id, "status": status}

        class FakeReportStore:
            def __init__(self, label: str) -> None:
                self.label = label

            def report(self, *, exclude_actor_types: set[str]) -> dict:
                calls.append((self.label, sorted(exclude_actor_types)))
                return {"report": self.label}

        commercial = {"service": "old"}
        app = FastAPI()
        app.include_router(
            create_admin_operations_router(
                dataset_availability_store=lambda: FakeDatasetStore(),
                compatibility_usage_store=lambda: FakeReportStore("compat"),
                trial_monitoring_store=lambda: FakeReportStore("trial"),
                require_capability_admin=lambda request: (_ for _ in ()).throw(PermissionError("admin required")) if request.headers.get("x-admin-token") != "secret" else calls.append(("admin", True)),
                scan_dataset_availability=lambda product_id, scan_method="", actor="", summary="": {"product_id": product_id, "scan_method": scan_method, "actor": actor, "summary": summary},
                reset_system_workspace=lambda *, workdir, commercial_service, mode, confirm_text: {
                    "ok": True,
                    "commercial_service": {"service": "new"},
                    "mode": mode,
                    "workdir": str(workdir),
                    "root": str(workdir),
                    "confirm_text": confirm_text,
                    "debug_path": "E:/work/secret/reset-debug.json",
                    "deleted": {
                        "files": 2,
                        "directories": 1,
                        "bytes": 32,
                        "errors": ["E:/work/secret/delete-error.log", "/tmp/work/secret/delete-error.log"],
                    },
                    "preserved": {"accounts": 1, "workspace_entries": ["capability_config"]},
                    "capability_cleanup": {"private_knowledge_items": ["k1"], "index_dirs": ["vector_index"]},
                },
                get_commercial_service=lambda: commercial["service"],
                set_commercial_service=lambda value: commercial.__setitem__("service", value),
                clear_workspace_services=lambda: calls.append(("clear_workspace", True)),
                ensure_base_dirs=lambda: calls.append(("ensure_dirs", True)),
                scan_storage_cleanup_candidates=lambda workdir: {
                    "schema_version": "storage-cleanup-scan/v1",
                    "root": str(workdir),
                    "workdir": str(workdir),
                    "candidates": [
                        {
                            "candidate_id": "tmp",
                            "id": "legacy_tmp",
                            "category": "preview_cache",
                            "path": "E:/work/users/u1/sessions/s1/map_previews/preview.png",
                            "file_count": 1,
                            "size_bytes": 12,
                            "safe_to_delete": True,
                            "reason": "old preview",
                        }
                    ],
                    "total_candidates": 1,
                    "total_size_bytes": 12,
                },
                cleanup_storage_candidates=lambda workdir, candidate_ids, confirm_text: {
                    "schema_version": "storage-cleanup-delete/v1",
                    "deleted": [
                        {
                            "candidate_id": candidate_id,
                            "path": f"E:/work/users/u1/sessions/s1/map_previews/{candidate_id}.png",
                            "files": 1,
                            "bytes": 12,
                        }
                        for candidate_id in candidate_ids
                    ],
                    "errors": [f"E:/work/secret/{confirm_text}.log", f"/tmp/work/secret/{confirm_text}.log"],
                    "deleted_count": len(candidate_ids),
                    "freed_bytes": 12 * len(candidate_ids),
                },
                agent_runtime_diagnostics=lambda: {
                    "available": True,
                    "enabled": True,
                    "mode": "shadow",
                    "context": {
                        "current_user_id": "u_admin",
                        "current_session_id": "s_admin",
                        "workspace_dir": "E:/secret/workspace",
                    },
                    "trace_events": [
                        {
                            "event": "context_merge",
                            "runtime_report": "/tmp/secret/runtime-report.json",
                            "payload": {
                                "prompt": "full user prompt should not leak",
                                "token": "secret-token",
                                "cookie": "secret-cookie",
                                "path": "E:/secret/file.env",
                                "ok": True,
                            },
                        }
                    ],
                },
                agent_runtime_rag_readiness=lambda: {
                    "schema_version": "agent-runtime-rag-readiness/v1",
                    "mode": "read_only_no_embedding",
                    "provider": {"credential_configured": True, "api_key": "secret-key"},
                    "vector_store": {"configured": True, "store_filename": "vectors.json", "path": "E:/secret/vectors.json", "snapshot": "/tmp/secret/vectors.json"},
                    "operations": {"embedding_calls_performed": 0, "rebuild_available": False},
                },
                agent_runtime_exposure=lambda: {
                    "schema_version": "agent-runtime-exposure-policy/v1",
                    "environment": "staging",
                    "requested_percent": 5,
                    "eligible_for_user_exposure": True,
                    "deterministic_smoke": {"report_filename": "active_smoke.json", "path": "E:/secret/smoke.json", "report": "/tmp/secret/smoke.json"},
                },
                workdir="E:/work",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        self.assertEqual(client.get("/api/admin/dataset-availability").status_code, 403)
        self.assertEqual(client.get("/api/admin/agent-runtime/diagnostics").status_code, 403)
        listed = client.get("/api/admin/dataset-availability?include_inactive=true", headers={"x-admin-token": "secret"}).json()
        self.assertEqual(listed["items"][0]["product_id"], "p1")
        diagnostics = client.get("/api/admin/agent-runtime/diagnostics", headers={"x-admin-token": "secret"}).json()
        self.assertTrue(diagnostics["available"])
        self.assertEqual(diagnostics["mode"], "shadow")
        self.assertNotIn("workspace_dir", diagnostics["context"])
        self.assertNotIn("prompt", str(diagnostics))
        self.assertNotIn("secret-token", str(diagnostics))
        self.assertNotIn("secret-cookie", str(diagnostics))
        self.assertNotIn("E:/secret", str(diagnostics))
        self.assertNotIn("/tmp/secret", str(diagnostics))
        rag_readiness = client.get("/api/admin/agent-runtime/rag-readiness", headers={"x-admin-token": "secret"}).json()
        self.assertEqual(rag_readiness["mode"], "read_only_no_embedding")
        self.assertEqual(rag_readiness["operations"]["embedding_calls_performed"], 0)
        self.assertNotIn("api_key", str(rag_readiness))
        self.assertNotIn("E:/secret", str(rag_readiness))
        self.assertNotIn("/tmp/secret", str(rag_readiness))
        exposure = client.get("/api/admin/agent-runtime/exposure", headers={"x-admin-token": "secret"}).json()
        self.assertEqual(exposure["environment"], "staging")
        self.assertEqual(exposure["requested_percent"], 5)
        self.assertNotIn("E:/secret", str(exposure))
        self.assertNotIn("/tmp/secret", str(exposure))
        upserted = client.post("/api/admin/dataset-availability", headers={"x-admin-token": "secret"}, json={"product_id": "p2"}).json()
        self.assertEqual(upserted["item"]["product_id"], "p2")
        status = client.post(
            "/api/admin/dataset-availability/p2/status",
            headers={"x-admin-token": "secret"},
            json={"status": "disabled", "actor": "reviewer", "summary": "pause"},
        ).json()
        self.assertEqual(status["item"]["status"], "disabled")
        scanned = client.post(
            "/api/admin/dataset-availability/p2/scan",
            headers={"x-admin-token": "secret"},
            json={"scan_method": "catalog", "actor": "robot", "summary": "scan"},
        ).json()
        self.assertEqual(scanned["item"]["scan_method"], "catalog")
        self.assertEqual(client.get("/api/admin/compat-usage/report", headers={"x-admin-token": "secret"}).json()["report"], "compat")
        self.assertEqual(client.get("/api/admin/trial-monitoring/report", headers={"x-admin-token": "secret"}).json()["report"], "trial")
        reset = client.post(
            "/api/admin/system-reset",
            headers={"x-admin-token": "secret"},
            json={"mode": "keep_accounts", "confirm_text": "RESET"},
        ).json()
        self.assertEqual(reset["mode"], "keep_accounts")
        self.assertEqual(reset["deleted"]["files"], 2)
        self.assertEqual(reset["preserved"]["accounts"], 1)
        self.assertEqual(reset["capability_cleanup"]["index_dirs"], ["vector_index"])
        self.assertNotIn("commercial_service", reset)
        self.assertNotIn("workdir", reset)
        self.assertNotIn("root", reset)
        self.assertNotIn("confirm_text", reset)
        self.assertNotIn("debug_path", reset)
        self.assertNotIn("E:/work", str(reset))
        self.assertNotIn("/tmp/work", str(reset))
        self.assertNotIn("delete-error.log", str(reset))
        self.assertEqual(commercial["service"], {"service": "new"})
        storage_scan = client.get("/api/admin/storage-cleanup/scan", headers={"x-admin-token": "secret"}).json()
        self.assertEqual(storage_scan["candidates"][0]["candidate_id"], "tmp")
        self.assertEqual(storage_scan["candidates"][0]["label"], "preview.png")
        self.assertNotIn("root", storage_scan)
        self.assertNotIn("workdir", storage_scan)
        self.assertNotIn("path", storage_scan["candidates"][0])
        self.assertNotIn("E:/work", str(storage_scan))
        cleanup = client.post(
            "/api/admin/storage-cleanup/delete",
            headers={"x-admin-token": "secret"},
            json={"candidate_ids": ["tmp"], "confirm_text": "DELETE"},
        ).json()
        self.assertEqual(cleanup["deleted"][0]["candidate_id"], "tmp")
        self.assertEqual(cleanup["deleted"][0]["label"], "tmp.png")
        self.assertEqual(cleanup["deleted_count"], 1)
        self.assertNotIn("path", cleanup["deleted"][0])
        self.assertNotIn("E:/work", str(cleanup))
        self.assertNotIn("/tmp/work", str(cleanup))
        self.assertNotIn("DELETE.log", str(cleanup))

        self.assertIn(("list_profiles", True), calls)
        self.assertIn(("set_status", ("p2", "disabled", "reviewer", "pause")), calls)
        self.assertIn(("clear_workspace", True), calls)
        self.assertIn(("ensure_dirs", True), calls)

    def test_chat_actions_routes_cover_ask_stream_and_confirm(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeService:
            current_session_id = "s1"
            manager = SimpleNamespace(workdir=".")

            def apply_frontend_context(self, context: dict) -> None:
                calls.append(("context", context))

            def ask(self, prompt: str, **kwargs) -> dict:
                calls.append(("ask", (prompt, kwargs)))
                callback = kwargs.get("stream_callback")
                if callback:
                    callback("delta")
                return {"reply": f"reply:{prompt}", "messages": [{"role": "assistant", "content": prompt}]}

        class FakeEventStore:
            def append(self, **kwargs) -> dict:
                calls.append(("event_store_append", kwargs.get("status")))
                return kwargs

        class FakeHub:
            def __init__(self) -> None:
                self.channel: Queue = Queue()

            def subscribe(self, *, user_id: str, session_id: str) -> Queue:
                calls.append(("subscribe", (user_id, session_id)))
                return self.channel

            def unsubscribe(self, channel: Queue) -> None:
                calls.append(("unsubscribe", True))

            def publish_model_token(self, **kwargs) -> dict:
                event = {"kind": "model_token", "task_id": kwargs["task_id"], "delta": kwargs["delta"]}
                self.channel.put(event)
                return event

            def publish(self, **kwargs) -> dict:
                event = {"kind": kwargs["kind"], "task_id": kwargs["task_id"], "status": kwargs.get("status", "")}
                self.channel.put(event)
                return event

        service = FakeService()
        app = FastAPI()
        app.include_router(
            create_chat_actions_router(
                scoped_workspace_service=lambda user_id, session_id="": service,
                require_request_user_if_present=lambda request, user_id: user_id or "u1",
                attach_result_panel=lambda service, user_id, response: {**response, "panel": user_id},
                attach_chat_state=lambda service, response: {**response, "state": True},
                build_chat_response=lambda service, user_prompt, result, meta_keys=(): {"reply": result.get("reply", ""), "messages": []},
                start_chat_task=lambda task_id, user_id="", session_id="": calls.append(("start", task_id)),
                finish_chat_task=lambda task_id: calls.append(("finish", task_id)),
                is_commercial_download_status_prompt=lambda prompt: "job_" in prompt,
                download_requires_login_result=lambda prompt: {"reply": "login required"},
                format_commercial_download_status=lambda prompt, user_id: {"reply": "job status"},
                attach_download_tool_result=lambda payload: {**payload, "tool_result": True},
                realtime_event_hub=FakeHub(),
                task_event_store_for_service=lambda service: FakeEventStore(),
                stream_task_update=lambda response: {"status": "succeeded"},
                sse_event=lambda event: f"event: {event['kind']}\ndata: ok\n\n",
                task_id_factory=lambda: "chat_fixed",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        asked = client.post("/api/chat/ask", json={"prompt": "hello", "user_id": "u1", "session_id": "s1", "task_id": "t1"}).json()
        self.assertEqual(asked["panel"], "u1")
        self.assertTrue(asked["state"])
        confirmed = client.post(
            "/api/chat/confirm",
            json={"confirmation_id": "c1", "confirmation_prompt": "run it", "user_id": "u1", "session_id": "s1"},
        ).json()
        self.assertTrue(confirmed["state"])
        with client.stream("POST", "/api/chat/stream", json={"prompt": "stream", "user_id": "u1", "session_id": "s1"}) as response:
            body = "".join(response.iter_text())
        self.assertIn("event: model_token", body)
        self.assertIn("event: model_complete", body)

        self.assertIn(("start", "t1"), calls)
        self.assertIn(("finish", "t1"), calls)
        confirm_prompts = [payload[0] for name, payload in calls if name == "ask" and "confirmed_action_id=c1" in payload[0]]
        self.assertEqual(confirm_prompts, ["run it confirmed_action_id=c1"])

    def test_chat_actions_finish_task_when_non_stream_request_fails(self) -> None:
        calls: list[tuple[str, object]] = []

        class FailingService:
            current_session_id = "s1"
            manager = SimpleNamespace(workdir=".")

            def apply_frontend_context(self, context: dict) -> None:
                calls.append(("context", context))

            def ask(self, prompt: str, **kwargs) -> dict:
                calls.append(("ask", (prompt, kwargs)))
                raise RuntimeError("planner failed")

        class FakeHub:
            def publish_model_token(self, **kwargs) -> dict:
                return {}

            def publish(self, **kwargs) -> dict:
                return {}

            def subscribe(self, **kwargs) -> Queue:
                return Queue()

            def unsubscribe(self, channel: Queue) -> None:
                return None

        app = FastAPI()
        app.include_router(
            create_chat_actions_router(
                scoped_workspace_service=lambda user_id, session_id="": FailingService(),
                require_request_user_if_present=lambda request, user_id: user_id or "u1",
                attach_result_panel=lambda service, user_id, response: response,
                attach_chat_state=lambda service, response: response,
                build_chat_response=lambda service, user_prompt, result, meta_keys=(): result,
                start_chat_task=lambda task_id, user_id="", session_id="": calls.append(("start", task_id)),
                finish_chat_task=lambda task_id: calls.append(("finish", task_id)),
                is_commercial_download_status_prompt=lambda prompt: False,
                download_requires_login_result=lambda prompt: {},
                format_commercial_download_status=lambda prompt, user_id: {},
                attach_download_tool_result=lambda payload: payload,
                realtime_event_hub=FakeHub(),
                task_event_store_for_service=lambda service: None,
                stream_task_update=lambda response: {},
                sse_event=lambda event: "",
                task_id_factory=lambda: "chat_fixed",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app, raise_server_exceptions=False)

        asked = client.post("/api/chat/ask", json={"prompt": "hello", "user_id": "u1", "session_id": "s1", "task_id": "ask_fail"})
        confirmed = client.post(
            "/api/chat/confirm",
            json={"confirmation_id": "c1", "confirmation_prompt": "run it", "user_id": "u1", "session_id": "s1", "task_id": "confirm_fail"},
        )

        self.assertEqual(asked.status_code, 500)
        self.assertEqual(confirmed.status_code, 500)
        self.assertIn(("start", "ask_fail"), calls)
        self.assertIn(("finish", "ask_fail"), calls)
        self.assertIn(("start", "confirm_fail"), calls)
        self.assertIn(("finish", "confirm_fail"), calls)

    def test_chat_actions_do_not_persist_raw_download_job_meta(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeService:
            current_session_id = "s1"

            def apply_frontend_context(self, context: dict) -> None:
                calls.append(("context", context))

        class FakeHub:
            def publish_model_token(self, **kwargs) -> dict:
                return {}

            def publish(self, **kwargs) -> dict:
                return {}

            def subscribe(self, **kwargs) -> Queue:
                return Queue()

            def unsubscribe(self, channel: Queue) -> None:
                return None

        def build_response(service, user_prompt, result, meta_keys=()):
            calls.append(("meta_keys", tuple(meta_keys)))
            calls.append(("result", result))
            return {"reply": result.get("reply", ""), "messages": []}

        app = FastAPI()
        app.include_router(
            create_chat_actions_router(
                scoped_workspace_service=lambda user_id, session_id="": FakeService(),
                require_request_user_if_present=lambda request, user_id: user_id or "u1",
                attach_result_panel=lambda service, user_id, response: response,
                attach_chat_state=lambda service, response: response,
                build_chat_response=build_response,
                start_chat_task=lambda task_id, user_id="", session_id="": None,
                finish_chat_task=lambda task_id: None,
                is_commercial_download_status_prompt=lambda prompt: True,
                download_requires_login_result=lambda prompt: {},
                format_commercial_download_status=lambda prompt, user_id: {
                    "reply": "job status",
                    "job": {"job_id": "job_1", "output_path": r"E:\agent\secret.tif"},
                    "tile_job": {"status_path": r"E:\agent\tile.json"},
                    "scene_job": {"status_path": r"E:\agent\scene.json"},
                },
                attach_download_tool_result=lambda payload: {**payload, "presentation_result": {"status": "succeeded"}, "execution_summary": {"status": "succeeded"}},
                realtime_event_hub=FakeHub(),
                task_event_store_for_service=lambda service: None,
                stream_task_update=lambda response: {},
                sse_event=lambda event: "",
                task_id_factory=lambda: "chat_fixed",
                guard=lambda fn: fn(),
            )
        )

        response = TestClient(app).post("/api/chat/ask", json={"prompt": "job_1 状态", "user_id": "u1", "session_id": "s1"})

        self.assertEqual(response.status_code, 200)
        meta_keys = next(payload for name, payload in calls if name == "meta_keys")
        self.assertNotIn("job", meta_keys)
        self.assertNotIn("tile_job", meta_keys)
        self.assertNotIn("scene_job", meta_keys)

    def test_chat_state_routes_cover_sessions_events_models_and_cancel(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeManager:
            workdir = "."

        class FakeService:
            current_session_id = "s1"
            manager = FakeManager()

            def set_request_context(self, user_id: str, *, create_if_missing: bool = False) -> None:
                calls.append(("set_context", (user_id, create_if_missing)))

            def list_sessions(self) -> list[dict]:
                calls.append(("list_sessions", True))
                return [{"session_id": "s1", "title": "Main"}]

            def current_messages(self) -> list[dict]:
                calls.append(("messages", True))
                return [{"role": "assistant", "content": "ready"}]

            def create_new_session(self, title: str | None = None) -> str:
                calls.append(("create", title))
                self.current_session_id = "s2"
                return "s2"

            def switch_session(self, session_id: str) -> None:
                calls.append(("switch", session_id))
                self.current_session_id = session_id

            def rename_session(self, session_id: str, title: str) -> None:
                calls.append(("rename", (session_id, title)))

            def delete_session(self, session_id: str) -> str:
                calls.append(("delete", session_id))
                return "s1"

            def set_interaction_mode(self, mode: str, session_id: str) -> str:
                calls.append(("mode", (mode, session_id)))
                return mode

            def clear_current_chat(self) -> None:
                calls.append(("clear", True))

            def edit_user_message_and_retry(self, message_id: str, content: str) -> dict:
                calls.append(("retry", (message_id, content)))
                return {"ok": True}

            def chat_model_state(self, session_id: str) -> dict:
                calls.append(("model_state", session_id))
                return {
                    "session_id": session_id,
                    "route_mode": "manual",
                    "selected_model": "gpt-test",
                    "active_model": "gpt-test",
                    "models": [{"id": "gpt-test", "capability": "text", "token": "secret"}],
                    "provider_health": {"status": "ok", "api_key": "sk-secret"},
                    "debug_path": "E:/secret/model-state.json",
                }

            def select_chat_model(self, model: str, session_id: str) -> dict:
                calls.append(("select_model", (model, session_id)))
                return {
                    "session_id": session_id,
                    "route_mode": "manual",
                    "selected_model": model,
                    "active_model": model,
                    "models": [{"id": model, "capability": "text", "storage_state_path": "E:/secret/state.json"}],
                    "token": "secret",
                    "debug_path": "E:/secret/model-select.json",
                }

        service = FakeService()

        def auth_user(request: Request, user_id: str) -> str:
            calls.append(("auth", user_id))
            return user_id or "u1"

        app = FastAPI()
        app.include_router(
            create_chat_state_router(
                scoped_workspace_service=lambda user_id, session_id="": service,
                require_request_user_if_present=auth_user,
                decorate_response_artifacts=lambda service, user_id, response: calls.append(("decorate", sorted(response.keys()))) or {**response, "decorated": user_id},
                public_task_events=lambda service, user_id, session_id, after_version=0, limit=200: [{"version": 1, "kind": "task_status"}],
                sse_event=lambda event: f"data: {event['kind']}\n\n",
                realtime_event_hub=None,
                cancel_chat_task=lambda task_id, user_id="", reason="": {"cancelled": task_id, "reason": reason},
                workspace_services=lambda: [service],
                durable_job_store_factory=lambda path: None,
                cancel_session_jobs=lambda user_id, session_id, reason="": [{"job_id": "job1"}],
                hard_delete_session_jobs=lambda user_id, session_id: [{"job_id": "job1"}],
                compat_usage_store=lambda: type("Store", (), {"record_effective_request": lambda self, **kwargs: calls.append(("compat", kwargs))})(),
                compat_actor_type=lambda request: "automated_test",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        self.assertEqual(client.get("/api/chat/messages?user_id=u1").json()["messages"][0]["content"], "ready")
        self.assertEqual(client.get("/api/chat/sessions?user_id=u1").json()["current_session_id"], "s1")
        created = client.post("/api/chat/sessions", json={"user_id": "u1", "title": "New"}).json()
        switched = client.post("/api/chat/sessions/switch", json={"user_id": "u1", "session_id": "s1"}).json()
        renamed = client.post("/api/chat/sessions/rename", json={"user_id": "u1", "session_id": "s1", "title": "Renamed"})
        mode_changed = client.post("/api/chat/sessions/mode", json={"user_id": "u1", "session_id": "s1", "interaction_mode": "tool_enabled"}).json()
        cleared = client.post("/api/chat/sessions/clear", json={"user_id": "u1", "session_id": "s1"}).json()
        retried = client.post("/api/chat/retry", json={"user_id": "u1", "session_id": "s1", "message_id": 1, "content": "again"}).json()
        self.assertEqual(created["session_id"], "s2")
        self.assertEqual(switched["current_session_id"], "s1")
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(mode_changed["interaction_mode"], "tool_enabled")
        self.assertEqual(cleared["messages"][0]["content"], "ready")
        self.assertEqual(retried["ok"], True)
        for payload in (created, switched, renamed.json(), mode_changed, cleared, retried):
            self.assertEqual(payload["decorated"], "u1")
        model_state = client.get("/api/chat/models?user_id=u1&session_id=s1").json()
        selected_model = client.post("/api/chat/models/select", json={"user_id": "u1", "session_id": "s1", "model": "gpt-5"}).json()
        model_payload_text = json.dumps({"model_state": model_state, "selected_model": selected_model}, ensure_ascii=False)
        self.assertEqual(model_state["selected_model"], "gpt-test")
        self.assertEqual(model_state["session_id"], "s1")
        self.assertEqual(selected_model["selected_model"], "gpt-5")
        self.assertEqual(selected_model["session_id"], "s1")
        self.assertNotIn("token", model_payload_text)
        self.assertNotIn("api_key", model_payload_text)
        self.assertNotIn("provider_health", model_payload_text)
        self.assertNotIn("storage_state_path", model_payload_text)
        self.assertNotIn("debug_path", model_payload_text)
        self.assertNotIn("E:/secret", model_payload_text)
        self.assertEqual(client.get("/api/chat/events/replay?user_id=u1&session_id=s1").json()["events"][0]["kind"], "task_status")
        self.assertEqual(client.post("/api/chat/cancel", json={"user_id": "u1", "task_id": "t1", "reason": "stop"}).json()["cancelled"], "t1")
        deleted = client.post("/api/chat/sessions/delete", json={"user_id": "u1", "session_id": "s1"}).json()
        self.assertEqual(deleted["hard_deleted_downloads"], [{"job_id": "job1"}])

        self.assertIn(("retry", (1, "again")), calls)
        self.assertIn(("rename", ("s1", "Renamed")), calls)
        self.assertIn(("select_model", ("gpt-5", "s1")), calls)
        self.assertIn(("delete", "s1"), calls)
        compat_calls = [payload for name, payload in calls if name == "compat"]
        self.assertIn({"source": "POST /api/chat/sessions/delete", "actor_type": "automated_test"}, compat_calls)
        self.assertNotIn({"source": "POST /api/chat/ask", "actor_type": "automated_test"}, compat_calls)

    def test_admin_capabilities_routes_require_admin_and_use_store(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeUpload:
            filename = "uploaded.md"

        class FakeStore:
            def __init__(self) -> None:
                self.items: dict[str, dict] = {}
                self.events = [{"event_id": "evt1"}]

            def list_resources(self, resource_type: str, *, include_disabled: bool = False) -> list[dict]:
                calls.append(("list", (resource_type, include_disabled)))
                return list(self.items.values())

            def upsert_knowledge(self, body: dict) -> dict:
                calls.append(("upsert_knowledge", body.get("knowledge_id")))
                item = dict(body)
                self.items[item["knowledge_id"]] = item
                return item

            def set_status(self, resource_type: str, item_id: str, status: str, *, actor: str = "", summary: str = "") -> dict:
                calls.append(("status", (resource_type, item_id, status, actor, summary)))
                item = dict(self.items[item_id])
                item["status"] = status
                self.items[item_id] = item
                return item

            def rollback(self, resource_type: str, item_id: str, version: str, *, actor: str = "", summary: str = "") -> dict:
                calls.append(("rollback", (resource_type, item_id, version, actor, summary)))
                return {"knowledge_id": item_id, "version": version}

            def list_audit_events(self, *, limit: int = 100) -> list[dict]:
                calls.append(("audit_events", limit))
                return self.events[:limit]

            def retrieve_knowledge(self, query: str, *, limit: int = 5, language: str = "", scope: str = "") -> list[dict]:
                calls.append(("retrieve", (query, limit, language, scope)))
                return [{"knowledge_id": "doc1", "title": query}]

        store = FakeStore()

        def require_admin(request: Request) -> None:
            calls.append(("admin", request.headers.get("x-admin-token")))
            if request.headers.get("x-admin-token") != "secret":
                raise PermissionError("admin token required")

        async def extract(upload) -> tuple[str, str]:
            calls.append(("extract", getattr(upload, "filename", "")))
            return ("uploaded content", "uploaded.md")

        app = FastAPI()
        app.include_router(
            create_capabilities_router(
                capability_store=lambda: store,
                require_capability_admin=require_admin,
                extract_capability_document_text=extract,
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        denied = client.get("/api/admin/capabilities/knowledge")
        self.assertEqual(denied.status_code, 403)
        created = client.post(
            "/api/admin/capabilities/knowledge",
            headers={"x-admin-token": "secret"},
            json={"knowledge_id": "doc1", "title": "Doc", "content": "content"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        listed = client.get("/api/admin/capabilities/knowledge?include_disabled=true", headers={"x-admin-token": "secret"})
        self.assertEqual(listed.json()["items"][0]["knowledge_id"], "doc1")
        status = client.post(
            "/api/admin/capabilities/knowledge/doc1/status",
            headers={"x-admin-token": "secret"},
            json={"status": "active", "actor": "reviewer", "summary": "approved"},
        )
        self.assertEqual(status.json()["item"]["status"], "active")
        rollback = client.post(
            "/api/admin/capabilities/knowledge/doc1/rollback",
            headers={"x-admin-token": "secret"},
            json={"version": "v1", "actor": "reviewer"},
        )
        self.assertEqual(rollback.json()["item"]["version"], "v1")
        upload = client.post(
            "/api/admin/capabilities/knowledge/upload",
            headers={"x-admin-token": "secret"},
            data={"knowledge_id": "uploaded", "title": "Uploaded"},
            files={"file": ("uploaded.md", b"uploaded content", "text/markdown")},
        )
        self.assertEqual(upload.json()["item"]["knowledge_id"], "uploaded")
        audit = client.get("/api/admin/capabilities/audit/events?limit=1", headers={"x-admin-token": "secret"})
        self.assertEqual(audit.json()["events"], [{"event_id": "evt1"}])
        searched = client.get("/api/admin/capabilities/knowledge/search/test?query=soil", headers={"x-admin-token": "secret"})
        self.assertEqual(searched.json()["items"][0]["title"], "soil")

        self.assertIn(("list", ("knowledge", True)), calls)
        self.assertIn(("status", ("knowledge", "doc1", "active", "reviewer", "approved")), calls)
        self.assertIn(("extract", "uploaded.md"), calls)

    def test_system_routes_expose_status_health_ops_and_tianditu_config(self) -> None:
        app = FastAPI()
        app.include_router(
            create_system_router(
                local_library_root=lambda: "E:/library",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        status = client.get("/api/status").json()
        self.assertTrue(status["ok"])
        self.assertEqual(status["service"], "GIS Agent Web API")
        self.assertTrue(status["local_library"]["enabled"])
        self.assertNotIn("root", status["local_library"])
        self.assertNotIn("E:/library", str(status))
        self.assertIn("llm_status", status)
        self.assertIn("status", client.get("/api/llm/health").json())
        self.assertIn("ok", client.get("/api/ops/config").json())
        self.assertIn("enabled", client.get("/api/tianditu/config").json())

    def test_auth_routes_use_commercial_service_cookies_and_audit(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeCommercialService:
            def register_user(self, email: str, password: str, *, plan: str) -> dict:
                calls.append(("register_user", (email, password, plan)))
                return {"user_id": "u_1", "email": email}

            def authenticate_user(self, email: str, password: str) -> dict:
                calls.append(("authenticate_user", (email, password)))
                return {
                    "session_id": "s_1",
                    "session_token": "t_1",
                    "expires_at": "2099-01-01",
                    "user": {
                        "user_id": "u_1",
                        "email": email,
                        "plan": "basic",
                        "password_hash": "secret-password-hash",
                        "storage_state_path": "E:/secret/state.json",
                        "debug_note": "/tmp/secret/auth-debug.log",
                    },
                }

            def validate_session(self, session_id: str, session_token: str) -> dict:
                calls.append(("validate_session", (session_id, session_token)))
                return {
                    "valid": True,
                    "session_id": session_id,
                    "session_token": session_token,
                    "expires_at": "2099-01-01",
                    "user": {
                        "user_id": "u_1",
                        "email": "a@example.com",
                        "plan": "pro",
                        "plan_expires_at": "2099-01-01",
                        "platform_monthly_quota": 30,
                        "platform_monthly_used": 2,
                        "own_daily_quota": 100,
                        "status": "active",
                        "password_hash": "secret-password-hash",
                        "storage_state_path": "E:/secret/state.json",
                    },
                    "debug_path": "E:/secret/auth-debug.json",
                }

        def set_cookies(response, session: dict) -> None:
            calls.append(("set_cookies", session["session_id"]))
            response.set_cookie("sid", session["session_id"])

        def clear_cookies(response) -> None:
            calls.append(("clear_cookies", True))
            response.delete_cookie("sid")

        def request_session(request: Request) -> tuple[str, str]:
            calls.append(("request_session", request.url.path))
            if request.headers.get("x-empty-session") == "1":
                return ("", "")
            return ("s_1", "t_1")

        def optional_session(service, *, session_id: str, session_token: str) -> dict:
            calls.append(("optional_session", (session_id, session_token)))
            if not session_id or not session_token:
                return {"authenticated": False, "user": None}
            return {"authenticated": True, "user": {"user_id": "u_1"}}

        def audit(request: Request, **kwargs):
            calls.append(("audit", kwargs))

        app = FastAPI()
        app.include_router(
            create_auth_router(
                commercial_service=lambda: FakeCommercialService(),
                set_session_cookies=set_cookies,
                clear_session_cookies=clear_cookies,
                request_session=request_session,
                optional_authenticated_session=optional_session,
                audit=audit,
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        registered = client.post("/api/auth/register", json={"email": "a@example.com", "password": "password1"}).json()
        logged_in = client.post("/api/auth/login", json={"email": "a@example.com", "password": "password1"}).json()
        self.assertEqual(registered["user"]["user_id"], "u_1")
        self.assertEqual(logged_in["expires_at"], "2099-01-01")
        auth_text = json.dumps({"registered": registered, "logged_in": logged_in}, ensure_ascii=False)
        self.assertNotIn("session_token", auth_text)
        self.assertNotIn("password_hash", auth_text)
        self.assertNotIn("storage_state_path", auth_text)
        self.assertNotIn("debug_note", auth_text)
        self.assertNotIn("E:/secret", auth_text)
        self.assertNotIn("/tmp/secret", auth_text)
        validated = client.post("/api/auth/validate", json={"session_id": "s_1", "session_token": "t_1"}).json()
        self.assertTrue(validated["valid"])
        self.assertEqual(validated["session_id"], "s_1")
        self.assertEqual(validated["user"]["user_id"], "u_1")
        self.assertEqual(validated["user"]["email"], "a@example.com")
        self.assertEqual(validated["user"]["plan"], "pro")
        self.assertEqual(validated["user"]["plan_expires_at"], "2099-01-01")
        self.assertEqual(validated["user"]["platform_monthly_quota"], 30)
        self.assertEqual(validated["user"]["platform_monthly_used"], 2)
        self.assertEqual(validated["user"]["own_daily_quota"], 100)
        self.assertEqual(validated["user"]["status"], "active")
        validated_text = json.dumps(validated, ensure_ascii=False)
        self.assertNotIn("session_token", validated_text)
        self.assertNotIn("password_hash", validated_text)
        self.assertNotIn("storage_state_path", validated_text)
        self.assertNotIn("debug_path", validated_text)
        self.assertNotIn("E:/secret", validated_text)
        self.assertTrue(client.get("/api/auth/me").json()["authenticated"])
        self.assertEqual(client.get("/api/auth/me", headers={"x-empty-session": "1"}).json(), {"authenticated": False, "user": None})
        self.assertTrue(client.post("/api/auth/logout").json()["ok"])

        self.assertIn(("register_user", ("a@example.com", "password1", "basic")), calls)
        self.assertIn(("set_cookies", "s_1"), calls)
        self.assertIn(("clear_cookies", True), calls)
        audit_actions = [payload["action"] for name, payload in calls if name == "audit"]
        self.assertEqual(audit_actions, ["auth.register", "auth.login", "auth.logout"])

    def test_workspace_routes_use_scoped_service_and_artifact_policy(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeManager:
            workdir = "."
            upload_dir = Path(tempfile.gettempdir()) / "route_module_uploads"

            def _unique_storage_name(self, filename: str) -> str:
                return f"test_{filename}"

            def list_datasets(self) -> list[dict]:
                calls.append(("list_datasets", True))
                return [{"name": "points", "type": "table"}]

            def assert_artifact_access(self, user_id: str, session_id: str, artifact_id: str) -> dict:
                calls.append(("assert_artifact_access", (user_id, session_id, artifact_id)))
                return {"artifact_id": artifact_id, "path": "result.csv", "title": "result.csv", "type": "csv"}

            def delete_result_file(self, *, artifact_id: str = "", path: str = "") -> dict:
                calls.append(("delete_result_file", (artifact_id, path)))
                return {"ok": True, "path": "result.csv", "deleted_files": ["result.csv"], "deleted_artifacts": [artifact_id], "deleted_datasets": []}

        class FakeService:
            current_session_id = "s1"

            def __init__(self) -> None:
                self.manager = FakeManager()

            def upload_saved_files_batch(self, payload: list[tuple[Path, str]]) -> list[str]:
                calls.append(("upload_saved_files_batch", [original for _path, original in payload]))
                return ["上传成功：/tmp/secret/upload.csv，源文件 E:/secret/source.csv"]

            def export_results(self, *, mode: str) -> dict:
                calls.append(("export_results", mode))
                return {"artifact_id": "export_1", "zip_path": "export.zip", "file_count": 2}

        def scoped_service(user_id: str, session_id: str = "") -> FakeService:
            calls.append(("scoped_service", (user_id, session_id)))
            return FakeService()

        def auth_user(request: Request, user_id: str) -> str:
            calls.append(("auth_user", user_id))
            return user_id or "u1"

        def decorate_dashboard(service, *, user_id: str = "") -> dict:
            calls.append(("decorate_dashboard", user_id))
            return {"summary": {}, "artifacts": []}

        def workspace_mentions(datasets: list[dict]) -> dict:
            return {"items": [{"label": datasets[0]["name"]}], "count": len(datasets)}

        def public_artifact(service, artifact_id: str, user_id: str = "", session_id: str = "") -> dict:
            calls.append(("public_artifact", (artifact_id, user_id, session_id)))
            return {"artifact_id": artifact_id, "filename": "result.csv"}

        app = FastAPI()
        app.include_router(
            create_workspace_router(
                scoped_workspace_service=scoped_service,
                require_request_user_if_present=auth_user,
                decorate_dashboard=decorate_dashboard,
                build_workspace_mentions=workspace_mentions,
                local_library_items=lambda: [{"name": "lib"}],
                artifact_download_url=lambda artifact_id, user_id="", session_id="": f"/api/artifacts/{artifact_id}/download",
                public_artifact_or_error=public_artifact,
                audit=lambda request, **kwargs: calls.append(("audit", kwargs)),
                guard=lambda fn: fn(),
                max_upload_files=2,
                max_upload_bytes=1024,
            )
        )
        client = TestClient(app)

        self.assertEqual(client.get("/api/workspace/dashboard?user_id=u1&session_id=s1").json()["local_library"], [{"name": "lib"}])
        self.assertEqual(client.get("/api/workspace/mentions?user_id=u1&session_id=s1").json()["count"], 1)
        uploaded = client.post(
            "/api/files/upload",
            data={"user_id": "u1", "session_id": "s1"},
            files=[("files", ("upload.csv", b"x,y\n1,2\n", "text/csv"))],
        ).json()
        uploaded_text = json.dumps(uploaded, ensure_ascii=False)
        self.assertEqual(uploaded["count"], 1)
        self.assertNotIn("/tmp/secret", uploaded_text)
        self.assertNotIn("E:/secret", uploaded_text)
        export_payload = client.post("/api/workspace/export", json={"user_id": "u1", "session_id": "s1", "mode": "all"}).json()
        self.assertEqual(export_payload["download_url"], "/api/artifacts/export_1/download")
        self.assertEqual(export_payload["artifact_id"], "export_1")
        self.assertNotIn("zip_path", export_payload)
        self.assertNotIn("export_dir", export_payload)
        self.assertNotIn("files", export_payload)
        self.assertEqual(client.get("/api/artifacts/a1?user_id=u1&session_id=s1").json()["filename"], "result.csv")
        self.assertEqual(client.get("/api/files/artifact?path=old.csv").status_code, 410)
        missing_path = client.get("/api/files/artifact")
        self.assertEqual(missing_path.status_code, 410)
        self.assertIn("/api/artifacts/{artifact_id}/download", missing_path.json()["detail"])
        self.assertEqual(client.post("/api/workspace/artifacts/delete", json={"user_id": "u1", "session_id": "s1", "path": "result.csv"}).status_code, 400)
        deleted = client.post("/api/workspace/artifacts/delete", json={"user_id": "u1", "session_id": "s1", "artifact_id": "a1"}).json()
        self.assertEqual(deleted["deleted_artifacts"], ["a1"])
        self.assertEqual(deleted["artifact_id"], "a1")
        self.assertNotIn("path", deleted)
        self.assertNotIn("deleted_files", deleted)

        self.assertIn(("decorate_dashboard", "u1"), calls)
        self.assertIn(("public_artifact", ("a1", "u1", "s1")), calls)
        self.assertIn(("assert_artifact_access", ("u1", "s1", "a1")), calls)
        self.assertIn(("delete_result_file", ("a1", "")), calls)

    def test_workspace_mentions_do_not_expose_raw_paths(self) -> None:
        from api_server import _build_workspace_mentions

        mentions = _build_workspace_mentions(
            [
                {
                    "id": "dataset_1",
                    "name": "soil_points",
                    "type": "table",
                    "path": r"E:\agent\workspace\users\u1\sessions\s1\uploads\soil_points.csv",
                    "filename": "soil_points.csv",
                    "meta": {"columns": ["lon", "lat"], "rows": 2},
                }
            ]
        )

        item = mentions["items"][0]
        self.assertEqual(item["filename"], "soil_points.csv")
        self.assertEqual(item["mention"], "@{soil_points}")
        self.assertNotIn("path", item)
        self.assertNotIn("E:\\agent", str(item))

    def test_map_routes_handle_empty_context_and_require_refresh_target(self) -> None:
        calls: list[tuple[str, object]] = []

        def auth_user(request: Request, user_id: str) -> str:
            calls.append(("auth_user", user_id))
            return user_id or "u1"

        app = FastAPI()
        app.include_router(
            create_map_router(
                scoped_workspace_service=lambda user_id, session_id="": object(),
                require_request_user_if_present=auth_user,
                load_station_collection=lambda user_id="": {"stations": [], "count": 0},
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        self.assertEqual(client.get("/api/map/layers").json(), {"layers": []})
        self.assertEqual(client.get("/api/map/stations?user_id=u1").json()["count"], 0)
        self.assertEqual(client.post("/api/map/layers/refresh", json={"user_id": "u1"}).status_code, 400)
        self.assertIn(("auth_user", "u1"), calls)

    def test_map_routes_use_layer_service_for_workspace_layers_and_artifact_refresh(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeManager:
            def assert_artifact_access(self, user_id: str, session_id: str, artifact_id: str) -> dict:
                calls.append(("assert_artifact_access", (user_id, session_id, artifact_id)))
                return {"artifact_id": artifact_id}

        class FakeService:
            current_session_id = "current_s"

            def __init__(self) -> None:
                self.manager = FakeManager()

        class FakeMapLayerService:
            def __init__(self, service: FakeService) -> None:
                calls.append(("layer_service", service.current_session_id))
                self.service = service

            def workspace_layers(self, *, user_id: str, session_id: str) -> dict:
                calls.append(("workspace_layers", (user_id, session_id)))
                return {"layers": [{"id": "layer1"}], "diagnostics": []}

            def refresh_artifact(self, artifact_id: str, *, user_id: str, session_id: str) -> dict:
                calls.append(("refresh_artifact", (artifact_id, user_id, session_id)))
                return {"artifact_id": artifact_id, "map_ready": True}

        def scoped_service(user_id: str, session_id: str = "") -> FakeService:
            calls.append(("scoped_service", (user_id, session_id)))
            return FakeService()

        def auth_user(request: Request, user_id: str) -> str:
            calls.append(("auth_user", user_id))
            return f"authorized_{user_id}"

        app = FastAPI()
        app.include_router(
            create_map_router(
                scoped_workspace_service=scoped_service,
                require_request_user_if_present=auth_user,
                load_station_collection=lambda user_id="": {},
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        with mock.patch("api.routes.map.MapLayerService", FakeMapLayerService):
            layers = client.get("/api/map/layers?user_id=u1&session_id=s1").json()
            refreshed = client.post(
                "/api/map/layers/refresh",
                json={"user_id": "u1", "session_id": "s1", "artifact_id": "a1"},
            ).json()

        self.assertEqual(layers["layers"], [{"id": "layer1"}])
        self.assertEqual(refreshed, {"artifact_id": "a1", "map_ready": True})
        self.assertIn(("auth_user", "u1"), calls)
        self.assertIn(("scoped_service", ("authorized_u1", "s1")), calls)
        self.assertIn(("workspace_layers", ("authorized_u1", "s1")), calls)
        self.assertIn(("assert_artifact_access", ("authorized_u1", "s1", "a1")), calls)
        self.assertIn(("refresh_artifact", ("a1", "authorized_u1", "s1")), calls)

    def test_map_routes_do_not_expose_legacy_path_fields(self) -> None:
        class FakeManager:
            def assert_artifact_access(self, user_id: str, session_id: str, artifact_id: str) -> dict:
                return {"artifact_id": artifact_id}

        class FakeService:
            current_session_id = "current_s"

            def __init__(self) -> None:
                self.manager = FakeManager()

        class FakeMapLayerService:
            def __init__(self, service: FakeService) -> None:
                self.service = service

            def workspace_layers(self, *, user_id: str, session_id: str) -> dict:
                return {
                    "layers": [
                        {
                            "id": "layer1",
                            "name": "Layer 1",
                            "type": "raster",
                            "preview_url": "/api/map/raster-preview?dataset_name=layer1",
                            "meta": {
                                "dataset_name": "layer1",
                                "source_path": r"E:\agent\workspace\users\u1\sessions\s1\outputs\layer1.tif",
                                "download_url": "/api/files/artifact?path=outputs/layer1.tif",
                                "note": "preview cached at /tmp/secret/layer1.png",
                                "nested": {
                                    "preview_path": r"E:\agent\workspace\temp\layer1.png",
                                    "debug": "source file E:/secret/layer1.tif",
                                },
                            },
                        }
                    ],
                    "diagnostics": [
                        {
                            "artifact_id": "a1",
                            "path": r"E:\agent\workspace\users\u1\sessions\s1\outputs\bad.tif",
                            "error": "failed",
                            "detail": "see /var/log/secret/map.log",
                        }
                    ],
                }

            def refresh_artifact(self, artifact_id: str, *, user_id: str, session_id: str) -> dict:
                return {
                    "artifact_id": artifact_id,
                    "map_ready": True,
                    "layer": {
                        "id": "layer1",
                        "meta": {
                            "absolute_path": r"E:\agent\workspace\outputs\layer1.tif",
                            "relative_path": "outputs/layer1.tif",
                            "display_path": "outputs/layer1.tif",
                            "diagnostic": "/home/app/secret/layer1.log",
                        },
                    },
                }

        app = FastAPI()
        app.include_router(
            create_map_router(
                scoped_workspace_service=lambda user_id, session_id="": FakeService(),
                require_request_user_if_present=lambda request, user_id: user_id or "u1",
                load_station_collection=lambda user_id="": {},
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        with mock.patch("api.routes.map.MapLayerService", FakeMapLayerService):
            layers = client.get("/api/map/layers?user_id=u1&session_id=s1").json()
            refreshed = client.post(
                "/api/map/layers/refresh",
                json={"user_id": "u1", "session_id": "s1", "artifact_id": "a1"},
            ).json()

        payload_text = json.dumps({"layers": layers, "refreshed": refreshed}, ensure_ascii=False)
        self.assertIn("preview_url", layers["layers"][0])
        self.assertNotIn("source_path", payload_text)
        self.assertNotIn("download_url", payload_text)
        self.assertNotIn("preview_path", payload_text)
        self.assertNotIn("absolute_path", payload_text)
        self.assertNotIn("relative_path", payload_text)
        self.assertNotIn("display_path", payload_text)
        self.assertNotIn("E:\\agent", payload_text)
        self.assertNotIn("E:/secret", payload_text)
        self.assertNotIn("/tmp/secret", payload_text)
        self.assertNotIn("/home/app/secret", payload_text)
        self.assertNotIn("/var/log/secret", payload_text)
        self.assertNotIn("/api/files/artifact", payload_text)

    def test_local_library_routes_use_library_service_and_workspace_import(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeLibrary:
            def list_items(self, **kwargs) -> list[dict]:
                calls.append(("list_items", kwargs))
                return {
                    "root": r"E:\agent\local_library",
                    "data_dir": r"E:\agent\local_library\data",
                    "manifest_path": r"E:\agent\local_library\library_manifest.json",
                    "items": [
                        {
                            "item_id": "item1",
                            "name": "demo",
                            "data_type": "table",
                            "path": r"E:\agent\local_library\data\demo.csv",
                            "absolute_path": r"E:\agent\local_library\data\demo.csv",
                            "description": "loaded from /tmp/secret/local_library/demo.csv",
                            "metadata": {"debug": "manifest at E:/secret/library_manifest.json"},
                        }
                    ],
                    "categories": [],
                    "data_types": [],
                    "count": 1,
                    "total": 1,
                }

            def rescan(self) -> dict:
                calls.append(("rescan", True))
                return {
                    "ok": True,
                    "root": r"E:\agent\local_library",
                    "data_dir": r"E:\agent\local_library\data",
                    "manifest_path": r"E:\agent\local_library\library_manifest.json",
                    "diagnostic": "/var/log/secret/local-library-rescan.log",
                    "added": 1,
                    "updated": 0,
                    "total": 1,
                }

            def resolve_paths(self, item_ids: list[str]) -> list[dict]:
                calls.append(("resolve_paths", item_ids))
                return [{"path": "demo.csv"}]

        class FakeService:
            def import_local_library_item(self, item: dict) -> str:
                calls.append(("import", item))
                return "imported /home/app/secret/demo.csv from E:/secret/local_library/demo.csv"

        app = FastAPI()
        app.include_router(
            create_local_library_router(
                local_library=lambda: FakeLibrary(),
                scoped_workspace_service=lambda user_id, session_id="": calls.append(("scope", (user_id, session_id))) or FakeService(),
                require_request_user_if_present=lambda request, user_id: user_id or "u1",
                decorate_dashboard=lambda service, user_id="": {"summary": {}, "artifacts": []},
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        listed = client.get("/api/local-library?query=demo").json()
        self.assertEqual(listed["items"][0]["filename"], "demo.csv")
        self.assertNotIn("root", listed)
        self.assertNotIn("data_dir", listed)
        self.assertNotIn("manifest_path", listed)
        self.assertNotIn("path", listed["items"][0])
        self.assertNotIn("absolute_path", listed["items"][0])
        self.assertNotIn("/tmp/secret", json.dumps(listed, ensure_ascii=False))
        self.assertNotIn("E:/secret", json.dumps(listed, ensure_ascii=False))
        rescanned = client.post("/api/local-library/rescan").json()
        self.assertTrue(rescanned["ok"])
        self.assertEqual(rescanned["added"], 1)
        self.assertNotIn("root", rescanned)
        self.assertNotIn("data_dir", rescanned)
        self.assertNotIn("manifest_path", rescanned)
        self.assertNotIn("E:\\agent", str(rescanned))
        self.assertNotIn("/var/log/secret", json.dumps(rescanned, ensure_ascii=False))
        imported = client.post("/api/local-library/import", json={"user_id": "u1", "session_id": "s1", "item_ids": ["item1"]}).json()
        self.assertEqual(imported["count"], 1)
        imported_text = json.dumps(imported, ensure_ascii=False)
        self.assertNotIn("/home/app/secret", imported_text)
        self.assertNotIn("E:/secret", imported_text)
        self.assertIn(("scope", ("u1", "s1")), calls)
        self.assertIn(("resolve_paths", ["item1"]), calls)

    def test_download_resume_route_uses_authenticated_user_service_and_audit(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeResumeService:
            def resume(self, user_id: str, job_id: str) -> dict:
                calls.append(("resume", (user_id, job_id)))
                return {"job": {"job_id": job_id, "user_id": user_id}, "auto_started": True}

        def authenticated_user(request: Request) -> str:
            calls.append(("auth", request.url.path))
            return "u_1"

        def audit(request: Request, **kwargs):
            calls.append(("audit", kwargs))

        app = FastAPI()
        app.include_router(
            create_downloads_router(
                resume_service=lambda: FakeResumeService(),
                authenticated_user=authenticated_user,
                audit=audit,
                guard=lambda fn: fn(),
            )
        )

        response = TestClient(app).post("/api/download-jobs/job_1/resume")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["auto_started"], True)
        self.assertNotIn("job", payload)
        self.assertIn(("auth", "/api/download-jobs/job_1/resume"), calls)
        self.assertIn(("resume", ("u_1", "job_1")), calls)
        audit_call = next(item for name, item in calls if name == "audit")
        self.assertEqual(audit_call["user_id"], "u_1")
        self.assertEqual(audit_call["action"], "download.resume")
        self.assertEqual(audit_call["resource_id"], "job_1")
        self.assertEqual(audit_call["detail"], {"auto_started": True})

    def test_gscloud_account_routes_use_authenticated_user_service_and_audit(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeAccountService:
            def status(self, user_id: str) -> dict:
                calls.append(("status", user_id))
                return {
                    "provider": "gscloud",
                    "logged_in": True,
                    "path": "E:/secret/state.json",
                    "storage_state_path": "E:/secret/state.json",
                    "status_path": "E:/secret/status.json",
                    "log_path": "E:/secret/login.log",
                    "diagnostics": {"runtime_log": "/var/log/secret/login.log"},
                }

            def start_login(self, user_id: str, *, timeout_seconds: int) -> dict:
                calls.append(("start_login", (user_id, timeout_seconds)))
                return {
                    "provider": "gscloud",
                    "login_session_id": "login_1",
                    "state": "BROWSER_OPENING",
                    "state_path": "E:/secret/state.json",
                    "status_path": "E:/secret/status.json",
                    "log_path": "E:/secret/login.log",
                    "diagnostics": {"runtime_log": "/tmp/secret/login.log"},
                }

            def complete_login(self, user_id: str, login_session_id: str) -> dict:
                calls.append(("complete_login", (user_id, login_session_id)))
                return {
                    "provider": "gscloud",
                    "logged_in": True,
                    "login_session_id": login_session_id,
                    "waiting_jobs": [
                        {
                            "job_id": "job_1",
                            "status": "waiting_login",
                            "output_path": "E:/secret/out.tif",
                            "zip_path": "E:/secret/out.zip",
                            "download_url": "/api/downloads/artifact?path=secret/out.zip",
                            "storage_state_path": "E:/secret/state.json",
                            "diagnostic": "/home/app/secret/out.log",
                        }
                    ],
                }

            def logout(self, user_id: str) -> dict:
                calls.append(("logout", user_id))
                return {"provider": "gscloud", "logged_in": False, "storage_state_path": "E:/secret/state.json"}

        def authenticated_user(request: Request) -> str:
            calls.append(("auth", request.url.path))
            return "u_1"

        def audit(request: Request, **kwargs):
            calls.append(("audit", kwargs))

        app = FastAPI()
        app.include_router(
            create_data_sources_router(
                account_service=lambda: FakeAccountService(),
                authenticated_user=authenticated_user,
                audit=audit,
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        status = client.get("/api/data-sources/gscloud/status").json()
        started = client.post("/api/data-sources/gscloud/login/start", json={"timeout_seconds": 120}).json()
        completed = client.post("/api/data-sources/gscloud/login/complete", json={"login_session_id": "login_1"}).json()
        logged_out = client.delete("/api/data-sources/gscloud/logout").json()
        rendered = json.dumps({"status": status, "started": started, "completed": completed, "logged_out": logged_out}, ensure_ascii=False)

        self.assertEqual(status["logged_in"], True)
        self.assertEqual(started["login_session_id"], "login_1")
        self.assertEqual(completed["logged_in"], True)
        self.assertEqual(logged_out["logged_in"], False)
        self.assertNotIn("path", rendered)
        self.assertNotIn("storage_state_path", rendered)
        self.assertNotIn("status_path", rendered)
        self.assertNotIn("log_path", rendered)
        self.assertNotIn("output_path", rendered)
        self.assertNotIn("zip_path", rendered)
        self.assertNotIn("download_url", rendered)
        self.assertNotIn("E:/secret", rendered)
        self.assertNotIn("/tmp/secret", rendered)
        self.assertNotIn("/home/app/secret", rendered)
        self.assertNotIn("/var/log/secret", rendered)
        self.assertEqual(completed["waiting_jobs"], [{"job_id": "job_1", "status": "waiting_login"}])

        self.assertIn(("status", "u_1"), calls)
        self.assertIn(("start_login", ("u_1", 120)), calls)
        self.assertIn(("complete_login", ("u_1", "login_1")), calls)
        self.assertIn(("logout", "u_1"), calls)
        audit_actions = [payload["action"] for name, payload in calls if name == "audit"]
        self.assertEqual(
            audit_actions,
            ["data_source.login_start", "data_source.login_complete", "data_source.logout"],
        )

    def test_payments_route_uses_plan_preset_payment_service_and_audit(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeCommercialService:
            def simulate_payment(self, **kwargs) -> dict:
                calls.append(("simulate_payment", kwargs))
                return {
                    "payment": {
                        "payment_id": "pay_1",
                        "user_id": kwargs["user_id"],
                        "plan": kwargs["plan"],
                        "storage_state_path": "E:/secret/state.json",
                        "token_hash": "secret-token-hash",
                    },
                    "order": {
                        "order_id": "ord_1",
                        "user_id": kwargs["user_id"],
                        "plan": kwargs["plan"],
                        "download_url": "/api/files/artifact?path=secret/order.json",
                    },
                    "user": {
                        "user_id": kwargs["user_id"],
                        "plan": kwargs["plan"],
                        "password_hash": "secret-password-hash",
                    },
                    "debug_path": "E:/secret/payment-debug.json",
                    "diagnostics": {"runtime_log": "/tmp/secret/payment-debug.log"},
                }

        app = FastAPI()
        app.include_router(
            create_payments_router(
                commercial_service=lambda: FakeCommercialService(),
                require_payment_user=lambda request, user_id: f"authorized_{user_id}",
                plan_presets={"pro": {"price_cents": 2000, "platform_monthly_quota": 30, "days": 30}},
                audit=lambda request, **kwargs: calls.append(("audit", kwargs)),
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        response = client.post("/api/payments/simulate", json={"user_id": "u1", "plan": "pro"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        payload_text = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["payment"]["payment_id"], "pay_1")
        self.assertEqual(payload["user"]["user_id"], "authorized_u1")
        self.assertNotIn("password_hash", payload_text)
        self.assertNotIn("token_hash", payload_text)
        self.assertNotIn("storage_state_path", payload_text)
        self.assertNotIn("download_url", payload_text)
        self.assertNotIn("debug_path", payload_text)
        self.assertNotIn("E:/secret", payload_text)
        self.assertNotIn("/tmp/secret", payload_text)
        payment_call = next(payload for name, payload in calls if name == "simulate_payment")
        self.assertEqual(payment_call["user_id"], "authorized_u1")
        self.assertEqual(payment_call["amount_cents"], 2000)
        self.assertEqual(payment_call["platform_quota"], 30)
        audit_call = next(payload for name, payload in calls if name == "audit")
        self.assertEqual(audit_call["action"], "payment.simulate")
        self.assertEqual(audit_call["resource_id"], "pay_1")

    def test_workflows_route_returns_prompt_or_runs_scoped_service(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeService:
            current_session_id = "s1"

            def ask(self, prompt: str) -> dict:
                calls.append(("ask", prompt))
                return {"reply": "workflow started", "prompt": prompt}

        app = FastAPI()
        app.include_router(
            create_workflows_router(
                require_request_user_if_present=lambda request, user_id: user_id or "u1",
                scoped_workspace_service=lambda user_id, session_id="": calls.append(("scope", (user_id, session_id))) or FakeService(),
                workflow_prompt="run workflow",
                attach_chat_state=lambda service, response: {**response, "messages": [{"role": "assistant", "content": response["reply"]}], "sessions": [{"session_id": service.current_session_id}], "current_session_id": service.current_session_id},
                attach_result_panel=lambda service, user_id, response: {**response, "result_panel": {"status": "ready", "user_id": user_id}},
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        prompt_only = client.post("/api/workflows/shandian-soil-moisture", json={"run_now": False}).json()
        self.assertEqual(prompt_only, {"prompt": "run workflow"})
        started = client.post(
            "/api/workflows/shandian-soil-moisture",
            json={"user_id": "u1", "session_id": "s1", "run_now": True},
        ).json()
        self.assertEqual(started["reply"], "workflow started")
        self.assertEqual(started["messages"][0]["content"], "workflow started")
        self.assertEqual(started["current_session_id"], "s1")
        self.assertEqual(started["result_panel"]["status"], "ready")
        self.assertNotIn("user_id", started["result_panel"])
        self.assertIn(("scope", ("u1", "s1")), calls)
        self.assertIn(("ask", "run workflow"), calls)

    def test_workflows_route_validates_raw_service_response_without_optional_decorators(self) -> None:
        class FakeService:
            current_session_id = "s1"

            def ask(self, prompt: str) -> dict:
                return {
                    "reply": "workflow started E:/secret/out.tif /api/files/artifact?path=derived/out.tif",
                    "artifacts": [
                        {
                            "artifact_id": "a1",
                            "filename": "out.tif",
                            "path": "E:/secret/out.tif",
                            "download_url": "/api/files/artifact?path=derived/out.tif",
                        }
                    ],
                    "files": [{"path": "E:/secret/file.csv"}],
                    "normalized_results": [{"outputs": {"path": "E:/secret/out.tif"}}],
                    "session_id": "s1",
                    "user_id": "u1",
                }

        app = FastAPI()
        app.include_router(
            create_workflows_router(
                require_request_user_if_present=lambda request, user_id: user_id or "u1",
                scoped_workspace_service=lambda user_id, session_id="": FakeService(),
                workflow_prompt="run workflow",
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        payload = client.post(
            "/api/workflows/shandian-soil-moisture",
            json={"user_id": "u1", "session_id": "s1", "run_now": True},
        ).json()
        rendered = json.dumps(payload, ensure_ascii=False)

        self.assertIn("[已隐藏内部路径]", payload["reply"])
        self.assertEqual(payload["artifacts"][0]["artifact_id"], "a1")
        self.assertEqual(payload["artifacts"][0]["filename"], "out.tif")
        self.assertNotIn("path", rendered)
        self.assertNotIn("output_path", rendered)
        self.assertNotIn("download_url", rendered)
        self.assertNotIn("user_id", rendered)
        self.assertNotIn("E:/secret", rendered)
        self.assertNotIn("/api/files/artifact", rendered)


if __name__ == "__main__":
    unittest.main()
