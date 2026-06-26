from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from api.schemas.admin_capabilities import CapabilityRollbackIn, CapabilityStatusIn
from core.capability_config import CAPABILITY_CONFIG_VERSION


ResourceType = Literal["knowledge", "tool_cards", "products", "assets"]


def _require_admin(require_capability_admin: Callable[[Request], None], request: Request) -> None:
    try:
        require_capability_admin(request)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def create_capabilities_router(
    *,
    capability_store: Callable[[], Any],
    require_capability_admin: Callable[[Request], None],
    extract_capability_document_text: Callable[[UploadFile], Awaitable[tuple[str, str]]],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/capabilities", tags=["admin-capabilities"])

    @router.get("/{resource_type}")
    def list_capability_resources(resource_type: ResourceType, request: Request, include_disabled: bool = False):
        def run():
            _require_admin(require_capability_admin, request)
            return {
                "schema_version": "capability-management-view/v1",
                "registry_version": CAPABILITY_CONFIG_VERSION,
                "resource_type": resource_type,
                "items": capability_store().list_resources(resource_type, include_disabled=include_disabled),
            }

        return guard(run)

    @router.post("/knowledge")
    def upsert_capability_knowledge(body: dict[str, Any], request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return {"ok": True, "item": capability_store().upsert_knowledge(body), "registry_version": CAPABILITY_CONFIG_VERSION}

        return guard(run)

    @router.post("/knowledge/upload")
    async def upload_capability_knowledge(
        request: Request,
        file: UploadFile = File(...),
        knowledge_id: str = Form(""),
        title: str = Form(""),
        source: str = Form("admin_upload"),
        language: str = Form("zh-CN"),
        tags: str = Form(""),
        applicable_scope: str = Form(""),
        reliability: str = Form("medium"),
        version: str = Form("v1"),
        status: str = Form("draft"),
    ):
        try:
            _require_admin(require_capability_admin, request)
            content, filename = await extract_capability_document_text(file)
            safe_id = knowledge_id.strip() or re.sub(r"[^A-Za-z0-9_.:-]+", "_", Path(filename).stem).strip("._:-") or "knowledge_doc"
            payload = {
                "knowledge_id": safe_id,
                "title": title.strip() or Path(filename).stem,
                "source": source,
                "language": language,
                "tags": [item.strip() for item in tags.split(",") if item.strip()],
                "applicable_scope": applicable_scope.strip() or "general",
                "reliability": reliability,
                "version": version,
                "status": status,
                "content": content,
                "original_filename": filename,
            }
            return {"ok": True, "item": capability_store().upsert_knowledge(payload), "registry_version": CAPABILITY_CONFIG_VERSION}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tool-cards")
    def upsert_capability_tool_card(body: dict[str, Any], request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return {"ok": True, "item": capability_store().upsert_tool_card(body), "registry_version": CAPABILITY_CONFIG_VERSION}

        return guard(run)

    @router.post("/products")
    def upsert_capability_product(body: dict[str, Any], request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return {"ok": True, "item": capability_store().upsert_product(body), "registry_version": CAPABILITY_CONFIG_VERSION}

        return guard(run)

    @router.post("/assets")
    def upsert_capability_asset(body: dict[str, Any], request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return {"ok": True, "item": capability_store().upsert_asset(body), "registry_version": CAPABILITY_CONFIG_VERSION}

        return guard(run)

    @router.post("/{resource_type}/{item_id}/status")
    def update_capability_status(resource_type: ResourceType, item_id: str, body: CapabilityStatusIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return {
                "ok": True,
                "item": capability_store().set_status(resource_type, item_id, body.status, actor=body.actor, summary=body.summary),
                "registry_version": CAPABILITY_CONFIG_VERSION,
            }

        return guard(run)

    @router.post("/{resource_type}/{item_id}/rollback")
    def rollback_capability_resource(resource_type: ResourceType, item_id: str, body: CapabilityRollbackIn, request: Request):
        def run():
            _require_admin(require_capability_admin, request)
            return {
                "ok": True,
                "item": capability_store().rollback(resource_type, item_id, body.version, actor=body.actor, summary=body.summary),
                "registry_version": CAPABILITY_CONFIG_VERSION,
            }

        return guard(run)

    @router.get("/audit/events")
    def list_capability_audit_events(request: Request, limit: int = 100):
        def run():
            _require_admin(require_capability_admin, request)
            return {
                "schema_version": "capability-audit-view/v1",
                "events": capability_store().list_audit_events(limit=limit),
            }

        return guard(run)

    @router.get("/knowledge/search/test")
    def test_capability_knowledge_search(request: Request, query: str, limit: int = 5, language: str = "", scope: str = ""):
        def run():
            _require_admin(require_capability_admin, request)
            return {
                "schema_version": "knowledge-retrieval-test/v1",
                "registry_version": CAPABILITY_CONFIG_VERSION,
                "query": query,
                "items": capability_store().retrieve_knowledge(query, limit=limit, language=language, scope=scope),
            }

        return guard(run)

    return router
