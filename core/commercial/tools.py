from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from langchain.tools import tool

from ..api_security import require_admin_token
from ..data_manager import DataManager
from ..domestic_sources.downloader import download_direct_url, postprocess_download
from ..domestic_sources.gscloud_adapter import (
    GSCLOUD_ASTER_GDEM30_ACCESS_URL,
    GSCLOUD_DEM_DATASETS,
    capture_gscloud_downloads,
    gscloud_platform_state_path,
    gscloud_user_state_path,
    open_login_and_save_state,
    parse_tile_ids,
    plan_aster_gdem_tiles,
    plan_gscloud_dem_tiles,
    resolve_gscloud_dem_product,
)
from ..domestic_sources.registry import get_source
from ..domestic_sources.gscloud_indexer import (
    scan_gscloud_dataset_index,
    download_gscloud_tiles_by_full_scan,
    query_index_for_tiles,
)
from ..domestic_sources.gscloud_stable_downloader import download_gscloud_tiles_by_identifier_search
from .security import generate_fernet_key
from .service import CommercialService
from .login_jobs import list_gscloud_login_jobs, read_gscloud_login_job, start_gscloud_login_process
from .capture_jobs import list_gscloud_capture_jobs, read_gscloud_capture_job, start_gscloud_capture_process
from .tile_jobs import list_gscloud_tile_jobs, read_gscloud_tile_job, start_gscloud_tile_process
from ..tool_contracts import download_job_to_tool_result


def _json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _download_job_payload(job: dict, **extra) -> dict:
    tool_result = _public_tool_result(download_job_to_tool_result(job))
    public_job = _public_download_job(job)
    payload = {
        "job": public_job,
        "tool_result": tool_result,
        "status": str(tool_result.get("status") or public_job.get("status") or ""),
        "ok": bool(tool_result.get("ok")),
        "error_message": str(tool_result.get("user_message") or ""),
    }
    payload.update(extra)
    return payload


_PUBLIC_WORKER_JOB_KEYS = (
    "login_job_id",
    "capture_job_id",
    "tile_job_id",
    "scene_job_id",
    "job_id",
    "source_key",
    "state",
    "status",
    "stage",
    "message",
    "progress",
    "region",
    "region_dataset",
    "dataset_id",
    "product_key",
    "pages_scanned",
    "candidate_count",
    "selected_count",
    "downloaded_count",
    "failed_count",
    "max_downloads",
    "max_tiles",
    "timeout_seconds",
    "headless",
    "auto_load",
    "process_id",
    "close_requested",
    "close_reason",
    "created_at",
    "updated_at",
    "finished_at",
)

_PUBLIC_WORKER_ID_KEYS = {"login_job_id", "capture_job_id", "tile_job_id", "scene_job_id", "job_id", "state", "status", "source_key"}
_PRIVATE_WORKER_TEXT_MARKERS = (
    "cookie",
    "token",
    "authorization",
    "storage_state",
    "traceback",
    "output_path",
    "zip_path",
    "download_url",
    "direct_url",
    "local_file_path",
    "status_path",
    "log_path",
    "state_path",
    ".env",
    "workspace/",
    "workspace\\",
    "/users/",
    "\\users\\",
)


def _public_worker_text(value: object, limit: int = 500) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if any(marker in lowered for marker in _PRIVATE_WORKER_TEXT_MARKERS):
        return ""
    if re.search(r"[A-Za-z]:[\\/]", text):
        return ""
    if text.startswith(("/api/files/artifact", "/api/downloads/artifact", "file:", "http:", "https:")):
        return ""
    return text[:limit]


def _public_worker_job(job: dict | None) -> dict:
    raw = job if isinstance(job, dict) else {}
    public: dict[str, object] = {}
    for key in _PUBLIC_WORKER_JOB_KEYS:
        if key not in raw:
            continue
        value = raw.get(key)
        if isinstance(value, str):
            public[key] = value[:120] if key in _PUBLIC_WORKER_ID_KEYS else _public_worker_text(value)
        else:
            public[key] = value
    return public or {"state": _public_worker_text(raw.get("state") or raw.get("status") or "UNKNOWN", 80)}


def _public_worker_jobs(jobs: list[dict]) -> list[dict]:
    return [_public_worker_job(job) for job in jobs if isinstance(job, dict)]


_PUBLIC_DOWNLOAD_JOB_KEYS = (
    "job_id",
    "source_key",
    "resource_type",
    "region",
    "start_date",
    "end_date",
    "account_mode",
    "output_name",
    "status",
    "state",
    "status_label",
    "stage",
    "message",
    "progress",
    "created_at",
    "updated_at",
    "finished_at",
    "canceled_at",
    "retried_from_job_id",
)

