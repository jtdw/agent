from __future__ import annotations

import json
import hashlib
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

from infrastructure.storage.workspace_paths import WorkspacePaths

from .archive_utils import safe_extract_zip
from .artifacts import artifact_download_url, artifact_meta_url, artifact_mime_type, safe_download_filename
from .model_results import generate_model_result_id
from .workspace_db import WorkspaceDatabase


VECTOR_EXTS = {".shp", ".geojson", ".gpkg", ".json", ".kml"}
RASTER_EXTS = {".tif", ".tiff", ".img"}
TABLE_EXTS = {".csv", ".xlsx", ".xls"}
DOCUMENT_EXTS = {".docx", ".txt", ".md"}
SHAPE_SIDE_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix"}


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    return safe_extract_zip(zf, target_dir)
    root = target_dir.resolve()
    for member in zf.infolist():
        mode = member.external_attr >> 16
        if mode & 0o170000 == 0o120000:
            raise ValueError(f"Unsafe zip symlink: {member.filename}")
        target = (root / member.filename).resolve()
        try:
            target.relative_to(root)
        except Exception:
            raise ValueError(f"压缩包包含不安全路径：{member.filename}")
    zf.extractall(root)


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
    try:
        return pd.read_csv(path)
    except pd.errors.ParserError as exc:
        station_df = _read_station_series_table(path)
        if station_df is not None:
            return station_df

        for options in (
            {"sep": None, "engine": "python"},
            {"sep": r"\s+", "engine": "python"},
        ):
            try:
                return pd.read_csv(path, **options)
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
        self.paths = WorkspacePaths(workdir).ensure()
        self.workdir = self.paths.root
        self.upload_dir = self.paths.uploads
        self.plot_dir = self.paths.plots
        self.derived_dir = self.paths.derived
        self.temp_dir = self.paths.temp
        self.datasets: dict[str, DatasetRecord] = {}
        self.database = WorkspaceDatabase(self.paths.database)
        self.last_plot_path: str = ""
        self.operation_log: list[dict[str, Any]] = []

        self._restore_workspace_state()

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
            self.datasets[dataset_name] = DatasetRecord(dataset_name, actual, "vector", gdf, self._build_vector_meta(gdf))
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
            self.datasets[dataset_name] = DatasetRecord(dataset_name, path, "raster", str(path), meta)
        elif data_type == "table":
            if path.suffix.lower() == ".csv":
                df = _read_csv_table(path)
            else:
                df = pd.read_excel(path)
            self.datasets[dataset_name] = DatasetRecord(dataset_name, path, "table", df, {"rows": len(df), "columns": list(df.columns)})
        elif data_type == "document":
            if path.suffix.lower() == ".docx":
                text = self._read_docx_text(path)
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
            self.datasets[dataset_name] = DatasetRecord(dataset_name, path, "document", text, self._build_document_meta(text))

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

        The agent sees manifest ids such as lib_china_admin_county_2023
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
        target = self.upload_dir / source.name

        if source.suffix.lower() == ".shp":
            for sibling in source.parent.glob(f"{source.stem}.*"):
                if sibling.suffix.lower() in SHAPE_SIDE_EXTS:
                    dest = self.upload_dir / sibling.name
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

    def _extract_zip_if_needed(self, path: Path) -> Path:
        if path.suffix.lower() != ".zip":
            return path
        target_dir = self.upload_dir / path.stem
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "r") as zf:
            _safe_extract_zip(zf, target_dir)

        search_order = [
            "*.shp", "*.gpkg", "*.geojson", "*.json", "*.kml",
            "*.csv", "*.xlsx", "*.xls",
            "*.tif", "*.tiff", "*.img",
            "*.docx", "*.txt", "*.md",
        ]
        for pattern in search_order:
            matches = sorted(target_dir.rglob(pattern))
            if matches:
                return matches[0]
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
        target = self.upload_dir / Path(filename).name
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

    def load_path(self, file_path: str, name: str | None = None) -> str:
        source = Path(file_path)
        if not source.exists():
            resolved = self._resolve_local_library_reference(file_path)
            if resolved is None:
                raise FileNotFoundError(f"文件不存在: {file_path}")
            source = resolved
        self._require_allowed_import_source(source)
        copied = self._copy_to_uploads(source)
        actual = self._extract_zip_if_needed(copied)
        dataset_name = self._unique_name(name or actual.stem)
        ext = actual.suffix.lower()

        if ext in VECTOR_EXTS:
            actual = self._prepare_vector_source(actual)
            gdf = gpd.read_file(actual)
            self.datasets[dataset_name] = DatasetRecord(
                name=dataset_name,
                path=actual,
                data_type="vector",
                object_ref=gdf,
                meta=self._build_vector_meta(gdf),
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
                }
            self.datasets[dataset_name] = DatasetRecord(
                name=dataset_name,
                path=actual,
                data_type="raster",
                object_ref=str(actual),
                meta=meta,
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
                meta={"rows": len(df), "columns": list(df.columns)},
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
                meta=self._build_document_meta(text),
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
        ]

    def list_dataset_names(self) -> list[str]:
        return list(self.datasets.keys())

    def dataset_brief(self) -> str:
        if not self.datasets:
            return "当前没有已加载的数据集。"
        return json.dumps(self.list_datasets(), ensure_ascii=False, indent=2)

    def workspace_summary(self) -> dict[str, Any]:
        return {
            "dataset_count": len(self.datasets),
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

    def list_artifacts(self) -> list[dict[str, Any]]:
        registered = [
            item
            for item in self.list_registered_artifacts(limit=200)
            if Path(str(item.get("path") or "")).exists()
        ]
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
                    "display_path": (str(relative).replace("\\", "/") if not isinstance(relative, str) else relative),
                    "category": category,
                    "size_kb": round(path.stat().st_size / 1024, 2),
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return registered + artifacts

    def get(self, name: str) -> DatasetRecord:
        if name not in self.datasets:
            raise KeyError(f"未找到数据集: {name}")
        return self.datasets[name]

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
            meta=self._build_vector_meta(gdf),
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def put_table(self, name: str, df: pd.DataFrame, filename: str | None = None) -> str:
        dataset_name = self._unique_name(name)
        filename = _safe_output_filename(filename or "", f"{dataset_name}.csv", {".csv"})
        output_path = self.derived_dir / filename
        df.to_csv(output_path, index=False)
        self.datasets[dataset_name] = DatasetRecord(
            name=dataset_name,
            path=output_path,
            data_type="table",
            object_ref=df,
            meta={"rows": len(df), "columns": list(df.columns)},
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
            meta=self._build_document_meta(text),
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
            meta=meta or {},
        )
        self._sync_dataset_to_database(dataset_name, auto_synced=True)
        return dataset_name

    def _sync_dataset_to_database(self, name: str, auto_synced: bool = True) -> dict[str, Any]:
        record = self.get(name)
        if record.data_type == "table":
            return self.database.sync_table(name, str(record.path), self.get_table(name), meta=record.meta, auto_synced=auto_synced)
        if record.data_type == "vector":
            return self.database.sync_vector(name, str(record.path), self.get_vector(name), meta=record.meta, auto_synced=auto_synced)
        if record.data_type == "document":
            return self.database.sync_document(name, str(record.path), self.get_document_text(name), meta=record.meta, auto_synced=auto_synced)
        if record.data_type == "raster":
            return self.database.register_raster(name, str(record.path), meta=record.meta, auto_synced=auto_synced)
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
            "catalog": self.database.list_catalog(),
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
            synced_artifacts.append(self.register_artifact(**artifact_payload))
        payload = {
            "model_result_id": resolved_model_result_id,
            "task_id": task_id,
            "dataset_id": dataset_id,
            "model_name": model_name,
            "output_prefix": output_prefix,
            "result_dataset": result_dataset,
            "metrics_dataset": metrics_dataset,
            "metrics_path": metrics_path,
            "figure_path": figure_path,
            "artifact_ids": [str(item.get("artifact_id") or "") for item in synced_artifacts if item.get("artifact_id")] or artifact_ids or [],
            "artifacts": synced_artifacts or artifacts or [],
            "metrics": metrics or {},
            "diagnostics": diagnostics or {},
        }
        return self.database.upsert_model_result(payload)

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
        meta: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        payload = {
            "artifact_id": artifact_id or f"artifact_{uuid4().hex[:10]}",
            "path": path,
            "type": type,
            "title": title,
            "description": description,
            "quality_status": quality_status,
            "preview_available": preview_available,
            "task_id": task_id,
            "model_result_id": model_result_id,
            "dataset_id": dataset_id,
            "meta": meta or {k: v for k, v in extra.items() if k not in {"name", "display_path", "category", "size_kb", "modified"}},
        }
        artifact = self.database.upsert_artifact(payload)
        return self._enrich_registered_artifact(artifact)

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        artifact = self.database.get_artifact(artifact_id)
        return self._enrich_registered_artifact(artifact) if artifact else None

    def resolve_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        clean = str(artifact_id or "").strip()
        if not clean:
            return None
        registered = self.get_artifact(clean)
        if registered:
            return registered
        for artifact in self.list_artifacts():
            if str(artifact.get("artifact_id") or "") == clean:
                return artifact
        return None

    def _delete_artifact_files(self, path: Path) -> list[str]:
        candidates = [path]
        if path.suffix.lower() == ".shp":
            candidates = [
                sidecar
                for sidecar in sorted(path.parent.glob(f"{path.stem}.*"))
                if sidecar.suffix.lower() in SHAPE_SIDE_EXTS
            ]
        deleted: list[str] = []
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
                deleted.append(str(candidate))
        return deleted

    def delete_artifact(self, artifact_id: str, *, delete_file: bool = True) -> dict[str, Any]:
        artifact = self.resolve_artifact(artifact_id)
        if not artifact:
            return {"ok": False, "artifact_id": str(artifact_id or ""), "status": "not_found", "file_deleted": False}
        path = Path(str(artifact.get("path") or "")).resolve()
        deleted_files = self._delete_artifact_files(path) if delete_file else []
        removed = self.database.delete_artifact(str(artifact.get("artifact_id") or artifact_id))
        references_removed = self.database.remove_artifact_references(str(artifact.get("artifact_id") or artifact_id))
        datasets_removed = self.database.drop_datasets_by_path(path) if delete_file else []
        for dataset_name in datasets_removed:
            self.datasets.pop(dataset_name, None)
        file_gone = not path.exists()
        ok = bool(removed or deleted_files or references_removed or datasets_removed or (delete_file and file_gone))
        self.log_operation("删除结果文件", str(artifact.get("filename") or artifact.get("name") or artifact_id), "artifact")
        return {
            "ok": ok,
            "artifact_id": str(artifact.get("artifact_id") or artifact_id),
            "filename": str(artifact.get("filename") or artifact.get("name") or path.name),
            "status": "deleted" if ok else "not_found",
            "file_deleted": bool(deleted_files),
            "deleted_files": deleted_files,
            "references_removed": references_removed,
            "datasets_removed": datasets_removed,
        }

    def list_registered_artifacts(self, *, model_result_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        return [self._enrich_registered_artifact(item) for item in self.database.list_artifacts(model_result_id=model_result_id, limit=limit)]

    def _enrich_registered_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        item = dict(artifact)
        path = Path(str(item.get("path") or ""))
        try:
            relative = path.relative_to(path.parents[1])
        except Exception:
            relative = path.name
        item.setdefault("name", path.name)
        item["filename"] = safe_download_filename(str(item.get("title") or item.get("name") or path.name))
        item["mime_type"] = artifact_mime_type(item["filename"], str(item.get("type") or ""))
        item["download_url"] = artifact_download_url(str(item.get("artifact_id") or ""))
        item["metadata_url"] = artifact_meta_url(str(item.get("artifact_id") or ""))
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        item["source"] = {
            "tool_name": str(meta.get("tool_name") or item.get("tool_name") or ""),
            "workflow_id": str(meta.get("workflow_id") or item.get("workflow_id") or ""),
            "message_id": str(meta.get("message_id") or item.get("message_id") or ""),
        }
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
            size_bytes = path.stat().st_size
            item["size_bytes"] = size_bytes
            item["size_kb"] = round(size_bytes / 1024, 2)
            item["modified"] = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        else:
            item.setdefault("size_kb", 0)
            item.setdefault("modified", item.get("updated_at") or "")
        return item

    def get_model_result(self, model_result_id: str) -> dict[str, Any] | None:
        result = self.database.get_model_result(model_result_id)
        return self._attach_registered_model_artifacts(result) if result else None

    def list_model_results(self, limit: int = 50) -> list[dict[str, Any]]:
        return [self._attach_registered_model_artifacts(item) for item in self.database.list_model_results(limit=limit)]

    def _attach_registered_model_artifacts(self, result: dict[str, Any] | None) -> dict[str, Any]:
        item = dict(result or {})
        model_result_id = str(item.get("model_result_id") or "")
        registered = [
            artifact
            for artifact in (self.list_registered_artifacts(model_result_id=model_result_id, limit=100) if model_result_id else [])
            if Path(str(artifact.get("path") or "")).exists()
        ]
        if registered:
            item["artifacts"] = registered
            item["artifact_ids"] = [str(artifact.get("artifact_id") or "") for artifact in registered if artifact.get("artifact_id")]
        else:
            stale_checked = []
            for artifact in item.get("artifacts") if isinstance(item.get("artifacts"), list) else []:
                if isinstance(artifact, dict) and Path(str(artifact.get("path") or "")).exists():
                    stale_checked.append(artifact)
            item["artifacts"] = stale_checked
            item["artifact_ids"] = [str(artifact.get("artifact_id") or "") for artifact in stale_checked if isinstance(artifact, dict) and artifact.get("artifact_id")]
        return item
