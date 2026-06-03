from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from .config import Settings
from .data_manager import DataManager
from .gis_tools import build_tools

# Direct command router for high-risk / UI-opening actions.
# This avoids cases where the LLM answers in text instead of invoking the tool.
try:
    from .commercial.service import CommercialService
    from .domestic_sources.gscloud_adapter import (
        gscloud_platform_state_path,
        gscloud_user_state_path,
        open_login_and_save_state,
        plan_aster_gdem_tiles,
    )
    from .commercial.login_jobs import start_gscloud_login_thread
    from .commercial.capture_jobs import start_gscloud_capture_process
    from .commercial.tile_jobs import start_gscloud_tile_process
except Exception:  # pragma: no cover
    CommercialService = None  # type: ignore
    gscloud_platform_state_path = None  # type: ignore
    gscloud_user_state_path = None  # type: ignore
    open_login_and_save_state = None  # type: ignore
    plan_aster_gdem_tiles = None  # type: ignore
    start_gscloud_login_thread = None  # type: ignore
    start_gscloud_capture_process = None  # type: ignore
    start_gscloud_tile_process = None  # type: ignore


SYSTEM_PROMPT = """
你是一个更偏科研与论文场景的智能 GIS 助手，主要服务于地理信息科学专业学生的开题、毕业设计、遥感/GIS 数据处理、实验设计、结果分析和论文写作。

你的角色不仅是 GIS 工具执行器，也是研究流程协作者。尤其适合：
- 开题报告与论文结构优化
- 多源遥感/再分析/站点数据的预处理与匹配
- 流域尺度空间分析、制图与结果汇报
- 土壤水分、生态水文、遥感反演与模型比较研究
- 结果复核、误差评价、月尺度/季节尺度分析

工作原则：
1. 先理解当前已有数据集，再决定调用哪些工具。
2. 尽量自主完成中间步骤，例如先检查字段、识别坐标字段、判断时间字段、识别文档内容，再决定下一步处理。
3. 不要编造字段名、统计值、输出路径；所有结论必须基于工具结果。
4. 当用户要“制图”“看分布”“画图”“生成结果图”时，优先调用 plot_dataset 或 raster_histogram。
5. 当用户上传的是表格且包含经纬度或坐标字段时，优先考虑 detect_coordinate_fields，再决定是否使用 table_to_points。若用户上传的是点 shapefile/GeoJSON/GPKG，则应直接把它视为可建模的矢量属性数据，不要误判为普通表格。
6. 当用户上传的是 docx、txt、md 等论文或方案文档时，优先使用 preview_document、document_outline、search_document_text 读取内容后再回答，不要只凭用户一句话猜测全文。
7. 当用户要做叠加分析、相交、差异、面内点统计、空间连接、提取栅格值到点、属性连接、面积长度字段补充时，优先使用对应 GIS 工具而不是只做口头说明。
8. 当用户要做模型评价、产品比较、缺失统计、时间聚合、滞后特征构建、BTCH 融合、RF/XGBoost 融合、LSTM 时序建模或 GCP 不确定性分析时，优先使用 evaluate_prediction_accuracy、aggregate_time_series、build_time_features、profile_missing_values、btch_fusion_model、train_rf_fusion_model、train_xgboost_fusion_model、train_lstm_fusion_model、geographical_conformal_prediction 等工具。对于点位 shapefile 的回归任务，优先使用 train_xgboost_fusion_model，并保持空间几何、启用空间分块验证、检查 Moran's I、输出残差空间分布图。
8.0 当用户在 XGBoost / RF / BTCH / LSTM 结果后继续要求 GCP、预测区间、不确定性范围、PICP/MPIW/NMPIW/QCP/IS 时，应继续调用 geographical_conformal_prediction。若结果数据集中没有显式 holdout 标签，但存在 *_xgb_spatial_cv 或 *_spatial_cv 这类空间交叉验证预测列，则默认把这些非空样本视为可用于 GCP 的目标样本；不要因为用户写了 target_filter=xxx == 'holdout' 就直接失败。
8.05 当用户要求“残差空间分布图”“预测结果图层”“空间分布图”时，优先理解为矢量结果图层或空间分布图输出，不要把这类需求误当成只支持普通统计图的 chart_type；若需要调用 generate_thesis_charts，优先使用 spatial_distribution、residual_map、prediction_map 或 auto_pack。
8.1 当用户提到“数据库”“存储数据”“自动调用数据”“SQL”“结果复用”时，优先使用 database_status、list_database_objects、sync_dataset_to_database、sync_all_to_database、query_workspace_database，把表格、矢量属性和文档摘要组织进内置 SQLite 工作区数据库，再基于查询结果继续分析。
8.2 当用户希望“一键跑完整流程”“显示处理过程”“让新手看懂步骤”时，优先使用 explain_database_training_pipeline、run_database_training_pipeline、list_pipeline_runs、show_pipeline_run，给出可视化步骤说明、运行记录和阶段性输出。
9. 若缺少参数，请基于已有数据给出最小化追问，或先列出候选字段并建议下一步。
10. 回答尽量使用清晰结构：
   - 已完成操作
   - 关键结果
   - 输出文件
   - 下一步建议
11. 若用户让你概括当前工作区，请优先调用 workspace_status 或 describe_dataset。
12. 对毕业论文场景，优先使用正式、准确、易引用的表达；涉及实验设计时，主动从“数据、方法、验证、结果表达、风险点”五个方面组织建议。若用户提到开题、中期或答辩材料，请优先考虑 generate_stage_report 与 generate_model_comparison_summary。
13. 如果收到附带图片、地图、统计图或图件预览，请结合图像内容回答，不要忽略视觉信息。
14. 如果用户希望“自动完成一整套处理流程”，可以连续调用多个工具，但每一步都必须基于前一步结果。
15. 对“基于多源遥感的闪电河流域表层土壤水分数据融合及模型比较研究”这类任务，应优先联想到：站点—栅格匹配、时间对齐、深度统一、缺失值检查、滞后降水构建、BTCH 权重融合、RF/XGBoost 回归融合、LSTM 时序建模、GCP 空间不确定性估计、月季尺度统计、精度指标比较、阶段材料生成、论文结果表述，以及必要时通过内置数据库统一管理训练表、验证表和阶段成果。
16. 当用户提到“下载某地 DEM / 降水 / 外部资源 / 在线数据 / 某省数据”时，优先先调用 download_backend_status、list_remote_resource_catalog 或本地文件库工具，判断本地文件库、国内数据源、天地图能力和商业化账号任务是否可用；若需要区域边界，优先从本地文件库调用行政区划/流域边界，若用户给了直链，则优先使用 download_file_from_url。
16.1 当用户提到“国内网站 / 国内数据源 / 地理空间数据云 / 中国气象数据网 / 国家地球系统科学数据中心 / RESDC / 账号登录下载”时，优先调用 list_domestic_data_sources 与 domestic_login_status。若网站有验证码或复杂下单流程，使用 open_domestic_login_window 让用户手动登录保存 Cookie，再用 capture_domestic_browser_download 捕获用户点击的下载文件；不要尝试绕过验证码、付费墙或权限控制。若用户提供的是下载直链，使用 download_domestic_url；若用户已经手动下载到本机，使用 import_domestic_downloaded_file 入库。
16.2 当用户提到“商业版 / 商用智能体 / 付费 / 会员 / 平台账号 / 用户自己的账号 / 账号池 / 下载额度 / 订单 / 任务状态 / 登录 / 注册”时，优先调用 commercial_system_status、register_commercial_login_user、authenticate_commercial_login_user、commercial_permission_summary、create_mock_payment_order、complete_mock_payment_order、simulate_commercial_payment、create_commercial_customer、grant_commercial_plan、add_platform_source_account、submit_commercial_download_job、list_commercial_download_jobs 等商业化工具。平台账号不得暴露给普通用户；用户凭据和平台凭据只能加密保存，回复中只显示掩码。普通用户使用 account_mode=own 调用自己的地理空间数据云账号或 Cookie；付费用户使用 account_mode=platform 调用平台账号池并消耗 platform_monthly_quota。地理空间数据云 DEM 任务优先使用 open_gscloud_customer_login_window 或 open_gscloud_platform_login_window 保存登录态。若用户不知道四川/某区域对应哪些分幅，先调用 plan_gscloud_aster_gdem_tiles 计算 ASTGTM_NxxExxx 分幅清单；商业化场景下用户说“提交地理空间数据云 DEM 下载任务”时，应优先创建任务并启动 start_gscloud_dem_region_auto_tiles_job 或 run_gscloud_dem_region_auto_tiles_job，让系统自动计算分幅、扫描访问数据页全部分页并只下载目标分幅，不要默认打开网页让用户自己选择分幅；只有自动流程失败或用户明确要求手动时，才调用 run_gscloud_dem_capture_job 让用户按清单手动点击。
16.3 当用户提到“天地图 / 底图 / 地名搜索 / 逆地理编码 / 行政区 / 道路 / 水系 / 地图服务 / WMTS”时，应优先说明天地图在本系统中的定位：用于网页底图、影像/矢量/地形底图、地名检索、逆地理编码、政区/道路/水系等要素辅助查询；不得把天地图底图服务误说成 DEM 或降雨原始数据下载源。若未配置 TIANDITU_TOKEN，应提示用户先在 .env 中配置。

17. 对外部资源下载场景，不要凭空承诺某网站一定可用。要基于工具返回结果说明：下载来源、区域范围、时间范围、输出文件和当前限制（例如本地文件库没有匹配数据、国内网站需要用户手动登录/授权、平台账号额度不足、天地图 Key 未配置）。
""".strip()


