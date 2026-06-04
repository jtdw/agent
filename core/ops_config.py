from __future__ import annotations

import os
from typing import Any


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def validate_production_config() -> dict[str, Any]:
    env_name = os.getenv("GIS_AGENT_ENV", os.getenv("ENV", "development")).strip().lower()
    production = env_name in {"prod", "production"}
    missing: list[str] = []
    warnings: list[str] = []
    if production:
        if not os.getenv("APP_SECRET_KEY", "").strip():
            missing.append("APP_SECRET_KEY")
        if not os.getenv("GIS_AGENT_ADMIN_TOKEN", "").strip():
            missing.append("GIS_AGENT_ADMIN_TOKEN")
        if not _truthy_env("GIS_AGENT_COOKIE_SECURE"):
            missing.append("GIS_AGENT_COOKIE_SECURE=1")
        if _truthy_env("GIS_AGENT_ENABLE_MOCK_PAYMENT"):
            warnings.append("GIS_AGENT_ENABLE_MOCK_PAYMENT should stay disabled in production")
    return {
        "ok": not missing,
        "environment": env_name or "development",
        "production": production,
        "missing": missing,
        "warnings": warnings,
    }


def require_valid_production_config() -> dict[str, Any]:
    result = validate_production_config()
    if not result["ok"]:
        raise RuntimeError("Invalid production configuration: " + ", ".join(result["missing"]))
    return result
