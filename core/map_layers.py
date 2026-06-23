from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zipfile import ZipFile

from core.archive_utils import safe_extract_zip
from core.service import GISWorkspaceService

VECTOR_EXTS = {".shp", ".geojson", ".gpkg", ".json", ".kml", ".zip"}
RASTER_EXTS = {".tif", ".tiff", ".img"}
SPATIAL_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MAP_DISPLAYABLE_EXTS = VECTOR_EXTS.union(RASTER_EXTS)
SHANDIAN_BOUNDARY_FILENAMES = ("shandianhe_basin_boundary_full.zip", "shandianhe_basin_boundary.zip")

_LOCAL_SHANDIAN_BOUNDARY_LAYER_CACHE: dict[str, Any] | None = None


def safe_layer_id(value: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip()).strip("_").lower()
    return clean or "layer"


def dataset_map_kind(name: str, data_type: str) -> str:
    text = str(name or "").lower()
    if any(token in text for token in ["ndvi", "evi", "vegetation", "植被"]):
        return "vegetation"
    if any(token in text for token in ["soil", "moisture", "sm", "prediction", "result"]):
        return "soil"
    if any(token in text for token in ["dem", "elevation", "srtm", "aster", "terrain", "slope", "aspect"]):
        return "dem"
    if any(token in text for token in ["boundary", "region", "aoi", "basin", "admin"]):
        return "boundary"
    return "boundary" if data_type == "vector" else "dem"


def _crs_text(value: Any) -> str:
    if not value:
        return ""
    try:
        return value.to_string()
    except Exception:
        return str(value)


def _merge_meta(*items: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict):
            merged.update(item)
    return merged


