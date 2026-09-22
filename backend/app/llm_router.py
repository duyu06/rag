from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic, perf_counter
from typing import Any

import httpx

from app.config import settings
from app.llm_metrics import llm_metrics_snapshot, record_llm_attempt
from app.llm_provider import (
    LLMRuntimeConfig,
    chat_message,
    public_runtime_config,
    resolve_llm_config,
    stream_chat,
)


@dataclass(frozen=True)
class RouteContext:
    sensitivity: str = "public"
    requires_tools: bool = False
    requires_reasoning: bool = False
    mode: str = "rag"


@dataclass
class _BreakerState:
    outcomes: deque[bool] = field(default_factory=deque)
    open_until: float = 0.0
    half_open_probe: bool = False


class LLMRouteError(RuntimeError):
    pass


_PROVIDER_CAPABILITIES: dict[str, dict[str, bool]] = {
    "ollama": {"tools": True, "reasoning": True, "stream": True, "external": False},
    "deepseek": {"tools": True, "reasoning": True, "stream": True, "external": True},
    "qwen": {"tools": True, "reasoning": True, "stream": True, "external": True},
    "openai": {"tools": True, "reasoning": True, "stream": True, "external": True},
    "openai-compatible": {"tools": True, "reasoning": True, "stream": True, "external": True},
}

_BREAKERS: dict[str, _BreakerState] = {}
_BREAKER_LOCK = Lock()


def external_allowed_for_sensitivity(sensitivity: str) -> bool:
    value = str(sensitivity or "public").lower()
    if value == "restricted":
        return False
    if value == "confidential":
        return bool(settings.llm_external_confidential_allowed)
    if value == "internal":
        return bool(settings.llm_external_internal_allowed)
    return True


def _capabilities(provider: str) -> dict[str, bool]:
    return _PROVIDER_CAPABILITIES.get(
        provider,
        {"tools": True, "reasoning": True, "stream": True, "external": True},
    )


def _breaker_state(provider: str) -> _BreakerState:
    with _BREAKER_LOCK:
        state = _BREAKERS.get(provider)
        if state is None:
            state = _BreakerState(
                outcomes=deque(maxlen=int(settings.llm_router_failure_window))
            )
            _BREAKERS[provider] = state
        elif state.outcomes.maxlen != int(settings.llm_router_failure_window):
            state.outcomes = deque(
                state.outcomes,
                maxlen=int(settings.llm_router_failure_window),
            )
        return state


def _breaker_allow(provider: str) -> bool:
    state = _breaker_state(provider)
    now = monotonic()
    with _BREAKER_LOCK:
        if state.open_until > now:
            return False
        if state.open_until > 0:
            if state.half_open_probe:
                return False
            state.half_open_probe = True
            return True
        return True


def _breaker_record(provider: str, success: bool) -> None:
    state = _breaker_state(provider)
    now = monotonic()
    with _BREAKER_LOCK:
        if success:
            if state.half_open_probe or state.open_until > 0:
                state.outcomes.clear()
            else:
                state.outcomes.append(True)
            state.open_until = 0.0
            state.half_open_probe = False
            return

        state.outcomes.append(False)
        state.half_open_probe = False
        minimum_samples = min(5, int(settings.llm_router_failure_window))
        if len(state.outcomes) < minimum_samples:
            return
        failures = sum(1 for item in state.outcomes if not item)
        failure_rate = failures / max(1, len(state.outcomes))
        if failure_rate >= float(settings.llm_router_failure_threshold):
            state.open_until = now + float(settings.llm_router_cooldown_seconds)


def circuit_breaker_snapshot() -> dict[str, dict[str, Any]]:
    now = monotonic()
    with _BREAKER_LOCK:
        result: dict[str, dict[str, Any]] = {}
        for provider, state in _BREAKERS.items():
            failures = sum(1 for item in state.outcomes if not item)
            total = len(state.outcomes)
            result[provider] = {
                "state": (
                    "open"
                    if state.open_until > now
                    else ("half_open" if state.open_until > 0 else "closed")
                ),
                "samples": total,
                "failures": failures,
                "failure_rate": round(failures / max(1, total), 4),
                "cooldown_remaining_seconds": round(max(0.0, state.open_until - now), 2),
            }
        return result


