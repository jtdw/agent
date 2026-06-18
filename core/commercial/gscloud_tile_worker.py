from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..data_manager import DataManager
from .service import CommercialService
from ..domestic_sources.gscloud_adapter import (
    plan_gscloud_dem_tiles,
    gscloud_platform_state_path,
    gscloud_user_state_path,
)
from ..domestic_sources.raster_postprocess import standardize_raster_download_result
from ..domestic_sources.gscloud_stable_downloader import download_gscloud_tiles_by_identifier_search


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _resolve_storage_state_with_fallback(service: CommercialService, workdir: Path, job: dict[str, Any]) -> str:
    """Resolve cookie path even if DB has not been updated by the login worker yet."""
    state_path = service.resolve_job_storage_state_path(job.get("job_id", ""))
    if state_path and Path(state_path).exists():
        return str(state_path)

    mode = str(job.get("account_mode") or "").lower()
    source_key = str(job.get("source_key") or "gscloud").lower() or "gscloud"
    if mode in {"platform", "platform_account"}:
        account_id = str(job.get("account_id") or "")
        if account_id:
            expected = gscloud_platform_state_path(workdir, account_id, source_key)
            try:
                service.set_platform_account_storage_state(account_id, str(expected))
            except Exception:
                pass
            if expected.exists():
                return str(expected)
    if mode in {"own", "user", "user_account", "manual_cookie"}:
        user_id = str(job.get("user_id") or "")
        if user_id:
            expected = gscloud_user_state_path(workdir, user_id, source_key)
            try:
                service.set_user_credential_storage_state(user_id, source_key, str(expected))
            except Exception:
                pass
            if expected.exists():
                return str(expected)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="GSCloud ASTER/GDEM automatic tile worker")
    parser.add_argument("--status-path", required=True)
    args = parser.parse_args()

    status_path = Path(args.status_path)
    manifest: dict[str, Any] = json.loads(status_path.read_text(encoding="utf-8"))
    current = dict(manifest)
    # .../<workdir>/domestic_auth/tile_jobs/<id>.json
    workdir = Path(status_path).parents[2]
    job_id = current["job_id"]

    try:
        service = CommercialService(workdir)
        manager = DataManager(workdir)
        job = service.get_job(job_id)
        service._update_job(job_id, status="running", progress=8, stage="planning_gscloud_dem_tiles")

        state_path = _resolve_storage_state_with_fallback(service, workdir, job)
        if not state_path or not Path(state_path).exists():
            raise RuntimeError(
                "未找到可用地理空间数据云登录态。请先完成平台账号或用户账号登录保存 Cookie；"
                "登录成功后等待 5-10 秒再启动自动分幅下载。"
            )

        region = current.get("region") or job.get("region") or "四川省"
        region_dataset = current.get("region_dataset") or ""
        output_name = job.get("output_name") or f"{region}_gscloud_dem"

        current.update({
            "state": "PLANNING",
            "message": "正在根据区域边界计算 ASTER/GDEM 1°×1° 分幅。",
            "job_snapshot": job,
            "storage_state_path": state_path,
            "updated_at": _now(),
        })
        _safe_write_json(status_path, current)

        plan = plan_gscloud_dem_tiles(
            manager=manager,
            region=region,
            region_dataset=region_dataset,
            output_name=f"{output_name}_tile_plan",
            bbox_only=False,
            save_preview=True,
            dataset_id=str(current.get("dataset_id") or "310"),
        )
        ids = list(plan.get("tile_ids") or [])
        max_tiles = int(current.get("max_tiles") or 0)
        if max_tiles > 0:
            ids = ids[:max_tiles]
        if not ids:
            raise RuntimeError("没有计算出可下载分幅。")

        service._update_job(job_id, status="running", progress=20, stage="auto_downloading_gscloud_tiles")
        current.update({
            "state": "INDEXING_AND_AUTO_DOWNLOADING",
            "message": f"已计算出 {plan.get('tile_count')} 个分幅，开始按数据标识逐个精确搜索并自动下载目标分幅。",
            "tile_count_planned": plan.get("tile_count"),
            "tile_count_to_download": len(ids),
            "tile_ids_preview": ids[:30],
            "tile_plan": {k: v for k, v in plan.items() if k != "records"},
            "updated_at": _now(),
        })
        _safe_write_json(status_path, current)

        result = download_gscloud_tiles_by_identifier_search(
            manager=manager,
            tile_ids=ids,
            dataset_id=str(plan.get("dataset_id") or current.get("dataset_id") or "310"),
            pid=str(plan.get("pid") or "1"),
            tile_scheme=str(plan.get("tile_scheme") or "astgtm_1deg"),
            storage_state_path=state_path,
            output_name=output_name,
            timeout_seconds=int(current.get("timeout_seconds") or 1800),
            headless=bool(current.get("headless", True)),
            auto_load=bool(current.get("auto_load", True)),
            status_path=status_path,
        )
        result["tile_plan"] = {k: v for k, v in plan.items() if k != "records"}

        service._update_job(job_id, status="running", progress=86, stage="mosaicking_and_clipping_dem")
        current.update({
            "state": "STANDARDIZING_RASTER",
            "message": "分幅下载完成，正在执行标准栅格流程：解压、拼接、按区域边界裁剪、注册和打包。",
            "updated_at": _now(),
        })
        _safe_write_json(status_path, current)
        result = standardize_raster_download_result(
            manager=manager,
            result=result,
            output_name=output_name,
            clip_vector=str(plan.get("region_dataset") or ""),
        )

        service._update_job(job_id, status="running", progress=94, stage="packaging_result")
        done = service.run_job_with_result(job_id, result)
        current.update({
            "state": "COMPLETED",
            "message": "已按数据标识精确搜索并自动下载目标分幅，完成解压、自动拼接、按边界裁剪、入库和打包。",
            "result": result,
            "job": done,
            "updated_at": _now(),
            "finished_at": _now(),
        })
        _safe_write_json(status_path, current)
        return 0
    except Exception as exc:
        try:
            service = CommercialService(workdir)
            failed = service.fail_job(job_id, str(exc))
        except Exception:
            failed = None
        current.update({
            "state": "FAILED",
            "message": "地理空间数据云 DEM 自动分幅下载失败。",
            "error": str(exc),
            "job": failed,
            "updated_at": _now(),
            "finished_at": _now(),
        })
        _safe_write_json(status_path, current)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