class GISAgent:
    def __init__(self, settings: Settings, manager: DataManager):
        self.settings = settings
        self.manager = manager
        self.model = ChatOpenAI(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            temperature=settings.temperature,
        )
        self.tools = build_tools(manager)
        self.agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=SYSTEM_PROMPT,
        )

    def _normalize_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content") or str(item)
                    parts.append(str(text))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(content)

    def _image_to_data_url(self, image_path: str) -> str:
        path = Path(image_path)
        mime_type, _ = mimetypes.guess_type(path.name)
        mime_type = mime_type or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _build_user_content(self, user_text: str, image_paths: list[str] | None = None) -> Any:
        current_hint = f"\n\n当前已加载数据集概览：\n{self.manager.dataset_brief()}"
        if not image_paths:
            return user_text + current_hint

        image_list = [path for path in image_paths if Path(path).exists()]
        blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": user_text
                + current_hint
                + "\n\n附加说明：已附带相关图件/图片，请结合视觉内容回答。如果图像与工具结果不一致，请说明可能原因。",
            }
        ]
        for image_path in image_list:
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._image_to_data_url(image_path)},
                }
            )
        return blocks

    def register_file(self, file_path: str) -> str:
        dataset_name = self.manager.load_path(file_path)
        return f"已加载数据: {dataset_name}\n{self.manager.dataset_brief()}"

    def _append_direct_reply(self, user_text: str, reply: str, history: list[Any] | None) -> tuple[str, list[Any]]:
        messages = list(history or [])
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": reply})
        self.manager.log_operation("直接执行命令", reply[:180], "chat")
        return reply, messages

    def _extract_timeout_seconds(self, user_text: str, default: int = 300) -> int:
        match = re.search(r"(\d+)\s*秒", user_text)
        if match:
            return max(30, int(match.group(1)))
        match = re.search(r"(\d+)\s*(?:分钟|分)", user_text)
        if match:
            return max(30, int(match.group(1)) * 60)
        return default

    def _try_direct_gscloud_login_command(self, user_text: str) -> str | None:
        """Directly execute GSCloud login-window commands.

        The browser-opening action is time-sensitive and visible to the user.
        In practice, some LLM calls answer with text instead of selecting the tool.
        This deterministic router handles common Chinese commands such as:
        “为平台账号 pa_xxx 打开地理空间数据云登录窗口，等待我手动登录 300 秒。”
        """
        text = user_text.strip()
        if not ("地理空间数据云" in text and "登录" in text and "打开" in text):
            return None
        if open_login_and_save_state is None or CommercialService is None:
            return json.dumps(
                {"ok": False, "error": "商业化/地理空间数据云模块未正确加载。"},
                ensure_ascii=False,
                indent=2,
            )

        timeout_seconds = self._extract_timeout_seconds(text, default=300)
        headless = False
        commercial = CommercialService(self.manager.workdir)

        # Platform account: pa_xxxxx
        platform_match = re.search(r"(pa_[A-Za-z0-9_\-]+)", text)
        if "平台账号" in text and platform_match:
            account_id = platform_match.group(1)
            try:
                account = commercial.get_platform_account_private(account_id)
                state_path = gscloud_platform_state_path(self.manager.workdir, account["account_id"], "gscloud")
                # Immediately bind the deterministic cookie path to this platform account.
                # The background login worker writes cookies to this file every few seconds,
                # so the next download job can resolve the login state without waiting for
                # the 300-second login window to finish.
                commercial.set_platform_account_storage_state(account["account_id"], str(state_path))
                if start_gscloud_login_thread is None:
                    raise RuntimeError("后台登录任务模块未正确加载。")

                login_job = start_gscloud_login_thread(
                    workdir=commercial.workdir,
                    subject_type="platform_account",
                    subject_id=account["account_id"],
                    state_path=state_path,
                    timeout_seconds=timeout_seconds,
                    headless=headless,
                    save_callback=lambda sp: CommercialService(self.manager.workdir).set_platform_account_storage_state(account["account_id"], sp),
                )
                return json.dumps(
                    {
                        "ok": True,
                        "direct_command": "open_gscloud_platform_login_window",
                        "non_blocking": True,
                        "account_id": account_id,
                        "login_job": login_job,
                        "next_step": "浏览器已在后台打开。本次对话不会阻塞；请在浏览器中完成登录，等待时间结束后会自动保存 Cookie。之后可提交/运行地理空间数据云 DEM 捕获下载任务。",
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            except Exception as exc:
                return json.dumps(
                    {
                        "ok": False,
                        "direct_command": "open_gscloud_platform_login_window",
                        "account_id": account_id,
                        "error": str(exc),
                        "hint": "请先确认该平台账号存在；可在智能体中输入：列出平台账号池。",
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )

        # Customer/user account: support common forms like “为用户 u_xxx ...” or an email.
        user_match = re.search(r"(?:用户|客户|为)\s*([A-Za-z0-9_.+@\-]+)\s*(?:打开|的)?", text)
        email_match = re.search(r"[A-Za-z0-9_.+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+", text)
        user_id = ""
        if "用户" in text or "客户" in text or email_match:
            if email_match:
                user_id = email_match.group(0)
            elif user_match:
                user_id = user_match.group(1)

        if user_id:
            try:
                user = commercial.get_user(user_id)
                state_path = gscloud_user_state_path(self.manager.workdir, user["user_id"], "gscloud")
                # Immediately bind the deterministic cookie path to this customer credential.
                # The background login worker will populate the file while the browser remains open.
                commercial.set_user_credential_storage_state(user["user_id"], "gscloud", str(state_path))
                if start_gscloud_login_thread is None:
                    raise RuntimeError("后台登录任务模块未正确加载。")

                login_job = start_gscloud_login_thread(
                    workdir=self.manager.workdir,
                    subject_type="customer",
                    subject_id=user["user_id"],
                    state_path=state_path,
                    timeout_seconds=timeout_seconds,
                    headless=headless,
                    save_callback=lambda sp: CommercialService(self.manager.workdir).set_user_credential_storage_state(user["user_id"], "gscloud", sp),
                )
                return json.dumps(
                    {
                        "ok": True,
                        "direct_command": "open_gscloud_customer_login_window",
                        "non_blocking": True,
                        "user_id": user["user_id"],
                        "login_job": login_job,
                        "next_step": "浏览器已在后台打开。本次对话不会阻塞；请在浏览器中完成登录，等待时间结束后会自动保存 Cookie。之后可用该用户自己的账号运行下载任务。",
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            except Exception as exc:
                return json.dumps(
                    {
                        "ok": False,
                        "direct_command": "open_gscloud_customer_login_window",
                        "user_id": user_id,
                        "error": str(exc),
                        "hint": "请先确认该用户已创建；可先创建商业版用户。",
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )

        return None


    def _try_direct_gscloud_tile_plan_command(self, user_text: str) -> str | None:
        """Directly calculate ASTER/GDEM tile IDs for a region such as Sichuan.

        This makes commands like “计算四川省 DEM 分幅” deterministic, so the
        assistant does not just explain tile naming without running the planner.
        """
        text = user_text.strip()
        trigger = (
            ("地理空间数据云" in text or "GDEM" in text.upper() or "ASTER" in text.upper() or "DEM" in text.upper())
            and ("分幅" in text or "瓦片" in text or "tile" in text.lower() or "数据标识" in text)
            and ("计算" in text or "哪些" in text or "识别" in text or "四川" in text or "区域" in text)
        )
        if not trigger:
            return None
        if plan_aster_gdem_tiles is None:
            return json.dumps({"ok": False, "error": "地理空间数据云分幅规划模块未正确加载。"}, ensure_ascii=False, indent=2)

        region = "四川省" if "四川" in text else ""
        # Try to use an explicitly mentioned workspace dataset name.
        ds_match = re.search(r"(?:数据集|边界|区域用)\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", text)
        region_dataset = ds_match.group(1) if ds_match else ""
        try:
            plan = plan_aster_gdem_tiles(
                manager=self.manager,
                region=region or "四川省",
                region_dataset=region_dataset,
                output_name=(region or "region") + "_aster_gdem_tiles",
                bbox_only=False,
                save_preview=True,
            )
            preview = list(plan.get("tile_ids") or [])[:30]
            return json.dumps(
                {
                    "ok": True,
                    "direct_command": "plan_gscloud_aster_gdem_tiles",
                    "region": plan.get("region"),
                    "region_dataset": plan.get("region_dataset"),
                    "region_source": plan.get("region_source"),
                    "tile_count": plan.get("tile_count"),
                    "tile_ids_preview": preview,
                    "tile_ids_text": plan.get("tile_ids_text"),
                    "derived_files": plan.get("derived_files"),
                    "next_step": "如果要自动下载这些分幅，可先提交 gscloud DEM 商业任务，再调用 run_gscloud_dem_region_auto_tiles_job；若自动点击失败，可按生成的 CSV/TXT 清单在页面中筛选数据标识并手动点击下载。",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "direct_command": "plan_gscloud_aster_gdem_tiles",
                    "error": str(exc),
                    "hint": "请先确保工作区已有四川边界数据集 sichuan_boundary；没有边界时系统会用四川省近似外包框兜底。",
                },
                ensure_ascii=False,
                indent=2,
            )

    def _extract_max_downloads(self, user_text: str, default: int = 1) -> int:
        text = user_text.strip()
        match = re.search(r"点击\s*(\d+)\s*个", text)
        if match:
            return max(1, int(match.group(1)))
        match = re.search(r"捕获\s*(\d+)\s*个", text)
        if match:
            return max(1, int(match.group(1)))
        return default

    def _resolve_gscloud_storage_state_for_job(self, commercial: Any, job: dict[str, Any]) -> str:
        """Resolve a usable GSCloud Playwright storage_state path for a commercial job.

        The non-blocking login worker writes cookies to a deterministic file while the
        browser remains open. The database used to be updated only after the whole
        login window timeout ended, so auto-download could not find the login state
        immediately after the user had logged in. This helper checks the DB path first,
        then falls back to the deterministic platform/user cookie path and writes that
        path back to the database.
        """
        state_path = commercial.resolve_job_storage_state_path(job.get("job_id", ""))
        if state_path and Path(state_path).exists():
            return str(state_path)

        mode = str(job.get("account_mode") or "").lower()
        source_key = str(job.get("source_key") or "gscloud").lower() or "gscloud"

        if mode in {"platform", "platform_account"}:
            account_id = str(job.get("account_id") or "")
            if account_id and gscloud_platform_state_path is not None:
                expected = gscloud_platform_state_path(self.manager.workdir, account_id, source_key)
                try:
                    commercial.set_platform_account_storage_state(account_id, str(expected))
                except Exception:
                    pass
                if expected.exists():
                    return str(expected)

        if mode in {"own", "user", "user_account", "manual_cookie"}:
            user_id = str(job.get("user_id") or "")
            if user_id and gscloud_user_state_path is not None:
                expected = gscloud_user_state_path(self.manager.workdir, user_id, source_key)
                try:
                    commercial.set_user_credential_storage_state(user_id, source_key, str(expected))
                except Exception:
                    pass
                if expected.exists():
                    return str(expected)

        return ""

    def _resolve_latest_gscloud_job_id(self, commercial: Any) -> str:
        """Resolve “这个任务” to the newest unfinished gscloud DEM job."""
        jobs = commercial.list_jobs(limit=30)
        preferred_status = {"queued", "waiting_manual", "running", "pending", "created"}
        for job in jobs:
            if str(job.get("source_key", "")).lower() != "gscloud":
                continue
            if str(job.get("status", "")).lower() in {"completed", "failed"}:
                continue
            if preferred_status and str(job.get("status", "")).lower() in preferred_status:
                return str(job.get("job_id"))
        # fallback: any latest unfinished gscloud job
        for job in jobs:
            if str(job.get("source_key", "")).lower() == "gscloud" and str(job.get("status", "")).lower() not in {"completed", "failed"}:
                return str(job.get("job_id"))
        raise ValueError("没有找到可运行的地理空间数据云商业任务。请先提交一个 gscloud DEM 下载任务。")

    def _try_direct_gscloud_capture_command(self, user_text: str) -> str | None:
        """Directly start GSCloud DEM capture download commands.

        Handles common commands such as:
        “运行这个任务的地理空间数据云 DEM 捕获下载，打开 ASTER GDEM 30M 页面，等待我点击 1 个下载按钮。”
        This bypasses LLM tool-selection and starts a detached worker, so the UI will not keep loading.
        """
        text = user_text.strip()
        # Keep this narrow to avoid hijacking normal questions.
        trigger = (
            "地理空间数据云" in text
            and ("捕获" in text or "点击" in text or "下载按钮" in text)
            and ("DEM" in text.upper() or "ASTER" in text.upper() or "GDEM" in text.upper())
        )
        if not trigger:
            return None
        if CommercialService is None or start_gscloud_capture_process is None:
            return json.dumps({"ok": False, "error": "商业化/地理空间数据云捕获模块未正确加载。"}, ensure_ascii=False, indent=2)

        commercial = CommercialService(self.manager.workdir)
        job_match = re.search(r"(job_[A-Za-z0-9_\-]+)", text)
        try:
            job_id = job_match.group(1) if job_match else self._resolve_latest_gscloud_job_id(commercial)
            job = commercial.get_job(job_id)
            if str(job.get("source_key", "")).lower() != "gscloud":
                raise ValueError("该任务不是地理空间数据云任务。")
            state_path = self._resolve_gscloud_storage_state_for_job(commercial, job)
            if not state_path or not Path(state_path).exists():
                raise RuntimeError(
                    "未找到可用登录态。请先为平台账号或用户账号打开地理空间数据云登录窗口并完成登录；"
                    "登录成功后等 5-10 秒，让 Cookie 文件写入 workspace/domestic_auth/ 后再启动下载。"
                )

            timeout_seconds = self._extract_timeout_seconds(text, default=1800)
            max_downloads = self._extract_max_downloads(text, default=1)
            headless = False
            commercial._update_job(job_id, status="running", progress=20, stage="starting_capture_browser")
            capture_job = start_gscloud_capture_process(
                workdir=self.manager.workdir,
                job_id=job_id,
                start_url="",  # worker defaults to ASTER GDEM 30M page
                max_downloads=max_downloads,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=True,
            )
            return json.dumps(
                {
                    "ok": True,
                    "direct_command": "start_gscloud_dem_capture_job",
                    "non_blocking": True,
                    "job_id": job_id,
                    "capture_job": capture_job,
                    "next_step": "浏览器应已在独立进程中打开。请在 ASTER GDEM 30M 页面点击下载按钮；下载完成后后台会自动解压、入库、打包，并更新该商业任务状态。你可以继续对话。",
                    "check_status": f"查看商业下载任务 {job_id} 的状态，或列出地理空间数据云 DEM 捕获下载后台任务状态。",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "direct_command": "start_gscloud_dem_capture_job",
                    "error": str(exc),
                    "hint": "请确认已先提交 gscloud DEM 任务，并且已经完成平台账号/用户账号登录保存 Cookie。",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )

    def _extract_output_name(self, user_text: str, default: str = "") -> str:
        text = user_text.strip()
        patterns = [
            r"输出名为\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)",
            r"保存为\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)",
            r"命名为\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1)
        return default

    def _extract_user_id_or_email(self, user_text: str) -> str:
        text = user_text.strip()
        m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
        if m:
            return m.group(0).lower()
        m = re.search(r"(u_[A-Za-z0-9_\-]+)", text)
        if m:
            return m.group(1)
        return ""

    def _extract_max_tiles(self, user_text: str, default: int = 0) -> int:
        text = user_text.strip()
        for pat in [r"限制\s*(\d+)\s*个", r"先\s*(?:下载|测试|限制)?\s*(\d+)\s*个", r"前\s*(\d+)\s*个"]:
            m = re.search(pat, text)
            if m:
                return max(1, int(m.group(1)))
        return default

    def _try_direct_gscloud_submit_auto_tiles_command(self, user_text: str) -> str | None:
        """Submit a commercial GSCloud DEM job and immediately start automatic tile download.

        This handles commands like:
        “为 test@example.com 提交一个地理空间数据云 DEM 下载任务，区域为四川省，使用平台账号，输出名为 sichuan_dem_paid。”

        The previous behavior often only created a job or opened a page for manual clicking.
        For commercial use, this router creates the job, calculates the region tiles and starts
        the automatic tile worker in the background, so the user does not need to know which
        ASTGTM_NxxExxx tiles cover Sichuan.
        """
        text = user_text.strip()
        trigger = (
            "提交" in text
            and "地理空间数据云" in text
            and "DEM" in text.upper()
            and "下载任务" in text
            and ("四川" in text or "区域" in text)
        )
        if not trigger:
            return None
        if CommercialService is None or start_gscloud_tile_process is None:
            return json.dumps({"ok": False, "error": "商业化/自动分幅下载模块未正确加载。"}, ensure_ascii=False, indent=2)

        commercial = CommercialService(self.manager.workdir)
        user_id = self._extract_user_id_or_email(text)
        if not user_id:
            return json.dumps({"ok": False, "error": "没有识别到用户邮箱或 user_id。示例：为 test@example.com 提交..."}, ensure_ascii=False, indent=2)
        region = "四川省" if "四川" in text else ""
        account_mode = "platform" if "平台账号" in text else "own"
        output_name = self._extract_output_name(text, default=("sichuan_dem" if region == "四川省" else "gscloud_dem"))
        max_tiles = self._extract_max_tiles(text, default=0)

        try:
            job = commercial.submit_job(
                user_id=user_id,
                source_key="gscloud",
                resource_type="dem",
                region=region or "四川省",
                account_mode=account_mode,
                request_text=text,
                output_name=output_name,
            )
            state_path = self._resolve_gscloud_storage_state_for_job(commercial, job)
            if not state_path or not Path(state_path).exists():
                commercial._update_job(job["job_id"], status="waiting_login", progress=5, stage="needs_gscloud_login_state")
                return json.dumps(
                    {
                        "ok": True,
                        "direct_command": "submit_gscloud_dem_job_auto_tiles",
                        "job": commercial.get_job(job["job_id"]),
                        "auto_started": False,
                        "reason": "未找到可用地理空间数据云登录态，所以没有启动自动下载。",
                        "next_step": "请先为平台账号或用户自己的账号打开地理空间数据云登录窗口并完成登录。登录成功后等 5-10 秒，让 Cookie 文件写入磁盘；无需等登录窗口倒计时结束。随后输入：启动这个任务的自动分幅下载。",
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )

            commercial._update_job(job["job_id"], status="running", progress=5, stage="starting_auto_tile_worker")
            tile_job = start_gscloud_tile_process(
                workdir=commercial.workdir,
                job_id=job["job_id"],
                region=region or "四川省",
                region_dataset="",
                dataset_id="310",
                max_tiles=max_tiles,
                timeout_seconds=1800,
                headless=True,
                auto_load=True,
            )
            return json.dumps(
                {
                    "ok": True,
                    "direct_command": "submit_gscloud_dem_job_auto_tiles",
                    "job": commercial.get_job(job["job_id"]),
                    "auto_started": True,
                    "auto_tile_job": tile_job,
                    "message": "已创建商业任务，并在后台启动四川省 ASTER GDEM 自动分幅下载。该流程会扫描地理空间数据云访问数据页全部分页，仅下载目标分幅；不会打开网页让用户自行选择。下载文件会经过分幅校验，错误分幅不会被标记为完成。",
                    "status_queries": [
                        f"查看商业下载任务 {job['job_id']} 的状态。",
                        "列出地理空间数据云 DEM 自动分幅下载后台任务状态。",
                    ],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "direct_command": "submit_gscloud_dem_job_auto_tiles",
                    "error": str(exc),
                    "hint": "请确认用户已创建且有平台账号额度，平台账号已保存登录态。",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )


    def _try_direct_gscloud_tile_status_command(self, user_text: str) -> str | None:
        """Directly list GSCloud automatic tile-download job status.

        Fixes this routing bug:
        用户输入“列出地理空间数据云 DEM 自动分幅下载后台任务状态”时，
        旧逻辑会误触发 start_gscloud_dem_auto_tile_job，导致它去检查登录态并报错。
        该函数必须排在“启动自动分幅下载”路由前面。
        """
        text = user_text.strip()
        trigger = (
            "地理空间数据云" in text
            and ("DEM" in text.upper() or "分幅" in text or "瓦片" in text)
            and (
                "状态" in text
                or "进度" in text
                or "后台任务" in text
                or "任务状态" in text
                or "列出" in text
                or "查看" in text
                or "查询" in text
            )
        )
        if not trigger:
            return None

        try:
            from .commercial.tile_jobs import list_gscloud_tile_jobs

            jobs = list_gscloud_tile_jobs(CommercialService(self.manager.workdir).workdir, limit=20)
            return json.dumps(
                {
                    "ok": True,
                    "direct_command": "list_gscloud_auto_tile_jobs",
                    "jobs": jobs,
                    "message": "已列出地理空间数据云 DEM 自动分幅下载后台任务状态。",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "direct_command": "list_gscloud_auto_tile_jobs",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )

    def _try_direct_gscloud_start_auto_tiles_command(self, user_text: str) -> str | None:
        """Start automatic tile download for an existing GSCloud job."""
        text = user_text.strip()
        # Status/query commands must not start a download task.
        status_words = ["列出", "查看", "查询", "状态", "进度", "后台任务", "任务状态"]
        if any(w in text for w in status_words):
            return None

        trigger = (
            "地理空间数据云" in text
            and ("自动分幅" in text or "自动下载" in text or "启动这个任务" in text)
            and ("DEM" in text.upper() or "分幅" in text)
        )
        if not trigger:
            return None
        if CommercialService is None or start_gscloud_tile_process is None:
            return json.dumps({"ok": False, "error": "商业化/自动分幅下载模块未正确加载。"}, ensure_ascii=False, indent=2)
        commercial = CommercialService(self.manager.workdir)
        try:
            job_match = re.search(r"(job_[A-Za-z0-9_\-]+)", text)
            job_id = job_match.group(1) if job_match else self._resolve_latest_gscloud_job_id(commercial)
            job = commercial.get_job(job_id)
            state_path = self._resolve_gscloud_storage_state_for_job(commercial, job)
            if not state_path or not Path(state_path).exists():
                raise RuntimeError(
                    "未找到可用登录态。请先为平台账号或用户账号打开登录窗口并完成登录；"
                    "登录成功后等 5-10 秒，让 Cookie 文件写入 workspace/domestic_auth/ 后再启动下载。"
                )
            max_tiles = self._extract_max_tiles(text, default=0)
            region = "四川省" if ("四川" in text or not job.get("region")) else str(job.get("region") or "四川省")
            commercial._update_job(job_id, status="running", progress=5, stage="starting_auto_tile_worker")
            tile_job = start_gscloud_tile_process(
                workdir=commercial.workdir,
                job_id=job_id,
                region=region,
                region_dataset="",
                dataset_id="310",
                max_tiles=max_tiles,
                timeout_seconds=1800,
                headless=True,
                auto_load=True,
            )
            return json.dumps({
                "ok": True,
                "direct_command": "start_gscloud_dem_auto_tile_job",
                "job_id": job_id,
                "auto_tile_job": tile_job,
                "next_step": "后台会自动计算区域分幅，扫描访问数据页全部分页并下载目标分幅，不会打开网站让用户自己选择。下载后会校验文件名中的 ASTGTM 分幅编号，错误或缺失分幅不会被标记为完整成功。",
            }, ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            return json.dumps({"ok": False, "direct_command": "start_gscloud_dem_auto_tile_job", "error": str(exc)}, ensure_ascii=False, indent=2)

    def ask(
        self,
        user_text: str,
        history: list[Any] | None = None,
        image_paths: list[str] | None = None,
    ) -> tuple[str, list[Any]]:
        # Deterministic execution for GSCloud login-window commands.
        # If matched, bypass the LLM and open the browser immediately.
        if not image_paths:
            direct_reply = self._try_direct_gscloud_login_command(user_text)
            if direct_reply is not None:
                return self._append_direct_reply(user_text, direct_reply, history)
            direct_reply = self._try_direct_gscloud_submit_auto_tiles_command(user_text)
            if direct_reply is not None:
                return self._append_direct_reply(user_text, direct_reply, history)
            direct_reply = self._try_direct_gscloud_tile_status_command(user_text)
            if direct_reply is not None:
                return self._append_direct_reply(user_text, direct_reply, history)

            direct_reply = self._try_direct_gscloud_start_auto_tiles_command(user_text)
            if direct_reply is not None:
                return self._append_direct_reply(user_text, direct_reply, history)
            direct_reply = self._try_direct_gscloud_capture_command(user_text)
            if direct_reply is not None:
                return self._append_direct_reply(user_text, direct_reply, history)
            direct_reply = self._try_direct_gscloud_tile_plan_command(user_text)
            if direct_reply is not None:
                return self._append_direct_reply(user_text, direct_reply, history)

        messages = list(history or [])
        messages.append({"role": "user", "content": self._build_user_content(user_text, image_paths=image_paths)})
        result = self.agent.invoke({"messages": messages})

        if isinstance(result, dict):
            new_history = result.get("messages", messages)
        else:
            new_history = messages + [result]

        if not new_history:
            return "", []

        final_message = new_history[-1]
        content = getattr(final_message, "content", None)
        if content is None and isinstance(final_message, dict):
            content = final_message.get("content", "")

        reply = self._normalize_text(content or "")
        self.manager.log_operation("智能体回复", reply[:180], "chat")
        return reply, list(new_history)
