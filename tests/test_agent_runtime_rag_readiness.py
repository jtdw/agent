from __future__ import annotations


def test_rag_default_readiness_requires_fresh_index_provider_ok_and_recall_threshold() -> None:
    from core.agent_runtime.vector_rag import evaluate_rag_default_readiness

    thresholds = {"min_recall_at_k": 0.8, "min_case_count": 3}
    passing_eval = {"recall_at_k": 1.0, "case_count": 3}
    fresh_index = {"ok": True, "status": "fresh"}
    provider_ok = {"ok": True, "status": "ok"}

    ready = evaluate_rag_default_readiness(passing_eval, fresh_index, provider_ok, thresholds=thresholds)
    low_recall = evaluate_rag_default_readiness(
        {"recall_at_k": 0.66, "case_count": 3},
        fresh_index,
        provider_ok,
        thresholds=thresholds,
    )
    stale = evaluate_rag_default_readiness(passing_eval, {"ok": False, "status": "stale"}, provider_ok, thresholds=thresholds)
    provider_error = evaluate_rag_default_readiness(
        passing_eval,
        fresh_index,
        {"ok": False, "status": "provider_error"},
        thresholds=thresholds,
    )

    assert ready["ready"] is True
    assert ready["status"] == "ready_for_manual_enablement"
    assert ready["required_actions"] == ["manual_enablement_decision"]
    assert low_recall["ready"] is False
    assert "recall_below_threshold" in low_recall["reasons"]
    assert stale["ready"] is False
    assert "index_not_fresh" in stale["reasons"]
    assert provider_error["ready"] is False
    assert "embedding_provider_unavailable" in provider_error["reasons"]


def test_api_embedding_client_retries_transient_provider_errors_without_leaking_key() -> None:
    from core.agent_runtime.vector_rag import APIEmbeddingClient

    attempts: list[int] = []
    sleep_durations: list[float] = []

    def flaky_transport(_url: str, _payload: dict, _headers: dict, _timeout: float) -> dict:
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RuntimeError("temporary 429 for secret-key")
        return {"data": [{"embedding": [1.0, 0.0]}]}

    client = APIEmbeddingClient(
        provider="openai",
        api_key="secret-key",
        model="embedding-model",
        base_url="https://api.example/v1",
        transport=flaky_transport,
        max_retries=1,
        retry_backoff_seconds=0.25,
        retry_sleep=sleep_durations.append,
    )

    vectors = client.embed_texts(["soil"])

    assert vectors == [[1.0, 0.0]]
    assert attempts == [1, 2]
    assert sleep_durations == [0.25]
    assert "secret-key" not in str(client.diagnostics())


def test_api_embedding_client_reports_sanitized_provider_error_after_retry_budget() -> None:
    from core.agent_runtime.vector_rag import APIEmbeddingClient

    def failing_transport(_url: str, _payload: dict, _headers: dict, _timeout: float) -> dict:
        raise RuntimeError("temporary 500 for secret-key")

    client = APIEmbeddingClient(
        provider="openai",
        api_key="secret-key",
        model="embedding-model",
        base_url="https://api.example/v1",
        transport=failing_transport,
        max_retries=1,
        retry_backoff_seconds=0,
        retry_sleep=lambda _duration: None,
    )

    try:
        client.embed_texts(["soil"])
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected provider error")

    assert "EMBEDDING_PROVIDER_ERROR" in message
    assert "secret-key" not in message


def test_default_gis_rag_eval_cases_cover_core_gis_queries() -> None:
    from core.agent_runtime.vector_rag import default_gis_rag_eval_cases

    cases = default_gis_rag_eval_cases()
    case_ids = {str(case.get("case_id")) for case in cases}

    assert {"soil_xgboost_workflow", "map_preview_formats", "artifact_download_safety"} <= case_ids
    assert all(case.get("query") for case in cases)
    assert all(case.get("expected_knowledge_ids") for case in cases)
