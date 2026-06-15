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


def _line_key(line: str) -> str:
    clean = re.sub(r"\s+", " ", line.strip())
    clean = clean.replace("；", ";")
    return clean


def dedupe_assistant_reply(text: str) -> str:
    """Remove repeated high-level result sections without rewriting content."""

    raw = str(text or "")
    if not raw.strip():
        return raw
    seen_lines: set[str] = set()
    seen_sections: set[str] = set()
    output: list[str] = []
    skipping_duplicate_section = False

    for line in raw.splitlines():
        stripped = line.strip()
        section = next((prefix for prefix in RESULT_SECTION_PREFIXES if stripped.startswith(f"{prefix}：") or stripped == f"{prefix}："), "")
        if section and section in seen_sections:
            skipping_duplicate_section = True
            continue
        if section:
            seen_sections.add(section)
            skipping_duplicate_section = False
        elif skipping_duplicate_section and (stripped.startswith("- ") or stripped.startswith("•") or not stripped):
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


MOJIBAKE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\u7279\u5f81\u91cd\u8981\u6027/\u9417\u7470\u7ddb\u95b2\u5d88\ue6e6\u93ac?\uff1a", "特征重要性："),
    ("\u6b8b\u5dee\u7a7a\u95f4\u5206\u5e03/\u5a08\u5b2a\u6a0a\u7ecc\u6d2a\u68ff\u9352\u55d7\u7af7\uff1a", "残差空间分布："),
    ("\u5bb8\u63d2\u756c\u93b4\u612d\u6437\u6d63", "已完成操作"),
    ("\u6d63\u8de8\u6564\u9428\u52ec\u669f\u93b9", "使用的数据"),
    ("\u934f\u62bd\u656d\u7f01\u64b4\u7049", "关键结果"),
    ("\u6748\u64b3\u56ad\u93c2\u56e6\u6b22", "输出文件"),
    ("\u6fb6\u52ed\u608a\u935a\u5ea3\u6b91\u93c1\u7248\u5d41\u6d63\u5d87\u7586", "处理后的数据位置"),
    ("\u93c8\u20ac\u93c2\u7248\u0101\u9368\u5b2c\u7ca8\u93cb", "最新模型结果"),
    ("\u7f01\u64b4\u7049\u935a\ue0a1\u7b9f", "结果含义"),
    ("\u9359\ue21d\u5158\u95c2\ue1c0\ue57d", "可能问题"),
    ("\u6d93\u5b29\u7af4\u59dd\u30e5\u7f13\u7481", "下一步建议"),
    ("\u5bb8\u63d2\ue632\u9352?", "已复制"),
    ("\u6fb6\u5d85\u57d7\u6d60\uff47\u721c", "复制代码"),
    ("\u6fb6\u5d85\u57d7\u95ab\u5909\u8151\u93c2\u56e8\u6e70", "复制选中文本"),
    ("\u6d93\u5a41\u7d36", "上传"),
    ("\u6d93\u5b2d\u6d47", "下载"),
    ("\u7035\u714e\u56ad", "导出"),
    ("\u59ab\u20ac\u93cc\u30e6\u669f\u93b9", "检查数据"),
    ("\u59ab\u20ac\u7ef1?", "检索"),
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
    tokens.extend(extra_tokens)
    return any(token and token in str(text or "") for token in tokens)
