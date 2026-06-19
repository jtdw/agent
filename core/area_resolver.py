from __future__ import annotations

import re
from typing import Any

import geopandas as gpd

from core.capability_config import configured_assets


AREA_RESOLVER_VERSION = "area-resolver/v1"


_STATIC_AREAS: list[dict[str, Any]] = [
    {
        "asset_id": "admin:province:四川省",
        "name": "四川省",
        "area_source": "local_admin_boundary",
        "admin_level": "province",
        "aliases": ["四川", "四川省", "sichuan"],
        "parent": "中国",
        "crs": "EPSG:4326",
        "geometry_type": "MultiPolygon",
        "resolution_method": "county_units_dissolve",
        "fields_required": ["省级", "地级", "地名", "geometry"],
    },
    {
        "asset_id": "admin:city:四川省:成都市",
        "name": "成都市",
        "area_source": "local_admin_boundary",
        "admin_level": "city",
        "aliases": ["成都", "成都市", "chengdu"],
        "parent": "四川省",
        "crs": "EPSG:4326",
        "geometry_type": "MultiPolygon",
        "resolution_method": "county_units_dissolve",
        "fields_required": ["省级", "地级", "地名", "geometry"],
    },
    {
        "asset_id": "admin:city:四川省:绵阳市",
        "name": "绵阳市",
        "area_source": "local_admin_boundary",
        "admin_level": "city",
        "aliases": ["绵阳", "绵阳市", "mianyang"],
        "parent": "四川省",
        "crs": "EPSG:4326",
        "geometry_type": "MultiPolygon",
        "resolution_method": "county_units_dissolve",
        "fields_required": ["省级", "地级", "地名", "geometry"],
    },
    {
        "asset_id": "library:basin:shandianhe",
        "name": "闪电河流域",
        "area_source": "user_selected_default_library",
        "admin_level": "basin",
        "aliases": ["闪电河", "闪电河流域", "shandianhe", "shandian"],
        "parent": "文件库默认流域",
        "crs": "EPSG:4326",
        "geometry_type": "Polygon",
        "resolution_method": "local_library_boundary_asset",
        "item_id": "lib_shandianhe_basin_boundary_full",
        "dataset_name": "shandianhe_basin_boundary",
    },
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def list_area_index() -> list[dict[str, Any]]:
    items = [dict(item, schema_version=AREA_RESOLVER_VERSION, version=str(item.get("version") or "builtin")) for item in _STATIC_AREAS]
    for asset in configured_assets():
        if str(asset.get("status") or "enabled") != "enabled":
            continue
        items.append(
            {
                "asset_id": asset.get("asset_id"),
                "name": asset.get("name"),
                "area_source": asset.get("source") or "asset_registry",
                "admin_level": asset.get("asset_type") or "asset",
                "aliases": asset.get("aliases") or [asset.get("name")],
                "parent": asset.get("parent") or "",
                "crs": asset.get("crs") or "",
                "geometry_type": asset.get("geometry_type") or "",
                "bounds": asset.get("bounds") or [],
                "permission": asset.get("permission") or "public",
                "asset_profile": asset.get("asset_profile") or {},
                "schema_version": AREA_RESOLVER_VERSION,
                "version": asset.get("version") or "",
                "source": asset.get("source") or "asset_registry",
            }
        )
    return items


def area_by_asset_id(asset_id: str) -> dict[str, Any] | None:
    normalized = str(asset_id or "").strip()
    for item in list_area_index():
        if item["asset_id"] == normalized:
            return item
    return None


def _static_area_candidates(query: str = "", *, limit: int = 8) -> list[dict[str, Any]]:
    text = _normalize(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in list_area_index():
        aliases = [_normalize(value) for value in item.get("aliases", [])]
        score = sum(len(alias) for alias in aliases if alias and alias in text)
        if item["asset_id"] == "library:basin:shandianhe" and ("闪电河" in text or "shandian" in text):
            score += 1000
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (pair[0], pair[1]["asset_id"]), reverse=True)
    return [item for _, item in scored[: max(1, int(limit or 1))]]


def _first_existing_column(gdf: gpd.GeoDataFrame, names: list[str]) -> str:
    for name in names:
        if name in gdf.columns:
            return name
    return ""


def _clean_name(value: Any) -> str:
    return str(value or "").strip()


def _admin_query_terms(query: str) -> list[str]:
    raw = str(query or "").strip()
    terms = [raw]
    for match in re.findall(r"[\u4e00-\u9fff]{2,}(?:省|市|县|区|旗|州|盟)", raw):
        terms.append(match)
    compact = re.sub(r"[A-Za-z0-9_\-\s]+", "", raw)
    compact = re.sub(r"^(?:请|帮我|给我|下载|获取|查询|准备|裁剪|处理|进行)+", "", compact)
    compact = re.sub(r"(?:的|数据|范围|边界|行政区|流域|高程|地形).*$", "", compact)
    if compact:
        terms.append(compact)
    return list(dict.fromkeys(term for term in terms if term))


def _dissolved_candidate(
    manager: Any,
    selected: gpd.GeoDataFrame,
    *,
    level: str,
    name: str,
    province: str = "",
    city: str = "",
    source_name: str = "",
) -> dict[str, Any] | None:
    if selected.empty:
        return None
    if selected.crs is None:
        selected = selected.set_crs("EPSG:4326", allow_override=True)
    else:
        selected = selected.to_crs("EPSG:4326")
    selected = selected[selected.geometry.notna() & ~selected.geometry.is_empty].copy()
    if selected.empty:
        return None
    union_geom = selected.geometry.union_all() if hasattr(selected.geometry, "union_all") else selected.geometry.unary_union
    dissolved = gpd.GeoDataFrame(
        [{"name": name, "province": province, "city": city, "admin_level": level}],
        geometry=[union_geom],
        crs="EPSG:4326",
    )
    safe = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", f"{province}_{city}_{name}_{level}").strip("_") or "admin_boundary"
    dataset_name = manager.put_vector(f"{safe}_boundary", dissolved, filename=f"{safe}_boundary.geojson")
    minx, miny, maxx, maxy = [float(v) for v in dissolved.total_bounds]
    parts = ["admin", level, province, city, name]
    asset_id = ":".join(part for part in parts if part)
    return {
        "asset_id": asset_id,
        "name": name,
        "area_source": "local_admin_boundary",
        "admin_level": level,
        "parent": city or province or "中国",
        "province": province,
        "city": city,
        "crs": "EPSG:4326",
        "geometry_type": str(dissolved.geometry.iloc[0].geom_type),
        "geometry_asset_id": dataset_name,
        "dataset_name": dataset_name,
        "bounds": [minx, miny, maxx, maxy],
        "feature_count": int(len(selected)),
        "dissolved_feature_count": 1,
        "dissolve_method": "county_units_dissolve" if len(selected) > 1 else "single_unit",
        "source_dataset": source_name,
        "schema_version": AREA_RESOLVER_VERSION,
    }


def _dynamic_admin_candidates(query: str, manager: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    try:
        from core.admin_boundary import (
            _aliases,
            _cache_dir,
            _candidate_admin_archives,
            _safe_extract_zip,
            _text_match_mask,
            clean_admin_region_query,
        )
    except Exception:
        return []

    query_terms = _admin_query_terms(clean_admin_region_query(query))
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for archive in _candidate_admin_archives(manager):
        target = _cache_dir(manager, archive)
        marker = target / ".extracted"
        if not marker.exists():
            target.mkdir(parents=True, exist_ok=True)
            _safe_extract_zip(archive, target)
            marker.write_text(str(archive), encoding="utf-8")
        for shp in target.rglob("*.shp"):
            try:
                gdf = gpd.read_file(shp)
            except Exception:
                continue
            if gdf.empty or "geometry" not in gdf:
                continue
            matched_query = ""
            matched_aliases: list[str] = []
            mask = None
            for term in query_terms:
                aliases = _aliases(term)
                if not aliases:
                    continue
                candidate_mask = _text_match_mask(gdf, aliases)
                if bool(candidate_mask.any()):
                    matched_query = term
                    matched_aliases = aliases
                    mask = candidate_mask
                    break
            if mask is None or not bool(mask.any()):
                continue
            province_col = _first_existing_column(gdf, ["省级", "NAME_1"])
            city_col = _first_existing_column(gdf, ["地级", "NAME_2"])
            county_col = _first_existing_column(gdf, ["县级", "地名", "NAME_3", "ENG_NAME"])
            selected = gdf.loc[mask].copy()

            province_mask = None
            city_mask = None
            county_mask = None
            if province_col:
                province_mask = selected[province_col].astype(str).str.casefold().isin([str(alias).casefold() for alias in matched_aliases])
            if city_col:
                city_mask = selected[city_col].astype(str).str.casefold().isin([str(alias).casefold() for alias in matched_aliases])
            if county_col:
                county_mask = selected[county_col].astype(str).str.casefold().isin([str(alias).casefold() for alias in matched_aliases])

            groups: list[tuple[str, tuple[str, ...], gpd.GeoDataFrame]] = []
            if province_mask is not None and bool(province_mask.any()) and province_col:
                for province, group in selected.loc[province_mask].groupby(province_col, dropna=False):
                    groups.append(("province", (_clean_name(province), "", _clean_name(province)), group))
            elif city_mask is not None and bool(city_mask.any()) and city_col:
                keys = [col for col in [province_col, city_col] if col]
                for key, group in selected.loc[city_mask].groupby(keys, dropna=False):
                    values = key if isinstance(key, tuple) else ("", key)
                    province = _clean_name(values[0]) if len(values) > 1 else ""
                    city = _clean_name(values[-1])
                    groups.append(("city", (province, city, city), group))
            elif county_mask is not None and bool(county_mask.any()) and county_col:
                keys = [col for col in [province_col, city_col, county_col] if col]
                for key, group in selected.loc[county_mask].groupby(keys, dropna=False):
                    values = key if isinstance(key, tuple) else ("", "", key)
                    padded = ["", "", "", *[_clean_name(v) for v in values]][-3:]
                    province, city, county = padded
                    groups.append(("county", (province, city, county), group))
            else:
                name = str(matched_query or matched_aliases[0])
                groups.append(("unknown", ("", "", name), selected))

            for level, (province, city, name), group in groups:
                key = (level, province, city, name)
                if key in seen:
                    continue
                seen.add(key)
                candidate = _dissolved_candidate(
                    manager,
                    group,
                    level=level,
                    name=name,
                    province=province,
                    city=city,
                    source_name=shp.name,
                )
                if candidate:
                    candidates.append(candidate)
                    if len(candidates) >= limit:
                        return candidates
    return candidates


def resolve_area_candidates(query: str = "", *, limit: int = 8, manager: Any | None = None) -> list[dict[str, Any]]:
    text = _normalize(query)
    static = _static_area_candidates(query, limit=limit)
    if static and static[0].get("asset_id") == "library:basin:shandianhe":
        return static[:limit]
    if manager is not None:
        dynamic = _dynamic_admin_candidates(query, manager, limit=limit)
        if dynamic:
            return dynamic[:limit]
    return static[:limit]


def area_context(query: str = "", *, manager: Any | None = None) -> dict[str, Any]:
    candidates = resolve_area_candidates(query, manager=manager)
    names = [str(item.get("name") or "") for item in candidates]
    return {
        "schema_version": AREA_RESOLVER_VERSION,
        "area_candidates": candidates,
        "ambiguous": len(candidates) > 1 and bool(names[0]) and names.count(names[0]) > 1,
    }
