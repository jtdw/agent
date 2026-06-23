from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CAPABILITY_CONFIG_VERSION = "capability-config/v1"
RESOURCE_TYPES = {"knowledge", "tool_cards", "products", "assets"}
DOWNLOAD_ADAPTER_ALLOWLIST = {
    "gscloud_dem_tile",
    "gscloud_scene_table",
    "fixture",
    "fixture_download",
}
RUNTIME_ACTIVE_STATUSES = {"active", "enabled"}
CAPABILITY_STATUSES = {"draft", "pending_review", "active", "deprecated", "disabled", "archived", "enabled"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", str(text or ""))}


def _default_root() -> Path:
    configured = os.getenv("GIS_AGENT_CAPABILITY_CONFIG_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / "workspace" / "capability_config"


def _sanitize_content(text: str, limit: int = 8000) -> str:
    blocked = (
        "ignore previous instructions",
        "ignore all previous instructions",
        "system prompt",
        "developer message",
        "call submit_commercial_download_job",
        "execute tool",
        "bypass validator",
        "绕过",
        "忽略之前",
        "系统提示词",
        "直接调用工具",
    )
    lines: list[str] = []
    for line in str(text or "").splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in blocked):
            continue
        lines.append(line)
    return "\n".join(lines).strip()[:limit]


def validate_download_adapter(adapter: str) -> str:
    value = str(adapter or "").strip()
    if value not in DOWNLOAD_ADAPTER_ALLOWLIST:
        raise ValueError(f"download_adapter is not allowlisted: {value}")
    if any(marker in value for marker in (":", "/", "\\", " ", ";", "&", "|", "$", "`")):
        raise ValueError("download_adapter must be a backend allowlist key, not a module, command, URL, or path")
    return value


def _validate_asset_registration(item: dict[str, Any]) -> None:
    raw_path = str(item.get("path") or item.get("source_path") or "").strip()
    if raw_path:
        profile = _as_dict(item.get("asset_profile"))
        if profile.get("path_verified") is not True and profile.get("source_path_verified") is not True:
            raise ValueError("Asset Registry path must be server verified before registration.")
    if item.get("permission") not in {"public", "private", "admin"}:
        raise ValueError("Asset Registry permission must be public, private, or admin.")


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    knowledge_id: str
    title: str
    source: str = ""
    language: str = "zh-CN"
    tags: list[str] = Field(default_factory=list)
    applicable_scope: str = "general"
    reliability: str = "untrusted"
    version: str = "v1"
    status: Literal["draft", "pending_review", "active", "deprecated", "disabled", "archived", "enabled"] = "draft"
    content: str = ""
    created_at: str = ""
    updated_at: str = ""


class ConfiguredProduct(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str
    display_name_zh: str
    source: str
    source_product_key: str = ""
    resource_type: str
    supported_resolutions: list[str] = Field(default_factory=list)
    temporal_requirement: str = "none"
    spatial_coverage: str = ""
    required_parameters: list[str] = Field(default_factory=list)
    optional_parameters: list[str] = Field(default_factory=list)
    login_or_license_requirement: str = ""
    supported_output_format: list[str] = Field(default_factory=list)
    tool_card: str
    download_adapter: str
    unsupported_scenarios: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: Literal["draft", "pending_review", "active", "deprecated", "disabled", "archived", "enabled"] = "draft"
    version: str = "v1"
    created_at: str = ""
    updated_at: str = ""


class ConfiguredAsset(BaseModel):
    model_config = ConfigDict(extra="allow")

    asset_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    asset_type: str = "boundary"
    source: str = ""
    crs: str = ""
    bounds: list[float] = Field(default_factory=list)
    geometry_type: str = ""
    permission: str = "public"
    version: str = "v1"
    status: Literal["draft", "pending_review", "active", "deprecated", "disabled", "archived", "enabled"] = "draft"
    asset_profile: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


def _resource_id(resource_type: str, data: dict[str, Any]) -> str:
    key = {
        "knowledge": "knowledge_id",
        "tool_cards": "tool_name",
        "products": "product_id",
        "assets": "asset_id",
    }.get(resource_type)
    if not key:
        raise ValueError(f"unsupported capability resource type: {resource_type}")
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


class CapabilityConfigStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else _default_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, resource_type: str) -> Path:
        if resource_type not in RESOURCE_TYPES:
            raise ValueError(f"unsupported capability resource type: {resource_type}")
        return self.root / f"{resource_type}.json"

    def _read(self, resource_type: str) -> dict[str, Any]:
        path = self._path(resource_type)
        if not path.exists():
            return {"schema_version": CAPABILITY_CONFIG_VERSION, "items": {}, "history": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"schema_version": CAPABILITY_CONFIG_VERSION, "items": {}, "history": {}}
        data.setdefault("schema_version", CAPABILITY_CONFIG_VERSION)
        data.setdefault("items", {})
        data.setdefault("history", {})
        return data

    def _write(self, resource_type: str, data: dict[str, Any]) -> None:
        path = self._path(resource_type)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def _audit_path(self) -> Path:
        return self.root / "audit_events.json"

    def _read_audit(self) -> list[dict[str, Any]]:
        path = self._audit_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [dict(item) for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def _write_audit(self, events: list[dict[str, Any]]) -> None:
        path = self._audit_path()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(events[-1000:], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def _record_audit(self, action: str, resource_type: str, item_id: str, *, actor: str = "", summary: str = "", status: str = "") -> None:
        events = self._read_audit()
        events.append(
            {
                "event_id": f"capability_audit_{len(events) + 1}",
                "timestamp": _now(),
                "action": action,
                "resource_type": resource_type,
                "item_id": item_id,
                "actor": str(actor or ""),
                "summary": str(summary or "")[:500],
                "status": str(status or ""),
            }
        )
        self._write_audit(events)

    def _upsert(self, resource_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        item = dict(payload)
        data = self._read(resource_type)
        pre_id = _resource_id(resource_type, item)
        current = _as_dict(data["items"].get(pre_id))
        if not item.get("status"):
            item["status"] = "draft"
        elif current and str(item.get("status")) in RUNTIME_ACTIVE_STATUSES:
            item["status"] = "draft"
        if resource_type == "knowledge":
            item["content"] = _sanitize_content(str(item.get("content") or ""))
            item = KnowledgeDocument.model_validate(item).model_dump(mode="json")
        elif resource_type == "products":
            item["download_adapter"] = validate_download_adapter(str(item.get("download_adapter") or ""))
            item = ConfiguredProduct.model_validate(item).model_dump(mode="json")
        elif resource_type == "assets":
            _validate_asset_registration(item)
            item = ConfiguredAsset.model_validate(item).model_dump(mode="json")
        elif resource_type == "tool_cards":
            from core.tool_cards import validate_tool_card

            errors = validate_tool_card(item)
            if errors:
                raise ValueError(f"invalid tool card: {', '.join(errors)}")
        item_id = _resource_id(resource_type, item)
        item.setdefault("created_at", current.get("created_at") or now)
        item["created_at"] = item.get("created_at") or current.get("created_at") or now
        item["updated_at"] = now
        item.setdefault("status", "draft")
        item.setdefault("version", "v1")
        item.setdefault("created_by", current.get("created_by") or str(payload.get("created_by") or ""))
        item.setdefault("change_summary", str(payload.get("change_summary") or current.get("change_summary") or ""))
        history = _as_list(data["history"].get(item_id))
        if current:
            history.append(current)
        data["history"][item_id] = history
        data["items"][item_id] = item
        self._write(resource_type, data)
        self._record_audit("upsert", resource_type, item_id, actor=str(payload.get("created_by") or payload.get("updated_by") or ""), summary=str(payload.get("change_summary") or ""), status=str(item.get("status") or ""))
        return item

    def upsert_knowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._upsert("knowledge", payload)

    def upsert_tool_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._upsert("tool_cards", payload)

    def upsert_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._upsert("products", payload)

    def upsert_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._upsert("assets", payload)

    def list_resources(self, resource_type: str, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        items = list(_as_dict(self._read(resource_type).get("items")).values())
        if not include_disabled:
            items = [item for item in items if _as_dict(item).get("status") in RUNTIME_ACTIVE_STATUSES]
        return [dict(item) for item in items if isinstance(item, dict)]

    def set_status(self, resource_type: str, item_id: str, status: str, *, actor: str = "", summary: str = "") -> dict[str, Any]:
        if status not in CAPABILITY_STATUSES:
            raise ValueError(f"unsupported capability status: {status}")
        data = self._read(resource_type)
        item = _as_dict(data["items"].get(item_id))
        if not item:
            raise FileNotFoundError(f"{resource_type} item not found: {item_id}")
        history = _as_list(data["history"].get(item_id))
        history.append(dict(item))
        item["status"] = status
        item["updated_at"] = _now()
        if status == "pending_review":
            item["submitted_by"] = actor
            item["submitted_at"] = item["updated_at"]
            item["review_summary"] = summary
        elif status == "active":
            item["reviewed_by"] = actor
            item["reviewed_at"] = item["updated_at"]
            item["review_summary"] = summary
        data["history"][item_id] = history
        data["items"][item_id] = item
        self._write(resource_type, data)
        self._record_audit("set_status", resource_type, item_id, actor=actor, summary=summary, status=status)
        return item

    def submit_for_review(self, resource_type: str, item_id: str, *, actor: str = "", summary: str = "") -> dict[str, Any]:
        item = self.set_status(resource_type, item_id, "pending_review", actor=actor, summary=summary)
        self._record_audit("submit_for_review", resource_type, item_id, actor=actor, summary=summary, status="pending_review")
        return item

    def approve(self, resource_type: str, item_id: str, *, actor: str = "", summary: str = "") -> dict[str, Any]:
        item = self.set_status(resource_type, item_id, "active", actor=actor, summary=summary)
        self._record_audit("approve", resource_type, item_id, actor=actor, summary=summary, status="active")
        return item

    def rollback(self, resource_type: str, item_id: str, version: str, *, actor: str = "", summary: str = "") -> dict[str, Any]:
        data = self._read(resource_type)
        current = _as_dict(data["items"].get(item_id))
        history = _as_list(data["history"].get(item_id))
        match = next((item for item in reversed(history + ([current] if current else [])) if _as_dict(item).get("version") == version), None)
        if not isinstance(match, dict):
            raise FileNotFoundError(f"{resource_type} version not found: {item_id}@{version}")
        if current:
            history.append(current)
        restored = dict(match)
        restored["status"] = "draft"
        restored["updated_at"] = _now()
        restored["rollback_source_version"] = version
        restored["rollback_by"] = actor
        restored["change_summary"] = summary
        data["history"][item_id] = history
        data["items"][item_id] = restored
        self._write(resource_type, data)
        self._record_audit("rollback", resource_type, item_id, actor=actor, summary=summary, status="draft")
        return restored

    def list_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._read_audit()[-max(1, int(limit or 1)) :]

    def hard_delete_session_private(self, user_id: str, session_id: str) -> list[str]:
        clean_user = str(user_id or "").strip()
        clean_session = str(session_id or "").strip()
        if not clean_session:
            return []
        data = self._read("knowledge")
        items = _as_dict(data.get("items"))
        history = _as_dict(data.get("history"))
        deleted: list[str] = []
        for item_id, item in list(items.items()):
            item_dict = _as_dict(item)
            if str(item_dict.get("session_id") or "") != clean_session:
                continue
            if clean_user and str(item_dict.get("owner_user_id") or "") not in {"", clean_user}:
                continue
            if str(item_dict.get("scope") or "").lower() not in {"private", "session", "user"}:
                continue
            deleted.append(str(item_id))
            items.pop(item_id, None)
            history.pop(item_id, None)
        data["items"] = items
        data["history"] = history
        self._write("knowledge", data)
        self._remove_session_index_files(clean_session)
        return deleted

    def _remove_session_index_files(self, session_id: str) -> list[str]:
        clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "")).strip("._")
        if not clean:
            return []
        removed: list[str] = []
        for folder_name in ("knowledge_index", "knowledge_chunks", "retrieval_cache", "vector_index"):
            root = self.root / folder_name
            if not root.exists():
                continue
            for path in sorted(root.rglob(f"*{clean}*"), reverse=True):
                try:
                    if path.is_dir():
                        for child in sorted(path.rglob("*"), reverse=True):
                            if child.is_file():
                                child.unlink()
                            elif child.is_dir():
                                child.rmdir()
                        path.rmdir()
                    else:
                        path.unlink()
                    removed.append(str(path))
                except Exception:
                    continue
        return removed

    def retrieve_knowledge(self, query: str, *, limit: int = 5, language: str = "", scope: str = "") -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        scored: list[tuple[int, dict[str, Any]]] = []
        for doc in self.list_resources("knowledge"):
            if language and doc.get("language") and str(doc.get("language")) != language:
                continue
            if scope and doc.get("applicable_scope") not in {scope, "general", ""}:
                continue
            content = str(doc.get("content") or "")
            parts = [part.strip() for part in re.split(r"\n\s*\n|(?<=[。.!?])", content) if part.strip()] or [content]
            for index, part in enumerate(parts):
                haystack = _tokens(" ".join([str(doc.get("title") or ""), part, " ".join(_as_list(doc.get("tags")))]))
                score = len(query_tokens & haystack)
                compact = str(query or "").lower()
                score += sum(2 for tag in _as_list(doc.get("tags")) if str(tag).lower() in compact)
                if score:
                    scored.append(
                        (
                            score,
                            {
                                "knowledge_chunk_id": f"{doc['knowledge_id']}:{doc.get('version')}:chunk_{index + 1}",
                                "knowledge_id": doc["knowledge_id"],
                                "knowledge_version": doc.get("version", ""),
                                "title": doc.get("title", ""),
                                "content": part[:1200],
                                "source": doc.get("source", ""),
                                "language": doc.get("language", ""),
                                "tags": _as_list(doc.get("tags")),
                                "applicable_scope": doc.get("applicable_scope", ""),
                                "reliability": doc.get("reliability", "untrusted"),
                                "source_trust": "trusted_operator" if doc.get("reliability") in {"high", "medium"} else "untrusted",
                                "schema_version": CAPABILITY_CONFIG_VERSION,
                            },
                        )
                    )
        scored.sort(key=lambda item: (-item[0], item[1]["knowledge_chunk_id"]))
        return [item for _, item in scored[: max(1, int(limit or 1))]]


def default_store() -> CapabilityConfigStore:
    return CapabilityConfigStore()


def configured_knowledge(query: str, *, limit: int = 5, language: str = "", scope: str = "") -> list[dict[str, Any]]:
    return default_store().retrieve_knowledge(query, limit=limit, language=language, scope=scope)


def configured_tool_cards() -> list[dict[str, Any]]:
    return default_store().list_resources("tool_cards")


def configured_products() -> list[dict[str, Any]]:
    return default_store().list_resources("products")


def configured_assets() -> list[dict[str, Any]]:
    return default_store().list_resources("assets")