def reset_circuit_breakers() -> None:
    with _BREAKER_LOCK:
        _BREAKERS.clear()


def _provider_order() -> list[str]:
    primary = resolve_llm_config()
    if not settings.llm_router_enabled:
        return [primary.provider]
    raw_fallbacks = [
        item.strip().lower().replace("_", "-")
        for item in str(settings.llm_router_fallback_providers or "").split(",")
        if item.strip()
    ]
    order: list[str] = []
    for provider in [primary.provider, *raw_fallbacks]:
        if provider not in order:
            order.append(provider)
    return order[: int(settings.llm_router_max_attempts)]


def _resolve_candidate(provider: str, primary: LLMRuntimeConfig) -> LLMRuntimeConfig:
    if provider == primary.provider:
        return primary
    return resolve_llm_config(provider)


def route_candidates(context: RouteContext) -> list[LLMRuntimeConfig]:
    primary = resolve_llm_config()
    allow_external = external_allowed_for_sensitivity(context.sensitivity)
    candidates: list[LLMRuntimeConfig] = []

    for provider in _provider_order():
        try:
            cfg = _resolve_candidate(provider, primary)
        except Exception:
            continue
        caps = _capabilities(cfg.provider)
        if not allow_external and caps.get("external", True):
            continue
        if context.requires_tools and not caps.get("tools", False):
            continue
        if context.requires_reasoning and not caps.get("reasoning", False):
            continue
        if not _breaker_allow(cfg.provider):
            continue
        candidates.append(cfg)

    # Restricted/confidential policy must fail closed to local generation rather
    # than silently re-enabling an external provider.
    if not candidates and not allow_external:
        try:
            local = resolve_llm_config("ollama")
            if _breaker_allow(local.provider):
                candidates.append(local)
        except Exception:
            pass
    return candidates[: int(settings.llm_router_max_attempts)]


def _retryable(exc: Exception) -> tuple[bool, bool]:
    if isinstance(exc, httpx.TimeoutException):
        return True, True
    if isinstance(exc, httpx.HTTPStatusError):
        status = int(exc.response.status_code)
        return status in {408, 409, 425, 429, 500, 502, 503, 504}, False
    if isinstance(exc, httpx.RequestError):
        return True, False
    return False, False


def _usage(message: dict[str, Any]) -> tuple[int, int]:
    usage = message.get("_usage")
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


