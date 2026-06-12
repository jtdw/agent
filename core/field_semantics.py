from __future__ import annotations

import re
import unicodedata
from typing import Any


_SEPARATORS_RE = re.compile(r"[\s_\-./\\:：,，;；()（）\[\]【】{}]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def normalize_field_name(field_name: Any) -> str:
    text = unicodedata.normalize("NFKC", str(field_name or "")).strip().lower()
    text = _CAMEL_RE.sub("", text)
    text = _SEPARATORS_RE.sub("", text)
    return text


def _tokenize(value: Any) -> set[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    spaced = _CAMEL_RE.sub(" ", text)
    tokens = [token for token in _SEPARATORS_RE.split(spaced) if token]
    compact = normalize_field_name(text)
    if compact:
        tokens.append(compact)
    return set(tokens)


def build_field_aliases() -> dict[str, list[str]]:
    return {
        "人口密度": [
            "人口密度",
            "人口密度图",
            "pop_density",
            "population_density",
            "density_pop",
            "popdensity",
            "人口/面积",
            "renkoumidu",
        ],
        "人口": [
            "人口",
            "常住人口",
            "总人口",
            "户籍人口",
            "population",
            "pop",
            "pop_total",
            "total_population",
            "renkou",
        ],
        "面积": [
            "面积",
            "区域面积",
            "area",
            "shape_area",
            "geom_area",
            "mianji",
        ],
        "GDP": [
            "gdp",
            "GDP",
            "地区生产总值",
            "生产总值",
            "gross_domestic_product",
            "regional_gdp",
        ],
        "高程": [
            "高程",
            "海拔",
            "地形高程",
            "elevation",
            "dem",
            "alt",
            "altitude",
            "height",
            "gaocheng",
        ],
        "降水": [
            "降水",
            "降雨",
            "降水量",
            "降雨量",
            "precipitation",
            "rainfall",
            "rain",
            "precip",
            "jiangshui",
        ],
        "温度": [
            "温度",
            "气温",
            "地表温度",
            "temperature",
            "temp",
            "lst",
            "wendu",
        ],
        "NDVI": [
            "ndvi",
            "NDVI",
            "植被指数",
            "归一化植被指数",
            "vegetation_index",
            "veg_index",
        ],
        "坡度": [
            "坡度",
            "slope",
            "podu",
        ],
        "土地利用": [
            "土地利用",
            "用地类型",
            "土地覆盖",
            "landuse",
            "land_use",
            "lulc",
            "landcover",
            "land_cover",
        ],
        "县域": [
            "县域",
            "区县",
            "县",
            "行政区",
            "行政区划",
            "county",
            "district",
            "county_name",
            "county_code",
            "region",
            "xianyu",
            "quxian",
        ],
        "边界": [
            "边界",
            "边界线",
            "边界面",
            "行政边界",
            "县域边界",
            "boundary",
            "border",
            "geometry",
            "geom",
            "shape",
            "region_boundary",
        ],
        "研究区": [
            "研究区",
            "研究区域",
            "项目区",
            "分析区",
            "study_area",
            "studyarea",
            "aoi",
            "roi",
            "area_of_interest",
            "mask",
            "clip_boundary",
        ],
    }


def _detect_concepts(user_text: Any) -> list[str]:
    aliases = build_field_aliases()
    normalized_text = normalize_field_name(user_text)
    text = unicodedata.normalize("NFKC", str(user_text or "")).lower()
    hits: list[tuple[int, str]] = []
    for concept, names in aliases.items():
        concept_norm = normalize_field_name(concept)
        matched = concept in text or concept_norm in normalized_text
        if not matched:
            matched = any(normalize_field_name(alias) in normalized_text for alias in names if normalize_field_name(alias))
        if matched:
            hits.append((len(concept_norm), concept))
    hits.sort(key=lambda item: item[0], reverse=True)
    return [concept for _, concept in hits]


def _score_field_for_alias(field: str, alias: str, concept: str) -> float:
    field_norm = normalize_field_name(field)
    alias_norm = normalize_field_name(alias)
    concept_norm = normalize_field_name(concept)
    if not field_norm or not alias_norm:
        return 0.0
    if field_norm == alias_norm:
        return 1.0 if alias_norm == concept_norm else 0.96
    if field_norm == concept_norm:
        return 1.0
    field_tokens = _tokenize(field)
    alias_tokens = _tokenize(alias)
    if field_tokens & alias_tokens:
        if alias_norm in field_norm or field_norm in alias_norm:
            return 0.88
        return 0.72
    if alias_norm in field_norm:
        return 0.84
    if field_norm in alias_norm and len(field_norm) >= 3:
        return 0.70
    return 0.0


def rank_candidate_fields(user_concept: str, available_fields: list[Any]) -> list[dict[str, Any]]:
    aliases = build_field_aliases()
    concepts = [user_concept] if user_concept in aliases else _detect_concepts(user_concept)
    if not concepts and str(user_concept or "").strip():
        concepts = [str(user_concept)]

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for concept in concepts:
        names = aliases.get(concept, [concept])
        for field in available_fields or []:
            field_name = str(field)
            best_score = 0.0
            best_alias = ""
            best_alias_rank = len(names)
            for alias_rank, alias in enumerate(names):
                score = _score_field_for_alias(field_name, alias, concept)
                if score > best_score:
                    best_score = score
                    best_alias = alias
                    best_alias_rank = alias_rank
            if best_score >= 0.55 and field_name not in seen:
                seen.add(field_name)
                candidates.append(
                    {
                        "field": field_name,
                        "score": round(best_score, 3),
                        "concept": concept,
                        "matched_alias": best_alias,
                        "alias_rank": best_alias_rank,
                    }
                )

    candidates.sort(key=lambda item: (-float(item["score"]), int(item.get("alias_rank") or 0), len(str(item["field"])), str(item["field"])))
    return candidates


def match_user_field_concept(user_text: str, available_fields: list[Any]) -> dict[str, Any]:
    fields = [str(field) for field in available_fields or [] if str(field or "").strip()]
    concepts = _detect_concepts(user_text)
    by_field: dict[str, dict[str, Any]] = {}
    for concept in concepts:
        for item in rank_candidate_fields(concept, fields):
            field = str(item.get("field") or "")
            if not field:
                continue
            previous = by_field.get(field)
            if previous is None or float(item.get("score") or 0.0) > float(previous.get("score") or 0.0):
                by_field[field] = item

    all_candidates = list(by_field.values())
    all_candidates.sort(key=lambda item: (-float(item["score"]), int(item.get("alias_rank") or 0), len(str(item["field"])), str(item["field"])))
    if not all_candidates:
        return {
            "concept": concepts[0] if concepts else "",
            "best_field": "",
            "confidence": 0.0,
            "candidates": [],
            "needs_clarification": bool(concepts),
        }

    best = all_candidates[0]
    second_score = float(all_candidates[1]["score"]) if len(all_candidates) > 1 else 0.0
    confidence = float(best["score"])
    close_multiple = second_score >= 0.55 and confidence - second_score < 0.08
    return {
        "concept": best.get("concept", ""),
        "best_field": best.get("field", ""),
        "confidence": round(confidence, 3),
        "candidates": all_candidates[:5],
        "needs_clarification": confidence < 0.78 or close_multiple,
    }
