from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from core.domestic_sources.gscloud_products import GSCLOUD_PRODUCTS
from core.domestic_sources.gscloud_scene_table import normalize_scene_date, scene_data_available
from core.product_catalog import product_by_id


def _now_version() -> str:
    return "scan-" + datetime.now().strftime("%Y%m%d%H%M%S")


def _query_gscloud_boundary(product, *, direction: str) -> str:
    """Read one dated record from the registered public GSCloud scene table."""
    dataset_id = str(getattr(product, "dataset_id", "") or "").strip()
    if not dataset_id:
        return ""
    access_url = str(getattr(product, "access_url", "") or "https://www.gscloud.cn/")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    headers = {
        "User-Agent": "GIS-Agent-Availability-Scanner/1.0 Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": access_url,
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        opener.open(Request(access_url, headers={"User-Agent": headers["User-Agent"]}), timeout=8).read()
    except Exception:
        pass

    page_size = 20
    max_pages = 25
    for page_number in range(1, max_pages + 1):
        table_info = {
            "pageSize": page_size,
            "pageNumber": page_number,
            "sortSet": [{"id": "dataexists", "sort": "desc"}, {"id": "datadate", "sort": direction}],
            "multiSort": True,
            "filterSet": {},
        }
        query = urlencode({"pid": dataset_id, "tableInfo": json.dumps(table_info, separators=(",", ":"))})
        request = Request(
            f"https://www.gscloud.cn/wsd/gscloud_wsd/dataset/query_data?{query}",
            headers=headers,
        )
        try:
            try:
                response_context = opener.open(request, timeout=8)
            except AttributeError:
                response_context = urlopen(request, timeout=8)  # nosec B310: fixed GSCloud endpoint above
            with response_context as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            continue
        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not scene_data_available(row.get("dataexists", "")):
                continue
            value = (
                normalize_scene_date(row.get("datadate"))
                or normalize_scene_date(row.get("dataid"))
                or normalize_scene_date(row.get("identifications"))
                or normalize_scene_date(row.get("landsat_product_identifier_l2"))
            )
            if value:
                return value
    return ""


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
