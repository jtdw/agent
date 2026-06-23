from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

from core.capability_config import CapabilityConfigStore
from core.product_catalog import product_by_id


ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "docs" / "knowledge_seed"


EXPECTED_FILES = [
    "01_gis_data_and_asset_roles.md",
    "02_crs_extent_resolution_nodata.md",
    "03_download_products_and_time_rules.md",
    "04_download_execution_and_failures.md",
    "05_raster_vector_table_workflows.md",
    "06_geospatial_xgboost_workflow.md",
    "07_result_interpretation_and_user_response.md",
    "08_security_and_data_lifecycle.md",
]


def _front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    header = text.split("---\n", 2)[1]
    data: dict[str, str] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", str(text or ""))}


def _retrieve_seed_docs(query: str, *, limit: int = 3) -> list[str]:
    scored: list[tuple[int, str]] = []
    query_tokens = _tokens(query)
    for filename in EXPECTED_FILES:
        path = SEED_DIR / filename
        text = path.read_text(encoding="utf-8")
        manifest = json.loads((SEED_DIR / "manifest.json").read_text(encoding="utf-8"))
        entry = next(item for item in manifest["documents"] if item["file"] == filename)
        haystack = _tokens(text + " " + " ".join(entry.get("tags", [])) + " " + " ".join(entry.get("retrieval_test_questions", [])))
        score = len(query_tokens & haystack)
        if score:
            scored.append((score, filename))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [filename for _, filename in scored[:limit]]


def test_seed_documents_have_draft_front_matter_manifest_and_queries() -> None:
    manifest_path = SEED_DIR / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "knowledge-seed-manifest/v1"
    assert [item["file"] for item in manifest["documents"]] == EXPECTED_FILES

    for index, filename in enumerate(EXPECTED_FILES, start=1):
        path = SEED_DIR / filename
        assert path.exists(), filename
        meta = _front_matter(path)
        assert meta["language"] == "zh-CN"
        assert meta["status"] == "draft"
        assert meta["reliability"] in {"high", "medium"}
        assert meta["source"].startswith("project-code:")
        entry = manifest["documents"][index - 1]
        assert entry["import_order"] == index
        assert len(entry["retrieval_test_questions"]) >= 2
        assert entry["status"] == "draft"
        assert entry["content_hash"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert entry["reviewed_at"] == "2026-06-22"
        assert entry["verified_against_code_revision"]
        assert entry["knowledge_type"]
        assert entry["owner"] == "system-knowledge-admin"
        assert entry["last_verified_by"] == "Codex"
        assert any(any("\u4e00" <= ch <= "\u9fff" for ch in tag) for tag in entry["tags"])


def test_seed_docs_are_reference_only_and_do_not_override_catalog_or_trigger_tools(tmp_path: Path) -> None:
    store = CapabilityConfigStore(tmp_path / "capabilities")
    doc = (SEED_DIR / "03_download_products_and_time_rules.md").read_text(encoding="utf-8")
    store.upsert_knowledge(
        {
            "knowledge_id": "seed_download_rules",
            "title": "下载规则种子",
            "source": "seed-test",
            "language": "zh-CN",
            "tags": ["download"],
            "applicable_scope": "data_download",
            "reliability": "high",
            "version": "seed-test",
            "status": "draft",
            "content": doc + "\n\n错误示例：这里声称 DEM 支持 5m，但这不能覆盖 Product Catalog。",
        }
    )

    assert store.retrieve_knowledge("DEM 5m 下载", limit=3) == []
    assert product_by_id("gscloud_dem_30m") is not None
    assert product_by_id("seed_download_rules") is None


def test_seed_retrieval_questions_route_to_expected_reference_documents() -> None:
    cases = {
        "下载闪电河流域 LST 需要什么时间范围": "03_download_products_and_time_rules.md",
        "下载任务 waiting_login 是否是失败": "04_download_execution_and_failures.md",
        "栅格 CRS 不一致 NoData 怎么处理": "02_crs_extent_resolution_nodata.md",
        "DEM 坡度坡向 当前工具是否支持": "05_raster_vector_table_workflows.md",
        "XGBoost 空间泄漏 随机划分 空间交叉验证": "06_geospatial_xgboost_workflow.md",
        "删除会话后 私有知识 artifact 是否还能访问": "08_security_and_data_lifecycle.md",
    }

    for query, expected in cases.items():
        assert expected in _retrieve_seed_docs(query, limit=3), query
