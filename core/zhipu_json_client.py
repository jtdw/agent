from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Iterator
from urllib.parse import urljoin

from .llm_config import LLMProviderConfig
from .llm_usage import record_llm_usage


class LLMProviderError(RuntimeError):
    def __init__(self, kind: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


def _messages_payload(messages: Any) -> list[dict[str, str]]:
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    items: list[dict[str, str]] = []
    for item in messages if isinstance(messages, list) else []:
        if isinstance(item, tuple) and len(item) >= 2:
            items.append({"role": str(item[0]), "content": str(item[1])})
        elif isinstance(item, dict):
            role = str(item.get("role") or "user")
            content = str(item.get("content") or "")
            items.append({"role": role, "content": content})
    return items or [{"role": "user", "content": json.dumps(messages, ensure_ascii=False, default=str)}]


def _endpoint(base_url: str) -> str:
    base = str(base_url or "https://open.bigmodel.cn/api/paas/v4/").rstrip("/") + "/"
    return urljoin(base, "chat/completions")


def _cached_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        try:
            return int(details.get("cached_tokens") or 0)
        except Exception:
            return 0
    try:
        return int(usage.get("cached_tokens") or 0)
    except Exception:
        return 0


def _classify_error(status_code: int | None, body: str, exc: Exception | None = None) -> str:
    text = f"{body} {exc or ''}".lower()
    if status_code == 429 or "rate limit" in text or "too many requests" in text or "限流" in text:
        return "rate_limited"
    if status_code in {401, 403} and any(token in text for token in ("safe", "sensitive", "moderation", "内容安全", "安全")):
        return "safety_blocked"
    if any(token in text for token in ("sensitive", "moderation", "内容安全", "安全拦截", "unsafe")):
        return "safety_blocked"
    if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in text or "timeout" in text:
        return "timeout"
    return "provider_error"


class ZhipuJSONClient:
    """Minimal GLM chat-completions JSON-mode client.

    It never sends tools/function definitions. The existing TaskPlan, Validator,
    permission gate, and Durable Job path remain the only execution authority.
    """

    def __init__(self, config: LLMProviderConfig, *, api_key: str, transport: Any | None = None, operation: str = "planner"):
        self.config = config
        self.api_key = str(api_key or "")
        self.transport = transport
        self.operation = operation
        self.last_usage: dict[str, Any] = {}
        self.last_cached_tokens = 0
        self.last_latency_ms = 0
        self.last_retry_count = 0
        self.last_model = config.model
        self.last_status = ""

    def _payload(self, messages: Any, *, model: str | None = None) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": _messages_payload(messages),
            "temperature": self.config.temperature,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if model:
            payload["model"] = model
        if int(getattr(self.config, "max_output_tokens", 0) or 0) > 0:
            payload["max_tokens"] = int(self.config.max_output_tokens)
        return payload

    def _stream_payload(self, messages: Any, *, model: str | None = None) -> dict[str, Any]:
        payload = {
            "model": model or self.config.model,
            "messages": _messages_payload(messages),
            "temperature": self.config.temperature,
            "stream": True,
        }
        if int(getattr(self.config, "max_output_tokens", 0) or 0) > 0:
            payload["max_tokens"] = int(self.config.max_output_tokens)
        return payload

    def _request_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        if callable(self.transport):
            return self.transport(payload, self.config)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            _endpoint(self.config.base_url),
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=float(self.config.timeout or 60)) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LLMProviderError(_classify_error(exc.code, body, exc), "LLM provider request failed.", status_code=exc.code) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LLMProviderError("timeout", "LLM provider request timed out.") from exc
        except urllib.error.URLError as exc:
            raise LLMProviderError(_classify_error(None, "", exc), "LLM provider request failed.") from exc

    def _iter_stream_once(self, payload: dict[str, Any]) -> Iterator[str]:
        if callable(self.transport):
            response = self.transport(payload, self.config)
            if isinstance(response, dict):
                yield "data: " + json.dumps(response, ensure_ascii=False)
                return
            for chunk in response if isinstance(response, (list, tuple)) or hasattr(response, "__iter__") else []:
                yield str(chunk)
            return
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            _endpoint(self.config.base_url),
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=float(self.config.timeout or 60)) as response:
                for raw in response:
                    yield raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LLMProviderError(_classify_error(exc.code, body, exc), "LLM provider stream request failed.", status_code=exc.code) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LLMProviderError("timeout", "LLM provider stream request timed out.") from exc
        except urllib.error.URLError as exc:
            raise LLMProviderError(_classify_error(None, "", exc), "LLM provider stream request failed.") from exc

    def _models(self) -> list[str]:
        models = [str(self.config.model or "").strip()]
        models.extend(str(item).strip() for item in getattr(self.config, "fallback_models", ()) if str(item).strip())
        return list(dict.fromkeys(item for item in models if item))

    def _request(self, messages: Any) -> dict[str, Any]:
        retryable = {"timeout", "rate_limited", "provider_error"}
        max_retries = max(0, int(getattr(self.config, "max_retries", 0) or 0))
        last_error: LLMProviderError | None = None
        retry_count = 0
        started = time.perf_counter()
        for model in self._models():
            payload = self._payload(messages, model=model)
            for attempt in range(max_retries + 1):
                self.last_model = model
                try:
                    response = self._request_once(payload)
                    self.last_latency_ms = int((time.perf_counter() - started) * 1000)
                    self.last_retry_count = retry_count
                    self.last_status = "ok"
                    return response
                except LLMProviderError as exc:
                    last_error = exc
                    self.last_latency_ms = int((time.perf_counter() - started) * 1000)
                    self.last_retry_count = retry_count
                    self.last_status = exc.kind
                    record_llm_usage(
                        provider=self.config.provider,
                        model=model,
                        usage={},
                        cached_tokens=0,
                        operation=self.operation,
                        latency_ms=self.last_latency_ms,
                        status=exc.kind,
                        retry_count=retry_count,
                    )
                    if exc.kind not in retryable:
                        raise
                    if attempt < max_retries:
                        retry_count += 1
                        time.sleep(min(1.5, 0.2 * (2**attempt)))
                        continue
                    break
        if last_error is not None:
            raise last_error
        raise LLMProviderError("provider_error", "No LLM model configured.")

    def invoke(self, messages: Any) -> str:
        response = self._request(messages)
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        self.last_usage = usage
        self.last_cached_tokens = _cached_tokens(usage)
        record_llm_usage(
            provider=self.config.provider,
            model=self.last_model or self.config.model,
            usage=usage,
            cached_tokens=self.last_cached_tokens,
            operation=self.operation,
            latency_ms=self.last_latency_ms,
            status="ok",
            retry_count=self.last_retry_count,
        )
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        if not choices:
            raise LLMProviderError("invalid_response", "LLM provider response did not contain choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("invalid_response", "LLM provider response did not contain message content.")
        return content

    def stream_text(self, messages: Any) -> Iterator[str]:
        """Yield provider text deltas without JSON mode or tool/function definitions."""
        retryable = {"timeout", "rate_limited", "provider_error"}
        max_retries = max(0, int(getattr(self.config, "max_retries", 0) or 0))
        last_error: LLMProviderError | None = None
        retry_count = 0
        started = time.perf_counter()
        for model in self._models():
            payload = self._stream_payload(messages, model=model)
            for attempt in range(max_retries + 1):
                self.last_model = model
                try:
                    for raw_chunk in self._iter_stream_once(payload):
                        for line in str(raw_chunk).splitlines():
                            if not line.startswith("data:"):
                                continue
                            data_text = line[5:].strip()
                            if not data_text or data_text == "[DONE]":
                                continue
                            try:
                                data = json.loads(data_text)
                            except json.JSONDecodeError:
                                continue
                            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                            if usage:
                                self.last_usage = usage
                                self.last_cached_tokens = _cached_tokens(usage)
                            choices = data.get("choices") if isinstance(data.get("choices"), list) else []
                            if not choices or not isinstance(choices[0], dict):
                                continue
                            delta = choices[0].get("delta") if isinstance(choices[0].get("delta"), dict) else {}
                            content = delta.get("content") if isinstance(delta, dict) else ""
                            if isinstance(content, str) and content:
                                yield content
                    self.last_latency_ms = int((time.perf_counter() - started) * 1000)
                    self.last_retry_count = retry_count
                    self.last_status = "ok"
                    record_llm_usage(
                        provider=self.config.provider,
                        model=self.last_model or self.config.model,
                        usage=self.last_usage,
                        cached_tokens=self.last_cached_tokens,
                        operation=self.operation,
                        latency_ms=self.last_latency_ms,
                        status="ok",
                        retry_count=retry_count,
                    )
                    return
                except LLMProviderError as exc:
                    last_error = exc
                    self.last_latency_ms = int((time.perf_counter() - started) * 1000)
                    self.last_retry_count = retry_count
                    self.last_status = exc.kind
                    if exc.kind not in retryable or attempt >= max_retries:
                        break
                    retry_count += 1
                    time.sleep(min(1.5, 0.2 * (2**attempt)))
            if last_error and last_error.kind not in retryable:
                raise last_error
        if last_error is not None:
            raise last_error

    def with_structured_output(self, schema: Any) -> Any:
        client = self

        class _Structured:
            def invoke(self, payload: Any) -> Any:
                raw = client.invoke([("user", json.dumps(payload, ensure_ascii=False, default=str))])
                data = json.loads(raw)
                return schema.model_validate(data)

        return _Structured()
