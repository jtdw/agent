from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


DEFAULT_SUPPORTED_MODELS = (
    "glm-4.5-air",
    "glm-4.7",
    "glm-4.1v-thinking-flashx",
    "glm-4.6v",
)

AUTO_ROUTE_LABEL = "自动选择（按任务）"
VISION_MODEL_HINTS = ("4.1v", "4.6v")
TEXT_MODEL_HINTS = ("4.5", "4.7")


def _parse_supported_models() -> tuple[str, ...]:
    raw = os.getenv("ZAI_SUPPORTED_MODELS", "").strip()
    if not raw:
        return DEFAULT_SUPPORTED_MODELS

    models = tuple(item.strip() for item in raw.split(",") if item.strip())
    return models or DEFAULT_SUPPORTED_MODELS


def is_vision_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return any(hint in lowered for hint in VISION_MODEL_HINTS)


def is_text_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return any(hint in lowered for hint in TEXT_MODEL_HINTS) and not is_vision_model(model_name)


def pick_preferred_model(candidates: tuple[str, ...], preferred: tuple[str, ...]) -> str | None:
    for target in preferred:
        if target in candidates:
            return target
    return candidates[0] if candidates else None


@dataclass(slots=True)
class Settings:
    api_key: str = os.getenv("ZAI_API_KEY", "")
    model: str = os.getenv("ZAI_MODEL", "glm-4.5-air")
    supported_models: tuple[str, ...] = field(default_factory=_parse_supported_models)
    base_url: str = "https://api.z.ai/api/paas/v4/"
    workdir: Path = Path(os.getenv("GIS_AGENT_WORKDIR", "./workspace"))
    temperature: float = float(os.getenv("GIS_AGENT_TEMPERATURE", "0.1"))
    desktop_theme: str = os.getenv("GIS_AGENT_THEME", "dark")

    def ensure_dirs(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.workdir / "uploads").mkdir(parents=True, exist_ok=True)
        (self.workdir / "plots").mkdir(parents=True, exist_ok=True)
        (self.workdir / "derived").mkdir(parents=True, exist_ok=True)
        (self.workdir / "temp").mkdir(parents=True, exist_ok=True)

    def vision_models(self) -> tuple[str, ...]:
        return tuple(model for model in self.supported_models if is_vision_model(model))

    def text_models(self) -> tuple[str, ...]:
        return tuple(model for model in self.supported_models if not is_vision_model(model))


class ConfigError(RuntimeError):
    pass


def load_settings() -> Settings:
    settings = Settings()
    if not settings.api_key:
        raise ConfigError(
            "未读取到 ZAI_API_KEY。请在 .env 中设置，或在系统环境变量中设置后重启终端。"
        )
    if settings.model not in settings.supported_models:
        settings.supported_models = (settings.model, *settings.supported_models)
    settings.ensure_dirs()
    return settings
