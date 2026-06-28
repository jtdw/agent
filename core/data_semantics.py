from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "gis-data-semantic-card/v1"
META_KEY = "data_semantic_card"
CATALOG_FILENAME = "data_semantic_cards.json"

_SENSITIVE_KEY_TOKENS = (
    "absolute_path",
    "archive_path",
    "cookie",
    "credential",
    "env",
    "password",
    "prompt",
    "raw_rows",
    "secret",
    "storage_state",
    "token",
)
_PATH_PATTERN = re.compile(r"([A-Za-z]:\\|/[A-Za-z0-9_.-]+/|\\\\)")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").lower()
    return any(token in lowered for token in _SENSITIVE_KEY_TOKENS)


def _looks_like_path(value: str) -> bool:
    text = str(value or "")
    return bool(_PATH_PATTERN.search(text))


def build_data_semantic_card(
    *,
    dataset_name: str,
    source_kind: str,
    scientific_roles: list[str] | tuple[str, ...] | None = None,
    variables: list[dict[str, Any]] | None = None,
    spatial: dict[str, Any] | None = None,
    temporal: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    modeling: dict[str, Any] | None = None,
    lineage: dict[str, Any] | None = None,
    row_count: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_name": str(dataset_name or ""),
        "source_kind": str(source_kind or ""),
        "scientific_roles": [str(item) for item in _as_list(scientific_roles)],
        "variables": _json_safe(variables or []),
        "spatial": _json_safe(spatial or {}),
        "temporal": _json_safe(temporal or {}),
        "quality": _json_safe(quality or {}),
        "modeling": _json_safe(modeling or {}),
        "lineage": _json_safe(lineage or {}),
    }
    if row_count is not None:
        try:
            card["row_count"] = int(row_count)
        except Exception:
            card["row_count"] = row_count
    for key, value in extra.items():
        if value is not None:
            card[str(key)] = _json_safe(value)
    return card


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                continue
            sanitized = _sanitize_value(item)
            if sanitized is not None:
                clean[key_text] = sanitized
        return clean
    if isinstance(value, list):
        items = [_sanitize_value(item) for item in value]
        return [item for item in items if item is not None]
    if isinstance(value, tuple):
        items = [_sanitize_value(item) for item in value]
        return [item for item in items if item is not None]
    if isinstance(value, str) and _looks_like_path(value):
        return None
    return _json_safe(value)


def sanitize_semantic_card_for_planner(card: dict[str, Any]) -> dict[str, Any]:
    safe = _sanitize_value(card)
    if not isinstance(safe, dict):
        return {"schema_version": SCHEMA_VERSION}
    safe["schema_version"] = SCHEMA_VERSION
    allowed = {
        "schema_version",
        "dataset_name",
        "source_kind",
        "scientific_roles",
        "variables",
        "spatial",
        "temporal",
        "quality",
        "modeling",
        "lineage",
        "row_count",
        "recommended_tools",
    }
    return {key: value for key, value in safe.items() if key in allowed and value not in (None, "", [], {})}


def semantic_card_catalog_path(manager: Any) -> Path:
    base = Path(getattr(manager, "derived_dir", None) or getattr(manager, "workdir", "."))
    base.mkdir(parents=True, exist_ok=True)
    return base / CATALOG_FILENAME


def _write_catalog(manager: Any, cards: list[dict[str, Any]]) -> None:
    path = semantic_card_catalog_path(manager)
    path.write_text(json.dumps(cards, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def list_semantic_cards(manager: Any) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    try:
        datasets = manager.list_datasets()
    except Exception:
        datasets = []
    for item in datasets:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        card = meta.get(META_KEY)
        if isinstance(card, dict):
            cards.append(sanitize_semantic_card_for_planner(card))
    if cards:
        return cards
    path = semantic_card_catalog_path(manager)
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [sanitize_semantic_card_for_planner(item) for item in loaded if isinstance(item, dict)]


def attach_semantic_card_to_dataset(manager: Any, dataset_name: str, card: dict[str, Any]) -> dict[str, Any]:
    record = manager.get(dataset_name)
    safe = sanitize_semantic_card_for_planner({**dict(card), "dataset_name": dataset_name})
    meta = dict(getattr(record, "meta", {}) or {})
    meta[META_KEY] = safe
    record.meta = meta
    cards_by_name = {str(item.get("dataset_name") or ""): item for item in list_semantic_cards(manager)}
    cards_by_name[str(dataset_name)] = safe
    _write_catalog(manager, list(cards_by_name.values()))
    return safe


def semantic_cards_for_context(manager: Any, *, active_dataset_name: str = "", limit: int = 8) -> list[dict[str, Any]]:
    cards = list_semantic_cards(manager)
    if active_dataset_name:
        cards.sort(key=lambda item: 0 if str(item.get("dataset_name") or "") == active_dataset_name else 1)
    return cards[: max(0, int(limit))]
