from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from .vector_rag import local_vector_rag_diagnostics


CHAIN_NAMES = ("answer_only_context", "retrieval_context", "result_summary_context")
PRIVATE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s`'\"，。；;]+|/(?:tmp|home|var|etc|root|Users)/[^\s`'\"，。；;]+|workspace[\\/](?:users|sessions)[^\s`'\"，。；;]*)",
    re.IGNORECASE,
)
LEGACY_ARTIFACT_URL_RE = re.compile(r"/api/(?:files/artifact|downloads/artifact)\?[^\s`'\"，。；;]+", re.IGNORECASE)


def _load_runnable_lambda() -> Any | None:
    try:
        from langchain_core.runnables import RunnableLambda
    except Exception:
        return None
    return RunnableLambda


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = LEGACY_ARTIFACT_URL_RE.sub("[hidden legacy artifact link]", text)
    text = PRIVATE_PATH_RE.sub("[hidden internal path]", text)
    return text[:limit]


def _snippet(item: Any) -> dict[str, str]:
    payload = _as_dict(item)
    return {
        "title": _clean_text(payload.get("title") or payload.get("knowledge_id"), 160),
        "content": _clean_text(payload.get("content"), 600),
    }


class _CallableChain:
    def __init__(self, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._fn = fn

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._fn(payload)


@dataclass(frozen=True, slots=True)
class RuntimeChainSpec:
    name: str
    purpose: str
    status: str = "partial"

    def to_metadata(self) -> dict[str, str]:
        return {"name": self.name, "purpose": self.purpose, "status": self.status}


class RuntimeChainAdapter:
    def __init__(self) -> None:
        self._runnable_lambda = _load_runnable_lambda()

    @property
    def lcel_available(self) -> bool:
        return self._runnable_lambda is not None

    def chain_specs(self) -> list[RuntimeChainSpec]:
        return [
            RuntimeChainSpec("answer_only_context", "Prepare answer-only chat context without tool execution."),
            RuntimeChainSpec("retrieval_context", "Package existing keyword/context retrieval snippets for prompt use."),
            RuntimeChainSpec("result_summary_context", "Package normalized execution facts for result summarization."),
        ]

    def diagnostics(self) -> dict[str, Any]:
        vector_rag = local_vector_rag_diagnostics()
        return {
            "status": "partial",
            "lcel_available": self.lcel_available,
            "standard_lcel_status": "partial",
            "vector_rag_status": vector_rag["status"],
            "full_vector_rag": vector_rag["full_vector_rag"],
            "retrieval_mode": "keyword_plus_local_tfidf_scaffold",
            "chains": [spec.to_metadata() for spec in self.chain_specs()],
        }

    def _chain(self, name: str) -> Any:
        handlers = {
            "answer_only_context": self._answer_only_context,
            "retrieval_context": self._retrieval_context,
            "result_summary_context": self._result_summary_context,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown runtime chain: {name}")
        if self._runnable_lambda is not None:
            return self._runnable_lambda(handler)
        return _CallableChain(handler)

    def invoke(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._chain(name).invoke(dict(payload or {}))

    def _answer_only_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = _as_dict(payload.get("context"))
        snippets = [_snippet(item) for item in _as_list(context.get("knowledge_snippets"))[:5]]
        return {
            "chain_name": "answer_only_context",
            "status": "prepared",
            "executes_tools": False,
            "prompt": _clean_text(payload.get("prompt"), 1200),
            "response_language": _clean_text(context.get("response_language"), 20),
            "snippets": snippets,
        }

    def _retrieval_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        snippets = [_snippet(item) for item in _as_list(payload.get("knowledge_snippets"))[:5]]
        return {
            "chain_name": "retrieval_context",
            "status": "prepared",
            "query": _clean_text(payload.get("query"), 600),
            "retrieval_mode": "keyword_plus_local_tfidf_scaffold",
            "vector_rag_status": "local_tfidf_scaffold",
            "full_vector_rag": False,
            "snippets": snippets,
        }

    def _result_summary_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        results = [item for item in _as_list(payload.get("normalized_results")) if isinstance(item, dict)]
        statuses = [str(item.get("status") or "").strip() for item in results if str(item.get("status") or "").strip()]
        return {
            "chain_name": "result_summary_context",
            "status": "prepared",
            "result_count": len(results),
            "statuses": list(dict.fromkeys(statuses)),
            "executes_tools": False,
        }
