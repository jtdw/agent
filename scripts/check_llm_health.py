from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.config  # noqa: F401  # Load project .env before validating provider settings.
from core.llm_config import check_llm_provider_health


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check GIS Agent LLM provider configuration and optional provider connectivity.")
    parser.add_argument("--network", action="store_true", help="Run a real provider request. Default only validates local config.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless the provider is fully configured and healthy. Useful for deployment gates.",
    )
    args = parser.parse_args(argv)
    result = check_llm_provider_health(skip_network=not args.network)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.strict:
        return 0 if result.get("ok") and result.get("status") == "ok" else 1
    return 0 if result.get("status") in {"ok", "degraded"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
