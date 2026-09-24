"""健康探测的编排层（D6 收编：HTTP 与 URL 构造在 `provider.py`，这里只判语义与缓存）。

Task 2 之前 `probe_ollama / probe_llm` 住在 `app/rag.py`，里面直接 `httpx.get(...)`，那是
D6「单一出口」的违例点。本文件把它们**迁入**，并保证三条不降级的性质：

1. **签名与返回形状不变**：`probe_ollama(timeout=2.5) -> tuple[bool, str]`、
   `probe_llm(timeout=2.5) -> (bool, str)`。`/api/health`（`main.py`、`main_agent.py`）与
   `/api/system/status`（`knowledge_os.py`）以及前端 SystemView 消费的是 `(bool, str)` 与
   其中的 bool，因此逐字保持。
2. **detail 文案不变**：连接失败 / 非 2xx 的摘要仍是 `"{异常类名}: {消息}"`（由
   `provider.probe()` 用同一个 `except Exception` 口径生成），Ollama「已连接但未发现模型」
   与 OpenAI「openai-compatible」两条成功/半成功文案在本文件里原样保留。唯一文本差异是
   「200 但 body 不是 JSON 对象」这一非现实分支（legacy 会吐 `AttributeError` 摘要），
   这里换成一条可读摘要——它不影响任何被消费的 bool。
3. **provider 判定仍看 `settings.openai_api_key`**：legacy RAG 链的选择逻辑就是这一条
   （`rag.py::probe_llm` / `current_model_name` 同源），Router 侧的候选选择是 Task 3 的
   `plan()`，两条路互不改写。

`provider_health_view()` 是 §5「health 过滤」与 §8「status 的 `providers:{name:{healthy}}`」
的唯一数据源：按 provider（不是按模型）聚合，60s 缓存，避免每次 status 轮询都把 Ollama
打个来回。
"""
from __future__ import annotations

import time
from typing import Any, Mapping

from app.config import settings
from app.llm import provider
from app.llm.registry import Registry

__all__ = [
    "HEALTH_CACHE_TTL_SECONDS",
    "probe_llm",
    "probe_ollama",
    "provider_health_view",
    "reset_health_cache",
]

# §5/§8：健康视图的缓存窗口（60s）。刻意短于 `llm_breaker_open_seconds` 的默认 60s 同量级，
# 于是「熔断打开」与「探测到恢复」不会互相拖影。
HEALTH_CACHE_TTL_SECONDS = 60.0
# 单次探测超时：与 legacy `probe_*` 的默认值一致（status 路由不能被一个死掉的 Ollama 拖住）。
_PROBE_TIMEOUT_SECONDS = 2.5

#: provider 名 → (写入时刻, healthy)。进程内单 worker 语义，与 typesafe 判定缓存同构。
_health_cache: dict[str, tuple[float, bool]] = {}


def probe_ollama(timeout: float = 2.5) -> tuple[bool, str]:
    """Probe the Ollama model that the P1.4 Tool Calling Agent actually uses."""
    result = provider.probe("ollama", timeout=timeout)
    if not result.ok:
        return False, result.detail
    body: Any = result.body
    if not isinstance(body, dict):
        return False, f"Ollama 健康端点响应不是 JSON 对象：{type(body).__name__}"
    models = body.get("models", [])
    if not _ollama_model_installed(models, settings.ollama_model):
        return False, f"Ollama 已连接，但未发现模型 {settings.ollama_model}"
    return True, f"model={settings.ollama_model}"


def probe_llm(timeout: float = 2.5) -> tuple[bool, str]:
    """Probe the provider used by the legacy RAG answer path."""
    if not settings.openai_api_key:
        return probe_ollama(timeout)
    result = provider.probe("openai", timeout=timeout)
    if not result.ok:
        return False, result.detail
    return True, "openai-compatible"


def provider_health_view(registry: Registry) -> Mapping[str, dict[str, bool]]:
    """注册表里**可能被选中**的每个 provider 一份 `{healthy: bool}`，带 60s 缓存。

    只覆盖 `enabled=True` 条目的 provider：没有任何启用条目的 provider 不可能出现在
    Task 3 的候选里，探它等于白打一次网络。返回值是可写的普通 dict，但调用方按只读消费
    （Task 4/5 只读 `["healthy"]`）。
    """
    now = _now()
    view: dict[str, dict[str, bool]] = {}
    for name in _providers_of(registry):
        cached = _health_cache.get(name)
        if cached is None or now - cached[0] >= HEALTH_CACHE_TTL_SECONDS:
            healthy = provider.probe(name, timeout=_PROBE_TIMEOUT_SECONDS).ok
            _health_cache[name] = (now, healthy)
        else:
            healthy = cached[1]
        view[name] = {"healthy": healthy}
    return view


def reset_health_cache() -> None:
    """清缓存。测试换 provider 端点、或 Task 5 想强制刷新时必须调用。"""
    _health_cache.clear()


def _providers_of(registry: Registry) -> tuple[str, ...]:
    """按注册表声明顺序去重出启用条目的 provider 名（顺序稳定 ⇒ 测试可断言键序）。"""
    seen: dict[str, None] = {}
    for model in registry.models:
        if model.enabled:
            seen.setdefault(model.provider, None)
    return tuple(seen)


def _now() -> float:
    """时间源单独开一层：缓存过期用例patch它，而不是让测试睡 60 秒。"""
    return time.monotonic()


def _ollama_model_installed(models: list[dict], wanted_model: str) -> bool:
    installed_names = {
        str(item.get(key) or "").strip()
        for item in models
        for key in ("name", "model")
        if item.get(key)
    }
    wanted = wanted_model.strip()
    if not wanted:
        return False
    if ":" in wanted:
        return wanted in installed_names
    return any(
        name == wanted or name.split(":", 1)[0] == wanted
        for name in installed_names
    )
