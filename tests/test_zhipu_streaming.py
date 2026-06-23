from __future__ import annotations

from core.llm_config import LLMProviderConfig
from core.zhipu_json_client import ZhipuJSONClient


def _config() -> LLMProviderConfig:
    return LLMProviderConfig(
        provider="zai",
        model="glm-4.5-air",
        api_key_env="ZAI_API_KEY",
        api_key_present=True,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        timeout=30,
        temperature=0.1,
        max_retries=0,
        max_output_tokens=256,
        fallback_models=(),
        enable_llm_intent_classifier=False,
        fallback_to_rule_classifier=False,
    )


def test_zhipu_text_stream_parses_sse_deltas_and_omits_json_mode() -> None:
    captured: dict[str, object] = {}

    def transport(payload, _config):
        captured.update(payload)
        return [
            'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"，GIS"}}]}\n\n',
            'data: [DONE]\n\n',
        ]

    client = ZhipuJSONClient(_config(), api_key="secret", transport=transport, operation="answer_only")
    chunks = list(client.stream_text([("user", "解释 GIS")]))

    assert chunks == ["你好", "，GIS"]
    assert captured["stream"] is True
    assert "response_format" not in captured
