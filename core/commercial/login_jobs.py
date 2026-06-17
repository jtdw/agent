from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def gscloud_login_jobs_dir(workdir: str | Path) -> Path:
    path = Path(workdir) / "domestic_auth" / "login_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_gscloud_login_jobs(workdir: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(gscloud_login_jobs_dir(workdir).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, int(limit or 20))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("status_path", str(path))
            items.append(data)
        except Exception:
            items.append({"status_path": str(path), "state": "UNREADABLE"})
    return items


def read_gscloud_login_job(workdir: str | Path, login_job_id: str) -> dict[str, Any]:
    path = gscloud_login_jobs_dir(workdir) / f"{login_job_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到登录任务状态文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def request_gscloud_login_job_close(workdir: str | Path, login_job_id: str, *, reason: str = "login_completed") -> dict[str, Any]:
    path = gscloud_login_jobs_dir(workdir) / f"{login_job_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"login job not found: {login_job_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(
        {
            "close_requested": True,
            "close_reason": reason,
            "updated_at": _now(),
        }
    )
    _safe_write_json(path, data)
    return data


def start_gscloud_login_process(
    *,
    workdir: str | Path,
    subject_type: str,
    subject_id: str,
    state_path: str | Path,
    timeout_seconds: int = 300,
    headless: bool = False,
) -> dict[str, Any]:
    """Start a visible GSCloud login browser in a separate Python process.

    Why a process instead of calling Playwright inside the chat request:
    - The old blocking implementation kept the whole UI request open for 300s.
    - Streamlit/desktop reruns may close the Playwright pipe while Node still writes,
      which can surface as Node EPIPE and leave the UI stuck.
    - A short-lived detached worker owns Playwright, updates a JSON status file, and
      returns control to the chat immediately.
    """
    timeout_seconds = max(30, int(timeout_seconds or 300))
    workdir = Path(workdir)
    state_path = Path(state_path)
    login_job_id = f"login_{uuid4().hex[:12]}"
    status_path = gscloud_login_jobs_dir(workdir) / f"{login_job_id}.json"
    log_path = status_path.with_suffix(".log")

    manifest: dict[str, Any] = {
        "login_job_id": login_job_id,
        "source_key": "gscloud",
        "subject_type": subject_type,
        "subject_id": subject_id,
        "state": "STARTING",
        "message": "正在启动地理空间数据云登录窗口。",
        "timeout_seconds": timeout_seconds,
        "headless": bool(headless),
        "state_path": str(state_path),
        "status_path": str(status_path),
        "log_path": str(log_path),
        "created_at": _now(),
        "updated_at": _now(),
    }
    _safe_write_json(status_path, manifest)

    project_root = Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        "-m",
        "core.commercial.gscloud_login_worker",
        "--status-path",
        str(status_path),
    ]

    env = os.environ.copy()
    # Ensure the project root is importable when launched from desktop/web UI.
    env["PYTHONPATH"] = str(project_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    log_fh = open(log_path, "a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=(os.name != "nt"),
        creationflags=creationflags,
    )
    log_fh.close()

    manifest.update({
        "state": "BROWSER_OPENING",
        "message": "已在独立后台进程中打开登录窗口，本次对话不会再被阻塞。请在浏览器中完成登录；可以继续向智能体发送消息。",
        "process_id": proc.pid,
        "updated_at": _now(),
    })
    _safe_write_json(status_path, manifest)
    return manifest


# Backward-compatible alias for older imports in agent.py.
def start_gscloud_login_thread(**kwargs: Any) -> dict[str, Any]:
    kwargs.pop("save_callback", None)
    return start_gscloud_login_process(**kwargs)
