from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm_planner_eval import evaluate_llm_planner_cases


DEFAULT_CASES = ROOT / "tests" / "fixtures" / "llm_planner_cases.jsonl"


def _markdown_report(result: dict) -> str:
    lines = [
        "# LLM Planner Evaluation",
        "",
        f"- Cases: {result.get('case_count', 0)}",
        f"- Passed: {result.get('passed', 0)}",
        f"- Failed: {result.get('failed', 0)}",
        f"- Accuracy: {float(result.get('accuracy') or 0.0):.4f}",
        "",
        "| Case | Status | Result | Errors |",
        "|---|---:|---:|---|",
    ]
    for row in result.get("cases", []):
        errors = row.get("errors") if isinstance(row.get("errors"), list) else []
        error_text = ", ".join(str(item.get("code") or "") for item in errors if isinstance(item, dict)) or "-"
        outcome = "pass" if row.get("passed") else "fail"
        lines.append(f"| {row.get('case_id')} | {row.get('status')} | {outcome} | {error_text} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate LLM-first GIS TaskPlan fixtures without executing tools.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to JSONL planner evaluation cases.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Report format.")
    parser.add_argument("--min-accuracy", type=float, default=0.0, help="Exit non-zero if accuracy is below this threshold.")
    parser.add_argument(
        "--use-real-llm",
        action="store_true",
        help="Use the configured LLM provider for shadow planning instead of fixture model_output. Tools are still never executed.",
    )
    args = parser.parse_args(argv)

    result = evaluate_llm_planner_cases(Path(args.cases), use_real_llm=args.use_real_llm)
    if args.format == "markdown":
        print(_markdown_report(result), end="")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    accuracy = float(result.get("accuracy") or 0.0)
    return 0 if accuracy >= float(args.min_accuracy) else 1


if __name__ == "__main__":
    raise SystemExit(main())
