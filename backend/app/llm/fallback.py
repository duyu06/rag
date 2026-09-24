"""FallbackExecutor（spec §7）：重试 / 逐 provider 熔断 / 总预算 / 流式 commit 的**唯一执行层**。

调用链在这一层落地成事实::

    llm.complete|stream → classifier → router.plan → **本文件** → provider（唯一出口）

`router.plan()` 只裁决「谁有资格」，不发请求；`provider.py` 只发一次请求并归类错误，
不决定换不换。「按顺序试、试几次、还花多少预算、熔断器记不记账、流式能不能改口」——
这四件事全部只在本文件里发生，因此 D2/D4/D5 的行为义务都在这里被钉住。

冻结的六条执行语义（spec §6/§7 + D4/D5）
----------------------------------------
1. **候选链** = `RoutePlan.primary` + `fallbacks`，按顺序执行；`selected_index` 是
   **收口后链**的 0 基下标（即 §10 #4/#5 期望的 `fallback_index`）。
2. **上下文前置收口**（Task 3 评审移交①）：`plan()` 的入参里没有请求体（路由输入必须是
   可复现的值对象），所以「这次请求装不装得下」只能在这里裁决。收口后为空 ⇒
   自己抛 `NoCapableModelError(stage="context")`，**不新造理由码**（冻结枚举之外一个都不加）。
3. **重试预算**：只有 `kind="retryable"` 才重试当前模型，次数 `llm_retry_per_model`；
   `model_unavailable` 立刻换候选（对同一个加载失败的模型再发一次只是白等一次超时）、
   `config` 不重试当前且**本次请求内跳过该 provider 的其余候选**、`hard` 不重试当前但可换
   候选、`hard + no_fallback`（NO_FALLBACK）立即上抛原 `LLMError`。
4. **总预算制**（§6）：`TimeoutBudget(soft_ms=budget*0.7, hard_ms=budget)`，
   每次**真实外呼**前的 timeout = `min(llm_model_timeout_seconds, remaining/1000)`；
   多个 attempt 共享同一份预算（禁相加），`remaining <= 0` 就停止外呼并抛聚合错误。
5. **熔断记账口径（D4 + §6「每真实调用回执」）**：一次真实外呼换一条回执。
   `retryable` / `model_unavailable` / `config` ⇒ `record(False)`（provider 侧的失败事实）；
   `hard` ⇒ **视情况**：带 HTTP 状态码的 hard 说明对方活着并回了话（坏的是我们的请求），
   记 `record(True)`；不带状态码的 hard（未登记 provider、未发出的请求、未预期异常）
   记 `record(False)`。这条偏序的决定性论据在 **HALF_OPEN 的判活规则**上（见
   `app/resilience.py`）：该状态下只有 `record(True)` 算探测通过，任一 `record(False)`
   立即 `_trip()` 回 OPEN。于是**一条永久坏的自己人请求**（400/404/422 报文是我们写错的）
   若记 False，就会在每个冷却窗口把 healthy 的 provider 重新闸住 `open_seconds`，
   锁死在 OPEN → HALF_OPEN → OPEN 的循环里谁也过不去；带状态码即「对方在线」，
   记 True 才把健康 provider 留在服务面上。
   （顺带：回执**必须给**——HALF_OPEN 的探测名额没有租约回收，放行后永不回执会把名额
   占到状态切换。）
   `allow()` 为假 ⇒ 一条 `Attempt(result="skipped_circuit")` + `CIRCUIT_OPEN`，**不 record**
   （没有真实调用就没有回执，且 `resilience.py` 明确要求丢弃熔断期的迟到回执）。
   熔断打开**不污染** `healthy`（D4「OPEN 时不标 degraded」）⇒ `routing_health_view()` 里
   `healthy` 与 `circuit_open` 是两个独立键。
6. **流式 commit 边界（§7 第四段冻结）**：第一个**内容** chunk 交给消费方即
   `committed=True`。此前的失败 = 静默换下一候选重开（用户无感，`attempts` 逐次留痕）；
   此后的失败 = **禁止换模型**，抛 `StreamInterrupted(partial_text, attempts, selected_index)`，
   由 SSE 层落成现行事件词汇的 `error` + `done`（D5）。空文本 chunk（usage / finish 块）
   **不算内容**：未提交时先扣住不吐，避免「已经给用户看到东西」与「committed」两个事实分家。

时间源与时钟接缝
----------------
本文件所有计时都走 `_now()`，`TimeoutBudget` 也用同一个 `_now()` 构造。测试把它换成假钟
即可**确定性地**断言「每次外呼的 timeout 逐次收缩」（矩阵 #5 与预算用例），不必真等
30 秒。生产路径恒为 `time.perf_counter`。

D6 义务：本文件不 import httpx、不出现报文路径或凭据字面量，外呼只经 `provider` 模块属性
（同时也是测试的 stub 接缝）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Iterator, Literal, Mapping

from app.config import settings
from app.llm import errors, health, provider, router
from app.llm.errors import LLMError
from app.llm.models import (
    LLMChunk,
    LLMRequest,
    LLMResponse,
    ModelDefinition,
    RequestProfile,
    RouteCandidate,
    RoutePlan,
)
from app.llm.registry import Registry, get_registry
from app.llm.router import (
    CIRCUIT_OPEN,
    FALLBACK_AFTER_TIMEOUT,
    PROVIDER_CONFIG_FAILED,
    NoCapableModelError,
)
from app.resilience import CircuitBreaker, TimeoutBudget

__all__ = [
    "AllCandidatesFailedError",
    "Attempt",
    "BREAKERS",
    "CONTEXT_CHARS_PER_TOKEN",
    "FallbackResult",
    "StreamInterrupted",
    "StreamSession",
    "StreamSummary",
    "circuit_breaker",
    "circuit_is_open",
    "estimate_prompt_tokens",
    "fit_chain_to_context",
    "reset_circuit_breakers",
    "routing_health_view",
    "run_complete",
    "run_stream",
]

logger = logging.getLogger("app.llm.fallback")

# --------------------------------------------------------------------------
# 常量（口径的唯一出处）
# --------------------------------------------------------------------------
#: 上下文粗估的折算口径：**2 个字符 ≈ 1 token**（Task 3 报告移交①逐字给定的公式）。
#: 中文按字计，偏保守；它只做「装不装得下」的裁决，不是账单（账单在 §8 的 usage 面）。
CONTEXT_CHARS_PER_TOKEN = 2

#: `Attempt.result` 的三个取值（冻结）。`skipped_circuit` 与 `failed` 的区别是
#: 「一次请求都没发出」，因此前者永远不带 `error_type`。
AttemptResult = Literal["success", "failed", "skipped_circuit"]

_GO = "go"
_SKIP = "skip"
_STOP = "stop"
_GateState = Literal["go", "skip", "stop"]


def _now() -> float:
    """唯一的时钟入口（延迟计量与 `TimeoutBudget` 共用）。测试的假钟接缝就在这里。"""
    return time.perf_counter()


# --------------------------------------------------------------------------
# 值对象
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Attempt:
    """一次**候选级**回执（§6 `RouteAttemptResult.attempts`、§8 trace 的 `model_route`）。

    - 一次真实外呼（含同模型重试）产出一条；重试多条就是多条，`error_type` 逐条归因。
    - `skipped_circuit` 与「因同 provider 已 config 失败而跳过」不同：前者进 `attempts`
      （D4 要求 reason 记 `CIRCUIT_OPEN`，读 trace 的人要看见它被闸掉了），后者**不进**
      ——它既没有真实调用、也没有自己的错误事实，`PROVIDER_CONFIG_FAILED` 已经描述了整组
      跳过，多一条同名 Attempt 只会让 `fallback_rate` 的聚合口径变糊。
    - `error_type` 取 `LLMError.kind`（机器码，不做文案）；无错误时为 None。
    """

    model_id: str
    provider: str
    result: AttemptResult
    error_type: str | None = None
    latency_ms: float = 0.0


@dataclass(frozen=True)
class FallbackResult:
    """非流式执行结果（brief 冻结的五字段 + 两个可加字段）。

    `reason_codes` = `RoutePlan.reason_codes`（入选/剔除理由，顺序在前）+ 执行期码
    （`FALLBACK_AFTER_TIMEOUT` / `PROVIDER_CONFIG_FAILED` / `CIRCUIT_OPEN`），按首次出现去重
    ——T3 报告移交③要求的「T5 直接 concat」在这里已经做完，`usage.route_reason` 可直接落库。

    `context_dropped` 是 Task 3 评审移交④要的**被剔计数**（上下文收口吃掉的候选条数）：
    trace 的 `model_route` 要「带 stage + 被剔计数、不造新 reason 码」，被剔计数没地方放
    就解释不了「为什么链比计划短」。默认 0，不影响既有五字段的构造顺序。

    `plan` 是 **Task 5 评审裁定 C 的 (c) 变体**（复审 N4 移交 T6）：`llm.complete()` 只返回
    本对象、不把 `RoutePlan` 递出来，而 `usage.model_route_trace()` 的计划面必需它。三条链
    的挂载形状因此固定为 `attach_model_route(trace, result.plan, result, profile=profile)`。
    刻意**没有**改 `complete()/stream()` 的返回对象、也**没有**加回调参数（评审否掉的两条：
    前者动返回形状，后者要三条链各自闭包传参、形状更容易漂）。frozen dataclass 的
    **末位带默认值** ⇒ 既有的五/六字段构造断言与位置参都不破。
    """

    response: LLMResponse
    attempts: tuple[Attempt, ...] = ()
    selected_index: int = 0
    reason_codes: tuple[str, ...] = ()
    budget_ms: float = 0.0
    context_dropped: int = 0
    plan: RoutePlan | None = None


@dataclass(frozen=True)
class StreamSummary:
    """`StreamSession.finish()` 的汇总（§8 记账与 §7 commit 事实的消费面）。

    `response_text` 「可选」的口径：一个 chunk 都没产出且没提交 ⇒ None（这次会话对用户
    没有说过一个字）；否则是已产出文本的拼接（成功收尾时是全文，commit 后中断时是残缺部分）。
    `usage` 只取**成功收尾那一轮**的 provider 回执（多 attempt 不叠加，失败轮次的 usage
    是半截账），缺失时全 0 且 `estimated=True`。`selected_index` 在没有成功候选时是 **-1**。

    `completed` / `error_type` 是为 §8 的 `success` / `error_type` 两列加的**可加字段**：
    一次会话有三种终态，只看 `committed` 分不开——
    * 走完 ⇒ `completed=True`、`committed` 视是否交付过内容；
    * commit 后中断 ⇒ `completed=False`、`committed=True`、`error_type` 是原始归类；
    * pre-commit 全败 ⇒ `completed=False`、`committed=False`、`selected_index=-1`。

    `plan` 与 `FallbackResult.plan` 同名同语义（Task 5 评审裁定 C 的 (c) 变体 / 复审 N4）：
    T7 的 SSE 链在 `session.finish()` 之后拿 `summary.plan` 去
    `attach_model_route(trace, summary.plan, summary, profile=profile)`，不必改 `stream()`
    的返回形状。末位带默认值 ⇒ 既有的位置参构造与 T4 的字段序断言都不破。
    """

    response_text: str | None
    usage: dict[str, Any]
    ttft_ms: float | None
    attempts: tuple[Attempt, ...]
    selected_index: int
    reason_codes: tuple[str, ...] = ()
    committed: bool = False
    completed: bool = False
    error_type: str | None = None
    model_id: str = ""
    provider_name: str = ""
    budget_ms: float = 0.0
    context_dropped: int = 0
    plan: RoutePlan | None = None


class AllCandidatesFailedError(LLMError):
    """整条候选链走完仍未成功（§7 的聚合出口）。

    刻意是 `LLMError` 的子类：三条链今天就在 `except LLMError` 里落各自的兜底文案，
    聚合失败不该成为第二种需要新增 catch 的异常（D2「不得给用户裸错」）。
    `kind` 沿用**最后一个真实失败**的归类（没有失败可沿用 ⇒ `hard`，例如全被熔断闸掉），
    于是日志与 usage 的 `error_type` 仍然指向真正的原因，而不是一个自造词。
    `attempts` / `reason_codes` / `budget_exhausted` 供 trace 与 T7 的 payload 增量消费。

    `plan` / `context_dropped` 与 `FallbackResult`、`StreamSummary` **同名同语义**（Task 5
    评审裁定 C + 复审 N4）：全链失败正是 trace 的 `model_route` 最需要解释的那一条，而
    §8.1 第 4 条的九键里 `context_dropped` 在降级路上原本会成哑键（执行面明明知道剔了几条）。
    两者都是**末位带默认值**的可加参数 ⇒ 既有构造（含 T5 直接 `AllCandidatesFailedError(
    attempts, reason_codes=…)` 的那几例）不受影响，读不到事实时仍落 `None` / 0。

    异常文本只含**计数与归类**，不含消息内容（D3）。
    """

    def __init__(self, attempts: tuple[Attempt, ...] | list[Attempt], *,
                 reason_codes: tuple[str, ...] = (), budget_exhausted: bool = False,
                 last_error: LLMError | None = None, profile: RequestProfile | None = None,
                 chain_size: int = 0, message: str = "",
                 plan: RoutePlan | None = None, context_dropped: int = 0) -> None:
        self.attempts: tuple[Attempt, ...] = tuple(attempts)
        self.reason_codes: tuple[str, ...] = tuple(reason_codes)
        self.budget_exhausted = budget_exhausted
        self.last_error = last_error
        self.profile = profile
        self.chain_size = chain_size
        # 执行面事实（与 `FallbackResult` / `StreamSummary` 同名同语义）：`plan` 供
        # `attach_model_route(trace, exc.plan, exc, profile=…)`，`context_dropped` 让
        # 「链为什么比计划短」在降级行里也有词可用。
        self.plan: RoutePlan | None = plan
        self.context_dropped: int = int(context_dropped or 0)
        kind = last_error.kind if last_error is not None else "hard"
        status_code = last_error.status_code if last_error is not None else None
        if not message:
            message = _all_failed_message(self.attempts, budget_exhausted, chain_size)
        super().__init__(kind, status_code, message, provider=_dominant_provider(
            self.attempts, last_error))


class StreamInterrupted(Exception):
    """**commit 之后**流被切断（§7 冻结：此时禁止换模型）。

    刻意**不**是 `LLMError` 的子类：`LLMError` 在执行链上的语义是「一次 provider 往返的
    失败归类，执行器已据此裁决完毕」，而这里的语义是「会话终止 + 已交付内容」——如果它
    落进同一个 `except LLMError` 分支，调用方很容易顺手把整条链再跑一遍，用户就会看到
    两段接在一起的、来自不同模型的回答。所以 D5 的 `error` + `done` 事件必须显式地由
    `StreamInterrupted` 触发，而不是由「LLMError 的一个子类」触发。

    携带的三件套由 brief 冻结：`partial_text`（已交付给用户的文本，只用于兜底文案与
    记账，不得再重复推送）、`attempts`、`selected_index`。`error` 是原始 `LLMError`，
    `error_type` 是它的 `kind`（矩阵 #11 的 payload 增量字段）。
    """

    def __init__(self, partial_text: str, attempts: tuple[Attempt, ...] | list[Attempt] = (),
                 selected_index: int = -1, *, error: LLMError | None = None,
                 reason_codes: tuple[str, ...] = (), model_id: str = "",
                 provider_name: str = "") -> None:
        self.partial_text = partial_text or ""
        self.attempts: tuple[Attempt, ...] = tuple(attempts)
        self.selected_index = selected_index
        self.error = error
        self.error_type: str | None = error.kind if error is not None else "unknown"
        self.status_code: int | None = error.status_code if error is not None else None
        self.reason_codes: tuple[str, ...] = tuple(reason_codes)
        self.model_id = model_id
        self.provider_name = provider_name
        # 消息里只有归类与长度事实：文本内容可能含用户问题，绝不进异常消息（D3）。
        super().__init__(
            f"流式生成在首个内容块之后中断：kind={self.error_type}"
            f" status={self.status_code} partial_chars={len(self.partial_text)}")


# --------------------------------------------------------------------------
# 逐 provider 熔断器：模块级注册表单例 dict（D4）
# --------------------------------------------------------------------------
#: provider 名 → `CircuitBreaker`。进程内单 worker 语义，与 typesafe 判定层同构。
BREAKERS: dict[str, CircuitBreaker] = {}


def circuit_breaker(provider_name: str) -> CircuitBreaker | None:
    """取（必要时创建）一个 provider 的熔断器。`llm_breaker_enabled=false` ⇒ **None = 旁路**。

    参数全部来自 §12 的 `llm_breaker_*`（`window` / `failure_ratio` /
    `open_seconds` / `half_open_probes`）。旁路时既不创建也不查询：一条都不该被闸掉的
    链路（legacy 应急、以及矩阵 #18 的双路等价）不能因为测试之间残留的 breaker 状态而抖。
    """
    if not settings.llm_breaker_enabled:
        return None
    breaker = BREAKERS.get(provider_name)
    if breaker is None:
        breaker = CircuitBreaker(
            name=provider_name,
            window=int(settings.llm_breaker_window),
            failure_ratio=float(settings.llm_breaker_failure_ratio),
            open_seconds=float(settings.llm_breaker_open_seconds),
            half_open_probes=int(settings.llm_breaker_half_open_probes),
        )
        BREAKERS[provider_name] = breaker
    return breaker


def circuit_is_open(provider_name: str) -> bool:
    """该 provider 现在是否被熔断。**只读已存在的实例**，不懒创建。

    读的是 `breaker.state`（`resilience.py` 文档化的「观测口」）而不是 `allow()`：
    `allow()` 会占用 HALF_OPEN 的探测名额，而这里只是给 §5 的 health 过滤步供一个键。
    「plan 阶段按 circuit_open 剔候选」与「attempt 前 `allow()` 预检」是**两道门**
    （T3 移交），后者才是外呼闸门。
    """
    breaker = BREAKERS.get(provider_name)
    if breaker is None or not settings.llm_breaker_enabled:
        return False
    return breaker.state == "open"


def reset_circuit_breakers() -> None:
    """清空熔断器单例。测试必须用（跨用例的状态泄漏会把下一个用例直接闸掉）。"""
    BREAKERS.clear()


def routing_health_view(registry: Registry | None = None, *, include_probes: bool = True,
                        base: Mapping[str, Any] | None = None) -> dict[str, dict[str, bool]]:
    """§5 health 步的输入视图：`{provider: {"healthy": bool, "circuit_open": bool}}`。

    T3 移交项在这里闭合：`provider_health_view()` 只产出 `{healthy}`（探针语义），
    路由还需要知道熔断态才能做「plan 门」。两个键**刻意独立**（D4：OPEN 不是不健康的一
    种，它不该冒领 `PRIMARY_UNHEALTHY`，也不该把 §8 status 的 degraded 面带偏）。

    `include_probes=False` ⇒ 不打网络（只并熔断键，`healthy` 默认 True）：测试与离线回放用。
    `base` 给定时以它为准并进去——于是调用方可以自带缓存过的探针视图。
    """
    registry = registry if registry is not None else get_registry()
    source: Mapping[str, Any] = {}
    if base is not None:
        source = base
    elif include_probes:
        source = health.provider_health_view(registry)
    view: dict[str, dict[str, bool]] = {}
    for name in _provider_names(registry, source):
        raw_entry = source.get(name)
        if isinstance(raw_entry, bool):              # 容错：视图写成 {provider: True}
            entry: dict[str, bool] = {"healthy": raw_entry}
        elif isinstance(raw_entry, Mapping):
            entry = dict(raw_entry)
        else:
            entry = {}
        entry.setdefault("healthy", True)
        entry["circuit_open"] = circuit_is_open(name)
        view[name] = entry
    return view


def _provider_names(registry: Registry, source: Mapping[str, Any]) -> tuple[str, ...]:
    """注册表里启用条目的 provider ∪ 视图里已有的 provider（声明序稳定）。"""
    names: dict[str, None] = {}
    for model in registry.models:
        if model.enabled:
            names.setdefault(model.provider, None)
    for name in source:
        names.setdefault(str(name), None)
    return tuple(names)


# --------------------------------------------------------------------------
# 上下文前置收口（Task 3 移交①）
# --------------------------------------------------------------------------
def estimate_prompt_tokens(messages: Any) -> float:
    """冻结口径：`sum(len(str(m)) for m in messages) / 2`（Task 3 报告移交①逐字）。

    对**整条消息字典**取长度（不是只取 content）：role/name/tool_calls 也要占上下文。
    返回 float——`/2` 是粗估而不是计数，取整只会让边界用例看起来像精确账。
    """
    items = list(messages or [])
    return sum(len(str(item)) for item in items) / float(CONTEXT_CHARS_PER_TOKEN)


def fit_chain_to_context(plan: RoutePlan, req: LLMRequest) -> tuple[tuple[RouteCandidate, ...], int]:
    """按计划顺序把「装不下本次请求」的候选剔掉，返回 `(留下的候选, 被剔条数)`。

    判据：`estimated > model.limits.context_tokens` ⇒ 剔（等于上限算装得下，边界由测试钉）。
    **不重排、不改打分**：这一步只是收口，排序仍是 §5 的裁决。被剔条数交给 trace
    （移交④），不新增理由码。
    """
    estimated = estimate_prompt_tokens(req.messages)
    kept = tuple(candidate for candidate in _plan_chain(plan)
                 if estimated <= candidate.model.limits.context_tokens)
    return kept, len(_plan_chain(plan)) - len(kept)


def _plan_chain(plan: RoutePlan) -> tuple[RouteCandidate, ...]:
    return (plan.primary,) + tuple(plan.fallbacks)


# --------------------------------------------------------------------------
# 执行器共享状态（run_complete 与 StreamSession 用同一套闸门/记账，语义必须一致）
# --------------------------------------------------------------------------
class _Runner:
    """一条候选链的执行状态机：预检三段（config 跳过 / 预算收缩 / 熔断 allow）+ 记账。

    刻意不含「怎么调用 provider」的知识：非流式与流式的差别只在怎么消费回执，
    而预算、熔断、理由码、attempts 这四本账必须一模一样，否则 §10 #3–#8 的矩阵要在
    两条路上各测一遍。
    """

    def __init__(self, *, chain: tuple[RouteCandidate, ...], req: LLMRequest,
                 profile: RequestProfile | None, plan: RoutePlan | None,
                 plan_codes: tuple[str, ...],
                 context_dropped: int, budget_ms: float,
                 trace_id: str | None, request_id: str | None) -> None:
        self.chain = chain
        self.req = req
        self.profile = profile
        #: 本次执行所依据的**整份计划**（含被上下文收口剔掉的条目）。
        #: 执行面把它原样带出去（`FallbackResult.plan` / `StreamSummary.plan` /
        #: `AllCandidatesFailedError.plan`），T7/T8 才能拿
        #: `attach_model_route(trace, result.plan, result, profile=profile)` 解释「计划 vs 实跑」。
        self.plan = plan
        self.context_dropped = context_dropped
        self.budget_ms = float(budget_ms)
        self.trace_id = trace_id
        self.request_id = request_id
        self.budget = TimeoutBudget(soft_ms=self.budget_ms * 0.7, hard_ms=self.budget_ms,
                                    clock=_now)
        self.attempts: list[Attempt] = []
        self.codes: list[str] = list(plan_codes)
        self.config_failed: set[str] = set()
        self.last_error: LLMError | None = None
        self.budget_exhausted = False

    # --- 预算 -------------------------------------------------------------
    def timeout_or_none(self) -> float | None:
        """本次外呼可用的秒数：`min(llm_model_timeout_seconds, remaining/1000)`。

        `None` ⇒ 预算已耗尽（`remaining <= 0`），调用方必须**停止外呼**（§6 总预算制）。
        """
        remaining_ms = self.budget.remaining_ms()
        if remaining_ms <= 0.0:
            return None
        return min(float(settings.llm_model_timeout_seconds), remaining_ms / 1000.0)

    def note_budget_exhausted(self) -> None:
        self.budget_exhausted = True
        self.add_code(FALLBACK_AFTER_TIMEOUT)

    # --- 理由码与 attempts ------------------------------------------------
    def add_code(self, code: str) -> None:
        if code not in self.codes:
            self.codes.append(code)

    def reason_codes(self) -> tuple[str, ...]:
        return tuple(self.codes)

    def note_success(self, model: ModelDefinition, latency_ms: float) -> Attempt:
        attempt = Attempt(model.id, model.provider, "success", None, round(latency_ms, 3))
        self.attempts.append(attempt)
        return attempt

    def note_failure(self, model: ModelDefinition, error: LLMError, latency_ms: float) -> Attempt:
        attempt = Attempt(model.id, model.provider, "failed", error.kind, round(latency_ms, 3))
        self.attempts.append(attempt)
        self.last_error = error
        return attempt

    def note_cause_codes(self, error: LLMError) -> None:
        """把「为什么换了下个候选」翻译成执行期理由码（不造新码）。"""
        if _looks_like_timeout(error):
            self.add_code(FALLBACK_AFTER_TIMEOUT)

    def mark_provider_config_failed(self, provider_name: str) -> None:
        self.config_failed.add(provider_name)
        self.add_code(PROVIDER_CONFIG_FAILED)

    # --- 熔断器回执（§6「每真实调用回执」+ D4）----------------------------
    def answer_ok(self, breaker: CircuitBreaker | None) -> None:
        if breaker is not None:
            breaker.record(True)

    def answer_error(self, breaker: CircuitBreaker | None, error: LLMError) -> None:
        if breaker is not None:
            breaker.record(_breaker_receipt_is_ok(error))

    def allow_retry(self, breaker: CircuitBreaker | None) -> bool:
        """重试当前模型前再过一次闸。

        必要性的来源：`CircuitBreaker` 的 `allow()` 在 HALF_OPEN 会**占名额**，
        而一次候选级外呼可能对应多次真实调用（重试）。若不重新预检，迟到的多条回执会
        记错账（`resilience.py` 文档化的无世代令牌限制）；重新预检同时让「熔断在重试前
        打开」这条路径变成不外呼，也就没有需要丢弃的回执。
        """
        return breaker is None or breaker.allow()

    # --- 三段预检 ---------------------------------------------------------
    def gate(self, index: int) -> tuple[_GateState, ModelDefinition | None,
                                        CircuitBreaker | None, float]:
        """第 `index` 个候选外呼前的统一裁决。返回 `(状态, 模型, 熔断器, timeout 秒)`。

        顺序冻结：**config 跳过 → 预算 → 熔断 allow()**。
        - config 在前：同 provider 已凭据失败就不该再消耗一次预算，也不该占熔断名额。
        - 预算在 allow() 之前：`allow()` 一旦放行就欠一条回执，预算耗尽时根本不该借名额。
        - 熔断在最后：它是外呼闸门（`resilience.py`：`allow()` 是唯一依据）。
        """
        model = self.chain[index].model
        if model.provider in self.config_failed:
            return _SKIP, None, None, 0.0
        timeout = self.timeout_or_none()
        if timeout is None:
            self.note_budget_exhausted()
            return _STOP, None, None, 0.0
        breaker = circuit_breaker(model.provider)
        if breaker is not None and not breaker.allow():
            self.attempts.append(Attempt(model.id, model.provider, "skipped_circuit",
                                         None, 0.0))
            self.add_code(CIRCUIT_OPEN)
            return _SKIP, None, None, 0.0
        return _GO, model, breaker, timeout

    def retries_left(self) -> int:
        return max(0, int(settings.llm_retry_per_model))

    def all_failed(self) -> AllCandidatesFailedError:
        return AllCandidatesFailedError(
            self.attempts, reason_codes=self.reason_codes(),
            budget_exhausted=self.budget_exhausted, last_error=self.last_error,
            profile=self.profile, chain_size=len(self.chain),
            plan=self.plan, context_dropped=self.context_dropped)


def _breaker_receipt_is_ok(error: LLMError) -> bool:
    """失败外呼对熔断器的**回执值**（模块 docstring 第 5 条）。

    `hard` 的分支论据落在 HALF_OPEN 的判活规则上：`CircuitBreaker` 在该状态下**只有
    `record(True)` 算探测通过**，任一 `record(False)` 立即 `_trip()` 回 OPEN。带状态码的
    `hard`（400/404/422）= 对方活着并回了话、坏的是我们的请求：记 False 就是让一条
    **永久坏**的请求在每个探测窗口把 healthy 的 provider 重新闸 `open_seconds` 秒，
    OPEN → HALF_OPEN → OPEN 循环锁死；记 True 才把它留在服务面上。
    不带状态码的 `hard` 是「这次外呼没能发生」（未登记 provider、凭据解析失败、
    未预期异常），与 config 同列记 False。
    """
    if error.kind in ("retryable", "model_unavailable", "config"):
        return False
    return error.status_code is not None


def _looks_like_timeout(error: LLMError) -> bool:
    """是否把「换候选」归因为 `FALLBACK_AFTER_TIMEOUT`（矩阵 #5 的期望）。

    `errors.from_exception` 把 httpx 的超时族翻译成 `kind="retryable"` 且
    `status_code=None`、消息以「超时：」开头（见 `errors._TIMEOUT_CLASS_NAMES` 那条注释）。
    连接失败同样没有状态码，但它的消息前缀是「连接失败」——所以这里按**归类事实**判，
    而不是「没有状态码就是超时」。408 是服务端自己宣告的请求超时，同样算这一类。
    """
    if error.kind != "retryable":
        return False
    if error.status_code == 408:
        return True
    if error.status_code is not None:
        return False
    text = str(error)
    return text.startswith("超时") or "Timeout" in text or "timeout" in text


def _all_failed_message(attempts: tuple[Attempt, ...], budget_exhausted: bool,
                        chain_size: int) -> str:
    kinds = "+".join(sorted({a.error_type or a.result for a in attempts})) or "none"
    skipped = sum(1 for a in attempts if a.result == "skipped_circuit")
    failed = sum(1 for a in attempts if a.result == "failed")
    return (f"全部候选均失败：候选链 {chain_size} 条，"
            f"外呼失败 {failed} 次，熔断跳过 {skipped} 次，归类 {kinds}"
            + ("，预算耗尽" if budget_exhausted else ""))


def _dominant_provider(attempts: tuple[Attempt, ...], last_error: LLMError | None) -> str:
    provider_name = getattr(last_error, "provider", "") or ""
    if provider_name:
        return provider_name
    for attempt in reversed(attempts):
        if attempt.result == "failed":
            return attempt.provider
    return ""


# --------------------------------------------------------------------------
# 入口的公共零件：RoutePlan | RequestProfile → 执行状态
# --------------------------------------------------------------------------
def _plan_and_profile(chain_source: RoutePlan | RequestProfile, *,
                      registry: Registry | None = None,
                      health_view: Any = None
                      ) -> tuple[RoutePlan, RequestProfile | None]:
    """`run_*` 的第一个位置参可以是 `RoutePlan`（候选链的冻结出处）或 `RequestProfile`。

    brief 把 `run_complete` 的首参写成 `profile`，而候选链 = `RoutePlan.primary+fallbacks`：
    两种给法都支持，语义不同——
    - 传 `RoutePlan`：执行器**只做执行**，计划由调用方（`llm.complete()`）负责，可复现、
      可在 trace 里对照（生产路径就是这一支）。
    - 传 `RequestProfile`：便利入口，执行器自己 `plan()`（默认取进程注册表 +
      `routing_health_view()`，会打探针）。画像本身留给异常与 trace 用。

    `registry` / `health_view` 只服务第二支（测试与离线回放传 stub 就不打网络）。
    既不是这两者 ⇒ `TypeError`（宁可炸在入口，也不要在链路上「没有候选」）。
    """
    if isinstance(chain_source, RoutePlan):
        return chain_source, None
    if isinstance(chain_source, RequestProfile):
        resolved_registry = registry if registry is not None else get_registry()
        view = (routing_health_view(resolved_registry) if health_view is None
                else health_view)
        return router.plan(chain_source, resolved_registry, view), chain_source
    raise TypeError(
        "run_complete/run_stream 的首参必须是 RoutePlan（候选链）或 RequestProfile"
        f"（由执行器自行 plan），收到 {type(chain_source).__name__}")


def _prepare(chain_source: RoutePlan | RequestProfile, req: LLMRequest, *,
             trace_id: str | None, request_id: str | None) -> _Runner:
    """计划 → **上下文收口** → 执行状态。收口后为空即 D2 的零候选出口。"""
    plan, profile = _plan_and_profile(chain_source)
    chain, dropped = fit_chain_to_context(plan, req)
    if not chain:
        original = len(_plan_chain(plan))
        raise NoCapableModelError(
            f"Router 无可用候选：stage=context 计划内 {original} 个候选的上下文上限"
            f"都装不下本次请求（粗估 {int(estimate_prompt_tokens(req.messages))} tokens，"
            f"折算口径 {CONTEXT_CHARS_PER_TOKEN} 字符/token，被剔 {dropped} 条）",
            profile=profile, stage="context")
    return _Runner(chain=chain, req=req, profile=profile, plan=plan,
                   plan_codes=plan.reason_codes, context_dropped=dropped,
                   budget_ms=float(settings.llm_total_budget_ms),
                   trace_id=trace_id, request_id=request_id)


# --------------------------------------------------------------------------
# 非流式执行
# --------------------------------------------------------------------------
def run_complete(chain_source: RoutePlan | RequestProfile, req: LLMRequest, *,
                 trace_id: str | None = None,
                 request_id: str | None = None) -> FallbackResult:
    """按候选链跑一次非流式生成（§7）。

    返回 `FallbackResult`；抛错只有三种口径：
    - `NoCapableModelError`：上下文收口后零候选（未发出任何请求，D2 降级）；
    - `LLMError`：`hard + no_fallback`（NO_FALLBACK 硬终态，原样上抛**对象本身**）；
    - `AllCandidatesFailedError`：链走完仍无成功（`attempts` 附带，`budget_exhausted` 有旗）。

    `trace_id` / `request_id` 不参与裁决，只用于日志归因（§8 的记账在 T5 的调用点做）。
    """
    runner = _prepare(chain_source, req, trace_id=trace_id, request_id=request_id)
    retries_per_model = runner.retries_left()

    for index in range(len(runner.chain)):
        state, model, breaker, timeout = runner.gate(index)
        if state == _STOP:
            break
        if state != _GO or model is None:
            continue
        retries_left = retries_per_model
        while True:
            started = _now()
            try:
                response = provider.complete(model, runner.req, timeout)
            except Exception as exc:                  # noqa: BLE001 - provider 只抛 LLMError
                error = exc if isinstance(exc, LLMError) else errors.from_exception(exc)
                runner.note_failure(model, error, (_now() - started) * 1000.0)
                runner.answer_error(breaker, error)
                if error.no_fallback:
                    # §6 硬终态：请求本身不合法，换模型没有意义 —— 原对象上抛。
                    raise error
                if error.retryable and retries_left > 0 and runner.allow_retry(breaker):
                    retries_left -= 1
                    retry_timeout = runner.timeout_or_none()
                    if retry_timeout is not None:
                        timeout = retry_timeout
                        continue
                    runner.note_budget_exhausted()
                runner.note_cause_codes(error)
                if error.kind == "config":
                    runner.mark_provider_config_failed(model.provider)
                break
            latency_ms = (_now() - started) * 1000.0
            runner.note_success(model, latency_ms)
            runner.answer_ok(breaker)
            return FallbackResult(
                response=response, attempts=tuple(runner.attempts), selected_index=index,
                reason_codes=runner.reason_codes(), budget_ms=runner.budget_ms,
                context_dropped=runner.context_dropped, plan=runner.plan)

    error = runner.all_failed()
    logger.warning("LLM 候选链全部失败（非流式）：trace_id=%s request_id=%s %s",
                   trace_id, request_id, error)
    raise error


# --------------------------------------------------------------------------
# 流式执行 + commit 边界
# --------------------------------------------------------------------------
def run_stream(chain_source: RoutePlan | RequestProfile, req: LLMRequest, *,
               trace_id: str | None = None, request_id: str | None = None) -> StreamSession:
    """开一个流式会话。本函数**不发请求**（§7 的 pre-commit 换模型靠这个惰性）。

    立刻可能抛的只有 `NoCapableModelError`（上下文收口后零候选）与 `TypeError`。
    候选链的失败要到 `session.chunks()` 才冒出来：pre-commit 全败 ⇒
    `AllCandidatesFailedError`；post-commit 中断 ⇒ `StreamInterrupted`。
    """
    runner = _prepare(chain_source, req, trace_id=trace_id, request_id=request_id)
    return StreamSession(runner)


class StreamSession:
    """一次流式生成的会话：`chunks()` 消费、`finish()` 汇总（§7 第四段冻结）。

    状态机（只有一个提交点，别的都不算承诺）::

        未开始 → pre-commit（可换候选，用户什么都没看到）
              → committed（第一个内容 chunk 已交付，**永不换模型**）
              → 收尾 / StreamInterrupted

    扣住不吐空文本 chunk 是这套语义的支点：如果在提交前就把 `finish`/`usage` 块交给
    消费方，SSE 层就会先于「内容」给用户看到东西，那时换模型等于说过的话改口。
    """

    def __init__(self, runner: _Runner) -> None:
        self._runner = runner
        self.committed = False
        self.selected_index = -1
        self._started = False
        self._finished = False
        self._parts: list[str] = []
        self._ttft_ms: float | None = None
        self._usage: dict[str, Any] | None = None
        self._pending_usage: dict[str, Any] | None = None
        self._in_yield = False
        self._session_started = 0.0

    # --- 只读观测面（T7 的 payload 增量与 T5 的记账都从这里取）------------
    @property
    def attempts(self) -> tuple[Attempt, ...]:
        return tuple(self._runner.attempts)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return self._runner.reason_codes()

    @property
    def budget_ms(self) -> float:
        return self._runner.budget_ms

    @property
    def context_dropped(self) -> int:
        return self._runner.context_dropped

    @property
    def partial_text(self) -> str:
        return "".join(self._parts)

    @property
    def selected_candidate(self) -> RouteCandidate | None:
        if self.selected_index < 0:
            return None
        return self._runner.chain[self.selected_index]

    # --- 消费 -------------------------------------------------------------
    def chunks(self) -> Iterator[LLMChunk]:
        """驱动候选链并产出 chunk 流。一个会话只能消费一次。"""
        if self._started:
            raise RuntimeError("StreamSession.chunks() 只能消费一次：重开请求归执行器负责")
        self._started = True
        return self._pump()

    def _pump(self) -> Iterator[LLMChunk]:
        runner = self._runner
        req = runner.req
        retries_per_model = runner.retries_left()
        self._session_started = _now()

        for index in range(len(runner.chain)):
            state, model, breaker, timeout = runner.gate(index)
            if state == _STOP:
                break
            if state != _GO or model is None:
                continue
            retries_left = retries_per_model
            while True:
                started = _now()
                self._pending_usage = None
                try:
                    iterator = provider.stream(model, req, timeout)
                    for chunk in iterator:
                        if isinstance(chunk.usage, dict) and chunk.usage:
                            self._pending_usage = chunk.usage
                        if not chunk.text:
                            # 未提交 ⇒ 扣住（空文本不是「内容」）；已提交 ⇒ 照原序透传。
                            if self.committed:
                                yield from self._emit(chunk)
                            continue
                        self._commit(index, model)
                        self._parts.append(chunk.text)
                        yield from self._emit(chunk)
                except GeneratorExit:
                    # 消费方提前离开（客户端断开）：没有回执可给，原样退出。
                    raise
                except Exception as exc:              # noqa: BLE001 - provider 只抛 LLMError
                    if self._in_yield:
                        # 异常来自**消费方**（在我们让出控制权时抛入）：它不是 provider 的
                        # 失败事实，既不能记熔断回执，也不能触发换模型或 StreamInterrupted。
                        raise
                    error = exc if isinstance(exc, LLMError) else errors.from_exception(exc)
                    latency_ms = (_now() - started) * 1000.0
                    runner.note_failure(model, error, latency_ms)
                    runner.answer_error(breaker, error)
                    if self.committed:
                        # §7 冻结：commit 之后禁止换模型。这里必须是**唯一**的出口。
                        raise self._interrupted(error) from exc
                    if error.no_fallback:
                        raise
                    if error.retryable and retries_left > 0 and runner.allow_retry(breaker):
                        retries_left -= 1
                        retry_timeout = runner.timeout_or_none()
                        if retry_timeout is not None:
                            timeout = retry_timeout
                            continue
                        runner.note_budget_exhausted()
                    runner.note_cause_codes(error)
                    if error.kind == "config":
                        runner.mark_provider_config_failed(model.provider)
                    break
                # 流干净地走完了（哪怕一个内容块都没有）：这是**成功**，不是失败。
                runner.note_success(model, (_now() - started) * 1000.0)
                runner.answer_ok(breaker)
                self._usage = _normalized_usage(self._pending_usage)
                if self.selected_index < 0:
                    # 全程没有内容块：仍然记为「选中了它」（流干净走完了），但**不提交**
                    # —— committed 的事实只能是「用户看到了内容」（D5 的 payload 增量）。
                    self.selected_index = index
                self._finished = True
                return

        error = runner.all_failed()
        logger.warning("LLM 候选链全部失败（流式 pre-commit）：trace_id=%s request_id=%s %s",
                       runner.trace_id, runner.request_id, error)
        raise error

    def _emit(self, chunk: LLMChunk) -> Iterator[LLMChunk]:
        """唯一的让出点：标记「此刻若冒出来的异常来自消费方」，交给 `_pump` 分辨。"""
        self._in_yield = True
        try:
            yield chunk
        finally:
            self._in_yield = False

    def _commit(self, index: int, model: ModelDefinition) -> None:
        if self.committed:
            return
        self.committed = True
        self.selected_index = index
        self._ttft_ms = round((_now() - self._session_started) * 1000.0, 3)

    def _interrupted(self, error: LLMError) -> StreamInterrupted:
        candidate = self.selected_candidate
        return StreamInterrupted(
            self.partial_text, self.attempts, self.selected_index, error=error,
            reason_codes=self.reason_codes,
            model_id=candidate.model.id if candidate is not None else "",
            provider_name=candidate.model.provider if candidate is not None else "")

    # --- 汇总 -------------------------------------------------------------
    def finish(self) -> StreamSummary:
        """汇总本次会话（§8 记账面）。**任何时候都可调用**——包括 `chunks()` 已经抛错、
        或消费方中途离开之后；只有「从没消费过」是误用（那意味着链上什么都没发生，
        拿到的账会被误读成「一次空生成」）。
        """
        if not self._started:
            raise RuntimeError("StreamSession.finish() 之前必须先消费 chunks()")
        candidate = self.selected_candidate
        text: str | None
        if self._parts or self.committed or self._finished:
            text = "".join(self._parts)
        else:
            text = None
        # `error_type` 只在「没有成功收尾」时取最后一个真实失败的归类：成功链上早期
        # 的失败 attempt 已经由 `attempts` 与理由码描述，不该再冒领一次会话级错误。
        error_type = None if self._finished else (
            self._runner.last_error.kind if self._runner.last_error is not None else None)
        return StreamSummary(
            response_text=text,
            usage=self._usage if self._usage is not None else _normalized_usage(None),
            ttft_ms=self._ttft_ms,
            attempts=self.attempts,
            selected_index=self.selected_index,
            reason_codes=self.reason_codes,
            committed=self.committed,
            completed=self._finished,
            error_type=error_type,
            model_id=candidate.model.id if candidate is not None else "",
            provider_name=candidate.model.provider if candidate is not None else "",
            budget_ms=self._runner.budget_ms,
            context_dropped=self._runner.context_dropped,
            plan=self._runner.plan)


def _normalized_usage(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """把 provider 的 usage 块折成 §8 记账口径；缺失记 0 并置 `estimated`（§6）。

    两侧键名不同（OpenAI `prompt_tokens/completion_tokens`、Ollama
    `prompt_eval_count/eval_count`），但 `normalize` 层的 `LLMChunk.usage` 已经是
    `_usage()` 的输出形状（`input_tokens/output_tokens/total_tokens/estimated`）。
    这里只兜住「有人塞了原始形状」的情况，保持幂等而不是再猜一次协议。
    """
    body = dict(raw or {})
    input_tokens = _int_of(body, "input_tokens", "prompt_tokens", "prompt_eval_count")
    output_tokens = _int_of(body, "output_tokens", "completion_tokens", "eval_count")
    estimated = bool(body.get("estimated")) or "input_tokens" not in body
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": _int_of(body, "total_tokens") or (input_tokens + output_tokens),
        "estimated": estimated,
    }


def _int_of(body: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        raw = body.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int):
            continue
        if raw >= 0:
            return raw
    return 0
