from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.durable_jobs import DurableJobStore
from core.execution_trace import build_execution_trace
from core.tool_context import ToolRuntimeContext
from core.tool_contracts import normalize_tool_result, tool_result_blocked, tool_result_error
from core.workflow_executor import execute_single_workflow_step


UNIFIED_WORKER_JOB_TYPE = "validated_task_plan"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class WorkerResourceLimits:
    max_concurrent_per_user: int = 1
    max_queue_per_user: int = 5
    max_queue_per_session: int = 3
    min_free_disk_mb: int = 256
    max_runtime_seconds: int = 300
    poll_interval_seconds: float = 0.2

    @classmethod
    def from_env(cls) -> "WorkerResourceLimits":
        return cls(
            max_concurrent_per_user=int(os.getenv("GIS_WORKER_MAX_CONCURRENT_PER_USER") or 1),
            max_queue_per_user=int(os.getenv("GIS_WORKER_MAX_QUEUE_PER_USER") or 5),
            max_queue_per_session=int(os.getenv("GIS_WORKER_MAX_QUEUE_PER_SESSION") or 3),
            min_free_disk_mb=int(os.getenv("GIS_WORKER_MIN_FREE_DISK_MB") or 256),
            max_runtime_seconds=int(os.getenv("GIS_WORKER_MAX_RUNTIME_SECONDS") or 300),
            poll_interval_seconds=float(os.getenv("GIS_WORKER_POLL_INTERVAL_SECONDS") or 0.2),
        )


class CancellationToken:
    def __init__(self, store: DurableJobStore, job_id: str):
        self.store = store
        self.job_id = job_id

    def is_cancelled(self) -> bool:
        try:
            return str(self.store.get_job(self.job_id).get("status") or "") == "cancelled"
        except Exception:
            return True

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise WorkerCancelled("Job was cancelled.")


class WorkerCancelled(RuntimeError):
    pass


StepExecutor = Callable[..., dict[str, Any]]


def _plan_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    steps = _as_list(plan.get("workflow_plan"))
    if steps:
        return [step for step in steps if isinstance(step, dict)]
    tool_plan = _as_list(plan.get("tool_plan"))
    out: list[dict[str, Any]] = []
    for index, step in enumerate(tool_plan):
        if not isinstance(step, dict):
            continue
        tool_name = str(step.get("tool_name") or "")
        args = step.get("args")
        if not isinstance(args, dict):
            args = _as_dict(_as_dict(plan.get("validated_tool_args")).get(tool_name))
        out.append(
            {
                "step_id": str(step.get("step_id") or tool_name or f"step_{index + 1}"),
                "tool_name": tool_name,
                "validated_tool_args": args if isinstance(args, dict) else {},
                "depends_on": _as_list(step.get("depends_on")),
            }
        )
    if out:
        return out
    return [
        {"step_id": name, "tool_name": name, "validated_tool_args": args, "depends_on": []}
        for name, args in _as_dict(plan.get("validated_tool_args")).items()
        if isinstance(args, dict)
    ]


