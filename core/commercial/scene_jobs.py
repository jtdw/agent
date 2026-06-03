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


def gscloud_scene_jobs_dir(workdir: str | Path) -> Path:
    path = _shared_workdir(workdir) / "domestic_auth" / "scene_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_gscloud_scene_jobs(workdir: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(gscloud_scene_jobs_dir(workdir).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, int(limit or 20))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("status_path", str(path))
            items.append(data)
        except Exception:
            items.append({"status_path": str(path), "state": "UNREADABLE"})
    return items


def read_gscloud_scene_job(workdir: str | Path, scene_job_id: str) -> dict[str, Any]:
    path = gscloud_scene_jobs_dir(workdir) / f"{scene_job_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到场景下载任务状态文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def start_gscloud_scene_process(
    *,
    workdir: str | Path,
    job_id: str,
    product_key: str,
    region: str,
    start_message: str,
    running_message: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workdir = _shared_workdir(workdir)
    scene_job_id = f"scene_{uuid4().hex[:12]}"
    status_path = gscloud_scene_jobs_dir(workdir) / f"{scene_job_id}.json"
    log_path = status_path.with_suffix(".log")
    manifest: dict[str, Any] = {
        "scene_job_id": scene_job_id,
        "source_key": "gscloud",
        "product_key": product_key,
        "job_id": job_id,
        "region": region,
        "year": year,
        "start_date": start_date,
        "end_date": end_date,
        "max_scenes": max(1, int(max_scenes or 1)),
        "timeout_seconds": max(30, int(timeout_seconds or 1800)),
        "headless": bool(headless),
        "auto_load": bool(auto_load),
        "state": "STARTING",
        "message": start_message,
        "status_path": str(status_path),
        "log_path": str(log_path),
        "created_at": _now(),
        "updated_at": _now(),
    }
    if extra:
        manifest.update(extra)
    _safe_write_json(status_path, manifest)

    project_root = Path(__file__).resolve().parents[2]
    cmd = [sys.executable, "-m", "core.commercial.gscloud_scene_worker", "--status-path", str(status_path)]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    with open(log_path, "a", encoding="utf-8") as log_fh:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
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
    manifest.update({
        "state": "SCANNING",
        "message": running_message,
        "process_id": proc.pid,
        "updated_at": _now(),
    })
    _safe_write_json(status_path, manifest)
    return manifest


def start_gscloud_landsat8_process(
    *,
    workdir: str | Path,
    job_id: str,
    region: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    cloud_max: float = 30.0,
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
) -> dict[str, Any]:
    return start_gscloud_scene_process(
        workdir=workdir,
        job_id=job_id,
        product_key="landsat8_oli_tirs",
        region=region,
        year=year,
        start_date=start_date,
        end_date=end_date,
        max_scenes=max_scenes,
        timeout_seconds=timeout_seconds,
        headless=headless,
        auto_load=auto_load,
        extra={"cloud_max": float(cloud_max)},
        start_message="正在启动 Landsat 8 OLI_TIRS 自动检索下载任务。任务会强制筛选“数据=有”，并按云量、日期和区域中心排序。",
        running_message="已在独立后台进程启动 Landsat 8 检索下载。当前对话不会阻塞。",
    )


def start_gscloud_modnd1d_process(
    *,
    workdir: str | Path,
    job_id: str,
    region: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    include_qc: bool = False,
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
) -> dict[str, Any]:
    return start_gscloud_scene_process(
        workdir=workdir,
        job_id=job_id,
        product_key="modnd1d_china_500m_ndvi_daily",
        region=region,
        year=year,
        start_date=start_date,
        end_date=end_date,
        max_scenes=max_scenes,
        timeout_seconds=timeout_seconds,
        headless=headless,
        auto_load=auto_load,
        extra={"include_qc": bool(include_qc)},
        start_message="正在启动 MODND1D 中国 500M NDVI 每天产品自动检索下载任务。任务会强制筛选“数据=有”，默认只下载 NDVI 主产品。",
        running_message="已在独立后台进程启动 MODND1D NDVI 检索下载。当前对话不会阻塞。",
    )


def start_gscloud_modl1d_process(
    *,
    workdir: str | Path,
    job_id: str,
    region: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    include_quality: bool = False,
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
) -> dict[str, Any]:
    return start_gscloud_scene_process(
        workdir=workdir,
        job_id=job_id,
        product_key="modl1d_china_1km_lst_daily",
        region=region,
        year=year,
        start_date=start_date,
        end_date=end_date,
        max_scenes=max_scenes,
        timeout_seconds=timeout_seconds,
        headless=headless,
        auto_load=auto_load,
        extra={"include_quality": bool(include_quality)},
        start_message="正在启动 MODL1D 中国 1KM 地表温度每天产品自动检索下载任务。任务会强制筛选“数据=有”，默认只下载 LTD/LTN 主产品。",
        running_message="已在独立后台进程启动 MODL1D 地表温度检索下载。当前对话不会阻塞。",
    )


def start_gscloud_modev1f_process(
    *,
    workdir: str | Path,
    job_id: str,
    region: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
) -> dict[str, Any]:
    return start_gscloud_scene_process(
        workdir=workdir,
        job_id=job_id,
        product_key="modev1f_china_250m_evi_5day",
        region=region,
        year=year,
        start_date=start_date,
        end_date=end_date,
        max_scenes=max_scenes,
        timeout_seconds=timeout_seconds,
        headless=headless,
        auto_load=auto_load,
        start_message="正在启动 MODEV1F 中国 250M EVI 五天合成产品自动检索下载任务。任务会强制筛选“数据=有”的 EVI 记录。",
        running_message="已在独立后台进程启动 MODEV1F EVI 检索下载。当前对话不会阻塞。",
    )


def start_gscloud_mod021km_process(
    *,
    workdir: str | Path,
    job_id: str,
    region: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
) -> dict[str, Any]:
    return start_gscloud_scene_process(
        workdir=workdir,
        job_id=job_id,
        product_key="mod021km_1km_surface_reflectance",
        region=region,
        year=year,
        start_date=start_date,
        end_date=end_date,
        max_scenes=max_scenes,
        timeout_seconds=timeout_seconds,
        headless=headless,
        auto_load=auto_load,
        start_message="正在启动 MOD021KM 1KM 地表反射率自动检索下载任务。任务会强制筛选“数据=有”的记录。",
        running_message="已在独立后台进程启动 MOD021KM 地表反射率检索下载。当前对话不会阻塞。",
    )


def start_gscloud_sentinel2_process(
    *,
    workdir: str | Path,
    job_id: str,
    region: str,
    year: str = "",
    start_date: str = "",
    end_date: str = "",
    processing_level: str = "",
    max_scenes: int = 1,
    timeout_seconds: int = 1800,
    headless: bool = True,
    auto_load: bool = True,
) -> dict[str, Any]:
    return start_gscloud_scene_process(
        workdir=workdir,
        job_id=job_id,
        product_key="sentinel2_msi",
        region=region,
        year=year,
        start_date=start_date,
        end_date=end_date,
        max_scenes=max_scenes,
        timeout_seconds=timeout_seconds,
        headless=headless,
        auto_load=auto_load,
        extra={"processing_level": processing_level},
        start_message="正在启动 Sentinel-2 自动检索下载任务。任务会强制筛选“数据=有”的记录。",
        running_message="已在独立后台进程启动 Sentinel-2 检索下载。当前对话不会阻塞。",
    )
