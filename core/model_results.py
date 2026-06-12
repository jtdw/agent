from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


def _safe_part(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip().lower())
    return re.sub(r"_+", "_", text).strip("_") or "model"


def generate_model_result_id(model_name: str = "", output_prefix: str = "", *, legacy_key: str = "") -> str:
    if legacy_key:
        digest = hashlib.sha1(str(legacy_key).encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"legacy_model_{digest}"
    prefix = _safe_part(output_prefix or model_name)
    model = _safe_part(model_name)
    return f"model_result_{model}_{prefix}_{uuid4().hex[:10]}"


@dataclass
class ModelResult:
    model_result_id: str
    task_id: str
    dataset_id: str
    model_name: str
    output_prefix: str = ""
    result_dataset: str = ""
    metrics_dataset: str = ""
    metrics_path: str = ""
    figure_path: str = ""
    artifact_ids: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