def _idempotency_key(plan: dict[str, Any], user_id: str, session_id: str) -> str:
    explicit = str(plan.get("idempotency_key") or "").strip()
    if explicit:
        return explicit
    payload = {
        "user_id": user_id,
        "session_id": session_id,
        "plan_id": plan.get("plan_id"),
        "operation": plan.get("operation"),
        "workflow_plan": plan.get("workflow_plan"),
        "tool_plan": plan.get("tool_plan"),
        "validated_tool_args": plan.get("validated_tool_args"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return "validated-plan:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _blocked_job(*, code: str, message: str, user_id: str, session_id: str) -> dict[str, Any]:
    result = tool_result_blocked(
        UNIFIED_WORKER_JOB_TYPE,
        error_code=code,
        error_title="任务暂时无法入队",
        user_message=message,
        outputs={"durable_status": "blocked"},
        next_actions=["请等待当前任务完成，或取消不需要的任务后重试。"],
    ).to_dict()
    return {
        "job_id": "",
        "status": "blocked",
        "user_id": user_id,
        "session_id": session_id,
        "tool_result": result,
        "management_view": {
            "task_id": "",
            "status": "blocked",
            "progress": 0,
            "display_title": "后台任务",
            "source_name": "Unified Worker",
            "artifact_refs": [],
            "map_layer_refs": [],
            "warnings": [],
            "error_code": code,
            "error_title": "任务暂时无法入队",
            "user_message": message,
            "available_actions": [],
            "action_state": {},
            "updated_at": _now(),
        },
    }


class UnifiedBackgroundWorker:
    def __init__(
        self,
        store: DurableJobStore,
        manager: Any,
        *,
        limits: WorkerResourceLimits | None = None,
        step_executor: StepExecutor | None = None,
        runtime_context: ToolRuntimeContext | None = None,
    ):
        self.store = store
        self.manager = manager
        self.limits = limits or WorkerResourceLimits.from_env()
        self.step_executor = step_executor or execute_single_workflow_step
        self.runtime_context = runtime_context
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _disk_blocker(self) -> dict[str, str] | None:
        root = Path(getattr(self.manager, "workdir", self.store.db_path.parent) or self.store.db_path.parent)
        try:
            usage = shutil.disk_usage(root)
        except Exception:
            return None
        free_mb = int(usage.free / (1024 * 1024))
        if free_mb < self.limits.min_free_disk_mb:
            return {"code": "WORKER_DISK_SPACE_LOW", "message": f"当前可用磁盘空间不足，需要至少 {self.limits.min_free_disk_mb} MB。"}
        return None

    def enqueue_validated_plan(
        self,
        plan: dict[str, Any],
        *,
        context: dict[str, Any],
        user_id: str,
        session_id: str,
        project_id: str = "",
    ) -> dict[str, Any]:
        user_id = str(user_id or "anonymous")
        session_id = str(session_id or "")
        key = _idempotency_key(plan, user_id, session_id)
        existing = self.store.list_jobs(user_id=user_id, session_id=session_id, statuses=["queued", "running"], job_type=UNIFIED_WORKER_JOB_TYPE, limit=100)
        for job in existing:
            if str(job.get("idempotency_key") or "") == key:
                return job
        if self.store.count_active_jobs(user_id=user_id, job_type=UNIFIED_WORKER_JOB_TYPE) >= self.limits.max_queue_per_user:
            return _blocked_job(code="WORKER_QUEUE_LIMIT_EXCEEDED", message="该用户后台任务队列已满。", user_id=user_id, session_id=session_id)
        if self.store.count_active_jobs(user_id=user_id, session_id=session_id, job_type=UNIFIED_WORKER_JOB_TYPE) >= self.limits.max_queue_per_session:
            return _blocked_job(code="WORKER_SESSION_QUEUE_LIMIT_EXCEEDED", message="该会话后台任务队列已满。", user_id=user_id, session_id=session_id)
        disk = self._disk_blocker()
        if disk:
            return _blocked_job(code=disk["code"], message=disk["message"], user_id=user_id, session_id=session_id)
        payload = {
            "plan": plan,
            "context": context,
            "steps": _plan_steps(plan),
            "task_plan_version": str(plan.get("schema_version") or plan.get("version") or ""),
            "input_asset_ids": [str(item.get("name") or item.get("asset_id") or "") for item in _as_list(plan.get("input_assets")) if isinstance(item, dict)],
            "input_hash": hashlib.sha256(json.dumps(plan.get("input_assets") or [], ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
            "events": [{"time": _now(), "phase": "queued", "level": "info", "message": "任务已进入后台队列。"}],
        }
        return self.store.submit_job(
            plan_id=str(plan.get("plan_id") or ""),
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
            job_type=UNIFIED_WORKER_JOB_TYPE,
            idempotency_key=key,
            payload=payload,
            max_attempts=1,
        )

    def cancel_job(self, job_id: str, *, user_id: str = "", reason: str = "") -> dict[str, Any]:
        return self.store.cancel_job(job_id, user_id=user_id, reason=reason or "用户取消任务。")

    def run_next_job(self) -> dict[str, Any]:
        job = self.store.next_queued_job(job_type=UNIFIED_WORKER_JOB_TYPE)
        if not job:
            return {"status": "idle", "executed": False}
        job_id = str(job.get("job_id") or "")
        if str(job.get("status") or "") == "cancelled":
            return job
        return self._run_job(job_id)

    def _run_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if str(job.get("status") or "") == "cancelled":
            return job
        payload = _as_dict(job.get("payload"))
        plan = _as_dict(payload.get("plan"))
        context = _as_dict(payload.get("context"))
        steps = [step for step in _as_list(payload.get("steps")) if isinstance(step, dict)]
        if not steps:
            failed = tool_result_error(
                UNIFIED_WORKER_JOB_TYPE,
                error_code="WORKER_PLAN_HAS_NO_STEPS",
                error_title="计划没有可执行步骤",
                user_message="已验证计划中没有可执行的 workflow step。",
            ).to_dict()
            return self.store.update_status(job_id, "failed", progress=100, error_code="WORKER_PLAN_HAS_NO_STEPS", error_message="Plan has no executable steps.", result={"tool_result": failed})
        token = CancellationToken(self.store, job_id)
        self.store.update_status(job_id, "running", progress=1, phase="starting", current_step="准备后台任务执行")
        started = time.monotonic()
        results: list[dict[str, Any]] = []
        completed: dict[str, dict[str, Any]] = {}
        try:
            for index, step in enumerate(steps):
                token.raise_if_cancelled()
                if time.monotonic() - started > self.limits.max_runtime_seconds:
                    raise TimeoutError("worker runtime exceeded")
                step_id = str(step.get("step_id") or f"step_{index + 1}")
                tool_name = str(step.get("tool_name") or "")
                self.store.update_status(
                    job_id,
                    "running",
                    progress=max(1, int(index / max(len(steps), 1) * 90)),
                    phase="tool_execution",
                    current_step=tool_name or step_id,
                )
                kwargs = {"completed_results": completed, "context": self.runtime_context}
                try:
                    if "cancellation_token" in inspect.signature(self.step_executor).parameters:
                        kwargs["cancellation_token"] = token
                except Exception:
                    pass
                execution = self.step_executor(self.manager, step, **kwargs)
                token.raise_if_cancelled()
                result = normalize_tool_result(_as_dict(execution).get("tool_result") if isinstance(execution, dict) else {})
                result["step_id"] = str(step.get("step_id") or result.get("step_id") or f"step_{index + 1}")
                result["tool_name"] = str(step.get("tool_name") or result.get("tool_name") or "")
                results.append(result)
                completed[result["step_id"]] = result
                if str(result.get("status") or "") in {"failed", "blocked", "awaiting_confirmation"}:
                    break
            trace = build_execution_trace(plan, {"tool_results": results}, plan_id=str(plan.get("plan_id") or job.get("plan_id") or ""))
            final_status = str(trace.status)
            durable_status = {
                "succeeded": "succeeded",
                "failed": "failed",
                "blocked": "failed",
                "awaiting_confirmation": "awaiting_confirmation",
                "running": "running",
            }.get(final_status, "failed")
            return self.store.update_status(
                job_id,
                durable_status,
                progress=100 if durable_status in {"succeeded", "failed", "awaiting_confirmation"} else 90,
                phase="complete" if durable_status == "succeeded" else final_status,
                current_step="后台任务执行结束",
                result={
                    "execution_trace": trace.model_dump(mode="json"),
                    "normalized_results": [item.model_dump(mode="json") for item in trace.results],
                    "events": [{"time": _now(), "phase": final_status, "level": "info", "message": "后台任务执行结束。"}],
                },
            )
        except WorkerCancelled:
            return self.store.cancel_job(job_id, reason="Job was cancelled before completion.")
        except TimeoutError:
            failed = tool_result_error(
                UNIFIED_WORKER_JOB_TYPE,
                error_code="WORKER_RUNTIME_LIMIT_EXCEEDED",
                error_title="任务运行超时",
                user_message="后台任务超过允许运行时间，已停止。",
            ).to_dict()
            return self.store.update_status(
                job_id,
                "failed",
                progress=100,
                phase="timeout",
                current_step="后台任务运行超时",
                error_code="WORKER_RUNTIME_LIMIT_EXCEEDED",
                error_message="Worker runtime exceeded.",
                timeout_reason=f"超过最大运行时间 {self.limits.max_runtime_seconds} 秒",
                result={"tool_result": failed},
            )
        except Exception as exc:
            failed = tool_result_error(
                UNIFIED_WORKER_JOB_TYPE,
                error_code="WORKER_EXECUTION_FAILED",
                error_title="后台任务失败",
                user_message="后台任务执行失败，未生成成功结果。",
                technical_detail=f"{type(exc).__name__}: {exc}",
            ).to_dict()
            return self.store.update_status(job_id, "failed", progress=100, phase="error", current_step="后台任务执行失败", error_code="WORKER_EXECUTION_FAILED", error_message="Worker execution failed.", result={"tool_result": failed})

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.is_set():
                self.run_next_job()
                time.sleep(self.limits.poll_interval_seconds)

        self._thread = threading.Thread(target=loop, name="UnifiedBackgroundWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def recover_interrupted_worker_jobs(store: DurableJobStore) -> dict[str, Any]:
    return store.recover_interrupted_jobs()
