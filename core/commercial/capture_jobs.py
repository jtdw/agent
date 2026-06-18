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


def gscloud_capture_jobs_dir(workdir: str | Path) -> Path:
    path = Path(workdir) / "domestic_auth" / "capture_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_gscloud_capture_jobs(workdir: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(gscloud_capture_jobs_dir(workdir).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, int(limit or 20))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("status_path", str(path))
            items.append(data)
        except Exception:
            items.append({"status_path": str(path), "state": "UNREADABLE"})
    return items


def read_gscloud_capture_job(workdir: str | Path, capture_job_id: str) -> dict[str, Any]:
    path = gscloud_capture_jobs_dir(workdir) / f"{capture_job_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到捕获下载任务状态文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def start_gscloud_capture_process(
    *,
    workdir: str | Path,
    job_id: str,
    start_url: str = "",
    max_downloads: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = False,
    auto_load: bool = True,
) -> dict[str, Any]:
    """Start a visible GSCloud download-capture browser in a separate process.

    This avoids relying on the LLM to call the capture tool and prevents the chat
    request from blocking while the operator manually clicks a download button.
    """
    timeout_seconds = max(30, int(timeout_seconds or 1800))
    max_downloads = max(1, int(max_downloads or 1))
    workdir = Path(workdir)
    capture_job_id = f"capture_{uuid4().hex[:12]}"
    status_path = gscloud_capture_jobs_dir(workdir) / f"{capture_job_id}.json"
    log_path = status_path.with_suffix(".log")

    manifest: dict[str, Any] = {
        "capture_job_id": capture_job_id,
        "source_key": "gscloud",
        "job_id": job_id,
        "state": "STARTING",
        "message": "正在启动地理空间数据云 DEM 捕获下载窗口。",
        "start_url": start_url,
        "max_downloads": max_downloads,
        "timeout_seconds": timeout_seconds,
        "headless": bool(headless),
        "auto_load": bool(auto_load),
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
        "core.commercial.gscloud_capture_worker",
        "--status-path",
        str(status_path),
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

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
        "message": "已在独立后台进程中打开捕获下载窗口。请在弹出的地理空间数据云页面中点击下载按钮；本次对话不会被阻塞。",
        "process_id": proc.pid,
        "updated_at": _now(),
    })
    _safe_write_json(status_path, manifest)
    return manifest
