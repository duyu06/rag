from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


REDACTED = "[REDACTED]"

# TypeSafe currently issues keys with an ``apikey_`` prefix. Keep this matcher
# intentionally broad enough to cover rotated keys without encoding one concrete
# key length in source control.
_TYPESAFE_KEY_PATTERN = re.compile(r"(?i)\bapikey_[A-Za-z0-9_-]{20,}\b")
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")

# These are the only TypeSafe fields allowed to cross an API, SSE, audit/debug,
# or trace boundary. Never replace this allowlist with a ``typesafe_*`` prefix
# check: configuration and credentials use the same prefix.
PUBLIC_TYPESAFE_METRIC_KEYS = frozenset(
    {
        "typesafe_enabled",
        "typesafe_mode",
        "typesafe_degraded",
        "typesafe_request_count",
        "typesafe_input_tokens",
        "typesafe_output_tokens",
        "typesafe_estimated_cost_usd",
        "typesafe_latency_p50_ms",
        "typesafe_latency_p95_ms",
        "typesafe_total_ms",
        "typesafe_unauthorized_candidates_blocked",
        "typesafe_route_counts",
        "typesafe_models",
        "typesafe_errors",
        # V2 request-level observability (design §7). Enumerated one by one on
        # purpose: ``judge_input_count`` is a request counter that happens to
        # travel with the judgment bag, and a prefix rule would silently admit
        # every future ``typesafe_*`` field the judgment layer invents.
        "typesafe_trigger",
        "typesafe_skipped",
        "typesafe_skip",
        "typesafe_cache_hit",
        "typesafe_circuit_open",
        "typesafe_slow",
        # Selective-gate trigger reasons (design §3 signals, Task 8 段B2). A list whose
        # members are produced by ``app.typesafe_router.REASON_TOKENS`` — literally the
        # six tokens compound/margin/floor/risk/dispersed/param — so there is no path
        # from this key to submitted text or credentials. Still listed one by one: a
        # sibling such as ``typesafe_skipped_reasons`` stays out by design.
        "typesafe_reasons",
        "judge_input_count",
    }
)

# Runtime timing data is public observability, not a generic pass-through bag.
PUBLIC_TIMING_KEYS = frozenset(
    {
        "vector_ms",
        "bm25_ms",
        "fusion_ms",
        "rerank_ms",
        "diversity_ms",
        "retrieval_ms",
        "retrieval_total_ms",
        "total_ms",
        "llm_ms",
        "ttft_ms",
        "bm25_cache_hit",
        "parallel_hybrid",
        "fusion",
        "vector_query_instruction",
        "vector_candidates",
        "bm25_candidates",
        "rerank_candidates",
        "max_chunks_per_document",
        "returned_documents",
        "llm_calls",
        "tool_calls",
        "fast_path",
        "native_stream",
        # V2 judgment-stage local sections (design §2/§7): ``rerank_stage_ms`` is
        # the cross-encoder section alone, ``rerank_ms`` stays the whole section.
        "dedup_ms",
        "rerank_stage_ms",
    }
)

# In-process rolling aggregates (``app.typesafe_judgments.typesafe_stats()``) are a
# *second* boundary the moment they reach a response. Keep listing them explicitly:
# ``typesafe_stats()`` may grow keys (Task 5 already added ``sample_count`` and
# ``slow_rate`` beyond design §7), and an un-prefixed aggregate dict has no
# name-based rule that could tell a rate from a credential.
PUBLIC_TYPESAFE_STATS_KEYS = frozenset(
    {
        "sample_count",
        "trigger_rate",
        "skip_rate",
        "cache_hit_ratio",
        "requests_per_query_p50",
        "requests_per_query_p95",
        "input_tokens_per_query_p50",
        "cost_per_query_p50",
        "timeout_rate",
        "degraded_rate",
        "slow_rate",
        "latency_p50_ms",
        "latency_p95_ms",
        "breaker_state",
    }
)


# Model Router V2.3 §8：`/api/system/status` 的 `llm` 块。逐条列举，理由与
# `PUBLIC_TYPESAFE_METRIC_KEYS` 同一条：按 `llm_` / 按「看起来像比率」的前缀放行，等于
# 把下一个还没评审过的聚合键自动开放到响应面。
# 前六个是 V2.3 之前就存在的探针面键（`status`/`model`/`provider`/`p50_ms`/`p95_ms`/
# `ttft_ms`）——§9「additive only」要求它们原样留着；后七个是 §8 的聚合出口。
# `providers` / `breaker` 的**成员**另有约束（见 `public_llm_status`）：那一层是
# 「provider 名 → 一个封闭值」，名字要过字符集，值要落在封闭集合里。
PUBLIC_LLM_STATUS_KEYS = frozenset(
    {
        "status",
        "model",
        "provider",
        "p50_ms",
        "p95_ms",
        "ttft_ms",
        "requests_5m",
        "success_rate",
        "fallback_rate",
        "aborted_rate",
        "p95_latency_ms",
        "providers",
        "breaker",
    }
)

