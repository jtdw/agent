from __future__ import annotations

import tempfile
from pathlib import Path


def _embedding_client():
    from core.agent_runtime.vector_rag import APIEmbeddingClient

    def transport(_url: str, payload: dict, _headers: dict, _timeout: float) -> dict:
        rows = []
        for text in payload["input"]:
            lowered = str(text).lower()
            if "soil" in lowered or "xgboost" in lowered:
                rows.append({"embedding": [1.0, 0.0]})
            elif "map" in lowered or "preview" in lowered:
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


def _documents() -> list[dict]:
    return [
        {"knowledge_id": "soil", "title": "Soil XGBoost", "content": "soil xgboost workflow"},
        {"knowledge_id": "map", "title": "Map preview", "content": "map preview formats"},
        {"knowledge_id": "artifact_security", "title": "Download safety", "content": "artifact download safety"},
    ]


def test_rag_ops_status_is_read_only_and_does_not_require_embedding(monkeypatch) -> None:
    from core.agent_runtime.rag_ops import run_rag_ops

    monkeypatch.delenv("GIS_AGENT_EMBEDDING_API_KEY", raising=False)

    code, payload = run_rag_ops(["status"])

    assert code == 0
    assert payload["command"] == "status"
    assert payload["report"]["mode"] == "read_only_no_embedding"
    assert payload["report"]["operations"]["embedding_calls_performed"] == 0


def test_rag_ops_rebuild_requires_explicit_confirmation() -> None:
    from core.agent_runtime.rag_ops import run_rag_ops

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store_path = Path(tmp) / "vectors.json"
        code, payload = run_rag_ops(["rebuild", "--store", str(store_path)], embedding_client=_embedding_client(), document_loader=_documents)

    assert code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "CONFIRM_REBUILD_REQUIRED"
    assert not store_path.exists()


def test_rag_ops_rebuild_writes_index_without_leaking_key_or_absolute_path() -> None:
    from core.agent_runtime.rag_ops import run_rag_ops

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store_path = Path(tmp) / "vectors.json"
        code, payload = run_rag_ops(
            ["rebuild", "--store", str(store_path), "--confirm-rebuild"],
            embedding_client=_embedding_client(),
            document_loader=_documents,
        )

        assert code == 0
        assert store_path.exists()

    rendered = str(payload)
    assert payload["command"] == "rebuild"
    assert payload["result"]["ok"] is True
    assert payload["result"]["document_count"] == 3
    assert payload["result"]["store_filename"] == "vectors.json"
    assert "secret-key" not in rendered
    assert str(store_path) not in rendered


def test_rag_ops_eval_reports_recall_and_readiness_from_existing_index() -> None:
    from core.agent_runtime.rag_ops import run_rag_ops

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store_path = Path(tmp) / "vectors.json"
        rebuild_code, _ = run_rag_ops(
            ["rebuild", "--store", str(store_path), "--confirm-rebuild"],
            embedding_client=_embedding_client(),
            document_loader=_documents,
        )
        eval_code, payload = run_rag_ops(
            ["eval", "--store", str(store_path), "--top-k", "1"],
            embedding_client=_embedding_client(),
            document_loader=_documents,
            eval_cases=[
                {"query": "soil xgboost", "expected_knowledge_ids": ["soil"]},
                {"query": "map preview", "expected_knowledge_ids": ["map"]},
                {"query": "artifact download safety", "expected_knowledge_ids": ["artifact_security"]},
            ],
        )

    assert rebuild_code == 0
    assert eval_code == 0
    assert payload["command"] == "eval"
    assert payload["eval"]["recall_at_k"] == 1.0
    assert payload["readiness"]["ready"] is True
    assert payload["readiness"]["status"] == "ready_for_manual_enablement"
