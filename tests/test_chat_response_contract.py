from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from core.chat_response import build_chat_response
from core.config import Settings
from core.response_postprocess import dedupe_assistant_reply, repair_mojibake_text
from core.service import GISWorkspaceService


pytestmark = pytest.mark.slow


class ChatResponseContractTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_build_chat_response_persists_exchange_and_returns_authoritative_state(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            response = build_chat_response(
                service,
                user_prompt="检查下载任务状态",
                result={"reply": "没有正在运行的下载任务。", "model": "direct-router", "reason": "download_status", "job": {"job_id": "job_1"}},
                meta_keys=("model", "reason", "job"),
            )

            self.assertEqual(response["reply"], "没有正在运行的下载任务。")
            self.assertEqual(response["model"], "direct-router")
            self.assertEqual(response["reason"], "download_status")
            self.assertEqual(response["current_session_id"], service.current_session_id)
            self.assertGreaterEqual(len(response["sessions"]), 1)
            self.assertEqual([item["role"] for item in response["messages"]], ["user", "assistant"])
            self.assertEqual(response["messages"][0]["content"], "检查下载任务状态")
            self.assertEqual(response["messages"][1]["content"], "没有正在运行的下载任务。")
            self.assertEqual(response["messages"][1]["meta"]["job"]["job_id"], "job_1")

    def test_build_chat_response_does_not_swallow_persistence_errors(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.database.add_message = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down"))  # type: ignore[method-assign]

            with self.assertRaises(RuntimeError):
                build_chat_response(
                    service,
                    user_prompt="检查下载任务状态",
                    result={"reply": "ok", "model": "direct-router"},
                    meta_keys=("model",),
                )

    def test_download_requires_login_reply_is_regular_chat_result(self) -> None:
        from core.api_helpers import _download_requires_login_result

        result = _download_requires_login_result("下载成都市 DEM")

        self.assertEqual(result["model"], "direct-router")
        self.assertEqual(result["reason"], "download_requires_login")
        self.assertIn("登录", result["reply"])
        self.assertIn("DEM", result["reply"])

    def test_api_artifact_decoration_hides_internal_paths_and_scope_ids(self) -> None:
        from api_server import _decorate_response_artifacts

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.set_runtime_scope(user_id="u_1", session_id="s_1")
            service.current_session_id = "s_1"
            artifact_path = service.manager.derived_dir / "xgb_metrics.csv"
            artifact_path.write_text("metric,value\nRMSE,0.1\n", encoding="utf-8")
            artifact = service.manager.register_artifact(path=str(artifact_path), type="metrics", title="xgb_metrics.csv")
            raw_response = {
                "artifacts": [artifact],
                "user_facing_result": {
                    "primary_artifacts": [artifact],
                    "download_bundle": None,
                    "debug": {},
                },
                "messages": [{"role": "assistant", "content": "ok", "meta": {"artifacts": [artifact], "user_facing_result": {"primary_artifacts": [artifact]}}}],
            }

            decorated = _decorate_response_artifacts(service, "u_1", raw_response)

            payloads = [
                decorated["artifacts"][0],
                decorated["user_facing_result"]["primary_artifacts"][0],
                decorated["messages"][0]["meta"]["artifacts"][0],
                decorated["messages"][0]["meta"]["user_facing_result"]["primary_artifacts"][0],
            ]
            for payload in payloads:
                self.assertEqual(payload["artifact_id"], artifact["artifact_id"])
                self.assertIn("/api/artifacts/", payload["download_url"])
                self.assertEqual(payload["filename"], "xgb_metrics.csv")
                self.assertNotIn("path", payload)
                self.assertNotIn("absolute_path", payload)
                self.assertNotIn("owner_user_id", payload)
                self.assertNotIn("session_id", payload)

    def test_api_artifact_decoration_replaces_legacy_download_urls(self) -> None:
        from api_server import _decorate_response_artifacts

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.set_runtime_scope(user_id="u_1", session_id="s_1")
            service.current_session_id = "s_1"
            artifact_path = service.manager.derived_dir / "legacy_metrics.csv"
            artifact_path.write_text("metric,value\nRMSE,0.1\n", encoding="utf-8")
            artifact = service.manager.register_artifact(
                artifact_id="artifact_legacy_metrics",
                path=str(artifact_path),
                type="metrics",
                title="legacy_metrics.csv",
            )
            raw = {
                **artifact,
                "download_url": "/api/files/artifact?path=derived/legacy_metrics.csv",
            }

            decorated = _decorate_response_artifacts(
                service,
                "u_1",
                {
                    "artifacts": [raw],
                    "user_facing_result": {"primary_artifacts": [raw]},
                    "messages": [{"role": "assistant", "content": "ok", "meta": {"artifacts": [raw]}}],
                },
            )

            payloads = [
                decorated["artifacts"][0],
                decorated["user_facing_result"]["primary_artifacts"][0],
                decorated["messages"][0]["meta"]["artifacts"][0],
            ]
            for payload in payloads:
                self.assertEqual(
                    payload["download_url"],
                    "/api/artifacts/artifact_legacy_metrics/download?user_id=u_1&session_id=s_1",
                )
                self.assertNotIn("/api/files/artifact", payload["download_url"])

    def test_response_quality_gate_sanitizes_public_debug_leaks(self) -> None:
        from core.response_quality import validate_response_before_send

        raw = {
            "reply": "已完成。\nworkspace\\users\\u_1\\sessions\\s_1\\derived\\x.csv\n/tmp/secret/runtime.log",
            "user_facing_result": {
                "summary": "已完成，诊断文件 /home/app/secret/runtime.log",
                "primary_artifacts": [],
                "technical_details": {"path": "workspace\\users\\u_1\\sessions\\s_1\\derived\\x.csv"},
                "debug": {"raw_workflow_result": {"steps": [{"input": {"path": "secret"}}]}},
            },
            "artifacts": [
                {
                    "artifact_id": "a1",
                    "path": "workspace\\users\\u_1\\sessions\\s_1\\derived\\x.csv",
                    "owner_user_id": "u_1",
                    "session_id": "s_1",
                    "log_note": "/var/log/gis-agent/private.log",
                }
            ],
            "messages": [
                {
                    "role": "assistant",
                    "content": "output: {'path': 'workspace/users/u_1/x.csv'}; see /root/private/debug.json",
                    "meta": {"plan": {"input": "raw"}, "diagnostics": {"x": 1}},
                }
            ],
        }

        cleaned = validate_response_before_send(raw, user_id="u_1", session_id="s_1")
        rendered = str(cleaned)

        self.assertNotIn("workspace\\users", cleaned["reply"])
        self.assertNotIn("workspace/users", rendered)
        self.assertNotIn("/tmp/secret", rendered)
        self.assertNotIn("/home/app/secret", rendered)
        self.assertNotIn("/var/log/gis-agent", rendered)
        self.assertNotIn("/root/private", rendered)
        self.assertNotIn("owner_user_id", rendered)
        self.assertNotIn("session_id", rendered)
        self.assertNotIn("'input': 'raw'", rendered)
        self.assertIn("quality_warnings", cleaned["user_facing_result"])

    def test_response_quality_preserves_chat_session_ids_without_private_fields(self) -> None:
        from core.response_quality import validate_response_before_send

        raw = {
            "sessions": [
                {
                    "session_id": "s_1",
                    "title": "Analysis",
                    "updated_at": "2099-01-01",
                    "path": "workspace/users/u_1/sessions/s_1/private.json",
                    "user_id": "u_1",
                    "storage_state_path": "E:/secret/state.json",
                }
            ],
            "session_id": "s_1",
            "current_session_id": "s_1",
            "messages": [],
        }

        cleaned = validate_response_before_send(raw, user_id="u_1", session_id="s_1")
        rendered = str(cleaned)

        self.assertEqual(cleaned["sessions"][0]["session_id"], "s_1")
        self.assertEqual(cleaned["session_id"], "s_1")
        self.assertEqual(cleaned["current_session_id"], "s_1")
        self.assertEqual(cleaned["sessions"][0]["title"], "Analysis")
        self.assertNotIn("path", cleaned["sessions"][0])
        self.assertNotIn("user_id", cleaned["sessions"][0])
        self.assertNotIn("storage_state_path", rendered)
        self.assertNotIn("workspace/users", rendered)
        self.assertNotIn("E:/secret", rendered)

    def test_response_quality_removes_legacy_url_fields_and_links(self) -> None:
        from core.response_quality import validate_response_before_send

        raw = {
            "reply": "下载：/api/files/artifact?path=derived/legacy.csv，也可看 /api/downloads/artifact?job_id=job_1&path=downloads/job_1/out.zip",
            "artifacts": [
                {
                    "artifact_id": "artifact_legacy",
                    "name": "legacy.csv",
                    "url": "/api/files/artifact?path=derived/legacy.csv",
                    "download_url": "/api/files/artifact?path=derived/legacy.csv",
                }
            ],
            "user_facing_result": {
                "summary": "结果见 /api/files/artifact?path=derived/legacy.csv",
                "primary_artifacts": [
                    {
                        "artifact_id": "artifact_legacy",
                        "filename": "legacy.csv",
                        "url": "/api/downloads/artifact?job_id=job_1&path=downloads/job_1/out.zip",
                    }
                ],
            },
            "messages": [
                {
                    "role": "assistant",
                    "content": "legacy link: /api/files/artifact?path=derived/legacy.csv",
                    "meta": {
                        "artifacts": [
                            {
                                "artifact_id": "artifact_legacy",
                                "filename": "legacy.csv",
                                "url": "/api/files/artifact?path=derived/legacy.csv",
                            }
                        ]
                    },
                }
            ],
        }

        cleaned = validate_response_before_send(raw, user_id="u_1", session_id="s_1")
        rendered = str(cleaned)

        self.assertIn("artifact_legacy", rendered)
        self.assertIn("legacy.csv", rendered)
        self.assertNotIn("/api/files/artifact", rendered)
        self.assertNotIn("/api/downloads/artifact", rendered)
        self.assertNotIn("'url'", rendered)
        self.assertNotIn("download_url", rendered)

    def test_latest_model_result_context_uses_artifact_refs_not_paths(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.discover_model_results = lambda: [  # type: ignore[method-assign]
                {
                    "model": "XGBoost",
                    "output_prefix": "soil_xgb",
                    "metrics": {"RMSE": 0.12},
                    "artifacts": [
                        {
                            "artifact_id": "artifact_xgb_metrics",
                            "label": "指标表",
                            "display_path": "derived/soil_xgb_metrics.csv",
                            "path": "workspace/users/u1/sessions/s1/derived/soil_xgb_metrics.csv",
                        }
                    ],
                    "recommendations": ["检查残差空间分布"],
                }
            ]

            reply = service._format_latest_model_result_context()

        self.assertIn("结果引用：", reply)
        self.assertIn("指标表", reply)
        self.assertIn("artifact_xgb_metrics", reply)
        self.assertNotIn("处理后的数据位置：", reply)
        self.assertNotIn("derived/soil_xgb_metrics.csv", reply)
        self.assertNotIn("workspace/users", reply)

    def test_referenced_object_reply_does_not_expose_object_path(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.set_interaction_mode("tool_enabled")
            intent = {"intent": "result_analysis", "needs_followup_resolution": True}
            referenced = {
                "type": "artifact",
                "id": "artifact_current",
                "label": "当前结果",
                "path": "workspace/users/u1/sessions/s1/derived/current.csv",
            }
            plan = {
                "primary_goal": "解释当前结果",
                "intent": "result_analysis",
                "operation": "explain_result",
                "execution_required": True,
                "response_mode": "",
                "input_assets": [],
                "asset_roles": {},
                "requested_downloads": [],
                "download_requests": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": [],
                "selected_tools": [],
                "workflow_steps": [],
                "workflow_plan": [],
                "tool_plan": [],
                "expected_outputs": ["explanation"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {},
                "explicit_history_references": [],
                "response_language": "zh-CN",
            }

            with mock.patch("core.service.classify_user_intent", return_value=intent):
                with mock.patch("core.service.resolve_followup", return_value={"referenced_object": referenced}):
                    with mock.patch("core.service.build_task_plan", return_value=plan):
                        with mock.patch.object(service, "_build_active_task_plan", return_value={"status": "ready", "plan": plan}):
                            with mock.patch.object(service, "_build_shadow_task_plan", return_value={"status": "disabled"}):
                                with mock.patch("core.service.validate_task_plan_before_execution", return_value={"ok": True, "status": "valid_tool_plan", "execution_plan": plan}):
                                    with mock.patch("core.service._plan_requests_tool_execution", return_value=True):
                                        with mock.patch("core.service.run_coordinated_execution", return_value={"executed": False, "blocked_reason": "NO_EXECUTABLE_STEPS"}):
                                            with mock.patch("core.service.execute_workflow_plan", return_value={"executed": False}):
                                                with mock.patch("core.service.execute_validated_tool_plan", return_value={"executed": False}):
                                                    with mock.patch("core.service.interpret_result", side_effect=lambda _prompt, _intent, _plan, raw, _context, _dashboard: raw):
                                                        result = service.ask("这个结果怎么看？")

        self.assertEqual(result["mode"], "deterministic_context")
        self.assertIn("对象 ID：artifact_current", result["reply"])
        self.assertNotIn("对象路径：", result["reply"])
        self.assertNotIn("workspace/users", result["reply"])

    def test_response_quality_preserves_sanitized_presentation_fields(self) -> None:
        from core.response_quality import validate_response_before_send

        raw = {
            "reply": "ok",
            "normalized_results": [
                {
                    "status": "succeeded",
                    "step_id": "plot",
                    "tool_name": "plot_dataset",
                    "outputs": {"result_dataset": "map", "path": "workspace/users/u1/sessions/s1/x.png"},
                    "diagnostics": {"crs": "EPSG:4326", "log_path": "workspace/users/u1/log.txt"},
                    "artifacts": [{"artifact_id": "a1", "path": "workspace/users/u1/sessions/s1/x.png"}],
                    "extra_raw": {"path": "secret"},
                }
            ],
            "presentation_result": {"status": "succeeded", "artifact_refs": [{"artifact_id": "a1"}]},
            "execution_summary": {"status": "succeeded", "artifact_count": 1},
            "execution_trace": {"results": [{"outputs": {"path": "secret"}}]},
            "coordinator_execution": {"tool_results": [{"outputs": {"path": "secret"}}]},
            "messages": [
                {
                    "role": "assistant",
                    "content": "ok",
                    "meta": {
                        "normalized_results": [
                            {
                                "status": "succeeded",
                                "step_id": "plot",
                                "tool_name": "plot_dataset",
                                "outputs": {"result_dataset": "map", "path": "workspace/users/u1/sessions/s1/x.png"},
                                "diagnostics": {"crs": "EPSG:4326"},
                            }
                        ],
                        "presentation_result": {"status": "succeeded", "artifact_refs": [{"artifact_id": "a1"}]},
                        "execution_summary": {"status": "succeeded"},
                        "execution_trace": {"results": []},
                    },
                }
            ],
        }

        cleaned = validate_response_before_send(raw, user_id="u1", session_id="s1")
        rendered = str(cleaned)

        self.assertIn("presentation_result", cleaned)
        self.assertIn("execution_summary", cleaned)
        self.assertEqual(cleaned["normalized_results"][0]["outputs"]["result_dataset"], "map")
        self.assertEqual(cleaned["normalized_results"][0]["diagnostics"]["crs"], "EPSG:4326")
        self.assertNotIn("execution_trace", rendered)
        self.assertNotIn("coordinator_execution", rendered)
        self.assertNotIn("workspace/users", rendered)
        self.assertNotIn("log_path", rendered)

    def test_result_interpreter_does_not_read_raw_workflow_result_as_success(self) -> None:
        import json

        from core.result_interpreter import interpret_result

        workflow_result = {
            "ok": True,
            "workflow_id": "wf_1",
            "steps": [
                {
                    "step_id": "train_model",
                    "tool_name": "train_xgboost_fusion_model",
                    "status": "success",
                    "validated_tool_args": {"dataset_name": "demo"},
                    "tool_result": {
                        "ok": True,
                        "tool_name": "train_xgboost_fusion_model",
                        "inputs": {"dataset_name": "demo"},
                        "outputs": {"model_result_id": "m1"},
                        "artifacts": [{"artifact_id": "a1", "path": "workspace/users/u_1/derived/predictions.csv", "type": "dataset", "title": "predictions"}],
                        "diagnostics": {"metrics": {"spatial_cv": {"RMSE": 0.12, "MAE": 0.09, "NSE": 0.7, "Bias": 0.01, "n": 48}}},
                    },
                }
            ],
            "final_artifacts": [{"artifact_id": "a1", "path": "workspace/users/u_1/derived/predictions.csv", "type": "dataset", "title": "predictions"}],
            "final_summary": "Workflow completed successfully.",
            "failed_step": "",
            "diagnostics": {"executed_steps": ["train_model"]},
            "next_actions": [],
        }

        reply = interpret_result(
            "训练 XGBoost",
            {"intent": "modeling"},
            {"task_type": "modeling"},
            json.dumps(workflow_result, ensure_ascii=False),
            {"active_dataset": {"name": "demo"}},
            {},
        )

        self.assertIn("canonical", reply.lower())
        self.assertNotIn("XGBoost", reply)
        self.assertNotIn("RMSE", reply)
        self.assertNotIn("input:", reply)
        self.assertNotIn("output:", reply)
        self.assertNotIn("workspace/users", reply)
        self.assertNotIn("裁剪或处理结果", reply)


    def test_coordinated_chat_meta_prefers_presentation_result_without_legacy_tool_results(self) -> None:
        import json
        from unittest import mock

        import pandas as pd

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.current_session_id = service.create_new_session()
            service.set_interaction_mode("tool_enabled")
            service.manager.put_table("stations", pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
            active_plan = {
                "status": "ready",
                "mode": "active",
                "planner_source": "test",
                "executes_tools": False,
                "plan": {
                    "primary_goal": "describe_dataset",
                    "task_type": "data_upload_analysis",
                    "intent": "analysis",
                    "operation": "",
                    "input_assets": [],
                    "asset_roles": {},
                    "requested_downloads": [],
                    "study_area": {},
                    "time_range": {},
                    "spatial_resolution": "",
                    "candidate_tools": ["describe_dataset"],
                    "selected_tools": ["describe_dataset"],
                    "workflow_plan": [
                        {"step_id": "describe", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": "stations"}},
                    ],
                    "tool_plan": [],
                    "validated_tool_args": {},
                    "expected_outputs": [],
                    "requires_confirmation": False,
                    "clarification_question": "",
                    "confidence": 0.9,
                    "source_attribution": {},
                    "explicit_history_references": [],
                },
            }

            def decide(plan, current_step, remaining_steps, execution_trace, user_request, **kwargs):
                if current_step:
                    return {
                        "status": "ready",
                        "decision": {
                            "decision": "continue",
                            "next_step_id": current_step["step_id"],
                            "selected_next_action": "",
                            "required_tool": current_step["tool_name"],
                            "required_inputs": current_step.get("validated_tool_args") or {},
                            "reason": "run canonical step",
                            "user_question": "",
                            "confidence": 0.9,
                        },
                    }
                return {"status": "ready", "decision": {"decision": "stop_success", "confidence": 0.9}}

            with mock.patch("core.service.build_llm_task_plan", return_value=active_plan):
                with mock.patch("core.coordinated_executor.build_coordinator_decision", side_effect=decide):
                    result = service.ask("describe stations")

            assistant = [item for item in service.manager.database.list_messages(service.current_session_id) if item["role"] == "assistant"][-1]
            meta = assistant["meta"]
            rendered = json.dumps(meta, ensure_ascii=False, default=str)

            self.assertIn("presentation_result", meta)
            self.assertIn("execution_summary", meta)
            self.assertEqual(meta["presentation_result"]["schema_version"], "presentation-result/v1")
            self.assertEqual(meta["execution_summary"]["schema_version"], "execution-summary/v1")
            self.assertEqual(meta["result_rendering_path"], "presentation_result")
            self.assertNotIn("tool_results", meta)
            self.assertNotIn("workflow_result", rendered)
            self.assertNotIn("workspace\\users", rendered)
            self.assertEqual(result["mode"], "coordinated_workflow")

    def test_response_postprocess_dedupes_result_sections(self) -> None:
        raw = "\n".join(
            [
                "\u5df2\u5b8c\u6210\u64cd\u4f5c\uff1a",
                "- \u5df2\u751f\u6210 DEM \u62fc\u63a5\u7ed3\u679c",
                "\u8f93\u51fa\u6587\u4ef6\uff1a",
                "- derived/county_dem.tif",
                "\u8f93\u51fa\u6587\u4ef6\uff1a",
                "- derived/county_dem.tif",
                "\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a",
                "- \u53ef\u4ee5\u76f4\u63a5\u52a0\u8f7d\u5230\u5730\u56fe\u68c0\u67e5",
                "\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a",
                "- \u53ef\u4ee5\u76f4\u63a5\u52a0\u8f7d\u5230\u5730\u56fe\u68c0\u67e5",
                "\u7ed3\u679c\u5f15\u7528\uff1a",
                "- artifact_dem",
                "\u7ed3\u679c\u5f15\u7528\uff1a",
                "- artifact_dem",
            ]
        )

        cleaned = dedupe_assistant_reply(raw)

        self.assertEqual(cleaned.count("\u8f93\u51fa\u6587\u4ef6\uff1a"), 1)
        self.assertEqual(cleaned.count("\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a"), 1)
        self.assertEqual(cleaned.count("\u7ed3\u679c\u5f15\u7528\uff1a"), 1)
        self.assertEqual(cleaned.count("derived/county_dem.tif"), 1)
        self.assertEqual(cleaned.count("artifact_dem"), 1)

    def test_build_chat_response_returns_and_persists_cleaned_reply(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raw_reply = "\u5df2\u5b8c\u6210\u64cd\u4f5c\uff1a\n- A\n\u8f93\u51fa\u6587\u4ef6\uff1a\n- out.tif\n\u8f93\u51fa\u6587\u4ef6\uff1a\n- out.tif"

            response = build_chat_response(
                service,
                user_prompt="\u751f\u6210\u7ed3\u679c",
                result={"reply": raw_reply, "model": "direct-router", "reason": "download_complete"},
                meta_keys=("model", "reason"),
            )

            self.assertEqual(response["reply"].count("\u8f93\u51fa\u6587\u4ef6\uff1a"), 1)
            self.assertEqual(response["reply"].count("out.tif"), 1)
            self.assertEqual(response["messages"][1]["content"], response["reply"])

    def test_workspace_database_cleans_updated_assistant_messages(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            session_id = service._ensure_session()
            message_id = service.manager.database.add_message(session_id, "assistant", "\u8f93\u51fa\u6587\u4ef6\uff1a\n- a.tif\n\u8f93\u51fa\u6587\u4ef6\uff1a\n- a.tif")

            service.manager.database.update_message(message_id, "\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a\n- \u68c0\u67e5\u5730\u56fe\n\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a\n- \u68c0\u67e5\u5730\u56fe")
            messages = service.manager.database.list_messages(session_id)

            self.assertEqual(messages[0]["content"].count("\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a"), 1)
            self.assertEqual(messages[0]["content"].count("\u68c0\u67e5\u5730\u56fe"), 1)
            self.assertEqual(repair_mojibake_text("\u6b63\u5e38\u6587\u672c"), "\u6b63\u5e38\u6587\u672c")

    def test_commercial_download_status_reply_hides_internal_paths(self) -> None:
        import api_server

        class FakeCommercialService:
            workdir = "."

            def get_job(self, job_id: str) -> dict:
                return {
                    "job_id": job_id,
                    "user_id": "u1",
                    "status": "completed",
                    "stage": "done",
                    "progress": 100,
                    "source_key": "gscloud",
                    "resource_type": "dem",
                    "region": "chengdu",
                    "output_name": "dem",
                    "output_path": r"E:\agent\workspace\users\u1\sessions\s1\downloads\job_abc\dem.tif",
                    "zip_path": r"E:\agent\workspace\users\u1\sessions\s1\downloads\job_abc\dem.zip",
                }

        with mock.patch.object(api_server, "commercial_service", FakeCommercialService()):
            with mock.patch.object(api_server, "require_resource_owner", lambda resource, **kwargs: resource):
                with mock.patch.object(api_server, "list_gscloud_tile_jobs", lambda workdir, limit=50: [{"job_id": "job_abc", "tile_job_id": "tile1", "state": "done", "status_path": r"E:\agent\status\tile1.json"}]):
                    with mock.patch.object(api_server, "list_gscloud_scene_jobs", lambda workdir, limit=50: []):
                        result = api_server._format_commercial_download_status("查询 job_abc 状态", "u1")

        self.assertIn("dem.tif", result["reply"])
        self.assertIn("dem.zip", result["reply"])
        self.assertIn("tile1", result["reply"])
        self.assertNotIn("E:\\agent", result["reply"])
        self.assertNotIn("输出路径", result["reply"])
        self.assertNotIn("结果压缩包", result["reply"])
        self.assertNotIn("状态文件", result["reply"])


if __name__ == "__main__":
    unittest.main()
