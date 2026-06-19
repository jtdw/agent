from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm_planner_observability import summarize_shadow_planner_messages


def _markdown(result: dict) -> str:
    lines = [
        "# LLM Planner Shadow Summary",
        "",
        f"- Database: {result.get('database')}",
        f"- Exists: {result.get('exists')}",
        f"- Assistant shadow messages: {result.get('assistant_shadow_message_count', 0)}",
        "",
        "## Status Counts",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for status, count in (result.get("status_counts") or {}).items():
        lines.append(f"| {status} | {count} |")
    lines.extend(["", "## Error Code Counts", "", "| Error Code | Count |", "|---|---:|"])
    for code, count in (result.get("error_code_counts") or {}).items():
        lines.append(f"| {code} | {count} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize recorded LLM planner shadow results from workspace.db.")
    parser.add_argument("--workdir", default=str(ROOT / "workspace"), help="Workspace directory containing workspace.db.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Report format.")
    args = parser.parse_args(argv)

    result = summarize_shadow_planner_messages(Path(args.workdir) / "workspace.db")
    if args.format == "markdown":
        print(_markdown(result), end="")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
