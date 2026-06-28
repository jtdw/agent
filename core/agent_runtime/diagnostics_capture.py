from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .decision_eval import capture_runtime_decision_eval_output


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _write_json(path_value: str | Path, payload: dict[str, Any]) -> str:
    path = Path(path_value).resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path.name


def _operations() -> dict[str, Any]:
    return {
        "llm_calls_performed": 0,
        "tool_calls_performed": 0,
        "live_execution": False,
    }


def capture_service_runtime_diagnostics(
    service: Any,
    *,
    diagnostics_output: str | Path,
    case_id: str = "",
    eval_outputs_output: str | Path | None = None,
) -> dict[str, Any]:
    diagnostics_fn = getattr(service, "agent_runtime_diagnostics", None)
    if not callable(diagnostics_fn):
        diagnostics = {"available": False}
    else:
        diagnostics = _as_dict(diagnostics_fn())
    diagnostics_filename = _write_json(diagnostics_output, diagnostics)

    payload: dict[str, Any] = {
        "ok": True,
        "command": "service",
        "schema_version": "agent-runtime-diagnostics-capture/v1",
        "diagnostics_filename": diagnostics_filename,
        "diagnostics_available": bool(diagnostics.get("available")),
        "operations": _operations(),
    }
    if case_id and eval_outputs_output is not None:
        outputs = capture_runtime_decision_eval_output(case_id, diagnostics)
        payload["eval_outputs_filename"] = _write_json(eval_outputs_output, outputs)
        payload["case_ids"] = sorted(outputs.keys())
    return payload


def _default_service_factory() -> Any:
    from core.service import GISWorkspaceService

    return GISWorkspaceService()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core.agent_runtime.diagnostics_capture")
    subcommands = parser.add_subparsers(dest="command", required=True)

    service = subcommands.add_parser("service", help="Capture GISWorkspaceService runtime diagnostics to JSON files.")
    service.add_argument("--diagnostics-output", required=True, help="UTF-8 JSON output path for service diagnostics.")
    service.add_argument("--case-id", default="", help="Optional eval case id used to emit report-ready outputs.")
    service.add_argument("--eval-outputs-output", default="", help="Optional UTF-8 JSON output path for report-ready outputs.")

    return parser


def run_diagnostics_capture_cli(
    argv: list[str] | tuple[str, ...],
    *,
    service_factory: Callable[[], Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    args = _parser().parse_args(list(argv))
    if args.command == "service":
        factory = service_factory or _default_service_factory
        payload = capture_service_runtime_diagnostics(
            factory(),
            diagnostics_output=args.diagnostics_output,
            case_id=str(args.case_id or ""),
            eval_outputs_output=str(args.eval_outputs_output or "") or None,
        )
        return 0, payload
    return 2, {"ok": False, "command": str(args.command or ""), "error_code": "UNKNOWN_COMMAND"}


def main(argv: list[str] | None = None) -> int:
    code, payload = run_diagnostics_capture_cli(sys.argv[1:] if argv is None else argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
