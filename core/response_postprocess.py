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
    ("宸插畬鎴愭搷浣?", "已完成操作"),
    ("浣跨敤鐨勬暟鎹?", "使用的数据"),
    ("鍏抽敭缁撴灉", "关键结果"),
    ("杈撳嚭鏂囦欢", "输出文件"),
    ("澶勭悊鍚庣殑鏁版嵁浣嶇疆", "处理后的数据位置"),
    ("鏈€鏂版ā鍨嬬粨鏋?", "最新模型结果"),
    ("缁撴灉鍚箟", "结果含义"),
    ("鍙兘闂", "可能问题"),
    ("涓嬩竴姝ュ缓璁?", "下一步建议"),
    ("浠诲姟缁撴灉鍒嗘瀽", "任务结果分析"),
    ("鐧诲綍", "登录"),
    ("涓嬭浇", "下载"),
    ("瀵煎嚭", "导出"),
    ("妫€鏌", "检查"),
    ("鑾峰彇", "获取"),
    ("鍑嗗", "准备"),
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
