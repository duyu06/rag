"""LLM 错误三分类（设计 §6 冻结映射表）。

Router 链上**只有一种异常**：`LLMError`。它带一个机器可读的 `kind`，Task 4 的
FallbackExecutor 据此决定「重试当前模型 / 换下一个候选 / 跳过该 provider 其余候选 /
直接上抛业务错误」。业务层永远不需要读 httpx 的异常类型，也不需要 `if provider == ...`。

`kind` 四值与 §6 三分类的对应关系（冻结）：

| kind               | 触发                                             | 同模型重试 | 换候选 |
| ------------------ | ------------------------------------------------ | ---------- | ------ |
| `retryable`        | 408/429/500/502/503/504、超时、连接失败、流截断   | 是（预算内）| 重试仍败后 |
| `model_unavailable`| 500 + body 含 `alloc`/`failed to load`/…          | **否**     | 立即换（更快）|
| `config`           | 401/403、凭据解析失败                             | 否         | 跳过同 provider 其余候选 |
| `hard`             | 400/404/422（`fallback_allowed=True`）；超限/非法工具 schema/不支持（`False`=NO_FALLBACK）| 否 | 见 `fallback_allowed` |

`model_unavailable` 在 §6 里属于 retryable **一类**（可 fallback），但 kind 独立：
本地模型加载失败时重试同一个模型只是白等一次超时，所以执行器换模型。这一条在
Task 4 的接口里冻结（`llm_retry_per_model` 不作用于它）。

**本文件不 import httpx**（D6：`app/llm/` 内只有 `provider.py` 允许出现 httpx）。
`from_exception` 因此按「异常类的 MRO 名字」识别 httpx 的异常族——类名是 httpx 的公开
稳定面，比 import 多一条依赖边更符合单一出口的收编目标；识别不到时落到「未预期错误」
分支，语义与显式 import 完全一致。

异常文本约束（D3）：`LLMError` 的 message 会被 Task 5 写进 `llm_request_logs.error_type`
相邻的日志面，也常被塞进 trace，所以 `classify` 生成的消息**只含状态码 + provider 回显的
原文摘要**（截断、去控制符）；请求内容、prompt、Authorization 一律不进消息体。
"""
from __future__ import annotations

import re
from typing import Any, Literal

__all__ = [
    "CONFIG_STATUSES",
    "HARD_RETRYABLE_STATUSES",
    "LLMError",
    "MODEL_UNAVAILABLE_MARKERS",
    "MODEL_UNAVAILABLE_PATTERNS",
    "NO_FALLBACK_MARKERS",
    "RETRYABLE_STATUSES",
    "classify",
    "from_exception",
    "from_response",
]
Kind = Literal["retryable", "config", "hard", "model_unavailable"]