_PRIVATE_TOOL_RESULT_KEYS = {
    "path",
    "display_path",
    "source_path",
    "absolute_path",
    "relative_path",
    "output_path",
    "zip_path",
    "package_path",
    "downloaded_path",
    "download_url",
    "direct_url",
    "local_file_path",
    "request_text",
    "status_path",
    "log_path",
    "storage_state_path",
    "state_path",
    "user_id",
    "session_id",
    "account_id",
}


def _public_download_job(job: dict | None) -> dict:
    raw = job if isinstance(job, dict) else {}
    public: dict[str, object] = {}
    for key in _PUBLIC_DOWNLOAD_JOB_KEYS:
        if key not in raw:
            continue
        value = raw.get(key)
        if isinstance(value, str):
            public[key] = value[:120] if key in {"job_id", "source_key", "resource_type", "status", "state", "account_mode"} else _public_worker_text(value)
        else:
            public[key] = value
    return public


def _public_tool_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _public_tool_value(v) for k, v in value.items() if str(k) not in _PRIVATE_TOOL_RESULT_KEYS}
    if isinstance(value, list):
        return [_public_tool_value(item) for item in value]
    if isinstance(value, str):
        return _public_worker_text(value)
    return value


def _public_tool_result(result: dict) -> dict:
    public = _public_tool_value(result)
    return public if isinstance(public, dict) else {}


def _public_download_jobs(jobs: list[dict]) -> list[dict]:
    return [_public_download_job(job) for job in jobs if isinstance(job, dict)]


def _public_download_tool_results(jobs: list[dict]) -> list[dict]:
    return [_public_tool_result(download_job_to_tool_result(job)) for job in jobs if isinstance(job, dict)]