def _artifact_path_index(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        path = artifact.get("path")
        if not path:
            continue
        try:
            result[str(Path(str(path)).resolve())] = artifact
        except Exception:
            result[str(path)] = artifact
    return result


def _artifact_dataset_index(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        dataset_name = str(meta.get("dataset_name") or artifact.get("dataset_id") or "").strip()
        if dataset_name:
            result[dataset_name] = artifact
    return result


def _dedupe_boundary_layers(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[float, float, float, float]] = set()
    result: list[dict[str, Any]] = []
    for layer in layers:
        if layer.get("kind") != "boundary":
            result.append(layer)
            continue
        bounds = layer.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            result.append(layer)
            continue
        key = tuple(round(float(value), 6) for value in bounds)
        if key in seen:
            continue
        seen.add(key)
        result.append(layer)
    return result


def _is_shandian_boundary_layer(layer: dict[str, Any]) -> bool:
    meta = layer.get("meta") if isinstance(layer.get("meta"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            layer.get("id"),
            layer.get("name"),
            layer.get("dataset_name"),
            meta.get("item_id"),
            meta.get("source_path"),
        )
    ).lower()
    return "shandian" in text or "闪电河" in text


def _is_download_artifact_without_map_binding(artifact: dict[str, Any]) -> bool:
    path = Path(str(artifact.get("path") or ""))
    if "downloads" not in {part.lower() for part in path.parts}:
        return False
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    return not str(meta.get("dataset_name") or artifact.get("dataset_id") or "").strip() and not bool(meta.get("map_ready"))


def _strip_numeric_suffixes(value: str) -> str:
    clean = str(value or "")
    while re.search(r"_\d+$", clean):
        clean = re.sub(r"_\d+$", "", clean)
    return clean


def _download_dataset_dedupe_key(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "")
    path = Path(str(item.get("path") or ""))
    text = f"{name} {path}".lower()
    if "gscloud" not in text and "download" not in text:
        return ""
    normalized_name = _strip_numeric_suffixes(name)
    if normalized_name.endswith("_mosaic"):
        normalized_name = normalized_name[: -len("_mosaic")]
    if normalized_name:
        return normalized_name
    stem = _strip_numeric_suffixes(path.stem or name)
    if "gscloud" in stem:
        marker = stem.find("gscloud")
        prefix_start = stem.rfind("_", 0, marker)
        if prefix_start >= 0:
            stem = stem[prefix_start + 1 :]
    if stem.endswith("_mosaic"):
        stem = stem[: -len("_mosaic")]
    return stem


def _layer_download_dedupe_key(layer: dict[str, Any]) -> str:
    return _download_dataset_dedupe_key(
        {
            "name": str(layer.get("dataset_name") or layer.get("name") or ""),
            "path": str((layer.get("meta") if isinstance(layer.get("meta"), dict) else {}).get("source_path") or ""),
        }
    )


class MapLayerService:
    def __init__(self, service: GISWorkspaceService):
        self.service = service

    def _candidate_shandian_boundary_paths(self) -> list[Path]:
        project_root = Path(__file__).resolve().parents[1]
        roots = [
            self.service.manager.workdir / "local_library" / "data" / "boundary",
            project_root / "local_library" / "data" / "boundary",
        ]
        candidates: list[Path] = []
        for root in roots:
            for filename in SHANDIAN_BOUNDARY_FILENAMES:
                path = root / filename
                if path.exists():
                    candidates.append(path)
        return candidates

    def local_shandian_boundary_layer(self) -> dict[str, Any] | None:
        global _LOCAL_SHANDIAN_BOUNDARY_LAYER_CACHE
        if _LOCAL_SHANDIAN_BOUNDARY_LAYER_CACHE is not None:
            return json.loads(json.dumps(_LOCAL_SHANDIAN_BOUNDARY_LAYER_CACHE))
        for path in self._candidate_shandian_boundary_paths():
            try:
                gdf = self.read_vector_for_map(path)
                layer = self.vector_map_layer(
                    "闪电河流域边界",
                    gdf,
                    layer_id="local_library_shandianhe_basin_boundary",
                    kind="boundary",
                    meta={
                        "source": "local_library",
                        "item_id": "lib_shandianhe_basin_boundary_full",
                        "source_path": str(path),
                    },
                    dataset_name="shandianhe_basin_boundary",
                )
                if layer:
                    _LOCAL_SHANDIAN_BOUNDARY_LAYER_CACHE = json.loads(json.dumps(layer))
                    return layer
            except Exception:
                continue
        return None

    def raster_preview_path(self, dataset_name: str) -> Path:
        return self.service.manager.temp_dir / "map_previews" / f"{safe_layer_id(dataset_name)}.png"

    def ensure_raster_preview(self, dataset_name: str, user_id: str = "", session_id: str = "") -> dict[str, Any]:
        import numpy as np
        import rasterio
        from PIL import Image
        from rasterio.warp import transform_bounds

        raster_path = self.service.manager.get_raster_path(dataset_name)
        preview_path = self.raster_preview_path(dataset_name)
        preview_path.parent.mkdir(parents=True, exist_ok=True)

        if not preview_path.exists() or preview_path.stat().st_mtime < raster_path.stat().st_mtime:
            with rasterio.open(raster_path) as src:
                max_size = 1200
                scale = max(src.width / max_size, src.height / max_size, 1)
                out_width = max(1, int(src.width / scale))
                out_height = max(1, int(src.height / scale))
                data = src.read(1, out_shape=(out_height, out_width), masked=True)
                masked = np.ma.asarray(data)
                arr = np.asarray(masked.data, dtype="float32")
                mask = np.ma.getmaskarray(masked)
                if mask.any():
                    arr[mask] = np.nan
                valid = np.isfinite(arr)
                rgba = np.zeros((out_height, out_width, 4), dtype=np.uint8)
                if valid.any():
                    lo, hi = np.nanpercentile(arr[valid], [2, 98])
                    if hi <= lo:
                        hi = lo + 1
                    norm = np.clip((arr - lo) / (hi - lo), 0, 1)
                    norm = np.where(valid, norm, 0)
                    rgba[..., 0] = (32 + 210 * norm).astype(np.uint8)
                    rgba[..., 1] = (96 + 120 * norm).astype(np.uint8)
                    rgba[..., 2] = (180 - 140 * norm).astype(np.uint8)
                    rgba[..., 3] = np.where(valid, 190, 0).astype(np.uint8)
                Image.fromarray(rgba, mode="RGBA").save(preview_path)

        with rasterio.open(raster_path) as src:
            bounds = tuple(src.bounds)
            crs = _crs_text(src.crs)
            if src.crs:
                bounds = transform_bounds(src.crs, "EPSG:4326", *bounds, densify_pts=21)
            raster_meta = {
                "crs": crs,
                "width": int(src.width),
                "height": int(src.height),
                "band_count": int(src.count),
                "dtype": str(src.dtypes[0]) if src.dtypes else "",
                "nodata": src.nodata,
            }
        params = {"dataset_name": dataset_name}
        if str(user_id or "").strip():
            params["user_id"] = str(user_id or "").strip()
        if str(session_id or "").strip():
            params["session_id"] = str(session_id or "").strip()
        return {
            "preview_path": str(preview_path),
            "preview_url": f"/api/map/raster-preview?{urlencode(params)}",
            "bounds": [float(v) for v in bounds],
            "meta": raster_meta,
        }

    def read_vector_for_map(self, path: Path):
        import geopandas as gpd

        if path.suffix.lower() == ".zip":
            with ZipFile(path) as archive:
                shp_names = [name for name in archive.namelist() if name.lower().endswith(".shp")]
                if not shp_names:
                    raise FileNotFoundError(f"zip archive has no shapefile: {path}")
                shp_name = sorted(shp_names, key=lambda item: ("/" in item, item))[0]
                with tempfile.TemporaryDirectory(prefix="gis-agent-map-vector-") as temp_dir:
                    safe_extract_zip(archive, Path(temp_dir))
                    return gpd.read_file(Path(temp_dir) / shp_name)
        return gpd.read_file(path)

    def vector_map_layer(
        self,
        name: str,
        gdf: Any,
        *,
        layer_id: str = "",
        kind: str = "",
        meta: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
        dataset_name: str = "",
    ) -> dict[str, Any] | None:
        if gdf.empty:
            return None
        original_crs = _crs_text(gdf.crs)
        geometry_type = ""
        try:
            geometry_type = str(gdf.geometry.geom_type.dropna().iloc[0])
        except Exception:
            geometry_type = ""
        if gdf.crs:
            gdf = gdf.to_crs("EPSG:4326")
        feature_count_total = int(len(gdf))
        if len(gdf) > 5000:
            gdf = gdf.head(5000)
        artifact_id = str((artifact or {}).get("artifact_id") or "")
        layer_meta = _merge_meta(meta, (artifact or {}).get("meta") if isinstance((artifact or {}).get("meta"), dict) else None)
        layer_meta.update(
            {
                "dataset_name": dataset_name or name,
                "artifact_id": artifact_id,
                "map_ready": True,
                "crs": original_crs,
                "geometry_type": geometry_type,
                "feature_count": feature_count_total,
            }
        )
        return {
            "id": layer_id or f"dataset_{safe_layer_id(dataset_name or name)}",
            "name": name,
            "dataset_name": dataset_name or name,
            "artifact_id": artifact_id,
            "type": "vector",
            "kind": kind or dataset_map_kind(name, "vector"),
            "bounds": [float(v) for v in gdf.total_bounds.tolist()],
            "feature_count": feature_count_total,
            "geojson": json.loads(gdf.to_json()),
            "map_ready": True,
            "meta": layer_meta,
        }

    def dataset_layer(self, item: dict[str, Any], artifact: dict[str, Any] | None = None, user_id: str = "", session_id: str = "") -> dict[str, Any] | None:
        name = str(item.get("name") or "")
        data_type = str(item.get("type") or "")
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        if data_type == "vector":
            gdf = self.service.manager.get_vector(name)
            return self.vector_map_layer(
                name,
                gdf,
                layer_id=f"dataset_{safe_layer_id(name)}",
                kind=str(meta.get("layer_kind") or dataset_map_kind(name, data_type)),
                meta=meta,
                artifact=artifact,
                dataset_name=name,
            )
        if data_type == "raster":
            preview = self.ensure_raster_preview(name, user_id=user_id, session_id=session_id)
            artifact_id = str((artifact or {}).get("artifact_id") or "")
            layer_meta = _merge_meta(meta, preview.get("meta"), (artifact or {}).get("meta") if isinstance((artifact or {}).get("meta"), dict) else None)
            layer_meta.update(
                {
                    "dataset_name": name,
                    "artifact_id": artifact_id,
                    "map_ready": True,
                    "bounds": preview["bounds"],
                }
            )
            return {
                "id": f"dataset_{safe_layer_id(name)}",
                "name": name,
                "dataset_name": name,
                "artifact_id": artifact_id,
                "type": "raster",
                "kind": str(meta.get("layer_kind") or dataset_map_kind(name, data_type)),
                "bounds": preview["bounds"],
                "preview_url": preview["preview_url"],
                "map_ready": True,
                "meta": layer_meta,
            }
        return None

    def artifact_image_layer(self, artifact: dict[str, Any]) -> dict[str, Any] | None:
        path = Path(str(artifact.get("path") or ""))
        if path.suffix.lower() not in SPATIAL_IMAGE_EXTS:
            return None
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        bounds = meta.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            return None
        artifact_id = str(artifact.get("artifact_id") or "")
        layer_id = str(meta.get("map_layer_id") or f"artifact_{safe_layer_id(artifact_id or path.stem)}")
        return {
            "id": layer_id,
            "name": str(artifact.get("title") or artifact.get("name") or path.name),
            "dataset_name": str(meta.get("dataset_name") or ""),
            "artifact_id": artifact_id,
            "type": "raster",
            "kind": str(meta.get("layer_kind") or "image"),
            "bounds": [float(v) for v in bounds],
            "preview_url": str(artifact.get("download_url") or ""),
            "map_ready": True,
            "meta": _merge_meta(meta, {"artifact_id": artifact_id, "map_ready": True}),
        }

    def artifact_spatial_layer(self, artifact: dict[str, Any], user_id: str = "", session_id: str = "") -> dict[str, Any] | None:
        path = Path(str(artifact.get("path") or ""))
        suffix = path.suffix.lower()
        if suffix not in MAP_DISPLAYABLE_EXTS or not path.exists() or not path.is_file():
            return None
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        dataset_name = str(meta.get("dataset_name") or artifact.get("dataset_id") or "").strip()
        if dataset_name:
            try:
                self.service.manager.get(dataset_name)
            except Exception:
                dataset_name = ""
        if not dataset_name:
            dataset_name = self.service.manager.find_dataset_by_path(path)
        if not dataset_name:
            if suffix in RASTER_EXTS:
                dataset_name = self.service.manager.register_raster_reference(
                    path,
                    name=path.stem,
                    meta={"source": "artifact_reference", "artifact_id": str(artifact.get("artifact_id") or "")},
                )
            else:
                dataset_name = self.service.manager.load_path(str(path), name=path.stem)
        dataset = next((item for item in self.service.manager.list_datasets() if item.get("name") == dataset_name), None)
        if not dataset:
            return None
        layer = self.dataset_layer(dataset, artifact=artifact, user_id=user_id, session_id=session_id)
        if not layer:
            return None
        refreshed_meta = _merge_meta(
            meta,
            layer.get("meta") if isinstance(layer.get("meta"), dict) else {},
            {
                "map_ready": True,
                "dataset_name": dataset_name,
                "map_layer_id": layer["id"],
                "layer_kind": layer["kind"],
                "bounds": layer.get("bounds"),
            },
        )
        refreshed = self.service.manager.register_artifact(
            artifact_id=str(artifact.get("artifact_id") or ""),
            path=str(path),
            type=str(artifact.get("type") or suffix.lstrip(".")),
            title=str(artifact.get("title") or artifact.get("name") or path.name),
            description=str(artifact.get("description") or ""),
            quality_status=str(artifact.get("quality_status") or "unchecked"),
            preview_available=bool(artifact.get("preview_available") or layer.get("preview_url")),
            task_id=str(artifact.get("task_id") or ""),
            model_result_id=str(artifact.get("model_result_id") or ""),
            dataset_id=dataset_name,
            meta=refreshed_meta,
        )
        return self.dataset_layer(dataset, artifact=refreshed, user_id=user_id, session_id=session_id)

    def workspace_layers(self, user_id: str = "", session_id: str = "") -> dict[str, Any]:
        artifacts = self.service.manager.list_artifacts()
        artifacts_by_path = _artifact_path_index(artifacts)
        artifacts_by_dataset = _artifact_dataset_index(artifacts)
        layers: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        seen_download_datasets: set[str] = set()
        for item in self.service.manager.list_datasets():
            name = str(item.get("name") or "")
            dedupe_key = _download_dataset_dedupe_key(item)
            if dedupe_key:
                if dedupe_key in seen_download_datasets:
                    continue
                seen_download_datasets.add(dedupe_key)
            artifact = artifacts_by_dataset.get(name)
            if artifact is None:
                try:
                    artifact = artifacts_by_path.get(str(Path(str(item.get("path") or "")).resolve()))
                except Exception:
                    artifact = None
            try:
                layer = self.dataset_layer(item, artifact=artifact, user_id=user_id, session_id=session_id)
            except Exception as exc:
                diagnostics.append({"dataset_name": name, "error": str(exc)})
                continue
            if layer:
                layers.append(layer)

        dataset_layer_ids = {layer.get("id") for layer in layers}
        for artifact in artifacts:
            if _is_download_artifact_without_map_binding(artifact):
                continue
            meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
            layer_id = str(meta.get("map_layer_id") or "")
            if layer_id and layer_id in dataset_layer_ids:
                continue
            try:
                spatial_layer = self.artifact_spatial_layer(artifact, user_id=user_id, session_id=session_id)
            except Exception as exc:
                diagnostics.append({"artifact_id": artifact.get("artifact_id"), "path": artifact.get("path"), "error": str(exc)})
                spatial_layer = None
            if spatial_layer:
                if spatial_layer.get("id") not in dataset_layer_ids:
                    layers.append(spatial_layer)
                    dataset_layer_ids.add(spatial_layer.get("id"))
                continue
            image_layer = self.artifact_image_layer(artifact)
            if image_layer:
                layers.append(image_layer)

        if not any(_is_shandian_boundary_layer(layer) for layer in layers):
            fallback = self.local_shandian_boundary_layer()
            if fallback:
                layers.insert(0, fallback)

        deduped_layers: list[dict[str, Any]] = []
        seen_layer_downloads: set[str] = set()
        for layer in layers:
            key = _layer_download_dedupe_key(layer)
            if key:
                if key in seen_layer_downloads:
                    continue
                seen_layer_downloads.add(key)
            deduped_layers.append(layer)

        return {"layers": _dedupe_boundary_layers(deduped_layers), "diagnostics": diagnostics}

    def refresh_artifact(self, artifact_id: str, user_id: str = "", session_id: str = "") -> dict[str, Any]:
        artifact = self.service.manager.get_artifact(artifact_id)
        if not artifact:
            raise FileNotFoundError(f"artifact not found: {artifact_id}")
        path = Path(str(artifact.get("path") or ""))
        suffix = path.suffix.lower()
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        dataset_name = str(meta.get("dataset_name") or "").strip()
        if not dataset_name:
            dataset_name = self.service.manager.find_dataset_by_path(path)
        if not dataset_name and suffix in VECTOR_EXTS.union(RASTER_EXTS):
            if suffix in RASTER_EXTS:
                dataset_name = self.service.manager.register_raster_reference(
                    path,
                    name=path.stem,
                    meta={"source": "artifact_reference", "artifact_id": artifact_id},
                )
            else:
                dataset_name = self.service.manager.load_path(str(path), name=path.stem)
        if not dataset_name and suffix in SPATIAL_IMAGE_EXTS and isinstance(meta.get("bounds"), list):
            layer_id = str(meta.get("map_layer_id") or f"artifact_{safe_layer_id(artifact_id)}")
            refreshed_meta = _merge_meta(meta, {"map_ready": True, "map_layer_id": layer_id, "layer_kind": meta.get("layer_kind") or "image"})
            self.service.manager.register_artifact(
                artifact_id=artifact_id,
                path=str(path),
                type=str(artifact.get("type") or suffix.lstrip(".")),
                title=str(artifact.get("title") or artifact.get("name") or path.name),
                description=str(artifact.get("description") or ""),
                quality_status=str(artifact.get("quality_status") or "unchecked"),
                preview_available=bool(artifact.get("preview_available")),
                task_id=str(artifact.get("task_id") or ""),
                model_result_id=str(artifact.get("model_result_id") or ""),
                dataset_id=str(artifact.get("dataset_id") or ""),
                meta=refreshed_meta,
            )
            return {"artifact_id": artifact_id, "dataset_name": "", "map_layer_id": layer_id, "map_ready": True}
        if not dataset_name:
            raise ValueError(f"artifact is not map-ready: {artifact_id}")

        dataset = next((item for item in self.service.manager.list_datasets() if item.get("name") == dataset_name), None)
        if not dataset:
            raise ValueError(f"dataset not found after artifact refresh: {dataset_name}")
        layer = self.dataset_layer(dataset, artifact=artifact, user_id=user_id, session_id=session_id)
        if not layer:
            raise ValueError(f"artifact produced no map layer: {artifact_id}")
        refreshed_meta = _merge_meta(
            meta,
            layer.get("meta") if isinstance(layer.get("meta"), dict) else {},
            {
                "map_ready": True,
                "dataset_name": dataset_name,
                "map_layer_id": layer["id"],
                "layer_kind": layer["kind"],
                "bounds": layer.get("bounds"),
            },
        )
        self.service.manager.register_artifact(
            artifact_id=artifact_id,
            path=str(path),
            type=str(artifact.get("type") or suffix.lstrip(".")),
            title=str(artifact.get("title") or artifact.get("name") or path.name),
            description=str(artifact.get("description") or ""),
            quality_status=str(artifact.get("quality_status") or "unchecked"),
            preview_available=bool(artifact.get("preview_available") or layer.get("preview_url")),
            task_id=str(artifact.get("task_id") or ""),
            model_result_id=str(artifact.get("model_result_id") or ""),
            dataset_id=dataset_name,
            meta=refreshed_meta,
        )
        return {
            "artifact_id": artifact_id,
            "dataset_name": dataset_name,
            "map_layer_id": layer["id"],
            "map_ready": True,
            "layer": layer,
        }
