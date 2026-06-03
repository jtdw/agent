from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import geopandas as gpd
import pandas as pd
import rasterio

from .workspace_db import WorkspaceDatabase


VECTOR_EXTS = {".shp", ".geojson", ".gpkg", ".json", ".kml"}
RASTER_EXTS = {".tif", ".tiff", ".img"}
TABLE_EXTS = {".csv", ".xlsx", ".xls"}
DOCUMENT_EXTS = {".docx", ".txt", ".md"}
SHAPE_SIDE_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix"}


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    root = target_dir.resolve()
    for member in zf.infolist():
        target = (root / member.filename).resolve()
        try:
            target.relative_to(root)
        except Exception:
            raise ValueError(f"压缩包包含不安全路径：{member.filename}")
    zf.extractall(root)


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
        self.upload_dir = self.workdir / "uploads"
        self.plot_dir = self.workdir / "plots"
        self.derived_dir = self.workdir / "derived"
        self.temp_dir = self.workdir / "temp"
        self.datasets: dict[str, DatasetRecord] = {}
        self.database = WorkspaceDatabase(self.workdir / "workspace.db")
        self.last_plot_path: str = ""
        self.operation_log: list[dict[str, Any]] = []

        for folder in [self.upload_dir, self.plot_dir, self.derived_dir, self.temp_dir]:
            folder.mkdir(parents=True, exist_ok=True)

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
                df = pd.read_csv(path)
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
                df = pd.read_csv(actual)
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
        artifacts: list[dict[str, Any]] = []
        root_to_category = {
            self.plot_dir.resolve(): "plot",
            self.derived_dir.resolve(): "derived",
        }
        for path in self.result_file_paths()[:100]:
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
            artifacts.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "display_path": (str(relative).replace("\\", "/") if not isinstance(relative, str) else relative),
                    "category": category,
                    "size_kb": round(path.stat().st_size / 1024, 2),
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return artifacts

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
        filename = filename or f"{dataset_name}.geojson"
        output_path = self.derived_dir / filename
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
        filename = filename or f"{dataset_name}.csv"
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
        filename = filename or f"{dataset_name}.txt"
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
