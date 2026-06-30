from __future__ import annotations

from pathlib import Path


def test_runtime_chain_adapter_reports_partial_lcel_and_local_vector_rag_scaffold() -> None:
    from core.agent_runtime.chains import RuntimeChainAdapter

    diagnostics = RuntimeChainAdapter().diagnostics()

    assert diagnostics["status"] == "partial"
    assert diagnostics["vector_rag_status"] == "local_tfidf_scaffold"
    assert diagnostics["full_vector_rag"] is False
    assert diagnostics["retrieval_mode"] == "keyword_plus_local_tfidf_scaffold"
    assert {item["name"] for item in diagnostics["chains"]} == {
        "answer_only_context",
        "retrieval_context",
        "result_summary_context",
    }


def test_runtime_chain_adapter_invokes_retrieval_context_without_exposing_raw_paths() -> None:
    from core.agent_runtime.chains import RuntimeChainAdapter

    result = RuntimeChainAdapter().invoke(
        "retrieval_context",
        {
            "query": "土壤水分 XGBoost",
            "knowledge_snippets": [
                {
                    "title": "XGBoost 建模",
                    "content": "需要明确目标变量和特征字段。",
                    "path": "E:/secret/private.md",
                }
            ],
        },
    )

    assert result["chain_name"] == "retrieval_context"
    assert result["retrieval_mode"] == "keyword_plus_local_tfidf_scaffold"
    assert result["vector_rag_status"] == "local_tfidf_scaffold"
    assert result["full_vector_rag"] is False
    assert result["snippets"] == [{"title": "XGBoost 建模", "content": "需要明确目标变量和特征字段。"}]
    assert "secret" not in str(result)


def test_runtime_chain_adapter_redacts_private_paths_inside_public_snippets() -> None:
    from core.agent_runtime.chains import RuntimeChainAdapter

    result = RuntimeChainAdapter().invoke(
        "answer_only_context",
        {
            "prompt": "Explain /tmp/private/runtime.log and E:/secret/data.shp",
            "context": {
                "response_language": "zh-CN",
                "knowledge_snippets": [
                    {
                        "title": "Internal note E:/secret/private.md",
                        "content": "Debug file /tmp/private/runtime.log and legacy link /api/files/artifact?path=derived/private.csv",
                    }
                ],
            },
        },
    )

    rendered = str(result)

    assert result["chain_name"] == "answer_only_context"
    assert "E:/secret" not in rendered
    assert "/tmp/private" not in rendered
    assert "/api/files/artifact" not in rendered
    assert "runtime.log" not in rendered
    assert "private.csv" not in rendered


def test_runtime_diagnostics_include_chain_adapter_boundary() -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    runtime = GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=True, mode="shadow"),
    )

    diagnostics = runtime.diagnostics()

    assert diagnostics["chain_adapter"]["status"] == "partial"
    assert diagnostics["chain_adapter"]["vector_rag_status"] == "local_tfidf_scaffold"
    assert diagnostics["chain_adapter"]["full_vector_rag"] is False
