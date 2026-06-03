from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

VECTOR_EXTS = {".shp", ".geojson", ".gpkg", ".json", ".kml"}
RASTER_EXTS = {".tif", ".tiff", ".img"}
TABLE_EXTS = {".csv", ".xlsx", ".xls"}
DOCUMENT_EXTS = {".docx", ".txt", ".md", ".pdf"}
ARCHIVE_EXTS = {".zip"}
SHAPE_SIDE_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix"}
SUPPORTED_EXTS = VECTOR_EXTS | RASTER_EXTS | TABLE_EXTS | DOCUMENT_EXTS | ARCHIVE_EXTS | SHAPE_SIDE_EXTS
HIDDEN_SOURCE_DOC_RE = re.compile(r"(^readme(?:[_-].*)?\.(?:md|txt)$|^license(?:[_-].*)?\.(?:md|txt)$|_from_source\.(?:md|txt)$)", re.IGNORECASE)


@dataclass
class LocalLibraryItem:
    item_id: str
    name: str
    category: str
    data_type: str
    path: str
    description: str = ""
    tags: list[str] | None = None
    region: str = ""
    time_range: str = ""
    scale: str = ""
    crs: str = ""
    source: str = ""
    license: str = ""
    size_bytes: int = 0
    updated_at: str = ""
    enabled: bool = True
    builtin: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = data.get("tags") or []
        return data


def _slug(text: str) -> str:
    raw = (text or "dataset").strip().lower()
    raw = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_.-]+", "_", raw)
    raw = raw.strip("._-") or "dataset"
    return raw[:64]


def _guess_data_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VECTOR_EXTS:
        return "vector"
    if ext in RASTER_EXTS:
        return "raster"
    if ext in TABLE_EXTS:
        return "table"
    if ext in DOCUMENT_EXTS:
        return "document"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext in SHAPE_SIDE_EXTS:
        return "shapefile_part"
    return "unknown"


def is_user_visible_library_item(item: dict[str, Any]) -> bool:
    if item.get("data_type") != "document":
        return True
    name = Path(str(item.get("name") or "")).name
    path_name = Path(str(item.get("path") or "")).name
    return not (HIDDEN_SOURCE_DOC_RE.search(name) or HIDDEN_SOURCE_DOC_RE.search(path_name))


def _guess_category(path: Path, data_type: str) -> str:
    text = "/".join(path.parts).lower()
    name = path.stem.lower()
    if any(k in text for k in ["admin", "行政", "boundary", "区划", "边界", "china"]):
        return "行政区划与边界"
    if any(k in text for k in ["rain", "precip", "chirps", "降雨", "降水", "气象"]):
        return "气象与降水"
    if any(k in text for k in ["dem", "slope", "aspect", "terrain", "高程", "坡度", "地形"]):
        return "地形数据"
    if any(k in text for k in ["soil", "sm", "soil_moisture", "土壤", "水分", "湿度"]):
        return "土壤与水分"
    if any(k in text for k in ["ndvi", "lai", "modis", "sentinel", "landsat", "vegetation", "植被", "遥感"]):
        return "遥感产品"
    if data_type == "vector":
        return "矢量基础数据"
    if data_type == "raster":
        return "栅格基础数据"
    if data_type == "table":
        return "表格与样点"
    if data_type == "document":
        return "文档资料"
    return "其他"


