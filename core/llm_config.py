from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping
from urllib.parse import urlparse


SUPPORTED_PROVIDERS = {"zai", "openai", "fake"}
DEFAULT_ZAI_BASE_URL = "https://api.z.ai/api/paas/v4/"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def _env(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float, env: Mapping[str, str]) -> float:
    raw = str(env.get(name, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int, env: Mapping[str, str]) -> int:
    raw = str(env.get(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _first_present(env: Mapping[str, str], names: list[str], default: str = "") -> str:
    for name in names:
        if name in env:
            return str(env.get(name) or "").strip()
    return default


@dataclass(slots=True)
class LLMProviderConfig:
    provider: str
    model: str
    api_key_env: str
    api_key_present: bool
    base_url: str
    timeout: float
    temperature: float
    max_retries: int
    enable_llm_intent_classifier: bool
    fallback_to_rule_classifier: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_llm_provider_config(env: Mapping[str, str] | None = None) -> LLMProviderConfig:
    source = _env(env)
    provider = str(source.get("LLM_PROVIDER") or "").strip().lower()
    if not provider:
        provider = "zai"

    if provider == "openai":
        api_key_env = str(source.get("LLM_API_KEY_ENV") or "OPENAI_API_KEY").strip()
        default_base_url = DEFAULT_OPENAI_BASE_URL
        default_model = "gpt-4o-mini"
    elif provider == "fake":
        api_key_env = str(source.get("LLM_API_KEY_ENV") or "").strip()
        default_base_url = ""
        default_model = "fake-gis"
    else:
        api_key_env = str(source.get("LLM_API_KEY_ENV") or "ZAI_API_KEY").strip()
        default_base_url = DEFAULT_ZAI_BASE_URL
        default_model = "glm-4.5-air"

    model = _first_present(source, ["LLM_MODEL"], default="")
    if not model:
        if "LLM_MODEL" in source:
            model = ""
        elif provider == "zai":
            model = str(source.get("ZAI_MODEL") or default_model).strip()
        else:
            model = default_model

    base_url = _first_present(source, ["LLM_BASE_URL"], default="")
    if not base_url:
        if "LLM_BASE_URL" in source:
            base_url = ""
        elif provider == "zai":
            base_url = str(source.get("ZAI_BASE_URL") or default_base_url).strip()
        else:
            base_url = default_base_url

    enable_intent = _truthy(source.get("ENABLE_LLM_INTENT_CLASSIFIER") or source.get("GIS_AGENT_ENABLE_LLM_INTENT"))
    fallback = _truthy(source.get("FALLBACK_TO_RULE_CLASSIFIER", "1"))
    timeout = _float_env("LLM_TIMEOUT", 60.0, source)
    max_retries = _int_env("LLM_MAX_RETRIES", 2, source)
    temperature = _float_env("LLM_TEMPERATURE", _float_env("GIS_AGENT_TEMPERATURE", 0.1, source), source)
    api_key = str(source.get(api_key_env) or "").strip() if api_key_env else ""
    return LLMProviderConfig(
        provider=provider,
        model=model,
        api_key_env=api_key_env,
        api_key_present=bool(api_key) or provider == "fake",
        base_url=base_url,
        timeout=timeout,
        temperature=temperature,
        max_retries=max_retries,
        enable_llm_intent_classifier=enable_intent,
        fallback_to_rule_classifier=fallback,
    )


def _error(code: str, message: str, **detail: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **detail}


def _valid_url(value: str) -> bool:
    if not value:
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_llm_config(config: LLMProviderConfig | None = None) -> dict[str, Any]:
    cfg = config or load_llm_provider_config()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if cfg.provider not in SUPPORTED_PROVIDERS:
        errors.append(_error("UNSUPPORTED_PROVIDER", f"Unsupported LLM provider: {cfg.provider}", supported=sorted(SUPPORTED_PROVIDERS)))
    if not cfg.model:
        errors.append(_error("MODEL_REQUIRED", "LLM model is required. Set LLM_MODEL or provider-specific model env."))
    if cfg.base_url and not _valid_url(cfg.base_url):
        errors.append(_error("BASE_URL_INVALID", "LLM_BASE_URL must be an http(s) URL."))
    if cfg.timeout <= 0 or cfg.timeout > 600:
        errors.append(_error("TIMEOUT_INVALID", "LLM_TIMEOUT must be between 0 and 600 seconds."))
    if cfg.max_retries < 0 or cfg.max_retries > 10:
        errors.append(_error("MAX_RETRIES_INVALID", "LLM_MAX_RETRIES must be between 0 and 10."))

    if cfg.provider != "fake" and not cfg.api_key_present:
        message = f"Missing API key. Set {cfg.api_key_env or 'LLM_API_KEY_ENV'}."
        if cfg.fallback_to_rule_classifier:
            errors.append(_error("API_KEY_MISSING", message, non_blocking=True))
        else:
            errors.append(_error("API_KEY_MISSING", message))

    blocking_errors = [error for error in errors if not error.get("non_blocking")]
    status = "invalid" if blocking_errors else ("degraded" if errors or warnings else "ok")
    return {
        "status": status,
        "provider": cfg.provider,
        "model": cfg.model,
        "api_key_env": cfg.api_key_env,
        "api_key_present": cfg.api_key_present,
        "base_url": cfg.base_url,
        "timeout": cfg.timeout,
        "temperature": cfg.temperature,
        "max_retries": cfg.max_retries,
        "enable_llm_intent_classifier": cfg.enable_llm_intent_classifier,
        "fallback_to_rule_classifier": cfg.fallback_to_rule_classifier,
        "errors": errors,
        "warnings": warnings,
    }


def _health_from_validation(validation: dict[str, Any], *, network_checked: bool = False) -> dict[str, Any]:
    return {
        **validation,
        "ok": validation.get("status") == "ok",
        "network_checked": network_checked,
    }


def check_llm_provider_health(*, skip_network: bool = True, client: Any | None = None) -> dict[str, Any]:
    validation = validate_llm_config()
    if validation["status"] == "invalid" or skip_network:
        return _health_from_validation(validation, network_checked=False)
    if validation["provider"] == "fake":
        return _health_from_validation(validation, network_checked=False)

    try:
        if client is not None:
            if hasattr(client, "invoke"):
                client.invoke("ping")
            elif callable(client):
                client("ping")
        else:
            from langchain_openai import ChatOpenAI

            cfg = load_llm_provider_config()
            kwargs: dict[str, Any] = {
                "model": cfg.model,
                "api_key": os.getenv(cfg.api_key_env, ""),
                "temperature": 0,
                "timeout": cfg.timeout,
                "max_retries": cfg.max_retries,
            }
            if cfg.base_url:
                kwargs["base_url"] = cfg.base_url
            ChatOpenAI(**kwargs).invoke("Reply with OK.")
    except Exception as exc:
        validation["status"] = "degraded"
        validation["warnings"].append(_error("LLM_HEALTH_CHECK_FAILED", "LLM provider health check failed.", technical_detail=type(exc).__name__))
        return _health_from_validation(validation, network_checked=True)
    return _health_from_validation(validation, network_checked=True)
