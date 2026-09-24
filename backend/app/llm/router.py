"""规则路由（spec §5：纯函数，不执行请求）。

`plan(profile, registry, health_view) -> RoutePlan` 是三条链唯一的候选裁决点。它只做
内存计算：**不发请求、不读配置、不碰凭据、不改输入**，所以同一个 (画像, 注册表, 健康视图)
永远得到同一份计划，可以在 trace 里复现、在测试里穷举。

过滤顺序（§5 冻结，逐步实现见 `plan` 体内的编号注释；**不得交换**）::

    enabled → 必需 capability → external policy → health/熔断 → limits
            → priority → cost

冻结语义的三条硬线：

1. **capability > preference**：priority=100 也救不回能力不符的条目（步骤 2 先于打分）。
   反过来，被 capability 剔掉的条目**进不了** health 步，所以它所在 provider 的不健康不会
   污染 `reason_codes`（顺序错了就会，测试从两侧钉）。
2. **external policy 在 V2.3 只透传**：不拦截、不加分，`external` 只决定入选条目挂
   `LOCAL_PREFERRED`（`external=false` 时）。隐私路由是 V2.5 的范围，这里刻意不留半成品开关。
3. **零候选 = 抛 `NoCapableModelError`**（D2）。健康全灭也抛，不降级成「忽略 health 硬选
   一个」：那会让一条注定超时的链路吃掉整个 30s 预算，而调用方（Agent fast-path /
   RAG 既有兜底文案）本来就有更便宜的降级。`NO_CAPABLE_MODEL` 只随异常出现，不进成功计划。

limits 这一步的现实边界（→ Task 4 的接口缺口）
---------------------------------------------
§5 写的「limits（context 估算）」要拿**请求体**去比 `context_tokens`，而 `plan()` 的冻结
入参只有画像（画像里没有消息体，也不该有：路由输入必须是可复现的值对象）。因此本步只做
**形式校验**（上限必须为正数，防 `model_construct` 之类的越界构造进候选池），真正的
「这次请求的上下文粗估长度是否装得下」由 **Task 4 在 execute 前置**按
`sum(len(str(m)) for m in ...) / 2 > context_tokens` 裁决（粗估口径见 Task 4 报告）。
"""
from __future__ import annotations

from typing import Literal, Mapping

from app.llm.models import ModelDefinition, RequestProfile, RouteCandidate, RoutePlan
from app.llm.registry import Registry

__all__ = [
    "CAPABILITY_BY_MODE",
    "PRIORITY_KEY_BY_MODE",
    "REASON_CODES",
    "NoCapableModelError",
    "plan",
]

# --------------------------------------------------------------------------
# §5 冻结的 reason code 枚举（机器码，入 usage.route_reason 与 trace，不做文案）
# --------------------------------------------------------------------------
CAPABILITY_MATCH = "CAPABILITY_MATCH"
HIGHER_PRIORITY = "HIGHER_PRIORITY"
LOWER_COST = "LOWER_COST"
LOCAL_PREFERRED = "LOCAL_PREFERRED"
PRIMARY_UNHEALTHY = "PRIMARY_UNHEALTHY"
CIRCUIT_OPEN = "CIRCUIT_OPEN"
FALLBACK_AFTER_TIMEOUT = "FALLBACK_AFTER_TIMEOUT"
PROVIDER_CONFIG_FAILED = "PROVIDER_CONFIG_FAILED"
NO_CAPABLE_MODEL = "NO_CAPABLE_MODEL"

# 冻结枚举逐字（plan 的 Global Constraints）。后三个**不由 plan 产生**：
# `FALLBACK_AFTER_TIMEOUT` / `PROVIDER_CONFIG_FAILED` 属于 Task 4 的执行期事实，
# `NO_CAPABLE_MODEL` 只随异常。列在这里是为了让「谁都能拼错一个码」在测试期就响。
REASON_CODES: tuple[str, ...] = (
    LOCAL_PREFERRED, CAPABILITY_MATCH, HIGHER_PRIORITY, LOWER_COST, PRIMARY_UNHEALTHY,
    CIRCUIT_OPEN, FALLBACK_AFTER_TIMEOUT, PROVIDER_CONFIG_FAILED, NO_CAPABLE_MODEL,
)

