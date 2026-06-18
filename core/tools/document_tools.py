from __future__ import annotations

from typing import Any

from core.tools import document_helpers as _helpers

DOCUMENT_TOOL_NAMES = {
    'preview_document',
    'document_outline',
    'search_document_text',
    'generate_stage_report',
}

_LEGACY_DEPENDENCIES = (
    'Any',
    '_artifact_safe_name',
    '_extract_btch_highlights',
    '_extract_feature_highlights',
    '_extract_metric_highlights',
    '_find_dataset_by_keywords',
    '_first_nonempty_text',
    '_heading_like_lines',
    '_json',
    '_make_text_snippets',
    '_prepare_dataframe',
    '_recent_artifact_paths',
    '_resolve_document_text_input',
    '_save_json_artifact',
    '_save_markdown_artifact',
    '_table_markdown',
    'pd',
    'tool',
)

for _name in _LEGACY_DEPENDENCIES:
    globals()[_name] = getattr(_helpers, _name)

def build_document_tools(manager: Any, *, legacy_tools: list[Any] | None = None) -> list[Any]:

    @tool
    def preview_document(dataset_name: str, max_chars: int = 1500) -> str:
        """预览文档前若干字符，适合快速查看开题报告、论文草稿、说明文档的正文内容。"""
        text = manager.preview_document(dataset_name, max_chars=max_chars)
        manager.log_operation("预览文档", f"{dataset_name} | {max_chars} chars", "document")
        return text


    @tool
    def document_outline(dataset_name: str, max_items: int = 30) -> str:
        """提取文档中疑似标题、章节或提纲行，适合快速梳理论文或报告结构。"""
        text = manager.get_document_text(dataset_name)
        outline = _heading_like_lines(text, max_items=max_items)
        manager.log_operation("提取文档提纲", dataset_name, "document")
        return _json({"dataset": dataset_name, "outline": outline, "count": len(outline)})


    @tool
    def search_document_text(dataset_name: str, keyword: str, context_chars: int = 120, max_hits: int = 8) -> str:
        """在文档中检索关键词并返回上下文片段，适合定位研究目标、技术路线、实验设计等内容。"""
        text = manager.get_document_text(dataset_name)
        hits = _make_text_snippets(text, keyword=keyword, context_chars=context_chars, max_hits=max_hits)
        manager.log_operation("文档关键词检索", f"{dataset_name} | {keyword}", "document")
        return _json({"dataset": dataset_name, "keyword": keyword, "hits": hits, "count": len(hits)})


    @tool
    def generate_stage_report(
        stage: str,
        output_prefix: str = "stage_pack",
        topic: str = "",
        research_document: str = "",
        metrics_dataset: str = "",
        gcp_metrics_dataset: str = "",
        feature_importance_dataset: str = "",
        btch_weights_dataset: str = "",
        figure_notes_document: str = "",
    ) -> str:
        """生成开题/中期/答辩一体化阶段材料，包括阶段报告、汇报提纲、答辩问答库和材料清单。stage 支持 proposal/opening、midterm、defense。"""
        stage_key = stage.strip().lower()
        aliases = {
            "opening": "proposal", "open": "proposal", "proposal": "proposal", "开题": "proposal",
            "midterm": "midterm", "mid": "midterm", "中期": "midterm",
            "defense": "defense", "答辩": "defense",
        }
        if stage_key not in aliases:
            raise ValueError("stage 仅支持 proposal/opening、midterm、defense。")
        stage_key = aliases[stage_key]

        if not research_document:
            research_document = _find_dataset_by_keywords(manager, ["开题"], {"document"}) or _find_dataset_by_keywords(manager, ["report"], {"document"}) or ""
        if not metrics_dataset:
            metrics_dataset = _find_dataset_by_keywords(manager, ["metrics"], {"table"}) or _find_dataset_by_keywords(manager, ["accuracy"], {"table"}) or ""
        if not gcp_metrics_dataset:
            gcp_metrics_dataset = _find_dataset_by_keywords(manager, ["gcp", "metrics"], {"table"}) or ""
        if not feature_importance_dataset:
            feature_importance_dataset = _find_dataset_by_keywords(manager, ["importance"], {"table"}) or ""
        if not btch_weights_dataset:
            btch_weights_dataset = _find_dataset_by_keywords(manager, ["btch", "weight"], {"table"}) or _find_dataset_by_keywords(manager, ["weights"], {"table"}) or ""
        if not figure_notes_document:
            figure_notes_document = _find_dataset_by_keywords(manager, ["figure", "notes"], {"document"}) or ""

        doc_text = manager.get_document_text(research_document) if research_document else ""
        doc_preview = doc_text[:2400].strip()
        topic_text = _first_nonempty_text(topic, "基于多源遥感的流域表层土壤水分数据融合及模型比较研究")
        datasets = manager.list_datasets()
        artifacts = manager.list_artifacts()

        metrics_md = ""
        metric_highlights: dict[str, Any] = {}
        if metrics_dataset:
            metrics_df = _prepare_dataframe(metrics_dataset, manager)
            metric_highlights = _extract_metric_highlights(metrics_df, dataset_name=metrics_dataset)
            metrics_md = _table_markdown(metrics_df)

        gcp_metrics_md = ""
        gcp_highlights: dict[str, Any] = {}
        if gcp_metrics_dataset:
            gcp_metrics_df = _prepare_dataframe(gcp_metrics_dataset, manager)
            gcp_highlights = _extract_metric_highlights(gcp_metrics_df, dataset_name=gcp_metrics_dataset)
            gcp_metrics_md = _table_markdown(gcp_metrics_df)

        importance_md = ""
        feature_highlights: list[dict[str, Any]] = []
        if feature_importance_dataset:
            importance_df = _prepare_dataframe(feature_importance_dataset, manager)
            feature_highlights = _extract_feature_highlights(importance_df)
            importance_md = _table_markdown(importance_df)

        btch_md = ""
        btch_highlights: dict[str, Any] = {}
        if btch_weights_dataset:
            btch_df = _prepare_dataframe(btch_weights_dataset, manager)
            btch_highlights = _extract_btch_highlights(btch_df)
            btch_md = _table_markdown(btch_df)

        figure_notes_text, figure_notes_source = _resolve_document_text_input(manager, figure_notes_document) if figure_notes_document else ("", "")
        figure_notes = figure_notes_text[:2000]
        recent_pngs = _recent_artifact_paths(manager, {".png"}, limit=10)
        recent_docs = _recent_artifact_paths(manager, {".md", ".txt", ".json", ".csv"}, limit=12)

        dataset_overview = pd.DataFrame([
            {"name": item["name"], "type": item["type"], "path": item["path"]} for item in datasets
        ]) if datasets else pd.DataFrame(columns=["name", "type", "path"])
        artifact_overview = pd.DataFrame([
            {"name": item["name"], "category": item["category"], "path": item["path"]} for item in artifacts[:16]
        ]) if artifacts else pd.DataFrame(columns=["name", "category", "path"])

        stage_titles = {"proposal": "开题阶段", "midterm": "中期检查阶段", "defense": "答辩阶段"}
        common_header = (
            f"# {topic_text}{stage_titles[stage_key]}材料包\n\n"
            f"- 阶段：{stage_titles[stage_key]}\n"
            f"- 研究主题：{topic_text}\n"
            f"- 工作区数据集数量：{len(datasets)}\n"
            f"- 工作区成果文件数量：{len(artifacts)}\n"
            f"- 点预测精度表：{metrics_dataset or '未指定'}\n"
            f"- GCP 不确定性表：{gcp_metrics_dataset or '未指定'}\n\n"
        )

        if stage_key == "proposal":
            report_parts = [
                common_header,
                "## 1. 研究背景与选题意义\n" ,
                (doc_preview or "请结合研究区背景、土壤水分的重要性、多源遥感产品的互补性来补充该部分。") + "\n\n" ,
                "## 2. 拟解决的核心问题\n"
                "- 如何在统一空间边界、统一深度和统一时间尺度下整合多源土壤水分产品。\n"
                "- 如何比较 BTCH、RF、XGBoost 与 LSTM 在流域尺度上的适用性。\n"
                "- 如何从总体、时间和空间维度完成独立验证与论文表达。\n"
                "- 如何联合汇报点预测精度与 GCP 不确定性结果。\n\n" ,
                "## 3. 数据基础与预处理计划\n" + _table_markdown(dataset_overview, 20) + "\n\n" ,
                "## 4. 方法路线\n"
                "1. 站点—栅格配准与时间对齐。\n"
                "2. 缺失值检查与时序特征构建。\n"
                "3. BTCH、RF、XGBoost、LSTM 建模。\n"
                "4. 按 2019 训练、2020 验证开展时间外推检验。\n"
                "5. 生成点预测图表与 GCP 区间结果分析。\n\n" ,
                "## 5. 预期成果\n"
                "- 融合结果表与精度评价表。\n"
                "- 权重变化图、特征重要性图、观测-预测散点图。\n"
                "- GCP 指标表与不确定性比较结果。\n"
                "- 开题、中期、答辩三阶段可复用材料模板。\n\n" ,
                "## 6. 风险点与应对\n"
                "- 缺失值过多：优先做站点—栅格配准后的可用性评估。\n"
                "- 时间交集不足：统一交集时间窗并记录删减规则。\n"
                "- 模型泛化不足：坚持时间外推验证，避免随机混洗替代独立验证。\n"
                "- 汇报混淆：将点预测精度和 GCP 不确定性分成两类图表与表格分别表述。\n" ,
            ]
            report = "".join(report_parts)
            outline = (
                "# 开题汇报提纲\n\n"
                "1. 选题背景与意义\n"
                "2. 国内外研究现状与不足\n"
                "3. 数据来源与研究区\n"
                "4. 技术路线与关键方法（BTCH/RF/XGBoost/LSTM/GCP）\n"
                "5. 进度安排与预期成果\n"
                "6. 风险点与可行性说明\n"
            )
            qa = (
                "# 开题常见问题与回答提纲\n\n"
                "1. 为什么选择该流域？\n- 因为其生态脆弱、水文敏感，且已有站网支撑独立验证。\n\n"
                "2. 为什么要同时比较四类方法？\n- 因为它们分别代表误差统计加权、传统集成学习、提升树回归与时序深度学习，具有互补性。\n\n"
                "3. 为什么还要做 GCP？\n- 因为点预测精度只能说明准确性，GCP 进一步回答模型预测区间是否可靠、是否足够紧致。\n"
            )
        elif stage_key == "midterm":
            highlights = []
            if metric_highlights.get("best_r"):
                highlights.append(f"点预测相关性最优模型：{metric_highlights['best_r']['predicted']} (R={metric_highlights['best_r']['R']:.3f})")
            if metric_highlights.get("best_rmse"):
                highlights.append(f"点预测误差最小模型：{metric_highlights['best_rmse']['predicted']} (RMSE={metric_highlights['best_rmse']['RMSE']:.3f})")
            if gcp_highlights.get("best_picp"):
                highlights.append(f"GCP 覆盖率最优模型：{gcp_highlights['best_picp']['predicted']} (PICP={gcp_highlights['best_picp']['PICP']:.3f})")
            if gcp_highlights.get("best_is"):
                highlights.append(f"GCP 区间评分最优模型：{gcp_highlights['best_is']['predicted']} (IS={gcp_highlights['best_is']['IS']:.3f})")
            highlight_text = "\n".join(f"- {item}" for item in highlights) if highlights else "- 当前尚未指定指标表，建议在中期材料中分别补充点预测精度表和 GCP 不确定性表。"
            report_parts = [
                common_header,
                "## 1. 已完成工作\n"
                "- 已形成数据清点、站点—栅格配准、时序特征构建与基础精度评价流程。\n"
                "- 已接入 BTCH、RF、XGBoost、LSTM 及论文图表自动生成模块。\n"
                "- 已生成的成果文件如下：\n" ,
                _table_markdown(artifact_overview, 20) + "\n\n" ,
                "## 2. 阶段性结果\n" ,
                highlight_text + "\n\n" ,
            ]
            if metrics_md:
                report_parts.append("### 2.1 点预测精度摘要\n" + metrics_md + "\n\n")
            if gcp_metrics_md:
                report_parts.append("### 2.2 GCP 不确定性摘要\n" + gcp_metrics_md + "\n\n")
            if importance_md:
                report_parts.append("### 2.3 特征重要性摘要\n" + importance_md + "\n\n")
            if btch_md:
                report_parts.append("### 2.4 BTCH 权重摘要\n" + btch_md + "\n\n")
            report_parts.append(
                "## 3. 当前存在的问题\n"
                "- 不同产品时间交集与缺失模式可能不一致。\n"
                "- 站点样本量与时序长度可能限制 LSTM 稳定性。\n"
                "- 不同分区结果仍需补充月尺度、季节尺度与空间分组分析。\n"
                "- 点预测精度与 GCP 不确定性需要分开解释，避免把 R/RMSE 与 PICP/MPIW 混为一谈。\n\n"
                "## 4. 后续计划\n"
                "- 完成统一指标表并补全图表编号。\n"
                "- 完成 2020 独立验证期的模型对比。\n"
                "- 补充分地类/高程/坡度分组统计。\n"
                "- 整理论文结果章节初稿。\n"
            )
            report = "".join(report_parts)
            outline = (
                "# 中期汇报提纲\n\n"
                "1. 研究目标回顾\n"
                "2. 数据准备与流程进展\n"
                "3. 已完成的模型与图表\n"
                "4. 阶段性结果（点预测精度 + GCP 不确定性）\n"
                "5. 当前问题与原因分析\n"
                "6. 后续工作计划\n"
            )
            qa = (
                "# 中期检查常见问题与回答提纲\n\n"
                "1. 当前最好的模型是谁？\n- 回答时先基于独立验证期点预测指标表，再补充 GCP 不确定性结果，说明准确性与可靠性并不完全等价。\n\n"
                "2. 为什么中期还不能直接下最终结论？\n- 因为还需补充分组检验、季节尺度分析，并把点预测与 GCP 区间结果联合整合。\n\n"
                "3. 后续最关键工作是什么？\n- 完成统一验证框架下的模型比较，并将点预测精度与不确定性结果转换为论文图表和章节文本。\n"
            )
        else:
            ranking_lines = []
            for idx, row in enumerate(metric_highlights.get("ranking", [])[:5], start=1):
                ranking_lines.append(f"{idx}. {row.get('predicted')}（点预测综合排序分数 {row.get('rank_score'):.2f}）")
            gcp_ranking_lines = []
            for idx, row in enumerate(gcp_highlights.get("ranking", [])[:5], start=1):
                gcp_ranking_lines.append(f"{idx}. {row.get('predicted')}（GCP 综合排序分数 {row.get('rank_score'):.2f}）")
            feat_lines = [f"- {row['feature']}: {row['importance']:.4f}" for row in feature_highlights[:6]]
            btch_lines = [f"- {row['product']}: 平均权重 {row['weight']:.4f}" for row in btch_highlights.get("mean_weights", [])[:6]]
            report_parts = [
                common_header,
                "## 1. 研究目标与完成情况\n"
                "- 已完成多源土壤水分产品与站点观测的统一整理。\n"
                "- 已完成 BTCH、RF、XGBoost、LSTM 四类方法的实验接入与对比准备。\n"
                "- 已具备自动生成论文图表、阶段材料和结果摘要的能力。\n\n" ,
                "## 2. 核心结果摘要\n" ,
                ("\n".join(ranking_lines) if ranking_lines else "- 请指定点预测指标表后重新生成，以写入最终模型排序。") + "\n\n" ,
            ]
            if gcp_ranking_lines:
                report_parts.append("### 2.1 GCP 不确定性排序\n" + "\n".join(gcp_ranking_lines) + "\n\n")
            if metrics_md:
                report_parts.append("### 2.2 点预测精度表\n" + metrics_md + "\n\n")
            if gcp_metrics_md:
                report_parts.append("### 2.3 GCP 指标表\n" + gcp_metrics_md + "\n\n")
            if feat_lines:
                report_parts.append("### 2.4 主要驱动因子\n" + "\n".join(feat_lines) + "\n\n")
            if btch_lines:
                report_parts.append("### 2.5 BTCH 权重特征\n" + "\n".join(btch_lines) + "\n\n")
            if recent_pngs:
                report_parts.append("## 3. 建议用于答辩的图件\n" + "\n".join(f"- {p}" for p in recent_pngs[:8]) + "\n\n")
            if figure_notes:
                report_parts.append("## 4. 图注草稿摘录\n" + figure_notes + "\n\n")
            report_parts.append(
                "## 5. 研究创新与不足\n"
                "- 创新：统一同一流域尺度下比较统计融合、集成学习与时序深度学习方法。\n"
                "- 创新：将配准、建模、评价、出图和阶段材料整合为一体化流程。\n"
                "- 不足：仍受站点密度、时间交集与模型超参数稳定性影响。\n\n"
                "## 6. 结论表达建议\n"
                "- 先给出独立验证期点预测总体排序，再单独说明 GCP 区间可靠性与紧致性。\n"
                "- 对最优模型的优势和局限同时表述，避免仅以单一指标下结论。\n"
                "- 将 BTCH 权重、特征重要性、时序图与 GCP 指标组合呈现，提高可解释性。\n"
            )
            report = "".join(report_parts)
            outline = (
                "# 答辩汇报提纲（10-12 分钟）\n\n"
                "1. 研究背景与问题提出\n"
                "2. 数据来源与研究区\n"
                "3. 技术路线\n"
                "4. 四类模型构建思路\n"
                "5. 点预测结果与 GCP 不确定性对比\n"
                "6. 时间/空间维度分析\n"
                "7. 结论、创新与不足\n"
                "8. 展望\n\n"
                "## 3 分钟精简版\n"
                "- 研究问题\n- 数据与方法\n- 点预测最优结果\n- GCP 可靠性最优结果\n- 结论与意义\n"
            )
            qa = (
                "# 答辩问答库\n\n"
                "1. 为什么 BTCH 仍然有必要？\n- 因为它不依赖真值直接参与权重估计，适合在站点稀缺场景下提供统计基线。\n\n"
                "2. RF 和 XGBoost 的差别是什么？\n- RF 更稳健、解释简单；XGBoost 更强调 boosting 迭代，往往在非线性拟合上更强，但更依赖参数。\n\n"
                "3. LSTM 的优势和限制是什么？\n- 优势在于刻画记忆效应与时序依赖；限制在于样本长度、缺失模式和训练稳定性。\n\n"
                "4. 为什么采用 2019 训练、2020 验证？\n- 为避免随机混洗带来的信息泄露，更真实地检验跨年泛化能力。\n\n"
                "5. 如果老师质疑最优模型结论怎么办？\n- 回到点预测指标表与 GCP 指标表，分别说明准确性和可靠性，再解释为什么最终推荐该模型。\n"
            )

        report_path = _save_markdown_artifact(manager, f"{output_prefix}_{stage_key}_report", report)
        outline_path = _save_markdown_artifact(manager, f"{output_prefix}_{stage_key}_outline", outline)
        qa_path = _save_markdown_artifact(manager, f"{output_prefix}_{stage_key}_qa", qa)
        manifest = {
            "stage": stage_key,
            "topic": topic_text,
            "research_document": research_document,
            "metrics_dataset": metrics_dataset,
            "gcp_metrics_dataset": gcp_metrics_dataset,
            "feature_importance_dataset": feature_importance_dataset,
            "btch_weights_dataset": btch_weights_dataset,
            "figure_notes_document": figure_notes_document,
            "figure_notes_source": figure_notes_source,
            "recent_pngs": recent_pngs,
            "recent_docs": recent_docs,
            "outputs": {
                "report": str(report_path),
                "outline": str(outline_path),
                "qa": str(qa_path),
            },
        }
        manifest_path = _save_json_artifact(manager, f"{output_prefix}_{stage_key}_manifest", manifest)
        report_name = manager.put_text_document(f"{output_prefix}_{stage_key}_report_doc", report, filename=f"{_artifact_safe_name(output_prefix)}_{stage_key}_report.txt")
        outline_name = manager.put_text_document(f"{output_prefix}_{stage_key}_outline_doc", outline, filename=f"{_artifact_safe_name(output_prefix)}_{stage_key}_outline.txt")
        qa_name = manager.put_text_document(f"{output_prefix}_{stage_key}_qa_doc", qa, filename=f"{_artifact_safe_name(output_prefix)}_{stage_key}_qa.txt")
        manager.log_operation("阶段材料生成", f"{stage_key} -> {report_path.name}", "report")
        stage_label = stage_titles[stage_key]
        return (
            f"已生成 {stage_label} 材料包。报告: {report_path}（数据集 {report_name}）；"
            f"提纲: {outline_path}（数据集 {outline_name}）；问答库: {qa_path}（数据集 {qa_name}）；"
            f"清单: {manifest_path}"
        )


    return [
        preview_document,
        document_outline,
        search_document_text,
        generate_stage_report,
    ]
