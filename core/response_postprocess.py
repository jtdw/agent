from __future__ import annotations

import re
from typing import Iterable


RESULT_SECTION_PREFIXES = (
    "已完成操作",
    "使用的数据",
    "使用数据",
    "关键结果",
    "输出文件",
    "处理后的数据位置",
    "最新模型结果",
    "结果含义",
    "含义与风险",
    "可能问题",
    "下一步建议",
    "任务结果分析",
    "结果位置",
    "推荐下一步",
)


MOJIBAKE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\u5bb8\u63d2\u756c\u93b4\u612d\u6437\u6d63?", "已完成操作"),
    ("\u6d63\u8de8\u6564\u9428\u52ec\u669f\u93b9?", "使用的数据"),
    ("\u934f\u62bd\u656d\u7f01\u64b4\u7049", "关键结果"),
    ("\u6748\u64b3\u56ad\u93c2\u56e6\u6b22", "输出文件"),
    ("\u6fb6\u52ed\u608a\u935a\u5ea3\u6b91\u93c1\u7248\u5d41\u6d63\u5d87\u7586", "处理后的数据位置"),
    ("\u93c8\u20ac\u93c2\u7248\u0101\u9368\u5b2c\u7ca8\u93cb?", "最新模型结果"),
    ("\u7f01\u64b4\u7049\u935a\ue0a1\u7b9f", "结果含义"),
    ("\u9359\ue21d\u5158\u95c2\ue1c0\ue57d", "可能问题"),
    ("\u6d93\u5b29\u7af4\u59dd\u30e5\u7f13\u7481?", "下一步建议"),
    ("\u6d60\u8bf2\u59df\u7f01\u64b4\u7049\u9352\u55d8\u703d", "任务结果分析"),
    ("\u9427\u8bf2\u7d8d", "登录"),
    ("\u6d93\u5b2d\u6d47", "下载"),
    ("\u7035\u714e\u56ad", "导出"),
    ("\u59ab\u20ac\u93cc", "检查"),
    ("\u947e\u5cf0\u5f47", "获取"),
    ("\u9351\u55d7\ue62c", "准备"),
)


def repair_mojibake_text(text: str) -> str:
    repaired = str(text or "")
    for old, new in MOJIBAKE_REPLACEMENTS:
        repaired = repaired.replace(old, new)
    return repaired


def contains_mojibake(text: str, extra_tokens: Iterable[str] = ()) -> bool:
    tokens = [old for old, _ in MOJIBAKE_REPLACEMENTS]
    tokens.extend(str(token) for token in extra_tokens)
    return any(token and token in str(text or "") for token in tokens)


def _line_key(line: str) -> str:
    clean = re.sub(r"\s+", " ", line.strip())
    clean = clean.replace("：", ":").replace("；", ";")
    return clean


def _section_prefix(line: str) -> str:
    stripped = line.strip()
    normalized = stripped.rstrip(":：").strip()
    for prefix in RESULT_SECTION_PREFIXES:
        if normalized == prefix:
            return prefix
    return ""


def dedupe_assistant_reply(text: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw

    seen_lines: set[str] = set()
    seen_sections: set[str] = set()
    output: list[str] = []
    skipping_duplicate_section = False

    for line in raw.splitlines():
        stripped = line.strip()
        section = _section_prefix(stripped)
        if section and section in seen_sections:
            skipping_duplicate_section = True
            continue
        if section:
            seen_sections.add(section)
            skipping_duplicate_section = False
        elif skipping_duplicate_section and (not stripped or stripped.startswith(("- ", "* ", "• "))):
            continue
        elif stripped:
            skipping_duplicate_section = False

        key = _line_key(line)
        if key and key in seen_lines:
            continue
        if key:
            seen_lines.add(key)
        output.append(line.rstrip())

    return "\n".join(output).strip()


def clean_assistant_reply(text: str) -> str:
    return dedupe_assistant_reply(repair_mojibake_text(str(text or "")))
