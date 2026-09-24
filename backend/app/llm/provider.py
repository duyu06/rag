"""LLM 的**唯一出口**（设计 §2 / D6）：全仓库只有这个文件允许出现 httpx 与 LLM endpoint 路径。

三条业务链路（RAG 非流式 / SSE 流式 / Agent 工具回路）以及 `health.py` 的 probe 都只能经
本文件发请求。之所以把 URL 路径常量与凭据组装都关在这里，是因为 D6 的静态扫描契约
（Task 9）按「`app/llm/provider.py` 之外零命中」判定；`health.py` 因此不自己 `httpx.get`，
而是调 `probe()`（probe 的 URL 构造也归本层）。

对外只暴露四个动词：
- `complete(model, req, timeout) -> LLMResponse`
- `stream(model, req, timeout) -> Iterator[LLMChunk]`
- `probe(provider, timeout=2.5) -> ProbeResult`（健康检查，带 body 供 model-installed 判定）
- `PROVIDERS` / `SUPPORTED_PROVIDERS` / `effective_model_name()`：分发事实，供路由与 trace 侧读取
  （`SUPPORTED_PROVIDERS` 是 registry 启动校验的输入，见 I-3）

异常口径：本层**只抛 `LLMError`**（`errors.from_exception` 统一翻译），因此 Task 4 的执行器
不需要知道 httpx 的存在。凭据缺失（registry 的 `RegistryError`）在这里翻译成
`LLMError(kind="config")`，Task 4 据此打 `PROVIDER_CONFIG_FAILED`。

model_override（Task 1 移交项）：`ProviderCredentials.model_override` 非空即**替换**请求体里
的模型名；响应模型名优先取 provider 回显值、无回显时取替换后的名字，于是 usage 归因指向
真正被调用的模型（§9）。
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from app.llm import errors, normalize
from app.llm.models import LLMChunk, LLMRequest, LLMResponse, ModelDefinition
from app.llm.registry import (
    ProviderCredentials,
    RegistryError,
    credentials_for_provider,
)

__all__ = [
    "PROVIDERS",
    "SUPPORTED_PROVIDERS",
    "ProbeResult",
    "complete",
    "effective_model_name",
    "probe",
    "stream",
]

#: 测试接缝：契约测试把它换成 `httpx.MockTransport(handler)`，生产路径恒为 None（默认传输）。
#: 之所以是模块级变量而不是参数：`complete/stream/probe` 的签名由 brief 冻结，不能为测试加参。
_transport: httpx.BaseTransport | None = None


# --------------------------------------------------------------------------
# 适配器：协议差异在这一层吸收完（§6）
# --------------------------------------------------------------------------
class _Adapter:
    """一个 provider 协议：endpoint 路径、报文构造、响应解析、鉴权头。"""

    key: str = ""
    chat_path: str = ""
    probe_path: str = ""
    #: 是否必须有 api_key（缺失即 config 类错误，不发无谓的 HTTP 往返）。
    requires_key: bool = False

    def payload(self, req: LLMRequest, model: str, *, stream: bool) -> dict[str, Any]:
        raise NotImplementedError

    def parse(self, data: dict[str, Any], model: str, provider: str,
              latency_ms: float) -> LLMResponse:
        raise NotImplementedError

    def chunks(self, response: Any) -> Iterator[LLMChunk]:
        raise NotImplementedError

    def headers(self, creds: ProviderCredentials) -> dict[str, str]:
        return {}


class OllamaNative(_Adapter):
    """Ollama 原生 `/api/chat`：NDJSON 流、`message.content`、`prompt_eval_count`。无 key（D1）。"""

    key = "ollama"
    chat_path = "/api/chat"
    probe_path = "/api/tags"

    def payload(self, req: LLMRequest, model: str, *, stream: bool) -> dict[str, Any]:
        return normalize.ollama_payload(req, model, stream=stream)

    def parse(self, data: dict[str, Any], model: str, provider: str,
              latency_ms: float) -> LLMResponse:
        return normalize.parse_ollama_response(data, model, provider, latency_ms)

    def chunks(self, response: Any) -> Iterator[LLMChunk]:
        return normalize.ollama_stream_lines(response)


class OpenAICompat(_Adapter):
    """OpenAI 兼容层 `/chat/completions`：SSE 流、`delta.content`、`usage.*_tokens`。"""

    key = "openai"
    chat_path = "/chat/completions"
    probe_path = "/models"
    requires_key = True

    def payload(self, req: LLMRequest, model: str, *, stream: bool) -> dict[str, Any]:
        return normalize.openai_payload(req, model, stream=stream)

    def parse(self, data: dict[str, Any], model: str, provider: str,
              latency_ms: float) -> LLMResponse:
        return normalize.parse_openai_response(data, model, provider, latency_ms)

    def chunks(self, response: Any) -> Iterator[LLMChunk]:
        return normalize.openai_stream_lines(response)

    def headers(self, creds: ProviderCredentials) -> dict[str, str]:
        """唯一的鉴权头装配点：key 只在这里进 HTTP 一次，且空 key 时宁可不发头。

        Ollama 侧继承基类的「不发 Authorization」——D1 规定 ollama 恒无 key，
        所以即使宿主误设了 `OLLAMA_API_KEY` 也不会被外带。
        """
        return {"Authorization": f"Bearer {creds.api_key}"} if creds.api_key else {}


_OLLAMA = OllamaNative()
_OPENAI_COMPAT = OpenAICompat()

#: provider 名 → 适配器（brief 冻结的 `PROVIDERS` 分发表）。
#: **显式列举**而不是「其余一律当 OpenAI 兼容」：§6 把「能力不支持」列为硬终态（NO_FALLBACK），
#: 未登记的 provider 名（多半是注册表拼错）必须大声失败——静默套一个协议等于把 key 发给
#: 错误的端点。deepseek / qwen 出厂即 OpenAI 兼容（§12 的 base_url 默认值就是 compatible
#: mode），所以它们指向同一个 `_OPENAI_COMPAT` 实例。
PROVIDERS: dict[str, _Adapter] = {
    "ollama": _OLLAMA,
    "openai": _OPENAI_COMPAT,
    "deepseek": _OPENAI_COMPAT,
    "qwen": _OPENAI_COMPAT,
}

#: `PROVIDERS` 的键集，给 registry 的启动校验用（Task 2 评审 I-3）。
#: 单独导出一个 frozenset 而不是让 registry 去 import 本模块：`provider → registry` 是
#: 编译期依赖（它要用 D1 的凭据解析），反向的模块级 import 会构成循环；registry 只在
#: `warmup()` 函数体内取这一次常量，环不存在。名字集合是**登记事实**而非协议细节，
#: 所以这份投影可以放心公开。
SUPPORTED_PROVIDERS: frozenset[str] = frozenset(PROVIDERS)


# --------------------------------------------------------------------------
# 三个对外动词
# --------------------------------------------------------------------------
def complete(model: ModelDefinition, req: LLMRequest, timeout: float) -> LLMResponse:
    """非流式一次生成。`timeout` 单位是**秒**，由 Task 4 按
    `min(llm_model_timeout_seconds, budget.remaining())` 传入（spec §6）。
    """
    adapter = _adapter(model.provider)
    creds = _credentials(model.provider, adapter, model.id)
    target = effective_model_name(model, creds)
    payload = adapter.payload(req, target, stream=False)
    started = time.perf_counter()
    try:
        with _client(timeout, adapter.headers(creds)) as client:
            response = client.post(creds.base_url + adapter.chat_path, json=payload)
            if response.status_code >= 400:
                raise errors.from_response(response.status_code, response.text)
            data = response.json()
        latency_ms = (time.perf_counter() - started) * 1000.0
        return adapter.parse(_object_body(data), target, model.provider, latency_ms)
    except Exception as exc:                      # 执行器只可能收到 LLMError
        raise errors.from_exception(exc) from exc


def stream(model: ModelDefinition, req: LLMRequest, timeout: float) -> Iterator[LLMChunk]:
    """流式生成。惰性顺序是契约的一部分：provider 未登记 / 凭据缺失在**调用本函数时**就抛，
    HTTP 层错误要到第一次 `next()`（请求真正发出）才抛。Task 4 的 commit 边界以第一个
    chunk 为界，pre-commit 失败才能静默换模型（§7 / 矩阵 #10）。
    """
    adapter = _adapter(model.provider)
    creds = _credentials(model.provider, adapter, model.id)
    target = effective_model_name(model, creds)
    payload = adapter.payload(req, target, stream=True)
    return _stream_iter(adapter, creds, payload, model.provider, timeout)


@dataclass(frozen=True)
class ProbeResult:
    """一次健康探测的结果。

    `detail` 的形状与 legacy `rag.py::probe_*` 的异常摘要逐字一致
    （`"{异常类名}: {消息}"`），因此 `/api/health` 的 `llm_detail` 不因迁移而换文案。
    """

    ok: bool
    detail: str
    body: Any = None


def probe(provider: str, *, timeout: float = 2.5) -> ProbeResult:
    """provider 级健康探测（D6：URL 构造与 HTTP 都在本层，`health.py` 只编排与缓存）。

    刻意**不**把异常翻译成 `LLMError`：这里要的是 legacy probe 的 `(bool, str)` 语义，
    detail 文本会被 `/api/health` 直接回显。凭据缺失是这里唯一可能冒出 `LLMError` 的路径，
    也被下面的宽 catch 收敛成 `(False, "LLMError: …")`，不会把异常抛进 status 路由。
    """
    adapter = _adapter(provider)
    try:
        creds = _credentials(provider, adapter, f"health:{provider}")
        with _client(timeout, adapter.headers(creds)) as client:
            response = client.get(creds.base_url + adapter.probe_path)
            response.raise_for_status()
            return ProbeResult(True, "", response.json())
    except Exception as exc:
        return ProbeResult(False, f"{type(exc).__name__}: {exc}", None)


# --------------------------------------------------------------------------
# 内部件
# --------------------------------------------------------------------------
def effective_model_name(model: ModelDefinition, creds: ProviderCredentials) -> str:
    """`model_override` 非空则替换请求模型名（Task 1 移交项的唯一落点）。"""
    return creds.model_override.strip() or model.model


def _stream_iter(adapter: _Adapter, creds: ProviderCredentials, payload: dict[str, Any],
                 provider: str, timeout: float) -> Iterator[LLMChunk]:
    try:
        with _client(timeout, adapter.headers(creds)) as client:
            with client.stream("POST", creds.base_url + adapter.chat_path,
                               json=payload) as response:
                if response.status_code >= 400:
                    raise errors.from_response(response.status_code, _error_body(response))
                yield from adapter.chunks(response)
    except Exception as exc:
        raise errors.from_exception(exc) from exc


@contextmanager
def _client(timeout: float, headers: dict[str, str] | None):
    """唯一的 httpx 客户端构造点（D6）。每次调用一个短生命周期 Client：
    连接复用的收益在这里小于「timeout / headers 随 attempt 变化」的正确性风险。
    """
    client = httpx.Client(timeout=timeout, headers=headers or None, transport=_transport)
    try:
        yield client
    finally:
        client.close()


def _adapter(provider: str) -> _Adapter:
    adapter = PROVIDERS.get(provider)
    if adapter is None:
        raise errors.LLMError(
            "hard", None,
            f"未登记的 LLM provider「{provider}」：PROVIDERS 只有 {sorted(PROVIDERS)}",
            no_fallback=True, provider=provider)
    return adapter


def _credentials(provider: str, adapter: _Adapter, label: str) -> ProviderCredentials:
    """按 D1 解析凭据：复用 `registry` 的**唯一**实现（`credentials_for_provider`）。

    provider 层不自己拼 env 名——否则 D1 的凭据约定会出现第二套解析逻辑，Task 9 的
    单一出口扫描也就无从判定「谁在读 key」。注册表层的 `RegistryError`（缺 base_url）
    在这里翻译成 `LLMError(kind="config")`（Task 1 的移交项）。
    """
    try:
        creds = credentials_for_provider(provider, label=label)
    except RegistryError as exc:
        raise errors.LLMError("config", None,
                              f"模型 {label} 的凭据不可用：{exc}", provider=provider) from exc
    if adapter.requires_key and not creds.api_key:
        # 不发一次注定 401 的往返：空 key 直接判 config（Task 4 打 PROVIDER_CONFIG_FAILED）。
        raise errors.LLMError("config", None,
                              f"provider「{provider}」未配置 API key，请求未发出",
                              provider=provider)
    return creds


def _object_body(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise errors.LLMError("hard", None, "响应体不是 JSON 对象")
    return data


def _error_body(response: Any) -> str:
    """流式响应里取错误体：必须先 `read()` 才有 `.text`；取不到也不能盖掉原始状态码。"""
    try:
        response.read()
        return str(response.text)
    except Exception:                            # pragma: no cover - 极端传输异常
        return ""
