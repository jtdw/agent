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


def _shared_workdir(workdir: str | Path) -> Path:
    path = Path(workdir)
    if path.parent.name == "users":
        return path.parent.parent
    if path.name == "anonymous":
        return path.parent
    return path


def gscloud_tile_jobs_dir(workdir: str | Path) -> Path:
    path = _shared_workdir(workdir) / "domestic_auth" / "tile_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_gscloud_tile_jobs(workdir: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(
        gscloud_tile_jobs_dir(workdir).glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[: max(1, int(limit or 20))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("status_path", str(path))
            items.append(data)
        except Exception:
            items.append({"status_path": str(path), "state": "UNREADABLE"})
    return items


def read_gscloud_tile_job(workdir: str | Path, tile_job_id: str) -> dict[str, Any]:
    path = gscloud_tile_jobs_dir(workdir) / f"{tile_job_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到自动分幅下载任务状态文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def start_gscloud_tile_process(
    *,
    workdir: str | Path,
    job_id: str,
    region: str = "四川省",
    region_dataset: str = "",
    dataset_id: str = "310",
    product_key: str = "aster_gdem_30m",
    pid: str = "1",
    max_tiles: int = 0,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
) -> dict[str, Any]:
    """Start automatic GSCloud ASTER/GDEM tile planning and downloading in a separate process.

    This is different from capture mode: it does not ask the user to decide which tile
    to click. The worker first calculates ASTGTM_NxxExxx tile IDs from the region,
    then scans every pagination page and clicks only rows whose ASTGTM tile IDs match the target region.
    """
    timeout_seconds = max(30, int(timeout_seconds or 1800))
    max_tiles = max(0, int(max_tiles or 0))
    workdir = _shared_workdir(workdir)
    tile_job_id = f"tile_{uuid4().hex[:12]}"
    status_path = gscloud_tile_jobs_dir(workdir) / f"{tile_job_id}.json"
    log_path = status_path.with_suffix(".log")

    manifest: dict[str, Any] = {
        "tile_job_id": tile_job_id,
        "source_key": "gscloud",
        "job_id": job_id,
        "region": region,
        "region_dataset": region_dataset,
        "dataset_id": dataset_id,
        "product_key": product_key,
        "pid": pid,
        "max_tiles": max_tiles,
        "timeout_seconds": timeout_seconds,
        "headless": bool(headless),
        "auto_load": bool(auto_load),
        "state": "STARTING",
        "message": "正在启动地理空间数据云 DEM 自动分幅下载任务。该任务会自动计算区域分幅、扫描全部分页并校验下载文件，不要求用户手动选择。",
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
        "core.commercial.gscloud_tile_worker",
        "--status-path",
        str(status_path),
    ]

    env = os.environ.copy()
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
        "state": "PLANNING",
        "message": "已在独立后台进程中启动自动分幅下载。系统会先计算分幅，再扫描全部分页，仅下载目标分幅；不会弹出网页让用户手动选择。本次对话不会阻塞。",
        "process_id": proc.pid,
        "updated_at": _now(),
    })
    _safe_write_json(status_path, manifest)
    return manifest