class LocalFileLibrary:
    """A metadata-driven local library for reusable built-in GIS datasets.

    Folder convention:
        <root>/data/                 place files here, in any subfolder
        <root>/library_manifest.json editable metadata registry

    Users can add new datasets later by copying files into data/ and clicking
    rescan in the UI, or by editing library_manifest.json for richer metadata.
    """

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.data_dir = self.root / "data"
        self.manifest_path = self.root / "library_manifest.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._write_manifest({"version": 1, "items": [], "updated_at": self._now()})
            self._write_sample_readme()

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _write_sample_readme(self) -> None:
        readme = self.root / "README_本地文件库.md"
        if readme.exists():
            return
        readme.write_text(
            "# GIS 智能体本地文件库\n\n"
            "把常用基础数据放到 `data/` 目录下，前端点击“扫描文件库”即可登记。\n\n"
            "建议目录示例：\n\n"
            "```text\n"
            "data/administrative/china_admin_boundary.zip\n"
            "data/climate/china_precip_2020.tif\n"
            "data/terrain/china_dem_1km.tif\n"
            "data/soil/shandian_station_template.csv\n"
            "```\n\n"
            "如需补充数据说明，可编辑 `library_manifest.json` 中对应条目的 description、tags、region、time_range、source 等字段。\n",
            encoding="utf-8",
        )

    def _read_manifest(self) -> dict[str, Any]:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "items": [], "updated_at": self._now()}

    def _write_manifest(self, data: dict[str, Any]) -> None:
        data["updated_at"] = self._now()
        self.manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _resolve_item_path(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        try:
            target.relative_to(self.root)
        except Exception:
            raise PermissionError("本地文件库路径越界，已拒绝访问。")
        return target

    def _scan_candidates(self) -> list[Path]:
        files: list[Path] = []
        for path in self.data_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            ext = path.suffix.lower()
            if ext not in SUPPORTED_EXTS:
                continue
            # For shapefile sidecar files, only register .shp as the primary item.
            if ext in SHAPE_SIDE_EXTS and ext != ".shp":
                continue
            files.append(path)
        files.sort(key=lambda p: str(p.relative_to(self.root)).lower())
        return files

    def rescan(self) -> dict[str, Any]:
        manifest = self._read_manifest()
        existing_by_path = {str(item.get("path", "")).replace("\\", "/"): item for item in manifest.get("items", [])}
        new_items: list[dict[str, Any]] = []
        updated = 0
        added = 0
        seen: set[str] = set()

        for path in self._scan_candidates():
            rel = str(path.relative_to(self.root)).replace("\\", "/")
            seen.add(rel)
            stat = path.stat()
            data_type = _guess_data_type(path)
            item = existing_by_path.get(rel)
            if item:
                item["size_bytes"] = stat.st_size
                item["updated_at"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                item.setdefault("enabled", True)
                item.setdefault("tags", [])
                item.setdefault("category", _guess_category(path, data_type))
                item.setdefault("data_type", data_type)
                updated += 1
            else:
                item_id = f"lib_{_slug(path.stem)}_{uuid4().hex[:6]}"
                item = LocalLibraryItem(
                    item_id=item_id,
                    name=path.stem,
                    category=_guess_category(path, data_type),
                    data_type=data_type,
                    path=rel,
                    description=f"自动扫描登记：{path.name}",
                    tags=[],
                    size_bytes=stat.st_size,
                    updated_at=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    enabled=True,
                    builtin=False,
                ).to_dict()
                added += 1
            new_items.append(item)

        # Keep manually declared missing items, but mark unavailable.
        for rel, item in existing_by_path.items():
            if rel and rel not in seen:
                item = dict(item)
                item["enabled"] = False
                item.setdefault("missing", True)
                new_items.append(item)

        manifest["items"] = new_items
        self._write_manifest(manifest)
        return {"ok": True, "root": str(self.root), "added": added, "updated": updated, "total": len(new_items)}

    def list_items(self, query: str = "", category: str = "", data_type: str = "", include_disabled: bool = False, include_source_docs: bool = False) -> dict[str, Any]:
        manifest = self._read_manifest()
        items = [dict(item) for item in manifest.get("items", [])]
        q = (query or "").strip().lower()
        filtered: list[dict[str, Any]] = []
        for item in items:
            if not include_disabled and not item.get("enabled", True):
                continue
            if not include_source_docs and not is_user_visible_library_item(item):
                continue
            if category and item.get("category") != category:
                continue
            if data_type and item.get("data_type") != data_type:
                continue
            text = " ".join(
                str(v)
                for v in [item.get("name"), item.get("description"), item.get("category"), item.get("region"), item.get("time_range"), item.get("source"), " ".join(item.get("tags") or [])]
            ).lower()
            if q and q not in text:
                continue
            path = self._resolve_item_path(item.get("path", "")) if item.get("path") else None
            item["exists"] = bool(path and path.exists())
            if path and path.exists():
                item["size_mb"] = round(path.stat().st_size / 1024 / 1024, 3)
            filtered.append(item)
        visible_items_for_filters = [
            item for item in items
            if (include_disabled or item.get("enabled", True)) and (include_source_docs or is_user_visible_library_item(item))
        ]
        categories = sorted({str(item.get("category") or "其他") for item in visible_items_for_filters})
        data_types = sorted({str(item.get("data_type") or "unknown") for item in visible_items_for_filters})
        return {
            "root": str(self.root),
            "data_dir": str(self.data_dir),
            "manifest_path": str(self.manifest_path),
            "items": filtered,
            "categories": categories,
            "data_types": data_types,
            "count": len(filtered),
            "total": len(items),
            "updated_at": manifest.get("updated_at", ""),
            "hint": "将文件放入 local_library/data 后点击扫描文件库；也可编辑 library_manifest.json 补充说明、标签、年份和来源。",
        }

    def get_item(self, item_id: str) -> dict[str, Any]:
        for item in self._read_manifest().get("items", []):
            if item.get("item_id") == item_id:
                path = self._resolve_item_path(item.get("path", ""))
                if not path.exists():
                    raise FileNotFoundError(f"文件库条目文件不存在：{item.get('path')}")
                result = dict(item)
                result["absolute_path"] = str(path)
                result["exists"] = True
                return result
        raise FileNotFoundError(f"未找到本地文件库条目：{item_id}")

    def resolve_paths(self, item_ids: Iterable[str]) -> list[dict[str, Any]]:
        return [self.get_item(item_id) for item_id in item_ids]

    def summary_text(self, max_items: int = 18) -> str:
        data = self.list_items()
        items = data.get("items", [])[:max_items]
        if not items:
            return "本地文件库目前为空。管理员可将 shp/zip/tif/csv/xlsx/docx 等文件放入 local_library/data 后扫描。"
        lines = [f"本地文件库根目录：{data.get('root')}", "可用条目："]
        for item in items:
            tags = ",".join(item.get("tags") or [])
            extra = f" | 标签:{tags}" if tags else ""
            try:
                real_path = str(self._resolve_item_path(item.get("path", "")))
            except Exception:
                real_path = str(item.get("path") or "")
            lines.append(
                f"- {item.get('item_id')}: {item.get('name')} [{item.get('data_type')}/{item.get('category')}] "
                f"文件路径:{real_path} {item.get('description','')}{extra}"
            )
        if data.get("count", 0) > max_items:
            lines.append(f"……另有 {data.get('count') - max_items} 个条目未列出。")
        return "\n".join(lines)