# 熔断状态机的封闭值域（`app/resilience.CircuitBreaker.state`）+ 观测不可用时的兜底。
LLM_BREAKER_STATES = frozenset({"closed", "half_open", "open", "unknown"})
# provider 名的形状：**与注册表同源**（`ModelDefinition.provider` 就是 `^[a-z0-9_]+$`，
# `app/llm/models.py`）。这里的白名单是**边界**上的第二道——键名若被换成 base url，正则
# 就是那道闸（`providers` 是唯一「键由外部数据决定」的响应面字段）。
# 闸必须真的做到注释说的强度：曾经这里是 `[A-Za-z0-9_.:-]{1,64}`，实测放过
# `api.openai.com` 与 `127.0.0.1:11434`（评审 Minor 1）——那两类形状恰恰就是「被换成
# base url」的写法，等于注释承诺了一道不存在的闸。今天上游已经校验过，所以这是纵深防御
# 口径不符而不是可利用缺陷；收紧后无既有的合法 provider 名受影响（小写下划线本来就够）。
_LLM_PROVIDER_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_LLM_STATUS_NAME_KEYS = ("providers", "breaker")
_LLM_STATUS_ENTRY_LIMIT = 32
_LLM_STATUS_TEXT_LIMIT = 128


def redact_text(value: Any) -> str:
    text = str(value)
    text = _TYPESAFE_KEY_PATTERN.sub(REDACTED, text)
    return _BEARER_PATTERN.sub(f"Bearer {REDACTED}", text)


def redact_secrets(value: Any) -> Any:
    """Recursively redact known credential shapes before persistence or output."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            redact_text(key): redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    return value


def public_typesafe_metrics(values: Mapping[str, Any] | None) -> dict[str, Any]:
    source = values or {}
    return {
        key: redact_secrets(source[key])
        for key in PUBLIC_TYPESAFE_METRIC_KEYS
        if key in source
    }


def public_timings(values: Mapping[str, Any] | None) -> dict[str, Any]:
    source = values or {}
    timings = {
        key: redact_secrets(source[key])
        for key in PUBLIC_TIMING_KEYS
        if key in source
    }
    timings.update(public_typesafe_metrics(source))
    return timings


def public_typesafe_stats(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Whitelist the rolling aggregates before they reach ``/api/system/status``."""
    source = values or {}
    return {
        key: redact_secrets(source[key])
        for key in PUBLIC_TYPESAFE_STATS_KEYS
        if key in source
    }


def public_llm_status(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Whitelist the Model Router ``llm`` block (§8) before it reaches the API surface.

    Three rules, all deny-by-default:

    * a key outside :data:`PUBLIC_LLM_STATUS_KEYS` never crosses the boundary, no matter
      what the aggregate starts inventing next (``llm_api_key`` / ``providers_detail`` /
      ``requests_5m_prompt`` all stay out);
    * scalars are re-typed, not passed through: rates must land in ``[0, 1]``, timings and
      counts must be non-negative numbers, text is run through ``redact_secrets`` and cut
      to a short summary length. A string where a number belongs is a bug upstream, and
      echoing it would turn an internal field into an attacker-controlled response body.
    * ``providers`` / ``breaker`` are ``{provider_name: {one_closed_key: value}}``. The
      name has to look like a name (a URL-shaped key is dropped outright — this is the one
      place where a value from the registry reaches the response as a *key*), and the
      inner dict keeps exactly one key: ``healthy`` (bool, else ``"unknown"``) or
      ``state`` (a value from :data:`LLM_BREAKER_STATES`, else ``"unknown"``).
    """
    source = values or {}
    block: dict[str, Any] = {}
    for key in PUBLIC_LLM_STATUS_KEYS:
        if key not in source:
            continue
        value = source[key]
        if key in _LLM_STATUS_NAME_KEYS:
            block[key] = _public_llm_provider_map(key, value)
        else:
            block[key] = _public_llm_scalar(key, value)
    return block


def _public_llm_scalar(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key == "requests_5m":
        return value if _is_count(value) else None
    if key.endswith("_rate"):
        return round(float(value), 6) if _is_ratio(value) else None
    if key.endswith("_ms"):
        return round(float(value), 1) if _is_measurement(value) else None
    if isinstance(value, str):
        return redact_text(value)[:_LLM_STATUS_TEXT_LIMIT]
    return None


def _public_llm_provider_map(key: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    inner_key = "healthy" if key == "providers" else "state"
    result: dict[str, Any] = {}
    for name, entry in value.items():
        if len(result) >= _LLM_STATUS_ENTRY_LIMIT:
            break
        if not isinstance(name, str) or not _LLM_PROVIDER_NAME_PATTERN.match(name):
            continue
        result[name] = {inner_key: _public_llm_entry_value(inner_key, entry)}
    return result


def _public_llm_entry_value(inner_key: str, entry: Any) -> Any:
    if inner_key == "state":
        raw = entry.get(inner_key) if isinstance(entry, Mapping) else entry
        return raw if raw in LLM_BREAKER_STATES else "unknown"
    raw = entry.get(inner_key) if isinstance(entry, Mapping) else entry
    # `unknown` 是「这一轮探针没跑完整轮预算」，不是「探到了不健康」——把它压成 False
    # 会让 §5 的 health 过滤面与 status 页同时冒领一次故障。
    return raw if isinstance(raw, bool) else "unknown"


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_ratio(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= float(value) <= 1.0


def _is_measurement(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) >= 0.0


def public_exception_detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {redact_text(exc)}"
