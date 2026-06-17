from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from collections import defaultdict
from datetime import datetime
import csv
import json
import re
import shutil
import zipfile

from .config import AUTO_ROUTE_LABEL, Settings, is_vision_model, load_settings, pick_preferred_model
from .context_builder import build_conversation_context, format_context_for_agent
from .conversation_intent import classify_user_intent
from .conversation_state import ConversationState, load_conversation_state, recover_conversation_state, save_conversation_state
from .followup_resolver import resolve_followup
from .frontend_context import apply_frontend_context_to_state, sanitize_frontend_context
from .model_results import generate_model_result_id
from .response_postprocess import clean_assistant_reply
from .result_interpreter import interpret_result
from .task_planner import build_task_plan
from .task_outcome_advisor import build_task_outcome
from .tool_executor import execute_validated_tool_plan
from .workflow_executor import execute_workflow_plan

try:
    from .data_manager import DataManager
except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
    DataManager = None  # type: ignore[assignment]
    _DATA_MANAGER_IMPORT_ERROR = exc
else:
    _DATA_MANAGER_IMPORT_ERROR = None


VISUAL_KEYWORDS = (
    "图", "图件", "地图", "图片", "影像", "栅格图", "截图", "照片", "可视化", "预览",
    "看一下", "解读", "判读", "识别", "检查图", "分析图", "结果图", "最新图件", "最新图"
)
TEXT_DEEP_KEYWORDS = (
    "论文", "研究", "推理", "详细", "严谨", "复杂", "方案", "设计", "代码", "误差", "原因",
    "解释", "分析", "比较", "总结", "方法", "步骤", "毕业", "报告", "评估", "开题", "文献",
    "综述", "实验", "模型", "融合", "精度", "验证", "时序", "土壤水分"
)
FAST_KEYWORDS = ("快速", "简要", "概括", "一句话", "简洁", "速览")
LOCAL_LIBRARY_CONTEXT_MARKER = "【本地文件库上下文】"


def _visible_chat_content(content: str) -> str:
    return str(content or "").split(LOCAL_LIBRARY_CONTEXT_MARKER, 1)[0].rstrip()


CAPABILITY_GROUPS = {
    "论文与文档辅助": [
        "读取 docx/txt/md 论文材料并提纲化",
        "关键词检索、章节定位、方法与结果复述",
        "围绕开题、实验设计、结果表达给出正式建议",
    ],
    "数据检查与预处理": [
        "自动识别表格坐标字段",
        "表格转点、字段预览、数据集重命名",
        "时间字段识别、缺失值统计、滞后与滚动特征构建",
    ],
    "常用矢量与栅格分析": [
        "属性筛选、缓冲区、裁剪、融合",
        "叠加分析：intersection / union / difference",
        "空间连接、质心生成、面积长度字段计算、栅格值提取",
    ],
    "数据库与结果复用": [
        "内置 SQLite 工作区数据库，自动登记上传数据和派生结果",
        "表格与矢量属性可直接入库并通过 SQL 查询生成训练表",
        "文档摘要与栅格目录也可统一登记，便于阶段材料复用",
        "训练流水线每一步都会写入数据库，可回看输入、输出和状态",
    ],
    "模型比较与论文表达": [
        "月尺度/季节尺度聚合",
        "R、RMSE、ubRMSE、Bias、NSE 等精度指标计算",
        "自动生成更适合论文的结果描述与下一步实验建议",
    ],
    "专题模型模块": [
        "BTCH 风格误差协方差加权融合与权重表输出",
        "随机森林 RF 融合训练、预测、特征重要性与模型保存",
        "XGBoost 空间回归：点图层属性训练、空间分块验证、残差分布图、Moran's I 与兼容 GCP 的空间 CV 输出",
        "LSTM 时序融合训练、预测、训练历史与模型保存",
        "GCP 地理共形预测：空间自适应预测区间、PICP/MPIW/NMPIW/QCP/IS 指标输出",
    ],
    "数据库驱动训练流水线": [
        "从 SQLite 或已有表自动生成训练表并显示完整处理步骤",
        "自动完成缺失检查、时序特征构建、模型训练与指标汇总",
        "输出流程报告、历史运行记录和阶段材料，适合新手复盘",
    ],
    "阶段材料一体化": [
        "开题/中期/答辩阶段报告自动生成",
        "模型比较摘要、答辩结论卡片与问答库",
        "结合已有图表和结果文件整理阶段性汇报材料",
    ],
    "批处理与论文出图": [
        "批量站点—栅格配准，支持长表/宽表输出",
        "自动生成精度柱状图、时序对比图、观测-预测散点图",
        "自动输出 BTCH 权重图、特征重要性图和图注草稿",
    ],
    "本地文件库": [
        "管理员可把中国行政区划、降雨、DEM、遥感产品、样点模板等基础数据放入 local_library/data",
        "前端可浏览、搜索、筛选、扫描并一键载入本地文件库条目",
        "用户提出使用内置数据时，智能体可优先从本地文件库调用并载入当前工作区",
        "文件库元数据由 library_manifest.json 管理，后续新增数据不需要改代码",
    ],
    "外部资源与底图服务": [
        "自动检查本地文件库、国内数据源、天地图 Key 和商业化下载任务是否可用",
        "行政区划、DEM、降水、土地利用等基础数据优先从本地文件库或国内数据源调用",
        "天地图用于网页矢量/影像/地形底图、注记叠加、地名检索、逆地理编码和要素辅助查询",
        "支持通过直链下载 zip/shp/tif/csv/docx 等资源并自动识别加载",
    ],
    "国内数据源下载": [
        "内置地理空间数据云、中国气象数据网、国家地球系统科学数据中心、RESDC 等数据源入口",
        "支持手动登录保存 Cookie，不绕过验证码或权限控制",
        "支持浏览器捕获下载、直链下载、已下载文件导入、自动解压与工作区入库",
        "下载结果可自动打包成 zip，方便交付给用户",
    ],
}


