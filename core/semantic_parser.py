from __future__ import annotations

import re
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd


ADMIN_ZIP = Path(__file__).resolve().parents[1] / "local_library" / "data" / "administrative" / "china_admin_county_2023.zip"

ACTION_TERMS = ("下载", "获取", "准备", "检索", "导入", "加载")
POLITE_OR_TASK_PREFIX_RE = re.compile(
    r"^(?:帮我|请|麻烦|给我|为我|我想|想要|需要|进行|处理|做一个|做一张|下载|获取|分析|生成|制作|查询|计算)+"
)
REGION_NOISE_RE = re.compile(
    r"(?:的|数据|文件|结果|地图|图层|行政区|边界|范围|DEM|dem|SRTM|srtm|ASTER|aster|GDEM|gdem|90m|90M|30m|30M|90米|30米|\s)+$"
)
ADMIN_SUFFIX_RE = re.compile(r"(特别行政区|自治州|自治县|自治旗|地区|盟|省|市|县|区|旗)$")


def _compact(value: str) -> str:
    return re.sub(r"[\s，。；;、,._\-]+", "", str(value or "").strip())


def _semantic_search_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"@\{[^}]+\}", " ", text)
    text = re.sub(r"\b[\w\-]+\.(?:csv|tsv|xlsx|xls|geojson|json|shp|zip|tif|tiff)\b", " ", text, flags=re.IGNORECASE)
    return text


def _has_ascii_resource_token(text: str, token: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9_]){re.escape(token)}(?:v?\d+)?(?![a-z0-9_])", str(text or "").lower()))


def clean_semantic_phrase(value: str) -> str:
    text = str(value or "").strip()
    previous = None
    while text and text != previous:
        previous = text
        text = POLITE_OR_TASK_PREFIX_RE.sub("", text).strip()
        text = REGION_NOISE_RE.sub("", text).strip()
    return text


def _project_admin_zip() -> Path:
    return ADMIN_ZIP


def _extract_admin_zip_once(zip_path: Path) -> Path:
    target = Path(tempfile.gettempdir()) / "gis_agent_semantic_admin" / zip_path.stem
    marker = target / ".extracted"
    if marker.exists():
        return target
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        root = target.resolve()
        for member in zf.infolist():
            dest = (root / member.filename).resolve()
            dest.relative_to(root)
        zf.extractall(root)
    marker.write_text(str(zip_path), encoding="utf-8")
    return target


def _without_suffix(value: str) -> str:
    return ADMIN_SUFFIX_RE.sub("", str(value or "").strip())


def _add_alias(aliases: dict[str, dict[str, Any]], alias: str, record: dict[str, Any]) -> None:
    key = _compact(alias)
    if not key:
        return
    current = aliases.get(key)
    if current is None or len(str(alias)) > len(str(current.get("matched_alias") or "")):
        aliases[key] = {**record, "matched_alias": alias}


@lru_cache(maxsize=1)
def _admin_alias_index() -> dict[str, dict[str, Any]]:
    zip_path = _project_admin_zip()
    if not zip_path.exists():
        return {}
    try:
        root = _extract_admin_zip_once(zip_path)
        shp = next(root.rglob("*.shp"))
        gdf = gpd.read_file(shp, ignore_geometry=True)
    except Exception:
        return {}

    aliases: dict[str, dict[str, Any]] = {}
    if gdf.empty:
        return aliases

    for _, row in gdf.iterrows():
        province = str(row.get("省级") or "").strip()
        city = str(row.get("地级") or "").strip()
        county = str(row.get("县级") or row.get("地名") or "").strip()
        if province:
            province_record = {
                "region": province,
                "region_standard": province,
                "admin_level": "province",
                "province": province,
                "city": "",
                "county": "",
            }
            for alias in {province, _without_suffix(province)}:
                _add_alias(aliases, alias, province_record)
        if city:
            city_record = {
                "region": city,
                "region_standard": f"{province}{city}" if province and not city.startswith(province) else city,
                "admin_level": "prefecture_city",
                "province": province,
                "city": city,
                "county": "",
            }
            city_short = _without_suffix(city)
            province_short = _without_suffix(province)
            for alias in {city, city_short, f"{province}{city}", f"{province}{city_short}", f"{province_short}{city}", f"{province_short}{city_short}"}:
                _add_alias(aliases, alias, city_record)
        if county:
            county_record = {
                "region": county,
                "region_standard": f"{province}{city}{county}" if province and city else county,
                "admin_level": "county",
                "province": province,
                "city": city,
                "county": county,
            }
            county_short = _without_suffix(county)
            for alias in {county, county_short, f"{city}{county}", f"{province}{city}{county}"}:
                _add_alias(aliases, alias, county_record)
    return aliases


def _detect_action(prompt: str) -> str:
    search_text = _semantic_search_text(prompt)
    compact = _compact(search_text).lower()
    if any(term in search_text for term in ACTION_TERMS) or "download" in compact or "get" in compact:
        return "download"
    if any(term in search_text for term in ("裁剪", "叠加", "重投影", "转换", "提取", "统计")):
        return "process"
    if any(term in search_text for term in ("制图", "画图", "地图", "专题图", "可视化")):
        return "map"
    return ""


