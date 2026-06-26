from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from core.semantic_parser import parse_user_semantics


Worker = Callable[..., dict[str, Any]]


def extract_gscloud_dem_dataset_id_from_prompt(prompt: str) -> str:
    semantic = parse_user_semantics(prompt)
    dataset_id = str(semantic.get("dataset_id") or "").strip()
    if dataset_id:
        return dataset_id

    compact = re.sub(r"\s+", "", str(prompt or "")).lower()
    if "srtm" in compact or "90m" in compact or "\u0039\u0030\u7c73" in compact:
        return "306"
    if "gdemv2" in compact or "gdem2" in compact:
        return "421"
    return "310"


def extract_year_from_prompt(prompt: str) -> str:
    match = re.search(r"(20\d{2}|19\d{2})\s*(?:\u5e74)?", prompt or "")
    return match.group(1) if match else ""


def extract_cloud_max_from_prompt(prompt: str, default: float = 30.0) -> float:
    text = prompt or ""
    patterns = [
        r"\u4e91\u91cf(?:\u5c0f\u4e8e|\u4f4e\u4e8e|\u4e0d\u8d85\u8fc7|<=|\u2264|<)?\s*(\d+(?:\.\d+)?)",
        r"cloud(?:\s*(?:max|cover|<=|\u2264|<|under|below))?\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return default


def extract_max_scenes_from_prompt(prompt: str, default: int = 1) -> int:
    text = prompt or ""
    patterns = [
        r"(?:\u4e0b\u8f7d|\u9009\u62e9|\u83b7\u53d6)\s*(\d+)\s*(?:\u666f|\u5e45|\u4e2a)",
        r"(\d+)\s*(?:scene|scenes|image|images)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return max(1, min(10, int(match.group(1))))
    return default


def sentinel2_processing_level_from_prompt(prompt: str) -> str:
    upper = str(prompt or "").upper().replace(" ", "")
    if "L2A" in upper or "MSIL2A" in upper:
        return "MSIL2A"
    if "L1C" in upper or "MSIL1C" in upper:
        return "MSIL1C"
    return ""


@dataclass
class GSCloudAutoStartService:
    commercial_service: Callable[[], Any]
    workdir: str | Path | Callable[[], str | Path]
    products: Mapping[str, Any]
    tile_worker: Worker | None = None
    modl1d_worker: Worker | None = None
    modnd1d_worker: Worker | None = None
    modev1f_worker: Worker | None = None
    mod021km_worker: Worker | None = None
    sentinel2_worker: Worker | None = None
    landsat8_worker: Worker | None = None

    def current_workdir(self) -> Path:
        value = self.workdir() if callable(self.workdir) else self.workdir
        return Path(value)

    def product_resource_type(self, key: str) -> str:
        product = self.products.get(key)
        return str(getattr(product, "resource_type", "") or "").lower()

    def maybe_start(self, job: dict, region: str = "") -> dict[str, Any]:
        source_key = str(job.get("source_key") or "").lower()
        resource_type = str(job.get("resource_type") or "").lower()
        if source_key != "gscloud":
            return {"auto_supported": False, "auto_started": False, "reason": "not_gscloud"}

        commercial = self.commercial_service()
        job_id = str(job.get("job_id") or "")
        state_path = self._resolve_storage_state_path(commercial, job_id)
        if not state_path or not Path(state_path).exists():
            if hasattr(commercial, "_release_platform_reservation"):
                commercial._release_platform_reservation(job_id, "release_waiting_login_platform_download")
            commercial._update_job(job_id, status="waiting_login", progress=5, stage="needs_gscloud_login_state")
            return {"auto_supported": True, "auto_started": False, "reason": "waiting_login"}

        actual_region = region or str(job.get("region") or "") or "\u5f53\u524d\u7814\u7a76\u533a"
        request_text = str(job.get("request_text") or "")
        year = extract_year_from_prompt(request_text) or str(job.get("start_date") or "")[:4]

        scene_handlers = {
            self.product_resource_type("modl1d"): (
                self.modl1d_worker,
                "modl1d_worker_unavailable",
                "starting_modl1d_scene_worker",
                {"include_quality": self._includes_quality(request_text)},
            ),
            self.product_resource_type("modnd1d"): (
                self.modnd1d_worker,
                "modnd1d_worker_unavailable",
                "starting_modnd1d_scene_worker",
                {"include_qc": self._includes_quality(request_text)},
            ),
            self.product_resource_type("modev1f"): (
                self.modev1f_worker,
                "modev1t_worker_unavailable",
                "starting_modev1t_scene_worker",
                {},
            ),
            self.product_resource_type("mod021km"): (
                self.mod021km_worker,
                "mod021km_worker_unavailable",
                "starting_mod021km_scene_worker",
                {},
            ),
            self.product_resource_type("sentinel2"): (
                self.sentinel2_worker,
                "sentinel2_worker_unavailable",
                "starting_sentinel2_scene_worker",
                {"processing_level": sentinel2_processing_level_from_prompt(request_text)},
            ),
            self.product_resource_type("landsat8"): (
                self.landsat8_worker,
                "landsat_worker_unavailable",
                "starting_landsat8_scene_worker",
                {"cloud_max": extract_cloud_max_from_prompt(request_text, default=30.0)},
            ),
        }
        scene_handlers.pop("", None)
        if resource_type in scene_handlers:
            worker, unavailable_reason, stage, extra = scene_handlers[resource_type]
            return self._start_scene_worker(
                commercial=commercial,
                worker=worker,
                unavailable_reason=unavailable_reason,
                stage=stage,
                job=job,
                job_id=job_id,
                region=actual_region,
                year=year,
                request_text=request_text,
                extra=extra,
            )

        if resource_type != "dem":
            return {"auto_supported": False, "auto_started": False, "reason": "unsupported_gscloud_resource_type"}
        if self.tile_worker is None:
            return {"auto_supported": True, "auto_started": False, "reason": "tile_worker_unavailable"}

        commercial._update_job(job_id, status="running", progress=5, stage="starting_auto_tile_worker")
        tile_job = self.tile_worker(
            workdir=self.current_workdir(),
            job_id=job_id,
            region=actual_region,
            region_dataset="",
            dataset_id=extract_gscloud_dem_dataset_id_from_prompt(request_text),
            max_tiles=0,
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        return {"auto_supported": True, "auto_started": True, "reason": "started", "auto_tile_job": tile_job}

    def _resolve_storage_state_path(self, commercial: Any, job_id: str) -> str:
        try:
            return str(commercial.resolve_job_storage_state_path(job_id) or "")
        except Exception:
            return ""

    def _start_scene_worker(
        self,
        *,
        commercial: Any,
        worker: Worker | None,
        unavailable_reason: str,
        stage: str,
        job: dict,
        job_id: str,
        region: str,
        year: str,
        request_text: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        if worker is None:
            return {"auto_supported": True, "auto_started": False, "reason": unavailable_reason}
        commercial._update_job(job_id, status="running", progress=5, stage=stage)
        scene_job = worker(
            workdir=self.current_workdir(),
            job_id=job_id,
            region=region,
            year=year,
            start_date=str(job.get("start_date") or ""),
            end_date=str(job.get("end_date") or ""),
            max_scenes=extract_max_scenes_from_prompt(request_text, default=1),
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
            **extra,
        )
        return {"auto_supported": True, "auto_started": True, "reason": "started", "scene_job": scene_job}

    def _includes_quality(self, request_text: str) -> bool:
        lower = request_text.lower()
        return "qc" in lower or "\u8d28\u91cf" in request_text
