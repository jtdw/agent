from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from collections import defaultdict
from datetime import datetime
import re
import shutil
import zipfile

from .agent import GISAgent
from .config import AUTO_ROUTE_LABEL, Settings, is_vision_model, load_settings, pick_preferred_model
from .data_manager import DataManager
from .resource_tools import get_export_task_overview


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
        self._agents: dict[str, GISAgent] = {}
        self.current_session_id = self._ensure_session()

    def _get_agent(self, model_name: str) -> GISAgent:
        if model_name not in self._agents:
            agent_settings = replace(self.settings, model=model_name)
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
        return self._get_agent(self.selected_model).register_file(file_path)

    def upload_bytes(self, filename: str, data: bytes) -> str:
        saved_path = self.manager.save_uploaded_bytes(filename, data)
        return self._get_agent(self.selected_model).register_file(str(saved_path))

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
                messages.append(self._get_agent(self.selected_model).register_file(str(path)))
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
            messages.append(self._get_agent(self.selected_model).register_file(str(shp_path)))

        return messages

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
        return get_export_task_overview(self.manager, refresh=refresh, limit=limit)

    def refresh_export_tasks(self, limit: int = 8) -> dict[str, Any]:
        return self.list_export_tasks(refresh=True, limit=limit)

    def ask(self, prompt: str, visible_prompt: str | None = None) -> dict[str, Any]:
        if not self.current_session_id:
            self.current_session_id = self._ensure_session()

        user_message = _visible_chat_content(visible_prompt if visible_prompt is not None else prompt)
        existing_messages = self.current_messages()
        if len(existing_messages) == 0:
            self.manager.database.rename_conversation(self.current_session_id, self._default_title(user_message))

        self.manager.database.add_message(self.current_session_id, "user", user_message)
        self._set_runtime_status("智能体正在运行", "正在解析任务与选择模型", busy=True, phase="routing", progress=10)

        try:
            model_name, image_paths, reason = self._decide_model(prompt)
            self._set_runtime_status("智能体正在运行", f"正在调用 {model_name} 并执行 GIS 工具", busy=True, phase="reasoning", progress=45)
            agent = self._get_agent(model_name)
            reply, _ = agent.ask(prompt, history=self._history_for_agent()[:-1], image_paths=image_paths)
            self.last_route = {"mode": self.route_mode, "model": model_name, "reason": reason, "images": image_paths}
            assistant_meta = {"model": model_name, "mode": self.route_mode, "reason": reason, "images": image_paths}
            self.manager.database.add_message(self.current_session_id, "assistant", reply, meta=assistant_meta)
            self.manager.log_operation("模型路由", f"{model_name} | {reason}", "route")
            self._set_runtime_status("运行完成", f"已完成任务，使用模型 {model_name}", busy=False, phase="complete", progress=100)
            return {"reply": reply, "model": model_name, "mode": self.route_mode, "reason": reason, "images": image_paths}
        except Exception:
            self._set_runtime_status("运行失败", "处理任务时出现错误", busy=False, phase="error", progress=0)
            raise

    def available_models(self) -> list[str]:
        return list(self.settings.supported_models)

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