# mode → 必需 capability 位。mode=agent 复用 `tools` 档（§3：priority 也只有三档）。
CAPABILITY_BY_MODE: dict[str, str] = {"chat": "chat", "rag": "rag", "agent": "tools"}
# mode → priority 取档键。与上一行的区别只在未来可能出现「打分维度 ≠ 能力维度」。
PRIORITY_KEY_BY_MODE: dict[str, str] = {"chat": "chat", "rag": "rag", "agent": "tools"}

# `stage`：清空候选池的那一步。前五个由 `plan()` 产生；`"context"` 是 **Task 4 的接缝**：
# 上下文粗估在 execute 前置做（见模块 docstring 的接口缺口段），收口后仍为空时由 Task 4
# 自己抛带该 stage 的异常。写进 Literal 是为了让「stage 拼错」和 reason code 一样能被静态查到。
_Stage = Literal["enabled", "capability", "health", "limits", "priority", "context"]


class NoCapableModelError(Exception):
    """零候选（D2）：Router 在**发任何请求之前**就判定没有可用模型。

    刻意不是 `LLMError` 的子类：Task 4 的 `except LLMError` 处理的是「一次 provider 往返
    的失败归类」（可重试 / 换候选 / 硬终态），而这里根本没有发生过往返，语义是「本链路的
    降级路径」。混成一族的后果是「零候选」被当成可重试错误，白烧预算。

    携带的可读信息是**画像摘要 + 清空候选池的那一步 + 理由码**，不含请求内容（D3）：
    `mode/complexity/需求旗标`四个字段足以定位是哪条链、哪一类请求掉到了 fast-path。

    入参约束：`reason_codes` 必须 ⊆ `REASON_CODES`（越界即 `ValueError`），`NO_CAPABLE_MODEL`
    由本类补上——调用方既不需要、也没资格漏掉它。

    调用方义务（D2 冻结）：Agent 捕获后走 `agent_local_fast_path`；RAG/SSE 走各自的既有
    兜底文案。**任何链都不得把它变成给用户看的 500/503 裸错。**
    """

    def __init__(self, message: str = "", *, profile: RequestProfile | None = None,
                 stage: _Stage = "capability",
                 reason_codes: tuple[str, ...] = ()) -> None:
        codes = tuple(reason_codes)
        # reason code 是**机器码**，下游 Task 4/5 按词写进 `usage.route_reason` 与 trace，
        # 所以越界词必须在构造时就响，而不是等到落库/前端读出一个谁都认不出的码。
        # `set(codes) <= set(REASON_CODES)` 是 `plan()` 侧不变量的入口版：plan 只会传
        # `PRIMARY_UNHEALTHY`/`CIRCUIT_OPEN`（`_filter_by_health` 内部常量），而 Task 4 手工
        # 传码时拼错（`"CIRCUIT_OPENN"`）必须在这里被拦住。用 ValueError 而不是 assert：
        # `python -O` 会删掉 assert，那时这里就成了一条静默的越界通道。
        unknown = sorted({code for code in codes if code not in REASON_CODES})
        if unknown:
            raise ValueError(
                f"NoCapableModelError 收到冻结枚举 REASON_CODES 之外的理由码：{unknown}")
        if NO_CAPABLE_MODEL not in codes:
            codes = codes + (NO_CAPABLE_MODEL,)      # 该码只随异常，且必随异常
        self.profile = profile
        self.stage = stage
        self.reason_codes = codes
        self.profile_summary = _profile_summary(profile)
        if not message:
            message = (
                f"Router 无可用候选：stage={stage} "
                f"reasons={'+'.join(codes)} profile[{self.profile_summary}]")
        super().__init__(message)


