from __future__ import annotations

import json
import math
import os
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PRIVATE_METADATA_KEYS = {
    "path",
    "absolute_path",
    "relative_path",
    "workspace_dir",
    "token",
    "cookie",
    "password",
    "secret",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_text(value: Any, limit: int = 1200) -> str:
    return str(value or "").strip()[:limit]


def _public_metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in item.items()
        if str(key) not in PRIVATE_METADATA_KEYS and not any(marker in str(key).lower() for marker in PRIVATE_METADATA_KEYS)
    }


def _document_id(item: dict[str, Any], index: int = 0) -> str:
    return _clean_text(item.get("knowledge_id") or item.get("id") or item.get("knowledge_chunk_id") or f"doc_{index}", 180)


def _source_hashes(documents: list[dict[str, Any]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for index, item in enumerate(documents):
        clean = _public_metadata(_as_dict(item))
        doc_id = _document_id(clean, index)
        rendered = json.dumps(clean, ensure_ascii=False, sort_keys=True, default=str)
        hashes[doc_id] = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return hashes


def _redact_error(value: Any) -> str:
    text = str(value or "")
    for marker in ("secret-key", os.getenv("GIS_AGENT_EMBEDDING_API_KEY") or "", os.getenv("OPENAI_API_KEY") or ""):
        if marker:
            text = text.replace(marker, "[redacted]")
    return text[:500]


def _document_text(item: dict[str, Any]) -> str:
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    return " ".join(
        [
            _clean_text(item.get("title"), 300),
            _clean_text(item.get("content"), 2000),
            " ".join(str(tag) for tag in tags),
        ]
    )


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _requests_transport(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    import requests

    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


@dataclass(slots=True)
class APIEmbeddingClient:
    provider: str
    api_key: str
    model: str
    base_url: str
    timeout: float = 30.0
    transport: Any = None
    max_retries: int = 0
    retry_backoff_seconds: float = 0.5
    retry_sleep: Any = None

    def _endpoint(self) -> str:
        base = str(self.base_url or "").rstrip("/")
        return f"{base}/embeddings"

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": str(self.provider or "openai"),
            "model": str(self.model or ""),
            "base_url_configured": bool(str(self.base_url or "").strip()),
            "api_key_configured": bool(str(self.api_key or "").strip()),
            "transport": "injected" if self.transport is not None else "requests",
            "retry_policy": {
                "max_retries": max(0, int(self.max_retries or 0)),
                "backoff_seconds": max(0.0, float(self.retry_backoff_seconds or 0.0)),
            },
        }

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        inputs = [_clean_text(text, 8000) for text in texts]
        if not inputs:
            return []
        if not str(self.api_key or "").strip():
            raise RuntimeError("embedding api key is not configured")
        payload = {"model": self.model, "input": inputs}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        transport = self.transport or _requests_transport
        response: dict[str, Any] = {}
        max_retries = max(0, int(self.max_retries or 0))
        for attempt in range(max_retries + 1):
            try:
                response = transport(self._endpoint(), payload, headers, float(self.timeout or 30.0))
                break
            except Exception as exc:
                if attempt >= max_retries:
                    raise RuntimeError(f"EMBEDDING_PROVIDER_ERROR: {_redact_error(exc)}") from exc
                duration = max(0.0, float(self.retry_backoff_seconds or 0.0)) * (2**attempt)
                if duration > 0:
                    sleeper = self.retry_sleep or time.sleep
                    sleeper(duration)
        rows = response.get("data") if isinstance(response, dict) else []
        vectors: list[list[float]] = []
        for row in rows if isinstance(rows, list) else []:
            embedding = row.get("embedding") if isinstance(row, dict) else None
            if isinstance(embedding, list):
                vectors.append([float(value) for value in embedding])
        if len(vectors) != len(inputs):
            raise RuntimeError("embedding response count does not match input count")
        return vectors


def api_embedding_client_from_env() -> APIEmbeddingClient | None:
    api_key = str(os.getenv("GIS_AGENT_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    provider = str(os.getenv("GIS_AGENT_EMBEDDING_PROVIDER") or "openai").strip() or "openai"
    model = str(os.getenv("GIS_AGENT_EMBEDDING_MODEL") or "text-embedding-3-small").strip()
    base_url = str(os.getenv("GIS_AGENT_EMBEDDING_BASE_URL") or "https://api.openai.com/v1").strip()
    try:
        timeout = float(os.getenv("GIS_AGENT_EMBEDDING_TIMEOUT") or "30")
    except ValueError:
        timeout = 30.0
    return APIEmbeddingClient(provider=provider, api_key=api_key, model=model, base_url=base_url, timeout=timeout)


@dataclass(slots=True)
class PersistentVectorRAGIndex:
    store_path: Path
    documents: list[dict[str, Any]]
    vectors: list[list[float]]
    embedding_client: APIEmbeddingClient | None = None

    @classmethod
    def build(
        cls,
        store_path: str | Path,
        documents: list[dict[str, Any]],
        embedding_client: APIEmbeddingClient,
    ) -> "PersistentVectorRAGIndex":
        path = Path(store_path).resolve(strict=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        clean_docs = [_public_metadata(_as_dict(item)) for item in documents if isinstance(item, dict)]
        vectors = embedding_client.embed_texts([_document_text(item) for item in clean_docs]) if clean_docs else []
        payload = {
            "schema_version": "agent-runtime-vector-rag/v1",
            "backend": "api_embedding_persistent",
            "embedding": embedding_client.diagnostics(),
            "manifest": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "document_count": len(clean_docs),
                "source_hashes": _source_hashes(clean_docs),
            },
            "documents": [{"metadata": doc, "embedding": vector} for doc, vector in zip(clean_docs, vectors)],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return cls(store_path=path, documents=clean_docs, vectors=vectors, embedding_client=embedding_client)

    @classmethod
    def load(cls, store_path: str | Path, *, embedding_client: APIEmbeddingClient | None = None) -> "PersistentVectorRAGIndex":
        path = Path(store_path).resolve(strict=False)
        if not path.exists():
            return cls(store_path=path, documents=[], vectors=[], embedding_client=embedding_client)
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("documents") if isinstance(data, dict) else []
        documents: list[dict[str, Any]] = []
        vectors: list[list[float]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            documents.append(_public_metadata(_as_dict(row.get("metadata"))))
            vectors.append([float(value) for value in row.get("embedding", []) if isinstance(value, (int, float))])
        return cls(store_path=path, documents=documents, vectors=vectors, embedding_client=embedding_client)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "status": "api_embedding_persistent",
            "embedding_provider": (self.embedding_client.diagnostics().get("provider") if self.embedding_client else "api"),
            "vector_store": "local_json_persistent",
            "document_count": len(self.documents),
            "full_vector_rag": True,
        }

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        if not self.documents or not self.vectors or self.embedding_client is None:
            return []
        query_vectors = self.embedding_client.embed_texts([query])
        query_vector = query_vectors[0] if query_vectors else []
        ranked = sorted(enumerate(self.vectors), key=lambda pair: (-_cosine(query_vector, pair[1]), pair[0]))
        hits: list[dict[str, Any]] = []
        for index, vector in ranked[: max(1, int(limit or 1))]:
            score = _cosine(query_vector, vector)
            if score <= 0:
                continue
            doc = dict(self.documents[index])
            doc["score"] = round(score, 6)
            doc["retrieval_mode"] = "api_embedding_vector"
            hits.append(doc)
        return hits


@dataclass(slots=True)
class LocalVectorRAGIndex:
    documents: list[dict[str, Any]]
    vectorizer: Any = None
    matrix: Any = None

    @classmethod
    def from_documents(cls, documents: list[dict[str, Any]]) -> "LocalVectorRAGIndex":
        clean_docs = [_public_metadata(_as_dict(item)) for item in documents if isinstance(item, dict)]
        index = cls(documents=clean_docs)
        if not clean_docs:
            return index
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
            matrix = vectorizer.fit_transform([index._document_text(item) for item in clean_docs])
        except Exception:
            return index
        index.vectorizer = vectorizer
        index.matrix = matrix
        return index

    @staticmethod
    def _document_text(item: dict[str, Any]) -> str:
        return _document_text(item)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "status": "local_tfidf_scaffold",
            "embedding_provider": "sklearn_tfidf_char_ngrams",
            "vector_store": "in_memory_sklearn",
            "document_count": len(self.documents),
            "full_vector_rag": False,
        }

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        if not self.documents or self.vectorizer is None or self.matrix is None:
            return []
        try:
            from sklearn.metrics.pairwise import cosine_similarity

            query_vector = self.vectorizer.transform([_clean_text(query, 1200)])
            scores = cosine_similarity(query_vector, self.matrix)[0]
        except Exception:
            return []
        ranked = sorted(enumerate(scores), key=lambda pair: (-float(pair[1]), pair[0]))
        hits: list[dict[str, Any]] = []
        for index, score in ranked[: max(1, int(limit or 1))]:
            if float(score) <= 0:
                continue
            doc = dict(self.documents[index])
            doc["score"] = round(float(score), 6)
            doc["retrieval_mode"] = "local_tfidf_vector"
            hits.append(doc)
        return hits


def local_vector_rag_diagnostics() -> dict[str, Any]:
    api_configured = str(os.getenv("GIS_AGENT_VECTOR_RAG_BACKEND") or "").strip().lower() == "api" and api_embedding_client_from_env() is not None
    return {
        "status": "api_embedding_available" if api_configured else "local_tfidf_scaffold",
        "embedding_provider": "api_configured" if api_configured else "sklearn_tfidf_char_ngrams",
        "vector_store": "local_json_persistent" if api_configured else "in_memory_sklearn",
        "full_vector_rag": api_configured,
    }


def build_persistent_rag_index(
    store_path: str | Path,
    documents: list[dict[str, Any]],
    embedding_client: APIEmbeddingClient,
) -> dict[str, Any]:
    try:
        index = PersistentVectorRAGIndex.build(store_path, documents, embedding_client)
    except Exception as exc:
        return {
            "ok": False,
            "status": "provider_error",
            "error_code": "EMBEDDING_PROVIDER_ERROR",
            "message": _redact_error(exc),
        }
    diagnostics = index.diagnostics()
    return {
        "ok": True,
        "status": "indexed",
        "document_count": diagnostics["document_count"],
        "store_path": str(index.store_path),
        "vector_store": diagnostics["vector_store"],
    }


def check_vector_index_freshness(store_path: str | Path, documents: list[dict[str, Any]]) -> dict[str, Any]:
    path = Path(store_path).resolve(strict=False)
    expected_hashes = _source_hashes([_public_metadata(_as_dict(item)) for item in documents if isinstance(item, dict)])
    if not path.exists():
        return {
            "ok": False,
            "status": "missing",
            "document_count": len(documents),
            "stale_reasons": ["index_missing"],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "ok": False,
            "status": "unreadable",
            "document_count": len(documents),
            "stale_reasons": ["index_unreadable"],
        }
    manifest = _as_dict(data.get("manifest"))
    actual_hashes = _as_dict(manifest.get("source_hashes"))
    stale_reasons: list[str] = []
    if int(manifest.get("document_count") or -1) != len(expected_hashes):
        stale_reasons.append("document_count_changed")
    if actual_hashes != expected_hashes:
        stale_reasons.append("source_hash_changed")
    return {
        "ok": not stale_reasons,
        "status": "fresh" if not stale_reasons else "stale",
        "document_count": len(expected_hashes),
        "stale_reasons": stale_reasons,
    }


def evaluate_rag_retrieval(index: Any, cases: list[dict[str, Any]], *, top_k: int = 3) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    hit_count = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        query = str(case.get("query") or "")
        expected = {str(item) for item in case.get("expected_knowledge_ids", []) if str(item).strip()}
        hits = index.search(query, limit=top_k) if hasattr(index, "search") else []
        hit_ids = [str(item.get("knowledge_id") or item.get("id") or "") for item in hits if isinstance(item, dict)]
        hit = bool(expected & set(hit_ids))
        hit_count += 1 if hit else 0
        results.append(
            {
                "query": query,
                "expected_knowledge_ids": sorted(expected),
                "hit_knowledge_ids": hit_ids,
                "hit": hit,
            }
        )
    case_count = len(results)
    return {
        "case_count": case_count,
        "hit_count": hit_count,
        "recall_at_k": round(hit_count / case_count, 6) if case_count else 0.0,
        "top_k": top_k,
        "cases": results,
    }


def default_gis_rag_eval_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "soil_xgboost_workflow",
            "query": "How should the GIS agent prepare a soil moisture XGBoost modeling workflow?",
            "expected_knowledge_ids": ["soil_xgboost_workflow", "soil_xgb", "soil"],
        },
        {
            "case_id": "map_preview_formats",
            "query": "Which GIS output formats should be registered for map preview?",
            "expected_knowledge_ids": ["map_preview_formats", "map_format", "map"],
        },
        {
            "case_id": "artifact_download_safety",
            "query": "How should artifact downloads prevent leaking workspace paths or secrets?",
            "expected_knowledge_ids": ["artifact_download_safety", "download_safety", "artifact_security"],
        },
    ]


def evaluate_rag_default_readiness(
    eval_result: dict[str, Any],
    freshness: dict[str, Any],
    provider_status: dict[str, Any],
    *,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    threshold_dict = thresholds if isinstance(thresholds, dict) else {}
    min_recall = float(threshold_dict.get("min_recall_at_k", 0.8))
    min_case_count = int(threshold_dict.get("min_case_count", 3))
    recall = float(_as_dict(eval_result).get("recall_at_k") or 0.0)
    case_count = int(_as_dict(eval_result).get("case_count") or 0)
    provider = _as_dict(provider_status)
    provider_ok = bool(provider.get("ok")) or str(provider.get("status") or "").lower() in {
        "ok",
        "configured",
        "api_embedding_available",
    }
    index_fresh = bool(_as_dict(freshness).get("ok"))

    reasons: list[str] = []
    required_actions: list[str] = []
    if case_count < min_case_count:
        reasons.append("insufficient_eval_cases")
        required_actions.append("add_gis_eval_cases")
    if recall < min_recall:
        reasons.append("recall_below_threshold")
        required_actions.append("improve_retrieval_quality")
    if not index_fresh:
        reasons.append("index_not_fresh")
        required_actions.append("rebuild_vector_index")
    if not provider_ok:
        reasons.append("embedding_provider_unavailable")
        required_actions.append("fix_embedding_provider")

    ready = not reasons
    if ready:
        required_actions = ["manual_enablement_decision"]
    return {
        "ready": ready,
        "status": "ready_for_manual_enablement" if ready else "not_ready",
        "reasons": reasons,
        "required_actions": list(dict.fromkeys(required_actions)),
        "thresholds": {
            "min_recall_at_k": min_recall,
            "min_case_count": min_case_count,
        },
        "metrics": {
            "recall_at_k": recall,
            "case_count": case_count,
            "index_status": freshness.get("status") if isinstance(freshness, dict) else "",
            "provider_status": provider.get("status") if isinstance(provider, dict) else "",
        },
    }


def _inspect_vector_store_from_env() -> dict[str, Any]:
    store_path = str(os.getenv("GIS_AGENT_VECTOR_RAG_STORE") or "").strip()
    if not store_path:
        return {
            "configured": False,
            "exists": False,
            "status": "not_configured",
            "store_filename": "",
            "document_count": 0,
        }
    path = Path(store_path).resolve(strict=False)
    payload: dict[str, Any] = {
        "configured": True,
        "exists": path.exists(),
        "status": "missing",
        "store_filename": path.name,
        "document_count": 0,
    }
    if not path.exists():
        return payload
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {**payload, "status": "unreadable"}
    manifest = _as_dict(data.get("manifest"))
    source_hashes = _as_dict(manifest.get("source_hashes"))
    return {
        **payload,
        "status": "present_unverified",
        "backend": str(data.get("backend") or ""),
        "schema_version": str(data.get("schema_version") or ""),
        "created_at": str(manifest.get("created_at") or ""),
        "document_count": int(manifest.get("document_count") or 0),
        "source_hash_count": len(source_hashes),
    }


def agent_runtime_rag_readiness_report() -> dict[str, Any]:
    cases = default_gis_rag_eval_cases()
    backend = str(os.getenv("GIS_AGENT_VECTOR_RAG_BACKEND") or "local").strip().lower() or "local"
    client = api_embedding_client_from_env()
    provider = client.diagnostics() if client is not None else {
        "provider": str(os.getenv("GIS_AGENT_EMBEDDING_PROVIDER") or "openai"),
        "model": str(os.getenv("GIS_AGENT_EMBEDDING_MODEL") or "text-embedding-3-small"),
        "base_url_configured": bool(str(os.getenv("GIS_AGENT_EMBEDDING_BASE_URL") or "").strip()),
        "api_key_configured": False,
        "transport": "requests",
    }
    provider["credential_configured"] = bool(provider.get("api_key_configured"))
    provider_status = {
        "ok": backend != "api" or bool(provider.get("api_key_configured")),
        "status": "configured" if backend != "api" or bool(provider.get("api_key_configured")) else "missing_api_key",
    }
    store = _inspect_vector_store_from_env()
    freshness = {
        "ok": False,
        "status": store.get("status") if store.get("exists") else "missing",
        "document_count": store.get("document_count", 0),
        "stale_reasons": ["source_hash_unverified_read_only"],
    }
    eval_result = {
        "status": "not_run_no_embedding_cost",
        "case_count": len(cases),
        "hit_count": 0,
        "recall_at_k": 0.0,
        "top_k": 3,
        "cases": cases,
    }
    return {
        "schema_version": "agent-runtime-rag-readiness/v1",
        "mode": "read_only_no_embedding",
        "backend": backend,
        "provider": provider,
        "vector_store": store,
        "eval": eval_result,
        "readiness": evaluate_rag_default_readiness(eval_result, freshness, provider_status),
        "operations": {
            "embedding_calls_performed": 0,
            "rebuild_available": False,
            "eval_execution": "disabled_to_avoid_embedding_cost",
        },
    }
