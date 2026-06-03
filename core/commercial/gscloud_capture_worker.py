from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..data_manager import DataManager
from .service import CommercialService
from ..domestic_sources.gscloud_adapter import (
    GSCLOUD_ASTER_GDEM30_ACCESS_URL,
    capture_gscloud_downloads,
    plan_aster_gdem_tiles,
    gscloud_platform_state_path,
    gscloud_user_state_path,
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _resolve_storage_state_with_fallback(service: CommercialService, workdir: Path, job: dict[str, Any]) -> str:
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
    parser = argparse.ArgumentParser(description="GSCloud DEM capture worker")
    parser.add_argument("--status-path", required=True)
    args = parser.parse_args()

    status_path = Path(args.status_path)
    manifest: dict[str, Any] = json.loads(status_path.read_text(encoding="utf-8"))
    current = dict(manifest)
    workdir = Path(status_path).parents[2]  # .../workdir/domestic_auth/capture_jobs/<id>.json
    job_id = current["job_id"]

    try:
        service = CommercialService(workdir)
        manager = DataManager(workdir)
        job = service.get_job(job_id)
        service._update_job(job_id, status="running", progress=15, stage="opening_gscloud_capture_browser")

        state_path = _resolve_storage_state_with_fallback(service, workdir, job)
        if not state_path or not Path(state_path).exists():
            raise RuntimeError(
                "未找到可用地理空间数据云登录态。请先完成平台账号或用户账号登录保存 Cookie；"
                "登录成功后等待 5-10 秒再启动捕获下载。"
            )

        plan = plan_aster_gdem_tiles(
            manager=manager,
            region=job.get("region") or "四川省",
            region_dataset=current.get("region_dataset") or "",
            output_name=(job.get("output_name") or "gscloud_dem") + "_tile_plan",
            bbox_only=False,
            save_preview=True,
        )
        expected_tile_ids = list(plan.get("tile_ids") or [])

        current.update({
            "state": "BROWSER_OPEN",
            "message": (
                "浏览器已打开。请只下载系统分幅清单中的文件；"
                "如果下载了错误分幅，任务会被拦截，不会被标记为四川 DEM 已完成。"
            ),
            "job_snapshot": job,
            "storage_state_path": state_path,
            "expected_tile_count": len(expected_tile_ids),
            "expected_tile_ids_preview": expected_tile_ids[:50],
            "tile_plan_files": plan.get("derived_files", {}),
            "updated_at": _now(),
        })
        _safe_write_json(status_path, current)

        service._update_job(job_id, status="running", progress=35, stage="waiting_download_click_with_tile_validation")
        result = capture_gscloud_downloads(
            manager=manager,
            start_url=current.get("start_url") or GSCLOUD_ASTER_GDEM30_ACCESS_URL,
            storage_state_path=state_path,
            output_name=job.get("output_name") or "gscloud_dem",
            max_downloads=int(current.get("max_downloads") or 1),
            timeout_seconds=int(current.get("timeout_seconds") or 1800),
            headless=bool(current.get("headless", False)),
            auto_load=bool(current.get("auto_load", True)),
            expected_tile_ids=expected_tile_ids,
            require_all_expected=True,
        )

        service._update_job(job_id, status="running", progress=85, stage="packaging_result")
        done = service.run_job_with_result(job_id, result)
        current.update({
            "state": "COMPLETED",
            "message": "已捕获下载文件并完成解压、入库和打包。",
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
            "message": "地理空间数据云 DEM 捕获下载失败。",
            "error": str(exc),
            "job": failed,
            "updated_at": _now(),
            "finished_at": _now(),
        })
        _safe_write_json(status_path, current)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
