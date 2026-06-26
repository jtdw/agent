from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import shutil
import warnings
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree as ET

import geopandas as gpd
import pandas as pd
import rasterio

from .archive_utils import safe_extract_zip
from .data_quality import validate_output_artifact, validate_zip_upload
from .model_results import MODEL_ARTIFACT_SCHEMA_VERSION, MODEL_RESULT_SCHEMA_VERSION, generate_model_result_id
from .workspace_db import WorkspaceDatabase


VECTOR_EXTS = {".shp", ".geojson", ".gpkg", ".json", ".kml"}
RASTER_EXTS = {".tif", ".tiff", ".img"}
TABLE_EXTS = {".csv", ".xlsx", ".xls"}
DOCUMENT_EXTS = {".docx", ".txt", ".md"}
SHAPE_SIDE_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix"}
ZIP_DATASET_PATTERNS = [
    "*.shp", "*.gpkg", "*.geojson", "*.json", "*.kml",
    "*.csv", "*.xlsx", "*.xls",
    "*.tif", "*.tiff", "*.img",
    "*.docx", "*.txt", "*.md",
]
ZIP_DATASET_EXTS = VECTOR_EXTS | RASTER_EXTS | TABLE_EXTS | DOCUMENT_EXTS


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    return safe_extract_zip(zf, target_dir)


def _safe_output_filename(filename: str, fallback: str, allowed_suffixes: set[str]) -> str:
    candidate = Path(str(filename or "").strip()).name or fallback
    stem = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", Path(candidate).stem).strip("._-")
    suffix = Path(candidate).suffix.lower()
    fallback_suffix = Path(fallback).suffix.lower()
    if suffix not in allowed_suffixes:
        suffix = fallback_suffix if fallback_suffix in allowed_suffixes else sorted(allowed_suffixes)[0]
    return f"{stem or Path(fallback).stem}{suffix}"


def _read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_station_series_table(path: Path) -> pd.DataFrame | None:
    text = _read_text_with_fallback(path)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    rows: list[dict[str, Any]] = []
    date_re = re.compile(r"^\d{4}[/.-]\d{1,2}[/.-]\d{1,2}$")
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 3 or not date_re.match(parts[0]):
            continue
        try:
            value: Any = float(parts[2])
        except Exception:
            value = parts[2]
        rows.append(
            {
                "date": parts[0],
                "time": parts[1] if len(parts) > 1 else "",
                "value": value,
                "quality_flags": parts[3] if len(parts) > 3 else "",
                "mode": parts[4] if len(parts) > 4 else "",
            }
        )

    if not rows:
        return None
    return pd.DataFrame(rows, columns=["date", "time", "value", "quality_flags", "mode"])


def _read_csv_table(path: Path) -> pd.DataFrame:
    def read_csv_with_encoding(**options: Any) -> pd.DataFrame:
        last_exc: Exception | None = None
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return pd.read_csv(path, encoding=encoding, **options)
            except UnicodeDecodeError as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            return pd.read_csv(path, encoding="utf-8", encoding_errors="replace", **options)
        return pd.read_csv(path, encoding="utf-8-sig", **options)

    try:
        return read_csv_with_encoding()
    except pd.errors.ParserError as exc:
        station_df = _read_station_series_table(path)
        if station_df is not None:
            return station_df

        for options in (
            {"sep": None, "engine": "python"},
            {"sep": r"\s+", "engine": "python"},
        ):
            try:
                return read_csv_with_encoding(**options)
            except Exception:
                continue
        raise ValueError(
            f"CSV 文件 {path.name} 不是标准逗号分隔格式，自动尝试空白分隔和站点时序解析仍失败。"
        ) from exc


@dataclass
class DatasetRecord:
    name: str
    path: Path
    data_type: str
    object_ref: Any
    meta: dict[str, Any] = field(default_factory=dict)