def plan(profile: RequestProfile, registry: Registry,
         health_view: Mapping[str, dict] | None) -> RoutePlan:
    """按 §5 冻结顺序过滤 + 打分，返回 `RoutePlan(primary, fallbacks[], reason_codes[])`。

    `health_view` 是 `{provider: {"healthy": bool, "circuit_open": bool}}`（生产上由
    `health.provider_health_view(registry)` 供给，粒度是 provider 而不是模型 —— D4）。
    视图里**没有**的 provider 按健康处理（`{"healthy": True}` 语义）：视图没覆盖不等于坏了，
    把它当坏会让任何新接入的 provider 在扩表那天静默饿死。传 `None` / 空视图 ⇒ 全部健康。

    上下文（context）粗估不在这里做：见模块 docstring 的「limits 这一步的现实边界」，
    该职责随 `LLMRequest` 一起移交给 Task 4 的 execute 前置。
    """
    # --- 1. enabled ---------------------------------------------------------
    # `registry.models[*].enabled` 已是「JSON 意图 ∧ D1 凭据事实」的生效值（Task 1 解析层
    # 折叠过），所以这里不再判第二遍 key。
    pool = tuple(model for model in registry.models if model.enabled)
    if not pool:
        raise NoCapableModelError(profile=profile, stage="enabled")

    # --- 2. 必需 capability（capability > preference）-----------------------
    passed = tuple(model for model in pool if _capabilities_match(model, profile))
    if not passed:
        raise NoCapableModelError(profile=profile, stage="capability")

    # --- 3. external policy：V2.3 仅透传 ------------------------------------
    # 不拦截、不改顺序、不产理由码；`external` 旗标只在下一步的理由里露面。

    # --- 4. health / 熔断态 --------------------------------------------------
    passed, health_codes = _filter_by_health(passed, health_view)
    if not passed:
        raise NoCapableModelError(profile=profile, stage="health",
                                  reason_codes=health_codes)

    # --- 5. limits（形式校验；上下文粗估在 Task 4 的 execute 前置）-----------
    passed = tuple(model for model in passed if _limits_usable(model))
    if not passed:
        raise NoCapableModelError(profile=profile, stage="limits")

    # --- 6. priority（缺失键=0 分 ⇒ 剔除，与 capability 双保险）--------------
    scored = [(model, _score(model, profile.mode)) for model in passed]
    scored = [(model, score) for model, score in scored if score > 0]
    if not scored:
        raise NoCapableModelError(profile=profile, stage="priority")

    # --- 7. 排序：priority 降序 → 同分 cost（输入+输出单价和）升序 → 声明序 ----
    order = sorted(range(len(scored)),
                   key=lambda index: (-scored[index][1], _unit_cost(scored[index][0]),
                                      index))
    ranked = [scored[index] for index in order]
    candidates = tuple(_candidate(model, score, ranked) for model, score in ranked)
    return RoutePlan(primary=candidates[0], fallbacks=candidates[1:],
                     reason_codes=_merge_codes(
                         *(item.reason_codes for item in candidates), health_codes))


# --------------------------------------------------------------------------
# 各过滤步
# --------------------------------------------------------------------------
def _capabilities_match(model: ModelDefinition, profile: RequestProfile) -> bool:
    """画像要求的每一项能力都必须为真。

    `chat` 是**恒需**项（任何一条链最后都要一次对话式补全）；mode 决定第二项
    （agent⇒tools）；三个需求旗标按需追加。画像 mode 不在映射表里时按「能力不符」处理
    而不是抛 KeyError：Router 的失败面必须收敛成 `NoCapableModelError` 一种，
    正常 mode 校验是 classifier 的职责（`MODES` 那里已经拦过一次）。
    """
    caps = model.capabilities
    if not caps.chat:
        return False
    mode_capability = CAPABILITY_BY_MODE.get(profile.mode)
    if mode_capability is None or not getattr(caps, mode_capability):
        return False
    if profile.needs_tools and not caps.tools:
        return False
    if profile.needs_stream and not caps.stream:
        return False
    if profile.needs_reasoning and not caps.reasoning:
        return False
    return True


def _filter_by_health(models: tuple[ModelDefinition, ...],
                      health_view: Mapping[str, dict] | None
                      ) -> tuple[tuple[ModelDefinition, ...], tuple[str, ...]]:
    """按 provider 出清不健康 / 熔断中的候选，并回收本步的理由码。

    「不健康」的定义是 `healthy` 为假 **或** `circuit_open` 为真；两个信号独立记账
    （D4：熔断打开不是「不健康」的一种，它不该冒领 `PRIMARY_UNHEALTHY`）。码按首次出现
    顺序去重，且只描述**本步真的剔掉过东西**——一个从没在注册表里出现的 provider 坏了，
    不该出现在任何计划里。
    """
    kept: list[ModelDefinition] = []
    codes: list[str] = []
    for model in models:
        entry = _health_entry(health_view, model.provider)
        healthy = bool(entry.get("healthy", True))
        circuit_open = bool(entry.get("circuit_open", False))
        if healthy and not circuit_open:
            kept.append(model)
            continue
        if not healthy and PRIMARY_UNHEALTHY not in codes:
            codes.append(PRIMARY_UNHEALTHY)
        if circuit_open and CIRCUIT_OPEN not in codes:
            codes.append(CIRCUIT_OPEN)
    return tuple(kept), tuple(codes)


