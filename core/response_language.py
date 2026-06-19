from __future__ import annotations

from typing import Any


ZH_CN = "zh-CN"
EN_US = "en-US"


def detect_response_language(text: Any) -> str:
    value = str(text or "")
    cjk_count = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    ascii_alpha_count = sum(1 for char in value if ("a" <= char.lower() <= "z"))
    if cjk_count > 0 and cjk_count >= max(1, ascii_alpha_count // 3):
        return ZH_CN
    return EN_US


def normalize_response_language(value: Any, fallback_text: Any = "") -> str:
    raw = str(value or "").strip()
    if raw.lower() in {"zh", "zh-cn", "zh_cn", "cn", "chinese", "中文"}:
        return ZH_CN
    if raw.lower() in {"en", "en-us", "en_us", "english"}:
        return EN_US
    return detect_response_language(fallback_text)


def is_chinese_language(value: Any) -> bool:
    return normalize_response_language(value).startswith("zh")


def localized_text(key: str, language: str) -> str:
    zh = is_chinese_language(language)
    messages = {
        "planner_unavailable": (
            "当前无法调用 LLM Planner 生成可靠计划，因此没有执行任何工具。请补充任务范围、数据来源或稍后重试。",
            "LLM planner is unavailable, so no tool execution was started.",
        ),
        "planner_error": (
            "LLM Planner 在生成可验证计划前失败，因此没有执行任何工具。请补充任务信息或稍后重试。",
            "LLM planner failed before producing a validated plan.",
        ),
        "invalid_llm_output": (
            "LLM Planner 没有返回结构化计划，因此没有执行任何工具。请重新描述任务或稍后重试。",
            "LLM planner did not return structured JSON.",
        ),
        "invalid_llm_plan": (
            "LLM Planner 返回的计划未通过校验，因此没有执行任何工具。请补充或确认关键输入。",
            "LLM planner returned an invalid plan.",
        ),
        "low_confidence": (
            "请进一步确认任务目标、输入数据、范围和输出要求；在计划置信度不足时不会执行工具。",
            "Please clarify the task before any tool execution.",
        ),
        "generic_no_plan": (
            "当前无法由 LLM Planner 生成可验证执行规划，因此没有执行任何工具。",
            "LLM planner did not produce a validated execution plan; no tools were run.",
        ),
        "execution_stopped": (
            "执行在生成成功结果前停止。",
            "Execution stopped before a successful result was produced.",
        ),
        "task_result_ready": (
            "任务结果已生成。",
            "Task result is ready.",
        ),
    }
    pair = messages.get(key, ("", ""))
    return pair[0] if zh else pair[1]


def looks_english_user_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    ascii_alpha_count = sum(1 for char in text if ("a" <= char.lower() <= "z"))
    return cjk_count == 0 and ascii_alpha_count >= 6


def enforce_user_text_language(value: Any, language: str, fallback_key: str = "generic_no_plan") -> str:
    text = str(value or "").strip()
    if is_chinese_language(language) and looks_english_user_text(text):
        return localized_text(fallback_key, language)
    return text