# §6 冻结：可重试（同模型重试 1 次，预算内仍败则 fallback）。
RETRYABLE_STATUSES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})
# §6 冻结：凭据/授权问题 → 本次请求内跳过该 provider 的其余候选。
CONFIG_STATUSES: frozenset[int] = frozenset({401, 403})
# §6 冻结：不换当前 provider 重试，但**允许** fallback 下一候选。
HARD_RETRYABLE_STATUSES: frozenset[int] = frozenset({400, 404, 422})
# §6 冻结：本地模型加载失败的 body 特征（Ollama 未常驻/显存不足/模型不存在）。
MODEL_UNAVAILABLE_MARKERS: tuple[str, ...] = (
    "alloc", "failed to load", "model not found", "no such model",
)
# 真机 Ollama 的 404 文案是 `model 'x' not found` / `model "x" not found`——模型名夹在
# 中间，所以**不会**命中上面冻结的 `model not found` 字面（Task 2 报告移交项 → 本条落地）。
# 冻结四枚字面一字不动，这里只**增补**一枚刻意收窄的正则：必须「model + 引号内的名字 +
# not found」三段连在一起才算，于是
# - `Invalid parameter: 'tool_choice' not found in schema`（OpenAI 400）不命中（无 `model` 主语）
# - `404 page not found`（网关 HTML/文本）不命中（同样没有模型名那一段）
# `\\?` 是为了吃 JSON 转义后的引号（Ollama 的 HTTP body 原文是
# `{"error":"model \"x\" not found"}`，classify 收到的正是这段带反斜杠的文本）；
# 命中集是评审给定字面正则的超集。
MODEL_UNAVAILABLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""model\s+\\?['"][^'"]{1,128}\\?['"]\s+not found"""),
)
# §6 冻结：硬终态（NO_FALLBACK）的 body 特征——请求本身不合法，换模型也没用。
NO_FALLBACK_MARKERS: tuple[str, ...] = (
    "payload_too_large", "payload too large", "tool schema", "invalid tool",
    "unsupported", "context_length_exceeded",
)

# 未列入 §6 三张表的状态码的兜底归类（spec 只枚举了常见码，实现必须对全码表有定义）：
# 5xx = 服务端故障 ⇒ retryable；4xx = 请求侧问题 ⇒ hard（仍可 fallback）。
_UNKNOWN_5XX_KIND: Kind = "retryable"
_UNKNOWN_4XX_KIND: Kind = "hard"


class LLMError(Exception):
    """LLM 链的统一异常。`kind` 决定执行器行为，`status_code` 供 usage/trace 归因。

    `no_fallback=True` 即 §6 的 hard terminal（NO_FALLBACK）：执行器必须立即停止并
    返回业务错误，不得再换候选。默认 `False`。
    """

    def __init__(
        self,
        kind: Kind,
        status_code: int | None = None,
        message: str = "",
        *,
        no_fallback: bool = False,
        provider: str = "",
    ) -> None:
        self.kind: Kind = kind
        self.status_code: int | None = status_code
        self.no_fallback = no_fallback
        self.provider = provider
        super().__init__(message or f"{kind}" + (f" (status={status_code})" if status_code else ""))

    @property
    def retryable(self) -> bool:
        """是否允许「重试当前模型」（`llm_retry_per_model`）。

        `model_unavailable` 刻意返回 False：它属于 §6 的可重试**一类**（可以换模型），
        但对同一个未加载成功的模型再发一次只是浪费预算。
        """
        return self.kind == "retryable"

    @property
    def fallback_allowed(self) -> bool:
        """是否可以换下一个候选模型（hard terminal 之外都可以）。"""
        return not self.no_fallback

    @property
    def is_config(self) -> bool:
        """401/403/凭据缺失：执行器据此打 `PROVIDER_CONFIG_FAILED` 并跳过同 provider。"""
        return self.kind == "config"


def classify(status: int, body_text: str) -> LLMError | None:
    """按 §6 表把一个 HTTP 响应归类为 `LLMError`；「不是错误」返回 None。

    判定顺序（冻结，测试逐条钉）：
    1. 状态码 ∈ `CONFIG_STATUSES`（401/403）⇒ `config`——**先于任何 body 特征**。
       网关的凭据/地域拒绝习惯把 `unsupported`、`region` 之类字样写进 message
       （例：401 + `{"error":{"message":"The region is unsupported..."}}`），
       那既是凭据问题也是「换模型没用」的信息，但 §6 的语义是
       `PROVIDER_CONFIG_FAILED`（矩阵 #7），不是 hard terminal，也不是换候选。
    2. body 含 `MODEL_UNAVAILABLE_MARKERS` 字面、或命中 `MODEL_UNAVAILABLE_PATTERNS`
       ⇒ `model_unavailable`。本地模型加载失败最常伪装成 500，且 Ollama 的加载错误文案里
       可能同时出现 `unsupported` 之类字样——它确实是「换模型」而不是「请求不合法」，
       所以这一组优先于 NO_FALLBACK 组。
    3. body 含 `NO_FALLBACK_MARKERS` ⇒ `hard` + `no_fallback=True`（§6 硬终态）。
    4. 状态码表：408/429/500/502/503/504 ⇒ `retryable`；400/404/422 ⇒ `hard`（可 fallback）。
    5. 未列出的状态码：5xx ⇒ `retryable`，4xx ⇒ `hard`（可 fallback）；1xx/2xx/3xx ⇒ None。
    """
    text = (body_text or "").lower()
    detail = _excerpt(body_text)

    if status in CONFIG_STATUSES:
        return LLMError("config", status, f"凭据或授权被拒绝：{detail}")

    hit = _first_marker(text, MODEL_UNAVAILABLE_MARKERS)
    if not hit:
        hit = _first_pattern_hit(text, MODEL_UNAVAILABLE_PATTERNS)
    if hit:
        return LLMError("model_unavailable", status,
                        f"模型不可用（{hit}）：{detail}")
    hit = _first_marker(text, NO_FALLBACK_MARKERS)
    if hit:
        return LLMError("hard", status, f"请求不被支持（{hit}）：{detail}",
                        no_fallback=True)

    if status in RETRYABLE_STATUSES:
        return LLMError("retryable", status, f"上游暂时不可用：{detail}")
    if status in HARD_RETRYABLE_STATUSES:
        return LLMError("hard", status, f"请求不被接受：{detail}")
    if 400 <= status <= 599:
        kind = _UNKNOWN_5XX_KIND if status >= 500 else _UNKNOWN_4XX_KIND
        return LLMError(kind, status, f"未归类的 HTTP 状态：{detail}")
    return None


def from_response(status: int, body_text: str = "") -> LLMError:
    """`classify` 的「总有返回值」版本：2xx 却带错误体（流内 error 帧）也有归类。

    2xx 的错误体既不是凭据问题也不是明确的客户端错误 ⇒ `retryable`（换模型/重试都比
    硬失败更合理），`status_code` 保持原值以便归因。
    """
    error = classify(status, body_text)
    if error is not None:
        return error
    return LLMError("retryable", status, f"响应异常（HTTP {status}）：{_excerpt(body_text)}")


def from_exception(exc: BaseException) -> LLMError:
    """把 httpx / 解析层的异常翻译成 `LLMError`；已是 `LLMError` 的原样返回。

    这里是 provider 层唯一允许读 httpx 异常类型的地方（Task 4 之后业务层只见 `LLMError`）。
    httpx 的类按 MRO 名字识别（见模块 docstring），本文件不 import httpx。
    """
    if isinstance(exc, LLMError):
        return exc

    names = _mro_names(exc)

    if "HTTPStatusError" in names and getattr(exc, "response", None) is not None:
        response = exc.response
        return from_response(int(response.status_code), _safe_text(response))

    if names & _TIMEOUT_CLASS_NAMES:
        # ConnectTimeout / ReadTimeout / WriteTimeout / PoolTimeout 的公共父类。
        return LLMError("retryable", None, f"超时：{type(exc).__name__}")

    if names & _TRANSPORT_CLASS_NAMES:
        # ConnectError / ReadError / WriteError / RemoteProtocolError …：传输层失败。
        return LLMError("retryable", None,
                        f"连接失败（{type(exc).__name__}）：{_excerpt(str(exc))}")

    if isinstance(exc, ValueError):
        # json.JSONDecodeError 是 ValueError 的子类：spec 矩阵 #8「malformed JSON」要求
        # 归类正确而不是崩溃 ⇒ hard（仍可 fallback），刻意不是 retryable（重发同一份坏
        # 响应没有意义）。
        return LLMError("hard", None, f"响应无法解析（{type(exc).__name__}）")

    # 未预期的异常（含 pydantic 校验、编码错误等）：不重试当前模型，但允许换候选，
    # 绝不把非 LLMError 泄漏到执行器（那会让 §10 矩阵的 error_type 归因失效）。
    return LLMError("hard", None, f"未预期错误（{type(exc).__name__}）：{_excerpt(str(exc))}")


# httpx 异常族的类名（ timeouts 与 transport 两组）。用名字而不是类对象识别：
# `httpx.TimeoutException` 之下所有具体超时类都带 "Timeout" 字样，`TransportError` 之下
# 的传输类同理；两组先判 timeout，因为 `ConnectTimeout` 同时属于两组（都是 retryable，
# 但消息要写「超时」而不是「连接失败」）。
_TIMEOUT_CLASS_NAMES: frozenset[str] = frozenset({
    "TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout",
    "PoolTimeout",
})
_TRANSPORT_CLASS_NAMES: frozenset[str] = frozenset({
    "TransportError", "ConnectError", "ReadError", "WriteError", "NetworkError",
    "ProtocolError", "RemoteProtocolError", "LocalProtocolError", "ProxyError",
    "UnsupportedProtocol",
})


def _mro_names(exc: BaseException) -> frozenset[str]:
    return frozenset(cls.__name__ for cls in type(exc).__mro__)


def _first_marker(text: str, markers: tuple[str, ...]) -> str:
    for marker in markers:
        if marker in text:
            return marker
    return ""


def _first_pattern_hit(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    """正则版的 `_first_marker`，返回**压平且截断**的命中原文。

    命中片段来自 provider 回显（可能含换行），而它要进错误消息（D3：日志/trace 面），
    所以与 `_excerpt` 同规格处理：空白折叠 + 截断。
    """
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return _excerpt(match.group(0), 80)
    return ""


def _safe_text(response: Any) -> str:
    """尽力取响应体文本；取不到也不能让错误分类本身抛出去。"""
    try:
        return str(response.text)
    except Exception:  # pragma: no cover - 已消费的流响应等极端情况
        return ""


def _excerpt(text: str, limit: int = 200) -> str:
    """错误消息里的 body 摘要：压掉换行/控制符并截断，避免把整段模型输出搬进日志。"""
    cleaned = " ".join(str(text or "").split())
    return cleaned[:limit]
