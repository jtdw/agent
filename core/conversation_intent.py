from __future__ import annotations

import os
from typing import Any, Callable

from core.llm_intent_classifier import classify_intent_with_llm


INTENTS = {
    "data_upload_analysis",
    "data_processing",
    "map_generation",
    "modeling",
    "result_analysis",
    "follow_up_question",
    "troubleshooting",
    "data_download",
    "general_gis_question",
    "unclear_request",
}

HYBRID_CONFIDENCE_THRESHOLD = 0.75


def _contains_any(text: str, words: tuple[str, ...]) -> list[str]:
    return [word for word in words if word and word.lower() in text]


def _workspace_dataset_count(workspace_summary: Any) -> int:
    if isinstance(workspace_summary, dict):
        value = workspace_summary.get("dataset_count")
        if isinstance(value, int):
            return value
    return 0


def _state_has_recent_object(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    return bool(
        state.get("active_dataset")
        or state.get("active_artifacts")
        or state.get("last_map_path")
        or state.get("last_model_result")
        or state.get("last_error")
        or state.get("last_user_goal")
        or state.get("referenced_object")
    )


def _secondary_intents(prompt: str, primary: str) -> list[str]:
    text = str(prompt or "").lower()
    processing_hits = _contains_any(
        text,
        (
            "处理",
            "清洗",
            "裁剪",
            "clip",
            "study area",
            "叠加",
            "提取",
            "转换",
            "瑁佸壀",
            "鍙犲姞",
            "鎻愬彇",
            "娓呮礂",
        ),
    )
    map_hits = _contains_any(
        text,
        ("制图", "画图", "画", "图", "地图", "分布图", "专题图", "可视化", "出一张图", "鍒跺浘", "鐢诲浘", "鍦板浘", "鍥"),
    )
    result_hits = _contains_any(text, ("解释", "说明", "解读", "含义", "怎么看", "瑙ｉ噴", "璇存槑", "鎬庝箞鐪"))
    modeling_hits = _contains_any(text, ("建模", "模型", "预测", "训练", "寤烘ā", "妯", "棰勬祴", "璁粌"))

    ordered: list[str] = []
    if processing_hits:
        ordered.append("data_processing")
    if map_hits:
        ordered.append("map_generation")
    if modeling_hits:
        ordered.append("modeling")
    if result_hits:
        ordered.append("result_analysis")
    return [intent for intent in ordered if intent != primary]


def _normalize_result(result: dict[str, Any], *, classifier: str, fallback_reason: str | None = None) -> dict[str, Any]:
    intent = str(result.get("intent") or "unclear_request")
    if intent not in INTENTS:
        intent = "unclear_request"
    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    keywords = result.get("keywords")
    if not isinstance(keywords, list):
        keywords = []

    missing_inputs = result.get("missing_inputs")
    if not isinstance(missing_inputs, list):
        missing_inputs = []

    secondary = result.get("secondary_intents")
    if not isinstance(secondary, list):
        secondary = []
    secondary_intents = [item for item in secondary if item in INTENTS and item != intent]

    normalized = {
        "intent": intent,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": str(result.get("reason") or result.get("reasoning_summary") or ""),
        "needs_followup_resolution": bool(result.get("needs_followup_resolution", False)),
        "keywords": [str(item) for item in keywords],
        "classifier": classifier,
        "referenced_object": result.get("referenced_object") if isinstance(result.get("referenced_object"), dict) else None,
        "missing_inputs": [str(item) for item in missing_inputs if item],
        "reasoning_summary": str(result.get("reasoning_summary") or result.get("reason") or ""),
        "should_ask_clarification": bool(result.get("should_ask_clarification", False)),
        "secondary_intents": secondary_intents,
    }
    if fallback_reason:
        normalized["fallback_reason"] = fallback_reason
    return normalized


def _truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def classify_user_intent_rule_based(prompt: str, conversation_state: Any, workspace_summary: Any) -> dict[str, Any]:
    """Deterministic GIS intent classifier used as high-confidence path and fallback."""
    text = str(prompt or "").strip()
    lower = text.lower()
    state = conversation_state if isinstance(conversation_state, dict) else {}
    dataset_count = _workspace_dataset_count(workspace_summary)

    if not text:
        return _normalize_result(
            {
                "intent": "unclear_request",
                "confidence": 0.2,
                "reason": "empty_prompt",
                "needs_followup_resolution": False,
                "keywords": [],
            },
            classifier="rule",
        )

    data_check_tokens = (
        "\u68c0\u67e5\u5f53\u524d\u4e0a\u4f20\u6570\u636e",
        "\u68c0\u67e5\u6570\u636e",
        "\u6570\u636e\u80fd\u505a\u4ec0\u4e48",
        "\u80fd\u505a\u4ec0\u4e48",
        "\u5b57\u6bb5",
        "\u5750\u6807",
        "\u7f3a\u5931\u503c",
    )
    data_check_hits = _contains_any(lower, data_check_tokens)
    if data_check_hits and (dataset_count > 0 or state.get("active_dataset")):
        return _normalize_result(
            {
                "intent": "data_upload_analysis",
                "confidence": 0.8,
                "reason": "matched_data_check_keywords",
                "needs_followup_resolution": False,
                "keywords": data_check_hits,
                "secondary_intents": _secondary_intents(text, "data_upload_analysis"),
            },
            classifier="rule",
        )

    troubleshooting_hits = _contains_any(
        lower,
        (
            "报错",
            "错误",
            "失败",
            "为什么失败",
            "不能",
            "无法",
            "异常",
            "traceback",
            "error",
            "failed",
            "鎶ラ敊",
            "閿欒",
            "澶辫触",
            "寮傚父",
        ),
    )
    if troubleshooting_hits:
        return _normalize_result(
            {
                "intent": "troubleshooting",
                "confidence": 0.86,
                "reason": "matched_troubleshooting_keywords",
                "needs_followup_resolution": True,
                "keywords": troubleshooting_hits,
            },
            classifier="rule",
        )

    followup_hits = _contains_any(
        lower,
        (
            "这个",
            "这张",
            "刚才",
            "继续",
            "下一步",
            "为什么",
            "怎么看",
            "说明什么",
            "改进一下",
            "再做",
            "它",
            "杩欎釜",
            "鍒氭墠",
            "缁х画",
            "涓嬩竴姝",
            "璇存槑",
            "鎬庝箞鐪",
        ),
    )
    if followup_hits and _state_has_recent_object(state):
        weak_complex_request = "整理" in text or "综合" in text
        processing_request = any(word in text for word in ("\u88c1\u526a", "\u5904\u7406", "\u53e0\u52a0", "\u63d0\u53d6", "\u8f6c\u6362", "clip", "overlay"))
        map_request = any(word in text for word in ("制图", "画图", "画", "出一张图", "鍒跺浘", "鐢诲浘", "鐢"))
        if weak_complex_request:
            return _normalize_result(
                {
                    "intent": "unclear_request",
                    "confidence": 0.5,
                    "reason": "weak_complex_followup_expression",
                    "needs_followup_resolution": True,
                    "keywords": followup_hits,
                    "secondary_intents": _secondary_intents(text, "unclear_request"),
                },
                classifier="rule",
            )
        if processing_request:
            intent = "data_processing"
        elif ("上传" in text or "涓婁紶" in text) and ("数据" in text or "鏁版嵁" in text):
            intent = "data_upload_analysis"
        elif ("数据" in text or "鏁版嵁" in text) and ("能做什么" in text or "鑳藉仛" in text):
            intent = "data_upload_analysis"
        elif any(word in text for word in ("图", "地图", "制图", "分布", "鍥", "鍦板浘", "鍒跺浘")):
            intent = "map_generation" if map_request else "follow_up_question"
        elif any(word in text for word in ("结果", "指标", "模型", "缁撴灉", "鎸囨爣", "妯")):
            intent = "result_analysis"
        elif "下一步" in text or "继续" in text or "涓嬩竴姝" in text or "缁х画" in text:
            intent = "follow_up_question"
        else:
            intent = "follow_up_question"
        return _normalize_result(
            {
                "intent": intent,
                "confidence": 0.82,
                "reason": "matched_followup_reference",
                "needs_followup_resolution": True,
                "keywords": followup_hits,
                "secondary_intents": _secondary_intents(text, intent),
            },
            classifier="rule",
        )

    download_hits = _contains_any(
        lower,
        (
            "下载",
            "获取",
            "dem",
            "sentinel",
            "landsat",
            "modis",
            "降水",
            "降雨",
            "行政区",
            "边界",
            "遥感",
            "涓嬭浇",
            "鑾峰彇",
            "闄嶆按",
            "琛屾斂鍖",
            "杈圭晫",
            "閬ユ劅",
        ),
    )
    if download_hits:
        return _normalize_result(
            {
                "intent": "data_download",
                "confidence": 0.84,
                "reason": "matched_download_keywords",
                "needs_followup_resolution": bool(followup_hits),
                "keywords": download_hits,
                "secondary_intents": _secondary_intents(text, "data_download"),
            },
            classifier="rule",
        )

    modeling_hits = _contains_any(
        lower,
        (
            "建模",
            "模型",
            "预测",
            "机器学习",
            "随机森林",
            "xgboost",
            "rf",
            "lstm",
            "btch",
            "gcp",
            "融合",
            "训练",
            "回归",
            "寤烘ā",
            "妯",
            "棰勬祴",
            "闅忔満",
            "璁粌",
        ),
    )
    if modeling_hits:
        return _normalize_result(
            {
                "intent": "modeling",
                "confidence": 0.86,
                "reason": "matched_modeling_keywords",
                "needs_followup_resolution": bool(followup_hits),
                "keywords": modeling_hits,
                "secondary_intents": _secondary_intents(text, "modeling"),
            },
            classifier="rule",
        )

    processing_hits = _contains_any(
        lower,
        (
            "处理",
            "清洗",
            "转换",
            "裁剪",
            "clip",
            "clip layer",
            "study area",
            "叠加",
            "提取",
            "缓冲",
            "相交",
            "空间连接",
            "重投影",
            "转点",
            "缺失值",
            "字段检查",
            "娓呮礂",
            "杞崲",
            "瑁佸壀",
            "鍙犲姞",
            "鎻愬彇",
            "缂撳啿",
            "鐩镐氦",
            "閲嶆姇",
        ),
    )
    if processing_hits:
        return _normalize_result(
            {
                "intent": "data_processing",
                "confidence": 0.82,
                "reason": "matched_processing_keywords",
                "needs_followup_resolution": bool(followup_hits),
                "keywords": processing_hits,
                "secondary_intents": _secondary_intents(text, "data_processing"),
            },
            classifier="rule",
        )

    map_hits = _contains_any(
        lower,
        (
            "制图",
            "画图",
            "地图",
            "分布图",
            "可视化",
            "图件",
            "专题图",
            "渲染",
            "人口密度图",
            "map",
            "plot",
            "鍒跺浘",
            "鐢诲浘",
            "鍦板浘",
            "鍥句欢",
            "涓撻鍥",
            "鍙",
            "鐢",
            "鍥",
        ),
    )
    if map_hits:
        return _normalize_result(
            {
                "intent": "map_generation",
                "confidence": 0.84,
                "reason": "matched_map_keywords",
                "needs_followup_resolution": bool(followup_hits),
                "keywords": map_hits,
                "secondary_intents": _secondary_intents(text, "map_generation"),
            },
            classifier="rule",
        )

    result_hits = _contains_any(
        lower,
        (
            "结果",
            "指标",
            "解释",
            "解读",
            "含义",
            "说明什么",
            "评价",
            "精度",
            "残差",
            "缁撴灉",
            "鎸囨爣",
            "瑙ｉ噴",
            "璇存槑",
            "璇勪环",
            "娈嬪樊",
        ),
    )
    if result_hits:
        return _normalize_result(
            {
                "intent": "result_analysis",
                "confidence": 0.78,
                "reason": "matched_result_keywords",
                "needs_followup_resolution": True,
                "keywords": result_hits,
                "secondary_intents": _secondary_intents(text, "result_analysis"),
            },
            classifier="rule",
        )

    upload_hits = _contains_any(
        lower,
        (
            "上传",
            "刚上传",
            "数据能做什么",
            "能做什么",
            "检查数据",
            "检查当前上传数据",
            "字段",
            "坐标",
            "缺失值",
            "理解数据",
            "工作区",
            "check this dataset",
            "check dataset",
            "inspect this dataset",
            "inspect dataset",
            "describe this dataset",
            "describe dataset",
            "what can this data do",
            "what can this dataset do",
            "涓婁紶",
            "鍒氫笂浼",
            "鏁版嵁鑳藉仛",
            "鑳藉仛",
            "妫€鏌ユ暟鎹",
        ),
    )
    if upload_hits and (dataset_count > 0 or state.get("active_dataset")):
        return _normalize_result(
            {
                "intent": "data_upload_analysis",
                "confidence": 0.78,
                "reason": "matched_upload_analysis_keywords",
                "needs_followup_resolution": bool(followup_hits),
                "keywords": upload_hits,
                "secondary_intents": _secondary_intents(text, "data_upload_analysis"),
            },
            classifier="rule",
        )

    general_hits = _contains_any(
        lower,
        (
            "什么是",
            "如何",
            "原理",
            "区别",
            "解释一下",
            "gis",
            "遥感",
            "空间分析",
            "浠€涔堟槸",
            "濡備綍",
            "鍘熺悊",
            "鍖哄埆",
            "閬ユ劅",
            "绌洪棿鍒嗘瀽",
        ),
    )
    if general_hits:
        return _normalize_result(
            {
                "intent": "general_gis_question",
                "confidence": 0.62,
                "reason": "matched_general_gis_keywords",
                "needs_followup_resolution": False,
                "keywords": general_hits,
                "secondary_intents": _secondary_intents(text, "general_gis_question"),
            },
            classifier="rule",
        )

    return _normalize_result(
        {
            "intent": "unclear_request",
            "confidence": 0.35,
            "reason": "no_rule_matched",
            "needs_followup_resolution": bool(followup_hits),
            "keywords": followup_hits,
            "secondary_intents": _secondary_intents(text, "unclear_request"),
        },
        classifier="rule",
    )


def classify_user_intent(
    prompt: str,
    conversation_state: Any,
    workspace_summary: Any,
    *,
    llm_classifier: Callable[[str, Any, Any], dict[str, Any]] | None = None,
    enable_llm: bool | None = None,
) -> dict[str, Any]:
    """Hybrid intent classifier with deterministic fallback.

    Rule-based classification is always executed first. High-confidence rule
    results are returned directly. Low-confidence or vague prompts may use the
    optional LLM classifier, but the rule result remains the fallback path.
    """
    rule_result = classify_user_intent_rule_based(prompt, conversation_state, workspace_summary)
    if float(rule_result.get("confidence", 0.0)) >= HYBRID_CONFIDENCE_THRESHOLD:
        return rule_result

    llm_allowed = enable_llm
    if llm_allowed is None:
        llm_allowed = bool(llm_classifier) or _truthy_env(os.getenv("GIS_AGENT_ENABLE_LLM_INTENT"))
    if not llm_allowed:
        rule_result["fallback_reason"] = "llm_disabled"
        return rule_result

    if llm_classifier is None:
        llm_result = classify_intent_with_llm(prompt, conversation_state, workspace_summary)
    else:
        try:
            llm_result = llm_classifier(prompt, conversation_state, workspace_summary)
        except Exception:
            llm_result = {"available": False, "fallback_reason": "llm_call_failed"}

    if not isinstance(llm_result, dict) or not llm_result.get("available"):
        rule_result["fallback_reason"] = str((llm_result or {}).get("fallback_reason") or "llm_unavailable")
        return rule_result

    merged = _normalize_result(
        {
            "intent": llm_result.get("intent"),
            "confidence": llm_result.get("confidence"),
            "reason": llm_result.get("reasoning_summary") or "llm_intent_classifier",
            "needs_followup_resolution": rule_result.get("needs_followup_resolution")
            or llm_result.get("intent") == "follow_up_question",
            "keywords": rule_result.get("keywords", []),
            "referenced_object": llm_result.get("referenced_object"),
            "missing_inputs": llm_result.get("missing_inputs"),
            "reasoning_summary": llm_result.get("reasoning_summary"),
            "should_ask_clarification": llm_result.get("should_ask_clarification"),
            "secondary_intents": llm_result.get("secondary_intents") or rule_result.get("secondary_intents"),
        },
        classifier="llm",
    )
    merged["rule_intent"] = rule_result.get("intent")
    merged["rule_confidence"] = rule_result.get("confidence")
    return merged