class DataManager:
    def __init__(self, workdir: Path):
        self.workdir = Path(workdir)
        self.base_upload_dir = self.workdir / "uploads"
        self.base_plot_dir = self.workdir / "plots"
        self.base_derived_dir = self.workdir / "derived"
        self.base_temp_dir = self.workdir / "temp"
        self.current_user_id = ""
        self.current_session_id = ""
        self.upload_dir = self.base_upload_dir
        self.plot_dir = self.base_plot_dir
        self.derived_dir = self.base_derived_dir
        self.temp_dir = self.base_temp_dir
        self.datasets: dict[str, DatasetRecord] = {}
        self.database = WorkspaceDatabase(self.workdir / "workspace.db")
        self.last_plot_path: str = ""
        self.operation_log: list[dict[str, Any]] = []

        for folder in [self.base_upload_dir, self.base_plot_dir, self.base_derived_dir, self.base_temp_dir]:
            folder.mkdir(parents=True, exist_ok=True)

        self._restore_workspace_state()

    def set_runtime_scope(self, user_id: str = "", session_id: str = "") -> None:
        self.current_user_id = str(user_id or "").strip()
        self.current_session_id = str(session_id or "").strip()
        if self.current_session_id:
            root = self.workdir / "sessions" / re.sub(r"[^A-Za-z0-9_.-]+", "_", self.current_session_id)
            self.upload_dir = root / "uploads"
            self.plot_dir = root / "plots"
            self.derived_dir = root / "derived"
            self.temp_dir = root / "temp"
        else:
            self.upload_dir = self.base_upload_dir
            self.plot_dir = self.base_plot_dir
            self.derived_dir = self.base_derived_dir
            self.temp_dir = self.base_temp_dir
        for folder in [self.upload_dir, self.plot_dir, self.derived_dir, self.temp_dir]:
            folder.mkdir(parents=True, exist_ok=True)

    def _scoped_meta(self, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(meta or {})
        if self.current_user_id:
            payload.setdefault("owner_user_id", self.current_user_id)
        if self.current_session_id:
            payload.setdefault("session_id", self.current_session_id)
        return payload

    def _record_visible_in_current_session(self, record: DatasetRecord) -> bool:
        if not self.current_session_id:
            return True
        return str((record.meta or {}).get("session_id") or "") == self.current_session_id

    def _artifact_visible_in_current_session(self, artifact: dict[str, Any]) -> bool:
        if artifact.get("is_deleted"):
            return False
        if not self.current_session_id:
            return True
        return str(artifact.get("session_id") or (artifact.get("meta") or {}).get("session_id") or "") == self.current_session_id

    def _scoped_relative_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workdir.resolve())).replace("\\", "/")
        except Exception:
            return path.name

    def _resolve_workspace_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        raw = str(path or "").replace("\\", "/")
        parts = [part for part in raw.split("/") if part]
        if "sessions" in parts:
            index = parts.index("sessions")
            if index + 1 < len(parts) and (not self.current_session_id or parts[index + 1] == self.current_session_id):
                return self.workdir / Path(*parts[index:])
        if "users" in parts:
            index = parts.index("users")
            if index + 1 < len(parts) and parts[index + 1] == self.workdir.name:
                suffix = parts[index + 2 :]
                if suffix:
                    return self.workdir / Path(*suffix)
        return self.workdir / candidate

    def _unique_storage_name(self, filename: str) -> str:
        original = Path(str(filename or "uploaded.bin")).name
        stem = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", Path(original).stem).strip("._-") or "uploaded"
        suffix = Path(original).suffix.lower()
        return f"{uuid4().hex}_{stem}{suffix}"

    def _restore_workspace_state(self) -> None:
        self.operation_log = self.database.list_operations(limit=100)
        for item in reversed(self.database.list_catalog()):
            try:
                self._restore_dataset_from_catalog(item)
            except Exception as exc:
                self.operation_log.insert(
                    0,
                    {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "title": f"恢复数据集失败 {item.get('dataset_name', '')}",
                        "detail": str(exc),
                        "category": "restore",
                    },
                )
        self.operation_log = self.operation_log[:100]
        images = [item["path"] for item in self.list_artifacts() if Path(item["path"]).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
        if images:
            self.last_plot_path = images[0]

    def _restore_dataset_from_catalog(self, item: dict[str, Any]) -> None:
        dataset_name = item["dataset_name"]
        data_type = item["data_type"]
        path = Path(item["path"])
        if not path.exists():
            return

        if data_type == "vector":
            actual = self._prepare_vector_source(path)
            gdf = gpd.read_file(actual)
            self.datasets[dataset_name] = DatasetRecord(dataset_name, actual, "vector", gdf, self._scoped_meta({**self._build_vector_meta(gdf), **(item.get("meta") or {})}))
        elif data_type == "raster":
            with rasterio.open(path) as src:
                meta = {
                    "width": src.width,
                    "height": src.height,
                    "count": src.count,
                    "crs": str(src.crs) if src.crs else None,
                    "bounds": tuple(src.bounds),
                    "dtype": str(src.dtypes[0]) if src.dtypes else None,
                    "nodata": src.nodata,
                }
            self.datasets[dataset_name] = DatasetRecord(dataset_name, path, "raster", str(path), self._scoped_meta({**meta, **(item.get("meta") or {})}))
        elif data_type == "table":
            if path.suffix.lower() == ".csv":
                df = _read_csv_table(path)
            else:
                df = pd.read_excel(path)
            self.datasets[dataset_name] = DatasetRecord(dataset_name, path, "table", df, self._scoped_meta({"rows": len(df), "columns": list(df.columns), **(item.get("meta") or {})}))
        elif data_type == "document":
            if path.suffix.lower() == ".docx":
                text = self._read_docx_text(path)
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
            self.datasets[dataset_name] = DatasetRecord(dataset_name, path, "document", text, self._scoped_meta({**self._build_document_meta(text), **(item.get("meta") or {})}))

    def log_operation(self, title: str, detail: str = "", category: str = "info") -> None:
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "title": title,
            "detail": detail,
            "category": category,
        }
        self.operation_log.insert(0, entry)
        self.operation_log = self.operation_log[:100]
        self.database.log_operation(title, detail, category)

    def _unique_name(self, preferred: str) -> str:
        preferred = preferred.strip().replace(" ", "_")
        if preferred and preferred not in self.datasets:
            return preferred
        base = preferred or "dataset"
        index = 1
        while f"{base}_{index}" in self.datasets:
            index += 1
        return f"{base}_{index}"

    def _local_library_roots(self) -> list[Path]:
        roots: list[Path] = []
        env_root = os.getenv("GIS_AGENT_LOCAL_LIBRARY_DIR", "").strip()
        if env_root:
            roots.append(Path(env_root).expanduser())
        roots.extend([
            self.workdir / "local_library",
            self.workdir.parent / "local_library",
            Path.cwd() / "local_library",
        ])
        for parent in self.workdir.parents:
            roots.append(parent / "local_library")

        resolved: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            try:
                actual = root.resolve()
            except Exception:
                actual = root
            key = str(actual).lower()
            if key not in seen:
                seen.add(key)
                resolved.append(actual)
        return resolved

    def _resolve_local_library_reference(self, file_path: str) -> Path | None:
        """Resolve accidental local-library item ids passed as file paths.

        The agent sees manifest ids such as lib_china_admin_province_city_county_shp
        in context and may pass them to load_dataset instead of the real zip path.
        """
        raw = str(file_path or "").strip()
        if not raw:
            return None
        candidate = Path(raw)
        key = candidate.name if candidate.name.startswith("lib_") else raw
        if not key.startswith("lib_"):
            return None

        for root in self._local_library_roots():
            manifest_path = root / "library_manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for item in manifest.get("items", []):
                if item.get("item_id") != key:
                    continue
                rel_path = str(item.get("path") or "")
                if not rel_path:
                    continue
                target = (root / rel_path).resolve()
                try:
                    target.relative_to(root.resolve())
                except Exception:
                    continue
                if target.exists():
                    return target
        return None

    def _copy_to_uploads(self, source: Path) -> Path:
        source = Path(source)
        try:
            source.resolve().relative_to(self.upload_dir.resolve())
            return source
        except Exception:
            pass
        storage_name = self._unique_storage_name(source.name)
        target = self.upload_dir / storage_name

        if source.suffix.lower() == ".shp":
            target_stem = target.stem
            for sibling in source.parent.glob(f"{source.stem}.*"):
                if sibling.suffix.lower() in SHAPE_SIDE_EXTS:
                    dest = self.upload_dir / f"{target_stem}{sibling.suffix.lower()}"
                    if sibling.resolve() != dest.resolve():
                        shutil.copy2(sibling, dest)
            return target

        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target

    def _allowed_import_roots(self) -> list[Path]:
        roots = [self.workdir]
        local_library = os.getenv("GIS_AGENT_LOCAL_LIBRARY_DIR", "").strip()
        if local_library:
            roots.append(Path(local_library).expanduser())
        roots.append(self.workdir.parent / "local_library")
        return [root.resolve() for root in roots]

    def _require_allowed_import_source(self, source: Path) -> None:
        if os.getenv("GIS_AGENT_ALLOW_ABSOLUTE_IMPORTS", "").strip().lower() in {"1", "true", "yes", "on"}:
            return
        resolved = source.resolve()
        for root in self._allowed_import_roots():
            try:
                resolved.relative_to(root)
                return
            except ValueError:
                continue
        raise PermissionError("Local file imports are restricted to the workspace or configured local library.")

    def _zip_dataset_candidates(self, target_dir: Path) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()
        for pattern in ZIP_DATASET_PATTERNS:
            for match in sorted(target_dir.rglob(pattern)):
                if not match.is_file() or match.suffix.lower() not in ZIP_DATASET_EXTS:
                    continue
                key = str(match.resolve(strict=False)).lower()
                if key not in seen:
                    seen.add(key)
                    candidates.append(match)
        return candidates

    def inspect_zip_datasets(self, file_path: str) -> list[dict[str, Any]]:
        path = Path(file_path)
        if not path.exists():
            resolved = self._resolve_local_library_reference(file_path)
            if resolved is None:
                raise FileNotFoundError(f"文件不存在: {file_path}")
            path = resolved
        if path.suffix.lower() != ".zip":
            raise ValueError("inspect_zip_datasets only supports .zip files")
        self._require_allowed_import_source(path)
        copied = self._copy_to_uploads(path)
        target_dir = self.upload_dir / copied.stem
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(copied, "r") as zf:
            _safe_extract_zip(zf, target_dir)
        root = target_dir.resolve()
        out: list[dict[str, Any]] = []
        for item in self._zip_dataset_candidates(target_dir):
            rel = str(item.resolve(strict=False).relative_to(root)).replace("\\", "/")
            out.append({"member": rel, "name": item.name, "suffix": item.suffix.lower()})
        return out

    def _extract_zip_if_needed(self, path: Path, zip_member: str = "") -> Path:
        if path.suffix.lower() != ".zip":
            return path
        zip_quality = validate_zip_upload(path)
        if not zip_quality.get("ok"):
            raise ValueError(str(zip_quality.get("user_message") or zip_quality.get("error_code") or "Invalid ZIP archive"))
        target_dir = self.upload_dir / path.stem
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "r") as zf:
            _safe_extract_zip(zf, target_dir)

        root = target_dir.resolve()
        if str(zip_member or "").strip():
            selected = (root / str(zip_member).replace("\\", "/")).resolve(strict=False)
            try:
                selected.relative_to(root)
            except ValueError as exc:
                raise PermissionError("zip_member is outside the extracted archive.") from exc
            if not selected.exists() or not selected.is_file():
                raise FileNotFoundError(f"zip member not found: {zip_member}")
            if selected.suffix.lower() not in ZIP_DATASET_EXTS:
                raise ValueError(f"zip member is not a supported dataset: {zip_member}")
            return selected

        matches = self._zip_dataset_candidates(target_dir)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            labels = [str(item.resolve(strict=False).relative_to(root)).replace("\\", "/") for item in matches[:20]]
            raise ValueError("multiple dataset candidates in zip; choose an explicit zip_member: " + ", ".join(labels))
        raise ValueError(f"压缩包 {path.name} 中没有找到可加载的数据文件")

    def _read_docx_text(self, path: Path) -> str:
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with zipfile.ZipFile(path, "r") as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        paragraphs: list[str] = []
        for p in root.findall(".//w:p", ns):
            texts = [node.text for node in p.findall(".//w:t", ns) if node.text]
            line = "".join(texts).strip()
            if line:
                paragraphs.append(line)
        return "\n".join(paragraphs)

    def save_uploaded_bytes(self, filename: str, data: bytes) -> Path:
        target = self.upload_dir / self._unique_storage_name(filename)
        target.write_bytes(data)
        return target

    def _prepare_vector_source(self, actual: Path) -> Path:
        if actual.suffix.lower() != ".shp":
            return actual

        os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")
        dbf_path = actual.with_suffix(".dbf")
        if not dbf_path.exists():
            raise ValueError(
                f"{actual.name} 缺少同名 .dbf 文件。Shapefile 需要至少包含 .shp + .dbf，"
                "建议上传包含 .shp/.shx/.dbf/.prj/.cpg 的 zip 包，或一次性上传完整配套文件。"
            )
        return actual

    def _build_vector_meta(self, gdf: gpd.GeoDataFrame) -> dict[str, Any]:
        return {
            "rows": len(gdf),
            "columns": list(gdf.columns),
            "crs": str(gdf.crs) if gdf.crs else None,
            "geometry_types": sorted({str(v) for v in gdf.geometry.geom_type.dropna().unique()}) if "geometry" in gdf else [],
            "bounds": tuple(gdf.total_bounds.tolist()) if not gdf.empty else None,
        }

    def _build_document_meta(self, text: str) -> dict[str, Any]:
        lines = [line for line in text.splitlines() if line.strip()]
        words = len(text.split())
        return {
            "characters": len(text),
            "lines": len(lines),
            "words": words,
            "preview": text[:200],
        }

    def load_path(self, file_path: str, name: str | None = None, original_filename: str = "", zip_member: str = "") -> str:
        source = Path(file_path)
        if not source.exists():
            resolved = self._resolve_local_library_reference(file_path)
            if resolved is None:
                raise FileNotFoundError(f"文件不存在: {file_path}")
            source = resolved
        self._require_allowed_import_source(source)
        copied = self._copy_to_uploads(source)
        actual = self._extract_zip_if_needed(copied, zip_member=zip_member)
        dataset_name = self._unique_name(name or actual.stem)
        ext = actual.suffix.lower()
        original_name = Path(str(original_filename or source.name)).name
        original_meta = {"original_filename": original_name} if original_name else {}

        if ext in VECTOR_EXTS:
            actual = self._prepare_vector_source(actual)
            gdf = gpd.read_file(actual)
            self.datasets[dataset_name] = DatasetRecord(
                name=dataset_name,
                path=actual,
                data_type="vector",
                object_ref=gdf,
                meta=self._scoped_meta({**self._build_vector_meta(gdf), **original_meta}),
            )
        elif ext in RASTER_EXTS:
            with rasterio.open(actual) as src:
                meta = {
                    "width": src.width,
                    "height": src.height,
                    "count": src.count,
                    "crs": str(src.crs) if src.crs else None,
                    "bounds": tuple(src.bounds),
                    "dtype": str(src.dtypes[0]) if src.dtypes else None,
                    "nodata": src.nodata,
                    **original_meta,
                }
            self.datasets[dataset_name] = DatasetRecord(
                name=dataset_name,
                path=actual,
                data_type="raster",
                object_ref=str(actual),
                meta=self._scoped_meta(meta),
            )
        elif ext in TABLE_EXTS:
            if ext == ".csv":
                df = _read_csv_table(actual)
            else:
                df = pd.read_excel(actual)
            self.datasets[dataset_name] = DatasetRecord(
                name=dataset_name,
                path=actual,
                data_type="table",
                object_ref=df,
                meta=self._scoped_meta({"rows": len(df), "columns": list(df.columns), **original_meta}),
            )
        elif ext in DOCUMENT_EXTS:
            if ext == ".docx":
                text = self._read_docx_text(actual)
            else:
                text = actual.read_text(encoding="utf-8", errors="ignore")
            self.datasets[dataset_name] = DatasetRecord(
                name=dataset_name,
                path=actual,
                data_type="document",
                object_ref=text,
                meta=self._scoped_meta({**self._build_document_meta(text), **original_meta}),
            )
        else:
            raise ValueError(f"暂不支持的文件类型: {ext}")

        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        self.log_operation(
            title=f"加载数据集 {dataset_name}",
            detail=f"来源: {actual.name} | 类型: {self.datasets[dataset_name].data_type}",
            category="load",
        )
        return dataset_name

    def list_datasets(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "type": record.data_type,
                "path": str(record.path),
                "meta": record.meta,
            }
            for name, record in self.datasets.items()
            if self._record_visible_in_current_session(record)
        ]

    def list_dataset_names(self) -> list[str]:
        return [name for name, record in self.datasets.items() if self._record_visible_in_current_session(record)]

    def dataset_brief(self) -> str:
        if not self.datasets:
            return "当前没有已加载的数据集。"
        return json.dumps(self.list_datasets(), ensure_ascii=False, indent=2)

    def workspace_summary(self) -> dict[str, Any]:
        return {
            "dataset_count": len(self.list_datasets()),
            "artifact_count": len(self.list_artifacts()),
            "last_plot": self.last_plot_path,
            "operation_count": len(self.operation_log),
        }

    def result_file_paths(self) -> list[Path]:
        files: list[Path] = []
        for folder in [self.plot_dir, self.derived_dir]:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                if path.is_file():
                    files.append(path)
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def _path_is_download_result_copy(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.derived_dir.resolve())
        except Exception:
            return False
        parts = [part.lower() for part in relative.parts]
        return len(parts) >= 3 and parts[0] == "downloads"

    def _filter_visible_artifact_duplicates(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for item in items:
            path = Path(str(item.get("path") or ""))
            artifact_id = str(item.get("artifact_id") or "")
            if self._path_is_download_result_copy(path) and not artifact_id.startswith("artifact_job_"):
                continue
            filtered.append(item)
        return filtered

    def list_artifacts(self) -> list[dict[str, Any]]:
        registered = self._filter_visible_artifact_duplicates(self.list_registered_artifacts(limit=200))
        seen_paths = {str(Path(item.get("path", "")).resolve()) for item in registered if item.get("path")}
        artifacts: list[dict[str, Any]] = []
        root_to_category = {
            self.plot_dir.resolve(): "plot",
            self.derived_dir.resolve(): "derived",
        }
        for path in self.result_file_paths()[:100]:
            try:
                resolved_path = str(path.resolve())
            except Exception:
                resolved_path = str(path)
            if resolved_path in seen_paths:
                continue
            if self._path_is_download_result_copy(path):
                continue
            try:
                relative = path.relative_to(path.parents[1])
            except Exception:
                relative = path.name
            parent_root = None
            for candidate in path.parents:
                if candidate.resolve() in root_to_category:
                    parent_root = candidate.resolve()
                    break
            category = root_to_category.get(parent_root, "derived")
            artifact_id = "artifact_" + hashlib.sha1(resolved_path.encode("utf-8", errors="ignore")).hexdigest()[:16]
            artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "name": path.name,
                    "path": str(path),
                    "absolute_path": str(path.resolve(strict=False)),
                    "relative_path": self._scoped_relative_path(path),
                    "owner_user_id": self.current_user_id,
                    "session_id": self.current_session_id,
                    "display_path": (str(relative).replace("\\", "/") if not isinstance(relative, str) else relative),
                    "category": category,
                    "size_kb": round(path.stat().st_size / 1024, 2),
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "meta": self._scoped_meta({}),
                }
            )
        return [item for item in registered + artifacts if self._artifact_visible_in_current_session(item)]

    def get(self, name: str) -> DatasetRecord:
        if name not in self.datasets:
            raise KeyError(f"未找到数据集: {name}")
        record = self.datasets[name]
        if not self._record_visible_in_current_session(record):
            raise PermissionError(f"dataset is outside the current session: {name}")
        return record

    def get_vector(self, name: str) -> gpd.GeoDataFrame:
        record = self.get(name)
        if record.data_type != "vector":
            raise TypeError(f"{name} 不是矢量数据")
        return record.object_ref.copy()

    def get_table(self, name: str) -> pd.DataFrame:
        record = self.get(name)
        if record.data_type != "table":
            raise TypeError(f"{name} 不是表格数据")
        return record.object_ref.copy()

    def get_document_text(self, name: str) -> str:
        record = self.get(name)
        if record.data_type != "document":
            raise TypeError(f"{name} 不是文档数据")
        return str(record.object_ref)

    def get_raster_path(self, name: str) -> Path:
        record = self.get(name)
        if record.data_type != "raster":
            raise TypeError(f"{name} 不是栅格数据")
        return Path(record.object_ref)

    def preview_table_rows(self, name: str, rows: int = 8) -> list[dict[str, Any]]:
        record = self.get(name)
        if record.data_type == "table":
            df = self.get_table(name)
        elif record.data_type == "vector":
            gdf = self.get_vector(name)
            df = pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))
        else:
            raise TypeError(f"{name} 不是表格或矢量属性数据")
        return df.head(rows).replace({pd.NA: None}).to_dict(orient="records")

    def preview_document(self, name: str, max_chars: int = 1500) -> str:
        text = self.get_document_text(name)
        return text[:max_chars]

    def rename_dataset(self, old_name: str, new_name: str) -> str:
        record = self.get(old_name)
        fresh_name = self._unique_name(new_name)
        if fresh_name == old_name:
            return fresh_name
        record.name = fresh_name
        self.datasets[fresh_name] = record
        del self.datasets[old_name]
        try:
            self.database.drop_dataset(old_name)
        except Exception:
            pass
        self._sync_dataset_to_database(fresh_name, auto_synced=True)
        self.log_operation("重命名数据集", f"{old_name} -> {fresh_name}", "manage")
        return fresh_name

    def put_vector(self, name: str, gdf: gpd.GeoDataFrame, filename: str | None = None) -> str:
        dataset_name = self._unique_name(name)
        filename = _safe_output_filename(filename or "", f"{dataset_name}.geojson", {".geojson", ".json"})
        output_path = self.derived_dir / filename
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r"'crs' was not provided.*", category=UserWarning)
            gdf.to_file(output_path, driver="GeoJSON")
        self.datasets[dataset_name] = DatasetRecord(
            name=dataset_name,
            path=output_path,
            data_type="vector",
            object_ref=gdf,
            meta=self._scoped_meta(self._build_vector_meta(gdf)),
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def put_table(self, name: str, df: pd.DataFrame, filename: str | None = None) -> str:
        dataset_name = self._unique_name(name)
        filename = _safe_output_filename(filename or "", f"{dataset_name}.csv", {".csv"})
        output_path = self.derived_dir / filename
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        self.datasets[dataset_name] = DatasetRecord(
            name=dataset_name,
            path=output_path,
            data_type="table",
            object_ref=df,
            meta=self._scoped_meta({"rows": len(df), "columns": list(df.columns)}),
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def put_text_document(self, name: str, text: str, filename: str | None = None) -> str:
        dataset_name = self._unique_name(name)
        filename = _safe_output_filename(filename or "", f"{dataset_name}.txt", {".txt", ".md"})
        output_path = self.derived_dir / filename
        output_path.write_text(text, encoding="utf-8")
        self.datasets[dataset_name] = DatasetRecord(
            name=dataset_name,
            path=output_path,
            data_type="document",
            object_ref=text,
            meta=self._scoped_meta(self._build_document_meta(text)),
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def put_raster_path(self, name: str, path: Path, meta: dict[str, Any] | None = None) -> str:
        dataset_name = self._unique_name(name)
        self.datasets[dataset_name] = DatasetRecord(
            name=dataset_name,
            path=path,
            data_type="raster",
            object_ref=str(path),
            meta=self._scoped_meta(meta or {}),
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def find_dataset_by_path(self, path: Path) -> str:
        target = Path(path).resolve(strict=False)
        for item in self.list_datasets():
            try:
                if Path(str(item.get("path") or "")).resolve(strict=False) == target:
                    return str(item.get("name") or "")
            except Exception:
                continue
        return ""

    def register_raster_reference(self, path: Path, name: str | None = None, meta: dict[str, Any] | None = None) -> str:
        source = Path(path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"raster artifact not found: {source}")
        self._require_allowed_import_source(source)
        existing = self.find_dataset_by_path(source)
        if existing:
            return existing
        with rasterio.open(source) as src:
            raster_meta = {
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "crs": str(src.crs) if src.crs else None,
                "bounds": tuple(src.bounds),
                "dtype": str(src.dtypes[0]) if src.dtypes else None,
                "nodata": src.nodata,
                "storage_mode": "reference",
            }
        dataset_name = self._unique_name(name or source.stem)
        self.datasets[dataset_name] = DatasetRecord(
            name=dataset_name,
            path=source,
            data_type="raster",
            object_ref=str(source),
            meta=self._scoped_meta({**raster_meta, **(meta or {})}),
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def register_vector_reference(self, path: Path, name: str | None = None, meta: dict[str, Any] | None = None) -> str:
        source = Path(path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"vector artifact not found: {source}")
        self._require_allowed_import_source(source)
        existing = self.find_dataset_by_path(source)
        if existing:
            return existing
        actual = self._prepare_vector_source(source)
        gdf = gpd.read_file(actual)
        dataset_name = self._unique_name(name or actual.stem)
        self.datasets[dataset_name] = DatasetRecord(
            name=dataset_name,
            path=actual,
            data_type="vector",
            object_ref=gdf,
            meta=self._scoped_meta({**self._build_vector_meta(gdf), "storage_mode": "reference", **(meta or {})}),
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def register_table_reference(self, path: Path, name: str | None = None, meta: dict[str, Any] | None = None) -> str:
        source = Path(path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"table artifact not found: {source}")
        self._require_allowed_import_source(source)
        existing = self.find_dataset_by_path(source)
        if existing:
            return existing
        ext = source.suffix.lower()
        df = _read_csv_table(source) if ext == ".csv" else pd.read_excel(source)
        dataset_name = self._unique_name(name or source.stem)
        self.datasets[dataset_name] = DatasetRecord(
            name=dataset_name,
            path=source,
            data_type="table",
            object_ref=df,
            meta=self._scoped_meta({"rows": len(df), "columns": list(df.columns), "storage_mode": "reference", **(meta or {})}),
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def register_dataset_reference(self, path: Path, name: str | None = None, meta: dict[str, Any] | None = None) -> str:
        source = Path(path)
        ext = source.suffix.lower()
        if ext in RASTER_EXTS:
            return self.register_raster_reference(source, name=name, meta=meta)
        if ext in VECTOR_EXTS:
            return self.register_vector_reference(source, name=name, meta=meta)
        if ext in TABLE_EXTS:
            return self.register_table_reference(source, name=name, meta=meta)
        return self.load_path(str(source), name=name)

    def _sync_dataset_to_database(self, name: str, auto_synced: bool = True) -> dict[str, Any]:
        record = self.get(name)
        if record.data_type == "table":
            return self.database.sync_table(name, str(record.path), self.get_table(name), meta=record.meta, auto_synced=auto_synced, owner_user_id=self.current_user_id, session_id=self.current_session_id)
        if record.data_type == "vector":
            return self.database.sync_vector(name, str(record.path), self.get_vector(name), meta=record.meta, auto_synced=auto_synced, owner_user_id=self.current_user_id, session_id=self.current_session_id)
        if record.data_type == "document":
            return self.database.sync_document(name, str(record.path), self.get_document_text(name), meta=record.meta, auto_synced=auto_synced, owner_user_id=self.current_user_id, session_id=self.current_session_id)
        if record.data_type == "raster":
            return self.database.register_raster(name, str(record.path), meta=record.meta, auto_synced=auto_synced, owner_user_id=self.current_user_id, session_id=self.current_session_id)
        raise TypeError(f"暂不支持同步到数据库的数据类型: {record.data_type}")

    def sync_dataset_to_database(self, name: str) -> dict[str, Any]:
        return self._sync_dataset_to_database(name, auto_synced=False)

    def sync_all_supported_to_database(self) -> list[dict[str, Any]]:
        results = []
        for name in self.list_dataset_names():
            results.append(self._sync_dataset_to_database(name, auto_synced=False))
        return results

    def database_status(self) -> dict[str, Any]:
        return self.database.status()

    def list_database_objects(self) -> dict[str, Any]:
        return {
            "catalog": self.database.list_catalog(session_id=self.current_session_id),
            "sql_tables": self.database.list_sql_tables(),
        }

    def query_database(self, sql: str) -> pd.DataFrame:
        return self.database.query(sql)

    def start_pipeline_run(
        self,
        run_id: str,
        pipeline_name: str,
        source_type: str,
        source_value: str,
        output_prefix: str,
        summary: dict[str, Any] | None = None,
    ) -> None:
        self.database.start_pipeline_run(run_id, pipeline_name, source_type, source_value, output_prefix, summary)
        self.log_operation("启动训练流水线", f"{pipeline_name} | {run_id}", "pipeline")

    def add_pipeline_step(
        self,
        run_id: str,
        step_order: int,
        step_name: str,
        status: str,
        input_summary: str = "",
        output_summary: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.database.add_pipeline_step(run_id, step_order, step_name, status, input_summary, output_summary, detail)
        self.log_operation(f"流水线步骤 {step_order}: {step_name}", output_summary or input_summary, "pipeline")

    def finish_pipeline_run(self, run_id: str, status: str, summary: dict[str, Any] | None = None) -> None:
        self.database.finish_pipeline_run(run_id, status, summary)
        self.log_operation("结束训练流水线", f"{run_id} | {status}", "pipeline")

    def list_pipeline_runs(self, limit: int = 12) -> list[dict[str, Any]]:
        return self.database.list_pipeline_runs(limit=limit)

    def pipeline_run_detail(self, run_id: str) -> dict[str, Any] | None:
        return self.database.pipeline_run_detail(run_id)

    def register_model_result(
        self,
        *,
        model_result_id: str = "",
        task_id: str = "",
        dataset_id: str = "",
        model_name: str,
        output_prefix: str = "",
        result_dataset: str = "",
        metrics_dataset: str = "",
        metrics_path: str = "",
        figure_path: str = "",
        artifact_ids: list[str] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        metrics: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_model_result_id = model_result_id or generate_model_result_id(model_name, output_prefix)
        synced_artifacts: list[dict[str, Any]] = []
        for artifact in artifacts or []:
            artifact_payload = dict(artifact)
            artifact_payload.setdefault("artifact_id", f"artifact_{uuid4().hex[:10]}")
            artifact_payload.setdefault("task_id", task_id)
            artifact_payload.setdefault("model_result_id", resolved_model_result_id)
            artifact_payload.setdefault("dataset_id", dataset_id)
            artifact_meta = dict(artifact_payload.get("meta") or {})
            artifact_meta.setdefault("schema_version", MODEL_ARTIFACT_SCHEMA_VERSION)
            artifact_meta.setdefault("model_result_schema_version", MODEL_RESULT_SCHEMA_VERSION)
            artifact_meta.setdefault("model_result_id", resolved_model_result_id)
            artifact_meta.setdefault("model_name", model_name)
            artifact_payload["meta"] = artifact_meta
            synced_artifacts.append(self.register_artifact(**artifact_payload))
        payload = {
            "schema_version": MODEL_RESULT_SCHEMA_VERSION,
            "artifact_version": MODEL_ARTIFACT_SCHEMA_VERSION,
            "model_result_id": resolved_model_result_id,
            "task_id": task_id,
            "dataset_id": dataset_id,
            "model_name": model_name,
            "output_prefix": output_prefix,
            "result_dataset": result_dataset,
            "metrics_dataset": metrics_dataset,
            "metrics_path": metrics_path,
            "figure_path": figure_path,
            "owner_user_id": self.current_user_id,
            "session_id": self.current_session_id,
            "artifact_ids": [str(item.get("artifact_id") or "") for item in synced_artifacts if item.get("artifact_id")] or artifact_ids or [],
            "artifacts": synced_artifacts or artifacts or [],
            "metrics": metrics or {},
            "diagnostics": diagnostics or {},
        }
        return self._normalize_model_result_versions(self.database.upsert_model_result(payload))

    def register_artifact(
        self,
        *,
        artifact_id: str = "",
        path: str,
        type: str = "",
        title: str = "",
        description: str = "",
        quality_status: str = "unchecked",
        preview_available: bool = False,
        task_id: str = "",
        model_result_id: str = "",
        dataset_id: str = "",
        mime_type: str = "",
        source_tool: str = "",
        meta: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        artifact_path = self._resolve_workspace_path(path)
        quality = validate_output_artifact(artifact_path)
        resolved_quality_status = quality_status
        if quality_status == "unchecked":
            resolved_quality_status = "ok" if quality.get("ok") else "failed"
        scoped_meta = self._scoped_meta(meta or {k: v for k, v in extra.items() if k not in {"name", "display_path", "category", "size_kb", "modified"}})
        scoped_meta.setdefault("quality_check", quality)
        payload = {
            "artifact_id": artifact_id or f"artifact_{uuid4().hex[:10]}",
            "path": str(artifact_path),
            "absolute_path": str(artifact_path.resolve(strict=False)),
            "relative_path": self._scoped_relative_path(artifact_path),
            "type": type,
            "title": title,
            "description": description,
            "quality_status": resolved_quality_status,
            "preview_available": preview_available,
            "task_id": task_id,
            "model_result_id": model_result_id,
            "dataset_id": dataset_id,
            "owner_user_id": self.current_user_id,
            "session_id": self.current_session_id,
            "mime_type": mime_type or mimetypes.guess_type(str(artifact_path))[0] or "application/octet-stream",
            "source_tool": source_tool,
            "meta": scoped_meta,
        }
        artifact = self.database.upsert_artifact(payload)
        return self._enrich_registered_artifact(artifact)

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        artifact = self.database.get_artifact(artifact_id)
        if not artifact or not self._artifact_visible_in_current_session(artifact):
            return None
        return self._enrich_registered_artifact(artifact)

    def list_registered_artifacts(self, *, model_result_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        return [
            self._enrich_registered_artifact(item)
            for item in self.database.list_artifacts(model_result_id=model_result_id, session_id=self.current_session_id, limit=limit)
            if self._artifact_visible_in_current_session(item)
        ]

    def assert_artifact_access(self, user_id: str, session_id: str, artifact_id: str) -> dict[str, Any]:
        artifact = self.database.get_artifact(artifact_id)
        if not artifact or artifact.get("is_deleted"):
            raise FileNotFoundError(f"artifact not found: {artifact_id}")
        owner = str(artifact.get("owner_user_id") or "")
        artifact_session = str(artifact.get("session_id") or "")
        if owner and str(user_id or "") and owner != str(user_id or ""):
            raise PermissionError("artifact belongs to another user")
        if artifact_session and str(session_id or "") and artifact_session != str(session_id or ""):
            raise PermissionError("artifact belongs to another session")
        if artifact_session and self.current_session_id and artifact_session != self.current_session_id:
            raise PermissionError("artifact is outside the current session")
        return self._enrich_registered_artifact(artifact)

    def _resolve_result_file_for_delete(self, *, artifact_id: str = "", path: str = "") -> Path:
        artifact = self.get_artifact(artifact_id) if artifact_id else None
        raw_path = str(path or (artifact or {}).get("path") or "").strip()
        if not raw_path:
            raise ValueError("需要提供 artifact_id 或 path 才能删除结果文件。")
        target = Path(raw_path)
        if not target.is_absolute():
            target = self.workdir / target
        resolved = target.resolve(strict=False)
        allowed_roots = [self.plot_dir.resolve(), self.derived_dir.resolve()]
        if not any(resolved == root or resolved.is_relative_to(root) for root in allowed_roots):
            raise PermissionError("只能删除工作区 plots/derived 下的结果文件，上传原始数据不会被此接口删除。")
        return resolved

    def _result_delete_targets(self, target: Path) -> list[Path]:
        targets = [target]
        if target.suffix.lower() == ".shp":
            targets = [target.with_suffix(ext) for ext in SHAPE_SIDE_EXTS]
        extra = [
            target.with_suffix(target.suffix + ".aux.xml") if target.suffix else target.with_name(target.name + ".aux.xml"),
            target.with_suffix(target.suffix + ".ovr") if target.suffix else target.with_name(target.name + ".ovr"),
            target.with_name(target.name + ".aux.xml"),
            target.with_name(target.name + ".ovr"),
        ]
        seen: set[str] = set()
        out: list[Path] = []
        for item in [*targets, *extra]:
            key = str(item.resolve(strict=False)).lower()
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    def delete_result_file(self, *, artifact_id: str = "", path: str = "") -> dict[str, Any]:
        target = self._resolve_result_file_for_delete(artifact_id=artifact_id, path=path)
        delete_targets = self._result_delete_targets(target)
        deleted_files: list[str] = []
        deleted_artifacts: list[str] = []
        deleted_datasets: list[str] = []

        target_keys = {str(item.resolve(strict=False)).lower() for item in delete_targets}
        for item in delete_targets:
            if item.is_dir():
                shutil.rmtree(item)
                deleted_files.append(str(item))
            elif item.exists():
                item.unlink()
                deleted_files.append(str(item))

        if artifact_id:
            if self.database.delete_artifact(artifact_id, hard=True):
                deleted_artifacts.append(artifact_id)
        for artifact in self.database.list_artifacts(session_id=self.current_session_id, limit=1000):
            artifact_path = Path(str(artifact.get("path") or "")).resolve(strict=False)
            if str(artifact_path).lower() in target_keys:
                artifact_key = str(artifact.get("artifact_id") or "")
                if artifact_key and self.database.delete_artifact(artifact_key, hard=True):
                    deleted_artifacts.append(artifact_key)

        for item in self.database.list_catalog(session_id=self.current_session_id):
            dataset_name = str(item.get("dataset_name") or "")
            dataset_path = Path(str(item.get("path") or "")).resolve(strict=False)
            if dataset_name and str(dataset_path).lower() in target_keys:
                try:
                    self.database.drop_dataset(dataset_name)
                except Exception:
                    pass
                self.datasets.pop(dataset_name, None)
                deleted_datasets.append(dataset_name)

        for name, record in list(self.datasets.items()):
            if str(Path(record.path).resolve(strict=False)).lower() in target_keys:
                self.datasets.pop(name, None)
                if name not in deleted_datasets:
                    deleted_datasets.append(name)

        if self.last_plot_path and str(Path(self.last_plot_path).resolve(strict=False)).lower() in target_keys:
            self.last_plot_path = ""

        self.log_operation("删除结果文件", str(target), "delete")
        return {
            "ok": True,
            "path": str(target),
            "deleted_files": deleted_files,
            "deleted_artifacts": sorted(set(deleted_artifacts)),
            "deleted_datasets": sorted(set(deleted_datasets)),
        }

    def cleanup_session_data(self, session_id: str) -> dict[str, Any]:
        clean_session = str(session_id or "").strip()
        if not clean_session:
            return {"ok": False, "session_id": "", "deleted_files": [], "deleted_artifacts": [], "deleted_datasets": [], "errors": ["missing session_id"]}

        deleted_artifacts: list[str] = []
        deleted_datasets: list[str] = []
        errors: list[str] = []

        for artifact in self.database.list_artifacts(session_id=clean_session, include_deleted=True, limit=10000):
            artifact_id = str(artifact.get("artifact_id") or "")
            if artifact_id and self.database.delete_artifact(artifact_id, hard=True):
                deleted_artifacts.append(artifact_id)

        for item in self.database.list_catalog(session_id=clean_session):
            dataset_name = str(item.get("dataset_name") or "")
            if dataset_name:
                try:
                    self.database.drop_dataset(dataset_name)
                except Exception as exc:
                    errors.append(f"{dataset_name}: {exc}")
                self.datasets.pop(dataset_name, None)
                deleted_datasets.append(dataset_name)

        for name, record in list(self.datasets.items()):
            if str((record.meta or {}).get("session_id") or "") == clean_session:
                self.datasets.pop(name, None)
                if name not in deleted_datasets:
                    deleted_datasets.append(name)

        root = self.workdir / "sessions" / re.sub(r"[^A-Za-z0-9_.-]+", "_", clean_session)
        deleted_files: list[str] = []
        if root.exists():
            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_file():
                    deleted_files.append(str(path))
            try:
                shutil.rmtree(root)
            except Exception as exc:
                errors.append(f"{root}: {exc}")

        if self.current_session_id == clean_session:
            self.set_runtime_scope(self.current_user_id, "")
        hard_deleted_records = self.database.hard_delete_session_records(clean_session)

        return {
            "ok": not errors,
            "session_id": clean_session,
            "deleted_files": deleted_files,
            "deleted_artifacts": sorted(set(deleted_artifacts)),
            "deleted_datasets": sorted(set(deleted_datasets)),
            "hard_deleted_records": hard_deleted_records,
            "errors": errors,
        }

    def _enrich_registered_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        item = dict(artifact)
        path = self._resolve_workspace_path(str(item.get("path") or ""))
        item["path"] = str(path)
        item["absolute_path"] = str(path.resolve(strict=False))
        item["relative_path"] = self._scoped_relative_path(path)
        try:
            relative = path.relative_to(path.parents[1])
        except Exception:
            relative = path.name
        item.setdefault("name", path.name)
        item["display_path"] = str(relative).replace("\\", "/")
        category = "derived"
        try:
            if path.resolve().is_relative_to(self.plot_dir.resolve()):
                category = "plot"
            elif path.resolve().is_relative_to(self.derived_dir.resolve()):
                category = "derived"
        except Exception:
            pass
        item["category"] = category
        if path.exists():
            item["size_kb"] = round(path.stat().st_size / 1024, 2)
            item["modified"] = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        else:
            item.setdefault("size_kb", 0)
            item.setdefault("modified", item.get("updated_at") or "")
        return item

    def get_model_result(self, model_result_id: str) -> dict[str, Any] | None:
        result = self.database.get_model_result(model_result_id)
        if not result or not self._model_result_visible_in_current_session(result):
            return None
        return self._attach_registered_model_artifacts(self._normalize_model_result_versions(result))

    def list_model_results(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            self._attach_registered_model_artifacts(self._normalize_model_result_versions(item))
            for item in self.database.list_model_results(limit=limit)
            if self._model_result_visible_in_current_session(item)
        ]

    def _model_result_visible_in_current_session(self, result: dict[str, Any]) -> bool:
        if not self.current_session_id:
            return True
        result_session = str(result.get("session_id") or "")
        return not result_session or result_session == self.current_session_id

    def _attach_registered_model_artifacts(self, result: dict[str, Any] | None) -> dict[str, Any]:
        item = self._normalize_model_result_versions(result or {})
        model_result_id = str(item.get("model_result_id") or "")
        registered = self.list_registered_artifacts(model_result_id=model_result_id, limit=100) if model_result_id else []
        if model_result_id:
            item["artifacts"] = registered
            item["artifact_ids"] = [str(artifact.get("artifact_id") or "") for artifact in registered if artifact.get("artifact_id")]
        return item

    def _normalize_model_result_versions(self, result: dict[str, Any] | None) -> dict[str, Any]:
        item = dict(result or {})
        item.setdefault("schema_version", MODEL_RESULT_SCHEMA_VERSION)
        item.setdefault("artifact_version", MODEL_ARTIFACT_SCHEMA_VERSION)
        return item
