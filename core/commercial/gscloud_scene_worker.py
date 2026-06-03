from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..data_manager import DataManager
from ..domestic_sources.gscloud_adapter import gscloud_platform_state_path, gscloud_user_state_path
from ..domestic_sources.gscloud_landsat import download_landsat8_oli_tirs_scenes
from ..domestic_sources.gscloud_modev1f import download_modev1f_china_evi_5day
from ..domestic_sources.gscloud_mod021km import download_mod021km_surface_reflectance
from ..domestic_sources.gscloud_modl1d import download_modl1d_china_lst_daily
from ..domestic_sources.gscloud_modnd1d import download_modnd1d_china_ndvi_daily
from ..domestic_sources.gscloud_reliability import classify_gscloud_failure, inspect_storage_state, resolve_download_region
from ..domestic_sources.gscloud_sentinel2 import download_sentinel2_msi_scenes
from .service import CommercialService


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
    parser = argparse.ArgumentParser(description="GSCloud scene-table product worker")
    parser.add_argument("--status-path", required=True)
    args = parser.parse_args()

    status_path = Path(args.status_path)
    current: dict[str, Any] = json.loads(status_path.read_text(encoding="utf-8"))
    workdir = Path(status_path).parents[2]
    job_id = current["job_id"]

    try:
        service = CommercialService(workdir)
        manager = DataManager(workdir)
        job = service.get_job(job_id)
        product_key = str(current.get("product_key") or job.get("resource_type") or "")
        if "modl1d" in product_key:
            stage = "scanning_gscloud_modl1d"
        elif "modnd1d" in product_key:
            stage = "scanning_gscloud_modnd1d"
        elif "modev1f" in product_key:
            stage = "scanning_gscloud_modev1f"
        elif "mod021km" in product_key:
            stage = "scanning_gscloud_mod021km"
        elif "sentinel2" in product_key:
            stage = "scanning_gscloud_sentinel2"
        else:
            stage = "scanning_gscloud_landsat8"
        service._update_job(job_id, status="running", progress=12, stage=stage)

        state_path = _resolve_storage_state_with_fallback(service, workdir, job)
        login_health = inspect_storage_state(state_path) if state_path else inspect_storage_state("")
        if not login_health.get("ok"):
            diagnostic = classify_gscloud_failure("未找到可用地理空间数据云登录态")
            current.update({
                "state": "WAITING_LOGIN",
                "message": diagnostic["user_message"],
                "login_health": login_health,
                "failure_diagnostic": diagnostic,
                "updated_at": _now(),
            })
            _safe_write_json(status_path, current)
            service._update_job(
                job_id,
                status="waiting_login",
                progress=5,
                stage="needs_gscloud_login_state",
                error_message=diagnostic["user_message"],
            )
            return 2

        resolved_region = resolve_download_region(
            str(current.get("request_text") or job.get("request_text") or ""),
            str(current.get("region") or job.get("region") or ""),
        )
        if not resolved_region.get("ok"):
            diagnostic = {
                "code": "region_required",
                "title": "需要明确下载区域",
                "user_message": resolved_region["message"],
                "next_action": resolved_region["next_action"],
            }
            current.update({
                "state": "WAITING_USER_INPUT",
                "message": resolved_region["message"],
                "region_resolution": resolved_region,
                "failure_diagnostic": diagnostic,
                "updated_at": _now(),
            })
            _safe_write_json(status_path, current)
            service._update_job(
                job_id,
                status="waiting_manual",
                progress=5,
                stage="needs_download_region",
                error_message=resolved_region["message"],
            )
            return 2
        actual_region = str(resolved_region.get("region") or current.get("region") or job.get("region") or "")

        current.update({
            "state": "SCANNING",
            "message": "正在打开地理空间数据云访问数据页，强制筛选“数据=有”，并扫描候选记录。",
            "job_snapshot": job,
            "storage_state_path": state_path,
            "updated_at": _now(),
        })
        _safe_write_json(status_path, current)

        if "modl1d" in product_key:
            service._update_job(job_id, status="running", progress=35, stage="filtering_modl1d_available_lst")
            result = download_modl1d_china_lst_daily(
                manager=manager,
                storage_state_path=state_path,
                region=actual_region,
                output_name=job.get("output_name") or "modl1d_lst",
                year=str(current.get("year") or ""),
                start_date=str(current.get("start_date") or job.get("start_date") or ""),
                end_date=str(current.get("end_date") or job.get("end_date") or ""),
                include_quality=bool(current.get("include_quality", False)),
                max_scenes=int(current.get("max_scenes") or 1),
                timeout_seconds=int(current.get("timeout_seconds") or 1800),
                headless=bool(current.get("headless", True)),
                auto_load=bool(current.get("auto_load", True)),
                status_path=status_path,
            )
        elif "modnd1d" in product_key:
            service._update_job(job_id, status="running", progress=35, stage="filtering_modnd1d_available_ndvi")
            result = download_modnd1d_china_ndvi_daily(
                manager=manager,
                storage_state_path=state_path,
                region=actual_region,
                output_name=job.get("output_name") or "modnd1d_ndvi",
                year=str(current.get("year") or ""),
                start_date=str(current.get("start_date") or job.get("start_date") or ""),
                end_date=str(current.get("end_date") or job.get("end_date") or ""),
                include_qc=bool(current.get("include_qc", False)),
                max_scenes=int(current.get("max_scenes") or 1),
                timeout_seconds=int(current.get("timeout_seconds") or 1800),
                headless=bool(current.get("headless", True)),
                auto_load=bool(current.get("auto_load", True)),
                status_path=status_path,
            )
        elif "modev1f" in product_key:
            service._update_job(job_id, status="running", progress=35, stage="filtering_modev1f_available_evi")
            result = download_modev1f_china_evi_5day(
                manager=manager,
                storage_state_path=state_path,
                region=actual_region,
                output_name=job.get("output_name") or "modev1f_evi",
                year=str(current.get("year") or ""),
                start_date=str(current.get("start_date") or job.get("start_date") or ""),
                end_date=str(current.get("end_date") or job.get("end_date") or ""),
                max_scenes=int(current.get("max_scenes") or 1),
                timeout_seconds=int(current.get("timeout_seconds") or 1800),
                headless=bool(current.get("headless", True)),
                auto_load=bool(current.get("auto_load", True)),
                status_path=status_path,
            )
        elif "mod021km" in product_key:
            service._update_job(job_id, status="running", progress=35, stage="filtering_mod021km_available_reflectance")
            result = download_mod021km_surface_reflectance(
                manager=manager,
                storage_state_path=state_path,
                region=actual_region,
                output_name=job.get("output_name") or "mod021km_reflectance",
                year=str(current.get("year") or ""),
                start_date=str(current.get("start_date") or job.get("start_date") or ""),
                end_date=str(current.get("end_date") or job.get("end_date") or ""),
                max_scenes=int(current.get("max_scenes") or 1),
                timeout_seconds=int(current.get("timeout_seconds") or 1800),
                headless=bool(current.get("headless", True)),
                auto_load=bool(current.get("auto_load", True)),
                status_path=status_path,
            )
        elif "sentinel2" in product_key:
            service._update_job(job_id, status="running", progress=35, stage="filtering_sentinel2_available_scenes")
            result = download_sentinel2_msi_scenes(
                manager=manager,
                storage_state_path=state_path,
                region=actual_region,
                output_name=job.get("output_name") or "sentinel2_msi",
                year=str(current.get("year") or ""),
                start_date=str(current.get("start_date") or job.get("start_date") or ""),
                end_date=str(current.get("end_date") or job.get("end_date") or ""),
                processing_level=str(current.get("processing_level") or ""),
                max_scenes=int(current.get("max_scenes") or 1),
                timeout_seconds=int(current.get("timeout_seconds") or 1800),
                headless=bool(current.get("headless", True)),
                auto_load=bool(current.get("auto_load", True)),
                status_path=status_path,
            )
        else:
            service._update_job(job_id, status="running", progress=35, stage="filtering_landsat8_available_scenes")
            result = download_landsat8_oli_tirs_scenes(
                manager=manager,
                storage_state_path=state_path,
                region=actual_region,
                output_name=job.get("output_name") or "landsat8_oli_tirs",
                year=str(current.get("year") or ""),
                start_date=str(current.get("start_date") or job.get("start_date") or ""),
                end_date=str(current.get("end_date") or job.get("end_date") or ""),
                cloud_max=float(current.get("cloud_max") or 30),
                max_scenes=int(current.get("max_scenes") or 1),
                timeout_seconds=int(current.get("timeout_seconds") or 1800),
                headless=bool(current.get("headless", True)),
                auto_load=bool(current.get("auto_load", True)),
                status_path=status_path,
            )

        service._update_job(job_id, status="running", progress=90, stage="packaging_scene_result")
        done = service.run_job_with_result(job_id, result)
        current.update({
            "state": "COMPLETED",
            "message": "地理空间数据云场景产品已完成检索、下载、解压/入库和打包。",
            "result": result,
            "job": done,
            "updated_at": _now(),
            "finished_at": _now(),
        })
        _safe_write_json(status_path, current)
        return 0
    except Exception as exc:
        diagnostic = classify_gscloud_failure(exc)
        try:
            service = CommercialService(workdir)
            failed = service.fail_job(job_id, diagnostic["user_message"])
        except Exception:
            failed = None
        current.update({
            "state": "FAILED",
            "message": diagnostic["user_message"],
            "error": str(exc),
            "failure_diagnostic": diagnostic,
            "job": failed,
            "updated_at": _now(),
            "finished_at": _now(),
        })
        _safe_write_json(status_path, current)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
