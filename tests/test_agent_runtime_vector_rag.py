from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_local_vector_rag_index_retrieves_relevant_documents_without_sensitive_metadata() -> None:
    from core.agent_runtime.vector_rag import LocalVectorRAGIndex

    index = LocalVectorRAGIndex.from_documents(
        [
            {
                "knowledge_id": "soil_xgb",
                "title": "土壤水分建模",
                "content": "土壤水分 XGBoost 需要目标变量、特征字段和空间验证。",
                "path": "E:/secret/soil.md",
            },
            {
                "knowledge_id": "map_format",
                "title": "地图格式",
                "content": "GeoJSON 和 GeoTIFF 可以用于地图预览。",
            },
        ]
    )

    hits = index.search("土壤水分 XGBoost 特征", limit=1)

    assert hits[0]["knowledge_id"] == "soil_xgb"
    assert hits[0]["score"] > 0
    assert hits[0]["retrieval_mode"] == "local_tfidf_vector"
    assert "secret" not in str(hits[0])
    assert index.diagnostics()["status"] == "local_tfidf_scaffold"
    assert index.diagnostics()["full_vector_rag"] is False


def test_local_vector_rag_index_handles_empty_documents() -> None:
    from core.agent_runtime.vector_rag import LocalVectorRAGIndex

    index = LocalVectorRAGIndex.from_documents([])

    assert index.search("anything") == []
    assert index.diagnostics()["document_count"] == 0


def test_runtime_chain_adapter_reports_local_vector_rag_scaffold() -> None:
    from core.agent_runtime.chains import RuntimeChainAdapter

    diagnostics = RuntimeChainAdapter().diagnostics()

    assert diagnostics["vector_rag_status"] == "local_tfidf_scaffold"
    assert diagnostics["full_vector_rag"] is False


def test_context_builder_vector_rag_context_is_opt_in(monkeypatch) -> None:
    from core.config import Settings
    from core.context_builder import build_conversation_context
    from core.service import GISWorkspaceService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))

        monkeypatch.delenv("GIS_AGENT_ENABLE_VECTOR_RAG_CONTEXT", raising=False)
        default_context = build_conversation_context(
            "土壤水分 XGBoost 特征",
            {"intent": "modeling"},
            {},
            service.manager,
            service.dashboard(),
        )

        monkeypatch.setenv("GIS_AGENT_ENABLE_VECTOR_RAG_CONTEXT", "1")
        vector_context = build_conversation_context(
            "土壤水分 XGBoost 特征",
            {"intent": "modeling"},
            {},
            service.manager,
            service.dashboard(),
        )

    assert "vector_knowledge_snippets" not in default_context
    assert vector_context["rag_trace"]["vector_rag_status"] == "local_tfidf_scaffold"
    assert vector_context["rag_trace"]["full_vector_rag"] is False
    assert vector_context["vector_knowledge_snippets"]
    assert vector_context["vector_knowledge_snippets"][0]["retrieval_mode"] == "local_tfidf_vector"


def test_api_embedding_client_uses_openai_compatible_payload_without_exposing_key() -> None:
    from core.agent_runtime.vector_rag import APIEmbeddingClient

    captured: dict = {}

    def transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["timeout"] = timeout
        return {"data": [{"embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}]}

    client = APIEmbeddingClient(
        provider="openai",
        api_key="secret-key",
        model="text-embedding-3-small",
        base_url="https://api.example/v1",
        transport=transport,
    )

    vectors = client.embed_texts(["soil", "map"])

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert captured["url"] == "https://api.example/v1/embeddings"
    assert captured["payload"] == {"model": "text-embedding-3-small", "input": ["soil", "map"]}
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in json.dumps(client.diagnostics(), ensure_ascii=False)


def test_persistent_api_vector_index_round_trips_and_searches() -> None:
    from core.agent_runtime.vector_rag import APIEmbeddingClient, PersistentVectorRAGIndex

    embeddings = {
        "土壤水分 土壤水分 XGBoost": [1.0, 0.0],
        "地图 地图格式": [0.0, 1.0],
        "土壤水分": [1.0, 0.0],
    }

    def transport(_url: str, payload: dict, _headers: dict, _timeout: float) -> dict:
        return {"data": [{"embedding": embeddings[text]} for text in payload["input"]]}

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store_path = Path(tmp) / "api_vectors.json"
        client = APIEmbeddingClient(
            provider="openai",
            api_key="secret-key",
            model="embedding-model",
            base_url="https://api.example/v1",
            transport=transport,
        )
        index = PersistentVectorRAGIndex.build(
            store_path,
            [
                {"knowledge_id": "soil", "title": "土壤水分", "content": "土壤水分 XGBoost"},
                {"knowledge_id": "map", "title": "地图", "content": "地图格式", "absolute_path": "E:/secret/map.md"},
            ],
            client,
        )
        reloaded = PersistentVectorRAGIndex.load(store_path, embedding_client=client)
        hits = reloaded.search("土壤水分", limit=1)

    assert index.diagnostics()["status"] == "api_embedding_persistent"
    assert hits[0]["knowledge_id"] == "soil"
    assert hits[0]["retrieval_mode"] == "api_embedding_vector"
    assert "secret" not in str(hits[0])


def test_context_builder_can_use_api_vector_backend_with_fallback(monkeypatch) -> None:
    from core.config import Settings
    from core.context_builder import build_conversation_context
    from core.service import GISWorkspaceService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
        monkeypatch.setenv("GIS_AGENT_ENABLE_VECTOR_RAG_CONTEXT", "1")
        monkeypatch.setenv("GIS_AGENT_VECTOR_RAG_BACKEND", "api")
        monkeypatch.setenv("GIS_AGENT_EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("GIS_AGENT_EMBEDDING_BASE_URL", "https://api.example/v1")
        monkeypatch.setenv("GIS_AGENT_EMBEDDING_MODEL", "embedding-model")
        monkeypatch.setenv("GIS_AGENT_VECTOR_RAG_STORE", str(Path(tmp) / "vectors.json"))

        def fake_client_from_env():
            from core.agent_runtime.vector_rag import APIEmbeddingClient

            def transport(_url: str, payload: dict, _headers: dict, _timeout: float) -> dict:
                vectors = [[1.0, 0.0] if "XGBoost" in text else [0.0, 1.0] for text in payload["input"]]
                return {"data": [{"embedding": vector} for vector in vectors]}

            return APIEmbeddingClient(
                provider="openai",
                api_key="test-key",
                model="embedding-model",
                base_url="https://api.example/v1",
                transport=transport,
            )

        monkeypatch.setattr("core.agent_runtime.vector_rag.api_embedding_client_from_env", fake_client_from_env)

        context = build_conversation_context(
            "土壤水分 XGBoost",
            {"intent": "modeling"},
            {},
            service.manager,
            service.dashboard(),
        )

    assert context["rag_trace"]["vector_rag_status"] == "api_embedding_persistent"
    assert context["rag_trace"]["full_vector_rag"] is True
    assert context["vector_knowledge_snippets"][0]["retrieval_mode"] == "api_embedding_vector"
