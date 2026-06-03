from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import uuid4

from fastapi import HTTPException


T = TypeVar("T")

logger = logging.getLogger("gis_agent.api")


def error_id() -> str:
    return f"err_{uuid4().hex[:10]}"


def api_guard(fn: Callable[[], T], *, context: str = "api") -> T:
    """Map domain exceptions to HTTP errors and keep an internal error id."""
    try:
        return fn()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        eid = error_id()
        logger.exception("Unhandled API error context=%s error_id=%s", context, eid)
        raise HTTPException(
            status_code=500,
            detail={"error_id": eid, "message": "Internal server error"},
        ) from exc


def resolve_child_path(root: Path, relative_path: str, *, must_exist: bool = True) -> Path:
    """Resolve a user-supplied relative path and require it to stay under root."""
    root_resolved = Path(root).resolve()
    raw = str(relative_path or "").strip()
    if not raw:
        raise ValueError("Missing file path.")

    target = (root_resolved / raw).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise PermissionError("Path is outside the allowed workspace.") from exc

    if must_exist and (not target.exists() or not target.is_file()):
        raise FileNotFoundError(f"File does not exist: {raw}")
    return target


def public_error_shape(exc: HTTPException) -> dict[str, Any]:
    return {"status_code": exc.status_code, "detail": exc.detail}
