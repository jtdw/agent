from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

try:
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    create_agent = None  # type: ignore[assignment]
    ChatOpenAI = None  # type: ignore[assignment]
    _AGENT_DEPENDENCY_IMPORT_ERROR = exc
else:
    _AGENT_DEPENDENCY_IMPORT_ERROR = None

from .config import Settings
from .llm_config import validate_llm_config
if TYPE_CHECKING:
    from .data_manager import DataManager
try:
    from .tools.registry import build_tools
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    build_tools = None  # type: ignore[assignment]
    _GIS_TOOLS_IMPORT_ERROR = exc
else:
    _GIS_TOOLS_IMPORT_ERROR = None

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
你是一个交互式 AI GIS 智能体，负责基于当前工作区数据、对话上下文和工具结果完成数据检查、处理、空间分析、制图、建模与结果解释。

工作原则：
1. 必须基于用户提供的上下文、当前工作区和工具返回结果回答。
2. 不得编造字段名、文件路径、坐标系、统计值、模型指标或图件内容。
3. 如果缺少关键输入，先做最小化追问；如果上下文足够，优先调用合适工具验证后再回答。
4. 每次工具调用都应服务于当前任务计划，不要做无关操作。
5. 解释结果时说明已完成操作、使用的数据、关键结果、输出文件、含义、风险和下一步建议。
6. 外部数据下载、账号、验证码、付费或平台凭据相关流程必须遵守权限和安全边界，不绕过访问控制。
""".strip()


def _remove_default_agent_admin_tool_hints(prompt: str) -> str:
    for tool_name in (
        "commercial_system_status",
        "create_commercial_customer",
        "grant_commercial_plan",
        "add_platform_source_account",
        "open_gscloud_platform_login_window",
    ):
        prompt = prompt.replace(tool_name, "")
    return prompt


SYSTEM_PROMPT = _remove_default_agent_admin_tool_hints(SYSTEM_PROMPT)


class GISAgent:
    def __init__(self, settings: Settings, manager: "DataManager"):
        if ChatOpenAI is None or create_agent is None:
            raise RuntimeError(
                "Missing AI agent dependencies (`langchain` / `langchain-openai`). "
                "Install the full backend requirements with `pip install -r requirements.txt`."
            ) from _AGENT_DEPENDENCY_IMPORT_ERROR
        if build_tools is None:
            raise RuntimeError(
                "Missing GIS tool dependencies while initializing GISAgent. "
                "Install the full backend requirements with `pip install -r requirements.txt`."
            ) from _GIS_TOOLS_IMPORT_ERROR
        validation = validate_llm_config()
        if validation.get("status") == "invalid" or not settings.api_key:
            key_env = str(validation.get("api_key_env") or "LLM_API_KEY_ENV")
            codes = ", ".join(str(error.get("code") or "") for error in validation.get("errors", []))
            if not settings.api_key:
                codes = (codes + ", " if codes else "") + "API_KEY_MISSING"
            raise RuntimeError(
                f"LLM provider is not ready ({codes}). Set {key_env}, LLM_PROVIDER and LLM_MODEL, "
                "or run scripts/check_llm_health.py for deployment diagnostics."
            )
        self.settings = settings
        self.manager = manager
        self.model = ChatOpenAI(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            temperature=settings.temperature,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
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

    def _message_content(self, message: Any) -> Any:
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content", "")
        return content

    def _message_role(self, message: Any) -> str:
        if isinstance(message, dict):
            return str(message.get("type") or message.get("role") or "").lower()
        return str(getattr(message, "type", "") or getattr(message, "role", "") or "").lower()

    def _json_payload(self, text: str) -> Any | None:
        stripped = str(text or "").strip()
        if not stripped:
            return None
        if not ((stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]"))):
            return None
        try:
            return json.loads(stripped)
        except Exception:
            return None

    def _candidate_fields_text(self, candidates: Any) -> str:
        if not isinstance(candidates, list):
            return ""
        fields: list[str] = []
        for item in candidates[:5]:
            if isinstance(item, dict):
                field = item.get("field") or item.get("name") or item.get("column")
                ratio = item.get("numeric_ratio")
                if field:
                    if isinstance(ratio, (int, float)):
                        fields.append(f"{field}（数值比例 {ratio:.0%}）")
                    else:
                        fields.append(str(field))
            elif item:
                fields.append(str(item))
        return "、".join(fields)

    def _tool_json_summary_from_payload(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""

        if {"ok", "tool_name", "task_id", "inputs", "outputs", "artifacts"}.issubset(payload):
            if payload.get("ok"):
                lines = [
                    f"工具：{payload.get('tool_name')}",
                    f"状态：成功",
                ]
                if payload.get("summary"):
                    lines.append(f"摘要：{payload.get('summary')}")
                outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
                for key, value in list(outputs.items())[:6]:
                    if value not in ("", None):
                        lines.append(f"{key}={value}")
                artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
                for item in artifacts[:4]:
                    if isinstance(item, dict):
                        label = item.get("title") or item.get("type") or "输出文件"
                        path = item.get("path") or item.get("display_path") or ""
                        lines.append(f"{label}: {path}" if path else str(label))
                next_actions = payload.get("next_actions") if isinstance(payload.get("next_actions"), list) else []
                if next_actions:
                    lines.append("建议：" + "；".join(str(item) for item in next_actions[:3]))
                return "我已调用工具并收到结构化结果：\n" + "\n".join(f"- {line}" for line in lines)

            lines = [
                f"工具：{payload.get('tool_name')}",
                f"状态：失败",
                f"错误代码：{payload.get('error_code')}",
                f"错误标题：{payload.get('error_title')}",
                f"原因：{payload.get('user_message')}",
            ]
            next_actions = payload.get("next_actions") if isinstance(payload.get("next_actions"), list) else []
            if next_actions:
                lines.append("建议：" + "；".join(str(item) for item in next_actions[:3]))
            return "我已调用工具并收到结构化失败诊断：\n" + "\n".join(f"- {line}" for line in lines if str(line).strip())

        lines: list[str] = []
        dataset = payload.get("dataset") or payload.get("dataset_name") or payload.get("name")
        if dataset:
            lines.append(f"数据集：{dataset}")

        x_fields = self._candidate_fields_text(payload.get("x_candidates"))
        if x_fields:
            lines.append(f"可能的 X/经度字段：{x_fields}")

        y_fields = self._candidate_fields_text(payload.get("y_candidates"))
        if y_fields:
            lines.append(f"可能的 Y/纬度字段：{y_fields}")

        for key, label in (
            ("time_candidates", "可能的时间字段"),
            ("target_candidates", "可能的目标变量"),
            ("feature_candidates", "可能的特征字段"),
        ):
            value = self._candidate_fields_text(payload.get(key))
            if value:
                lines.append(f"{label}：{value}")

        suggestion = payload.get("suggestion") or payload.get("next_step") or payload.get("message")
        if suggestion:
            lines.append(f"建议：{suggestion}")

        if not lines:
            scalar_items = []
            for key, value in list(payload.items())[:6]:
                if isinstance(value, (str, int, float, bool)) and value not in ("", None):
                    scalar_items.append(f"{key}={value}")
            if scalar_items:
                lines.append("；".join(scalar_items))

        if not lines:
            return ""

        return "我已调用工具完成检查，但模型没有继续生成自然语言总结。根据工具结果：\n" + "\n".join(
            f"- {line}" for line in lines
        )

    def _latest_tool_result_summary(self, messages: list[Any]) -> str:
        for message in reversed(messages):
            role = self._message_role(message)
            text = self._normalize_text(self._message_content(message) or "").strip()
            if not text:
                continue
            payload = self._json_payload(text)
            if role in {"tool", "toolmessage"} or payload is not None:
                summary = self._tool_json_summary_from_payload(payload)
                if summary:
                    return summary
        return ""

    def _last_nonempty_reply(self, messages: list[Any]) -> str:
        for message in reversed(messages):
            role = self._message_role(message)
            if role in {"human", "user"}:
                continue
            if role in {"tool", "toolmessage"}:
                continue
            text = self._normalize_text(self._message_content(message) or "").strip()
            if text and self._json_payload(text) is None:
                return text
        return ""

    def _confirmation_id(self, action: str, **params: Any) -> str:
        payload = json.dumps({"action": action, **params}, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _direct_confirmation_reply(self, action: str, user_text: str, **params: Any) -> str | None:
        expected = self._confirmation_id(action, **params)
        if expected in user_text:
            return None
        return json.dumps(
            {
                "ok": False,
                "requires_confirmation": True,
                "direct_command": action,
                "confirmed_action_id": expected,
                "message": "This action starts browser automation or uses a platform account. Re-send the request with confirmed_action_id to proceed.",
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )

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
            if os.getenv("GIS_AGENT_ALLOW_AGENT_PLATFORM_LOGIN", "").strip().lower() not in {"1", "true", "yes", "on"}:
                return json.dumps(
                    {
                        "ok": False,
                        "direct_command": "open_gscloud_platform_login_window",
                        "account_id": account_id,
                        "error": "forbidden_agent_platform_login",
                        "hint": "Platform account login is disabled for the default agent route. Use an admin-only API or set GIS_AGENT_ALLOW_AGENT_PLATFORM_LOGIN=1 in a trusted local/admin environment.",
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            confirmation = self._direct_confirmation_reply(
                "open_gscloud_platform_login_window",
                text,
                account_id=account_id,
                timeout_seconds=timeout_seconds,
                headless=headless,
            )
            if confirmation:
                return confirmation
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
            confirmation = self._direct_confirmation_reply(
                "open_gscloud_customer_login_window",
                text,
                user_id=user_id,
                timeout_seconds=timeout_seconds,
                headless=headless,
            )
            if confirmation:
                return confirmation
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
            timeout_seconds = self._extract_timeout_seconds(text, default=1800)
            max_downloads = self._extract_max_downloads(text, default=1)
            headless = False
            confirmation = self._direct_confirmation_reply(
                "start_gscloud_dem_capture_job",
                text,
                job_id=job_id,
                max_downloads=max_downloads,
                timeout_seconds=timeout_seconds,
                headless=headless,
                auto_load=True,
            )
            if confirmation:
                return confirmation
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
            confirmation = self._direct_confirmation_reply(
                "submit_gscloud_dem_job_auto_tiles",
                text,
                user_id=user_id,
                region=region,
                account_mode=account_mode,
                output_name=output_name,
                max_tiles=max_tiles,
            )
            if confirmation:
                return confirmation
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
            max_tiles = self._extract_max_tiles(text, default=0)
            region = "未知区域" if ("??" in text or not job.get("region")) else str(job.get("region") or "未知区域")
            confirmation = self._direct_confirmation_reply(
                "start_gscloud_dem_auto_tile_job",
                text,
                job_id=job_id,
                region=region,
                max_tiles=max_tiles,
                auto_load=True,
            )
            if confirmation:
                return confirmation
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

        reply = self._last_nonempty_reply(list(new_history))
        if not reply:
            reply = self._latest_tool_result_summary(list(new_history))
        if not reply:
            reply = "我已完成处理，但模型没有返回可显示的文本。请换一种说法重试，或要求我概括当前工作区。"
        self.manager.log_operation("智能体回复", reply[:180], "chat")
        return reply, list(new_history)
