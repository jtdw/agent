from __future__ import annotations

import io
import json
import os
import unittest
import warnings
from contextlib import redirect_stdout
from unittest import mock

from starlette.exceptions import StarletteDeprecationWarning

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
    from starlette.testclient import TestClient

from core.llm_intent_classifier import classify_intent_with_llm


class LLMConfigTests(unittest.TestCase):
    def clean_env(self, values: dict[str, str]):
        keys = [
            "LLM_PROVIDER",
            "LLM_MODEL",
            "LLM_API_KEY_ENV",
            "LLM_BASE_URL",
            "LLM_TIMEOUT",
            "LLM_MAX_RETRIES",
            "LLM_TEMPERATURE",
            "ENABLE_LLM_INTENT_CLASSIFIER",
            "FALLBACK_TO_RULE_CLASSIFIER",
            "OPENAI_API_KEY",
            "ZAI_API_KEY",
            "ZAI_MODEL",
            "ZAI_BASE_URL",
            "ZAI_INTENT_MODEL",
            "GIS_AGENT_ENABLE_LLM_INTENT",
        ]
        patch_values = {key: "" for key in keys}
        patch_values.update(values)
        return mock.patch.dict(os.environ, patch_values, clear=False)

    def test_missing_api_key_with_fallback_is_degraded_not_crashing(self) -> None:
        from core.llm_config import validate_llm_config

        with self.clean_env(
            {
                "LLM_PROVIDER": "zai",
                "LLM_MODEL": "glm-4.5-air",
                "FALLBACK_TO_RULE_CLASSIFIER": "1",
                "ENABLE_LLM_INTENT_CLASSIFIER": "1",
            }
        ):
            result = validate_llm_config()

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["fallback_to_rule_classifier"])
        self.assertTrue(any(error["code"] == "API_KEY_MISSING" for error in result["errors"]))

    def test_unsupported_provider_has_clear_error(self) -> None:
        from core.llm_config import validate_llm_config

        with self.clean_env({"LLM_PROVIDER": "unknown", "LLM_MODEL": "model"}):
            result = validate_llm_config()

        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["code"] == "UNSUPPORTED_PROVIDER" for error in result["errors"]))

    def test_empty_model_has_clear_error(self) -> None:
        from core.llm_config import validate_llm_config

        with self.clean_env({"LLM_PROVIDER": "openai", "LLM_MODEL": "", "OPENAI_API_KEY": "test-key"}):
            result = validate_llm_config()

        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["code"] == "MODEL_REQUIRED" for error in result["errors"]))

    def test_invalid_base_url_has_clear_error(self) -> None:
        from core.llm_config import validate_llm_config

        with self.clean_env(
            {
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "gpt-test",
                "OPENAI_API_KEY": "test-key",
                "LLM_BASE_URL": "not a url",
            }
        ):
            result = validate_llm_config()

        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(error["code"] == "BASE_URL_INVALID" for error in result["errors"]))

    def test_fake_provider_is_test_safe_without_network(self) -> None:
        from core.llm_config import check_llm_provider_health

        with self.clean_env({"LLM_PROVIDER": "fake", "LLM_MODEL": "fake-gis"}):
            result = check_llm_provider_health(skip_network=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider"], "fake")
        self.assertFalse(result["network_checked"])

    def test_network_health_uses_injected_client_without_leaking_key(self) -> None:
        from core.llm_config import check_llm_provider_health

        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def invoke(self, text: str) -> str:
                self.calls += 1
                return "OK"

        secret = "sk-network-secret-value"
        client = FakeClient()
        with self.clean_env(
            {
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "gpt-test",
                "OPENAI_API_KEY": secret,
                "LLM_BASE_URL": "https://api.openai.com/v1",
            }
        ):
            result = check_llm_provider_health(skip_network=False, client=client)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["ok"])
        self.assertTrue(result["network_checked"])
        self.assertEqual(client.calls, 1)
        self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))

    def test_network_health_failure_is_structured_and_key_safe(self) -> None:
        from core.llm_config import check_llm_provider_health

        class FailingClient:
            def invoke(self, text: str) -> str:
                raise RuntimeError("provider rejected sk-failure-secret-value")

        secret = "sk-failure-secret-value"
        with self.clean_env(
            {
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "gpt-test",
                "OPENAI_API_KEY": secret,
                "LLM_BASE_URL": "https://api.openai.com/v1",
            }
        ):
            result = check_llm_provider_health(skip_network=False, client=FailingClient())

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["network_checked"])
        self.assertTrue(any(warning["code"] == "LLM_HEALTH_CHECK_FAILED" for warning in result["warnings"]))
        self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))

    def test_errors_do_not_leak_real_api_key(self) -> None:
        from core.llm_config import validate_llm_config

        secret = "sk-real-secret-value"
        with self.clean_env(
            {
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "gpt-test",
                "OPENAI_API_KEY": secret,
                "LLM_BASE_URL": "not a url",
            }
        ):
            result = validate_llm_config()

        self.assertNotIn(secret, str(result))
        self.assertTrue(result["api_key_present"])

    def test_intent_classifier_uses_fallback_when_no_provider_key(self) -> None:
        with self.clean_env(
            {
                "LLM_PROVIDER": "zai",
                "LLM_MODEL": "glm-4.5-air",
                "ENABLE_LLM_INTENT_CLASSIFIER": "1",
                "FALLBACK_TO_RULE_CLASSIFIER": "1",
            }
        ):
            result = classify_intent_with_llm("plot a map", {}, {})

        self.assertFalse(result["available"])
        self.assertEqual(result["fallback_reason"], "llm_unavailable")

    def test_health_cli_supports_strict_deployment_exit_code(self) -> None:
        from scripts.check_llm_health import main

        with self.clean_env(
            {
                "LLM_PROVIDER": "zai",
                "LLM_MODEL": "glm-4.5-air",
                "FALLBACK_TO_RULE_CLASSIFIER": "1",
            }
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                default_code = main([])
            default_payload = json.loads(buf.getvalue())

            strict_buf = io.StringIO()
            with redirect_stdout(strict_buf):
                strict_code = main(["--strict"])
            strict_payload = json.loads(strict_buf.getvalue())

        self.assertEqual(default_code, 0)
        self.assertEqual(default_payload["status"], "degraded")
        self.assertEqual(strict_code, 1)
        self.assertEqual(strict_payload["status"], "degraded")

    def test_api_llm_health_and_status_are_key_safe(self) -> None:
        import api_server

        secret = "sk-api-secret-value"
        with self.clean_env(
            {
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "gpt-test",
                "OPENAI_API_KEY": secret,
                "LLM_BASE_URL": "https://api.openai.com/v1",
            }
        ):
            client = TestClient(api_server.app)
            health = client.get("/api/llm/health?network=false")
            status = client.get("/api/status")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(status.status_code, 200)
        self.assertNotIn(secret, health.text)
        self.assertNotIn(secret, status.text)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(status.json()["llm_status"]["provider"], "openai")


if __name__ == "__main__":
    unittest.main()
