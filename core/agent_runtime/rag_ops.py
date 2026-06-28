from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from core.agent_runtime.vector_rag import (
    APIEmbeddingClient,
    PersistentVectorRAGIndex,
    agent_runtime_rag_readiness_report,
    api_embedding_client_from_env,
    build_persistent_rag_index,
    check_vector_index_freshness,
    default_gis_rag_eval_cases,
    evaluate_rag_default_readiness,
    evaluate_rag_retrieval,
)
from core.knowledge_base import retrieve_knowledge_snippets


DocumentLoader = Callable[[], list[dict[str, Any]]]


def _clean_text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _doc_key(item: dict[str, Any], index: int) -> str:
    return _clean_text(item.get("knowledge_chunk_id") or item.get("knowledge_id") or item.get("id") or f"doc_{index}", 180)


def _store_path(value: str | None = None) -> Path | None:
    raw = str(value or os.getenv("GIS_AGENT_VECTOR_RAG_STORE") or "").strip()
    return Path(raw).resolve(strict=False) if raw else None


def _public_index_result(result: dict[str, Any], store_path: Path) -> dict[str, Any]:
    public = {key: value for key, value in result.items() if key != "store_path"}
    public["store_filename"] = store_path.name
    return public


def collect_default_rag_documents(*, limit_per_query: int = 12) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    cases = default_gis_rag_eval_cases()
    for case in cases:
        query = str(case.get("query") or "")
        for item in retrieve_knowledge_snippets(query, limit=limit_per_query):
            if not isinstance(item, dict):
                continue
            key = _doc_key(item, len(documents))
            if key in seen:
                continue
            seen.add(key)
            documents.append(dict(item))
    return documents


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core.agent_runtime.rag_ops")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("status", help="Read RAG readiness status without embedding calls.")

    rebuild = subcommands.add_parser("rebuild", help="Rebuild the local persistent vector RAG index.")
    rebuild.add_argument("--store", default="", help="Vector store JSON path. Defaults to GIS_AGENT_VECTOR_RAG_STORE.")
    rebuild.add_argument("--confirm-rebuild", action="store_true", help="Required guard for writing the vector store.")

    eval_cmd = subcommands.add_parser("eval", help="Evaluate retrieval recall against GIS RAG eval cases.")
    eval_cmd.add_argument("--store", default="", help="Vector store JSON path. Defaults to GIS_AGENT_VECTOR_RAG_STORE.")
    eval_cmd.add_argument("--top-k", type=int, default=3)

    return parser


def _embedding_client_or_error(client: APIEmbeddingClient | None = None) -> tuple[APIEmbeddingClient | None, dict[str, Any] | None]:
    resolved = client or api_embedding_client_from_env()
    if resolved is None:
        return None, {
            "ok": False,
            "error_code": "EMBEDDING_PROVIDER_NOT_CONFIGURED",
            "message": "embedding provider is not configured",
        }
    return resolved, None


def run_rag_ops(
    argv: Sequence[str],
    *,
    embedding_client: APIEmbeddingClient | None = None,
    document_loader: DocumentLoader | None = None,
    eval_cases: list[dict[str, Any]] | None = None,
) -> tuple[int, dict[str, Any]]:
    args = _parser().parse_args(list(argv))
    loader = document_loader or collect_default_rag_documents

    if args.command == "status":
        return 0, {"ok": True, "command": "status", "report": agent_runtime_rag_readiness_report()}

    store_path = _store_path(getattr(args, "store", ""))
    if store_path is None:
        return 2, {"ok": False, "command": args.command, "error_code": "VECTOR_STORE_REQUIRED"}

    if args.command == "rebuild":
        if not bool(getattr(args, "confirm_rebuild", False)):
            return (
                2,
                {
                    "ok": False,
                    "command": "rebuild",
                    "error_code": "CONFIRM_REBUILD_REQUIRED",
                    "message": "pass --confirm-rebuild to write the vector store",
                },
            )
        client, error = _embedding_client_or_error(embedding_client)
        if error is not None:
            return 2, {"command": "rebuild", **error}
        documents = loader()
        result = build_persistent_rag_index(store_path, documents, client)
        code = 0 if result.get("ok") else 1
        return code, {
            "ok": bool(result.get("ok")),
            "command": "rebuild",
            "result": _public_index_result(result, store_path),
            "document_count": len(documents),
        }

    if args.command == "eval":
        client, error = _embedding_client_or_error(embedding_client)
        if error is not None:
            return 2, {"command": "eval", **error}
        documents = loader()
        cases = eval_cases if isinstance(eval_cases, list) else default_gis_rag_eval_cases()
        index = PersistentVectorRAGIndex.load(store_path, embedding_client=client)
        eval_result = evaluate_rag_retrieval(index, cases, top_k=max(1, int(args.top_k or 1)))
        freshness = check_vector_index_freshness(store_path, documents)
        readiness = evaluate_rag_default_readiness(eval_result, freshness, {"ok": True, "status": "configured"})
        return 0, {
            "ok": True,
            "command": "eval",
            "store_filename": store_path.name,
            "eval": eval_result,
            "freshness": freshness,
            "readiness": readiness,
        }

    return 2, {"ok": False, "command": str(args.command or ""), "error_code": "UNKNOWN_COMMAND"}


def main(argv: Sequence[str] | None = None) -> int:
    code, payload = run_rag_ops(sys.argv[1:] if argv is None else argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
