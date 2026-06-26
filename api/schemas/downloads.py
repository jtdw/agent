from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DownloadIn(BaseModel):
    user_id: str
    session_id: str = ""
    source_key: str = "gscloud"
    resource_type: str = "dem"
    region: str = ""
    start_date: str = ""
    end_date: str = ""
    account_mode: Literal["own", "platform", "auto"] = "auto"
    request_text: str = ""
    output_name: str = ""
    include_raw: bool = False


class DownloadDeleteIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    job_id: str


class DownloadActionIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    job_id: str
    reason: str = ""


class DownloadPreflightIn(BaseModel):
    user_id: str
    session_id: str = ""
    source_key: str = "gscloud"
    resource_type: str = "landsat8_oli_tirs"
    product_key: str = ""
    region: str = ""
    start_date: str = ""
    end_date: str = ""
    account_mode: Literal["own", "platform", "auto"] = "auto"
    request_text: str = ""
    max_pages: int = 1
    cloud_max: float = 30.0
    processing_level: str = ""
