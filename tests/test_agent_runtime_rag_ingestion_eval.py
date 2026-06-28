from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _embedding_client():
    from core.agent_runtime.vector_rag import APIEmbeddingClient

    def transport(_url: str, payload: dict, _headers: dict, _timeout: float) -> dict:
        rows = []
        for text in payload["input"]:
            lowered = str(text).lower()
            if "soil" in lowered or "土壤" in lowered or "xgboost" in lowered:
                rows.append({"embedding": [1.0, 0.0]})
            elif "map" in lowered or "地图" in lowered:
                rows.append({"embedding": [0.0, 1.0]})
            else:
                rows.append({"embedding": [0.5, 0.5]})
        return {"data": rows}

    return APIEmbeddingClient(
        provider="openai",
        api_key="secret-key",
        model="embedding-model",
        base_url="https://api.example/v1",
        transport=transport,
    )


def test_build_persistent_rag_index_records_fresh_manifest_and_source_hashes() -> None:
    from core.agent_runtime.vector_rag import build_persistent_rag_index, check_vector_index_freshness

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store_path = Path(tmp) / "vectors.json"
        documents = [
            {"knowledge_id": "soil", "title": "Soil XGBoost", "content": "soil XGBoost features"},
            {"knowledge_id": "map", "title": "Map", "content": "map preview formats"},
        ]

        result = build_persistent_rag_index(store_path, documents, _embedding_client())
        freshness = check_vector_index_freshness(store_path, documents)
        stale = check_vector_index_freshness(store_path, [*documents, {"knowledge_id": "new", "content": "new doc"}])

    assert result["ok"] is True
    assert result["status"] == "indexed"
    assert result["document_count"] == 2
    assert freshness == {"ok": True, "status": "fresh", "document_count": 2, "stale_reasons": []}
    assert stale["ok"] is False
    assert "document_count_changed" in stale["stale_reasons"]


def test_build_persistent_rag_index_reports_provider_failure_without_leaking_key() -> None:
    from core.agent_runtime.vector_rag import APIEmbeddingClient, build_persistent_rag_index

    def failing_transport(_url: str, _payload: dict, _headers: dict, _timeout: float) -> dict:
        raise RuntimeError("provider timeout with secret-key")

    client = APIEmbeddingClient(
        provider="openai",
        api_key="secret-key",
        model="embedding-model",
        base_url="https://api.example/v1",
        transport=failing_transport,
    )

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        result = build_persistent_rag_index(
            Path(tmp) / "vectors.json",
            [{"knowledge_id": "soil", "title": "Soil", "content": "soil"}],
            client,
        )

    rendered = json.dumps(result, ensure_ascii=False)
    assert result["ok"] is False
    assert result["status"] == "provider_error"
    assert result["error_code"] == "EMBEDDING_PROVIDER_ERROR"
    assert "secret-key" not in rendered


def test_evaluate_rag_retrieval_reports_recall_at_k() -> None:
    from core.agent_runtime.vector_rag import PersistentVectorRAGIndex, evaluate_rag_retrieval

    documents = [
        {"knowledge_id": "soil", "title": "Soil XGBoost", "content": "soil XGBoost features"},
        {"knowledge_id": "map", "title": "Map", "content": "map preview formats"},
    ]

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store_path = Path(tmp) / "vectors.json"
        PersistentVectorRAGIndex.build(store_path, documents, _embedding_client())
        index = PersistentVectorRAGIndex.load(store_path, embedding_client=_embedding_client())
        result = evaluate_rag_retrieval(
            index,
            [
                {"query": "soil xgboost", "expected_knowledge_ids": ["soil"]},
                {"query": "map preview", "expected_knowledge_ids": ["map"]},
            ],
            top_k=1,
        )

    assert result["case_count"] == 2
    assert result["hit_count"] == 2
    assert result["recall_at_k"] == 1.0
    assert result["cases"][0]["hit"] is True