def _detect_resource_type(prompt: str) -> str:
    text = _semantic_search_text(prompt)
    lower = text.lower()
    if any(term in text for term in ("行政区边界", "行政边界", "边界")):
        return "admin_boundary"
    if any(_has_ascii_resource_token(lower, term) for term in ("dem", "srtm", "gdem")) or any(term in text for term in ("高程", "数字高程", "地形")):
        return "DEM"
    if "ndvi" in lower or "植被指数" in text:
        return "NDVI"
    if "evi" in lower:
        return "EVI"
    if "landsat" in lower:
        return "Landsat"
    if "sentinel" in lower or "哨兵" in text:
        return "Sentinel-2"
    return ""


def _detect_resolution(prompt: str) -> str:
    text = str(prompt or "")
    match = re.search(r"(?i)(\d+(?:\.\d+)?)\s*(m|米)", text)
    if match:
        number = match.group(1)
        return f"{number}m"
    return ""


def _best_admin_match(prompt: str) -> dict[str, Any]:
    aliases = _admin_alias_index()
    if not aliases:
        return {}
    compact_prompt = _compact(clean_semantic_phrase(prompt))
    if not compact_prompt:
        compact_prompt = _compact(prompt)
    matches: list[tuple[int, str, dict[str, Any]]] = []
    for alias, record in aliases.items():
        if alias and alias in compact_prompt:
            matches.append((len(alias), alias, record))
    if not matches:
        return {}
    matches.sort(key=lambda item: (-item[0], item[2].get("admin_level") != "prefecture_city", item[1]))
    return matches[0][2]


def _fallback_region_raw(prompt: str) -> str:
    text = str(prompt or "")
    patterns = [
        r"([\u4e00-\u9fff]{2,18}?(?:特别行政区|自治州|自治县|自治旗|地区|盟|省|市|县|区|旗))(?=(?:的|DEM|dem|GDEM|gdem|SRTM|srtm|90|30|数据|高程|行政|边界|[，。；;\s]|$))",
        r"(?:下载|获取|准备|检索|进行|处理)([^，。；;\s]{2,18})",
    ]
    for pattern in patterns:
        found = [clean_semantic_phrase(m.group(1)) for m in re.finditer(pattern, text)]
        found = [item for item in found if item]
        if found:
            return found[-1]
    return ""


def _dataset_id_for_dem(prompt: str, resolution: str) -> str:
    compact = _compact(prompt).lower()
    if "srtm" in compact or resolution == "90m":
        return "306"
    if "gdemv2" in compact or "gdem2" in compact:
        return "421"
    return "310"


def parse_user_semantics(prompt: str, context: Any | None = None) -> dict[str, Any]:
    text = str(prompt or "").strip()
    search_text = _semantic_search_text(text)
    action = _detect_action(search_text)
    resource_type = _detect_resource_type(search_text)
    resolution = _detect_resolution(search_text)
    admin = _best_admin_match(search_text)
    raw = str(admin.get("matched_alias") or "") if admin else _fallback_region_raw(search_text)
    cleaned_raw = clean_semantic_phrase(raw)
    if cleaned_raw and not admin:
        admin = _best_admin_match(cleaned_raw)

    intent = "unclear_request"
    if action == "download" and (resource_type or admin):
        intent = "data_download"
    elif action == "process":
        intent = "data_processing"
    elif action == "map":
        intent = "map_generation"

    region = str(admin.get("region") or "") if admin else ""
    region_standard = str(admin.get("region_standard") or "") if admin else ""
    admin_level = str(admin.get("admin_level") or "") if admin else ""
    needs_region = intent == "data_download" and resource_type in {"DEM", "admin_boundary", "NDVI", "EVI", "Landsat", "Sentinel-2"}
    needs_clarification = bool(needs_region and not region)
    missing_slots = ["region"] if needs_clarification else []
    product_key = ""
    dataset_id = ""
    data_source = "gscloud" if intent == "data_download" and resource_type in {"DEM", "NDVI", "EVI", "Landsat", "Sentinel-2"} else ""
    if resource_type == "DEM":
        product_key = "gscloud_dem"
        dataset_id = _dataset_id_for_dem(search_text, resolution)

    confidence = 0.35
    if intent != "unclear_request":
        confidence = 0.72
    if region:
        confidence += 0.18
    if resource_type:
        confidence += 0.08
    if needs_clarification:
        confidence = min(confidence, 0.62)

    return {
        "intent": intent,
        "action": action,
        "resource_type": resource_type,
        "region_raw": cleaned_raw,
        "region": region,
        "region_standard": region_standard,
        "admin_level": admin_level,
        "resolution": resolution,
        "data_source": data_source,
        "product_key": product_key,
        "dataset_id": dataset_id,
        "object_refs": [],
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "needs_clarification": needs_clarification,
        "missing_slots": missing_slots,
        "clarification_question": "请补充要下载或处理的行政区名称。" if needs_clarification else "",
    }
