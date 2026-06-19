from __future__ import annotations

from typing import Any

from core.domestic_sources.gscloud_products import GSCLOUD_PRODUCTS
from core.product_catalog import product_catalog_context


GSCLOUD_DEM_CANDIDATE = {
    "product_key": "gscloud_dem",
    "name": "DEM",
    "resource_type": "dem",
    "aliases": ("dem", "elevation", "gdem", "高程"),
}


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _candidate_from_product(product_key: str, name: str, resource_type: str, aliases: tuple[str, ...], *, matched: bool) -> dict[str, Any]:
    return {
        "source_key": "gscloud",
        "product_key": product_key,
        "name": name,
        "resource_type": resource_type,
        "confirmation_required": True,
        "license_note": "Requires source availability, account/login state, and user confirmation before starting download.",
        "matched_query": matched,
        "source": "download_candidate_catalog",
        "aliases": list(aliases[:8]),
    }


def candidate_download_products(query: str, *, limit: int = 6) -> list[dict[str, Any]]:
    catalog = product_catalog_context(query, limit=limit)
    if catalog:
        return [
            {
                "source_key": item["source"],
                "product_key": item.get("source_product_key") or item["product_id"],
                "product_id": item["product_id"],
                "name": item["display_name_zh"],
                "display_name_zh": item["display_name_zh"],
                "resource_type": item["resource_type"],
                "supported_resolutions": item["supported_resolutions"],
                "temporal_requirement": item["temporal_requirement"],
                "confirmation_required": True,
                "license_note": item["login_or_license_requirement"],
                "matched_query": True,
                "source": "download_candidate_catalog",
                "catalog_source": "product_catalog",
                "tool_card": item["tool_card"],
                "download_adapter": item["download_adapter"],
                "unsupported_scenarios": item["unsupported_scenarios"],
                "alternatives": item["alternatives"],
            }
            for item in catalog
        ]
    text = _normalize(query)
    products: list[tuple[str, str, str, tuple[str, ...]]] = [
        (product.key, product.name, product.resource_type, product.aliases)
        for product in GSCLOUD_PRODUCTS.values()
    ]
    products.append(
        (
            str(GSCLOUD_DEM_CANDIDATE["product_key"]),
            str(GSCLOUD_DEM_CANDIDATE["name"]),
            str(GSCLOUD_DEM_CANDIDATE["resource_type"]),
            tuple(GSCLOUD_DEM_CANDIDATE["aliases"]),
        )
    )

    scored: list[tuple[int, dict[str, Any]]] = []
    for product_key, name, resource_type, aliases in products:
        terms = (product_key, name, resource_type, *aliases)
        matched = any(_normalize(term) and _normalize(term) in text for term in terms)
        score = 1 if matched else 0
        scored.append((score, _candidate_from_product(product_key, name, resource_type, aliases, matched=matched)))

    scored.sort(key=lambda item: (item[0], item[1]["product_key"]), reverse=True)
    return [item for _, item in scored[: max(1, int(limit or 1))]]
