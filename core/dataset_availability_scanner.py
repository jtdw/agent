from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.domestic_sources.gscloud_products import GSCLOUD_PRODUCTS
from core.product_catalog import product_by_id


def _now_version() -> str:
    return "scan-" + datetime.now().strftime("%Y%m%d%H%M%S")


def _query_gscloud_boundary(product, *, direction: str) -> str:
    """Read one dated record from the registered public GSCloud scene table."""
    dataset_id = str(getattr(product, "dataset_id", "") or "").strip()
    if not dataset_id:
        return ""
    table_info = {
        "pageSize": 1,
        "pageNumber": 1,
        "sortSet": [{"id": "datadate", "sort": direction}],
        "filterSet": {"dataexists": "1"},
    }
    query = urlencode({"pid": dataset_id, "tableInfo": json.dumps(table_info, separators=(",", ":"))})
    request = Request(
        f"https://www.gscloud.cn/wsd/gscloud_wsd/dataset/query_data?{query}",
        headers={"User-Agent": "GIS-Agent-Availability-Scanner/1.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=8) as response:  # nosec B310: fixed GSCloud endpoint above
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(rows, list) or not rows:
        return ""
    value = rows[0].get("datadate") if isinstance(rows[0], dict) else ""
    return str(value or "").strip().split(" ", 1)[0]


def _source_temporal_coverage(product, gscloud_product) -> tuple[dict[str, str], str, list[str]]:
    if str(product.get("temporal_requirement") or "none") == "none":
        return {}, "not_applicable", ["该产品不以时间范围作为下载约束。"]
    if gscloud_product is None:
        return {}, "source_metadata_unavailable", ["当前产品没有受控的数据源时间查询适配器。"]
    try:
        start = _query_gscloud_boundary(gscloud_product, direction="asc")
        end = _query_gscloud_boundary(gscloud_product, direction="desc")
    except Exception as exc:
        return {}, "source_metadata_failed", [f"未能读取数据源公开场景表：{type(exc).__name__}。请稍后重试或人工复核。"]
    if not start or not end:
        return {}, "source_metadata_empty", ["数据源公开场景表未返回可用日期记录；该结果不能作为可下载性结论。"]
    return {"start": start, "end": end}, "public_scene_table", ["时间范围来自数据源公开场景表；具体区域、权限和文件可用性仍在提交下载前校验。"]


def scan_dataset_availability(product_id: str, *, scan_method: str = "catalog_metadata", actor: str = "", summary: str = "") -> dict[str, Any]:
    product = product_by_id(product_id)
    if not product:
        raise FileNotFoundError(f"Product Catalog 中不存在该产品: {product_id}")
    method = str(scan_method or "catalog_metadata").strip().lower()
    if method not in {"catalog_metadata", "public_page"}:
        raise ValueError("当前仅支持 catalog_metadata 或 public_page 扫描模式。")

    source_key = str(product.get("source_product_key") or "")
    gscloud_product = GSCLOUD_PRODUCTS.get(source_key)
    coverage, coverage_method, coverage_warnings = _source_temporal_coverage(product, gscloud_product)
    warnings = [
        "该扫描结果默认保存为 draft，不会直接影响 Planner 或 Validator。",
        *coverage_warnings,
    ]
    if method == "public_page":
        warnings.append("public_page 模式当前只记录公开产品入口；详细年份范围仍需场景表扫描或人工审核。")

    return {
        "product_id": product["product_id"],
        "source_product_key": source_key,
        "display_name_zh": product.get("display_name_zh") or product["product_id"],
        "source": product.get("source") or "",
        "source_url": gscloud_product.access_url if gscloud_product else "",
        "temporal_requirement": product.get("temporal_requirement") or "none",
        "temporal_coverage": coverage,
        "supported_formats": list(product.get("supported_output_format") or []),
        "supported_resolutions": list(product.get("supported_resolutions") or []),
        "spatial_coverage": product.get("spatial_coverage") or "",
        "login_or_license_requirement": product.get("login_or_license_requirement") or "",
        "verification_method": f"{method}_scan:{coverage_method}",
        "scan_summary": summary or "从当前 Product Catalog 与受控产品入口生成可用性草稿。",
        "warnings": warnings,
        "status": "draft",
        "version": _now_version(),
        "created_by": actor,
        "updated_by": actor,
    }
