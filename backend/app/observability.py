from __future__ import annotations

import hmac
import re
import time
from typing import Any

from fastapi import HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import SecretStr

from app.config import settings

HTTP_REQUESTS = Counter(
    "yaoke_http_requests_total",
    "HTTP requests handled by yaoke",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "yaoke_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
LLM_REQUESTS = Counter(
    "yaoke_llm_requests_total",
    "LLM provider attempts",
    ["provider", "model", "outcome", "fallback"],
)
LLM_LATENCY = Histogram(
    "yaoke_llm_request_duration_seconds",
    "LLM provider attempt latency",
    ["provider", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
LLM_TOKENS = Counter(
    "yaoke_llm_tokens_total",
    "Observed LLM tokens",
    ["provider", "model", "direction"],
)
LLM_TIMEOUTS = Counter(
    "yaoke_llm_timeouts_total",
    "LLM provider timeouts",
    ["provider", "model"],
)

_UUID_RE = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}(?=/|$)")
_HEX_ID_RE = re.compile(r"/[0-9a-fA-F]{24,64}(?=/|$)")
_NUMERIC_RE = re.compile(r"/\d+(?=/|$)")


def _safe_path(path: str) -> str:
    value = _UUID_RE.sub("/{id}", path)
    value = _HEX_ID_RE.sub("/{id}", value)
    value = _NUMERIC_RE.sub("/{id}", value)
    return value[:180]


async def prometheus_middleware(request: Request, call_next):
    if not settings.metrics_enabled:
        return await call_next(request)

    started = time.perf_counter()
    response = None
    status = 500
    try:
        response = await call_next(request)
        status = int(response.status_code)
        return response
    finally:
        path = _safe_path(request.url.path)
        HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
        HTTP_LATENCY.labels(request.method, path).observe(
            max(0.0, time.perf_counter() - started)
        )


def observe_llm_attempt(
    *,
    provider: str,
    model: str,
    success: bool,
    latency_ms: float,
    timeout: bool,
    fallback_index: int,
    input_tokens: int,
    output_tokens: int,
) -> None:
    if not settings.metrics_enabled:
        return
    outcome = "success" if success else "failure"
    fallback = "true" if fallback_index > 0 else "false"
    LLM_REQUESTS.labels(provider, model or "unknown", outcome, fallback).inc()
    LLM_LATENCY.labels(provider, model or "unknown").observe(
        max(0.0, float(latency_ms) / 1000.0)
    )
    if input_tokens:
        LLM_TOKENS.labels(provider, model or "unknown", "input").inc(max(0, input_tokens))
    if output_tokens:
        LLM_TOKENS.labels(provider, model or "unknown", "output").inc(max(0, output_tokens))
    if timeout:
        LLM_TIMEOUTS.labels(provider, model or "unknown").inc()


def _secret(value: SecretStr | str | None) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value or "")


def metrics_payload(authorization: str | None) -> tuple[bytes, str]:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    expected = _secret(settings.metrics_bearer_token).strip()
    if expected:
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization[7:].strip()
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid metrics credential")
    return generate_latest(), CONTENT_TYPE_LATEST