class GISWorkspaceService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        if DataManager is None:
            raise RuntimeError(
                "Missing GIS workspace dependency while initializing GISWorkspaceService. "
                "Install the full backend requirements with `pip install -r requirements.txt`."
            ) from _DATA_MANAGER_IMPORT_ERROR
        self.manager = DataManager(self.settings.workdir)
        self.route_mode = "auto"
        self.selected_model = self.settings.model
        self.last_route: dict[str, Any] = {
            "mode": "auto",
            "model": self.settings.model,
            "reason": "初始化默认模型",
            "images": [],
        }
        self.export_dir = self.manager.workdir / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_status: dict[str, Any] = {
            "busy": False,
            "label": "就绪",
            "detail": "等待任务",
            "started_at": None,
            "phase": "idle",
            "progress": 0,
        }
        self._agents: dict[str, Any] = {}
        self.current_session_id = self._ensure_session()

    def _get_agent(self, model_name: str) -> Any:
        if model_name not in self._agents:
            agent_settings = replace(self.settings, model=model_name)
            try:
                from .agent import GISAgent
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Missing AI agent dependency while creating GISAgent. "
                    "Install LangChain dependencies with `pip install -r requirements.txt`."
                ) from exc
            self._agents[model_name] = GISAgent(agent_settings, self.manager)
        return self._agents[model_name]

    def _ensure_session(self) -> str:
        current = self.manager.database.get_current_conversation_id()
        existing = {item["session_id"] for item in self.manager.database.list_conversations()}
        if current and current in existing:
            return current
        session_id = f"session_{uuid4().hex[:10]}"
        self.manager.database.create_conversation(session_id, "新对话")
        self.manager.database.set_current_conversation_id(session_id)
        return session_id

    def _default_title(self, text: str) -> str:
        clean = " ".join((text or "").strip().split())
        if not clean:
            return "新对话"

        job_match = re.search(r"(job_[0-9a-fA-F]+)", clean)
        if job_match and ("状态" in clean or "查看" in clean):
            return f"查看下载任务 {job_match.group(1)}"

        region_match = re.search(r"区域为([^，。,.；;\s]+)", clean)
        output_match = re.search(r"输出名为\s*([A-Za-z0-9_\-]+)", clean)
        if "DEM" in clean.upper() and ("下载" in clean or "任务" in clean):
            region = region_match.group(1) if region_match else ""
            output = output_match.group(1) if output_match else ""
            title = f"{region} DEM 下载".strip()
            if output:
                title = f"{title} {output}".strip()
            return title[:32]

        keyword_titles = [
            ("站点", "站点数据检查"),
            ("土壤水分", "土壤水分分析"),
            ("本地库", "本地文件库检查"),
            ("本地文件库", "本地文件库检查"),
            ("天地图", "天地图配置检查"),
            ("报错", "问题排查"),
            ("错误", "问题排查"),
            ("论文", "论文流程辅助"),
            ("制图", "地图制图任务"),
        ]
        for keyword, title in keyword_titles:
            if keyword in clean:
                return title

        clean = re.sub(r"[。！？!?]+$", "", clean)
        return clean[:32] or "新对话"

    def create_new_session(self, title: str | None = None) -> str:
        session_id = f"session_{uuid4().hex[:10]}"
        self.manager.database.create_conversation(session_id, title or "新对话")
        self.current_session_id = session_id
        self.manager.database.set_current_conversation_id(session_id)
        self.manager.log_operation("新建对话", session_id, "chat")
        return session_id

    def switch_session(self, session_id: str) -> None:
        existing = {item["session_id"] for item in self.manager.database.list_conversations()}
        if session_id not in existing:
            raise ValueError(f"未找到会话：{session_id}")
        self.current_session_id = session_id
        self.manager.database.set_current_conversation_id(session_id)
        self.manager.log_operation("切换对话", session_id, "chat")

    def use_session_or_current(self, session_id: str) -> bool:
        clean = str(session_id or "").strip()
        if not clean:
            self.current_session_id = self._ensure_session()
            return False

        existing = {item["session_id"] for item in self.manager.database.list_conversations()}
        if clean in existing:
            self.current_session_id = clean
            self.manager.database.set_current_conversation_id(clean)
            self.manager.log_operation("切换对话", clean, "chat")
            return True

        self.current_session_id = self._ensure_session()
        self.manager.log_operation("会话已失效，使用当前会话继续", clean, "chat")
        return False

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = self.manager.database.list_conversations()
        changed = False
        for item in sessions:
            if (item.get("title") or "").strip() != "新对话":
                continue
            messages = self.manager.database.list_messages(item["session_id"])
            first_user = next((m for m in messages if m.get("role") == "user" and str(m.get("content") or "").strip()), None)
            if not first_user:
                continue
            title = self._default_title(_visible_chat_content(first_user.get("content", "")))
            if title and title != "新对话":
                self.manager.database.rename_conversation(item["session_id"], title)
                item["title"] = title
                changed = True
        return self.manager.database.list_conversations() if changed else sessions

    def delete_session(self, session_id: str) -> str:
        sessions = self.manager.database.list_conversations()
        target = next((item for item in sessions if item["session_id"] == session_id), None)
        if not target:
            raise ValueError(f"未找到会话：{session_id}")

        was_current = session_id == self.current_session_id
        deleted_title = target.get("title", "新对话")
        self.manager.database.delete_conversation(session_id)

        remaining = [item for item in self.manager.database.list_conversations() if item["session_id"] != session_id]
        if remaining:
            next_session_id = remaining[0]["session_id"] if was_current else (self.current_session_id if self.current_session_id in {item["session_id"] for item in remaining} else remaining[0]["session_id"])
            self.current_session_id = next_session_id
            self.manager.database.set_current_conversation_id(next_session_id)
        else:
            self.current_session_id = self.create_new_session()

        self.manager.log_operation("删除对话", deleted_title, "chat")
        return self.current_session_id

    def current_messages(self) -> list[dict[str, Any]]:
        messages = self.manager.database.list_messages(self.current_session_id)
        for item in messages:
            if item.get("role") == "user":
                item["content"] = _visible_chat_content(item.get("content", ""))
        return messages

    def clear_current_chat(self) -> None:
        self.manager.database.clear_conversation_messages(self.current_session_id)
        self.manager.database.rename_conversation(self.current_session_id, "新对话")
        self.manager.log_operation("清空对话", self.current_session_id, "chat")

    def rename_session(self, session_id: str, title: str) -> None:
        existing = {item["session_id"] for item in self.manager.database.list_conversations()}
        if session_id not in existing:
            raise ValueError(f"未找到会话：{session_id}")
        clean = " ".join((title or "").strip().split())[:60]
        if not clean:
            raise ValueError("会话标题不能为空。")
        self.manager.database.rename_conversation(session_id, clean)
        self.manager.log_operation("重命名对话", clean, "chat")

    def edit_user_message_and_retry(self, message_id: int, content: str) -> dict[str, Any]:
        text = (content or "").strip()
        if not text:
            raise ValueError("消息内容不能为空。")
        messages = self.current_messages()
        target = next((item for item in messages if int(item.get("message_id") or 0) == int(message_id)), None)
        if not target:
            raise ValueError(f"当前会话未找到消息：{message_id}")
        if target.get("role") != "user":
            raise ValueError("只能编辑用户消息并重新生成。")

        self.manager.database.update_message(int(message_id), text, meta={"edited": True})
        self.manager.database.delete_messages_after(self.current_session_id, int(message_id), include_self=False)

        if int(message_id) == int(messages[0].get("message_id", -1)):
            self.manager.database.rename_conversation(self.current_session_id, self._default_title(text))

        self._set_runtime_status("智能体正在重新生成", "已回退后续消息并重新调用模型", busy=True, phase="reasoning", progress=20)
        try:
            model_name, image_paths, reason = self._decide_model(text)
            agent = self._get_agent(model_name)
            reply, _ = agent.ask(text, history=self._history_for_agent()[:-1], image_paths=image_paths)
            self.last_route = {"mode": self.route_mode, "model": model_name, "reason": reason, "images": image_paths}
            route_state = load_conversation_state(self.manager, self.current_session_id)
            route_state.last_active_chat_model = model_name
            save_conversation_state(self.manager, self.current_session_id, route_state)
            assistant_meta = {"model": model_name, "mode": self.route_mode, "reason": reason, "images": image_paths, "regenerated_from": int(message_id)}
            self.manager.database.add_message(self.current_session_id, "assistant", reply, meta=assistant_meta)
            self.manager.log_operation("重新生成回复", f"message_id={message_id} | {model_name}", "chat")
            self._set_runtime_status("重新生成完成", f"已使用模型 {model_name} 重新输出", busy=False, phase="complete", progress=100)
            return {"reply": reply, "model": model_name, "mode": self.route_mode, "reason": reason, "images": image_paths}
        except Exception:
            self._set_runtime_status("重新生成失败", "处理任务时出现错误", busy=False, phase="error", progress=0)
            raise

    def append_system_message(self, text: str, meta: dict[str, Any] | None = None) -> None:
        self.manager.database.add_message(self.current_session_id, "system", text, meta=meta)

    def _history_for_agent(self) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for item in self.current_messages():
            role = item.get("role")
            if role in {"user", "assistant"}:
                history.append({"role": role, "content": item.get("content", "")})
        return history

    def _pick_best_text_model(self, prompt: str) -> str:
        text_models = self.settings.text_models() or tuple(model for model in self.settings.supported_models if not is_vision_model(model))
        preferred = ("glm-4.7", "glm-4.5-air") if any(word in prompt for word in TEXT_DEEP_KEYWORDS) else ("glm-4.5-air", "glm-4.7")
        return pick_preferred_model(text_models, preferred) or self.settings.model

    def _pick_best_vision_model(self, prompt: str) -> str:
        vision_models = self.settings.vision_models()
        preferred = ("glm-4.1v-thinking-flashx", "glm-4.6v") if any(word in prompt for word in FAST_KEYWORDS) else ("glm-4.6v", "glm-4.1v-thinking-flashx")
        return pick_preferred_model(vision_models, preferred) or self._pick_best_text_model(prompt)

    def _prompt_needs_visual(self, prompt: str) -> bool:
        lowered = prompt.lower()
        return any(word in prompt for word in VISUAL_KEYWORDS) or "image" in lowered or "map" in lowered or "figure" in lowered

    def _latest_visual_candidates(self) -> list[str]:
        candidates: list[str] = []
        if self.manager.last_plot_path and Path(self.manager.last_plot_path).exists():
            candidates.append(self.manager.last_plot_path)
        for item in self.manager.list_artifacts():
            suffix = Path(item["path"]).suffix.lower()
            if suffix in {".png", ".jpg", ".jpeg", ".webp"} and item["path"] not in candidates:
                candidates.append(item["path"])
            if len(candidates) >= 2:
                break
        return candidates

    def _resolve_visual_context(self, prompt: str) -> tuple[list[str], str]:
        if not self._prompt_needs_visual(prompt):
            return [], "未检测到明显图像解读需求"
        candidates = self._latest_visual_candidates()
        if not candidates:
            return [], "检测到图像解读需求，但工作区暂无可附带的图件/图片"
        return candidates, f"检测到图件/图片解读需求，自动附带 {len(candidates)} 张最近图件"

    def _decide_model(self, prompt: str) -> tuple[str, list[str], str]:
        self._load_chat_model_route(self.current_session_id)
        if self.route_mode == "manual":
            image_paths, image_reason = self._resolve_visual_context(prompt)
            if not is_vision_model(self.selected_model):
                image_paths = []
            reason = f"手动指定模型：{self.selected_model}"
            if image_reason and image_paths:
                reason += f"；{image_reason}"
            return self.selected_model, image_paths, reason

        image_paths, image_reason = self._resolve_visual_context(prompt)
        if image_paths and self.settings.vision_models():
            model_name = self._pick_best_vision_model(prompt)
            return model_name, image_paths, f"自动路由到视觉模型：{image_reason}"

        model_name = self._pick_best_text_model(prompt)
        if self._prompt_needs_visual(prompt) and not self.settings.vision_models():
            return model_name, [], "检测到视觉需求，但当前配置没有视觉模型，已退回文本模型"
        if any(word in prompt for word in TEXT_DEEP_KEYWORDS):
            return model_name, [], "自动路由到更强文本模型：检测到复杂分析/论文类需求"
        return model_name, [], "自动路由到快速文本模型：常规 GIS 问答/处理请求"

    def upload_path(self, file_path: str) -> str:
        message = self._register_uploaded_file(Path(file_path))
        self._mark_latest_upload_state()
        return message

    def upload_bytes(self, filename: str, data: bytes) -> str:
        saved_path = self.manager.save_uploaded_bytes(filename, data)
        message = self._register_uploaded_file(saved_path)
        self._mark_latest_upload_state()
        return message

    def _register_uploaded_file(self, path: Path) -> str:
        try:
            return self._get_agent(self.selected_model).register_file(str(path))
        except RuntimeError as exc:
            if "LLM provider is not ready" not in str(exc) and "API_KEY_MISSING" not in str(exc):
                raise
            dataset_name = self.manager.load_path(str(path))
            record = self.manager.get(dataset_name)
            return f"Loaded dataset {dataset_name} ({record.data_type}) from {Path(path).name} using deterministic registration because the LLM provider is unavailable."

    def upload_bytes_batch(self, files: list[tuple[str, bytes]]) -> list[str]:
        if not files:
            return []

        saved_paths: list[Path] = []
        for filename, data in files:
            saved_paths.append(self.manager.save_uploaded_bytes(filename, data))

        messages: list[str] = []
        grouped_shape_parts: dict[str, list[Path]] = defaultdict(list)
        other_paths: list[Path] = []

        for path in saved_paths:
            ext = path.suffix.lower()
            if ext in {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix"}:
                grouped_shape_parts[path.stem].append(path)
            else:
                other_paths.append(path)

        for path in other_paths:
            try:
                messages.append(self._register_uploaded_file(path))
            except Exception as exc:
                # ISMN/SMN-SDR station archives contain .stm time-series files. They are
                # not ordinary tables, but the map endpoint can parse them directly from
                # uploads/. Keep the archive instead of rejecting the whole upload.
                if path.suffix.lower() == ".zip":
                    try:
                        with zipfile.ZipFile(path, "r") as zf:
                            has_station_series = any(name.lower().endswith(".stm") for name in zf.namelist())
                        if has_station_series:
                            self.manager.log_operation("保存站点观测压缩包", f"{path.name} | 地图站点图层可直接读取", "upload")
                            messages.append(f"已保存站点观测压缩包：{path.name}。该文件包含 .stm 时序，地图站点图层会自动读取，不按普通表格入库。")
                            continue
                    except Exception:
                        pass
                raise exc

        for stem, paths in grouped_shape_parts.items():
            shp_path = next((p for p in paths if p.suffix.lower() == ".shp"), None)
            if shp_path is None:
                continue
            messages.append(self._register_uploaded_file(shp_path))

        self._mark_latest_upload_state()
        return messages

    def _mark_latest_upload_state(self) -> None:
        if not self.current_session_id:
            return
        state = recover_conversation_state(self.manager, self.current_session_id)
        names = self.manager.list_dataset_names()
        if names:
            state.active_dataset = names[-1]
        state.active_artifacts = self.manager.list_artifacts()[:3]
        state.last_task_type = "data_upload_analysis"
        state.last_user_goal = "上传数据后的检查与理解"
        state.pending_clarification = None
        save_conversation_state(self.manager, self.current_session_id, state)

    def import_local_library_item(self, item: dict[str, Any]) -> str:
        """Load a registered local-library item into the current user workspace.

        The library file stays in the shared library, while DataManager copies the
        primary file and required Shapefile sidecars into this user's uploads
        directory before registering it as a normal dataset.
        """
        absolute_path = item.get("absolute_path") or item.get("path")
        if not absolute_path:
            raise ValueError("本地文件库条目缺少文件路径。")
        dataset_name = self.manager.load_path(str(absolute_path), name=item.get("name") or None)
        self.manager.log_operation(
            "从本地文件库载入数据",
            f"{item.get('name', dataset_name)} | {item.get('category', '')} | {absolute_path}",
            "local_library",
        )
        return f"已从本地文件库载入：{item.get('name', dataset_name)} -> 工作区数据集 {dataset_name}"

    def set_export_dir(self, path_str: str) -> str:
        target = Path(path_str).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        target.mkdir(parents=True, exist_ok=True)
        self.export_dir = target
        self.manager.log_operation("设置导出目录", str(target), "export")
        return str(target)

    def get_export_dir(self) -> str:
        return str(self.export_dir.resolve())

    def _set_runtime_status(self, label: str, detail: str = "", busy: bool = True, phase: str = "running", progress: int | None = None) -> None:
        current_progress = self.runtime_status.get("progress", 0)
        if progress is None:
            progress = current_progress if busy else (100 if phase == "complete" else 0)
        self.runtime_status = {
            "busy": busy,
            "label": label,
            "detail": detail,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if busy else None,
            "phase": phase,
            "progress": max(0, min(int(progress), 100)),
        }

    def _copy_result_file(self, source: Path, destination_root: Path) -> Path:
        destination_root.mkdir(parents=True, exist_ok=True)
        try:
            if source.is_relative_to(self.manager.plot_dir):
                relative = source.relative_to(self.manager.plot_dir)
                target = destination_root / "plots" / relative
            elif source.is_relative_to(self.manager.derived_dir):
                relative = source.relative_to(self.manager.derived_dir)
                target = destination_root / "derived" / relative
            else:
                target = destination_root / source.name
        except Exception:
            target = destination_root / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def export_results(self, mode: str = "all") -> dict[str, Any]:
        files = self.manager.result_file_paths()
        if not files:
            raise ValueError("当前还没有可导出的结果文件。")

        if mode == "latest":
            files = files[:1]
        elif mode != "all":
            raise ValueError("导出模式仅支持 latest 或 all。")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_root = self.export_dir / f"gis_results_{stamp}"
        copied: list[Path] = []
        for source in files:
            copied.append(self._copy_result_file(source, export_root))

        zip_path = self.export_dir / f"gis_results_{stamp}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for target in copied:
                zf.write(target, target.relative_to(export_root))

        self.manager.log_operation(
            "导出结果文件",
            f"模式: {mode} | 文件数: {len(copied)} | 目录: {export_root}",
            "export",
        )
        return {
            "mode": mode,
            "export_dir": str(export_root),
            "zip_path": str(zip_path),
            "file_count": len(copied),
            "files": [str(item) for item in copied[:20]],
        }

    def list_export_tasks(self, refresh: bool = False, limit: int = 8) -> dict[str, Any]:
        try:
            from .resource_tools import get_export_task_overview
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing agent tool dependency while listing export tasks. "
                "Install the full backend requirements with `pip install -r requirements.txt`."
            ) from exc
        return get_export_task_overview(self.manager, refresh=refresh, limit=limit)

    def refresh_export_tasks(self, limit: int = 8) -> dict[str, Any]:
        return self.list_export_tasks(refresh=True, limit=limit)

    def _column_names_for_record(self, record: Any) -> list[str]:
        columns = record.meta.get("columns") if isinstance(record.meta, dict) else None
        if isinstance(columns, list):
            return [str(item) for item in columns if str(item)]
        return []

    def _find_columns_by_keywords(self, columns: list[str], keywords: tuple[str, ...]) -> list[str]:
        matched: list[str] = []
        for column in columns:
            lowered = column.lower()
            normalized = re.sub(r"[^a-z0-9]+", "", lowered)
            has_match = False
            for keyword in keywords:
                key = keyword.lower()
                if key in {"x", "y"}:
                    has_match = normalized == key
                else:
                    has_match = key in lowered or keyword in column
                if has_match:
                    break
            if has_match:
                matched.append(column)
        return matched

    def _record_row_label(self, record: Any) -> str:
        meta = record.meta if isinstance(record.meta, dict) else {}
        if record.data_type == "table":
            return f"{meta.get('rows', 0)} 行"
        if record.data_type == "vector":
            return f"{meta.get('rows', 0)} 个要素"
        if record.data_type == "raster":
            width = meta.get("width") or "?"
            height = meta.get("height") or "?"
            count = meta.get("count") or "?"
            return f"{width}x{height} 像元，{count} 个波段"
        if record.data_type == "document":
            return f"{meta.get('characters', 0)} 字符"
        return "规模未知"

    def _missing_summary_for_record(self, name: str, record: Any) -> str:
        try:
            if record.data_type == "table":
                df = self.manager.get_table(name)
            elif record.data_type == "vector":
                gdf = self.manager.get_vector(name)
                df = gdf.drop(columns=["geometry"], errors="ignore")
            else:
                return "不适用"
            missing = df.isna().sum()
            total = int(missing.sum())
            if total == 0:
                return "未发现缺失值"
            top = [f"{col}={int(count)}" for col, count in missing[missing > 0].sort_values(ascending=False).head(5).items()]
            return f"共 {total} 个缺失值，主要字段：{', '.join(top)}"
        except Exception as exc:
            return f"缺失值统计失败：{exc}"

    def _workspace_dataset_profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for name, record in self.manager.datasets.items():
            columns = self._column_names_for_record(record)
            lon_cols = self._find_columns_by_keywords(columns, ("lon", "lng", "longitude", "经度", "x"))
            lat_cols = self._find_columns_by_keywords(columns, ("lat", "latitude", "纬度", "y"))
            time_cols = self._find_columns_by_keywords(columns, ("time", "date", "datetime", "year", "month", "day", "时间", "日期", "年", "月", "日"))
            value_cols = [col for col in columns if col not in {"geometry"} and col not in lon_cols and col not in lat_cols and col not in time_cols]
            profiles.append(
                {
                    "name": name,
                    "type": record.data_type,
                    "row_label": self._record_row_label(record),
                    "columns": columns,
                    "lon_cols": lon_cols,
                    "lat_cols": lat_cols,
                    "time_cols": time_cols,
                    "value_cols": value_cols,
                    "missing": self._missing_summary_for_record(name, record),
                    "meta": record.meta if isinstance(record.meta, dict) else {},
                }
            )
        return profiles

    def _format_workspace_summary_reply(self) -> str:
        profiles = self._workspace_dataset_profiles()
        if not profiles:
            return (
                "当前工作区还没有可分析的数据。\n\n"
                "下一步：请先上传 CSV/XLSX 表格、Shapefile/GeoJSON 边界、GeoTIFF 栅格或文档材料。上传后我会自动识别字段、坐标、时间和可用于建模的变量。"
            )

        counts = {
            "table": sum(1 for item in profiles if item["type"] == "table"),
            "vector": sum(1 for item in profiles if item["type"] == "vector"),
            "raster": sum(1 for item in profiles if item["type"] == "raster"),
            "document": sum(1 for item in profiles if item["type"] == "document"),
        }
        lines = [
            "当前工作区数据概况：",
            f"- 共 {len(profiles)} 个数据集：表格 {counts['table']} 个，矢量 {counts['vector']} 个，栅格 {counts['raster']} 个，文档 {counts['document']} 个。",
            "",
            "数据集清单：",
        ]
        for item in profiles[:12]:
            columns = item["columns"]
            field_preview = "、".join(columns[:8]) if columns else "无属性字段"
            lines.append(f"- {item['name']}：{item['type']}，{item['row_label']}，字段：{field_preview}")

        map_ready = [item["name"] for item in profiles if item["type"] in {"vector", "raster"} or (item["lon_cols"] and item["lat_cols"])]
        model_ready = [item["name"] for item in profiles if item["type"] in {"table", "vector"} and item["value_cols"]]
        analysis_ready = [item["name"] for item in profiles if item["type"] in {"table", "vector", "raster"}]
        lines.extend(
            [
                "",
                "可用性判断：",
                f"- 可直接用于制图：{', '.join(map_ready) if map_ready else '暂未发现。表格需要经纬度字段，或上传矢量/栅格数据。'}",
                f"- 可用于建模：{', '.join(model_ready) if model_ready else '暂未发现明确变量字段。需要目标变量、特征变量，最好包含坐标或时间。'}",
                f"- 可用于结果分析：{', '.join(analysis_ready) if analysis_ready else '暂无可分析数据。'}",
                "",
                "下一步建议：先运行字段与缺失值检查；如果表格包含经纬度，可生成点图层；如果有边界和栅格，可继续做裁剪、提取和专题制图。",
            ]
        )
        return "\n".join(lines)

    def _format_workspace_field_check_reply(self) -> str:
        profiles = self._workspace_dataset_profiles()
        if not profiles:
            return (
                "当前没有检测到已上传数据，因此无法检查字段、坐标、时间和缺失值。\n\n"
                "下一步：上传数据后再点击该推荐问题，我会给出字段清单、坐标识别、时间字段识别、缺失值统计和处理计划。"
            )

        lines = ["字段、坐标、时间和缺失值检查结果："]
        for item in profiles[:12]:
            columns = item["columns"]
            lines.extend(
                [
                    "",
                    f"{item['name']}（{item['type']}，{item['row_label']}）",
                    f"- 字段：{'、'.join(columns[:18]) if columns else '无属性字段'}",
                    f"- 坐标字段：经度={', '.join(item['lon_cols']) if item['lon_cols'] else '未识别'}；纬度={', '.join(item['lat_cols']) if item['lat_cols'] else '未识别'}",
                    f"- 时间字段：{', '.join(item['time_cols']) if item['time_cols'] else '未识别'}",
                    f"- 缺失值：{item['missing']}",
                ]
            )
            if item["type"] == "vector":
                meta = item["meta"]
                lines.append(f"- 空间信息：CRS={meta.get('crs') or '未知'}；几何类型={', '.join(meta.get('geometry_types') or []) or '未知'}")
            elif item["type"] == "raster":
                meta = item["meta"]
                lines.append(f"- 栅格信息：CRS={meta.get('crs') or '未知'}；nodata={meta.get('nodata')}")

        lines.extend(
            [
                "",
                "下一步处理计划：",
                "1. 先确认坐标字段和坐标系；表格若已识别经纬度，可转为点图层并检查空间范围。",
                "2. 对有缺失值的关键变量先做缺失统计、剔除或插补；不要直接进入建模。",
                "3. 若存在时间字段，统一时间格式并按日、月或季节聚合。",
                "4. 若目标是土壤水分融合，下一步需要明确目标变量、候选特征、研究区边界和训练/验证划分方式。",
            ]
        )
        return "\n".join(lines)

    def _format_soil_workflow_readiness_reply(self) -> str:
        profiles = self._workspace_dataset_profiles()
        table_or_vector = [item for item in profiles if item["type"] in {"table", "vector"}]
        has_space = any(item["type"] == "vector" or (item["lon_cols"] and item["lat_cols"]) for item in profiles)
        has_time = any(item["time_cols"] for item in profiles)
        has_value = any(item["value_cols"] for item in table_or_vector)
        missing_parts = []
        if not has_space:
            missing_parts.append("坐标字段或研究区矢量边界")
        if not has_time:
            missing_parts.append("时间字段")
        if not has_value:
            missing_parts.append("可作为目标/特征的数值字段")
        status = "具备初步检查条件" if profiles else "尚未上传数据"
        if profiles and not missing_parts:
            status = "具备进入土壤水分融合流程的基础条件"

        lines = [
            "闪电河流域土壤水分融合流程准备度检查：",
            f"- 当前状态：{status}。",
            f"- 空间信息：{'已具备' if has_space else '不足'}。",
            f"- 时间信息：{'已具备' if has_time else '不足'}。",
            f"- 建模变量：{'已发现候选字段' if has_value else '不足'}。",
        ]
        if missing_parts:
            lines.append(f"- 需要补充或确认：{', '.join(missing_parts)}。")
        lines.extend(
            [
                "",
                "建议流程：",
                "1. 完成字段、坐标、时间和缺失值检查。",
                "2. 生成统一训练表，明确土壤水分目标变量和遥感/地形/时序特征。",
                "3. 依次运行 BTCH、RF、XGBoost、LSTM，并保存指标表。",
                "4. 在模型预测结果基础上运行 GCP，输出预测区间和 PICP/MPIW 等可靠性指标。",
            ]
        )
        return "\n".join(lines)

    def _format_download_readiness_reply(self) -> str:
        profiles = self._workspace_dataset_profiles()
        map_context = [item["name"] for item in profiles if item["type"] in {"vector", "raster"} or (item["lon_cols"] and item["lat_cols"])]
        time_context = [item["name"] for item in profiles if item["time_cols"]]
        lines = [
            "下载准备检查：",
            f"- 当前工作区数据：{len(profiles)} 个数据集。",
            f"- 可作为空间范围或点位参考：{', '.join(map_context) if map_context else '暂未发现明确边界、栅格或经纬度表格。'}",
            f"- 可作为时间筛选参考：{', '.join(time_context) if time_context else '暂未识别时间字段，需要用户指定年份、月份或日期范围。'}",
            "",
            "可准备的数据方向：",
            "- DEM / 高程：需要研究区边界或经纬度范围，适合地形因子、坡度坡向和裁剪制图。",
            "- Sentinel-2：需要研究区、日期范围和云量阈值，适合植被、水体或地表覆盖特征。",
            "- 土壤水分/遥感产品：需要研究区和时间范围，适合与站点观测做匹配、融合或验证。",
            "",
            "当前数据集：",
        ]
        if profiles:
            for item in profiles[:12]:
                lines.append(f"- {item['name']}：{item['type']}，{item['row_label']}")
        else:
            lines.append("- 暂无。请先上传边界、站点表或指定行政区。")
        lines.extend(
            [
                "",
                "下一步：请补充或确认产品类型、研究区、时间范围和输出名；如果已有研究区边界，我可以直接用于下载任务的空间筛选。",
            ]
        )
        return "\n".join(lines)

    def _format_capability_reply(self) -> str:
        lines = ["我可以围绕当前工作区做这些事，包括数据检查、制图、建模、下载和结果解释："]
        for group, items in CAPABILITY_GROUPS.items():
            lines.append(f"- {group}：{'；'.join(items[:3])}")
        lines.append("")
        lines.append("你可以直接上传数据后点击推荐问题，我会优先用本地工作区数据给出确定性检查结果；需要复杂推理时再调用模型。")
        return "\n".join(lines)

    def _read_first_csv_record(self, path: str | Path) -> dict[str, Any]:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return {}
        preferred = next((row for row in rows if str(row.get("scope") or "").lower() in {"overall", "test", "spatial_cv"}), rows[0])
        out: dict[str, Any] = {}
        for key, value in preferred.items():
            if value is None:
                out[key] = value
                continue
            text = str(value).strip()
            try:
                out[key] = float(text)
            except ValueError:
                out[key] = text
        return out

    def _read_top_importance(self, path: str | Path, limit: int = 5) -> list[dict[str, Any]]:
        try:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))[:limit]
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            item: dict[str, Any] = {}
            for key, value in row.items():
                if value is None:
                    item[key] = value
                    continue
                text = str(value).strip()
                try:
                    item[key] = float(text)
                except ValueError:
                    item[key] = text
            out.append(item)
        return out

    def _model_recommendations(self, model: str, metrics: dict[str, Any], importance: list[dict[str, Any]], summary: dict[str, Any]) -> list[str]:
        recommendations: list[str] = []
        rmse = metrics.get("RMSE")
        r_value = metrics.get("R")
        nse = metrics.get("NSE")
        if isinstance(rmse, (int, float)):
            recommendations.append(f"RMSE={rmse:.4g}，建议结合目标变量量纲判断误差是否可接受，并与 RF/BTCH/LSTM 做横向比较。")
        if isinstance(r_value, (int, float)) and r_value >= 0.85:
            recommendations.append(f"R={r_value:.3f}，拟合相关性较高，但仍需要独立验证或空间分块验证排除过拟合。")
        if isinstance(nse, (int, float)) and nse < 0.5:
            recommendations.append("NSE 偏低，建议检查目标变量、异常值、时间对齐和特征缺失。")
        if importance:
            top = str(importance[0].get("feature") or importance[0].get("variable") or "")
            if top:
                recommendations.append(f"当前最重要特征是 {top}，建议在论文中解释其水文或遥感机理，并检查特征重要性是否稳定。")
        if model == "XGBoost" and not summary.get("spatial_validation"):
            recommendations.append("本次 XGBoost 未启用或未完成空间验证；正式论文结果建议补做空间分块 CV 与 GCP 不确定性分析。")
        if not recommendations:
            recommendations.append("建议打开指标表、重要性表和 summary 文件，先确认样本量、目标字段和训练参数，再进入论文结果解释。")
        return recommendations[:5]

    def discover_model_results(self) -> list[dict[str, Any]]:
        registered = self.manager.list_model_results(limit=50)
        registered_keys = {
            (
                str(item.get("metrics_dataset") or ""),
                str(item.get("metrics_path") or ""),
                str(item.get("output_prefix") or ""),
                str(item.get("model") or item.get("model_name") or ""),
            )
            for item in registered
        }
        artifacts = self.manager.list_artifacts()
        by_name = {str(item.get("name") or ""): item for item in artifacts}
        model_keys = {"xgb": "XGBoost", "rf": "RF", "lstm": "LSTM", "gcp": "GCP"}
        results: list[dict[str, Any]] = list(registered)
        for item in artifacts:
            name = str(item.get("name") or "")
            match = re.match(r"(.+)_(xgb|rf|lstm|gcp)_metrics\.csv$", name, flags=re.IGNORECASE)
            if not match:
                continue
            prefix, key = match.group(1), match.group(2).lower()
            model = model_keys.get(key, key.upper())
            metrics_dataset = Path(name).stem
            metrics_path = str(item.get("path") or "")
            if (metrics_dataset, metrics_path, prefix, model) in registered_keys:
                continue
            metrics = self._read_first_csv_record(metrics_path)
            importance_name = f"{prefix}_{key}_importance.csv"
            summary_name = f"{prefix}_{key}_summary.json"
            model_name = f"{prefix}_{key}_model.joblib"
            importance_artifact = by_name.get(importance_name)
            summary_artifact = by_name.get(summary_name)
            model_artifact = by_name.get(model_name)
            importance_rows = self._read_top_importance(str(importance_artifact.get("path"))) if importance_artifact else []
            summary: dict[str, Any] = {}
            if summary_artifact:
                try:
                    summary = json.loads(Path(str(summary_artifact.get("path"))).read_text(encoding="utf-8"))
                except Exception:
                    summary = {}
            related = [{"label": "指标表", **item}]
            if importance_artifact:
                related.append({"label": "特征重要性表", **importance_artifact})
            if summary_artifact:
                related.append({"label": "摘要文件", **summary_artifact})
            if model_artifact:
                related.append({"label": "模型文件", **model_artifact})
            results.append({
                "model_result_id": generate_model_result_id(model, prefix, legacy_key=metrics_path or name),
                "task_id": "",
                "dataset_id": str(summary.get("dataset") or ""),
                "model": model,
                "model_name": model,
                "output_prefix": prefix,
                "metrics_dataset": metrics_dataset,
                "metrics_path": metrics_path,
                "figure_path": "",
                "importance_dataset": Path(importance_name).stem if importance_artifact else "",
                "summary_dataset": Path(summary_name).stem if summary_artifact else "",
                "metrics": metrics,
                "top_importance": importance_rows,
                "summary": summary,
                "artifacts": related,
                "recommendations": self._model_recommendations(model, metrics, importance_rows, summary),
                "modified": item.get("modified") or "",
            })
        results.sort(key=lambda row: str(row.get("modified") or ""), reverse=True)
        return results[:12]

    def _format_latest_model_result_context(self) -> str:
        results = self.discover_model_results()
        if not results:
            return ""
        result = results[0]
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        metric_parts = []
        for key in ["R", "RMSE", "ubRMSE", "Bias", "NSE", "MAE"]:
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                metric_parts.append(f"{key}={value:.4g}")
        artifact_lines = []
        for artifact in result.get("artifacts", [])[:4]:
            if not isinstance(artifact, dict):
                continue
            label = str(artifact.get("label") or artifact.get("name") or "成果文件")
            display_path = str(artifact.get("display_path") or artifact.get("path") or "")
            artifact_lines.append(f"- {label}：{display_path}")
        recommendation_lines = [f"- {item}" for item in result.get("recommendations", [])[:4]]
        return "\n".join([
            "",
            "处理后的数据位置：",
            *artifact_lines,
            "",
            f"最新模型结果：{result.get('model')}（{result.get('output_prefix')}）",
            f"关键指标：{', '.join(metric_parts) if metric_parts else '请打开指标表查看详细数值'}",
            "",
            "下一步建议：",
            *recommendation_lines,
        ])

    def _should_append_model_result_context(self, prompt: str, reply: str) -> bool:
        text = f"{prompt}\n{reply}".lower()
        if "处理后的数据位置" in reply:
            return False
        tokens = ("xgboost", "xgb", "rf", "lstm", "gcp", "模型", "建模", "分析结果", "结果在哪里", "处理后的数据")
        return any(token in text for token in tokens)

    def _builtin_workspace_reply(self, prompt: str) -> str | None:
        clean = " ".join(str(prompt or "").strip().split())
        if not clean:
            return None
        if "概括当前工作区" in clean or ("工作区数据" in clean and ("制图" in clean or "建模" in clean or "结果分析" in clean)):
            return self._format_workspace_summary_reply()
        if "检查当前上传数据" in clean or ("字段" in clean and "缺失值" in clean and ("坐标" in clean or "时间" in clean)):
            return self._format_workspace_field_check_reply()
        if "BTCH" in clean and "GCP" in clean and ("土壤水分" in clean or "融合" in clean):
            return self._format_soil_workflow_readiness_reply()
        if ("下载" in clean or "DEM" in clean or "Sentinel" in clean or "遥感" in clean) and ("当前工作区" in clean or "准备" in clean or "检查" in clean):
            return self._format_download_readiness_reply()
        if "你能做什么" in clean or "有什么功能" in clean or "可以做什么" in clean:
            return self._format_capability_reply()
        return None

    def _update_conversation_state_after_turn(
        self,
        state: ConversationState,
        *,
        user_message: str,
        intent: dict[str, Any],
        plan: dict[str, Any],
        context: dict[str, Any],
        reply: str,
        dashboard_data: dict[str, Any],
        images: list[str] | None = None,
        error: Exception | None = None,
    ) -> ConversationState:
        task_type = str(plan.get("task_type") or intent.get("intent") or "")
        state.last_task_type = task_type
        state.last_user_goal = user_message or state.last_user_goal
        if context.get("referenced_object"):
            state.referenced_object = context["referenced_object"]
        if isinstance(context.get("active_dataset"), dict) and context["active_dataset"].get("name"):
            state.active_dataset = str(context["active_dataset"]["name"])
        elif not state.active_dataset:
            names = self.manager.list_dataset_names()
            state.active_dataset = names[-1] if names else ""

        artifacts = dashboard_data.get("artifacts") if isinstance(dashboard_data.get("artifacts"), list) else []
        state.active_artifacts = [item for item in artifacts[:3] if isinstance(item, dict)]
        last_plot = str(dashboard_data.get("last_plot") or "")
        if not last_plot and images:
            last_plot = images[0]
        if not last_plot:
            for item in state.active_artifacts:
                path = str(item.get("path") or "")
                if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    last_plot = path
                    break
        if last_plot:
            state.last_map_path = last_plot

        model_results = dashboard_data.get("model_results") if isinstance(dashboard_data.get("model_results"), list) else []
        if model_results and isinstance(model_results[0], dict):
            state.last_model_result = model_results[0]

        state.last_tool_results = [
            {
                "intent": intent.get("intent"),
                "task_type": task_type,
                "recommended_tools": plan.get("recommended_tools", []),
                "reply_preview": str(reply or "")[:500],
            },
            *state.last_tool_results[:2],
        ]
        state.pending_clarification = (
            {"question": plan.get("clarification_question"), "missing_inputs": plan.get("missing_inputs", [])}
            if plan.get("should_ask_clarification")
            else None
        )
        if error is not None:
            state.last_error = {"message": str(error), "task_type": task_type, "prompt": user_message}
        elif task_type != "troubleshooting":
            state.last_error = state.last_error
        save_conversation_state(self.manager, self.current_session_id, state)
        return state

    def apply_frontend_context(self, frontend_context: dict[str, Any] | None) -> None:
        if not self.current_session_id:
            self.current_session_id = self._ensure_session()
        clean_frontend_context = sanitize_frontend_context(frontend_context or {})
        if not clean_frontend_context:
            return
        state = recover_conversation_state(self.manager, self.current_session_id)
        apply_frontend_context_to_state(state, clean_frontend_context)
        save_conversation_state(self.manager, self.current_session_id, state)

    def _clean_assistant_reply(self, reply: str) -> str:
        return clean_assistant_reply(str(reply or ""))

    def ask(self, prompt: str, visible_prompt: str | None = None, frontend_context: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.current_session_id:
            self.current_session_id = self._ensure_session()

        user_message = _visible_chat_content(visible_prompt if visible_prompt is not None else prompt)
        existing_messages = self.current_messages()
        if len(existing_messages) == 0:
            self.manager.database.rename_conversation(self.current_session_id, self._default_title(user_message))

        self.manager.database.add_message(self.current_session_id, "user", user_message)
        self._set_runtime_status("智能体正在运行", "正在解析任务与选择模型", busy=True, phase="routing", progress=10)

        try:
            state = recover_conversation_state(self.manager, self.current_session_id)
            clean_frontend_context = sanitize_frontend_context(frontend_context or {})
            if clean_frontend_context:
                apply_frontend_context_to_state(state, clean_frontend_context)
                save_conversation_state(self.manager, self.current_session_id, state)
            dashboard_data = self.dashboard()
            intent = classify_user_intent(user_message, state.to_dict(), self.manager.workspace_summary())
            followup = resolve_followup(user_message, state.to_dict(), dashboard_data) if intent.get("needs_followup_resolution") or intent.get("intent") in {"follow_up_question", "result_analysis", "troubleshooting"} else {}
            if followup.get("referenced_object"):
                state.referenced_object = followup["referenced_object"]
            context = build_conversation_context(user_message, intent, state.to_dict(), self.manager, dashboard_data, followup=followup)
            plan = build_task_plan(user_message, intent, context, manager=self.manager)
            builtin_reply = self._builtin_workspace_reply(user_message)

            if plan.get("should_ask_clarification") and builtin_reply is None:
                reply = interpret_result(user_message, intent, plan, str(plan.get("clarification_question") or ""), context, dashboard_data)
                reply = self._clean_assistant_reply(reply)
                task_outcome = build_task_outcome("analysis", {"reply": reply}, dashboard=dashboard_data)
                assistant_meta = {"model": "conversation-coordinator", "mode": "clarification", "reason": "task_plan_missing_inputs", "intent": intent, "plan": plan}
                self._update_conversation_state_after_turn(
                    state,
                    user_message=user_message,
                    intent=intent,
                    plan=plan,
                    context=context,
                    reply=reply,
                    dashboard_data=dashboard_data,
                )
                self.manager.database.add_message(self.current_session_id, "assistant", reply, meta=assistant_meta)
                self.last_route = {"mode": "clarification", "model": "conversation-coordinator", "reason": "任务规划缺少关键输入", "images": []}
                self.manager.log_operation("对话澄清", user_message[:180], "chat")
                self._set_runtime_status("等待补充信息", str(plan.get("clarification_question") or ""), busy=False, phase="clarification", progress=100)
                return {"reply": reply, "model": "conversation-coordinator", "mode": "clarification", "reason": "task_plan_missing_inputs", "images": [], "task_outcome": task_outcome}

            workflow_execution = execute_workflow_plan(self.manager, plan) if plan.get("workflow_plan") else {"executed": False}
            if workflow_execution.get("executed"):
                raw_reply = str(workflow_execution.get("raw_reply") or "")
                dashboard_data = self.dashboard()
                context = build_conversation_context(user_message, intent, state.to_dict(), self.manager, dashboard_data, followup=followup)
                reply = interpret_result(user_message, intent, plan, raw_reply, context, dashboard_data)
                reply = self._clean_assistant_reply(reply)
                task_outcome = build_task_outcome("analysis", {"reply": reply}, dashboard=dashboard_data)
                images: list[str] = []
                workflow_result = workflow_execution.get("workflow_result") if isinstance(workflow_execution.get("workflow_result"), dict) else {}
                artifacts = workflow_result.get("final_artifacts") if isinstance(workflow_result.get("final_artifacts"), list) else []
                for artifact in artifacts:
                    if isinstance(artifact, dict) and str(artifact.get("type") or "") == "map" and artifact.get("path"):
                        images.append(str(artifact["path"]))
                if not workflow_execution.get("ok"):
                    state.last_error = {
                        "message": raw_reply,
                        "task_type": plan.get("task_type") or intent.get("intent"),
                        "prompt": user_message,
                        "failed_step": workflow_execution.get("failed_step"),
                    }
                assistant_meta = {
                    "model": "conversation-coordinator",
                    "mode": "deterministic_workflow",
                    "reason": "workflow_plan",
                    "intent": intent,
                    "plan": plan,
                    "workflow_execution": workflow_execution,
                }
                self._update_conversation_state_after_turn(
                    state,
                    user_message=user_message,
                    intent=intent,
                    plan=plan,
                    context=context,
                    reply=reply,
                    dashboard_data=dashboard_data,
                    images=images,
                )
                self.manager.database.add_message(self.current_session_id, "assistant", reply, meta=assistant_meta)
                self.last_route = {
                    "mode": "deterministic_workflow",
                    "model": "conversation-coordinator",
                    "reason": "workflow_plan",
                    "images": images,
                }
                self.manager.log_operation("deterministic_workflow_execution", ",".join(workflow_execution.get("executed_steps", [])), "workflow")
                self._set_runtime_status("运行完成", "已执行经过验证的 GIS 工作流", busy=False, phase="complete", progress=100)
                return {
                    "reply": reply,
                    "model": "conversation-coordinator",
                    "mode": "deterministic_workflow",
                    "reason": "workflow_plan",
                    "images": images,
                    "task_outcome": task_outcome,
                }

            deterministic_execution = execute_validated_tool_plan(self.manager, plan)
            if deterministic_execution.get("executed"):
                raw_reply = str(deterministic_execution.get("raw_reply") or "")
                dashboard_data = self.dashboard()
                context = build_conversation_context(user_message, intent, state.to_dict(), self.manager, dashboard_data, followup=followup)
                reply = interpret_result(user_message, intent, plan, raw_reply, context, dashboard_data)
                reply = self._clean_assistant_reply(reply)
                task_outcome = build_task_outcome("analysis", {"reply": reply}, dashboard=dashboard_data)
                images: list[str] = []
                for tool_result in deterministic_execution.get("tool_results", []):
                    if not isinstance(tool_result, dict):
                        continue
                    artifacts = tool_result.get("artifacts") if isinstance(tool_result.get("artifacts"), list) else []
                    for artifact in artifacts:
                        if isinstance(artifact, dict) and str(artifact.get("type") or "") == "map" and artifact.get("path"):
                            images.append(str(artifact["path"]))
                if not deterministic_execution.get("ok"):
                    state.last_error = {
                        "message": raw_reply,
                        "task_type": plan.get("task_type") or intent.get("intent"),
                        "prompt": user_message,
                        "failed_tool": deterministic_execution.get("failed_tool"),
                    }
                assistant_meta = {
                    "model": "conversation-coordinator",
                    "mode": "deterministic_tool",
                    "reason": "validated_tool_args",
                    "intent": intent,
                    "plan": plan,
                    "tool_execution": deterministic_execution,
                }
                self._update_conversation_state_after_turn(
                    state,
                    user_message=user_message,
                    intent=intent,
                    plan=plan,
                    context=context,
                    reply=reply,
                    dashboard_data=dashboard_data,
                    images=images,
                )
                self.manager.database.add_message(self.current_session_id, "assistant", reply, meta=assistant_meta)
                self.last_route = {
                    "mode": "deterministic_tool",
                    "model": "conversation-coordinator",
                    "reason": "validated_tool_args",
                    "images": images,
                }
                self.manager.log_operation("deterministic_tool_execution", ",".join(deterministic_execution.get("executed_tools", [])), "tool")
                self._set_runtime_status("运行完成", "已执行经过验证的 GIS 工具计划", busy=False, phase="complete", progress=100)
                return {
                    "reply": reply,
                    "model": "conversation-coordinator",
                    "mode": "deterministic_tool",
                    "reason": "validated_tool_args",
                    "images": images,
                    "task_outcome": task_outcome,
                }

            if builtin_reply is not None:
                dashboard_data = self.dashboard()
                task_outcome = build_task_outcome("analysis", {"reply": builtin_reply}, dashboard=dashboard_data)
                builtin_reply = interpret_result(user_message, intent, plan, builtin_reply, context, dashboard_data)
                builtin_reply = self._clean_assistant_reply(builtin_reply)
                assistant_meta = {"model": "builtin-workspace", "mode": "builtin", "reason": "builtin_workspace_prompt", "intent": intent, "plan": plan}
                self._update_conversation_state_after_turn(
                    state,
                    user_message=user_message,
                    intent=intent,
                    plan=plan,
                    context=context,
                    reply=builtin_reply,
                    dashboard_data=dashboard_data,
                )
                self.manager.database.add_message(self.current_session_id, "assistant", builtin_reply, meta=assistant_meta)
                self.last_route = {"mode": "builtin", "model": "builtin-workspace", "reason": "内置工作区推荐问题", "images": []}
                self.manager.log_operation("内置推荐问题回复", user_message[:180], "chat")
                self._set_runtime_status("运行完成", "已基于本地工作区生成回答", busy=False, phase="complete", progress=100)
                return {"reply": builtin_reply, "model": "builtin-workspace", "mode": "builtin", "reason": "builtin_workspace_prompt", "images": [], "task_outcome": task_outcome}

            referenced = context.get("referenced_object") if isinstance(context.get("referenced_object"), dict) else {}
            if referenced and str(intent.get("intent") or "") in {"follow_up_question", "result_analysis", "troubleshooting"}:
                ref_type = str(referenced.get("type") or "object")
                ref_id = str(referenced.get("id") or referenced.get("artifact_id") or referenced.get("model_result_id") or "")
                ref_label = str(referenced.get("label") or referenced.get("name") or ref_id or ref_type)
                ref_path = str(referenced.get("path") or "")
                raw_parts = [
                    f"已定位当前引用对象：{ref_label}",
                    f"对象类型：{ref_type}",
                ]
                if ref_id:
                    raw_parts.append(f"对象 ID：{ref_id}")
                if ref_path:
                    raw_parts.append(f"对象路径：{ref_path}")
                raw_parts.append("本轮基于当前工作区记录和前端选中对象进行解释，没有重新生成或编造新的指标。")
                raw_reply = "\n".join(raw_parts)
                reply = interpret_result(user_message, intent, plan, raw_reply, context, dashboard_data)
                reply = self._clean_assistant_reply(reply)
                task_outcome = build_task_outcome("analysis", {"reply": reply}, dashboard=dashboard_data)
                assistant_meta = {
                    "model": "conversation-coordinator",
                    "mode": "deterministic_context",
                    "reason": "referenced_object_context",
                    "intent": intent,
                    "plan": plan,
                    "referenced_object": referenced,
                }
                self._update_conversation_state_after_turn(
                    state,
                    user_message=user_message,
                    intent=intent,
                    plan=plan,
                    context=context,
                    reply=reply,
                    dashboard_data=dashboard_data,
                )
                self.manager.database.add_message(self.current_session_id, "assistant", reply, meta=assistant_meta)
                self.last_route = {"mode": "deterministic_context", "model": "conversation-coordinator", "reason": "referenced_object_context", "images": []}
                self.manager.log_operation("deterministic_context_reply", ref_label[:180], "chat")
                self._set_runtime_status("运行完成", "已基于当前选中对象生成解释", busy=False, phase="complete", progress=100)
                return {
                    "reply": reply,
                    "model": "conversation-coordinator",
                    "mode": "deterministic_context",
                    "reason": "referenced_object_context",
                    "images": [],
                    "task_outcome": task_outcome,
                }

            model_name, image_paths, reason = self._decide_model(prompt)
            self._set_runtime_status("智能体正在运行", f"正在调用 {model_name} 并执行 GIS 工具", busy=True, phase="reasoning", progress=45)
            agent = self._get_agent(model_name)
            enhanced_prompt = (
                f"{prompt}\n\n【对话协调上下文】\n{format_context_for_agent(context)}"
                f"\n\n【结构化任务计划】\n{json.dumps(plan, ensure_ascii=False, indent=2, default=str)}"
                "\n\n请严格基于以上上下文、当前工作区和工具结果回答；不要编造字段、路径、指标或图件内容。"
            )
            reply, _ = agent.ask(enhanced_prompt, history=self._history_for_agent()[:-1], image_paths=image_paths)
            if self._should_append_model_result_context(user_message, reply):
                model_context = self._format_latest_model_result_context()
                if model_context:
                    reply = f"{reply.rstrip()}\n{model_context}"
            dashboard_data = self.dashboard()
            context = build_conversation_context(user_message, intent, state.to_dict(), self.manager, dashboard_data, followup=followup)
            reply = interpret_result(user_message, intent, plan, reply, context, dashboard_data)
            reply = self._clean_assistant_reply(reply)
            task_outcome = build_task_outcome("analysis", {"reply": reply}, dashboard=dashboard_data)
            self.last_route = {"mode": self.route_mode, "model": model_name, "reason": reason, "images": image_paths}
            state.last_active_chat_model = model_name
            assistant_meta = {"model": model_name, "mode": self.route_mode, "reason": reason, "images": image_paths, "intent": intent, "plan": plan}
            self._update_conversation_state_after_turn(
                state,
                user_message=user_message,
                intent=intent,
                plan=plan,
                context=context,
                reply=reply,
                dashboard_data=dashboard_data,
                images=image_paths,
            )
            self.manager.database.add_message(self.current_session_id, "assistant", reply, meta=assistant_meta)
            self.manager.log_operation("模型路由", f"{model_name} | {reason}", "route")
            self._set_runtime_status("运行完成", f"已完成任务，使用模型 {model_name}", busy=False, phase="complete", progress=100)
            return {"reply": reply, "model": model_name, "mode": self.route_mode, "reason": reason, "images": image_paths, "task_outcome": task_outcome}
        except Exception as exc:
            try:
                state = recover_conversation_state(self.manager, self.current_session_id)
                state.last_error = {"message": str(exc), "task_type": "unknown", "prompt": user_message}
                save_conversation_state(self.manager, self.current_session_id, state)
            except Exception:
                pass
            self._set_runtime_status("运行失败", "处理任务时出现错误", busy=False, phase="error", progress=0)
            raise

    def available_models(self) -> list[str]:
        return list(self.settings.supported_models)

    def _load_chat_model_route(self, session_id: str | None = None) -> ConversationState:
        target = str(session_id or self.current_session_id or "").strip()
        if not target:
            target = self._ensure_session()
        state = load_conversation_state(self.manager, target)
        selected = str(state.selected_chat_model or "").strip()
        if state.model_route_mode == "manual" and selected in self.settings.supported_models:
            self.route_mode = "manual"
            self.selected_model = selected
            return state
        if state.model_route_mode != "auto" or selected:
            state.model_route_mode = "auto"
            state.selected_chat_model = ""
            save_conversation_state(self.manager, target, state)
        self.route_mode = "auto"
        self.selected_model = self.settings.model
        return state

    def chat_model_state(self, session_id: str | None = None) -> dict[str, Any]:
        target = str(session_id or self.current_session_id or "").strip()
        if not target:
            target = self._ensure_session()
        existing = {str(item.get("session_id") or "") for item in self.manager.database.list_conversations()}
        if target not in existing:
            raise ValueError(f"未找到会话：{target}")
        state = self._load_chat_model_route(target)
        return {
            "session_id": target,
            "route_mode": self.route_mode,
            "selected_model": self.selected_model if self.route_mode == "manual" else "auto",
            "active_model": state.last_active_chat_model or self.active_model(),
            "models": [
                {"id": model, "capability": "vision" if is_vision_model(model) else "text"}
                for model in self.available_models()
            ],
        }

    def select_chat_model(self, model_name: str, session_id: str | None = None) -> dict[str, Any]:
        target = str(session_id or self.current_session_id or "").strip()
        if not target:
            target = self._ensure_session()
        existing = {str(item.get("session_id") or "") for item in self.manager.database.list_conversations()}
        if target not in existing:
            raise ValueError(f"未找到会话：{target}")
        clean = str(model_name or "").strip()
        if clean != "auto" and clean not in self.settings.supported_models:
            raise ValueError(f"不支持的模型：{clean}")
        state = load_conversation_state(self.manager, target)
        state.model_route_mode = "auto" if clean == "auto" else "manual"
        state.selected_chat_model = "" if clean == "auto" else clean
        save_conversation_state(self.manager, target, state)
        self.manager.log_operation("切换会话模型", clean or "auto", "config")
        return self.chat_model_state(target)

    def route_options(self) -> list[str]:
        return [AUTO_ROUTE_LABEL, *self.available_models()]

    def current_model(self) -> str:
        return self.selected_model if self.route_mode == "manual" else AUTO_ROUTE_LABEL

    def active_model(self) -> str:
        return self.last_route.get("model") or self.selected_model

    def switch_model(self, model_name: str) -> str:
        if model_name == AUTO_ROUTE_LABEL:
            self.route_mode = "auto"
            self.last_route = {"mode": "auto", "model": self.active_model(), "reason": "已切换为自动选择模型", "images": []}
            self.manager.log_operation("切换模型策略", "已切换为自动选择", "config")
            message = "已切换为自动选择模型：系统会根据用户需求在文本模型和视觉模型之间自动分流。"
            self.append_system_message(message)
            return message

        if model_name not in self.settings.supported_models:
            raise ValueError(f"不支持的模型：{model_name}")

        self.route_mode = "manual"
        self.selected_model = model_name
        self.settings.model = model_name
        self.last_route = {"mode": "manual", "model": model_name, "reason": f"已手动指定模型：{model_name}", "images": []}
        self.manager.log_operation("切换模型策略", f"手动指定 {model_name}", "config")
        message = f"已切换为手动模式：{model_name}。后续新对话将固定使用该模型，直到你再次改回自动选择。"
        self.append_system_message(message)
        return message

    def dashboard(self) -> dict[str, Any]:
        datasets = self.manager.list_datasets()
        counts = {
            "vector": sum(1 for item in datasets if item["type"] == "vector"),
            "raster": sum(1 for item in datasets if item["type"] == "raster"),
            "table": sum(1 for item in datasets if item["type"] == "table"),
            "document": sum(1 for item in datasets if item["type"] == "document"),
        }
        db_status = self.manager.database_status()
        recent_runs = self.manager.list_pipeline_runs(limit=8)
        latest_pipeline = recent_runs[0] if recent_runs else None
        if latest_pipeline:
            latest_pipeline = self.manager.pipeline_run_detail(latest_pipeline["run_id"])
        model_results = self.discover_model_results()

        return {
            "summary": self.manager.workspace_summary(),
            "datasets": datasets,
            "artifacts": self.manager.list_artifacts(),
            "activity": self.manager.operation_log,
            "dataset_type_counts": counts,
            "workdir": str(self.manager.workdir.resolve()),
            "export_dir": self.get_export_dir(),
            "runtime_status": self.runtime_status,
            "recent_export_tasks": self.list_export_tasks(refresh=False, limit=8).get("items", []),
            "last_plot": self.manager.last_plot_path,
            "route_options": self.route_options(),
            "current_model": self.current_model(),
            "active_model": self.active_model(),
            "route_mode": self.route_mode,
            "last_route": self.last_route,
            "capability_groups": CAPABILITY_GROUPS,
            "database": db_status,
            "latest_pipeline": latest_pipeline,
            "model_results": model_results,
            "current_session_id": self.current_session_id,
            "sessions": self.list_sessions(),
            "messages": self.current_messages(),
            "suggestions": [
                "概括当前工作区的数据内容，并告诉我哪些能直接用于制图。",
                "识别表格中的坐标字段，并把表格转点生成一张分布图。",
                "对两个面图层做 intersection，然后计算面积字段。",
                "把站点点位的栅格值提取出来，并总结结果是否适合建模。",
                "统计面内点数量并生成适合论文写作的结果表述。",
                "解读一下最新图件，告诉我空间格局与异常位置。",
                "使用地理空间数据云或本地文件库准备四川省 DEM，并自动载入工作区。",
                "先检查本地文件库、国内数据源与天地图配置，再准备广东省 2020 年 6 月累计降水数据。",
            ],
        }

    def latest_plot_path(self) -> str:
        return self.manager.last_plot_path
