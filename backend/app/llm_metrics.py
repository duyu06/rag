from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from time import time
from typing import Any


@dataclass
class ProviderMetrics:
    requests: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    fallback_uses: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_latency_ms: float = 0.0
    last_error: str | None = None
    last_updated_at: float = 0.0


_LOCK = Lock()
_STATS: dict[str, ProviderMetrics] = {}


def record_llm_attempt(
    *,
    provider: str,
    success: bool,
    latency_ms: float,
    timeout: bool = False,
    fallback_index: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error_type: str | None = None,
) -> None:
    key = str(provider or "unknown")
    with _LOCK:
        item = _STATS.setdefault(key, ProviderMetrics())
        item.requests += 1
        item.successes += int(success)
        item.failures += int(not success)
        item.timeouts += int(timeout)
        item.fallback_uses += int(fallback_index > 0)
        item.input_tokens += max(0, int(input_tokens or 0))
        item.output_tokens += max(0, int(output_tokens or 0))
        item.total_latency_ms += max(0.0, float(latency_ms or 0.0))
        item.last_error = None if success else str(error_type or "unknown")
        item.last_updated_at = time()


def llm_metrics_snapshot() -> dict[str, dict[str, Any]]:
    with _LOCK:
        result: dict[str, dict[str, Any]] = {}
        for provider, item in _STATS.items():
            data = asdict(item)
            requests = max(1, int(item.requests))
            data["success_rate"] = round(item.successes / requests, 4)
            data["failure_rate"] = round(item.failures / requests, 4)
            data["avg_latency_ms"] = round(item.total_latency_ms / requests, 2)
            data["total_latency_ms"] = round(item.total_latency_ms, 2)
            result[provider] = data
        return result


def reset_llm_metrics() -> None:
    with _LOCK:
        _STATS.clear()
