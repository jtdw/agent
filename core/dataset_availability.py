from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any


DATASET_AVAILABILITY_SCHEMA_VERSION = "dataset-availability-profile/v1"
ACTIVE_STATUSES = {"active", "enabled"}
AVAILABILITY_STATUSES = {"draft", "pending_review", "active", "deprecated", "disabled", "archived", "enabled"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _default_root() -> Path:
    configured = os.getenv("GIS_AGENT_CAPABILITY_CONFIG_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / "workspace" / "capability_config"


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m", "%Y/%m", "%Y.%m", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


def normalize_availability_profile(raw: dict[str, Any]) -> dict[str, Any]:
    item = dict(raw or {})
    product_id = str(item.get("product_id") or "").strip()
    if not product_id:
        raise ValueError("product_id is required")
    item.setdefault("schema_version", DATASET_AVAILABILITY_SCHEMA_VERSION)
    item["product_id"] = product_id
    item["source_product_key"] = str(item.get("source_product_key") or "").strip()
    item["display_name_zh"] = str(item.get("display_name_zh") or product_id).strip()
    item["source_url"] = str(item.get("source_url") or "").strip()
    item["temporal_coverage"] = _as_dict(item.get("temporal_coverage"))
    item["supported_formats"] = [str(value).strip() for value in item.get("supported_formats", []) if str(value).strip()]
    item["verification_method"] = str(item.get("verification_method") or "").strip() or "manual"
    item["status"] = str(item.get("status") or "draft").strip().lower()
    item["version"] = str(item.get("version") or "v1").strip()
    item.setdefault("created_at", _now())
    item["updated_at"] = _now()
    return item


class DatasetAvailabilityStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else _default_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "dataset_availability_profiles.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": DATASET_AVAILABILITY_SCHEMA_VERSION, "items": {}, "history": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"schema_version": DATASET_AVAILABILITY_SCHEMA_VERSION, "items": {}, "history": {}}
        if not isinstance(data, dict):
            return {"schema_version": DATASET_AVAILABILITY_SCHEMA_VERSION, "items": {}, "history": {}}
        data.setdefault("schema_version", DATASET_AVAILABILITY_SCHEMA_VERSION)
        data.setdefault("items", {})
        data.setdefault("history", {})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)

    def upsert_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        item = normalize_availability_profile(payload)
        if item.get("status") not in AVAILABILITY_STATUSES:
            raise ValueError(f"unsupported dataset availability status: {item.get('status')}")
        product_id = item["product_id"]
        current = _as_dict(data["items"].get(product_id))
        if current:
            data["history"].setdefault(product_id, []).append(current)
            item["created_at"] = current.get("created_at") or item.get("created_at") or _now()
        data["items"][product_id] = item
        self._write(data)
        return item

    def set_status(self, product_id: str, status: str, *, actor: str = "", summary: str = "") -> dict[str, Any]:
        next_status = str(status or "").strip().lower()
        if next_status not in AVAILABILITY_STATUSES:
            raise ValueError(f"unsupported dataset availability status: {status}")
        data = self._read()
        key = str(product_id or "").strip()
        item = _as_dict(data.get("items", {}).get(key))
        if not item:
            raise FileNotFoundError(f"dataset availability profile not found: {key}")
        data["history"].setdefault(key, []).append(dict(item))
        item["status"] = next_status
        item["updated_at"] = _now()
        if actor:
            item["reviewed_by" if next_status in ACTIVE_STATUSES else "updated_by"] = str(actor)[:120]
        if summary:
            item["review_summary"] = str(summary)[:500]
        data["items"][key] = item
        self._write(data)
        return item

    def list_profiles(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        data = self._read()
        items = [dict(item) for item in data.get("items", {}).values() if isinstance(item, dict)]
        if not include_inactive:
            items = [item for item in items if str(item.get("status") or "").lower() in ACTIVE_STATUSES]
        return sorted(items, key=lambda item: (str(item.get("product_id") or ""), str(item.get("version") or "")))

    def get_active_profile(self, product_id: str) -> dict[str, Any]:
        item = _as_dict(self._read().get("items", {}).get(str(product_id or "").strip()))
        if str(item.get("status") or "").lower() not in ACTIVE_STATUSES:
            return {}
        return dict(item)


def availability_for_product(product_id: str) -> dict[str, Any]:
    return DatasetAvailabilityStore().get_active_profile(product_id)


def availability_time_error(product_id: str, time_range: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any] | None:
    item = profile if profile is not None else availability_for_product(product_id)
    item = _as_dict(item)
    coverage = _as_dict(item.get("temporal_coverage"))
    start_bound = _parse_date(coverage.get("start"))
    end_bound = _parse_date(coverage.get("end"))
    if not start_bound and not end_bound:
        return None
    requested_start = _parse_date(_as_dict(time_range).get("start"))
    requested_end = _parse_date(_as_dict(time_range).get("end")) or requested_start
    if not requested_start:
        return None
    if start_bound and requested_start < start_bound:
        return {
            "start": str(start_bound),
            "end": str(end_bound) if end_bound else "",
            "requested_start": str(requested_start),
            "requested_end": str(requested_end) if requested_end else "",
            "profile_version": item.get("version", ""),
            "verification_method": item.get("verification_method", ""),
        }
    if end_bound and requested_end and requested_end > end_bound:
        return {
            "start": str(start_bound) if start_bound else "",
            "end": str(end_bound),
            "requested_start": str(requested_start),
            "requested_end": str(requested_end),
            "profile_version": item.get("version", ""),
            "verification_method": item.get("verification_method", ""),
        }
    return None
