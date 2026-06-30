from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from api.schemas.map import MapLayerRefreshIn
from core.map_layers import MapLayerService

PRIVATE_MAP_PAYLOAD_KEYS = {
    "path",
    "source_path",
    "display_path",
    "absolute_path",
    "relative_path",
    "download_url",
    "preview_path",
    "status_path",
    "log_path",
    "metrics_path",
}
PRIVATE_MAP_TEXT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:tmp|home|var|etc|root|Users)/|workspace[\\/](?:users|sessions)|/api/(?:files/artifact|downloads/artifact)\?)",
    re.IGNORECASE,
)


def _looks_private_map_text(value: Any) -> bool:
    return bool(PRIVATE_MAP_TEXT_RE.search(str(value or "")))


def _public_map_payload(value: Any) -> Any:
    if isinstance(value, list):
        output = [_public_map_payload(item) for item in value]
        return [item for item in output if item not in ({}, [], "")]
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in PRIVATE_MAP_PAYLOAD_KEYS:
                continue
            cleaned = _public_map_payload(item)
            if cleaned in ({}, [], ""):
                continue
            clean[key] = cleaned
        return clean
    if isinstance(value, str):
        return "" if _looks_private_map_text(value) else value
    return value


def create_map_router(
    *,
    scoped_workspace_service: Callable[[str, str], Any],
    require_request_user_if_present: Callable[[Request, str], str],
    load_station_collection: Callable[..., dict[str, Any]],
    guard: Callable[[Callable[[], Any]], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/map", tags=["map"])

    @router.get("/stations")
    def map_stations(request: Request, user_id: str = Query(default="")):
        return guard(lambda: load_station_collection(require_request_user_if_present(request, user_id)))

    @router.get("/layers")
    def map_layers(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
        def run():
            if not str(user_id or "").strip() and not str(session_id or "").strip():
                return {"layers": []}
            authorized_user_id = require_request_user_if_present(request, user_id)
            payload = MapLayerService(scoped_workspace_service(authorized_user_id, session_id)).workspace_layers(
                user_id=authorized_user_id,
                session_id=session_id,
            )
            return _public_map_payload(payload)

        return guard(run)

    @router.post("/layers/refresh")
    def refresh_map_layer(body: MapLayerRefreshIn, request: Request):
        def run():
            if not body.artifact_id and not body.dataset_name:
                raise HTTPException(status_code=400, detail="artifact_id or dataset_name is required")
            authorized_user_id = require_request_user_if_present(request, body.user_id)
            service = scoped_workspace_service(authorized_user_id, body.session_id)
            layer_service = MapLayerService(service)
            if body.artifact_id:
                service.manager.assert_artifact_access(authorized_user_id, body.session_id or service.current_session_id, body.artifact_id)
                return _public_map_payload(layer_service.refresh_artifact(body.artifact_id, user_id=authorized_user_id, session_id=body.session_id))
            dataset = next((item for item in service.manager.list_datasets() if item.get("name") == body.dataset_name), None)
            if not dataset:
                raise FileNotFoundError(f"dataset not found: {body.dataset_name}")
            layer = layer_service.dataset_layer(dataset, user_id=authorized_user_id, session_id=body.session_id)
            if not layer:
                raise ValueError(f"dataset produced no map layer: {body.dataset_name}")
            return _public_map_payload({"dataset_name": body.dataset_name, "map_layer_id": layer["id"], "map_ready": True, "layer": layer})

        return guard(run)

    @router.get("/raster-preview")
    def map_raster_preview(request: Request, user_id: str = Query(default=""), session_id: str = Query(default=""), dataset_name: str = Query(...), palette: str = Query(default="")):
        def run():
            authorized_user_id = require_request_user_if_present(request, user_id)
            service = scoped_workspace_service(authorized_user_id, session_id)
            layer_service = MapLayerService(service)
            target = layer_service.raster_preview_path(dataset_name, palette=palette)
            if not target.exists():
                layer_service.ensure_raster_preview(dataset_name, user_id=authorized_user_id, session_id=session_id, palette=palette)
            if not target.exists():
                raise FileNotFoundError(f"raster preview not found: {dataset_name}")
            return FileResponse(str(target), media_type="image/png", filename=target.name)

        return guard(run)

    return router