def routed_chat_message(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    think: bool = False,
    context: RouteContext | None = None,
) -> dict[str, Any]:
    route_context = context or RouteContext(requires_tools=bool(tools))
    candidates = route_candidates(route_context)
    if not candidates:
        raise LLMRouteError(
            f"No eligible LLM provider for sensitivity={route_context.sensitivity}"
        )

    failures: list[str] = []
    for index, cfg in enumerate(candidates):
        started = perf_counter()
        try:
            message = chat_message(
                messages,
                tools,
                temperature=temperature,
                max_tokens=max_tokens,
                think=think,
                runtime_config=cfg,
            )
            latency_ms = (perf_counter() - started) * 1000
            input_tokens, output_tokens = _usage(message)
            _breaker_record(cfg.provider, True)
            record_llm_attempt(
                provider=cfg.provider,
                success=True,
                latency_ms=latency_ms,
                fallback_index=index,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            message["_route"] = {
                "selected": public_runtime_config(cfg),
                "fallback_index": index,
                "sensitivity": route_context.sensitivity,
                "requires_tools": route_context.requires_tools,
                "requires_reasoning": route_context.requires_reasoning,
                "external_allowed": external_allowed_for_sensitivity(route_context.sensitivity),
                "attempted_providers": [
                    item.provider for item in candidates[: index + 1]
                ],
            }
            return message
        except Exception as exc:
            latency_ms = (perf_counter() - started) * 1000
            retryable, timed_out = _retryable(exc)
            _breaker_record(cfg.provider, False)
            record_llm_attempt(
                provider=cfg.provider,
                success=False,
                latency_ms=latency_ms,
                timeout=timed_out,
                fallback_index=index,
                error_type=type(exc).__name__,
            )
            failures.append(f"{cfg.provider}:{type(exc).__name__}")
            if not retryable:
                break

    raise LLMRouteError(
        "LLM route failed; attempts=" + ",".join(failures or ["none"])
    )


def routed_stream_chat(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    think: bool = False,
    context: RouteContext | None = None,
    route_sink: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[str]:
    """Fail over only before the first visible token.

    Once a provider has emitted user-visible text, switching providers would risk
    duplicated or contradictory output, so mid-stream failures are surfaced.
    """
    route_context = context or RouteContext()
    candidates = route_candidates(route_context)
    if not candidates:
        raise LLMRouteError(
            f"No eligible streaming provider for sensitivity={route_context.sensitivity}"
        )

    failures: list[str] = []
    for index, cfg in enumerate(candidates):
        started = perf_counter()
        emitted = False
        try:
            iterator = iter(
                stream_chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    think=think,
                    runtime_config=cfg,
                )
            )
            first = next(iterator)
            emitted = True
            if route_sink is not None:
                route_sink(
                    {
                        "selected": public_runtime_config(cfg),
                        "fallback_index": index,
                        "sensitivity": route_context.sensitivity,
                        "external_allowed": external_allowed_for_sensitivity(
                            route_context.sensitivity
                        ),
                    }
                )
            yield first
            for text in iterator:
                yield text
            latency_ms = (perf_counter() - started) * 1000
            _breaker_record(cfg.provider, True)
            record_llm_attempt(
                provider=cfg.provider,
                success=True,
                latency_ms=latency_ms,
                fallback_index=index,
            )
            return
        except StopIteration:
            exc: Exception = RuntimeError(f"{cfg.provider} stream returned no visible tokens")
        except Exception as caught:
            exc = caught

        latency_ms = (perf_counter() - started) * 1000
        retryable, timed_out = _retryable(exc)
        _breaker_record(cfg.provider, False)
        record_llm_attempt(
            provider=cfg.provider,
            success=False,
            latency_ms=latency_ms,
            timeout=timed_out,
            fallback_index=index,
            error_type=type(exc).__name__,
        )
        failures.append(f"{cfg.provider}:{type(exc).__name__}")
        if emitted or not retryable:
            raise exc

    raise LLMRouteError(
        "LLM streaming route failed; attempts=" + ",".join(failures or ["none"])
    )


def router_registry_snapshot() -> dict[str, Any]:
    primary: dict[str, Any]
    try:
        primary = public_runtime_config(resolve_llm_config())
    except Exception as exc:
        primary = {"configured": False, "error": type(exc).__name__}

    providers: list[dict[str, Any]] = []
    seen: set[str] = set()
    order = []
    try:
        order = _provider_order()
    except Exception:
        order = ["ollama", "deepseek", "qwen", "openai"]

    for provider in order:
        if provider in seen:
            continue
        seen.add(provider)
        try:
            cfg = (
                resolve_llm_config()
                if primary.get("provider") == provider
                else resolve_llm_config(provider)
            )
            providers.append(
                {
                    **public_runtime_config(cfg),
                    "configured": True,
                    "capabilities": _capabilities(provider),
                }
            )
        except Exception as exc:
            providers.append(
                {
                    "provider": provider,
                    "configured": False,
                    "error": type(exc).__name__,
                    "capabilities": _capabilities(provider),
                }
            )

    return {
        "enabled": bool(settings.llm_router_enabled),
        "primary": primary,
        "providers": providers,
        "policy": {
            "max_attempts": int(settings.llm_router_max_attempts),
            "failure_window": int(settings.llm_router_failure_window),
            "failure_threshold": float(settings.llm_router_failure_threshold),
            "cooldown_seconds": int(settings.llm_router_cooldown_seconds),
            "external_internal_allowed": bool(settings.llm_external_internal_allowed),
            "external_confidential_allowed": bool(
                settings.llm_external_confidential_allowed
            ),
            "restricted_external_allowed": False,
        },
        "circuit_breakers": circuit_breaker_snapshot(),
        "metrics": llm_metrics_snapshot(),
    }
