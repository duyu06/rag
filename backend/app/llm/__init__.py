"""统一 LLM 出口包（Model Router V2.3，spec §2 冻结目录）。

Task 2 加了 `errors` / `normalize` / `provider` / `health` 四个模块，本文件的再导出清单
随之扩到「异常 + 健康探测」两组符号。**刻意不再导出** `provider.complete` /
`provider.stream`：业务侧唯一合法入口是本文件里 `llm.complete()` / `llm.stream()` 这一层
编排（classifier → router.plan → fallback.run_* → provider），
把 provider 的同名函数摆在包级别上等于给业务递一条绕过路由的后门。
`run_complete` / `run_stream` 两个执行器入口**是**再导出的：拿到 `RoutePlan` 的离线回放与
测试要绕开 classifier 直接驱动执行层，那仍然是「走路由」，不是后门。

Task 3 加了 `classifier` / `router` 两个**纯函数**模块，本文件随之再导出 `classify` /
`plan` / `NoCapableModelError` / `REASON_CODES`。它们是编排的零件而不是业务入口：调用方
（Task 6/7/8 的三条链）应该走 `llm.complete/stream`，直接 `plan()` 只在测试与离线回放里
出现——绕开 fallback 的计划没人执行，也就没人负责 D2 的降级。

`warmup` 是 `app.llm.registry.warmup` 的**同一对象**（本文件只做再导出/转发，不包一层）：
Task 5 接 lifespan 时无论走 `llm.warmup()` 还是 `registry.warmup()` 都会跑「加载 + provider
分发面校验」（Task 2 评审 I-3），两条路径不会有强度差。

温度（Task 2 评审 I-4，Task 6 的硬义务）：**`RAG_LEGACY_TEMPERATURE` 以本文件为单一出处**。
provider/normalize 两层刻意不注入默认温度（`LLMRequest.temperature` 的默认 0.2 是 Task 1
冻结的通用默认，不是 rag 链的现值），所以 **Task 6 必须以该常量构造 LLMRequest**——
即 `LLMRequest(temperature=RAG_LEGACY_TEMPERATURE)`；漏掉就是把 rag 链的采样温度从现网的
0.1 静默改成 0.2（行为变更，矩阵 #18 的 legacy 双路等价断言会红）。

Task 4 把业务入口填进了本文件：`router_enabled()` / `complete()` / `stream()`。至此
「能 import 但不能调用」的空档消失，包级别也获得了唯一的编排出口：
`classify → plan（带熔断态的 health_view）→ fallback.run_* → usage 接缝`。

`LLM_ROUTER_ENABLED` 旗标在本包里**只被 `router_enabled()` 读一次**（Task 4 的冻结口径：
legacy 分支属于**调用方**——rag/SSE/agent 三条链各自 `if router_enabled(): ... else: 原代码`，
矩阵 #18 的双路契约测试也就钉在那三个文件里）。原因：`complete()` 是路由开启后的唯一
合法路径，如果它内部再藏一条 legacy 旁路，那么「旗标关掉」这件事在 llm 包里就既看不见
也测不到，而三条链的 if 分支会长成第四种形状。

usage 记账（Task 5）走本文件的**接缝**：`set_usage_sink(callable)` 注册一个
`UsageRecord → None` 的落库函数；未注册时 `complete()` 会惰性尝试
`app.llm.usage.log_usage`（Task 5 建好该模块后**无需改这里**就会自动接上），再取不到就
静默跳过。所有落库动作都是 fail-open（异常吞进 warning，D3），记账永不影响生成。
`stream()` 侧的账由调用点在 `session.finish()` 之后交给 `log_stream_usage()`——那里才有
ttft 与 commit 事实，包级别不猜会话的生命周期。
trace 的 `model_route` 对象**不在本包构造**：§8.1 第 4 条定了唯一生产者
`app.llm.usage.model_route_trace()` 与唯一挂载点 `app.agent_trace.attach_model_route()`。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from app.config import settings
from app.llm import fallback
from app.llm.classifier import classify
from app.llm.errors import LLMError
from app.llm.fallback import (
    AllCandidatesFailedError,
    Attempt,
    FallbackResult,
    StreamInterrupted,
    StreamSession,
    StreamSummary,
    reset_circuit_breakers,
    run_complete,
    run_stream,
)
from app.llm.health import probe_llm, probe_ollama, provider_health_view
from app.llm.models import (
    CAPABILITY_KEYS,
    PRIORITY_KEYS,
    LLMChunk,
    LLMRequest,
    LLMResponse,
    ModelCapabilities,
    ModelDefinition,
    ModelLimits,
    ModelPricing,
    RequestProfile,
    RouteCandidate,
    RoutePlan,
    ToolCall,
    UsageRecord,
)
from app.llm.registry import (
    ProviderCredentials,
    Registry,
    RegistryError,
    get_registry,
    load_registry,
    provider_credentials,
    reset_registry,
    warmup,
)
from app.llm.router import REASON_CODES, NoCapableModelError, plan

# rag.py legacy 非流式路径的现值（0.1）——**单一出处**（Task 2 评审 I-4）。
# 放包级别而不是 `normalize.py`：报文层（normalize）与出口层（provider）都不注入默认
# 温度，这个常量只服务于「构造 LLMRequest 的调用方」（Task 6 的 rag 链，以及任何要继续
# 保持 legacy 采样温度的链路）——消费方在包外，出处就该在包上。
RAG_LEGACY_TEMPERATURE = 0.1

logger = logging.getLogger("app.llm")

# --------------------------------------------------------------------------
# usage 记账接缝（Task 5 落库，D3 fail-open）
# --------------------------------------------------------------------------
#: `UsageRecord → None`。Task 5 在导入 `app.llm.usage` 时注册，或本文件惰性解析同名函数。
_usage_sink: Callable[[UsageRecord], None] | None = None


def set_usage_sink(sink: Callable[[UsageRecord], None] | None
                   ) -> Callable[[UsageRecord], None] | None:
    """注册（或传 None 清除）落库函数，返回**前一个** sink。

    存在的全部理由是「Task 4 负责编排、Task 5 负责记账」这条任务边界：没有这个接缝，
    T4 就得 import 一个还不存在的模块；有了它，T5 只要 `llm.set_usage_sink(log_usage)`
    一行（或什么都不做——`app/llm/usage.py` 里出现 `log_usage` 就会被惰性解析到）。
    """
    global _usage_sink
    previous = _usage_sink
    _usage_sink = sink
    return previous


def usage_sink() -> Callable[[UsageRecord], None] | None:
    """当前生效的落库函数：显式 sink 优先，其次惰性解析 `app.llm.usage.log_usage`。"""
    if _usage_sink is not None:
        return _usage_sink
    try:
        from app.llm import usage as usage_module       # 惰性：T5 之前该模块不存在
    except ImportError:
        return None
    return getattr(usage_module, "log_usage", None)


def _log_usage(record: UsageRecord) -> None:
    """把一条账交出去。**任何异常都吞进 warning**（D3：记账失败绝不影响生成）。"""
    sink = usage_sink()
    if sink is None:
        return
    try:
        sink(record)
    except Exception as exc:                            # noqa: BLE001 - fail-open 是义务
        logger.warning("LLM usage 记账失败（fail-open，不影响生成）：%s: %s",
                       type(exc).__name__, exc)


__all__ = [
    "CAPABILITY_KEYS",
    "AllCandidatesFailedError",
    "Attempt",
    "FallbackResult",
    "LLMChunk",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "PRIORITY_KEYS",
    "RAG_LEGACY_TEMPERATURE",
    "ModelCapabilities",
    "ModelDefinition",
    "ModelLimits",
    "ModelPricing",
    "NoCapableModelError",
    "ProviderCredentials",
    "REASON_CODES",
    "Registry",
    "RegistryError",
    "RequestProfile",
    "RouteCandidate",
    "RoutePlan",
    "StreamInterrupted",
    "StreamSession",
    "StreamSummary",
    "ToolCall",
    "UsageRecord",
    "classify",
    "complete",
    "effective_model_name_for_entry",
    "get_registry",
    "load_registry",
    "log_stream_usage",
    "plan",
    "probe_llm",
    "probe_ollama",
    "provider_credentials",
    "provider_health_view",
    "reset_circuit_breakers",
    "reset_registry",
    "router_enabled",
    "run_complete",
    "run_stream",
    "set_usage_sink",
    "stream",
    "usage_sink",
    "warmup",
]


# --------------------------------------------------------------------------
# 旗标
# --------------------------------------------------------------------------
def router_enabled() -> bool:
    """`LLM_ROUTER_ENABLED`（§12，默认 true）。**本包里唯一读这个旗标的地方**。

    三条链（T6 rag / T7 SSE / T8 agent）用它在调用点二选一：真 ⇒ 走 `complete/stream`，
    假 ⇒ 走原 legacy 代码。旗标的分支不进本包（见模块 docstring）：那样「关掉」在 llm
    包里既不可见也不可测，矩阵 #18 的双路契约测试就没有落点。
    """
    return bool(settings.llm_router_enabled)


# --------------------------------------------------------------------------
# 业务入口
# --------------------------------------------------------------------------
def complete(messages: list[dict[str, Any]], *,
             mode: Literal["chat", "rag", "agent"],
             temperature: float = 0.2,
             tools: list[dict[str, Any]] | None = None,
             think: bool | None = None,
             num_predict: int | None = None,
             keep_alive: str | None = None,
             needs_stream: bool = False,
             trace_id: str | None = None,
             request_id: str | None = None,
             profile: RequestProfile | None = None) -> FallbackResult:
    """统一非流式生成入口：classify → plan → run_complete → usage 接缝。

    - `mode` 由**调用点声明**（§4：禁 LLM 判路由，也禁猜）。越界 mode 在 `classify` 入口
      就 `ValueError`——那是编程错误，不是降级路径。
    - `profile` 给定时**跳过 classifier**（调用方已算过画像，或离线回放要复现某个画像）。
      注意画像里的 `needs_stream` 以传入值为准：本函数是非流式入口，`needs_stream=True`
      只会把候选收口到「支持流式的模型」，不会让这次调用变成流式。
    - `NoCapableModelError`（D2）与 `AllCandidatesFailedError` / 硬终态 `LLMError`
      **一律透传不吞**：降级是调用链的权利（rag 的兜底文案、agent 的 local fast-path），
      包级别替它们决定「返回什么错误」就会偷走那条链的降级语义。异常在透传前只用来
      补一条失败账（`success=False`），不改类型、不改对象。
    """
    request = _request(messages, temperature=temperature, tools=tools, think=think,
                       num_predict=num_predict, keep_alive=keep_alive)
    routing_profile = profile or classify(
        _query_of(messages), mode=mode, needs_tools=bool(tools), needs_stream=needs_stream)
    try:
        result = run_complete(_plan(routing_profile), request,
                              trace_id=trace_id, request_id=request_id)
    except LLMError as exc:
        # 聚合失败与硬终态都在这里补一条失败账，然后**原对象上抛**（不吞、不换类型）。
        _log_usage(_usage_from_failure(exc, routing_profile, mode,
                                       trace_id=trace_id, request_id=request_id))
        raise
    _log_usage(_usage_from_result(result, routing_profile, mode,
                                  trace_id=trace_id, request_id=request_id))
    return result


def stream(messages: list[dict[str, Any]], *,
           mode: Literal["chat", "rag", "agent"],
           temperature: float = 0.2,
           tools: list[dict[str, Any]] | None = None,
           think: bool | None = None,
           num_predict: int | None = None,
           keep_alive: str | None = None,
           needs_stream: bool = True,
           trace_id: str | None = None,
           request_id: str | None = None,
           profile: RequestProfile | None = None) -> StreamSession:
    """统一流式入口。返回**未开始外呼**的 `StreamSession`（§7：pre-commit 才能静默换模型）。

    与 `complete()` 的两处刻意的不同：
    1. `needs_stream` 默认 **True**（这条链就是要流），调用方要显式关掉才会放宽候选；
    2. 这里不写成功账——ttft / commit 事实 / usage 都只在 `finish()` 之后才存在，
       所以交给调用点在会话结束时调 `log_stream_usage(session.finish(), ...)`。
       全链 pre-commit 皆败时 `chunks()` 抛 `AllCandidatesFailedError`，**同一个调用式**
       仍然成立（`finish()` 在抛错后可调，汇总里带 `error_type`），所以两条出口不会
       长成套两套 try/except 的债。
    """
    request = _request(messages, temperature=temperature, tools=tools, think=think,
                       num_predict=num_predict, keep_alive=keep_alive)
    routing_profile = profile or classify(
        _query_of(messages), mode=mode, needs_tools=bool(tools), needs_stream=needs_stream)
    # `run_stream` 只可能在这里抛 `NoCapableModelError`（上下文收口后零候选，D2 降级）；
    # 候选链的失败要到消费 `chunks()` 时才冒出来，所以这里没有可补的账。
    return run_stream(_plan(routing_profile), request,
                      trace_id=trace_id, request_id=request_id)


def log_stream_usage(summary: StreamSummary, *, profile: RequestProfile | None = None,
                     mode: str = "", trace_id: str | None = None,
                     request_id: str | None = None) -> UsageRecord:
    """把一次流式会话的 `finish()` 汇总折成 §8 的一行并交给 sink，返回该行本身。

    `model` 列与非流式的 `_usage_from_result` **同一个口径**：生效模型名（provider 真正
    被调用的那个名字），不是注册表条目 id。`StreamSummary` 只带条目 id（执行面的候选是
    条目），所以这里按条目回查一次注册表并套用 D1 的 `model_override`；查不到（条目已
    从注册表里删掉、注册表不可用）才退回 id —— 宁可留一个可解释的 id，也不要空串。
    劈叉不修的后果是 §8 的 `model` 列在两条链上指两种东西，任何按模型聚合的账都要
    先判一次「这行是流式的还是非流式的」。

    `estimated_cost` / `currency` 不在这里算：单价在注册表条目里，而折算发生在
    `usage.log_usage`（Task 5）—— 谁拥有账本谁负责算成本，T4 不猜价。`fallback_index`
    直接是 `selected_index`，未选中（全败）时是 -1 —— 判成功用 `summary.completed`，
    不要判 `committed`（commit 后中断的会话既交付过内容、又没有走完，两半都是事实）。

    `latency_ms` 与非流式的 `_usage_from_result` **同口径**：`_chain_latency_ms(attempts)`
    （各 attempt 实测延迟之和）。这里刻意不用 `summary.budget_ms`——那是配置常数
    （`llm_total_budget_ms`，默认 30000），把它写进 `latency_ms` 等于把 §8 的
    `p95_latency_ms` 钉死在预算天花板上：一条 300ms 就答完的流式链也会算成 30 秒，
    且慢链与快链在观测面上不可区分。`budget_ms` 本身是「这次给了多少预算」的事实，
    归 trace / `StreamSession` 消费面；§8 的 19 列**已冻结且没有 budget 列**（D3），
    所以它不落这张表，也不在这里顺手加列。
    """
    record = UsageRecord(
        trace_id=trace_id, request_id=request_id,
        route_mode=mode or (profile.mode if profile is not None else ""),
        route_reason=summary.reason_codes,
        provider=summary.provider_name, model=_effective_model_name(summary.model_id),
        fallback_index=summary.selected_index,
        input_tokens=int(summary.usage.get("input_tokens", 0)),
        output_tokens=int(summary.usage.get("output_tokens", 0)),
        total_tokens=int(summary.usage.get("total_tokens", 0)),
        ttft_ms=summary.ttft_ms,
        latency_ms=_chain_latency_ms(summary.attempts),
        success=summary.completed,
        error_type=summary.error_type,
        status_code=None)
    _log_usage(record)
    return record


def effective_model_name_for_entry(entry: ModelDefinition) -> str:
    """注册表条目 → **生效模型名**（含 D1 的 `{PROVIDER}_MODEL_OVERRIDE`）——唯一实现。

    Task 5 评审 Minor 7 数出过两份这件事的实现（本文件按条目 id 查一次注册表的那一份 +
    `app/llm/usage.py::_entry_effective_name`）。它们都委托 `provider.effective_model_name`
    这同一份解析，所以别名不会一边有一边无——但代码是两份，删掉 `model_route_payload()`
    之后本文件这一份只剩「按 id 查条目」这一层壳，于是把**解析**并成现在这一个公共件：
    账本复用它在 `_entry_effective_name`（外面再套一道字符集白名单），流式记账复用它在
    `_effective_model_name`（外面再套一道注册表查找）。

    局部 import `provider`：包级出口面刻意不出现 `provider.*`（模块 docstring 第一段——
    业务侧不许绕过路由直接调 provider），而这里要的只是一次名字换算，不是外呼入口。
    凭据解析失败（provider 没配 base_url ⇒ `credentials_for_provider` 抛 `RegistryError`）
    只意味着「没有别名可用」，退回注册表声明名即可：一个名字不值得把整行账或整条链丢掉。
    """
    try:
        from app.llm.provider import effective_model_name
        from app.llm.registry import credentials_for_provider

        return effective_model_name(
            entry, credentials_for_provider(entry.provider, label=entry.id))
    except (RegistryError, TypeError, ValueError):
        return entry.model or entry.id


def _effective_model_name(entry_id: str) -> str:
    """注册表条目 id → 生效模型名（`effective_model_name_for_entry` 的按-id 外壳）。

    与非流式的 `LLMResponse.model` 对齐：那一条取自 provider 回显，回显缺失时是
    `provider.effective_model_name(条目, 凭据)`。注册表里查不到这个 id（条目被删 /
    注册表不可用）⇒ 退回原 id：一条能解释的 id 比一个空串有用，且 `usage.log_usage`
    那一层还有一次字符集白名单兜着。
    """
    if not entry_id:
        return ""
    try:
        entry = get_registry().get(entry_id)
    except RegistryError:
        return entry_id
    return effective_model_name_for_entry(entry)


# --------------------------------------------------------------------------
# 入口的内部零件
# --------------------------------------------------------------------------
def _request(messages: list[dict[str, Any]], *, temperature: float,
             tools: list[dict[str, Any]] | None, think: bool | None,
             num_predict: int | None, keep_alive: str | None) -> LLMRequest:
    """`LLMRequest` 的唯一构造点（Ollama 专有项保持可选）。"""
    return LLMRequest(
        messages=list(messages or []), temperature=temperature,
        tools=list(tools or []), think=think, num_predict=num_predict,
        keep_alive=keep_alive)


def _query_of(messages: list[dict[str, Any]]) -> str:
    """分类器读的问题文本 = **最后一条消息**的 content（没有就空串）。

    只看最后一条是刻意的：整段拼接会把 rag 的上下文块（几千字检索原文）算进复杂度判定，
    于是任何带上下文的请求都是 high——那不再是「问题难不难」，而是「上下文长不长」，
    而 length 这个维度已经由 §5 的 limits 与 T4 的上下文收口在处理了。
    `complexity` 今天不参与打分（T3 偏离 3），所以这个口径只影响 trace 可读性。
    """
    for message in reversed(list(messages or [])):
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _plan(profile: RequestProfile) -> RoutePlan:
    """画像 → 计划。health_view 带熔断态（`routing_health_view`，T3 移交的闭环）。"""
    registry = get_registry()
    return plan(profile, registry, fallback.routing_health_view(registry))


def _chain_latency_ms(attempts: tuple[Attempt, ...]) -> float:
    """全链耗时 = 各 attempt 实测延迟之和（预算消费口径）。

    与 `LLMResponse.latency_ms`（最后一次成功外呼的单程）不是一回事：一条走了两跳的链
    对用户的耗时是两跳之和，§8 的 `p95_latency_ms` 要的是前者。
    """
    return round(sum(float(a.latency_ms) for a in attempts), 3)


def _usage_from_result(result: FallbackResult, profile: RequestProfile | None, mode: str, *,
                       trace_id: str | None, request_id: str | None) -> UsageRecord:
    response = result.response
    return UsageRecord(
        trace_id=trace_id, request_id=request_id,
        route_mode=mode or (profile.mode if profile is not None else ""),
        route_reason=result.reason_codes,
        provider=response.provider, model=response.model,
        fallback_index=result.selected_index,
        input_tokens=int(response.input_tokens), output_tokens=int(response.output_tokens),
        total_tokens=int(response.input_tokens) + int(response.output_tokens),
        ttft_ms=None, latency_ms=_chain_latency_ms(result.attempts), success=True,
        error_type=None, status_code=None)


def _usage_from_failure(exc: LLMError, profile: RequestProfile | None,
                        mode: str, *, trace_id: str | None,
                        request_id: str | None) -> UsageRecord:
    """失败行：`AllCandidatesFailedError` 带 attempts/理由码，硬终态 `LLMError` 都不带。

    两类都落同一张表：`error_type` 取 `kind`（机器码），`attempts` 缺省即空集，
    于是硬终态是一行「有错误、没有候选链事实」的账——这正是它该有的样子（请求没走完链）。
    """
    attempts = tuple(getattr(exc, "attempts", ()) or ())
    reason_codes = tuple(getattr(exc, "reason_codes", ()) or ())
    last = attempts[-1] if attempts else None
    return UsageRecord(
        trace_id=trace_id, request_id=request_id,
        route_mode=mode or (profile.mode if profile is not None else ""),
        route_reason=reason_codes,
        provider=last.provider if last is not None else (exc.provider or ""),
        model=last.model_id if last is not None else "",
        fallback_index=-1,                       # 没有选中任何候选
        input_tokens=0, output_tokens=0, total_tokens=0,
        ttft_ms=None, latency_ms=_chain_latency_ms(attempts), success=False,
        error_type=exc.kind, status_code=exc.status_code)