def _health_entry(health_view: Mapping[str, dict] | None, provider: str) -> dict:
    """取一个 provider 的健康条目；缺省即健康（见 `plan` docstring 的默认值语义）。"""
    if not health_view:
        return {"healthy": True}
    entry = health_view.get(provider, {"healthy": True})
    if isinstance(entry, bool):        # 容错：视图写成 {provider: True} 也能读
        return {"healthy": entry}
    return entry or {"healthy": True}


def _limits_usable(model: ModelDefinition) -> bool:
    """上限必须是正数。

    这不是重复 pydantic 的 `ge=1`：`model_construct` 之类的越界构造（以及未来从别的
    来源装配的条目）也会走到这里，而 `context_tokens=0` 的条目进了 provider 只会
    立刻失败一次。上下文的**实际**比较（本次请求粗估长度 vs 该上限）在 Task 4。
    """
    limits = model.limits
    return limits.context_tokens > 0 and limits.max_output_tokens > 0


def _score(model: ModelDefinition, mode: str) -> int:
    """取 `priority[mode 档]`，缺失键按 0 分处理（0 分在 `plan` 里被剔除）。

    0 分剔除是刻意的第二道闸：出厂注册表 ornith/phi3 的 `tools` 档就是 0，于是
    agent 模式即使有人误把 `capabilities.tools` 写成 true 也不会被选中（§5 的
    「capability 与 preference 双保险」）。
    """
    key = PRIORITY_KEY_BY_MODE.get(mode)
    if key is None:
        return 0
    raw = model.priority.get(key, 0)
    return raw if isinstance(raw, int) else 0


def _unit_cost(model: ModelDefinition) -> float:
    """同分时的比较量：输入 + 输出单价之和（每 100 万 token，§3 pricing）。

    不按「预期用量」加权：`plan()` 手里没有请求体，也没有 usage，任何权重都是在替
    调用方猜长度。等权重的好处是可解释（trace 里能直接读出「为什么是它」）。
    """
    pricing = model.pricing
    return float(pricing.input_per_1m) + float(pricing.output_per_1m)


def _candidate(model: ModelDefinition, score: int,
               ranked: list[tuple[ModelDefinition, int]]) -> RouteCandidate:
    """给一个入选者贴理由码（描述性，不参与排序）。

    - `CAPABILITY_MATCH`：它通过了 §5 第 2 步（每个入选者都有，读 trace 时能确认
      「这一档不是靠碰运气选中的」）。
    - `LOCAL_PREFERRED`：`external=false` 的条目入选时挂上，即「本地优先」是**事后**
      可解释的事实，不是加分项。
    - `HIGHER_PRIORITY`：计划里至少还有一个分数更低的候选 ⇒ 它靠分数压住了别人。
    - `LOWER_COST`：同分带里至少有一个候选更贵 ⇒ 它靠牌价赢下了那次 tie-break。
    """
    codes: list[str] = [CAPABILITY_MATCH]
    if not model.external:
        codes.append(LOCAL_PREFERRED)
    if any(other_score < score for _, other_score in ranked):
        codes.append(HIGHER_PRIORITY)
    cost = _unit_cost(model)
    if any(other_score == score and _unit_cost(other) > cost
           for other, other_score in ranked):
        codes.append(LOWER_COST)
    return RouteCandidate(model=model, score=score, reason_codes=tuple(codes))


def _merge_codes(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """合并整条计划的理由码：入选理由在前，剔除理由（health）在后，按首次出现去重。"""
    merged: list[str] = []
    for group in groups:
        for code in group:
            if code not in merged:
                merged.append(code)
    return tuple(merged)


def _profile_summary(profile: RequestProfile | None) -> str:
    """画像的五字段定长摘要（异常文本与 trace 注记共用；不含任何请求内容）。"""
    if profile is None:
        return "mode=unknown"
    return (f"mode={profile.mode} complexity={profile.complexity} "
            f"needs_tools={profile.needs_tools} needs_stream={profile.needs_stream} "
            f"needs_reasoning={profile.needs_reasoning}")
