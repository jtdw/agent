from __future__ import annotations

from pydantic import BaseModel


class MapLayerRefreshIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    artifact_id: str = ""
    dataset_name: str = ""