def _confirmation_id(action: str, **params) -> str:
    payload = json.dumps({"action": action, **params}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _require_confirmation(action: str, provided: str = "", **params) -> dict | None:
    expected = _confirmation_id(action, **params)
    if str(provided or "").strip() == expected:
        return None
    return {
        "ok": False,
        "requires_confirmation": True,
        "action": action,
        "confirmed_action_id": expected,
        "message": "This action starts browser automation or uses a platform account. Re-run with confirmed_action_id to proceed.",
    }


def build_commercial_tools(manager: DataManager, *, include_admin_tools: bool = False):
    commercial = CommercialService(manager.workdir)

    def _require_admin(admin_token: str) -> None:
        require_admin_token(os.getenv("GIS_AGENT_ADMIN_TOKEN", ""), admin_token)

    @tool
    def generate_commercial_secret_key(admin_token: str = "") -> str:
        """生成一个 APP_SECRET_KEY。生产环境应把它放到系统环境变量，不要提交到代码仓库。"""
        _require_admin(admin_token)
        return _json({"APP_SECRET_KEY": generate_fernet_key(), "usage": "将该值加入 .env 或系统环境变量 APP_SECRET_KEY。"})

    @tool
    def commercial_system_status(admin_token: str = "") -> str:
        """查看商业化模块状态，包括数据库位置、密钥来源、用户数、任务数和平台账号数。"""
        _require_admin(admin_token)
        return _json(commercial.status())

    @tool
    def create_commercial_customer(email: str, plan: str = "free", user_id: str = "", admin_token: str = "") -> str:
        """创建或更新一个商业版用户。plan 可选 free/basic/pro/team。"""
        _require_admin(admin_token)
        return _json(commercial.create_user(email=email, plan=plan, user_id=user_id))

    @tool
    def grant_commercial_plan(user_id: str, plan: str = "pro", platform_quota: int = -1, days: int = 30, amount_yuan: float = 0.0, note: str = "", admin_token: str = "") -> str:
        """管理员在确认支付后，手动给用户开通套餐或额度。后续可接微信/支付宝回调自动调用同等逻辑。"""
        _require_admin(admin_token)
        quota = None if int(platform_quota) < 0 else int(platform_quota)
        return _json(commercial.grant_plan(user_id=user_id, plan=plan, platform_quota=quota, days=days, amount_cents=int(float(amount_yuan) * 100), note=note))

    @tool
    def list_commercial_customers(limit: int = 20, admin_token: str = "") -> str:
        """列出最近商业版用户。"""
        _require_admin(admin_token)
        return _json(commercial.list_users(limit=limit))

    @tool
    def save_customer_source_credential(user_id: str, source_key: str, username: str = "", password: str = "", storage_state_path: str = "") -> str:
        """保存用户自己的国内数据源账号或浏览器登录态路径。账号密码会加密保存。"""
        return _json(commercial.save_user_credential(user_id=user_id, source_key=source_key, username=username, password=password, storage_state_path=storage_state_path))

    @tool
    def list_customer_source_credentials(user_id: str) -> str:
        """列出用户已保存的数据源凭据，只返回掩码，不返回明文密码。"""
        return _json(commercial.list_user_credentials(user_id=user_id))

    @tool
    def add_platform_source_account(source_key: str, username: str = "", password: str = "", label: str = "", daily_limit: int = 50, monthly_limit: int = 1000, storage_state_path: str = "", admin_token: str = "") -> str:
        """添加平台账号池账号。用于付费用户的代下载任务；账号密码会加密保存，不暴露给用户。"""
        _require_admin(admin_token)
        return _json(commercial.add_platform_account(source_key=source_key, username=username, password=password, label=label, daily_limit=daily_limit, monthly_limit=monthly_limit, storage_state_path=storage_state_path))

    @tool
    def list_platform_source_accounts(source_key: str = "", include_inactive: bool = False, admin_token: str = "") -> str:
        """列出平台账号池。只返回掩码，不返回明文密码。"""
        _require_admin(admin_token)
        return _json(commercial.list_platform_accounts(source_key=source_key, include_inactive=include_inactive))

    @tool
    def open_gscloud_customer_login_window(user_id: str, timeout_seconds: int = 300, headless: bool = False, confirmed_action_id: str = "") -> str:
        """为某个用户打开地理空间数据云登录窗口，用户自己登录后保存 Cookie 到该用户凭据。不会阻塞对话。"""
        confirmation = _require_confirmation("open_gscloud_customer_login_window", confirmed_action_id, user_id=user_id, timeout_seconds=timeout_seconds, headless=headless)
        if confirmation:
            return _json(confirmation)
        user = commercial.get_user(user_id)
        state_path = gscloud_user_state_path(manager.workdir, user["user_id"], "gscloud")
        login_job = start_gscloud_login_process(
            workdir=manager.workdir,
            subject_type="customer",
            subject_id=user["user_id"],
            state_path=state_path,
            timeout_seconds=timeout_seconds,
            headless=headless,
        )
        return _json({
            "ok": True,
            "non_blocking": True,
            "login_job": _public_worker_job(login_job),
            "message": "浏览器已在独立后台进程打开。本次对话不会被阻塞；请在浏览器中完成登录，系统会自动保存 Cookie。",
        })

    @tool
    def open_gscloud_platform_login_window(account_id: str, timeout_seconds: int = 300, headless: bool = False, confirmed_action_id: str = "", admin_token: str = "") -> str:
        """为平台账号打开地理空间数据云登录窗口。管理员登录后保存 Cookie 到平台账号池；普通用户不会看到账号密码。不会阻塞对话。"""
        _require_admin(admin_token)
        confirmation = _require_confirmation("open_gscloud_platform_login_window", confirmed_action_id, account_id=account_id, timeout_seconds=timeout_seconds, headless=headless)
        if confirmation:
            return _json(confirmation)
        account = commercial.get_platform_account_private(account_id)
        state_path = gscloud_platform_state_path(manager.workdir, account["account_id"], "gscloud")
        login_job = start_gscloud_login_process(
            workdir=manager.workdir,
            subject_type="platform_account",
            subject_id=account["account_id"],
            state_path=state_path,
            timeout_seconds=timeout_seconds,
            headless=headless,
        )
        return _json({
            "ok": True,
            "non_blocking": True,
            "login_job": _public_worker_job(login_job),
            "message": "浏览器已在独立后台进程打开。本次对话不会被阻塞；请在浏览器中完成登录，系统会自动保存 Cookie。",
        })

    @tool
    def list_gscloud_login_window_jobs(limit: int = 20) -> str:
        """列出地理空间数据云登录窗口后台任务状态，用于查看是否已保存 Cookie 或是否失败。"""
        return _json({"jobs": _public_worker_jobs(list_gscloud_login_jobs(manager.workdir, limit=limit))})

    @tool
    def get_gscloud_login_window_job(login_job_id: str) -> str:
        """查看某个地理空间数据云登录窗口后台任务状态。"""
        return _json(_public_worker_job(read_gscloud_login_job(manager.workdir, login_job_id)))

    @tool
    def list_gscloud_capture_window_jobs(limit: int = 20) -> str:
        """列出地理空间数据云 DEM 捕获下载后台任务状态。"""
        return _json({"jobs": _public_worker_jobs(list_gscloud_capture_jobs(manager.workdir, limit=limit))})

    @tool
    def get_gscloud_capture_window_job(capture_job_id: str) -> str:
        """查看一个地理空间数据云 DEM 捕获下载后台任务状态。"""
        return _json(_public_worker_job(read_gscloud_capture_job(manager.workdir, capture_job_id)))

    @tool
    def list_gscloud_auto_tile_jobs(limit: int = 20) -> str:
        """列出地理空间数据云 DEM 自动分幅下载后台任务。"""
        return _json({"jobs": _public_worker_jobs(list_gscloud_tile_jobs(commercial.workdir, limit=limit))})

    @tool
    def get_gscloud_auto_tile_job(tile_job_id: str) -> str:
        """查看一个地理空间数据云 DEM 自动分幅下载后台任务状态。"""
        return _json(_public_worker_job(read_gscloud_tile_job(commercial.workdir, tile_job_id)))

    @tool
    def start_gscloud_dem_region_auto_tiles_job(
        job_id: str,
        region: str = "四川省",
        region_dataset: str = "",
        dataset_id: str = "310",
        max_tiles: int = 0,
        timeout_seconds: int = 1800,
        headless: bool = True,
        auto_load: bool = True,
        confirmed_action_id: str = "",
    ) -> str:
        """在后台启动“自动计算区域分幅 + 自动批量下载地理空间数据云 ASTER GDEM”的任务。不会让用户自己选择分幅；默认 headless=True，不弹出网页。"""
        try:
            job = commercial.get_job(job_id)
            if job.get("source_key") != "gscloud":
                raise ValueError("该工具仅支持 source_key=gscloud 的任务。")
            confirmation = _require_confirmation(
                "start_gscloud_dem_region_auto_tiles_job",
                confirmed_action_id,
                job_id=job_id,
                region=region,
                region_dataset=region_dataset,
                dataset_id=dataset_id,
                max_tiles=max_tiles,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            if confirmation:
                return _json(confirmation)
            state_path = commercial.resolve_job_storage_state_path(job_id)
            if not state_path or not Path(state_path).exists():
                raise RuntimeError("未找到可用登录态，请先完成用户或平台账号登录保存 Cookie。")
            commercial._update_job(job_id, status="running", progress=5, stage="starting_auto_tile_worker")
            tile_job = start_gscloud_tile_process(
                workdir=commercial.workdir,
                job_id=job_id,
                region=region or job.get("region") or "四川省",
                region_dataset=region_dataset,
                dataset_id=dataset_id,
                max_tiles=max_tiles,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            return _json({
                "ok": True,
                "job_id": job_id,
                "auto_tile_job": _public_worker_job(tile_job),
                "next_step": "系统已在后台自动计算并下载分幅，不需要用户自己判断四川对应哪些分幅。可查询商业任务状态或自动分幅下载后台任务状态。",
            })
        except Exception as exc:
            return _json({"ok": False, "job_id": job_id, "error": str(exc)})

    @tool
    def start_gscloud_dem_capture_job(
        job_id: str,
        start_url: str = "",
        max_downloads: int = 1,
        timeout_seconds: int = 1800,
        headless: bool = False,
        auto_load: bool = True,
        confirmed_action_id: str = "",
    ) -> str:
        """非阻塞启动地理空间数据云 DEM 捕获下载窗口。浏览器在后台进程打开，不阻塞聊天。"""
        try:
            job = commercial.get_job(job_id)
            if job.get("source_key") != "gscloud":
                raise ValueError("该工具仅支持 source_key=gscloud 的任务。")
            confirmation = _require_confirmation(
                "start_gscloud_dem_capture_job",
                confirmed_action_id,
                job_id=job_id,
                start_url=start_url,
                max_downloads=max_downloads,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            if confirmation:
                return _json(confirmation)
            state_path = commercial.resolve_job_storage_state_path(job_id)
            if not state_path or not Path(state_path).exists():
                raise RuntimeError("未找到可用登录态，请先完成平台账号或用户账号登录保存 Cookie。")
            commercial._update_job(job_id, status="running", progress=20, stage="starting_capture_browser")
            capture_job = start_gscloud_capture_process(
                workdir=manager.workdir,
                job_id=job_id,
                start_url=start_url or GSCLOUD_ASTER_GDEM30_ACCESS_URL,
                max_downloads=max_downloads,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            return _json({
                "ok": True,
                "non_blocking": True,
                "job_id": job_id,
                "capture_job": _public_worker_job(capture_job),
                "next_step": "浏览器会自动打开到 ASTER GDEM 30M 页面。请在页面中点击下载按钮；下载完成后后台会自动入库、打包并更新任务状态。",
            })
        except Exception as exc:
            return _json(_download_job_payload(commercial.fail_job(job_id, str(exc))))

    @tool
    def submit_commercial_download_job(
        user_id: str,
        source_key: str,
        resource_type: str,
        region: str = "",
        account_mode: str = "auto",
        request_text: str = "",
        output_name: str = "",
        start_date: str = "",
        end_date: str = "",
        direct_url: str = "",
        local_file_path: str = "",
    ) -> str:
        """提交商业下载任务。account_mode 可选 own/user_account/platform/direct_url/local_file/browser_capture。平台账号模式会检查付费额度。"""
        # 浏览器捕获也按账号模式计费，platform 计平台额度，own 不计平台额度。
        normalized_mode = account_mode.strip().lower()
        if normalized_mode in {"browser_capture", "capture"}:
            normalized_mode = "own"
        job = commercial.submit_job(
            user_id=user_id,
            source_key=source_key,
            resource_type=resource_type,
            region=region,
            start_date=start_date,
            end_date=end_date,
            account_mode=normalized_mode,
            request_text=request_text,
            direct_url=direct_url,
            local_file_path=local_file_path,
            output_name=output_name,
        )
        return _json({
            "job": _public_download_job(job),
            "tool_result": _public_tool_result(download_job_to_tool_result(job)),
            "next_step": "如果 direct_url/local_file_path 已填写，可调用 run_commercial_download_job；地理空间数据云 DEM 推荐调用 run_gscloud_dem_capture_job。",
        })

    @tool
    def run_commercial_download_job(job_id: str, direct_url: str = "", local_file_path: str = "", auto_load: bool = True) -> str:
        """运行商业下载任务的通用执行器。支持 direct_url 或 local_file_path；地理空间数据云网页下载请使用 run_gscloud_dem_capture_job。"""
        job = commercial.get_job(job_id)
        try:
            if local_file_path or job.get("local_file_path"):
                path = Path(local_file_path or job.get("local_file_path") or "").expanduser()
                if not path.exists():
                    raise FileNotFoundError(f"本地文件不存在: {path}")
                manager._require_allowed_import_source(path)
                commercial._update_job(job_id, status="running", progress=40, stage="importing_local_file")
                result = postprocess_download(
                    manager=manager,
                    downloaded_path=path,
                    source_key=job.get("source_key", "manual"),
                    output_name=job.get("output_name") or path.stem,
                    auto_load=auto_load,
                ).to_dict()
                done = commercial.run_job_with_result(job_id, result)
                return _json(_download_job_payload(done))

            url = direct_url or job.get("direct_url") or ""
            if url:
                commercial._update_job(job_id, status="running", progress=30, stage="downloading_direct_url")
                source = get_source(job.get("source_key", ""))
                result = download_direct_url(
                    manager=manager,
                    url=url,
                    source=source,
                    output_name=job.get("output_name") or "",
                    auto_load=auto_load,
                    timeout_seconds=900,
                ).to_dict()
                done = commercial.run_job_with_result(job_id, result)
                return _json(_download_job_payload(done))

            commercial._update_job(job_id, status="waiting_manual", progress=10, stage="needs_site_adapter_or_browser_capture")
            return _json({
                "job": _public_download_job(commercial.get_job(job_id)),
                "tool_result": _public_tool_result(download_job_to_tool_result(commercial.get_job(job_id))),
                "message": "该任务已创建，但没有 direct_url 或 local_file_path。地理空间数据云 DEM 请调用 run_gscloud_dem_capture_job。",
            })
        except Exception as exc:
            return _json(_download_job_payload(commercial.fail_job(job_id, str(exc))))

    @tool
    def run_gscloud_dem_capture_job(
        job_id: str,
        start_url: str = "",
        max_downloads: int = 1,
        timeout_seconds: int = 1800,
        headless: bool = False,
        auto_load: bool = True,
        confirmed_action_id: str = "",
    ) -> str:
        """运行地理空间数据云 DEM 商业任务：打开访问数据页，复用用户/平台 Cookie，等待点击下载并捕获文件。适合你截图里的下载按钮流程。"""
        job = commercial.get_job(job_id)
        try:
            if job.get("source_key") != "gscloud":
                raise ValueError("该工具仅支持 source_key=gscloud 的任务。")
            confirmation = _require_confirmation(
                "run_gscloud_dem_capture_job",
                confirmed_action_id,
                job_id=job_id,
                start_url=start_url,
                max_downloads=max_downloads,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            if confirmation:
                return _json(confirmation)
            commercial._update_job(job_id, status="running", progress=15, stage="opening_gscloud_page")
            state_path = commercial.resolve_job_storage_state_path(job_id)
            if not state_path or not Path(state_path).exists():
                raise RuntimeError(
                    "未找到可用的地理空间数据云登录态。用户账号模式请先调用 open_gscloud_customer_login_window；平台账号模式请先调用 open_gscloud_platform_login_window。"
                )
            commercial._update_job(job_id, status="running", progress=35, stage="waiting_download_click")
            result = capture_gscloud_downloads(
                manager=manager,
                start_url=start_url or GSCLOUD_ASTER_GDEM30_ACCESS_URL,
                storage_state_path=state_path,
                output_name=job.get("output_name") or "gscloud_dem",
                max_downloads=max_downloads,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            commercial._update_job(job_id, status="running", progress=85, stage="packaging_result")
            done = commercial.run_job_with_result(job_id, result)
            return _json(_download_job_payload(done))
        except Exception as exc:
            return _json(_download_job_payload(commercial.fail_job(job_id, str(exc))))

    @tool
    def run_gscloud_dem_auto_tiles_job(
        job_id: str,
        tile_ids: str,
        dataset_id: str = "310",
        timeout_seconds: int = 1800,
        headless: bool = False,
        auto_load: bool = True,
        confirmed_action_id: str = "",
    ) -> str:
        """尝试按地理空间数据云数据标识自动下载 DEM 分幅，例如 ASTGTM_N30E103。若页面结构变化失败，请改用 run_gscloud_dem_capture_job。"""
        job = commercial.get_job(job_id)
        try:
            if job.get("source_key") != "gscloud":
                raise ValueError("该工具仅支持 source_key=gscloud 的任务。")
            ids = parse_tile_ids(tile_ids)
            if not ids:
                raise ValueError("请提供数据标识，例如 ASTGTM_N30E103, ASTGTM_N31E103。")
            confirmation = _require_confirmation(
                "run_gscloud_dem_auto_tiles_job",
                confirmed_action_id,
                job_id=job_id,
                tile_ids=tile_ids,
                dataset_id=dataset_id,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            if confirmation:
                return _json(confirmation)
            state_path = commercial.resolve_job_storage_state_path(job_id)
            if not state_path or not Path(state_path).exists():
                raise RuntimeError("未找到可用登录态，请先完成用户或平台账号登录保存 Cookie。")
            commercial._update_job(job_id, status="running", progress=25, stage="auto_filtering_tiles")
            _, product = resolve_gscloud_dem_product(dataset_id=dataset_id)
            result = download_gscloud_tiles_by_identifier_search(
                manager=manager,
                tile_ids=ids,
                dataset_id=str(product.get("dataset_id") or dataset_id),
                pid=str(product.get("pid") or "1"),
                tile_scheme=str(product.get("tile_scheme") or "astgtm_1deg"),
                storage_state_path=state_path,
                output_name=job.get("output_name") or "gscloud_dem_tiles",
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            done = commercial.run_job_with_result(job_id, result)
            return _json(_download_job_payload(done))
        except Exception as exc:
            return _json(_download_job_payload(commercial.fail_job(job_id, str(exc))))


    @tool
    def index_gscloud_aster_gdem_resources(
        account_mode: str = "platform",
        account_id: str = "",
        user_id: str = "",
        dataset_id: str = "310",
        max_pages: int = 0,
        headless: bool = True,
        confirmed_action_id: str = "",
    ) -> str:
        """扫描地理空间数据云 ASTER/GDEM 访问数据页面的所有分页，建立本地资源索引。不会下载数据，只建立 tile_id -> 页面记录索引。"""
        try:
            confirmation = _require_confirmation(
                "index_gscloud_aster_gdem_resources",
                confirmed_action_id,
                account_mode=account_mode,
                account_id=account_id,
                user_id=user_id,
                dataset_id=dataset_id,
                max_pages=max_pages,
                headless=headless,
            )
            if confirmation:
                return _json(confirmation)
            state_path = ""
            mode = str(account_mode or "platform").lower()
            if mode in {"platform", "platform_account"}:
                if account_id:
                    account = commercial.get_platform_account_private(account_id)
                    state_path = commercial.resolve_platform_storage_state_path(account["account_id"]) if hasattr(commercial, "resolve_platform_storage_state_path") else ""
                    fallback = gscloud_platform_state_path(manager.workdir, account["account_id"], "gscloud")
                    if not state_path or not Path(state_path).exists():
                        state_path = str(fallback)
            else:
                if user_id:
                    fallback = gscloud_user_state_path(manager.workdir, user_id, "gscloud")
                    state_path = str(fallback)
            if not state_path or not Path(state_path).exists():
                # 允许未登录扫描公开页，但给出提示。某些数据源列表需要登录才完整。
                state_path = ""
            result = scan_gscloud_dataset_index(
                workdir=manager.workdir,
                dataset_id=dataset_id,
                storage_state_path=state_path,
                max_pages=max_pages,
                headless=headless,
                output_name=f"gscloud_{dataset_id}_aster_gdem_index",
            )
            return _json(result)
        except Exception as exc:
            return _json({"ok": False, "error": str(exc), "hint": "请确认已完成地理空间数据云登录，并检查网站分页结构是否变化。"})

    @tool
    def query_gscloud_index_for_region_tiles(region: str = "四川省", region_dataset: str = "", dataset_id: str = "310") -> str:
        """先计算区域所需 ASTER/GDEM 分幅，再查询本地地理空间数据云资源索引中是否能找到这些分幅。"""
        try:
            plan = plan_aster_gdem_tiles(
                manager=manager,
                region=region,
                region_dataset=region_dataset,
                output_name=f"{region}_aster_gdem_tiles",
                bbox_only=False,
                save_preview=True,
            )
            q = query_index_for_tiles(manager.workdir, dataset_id, list(plan.get("tile_ids") or []))
            q["tile_plan"] = {k: v for k, v in plan.items() if k != "records"}
            return _json(q)
        except Exception as exc:
            return _json({"ok": False, "error": str(exc), "hint": "请先运行 index_gscloud_aster_gdem_resources 建立资源索引，或检查区域边界。"})

    @tool
    def list_gscloud_dem_products() -> str:
        """列出当前内置的地理空间数据云 DEM 产品页配置。"""
        return _json({"default_access_url": GSCLOUD_ASTER_GDEM30_ACCESS_URL, "products": GSCLOUD_DEM_DATASETS})

    @tool
    def plan_gscloud_aster_gdem_tiles(region: str = "四川省", region_dataset: str = "", output_name: str = "", bbox_only: bool = False) -> str:
        """根据省市县边界自动计算地理空间数据云 ASTER GDEM 30M 需要下载哪些 1°×1° 分幅。优先使用工作区矢量边界，例如 sichuan_boundary。"""
        try:
            return _json(plan_aster_gdem_tiles(
                manager=manager,
                region=region,
                region_dataset=region_dataset,
                output_name=output_name or f"{region}_aster_gdem_tiles",
                bbox_only=bbox_only,
                save_preview=True,
            ))
        except Exception as exc:
            return _json({"ok": False, "error": str(exc), "hint": "请先导入或下载区域边界，例如四川边界数据集 sichuan_boundary；没有边界时仅支持内置省份外包框兜底。"})

    @tool
    def run_gscloud_dem_region_auto_tiles_job(
        job_id: str,
        region: str = "四川省",
        region_dataset: str = "",
        dataset_id: str = "310",
        max_tiles: int = 0,
        timeout_seconds: int = 1800,
        headless: bool = True,
        auto_load: bool = True,
        confirmed_action_id: str = "",
    ) -> str:
        """先自动计算区域所需 ASTER GDEM 分幅，再按数据标识批量自动下载。max_tiles>0 可限制前 N 个分幅用于测试；默认 headless=True，不弹出网页。"""
        job = commercial.get_job(job_id)
        try:
            if job.get("source_key") != "gscloud":
                raise ValueError("该工具仅支持 source_key=gscloud 的任务。")
            confirmation = _require_confirmation(
                "run_gscloud_dem_region_auto_tiles_job",
                confirmed_action_id,
                job_id=job_id,
                region=region,
                region_dataset=region_dataset,
                dataset_id=dataset_id,
                max_tiles=max_tiles,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            if confirmation:
                return _json(confirmation)
            state_path = commercial.resolve_job_storage_state_path(job_id)
            if not state_path or not Path(state_path).exists():
                raise RuntimeError("未找到可用登录态，请先完成用户或平台账号登录保存 Cookie。")
            plan = plan_gscloud_dem_tiles(
                manager=manager,
                region=region or job.get("region") or "四川省",
                region_dataset=region_dataset,
                output_name=(job.get("output_name") or "gscloud_dem") + "_tile_plan",
                bbox_only=False,
                save_preview=True,
                dataset_id=dataset_id,
            )
            ids = list(plan.get("tile_ids") or [])
            if int(max_tiles or 0) > 0:
                ids = ids[: int(max_tiles)]
            if not ids:
                raise RuntimeError("没有计算出可下载分幅。")
            commercial._update_job(job_id, status="running", progress=20, stage="planned_tiles")
            result = download_gscloud_tiles_by_identifier_search(
                manager=manager,
                tile_ids=ids,
                dataset_id=str(plan.get("dataset_id") or dataset_id),
                pid=str(plan.get("pid") or "1"),
                tile_scheme=str(plan.get("tile_scheme") or "astgtm_1deg"),
                storage_state_path=state_path,
                output_name=job.get("output_name") or f"{region}_gscloud_dem",
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=auto_load,
            )
            result["tile_plan"] = {k: v for k, v in plan.items() if k != "records"}
            done = commercial.run_job_with_result(job_id, result)
            return _json(_download_job_payload(done))
        except Exception as exc:
            return _json(_download_job_payload(commercial.fail_job(job_id, str(exc))))

    @tool
    def get_commercial_download_job(job_id: str) -> str:
        """查看一个商业下载任务的状态与结果。"""
        return _json(_download_job_payload(commercial.get_job(job_id)))

    @tool
    def list_commercial_download_jobs(user_id: str = "", limit: int = 20) -> str:
        """列出商业下载任务。可按 user_id 过滤。"""
        jobs = commercial.list_jobs(user_id=user_id, limit=limit)
        return _json({"jobs": _public_download_jobs(jobs), "tool_results": _public_download_tool_results(jobs)})


    @tool
    def register_commercial_login_user(email: str, password: str, plan: str = "free", user_id: str = "") -> str:
        """注册智能体前端登录用户。密码只保存 PBKDF2 哈希；默认 free 只能使用自己的数据源账号。"""
        try:
            return _json(commercial.register_user(email=email, password=password, plan=plan, user_id=user_id))
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    @tool
    def authenticate_commercial_login_user(email: str, password: str) -> str:
        """校验智能体前端登录账号密码，成功后返回用户公开信息和会话 id。不会返回密码。"""
        try:
            result = commercial.authenticate_user(email=email, password=password)
            result.pop("session_token", None)
            return _json(result)
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    @tool
    def commercial_permission_summary(user_id: str) -> str:
        """查看用户当前是否能使用 own 模式和 platform 模式，以及剩余平台账号下载额度。"""
        try:
            return _json(commercial.permission_summary(user_id))
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    @tool
    def create_mock_payment_order(user_id: str, plan: str = "pro", amount_yuan: float = 20.0, platform_quota: int = -1, days: int = 30, note: str = "") -> str:
        """创建模拟支付订单。该工具只登记待支付订单，不自动开通。"""
        try:
            quota = None if int(platform_quota) < 0 else int(platform_quota)
            return _json(commercial.create_payment_order(user_id=user_id, plan=plan, amount_cents=int(float(amount_yuan) * 100), platform_quota=quota, days=days, provider="mock", note=note))
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    @tool
    def complete_mock_payment_order(order_id: str) -> str:
        """模拟支付成功回调，登记 payment_record，并给用户开通对应套餐和平台账号下载额度。"""
        try:
            return _json(commercial.complete_payment_order(order_id))
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    @tool
    def simulate_commercial_payment(user_id: str, plan: str = "pro", amount_yuan: float = 20.0, platform_quota: int = -1, days: int = 30) -> str:
        """一键模拟支付：创建订单、标记已支付、开通套餐。适合课堂演示和本地 MVP。"""
        try:
            quota = None if int(platform_quota) < 0 else int(platform_quota)
            return _json(commercial.simulate_payment(user_id=user_id, plan=plan, amount_cents=int(float(amount_yuan) * 100), platform_quota=quota, days=days))
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    @tool
    def list_mock_payment_orders(user_id: str = "", limit: int = 20) -> str:
        """列出模拟支付订单。可按用户过滤。"""
        return _json(commercial.list_payment_orders(user_id=user_id, limit=limit))

    @tool
    def list_payment_records(user_id: str = "", limit: int = 20) -> str:
        """列出已完成支付记录。可按用户过滤。"""
        return _json(commercial.list_payment_records(user_id=user_id, limit=limit))

    user_tools = [
        register_commercial_login_user,
        authenticate_commercial_login_user,
        commercial_permission_summary,
        create_mock_payment_order,
        complete_mock_payment_order,
        simulate_commercial_payment,
        list_mock_payment_orders,
        list_payment_records,
        save_customer_source_credential,
        list_customer_source_credentials,
        open_gscloud_customer_login_window,
        list_gscloud_login_window_jobs,
        get_gscloud_login_window_job,
        list_gscloud_capture_window_jobs,
        get_gscloud_capture_window_job,
        list_gscloud_auto_tile_jobs,
        get_gscloud_auto_tile_job,
        start_gscloud_dem_region_auto_tiles_job,
        start_gscloud_dem_capture_job,
        submit_commercial_download_job,
        run_commercial_download_job,
        run_gscloud_dem_capture_job,
        run_gscloud_dem_auto_tiles_job,
        index_gscloud_aster_gdem_resources,
        query_gscloud_index_for_region_tiles,
        list_gscloud_dem_products,
        plan_gscloud_aster_gdem_tiles,
        run_gscloud_dem_region_auto_tiles_job,
        get_commercial_download_job,
        list_commercial_download_jobs,
    ]

    admin_tools = [
        generate_commercial_secret_key,
        commercial_system_status,
        create_commercial_customer,
        grant_commercial_plan,
        list_commercial_customers,
        add_platform_source_account,
        list_platform_source_accounts,
        open_gscloud_platform_login_window,
    ]

    return user_tools + (admin_tools if include_admin_tools else [])
