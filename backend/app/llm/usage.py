"""Model Router V2.3 的 usage 记账与聚合观测（spec §8 + D3）。

三件事只在这个文件里发生：

1. **落库**：`llm_request_logs` 建在**现有** `data/conversations.db`（与 `ConversationStore`
   同一个 env 源 `CONVERSATION_DB_PATH`，同库不同表——观测面和会话面共享一次部署的
   数据目录，但不共享 schema 演进）。列 = §8 冻结的 19 列，逐字镜像
   `app.llm.models.UsageRecord` 的字段顺序，一个都不加、一个都不减（D3）。
2. **聚合**：`aggregate_status(window_s=300)` 只产出比率与分位数，不吐行、不吐原文。
3. **启动接线**：`warmup()` 是 lifespan 的 LLM 侧门闸（与 `identity.warmup` 并排）——
   注册表坏 = fail-fast；观测面（建表 / 接 sink）坏 = fail-open。

三条口径值得写在脸上，因为它们都是「顺手就会写错」的形状：

**记账永远 fail-open。** `log_usage()` 里任何异常都吞进 warning：记账塌了不能把生成拖
下水（D3）。写库用**每调短连接**而不是常驻单连接——FastAPI 的同步端点跑在线程池的不同
线程上，`sqlite3` 的跨线程连接检查会直接把常驻连接变成运行期异常；短连接 + 进程内写锁
既没有这个雷，也让「DB 被占用」退化成一次 2s 超时 + 一条 warning，而不是一次挂死的请求。

**禁存项靠净化而不是靠自觉。** `UsageRecord` 里没有 prompt 字段，但落库前的每个字符串
仍然要过白名单：`model` 是 provider 回显的任意文本、`error_type` 上游是
`LLMError.message`（人读的诊断摘要，可能带 body 原文）、`route_reason` 是理由码数组、
`trace_id/request_id` 是调用方给的东西。任何不合形状的值一律**替换**成机器可读的兜底
（`unknown` / 丢弃该码 / 空串），不做截断后保留——截断留着前缀照样能把中文 prompt 的
头几十字带进库。长度上限是同一条规则的第二层，不是第一层。

**只有交付过内容的行才敢叫关页（§8.1 第 1、2 条）。** §8 的 19 列不许加，也没有「是否被
用户取消」这一位；而 T4 的流式口径里 `success=False ∧ error_type IS NULL` 有两类已知来源：
消费方在 commit 之后离开（真实等待、不是模型故障），以及**生产者漏填归类**的全链失败行。
两者只从「缺席」看是同一个形状，从「有没有交付事实」看才分得开。所以账本只把
`fallback_index >= 0 ∧ (input+output) tokens > 0` 的那一类写成 `client_aborted`（`error_type`
既有列的合法值，不是新列），其余一律 `unknown`。这个收窄不是可选的卫生措施，而是防一个
具体的误读：一条谁都没归类的失败若被反推成关页，它就会从 `success_rate` 的分子**和分母**
同时被剔走，status 页于是把「一次全链故障」显示成「1.0 的用户关页 + 零失败样本」。
`unknown` 留在分母里（它是失败），`client_aborted` 由聚合从两头同时剔除并单列
`aborted_rate`——否则「用户关了页面」会被算成「模型失败」，success_rate 就会被浏览器行为
污染。`p95_latency_ms` 不剔除（它量的是用户等了多久，关页之前也是真实等待）。
`client_aborted` / `unknown` / `aborted_rate` / `breaker` 四件的授权口径见 §8.1（评审 I-4 的
回写），不是本文件自扩。

**`model` 列与 `estimated_cost` 由账本收口，不由生产者保证（Task 4 移交 M2）。** 实测三条
出口在 `model` 上写的是两种东西：非流式**成功**行写 provider 回显的**生效模型名**
（`_usage_from_result` 取 `LLMResponse.model`）、非流式**失败**行写**注册表条目 id**
（`_usage_from_failure` 取 `Attempt.model_id`）、流式行经 T4 修复轮后又写生效名
（`log_stream_usage` 自己回查一次注册表）。§8 把 `model` 冻成一列，一列只能指一个东西，
所以落库前统一成「生效模型名」（含 D1 的 `{PROVIDER}_MODEL_OVERRIDE` 别名），口径见
`_stored_model_name`；即便未来某条链又写成 id，列里也只剩一种读法。同一条查找顺带解决
成本：`_cost_for` 的三分支里注册表是**权威牌价**，匹不到条目时**持久化调用方已经算好的**
`estimated_cost`（见该函数 docstring）——§8 冻结了这两列，静默清零等于把账本里唯一的
数据位扔了。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.llm import effective_model_name_for_entry
from app.llm import health as health_module
from app.llm.fallback import (
    AllCandidatesFailedError,
    BREAKERS,
    FallbackResult,
    StreamSummary,
)
from app.llm.health import provider_health_view
from app.llm.models import (
    ModelDefinition,
    RequestProfile,
    RoutePlan,
    UsageRecord,
)
from app.llm.registry import Registry
from app.llm.registry import get_registry
from app.llm.registry import warmup as registry_warmup
from app.llm.registry import RegistryError
from app.llm.router import REASON_CODES

__all__ = [
    "ERROR_TYPE_CLIENT_ABORTED",
    "HEALTH_BUDGET_MS",
    "TABLE_NAME",
    "TRACE_UNKNOWN",
    "USAGE_WINDOW_SECONDS",
    "aggregate_status",
    "database_path",
    "init_usage_db",
    "log_usage",
    "model_route_trace",
    "reset_usage_state",
    "warmup",
]

logger = logging.getLogger("app.llm.usage")

# --------------------------------------------------------------------------
# 口径常量（唯一出处）
# --------------------------------------------------------------------------
TABLE_NAME = "llm_request_logs"
#: §8 的观测窗：`requests_5m` 就是这个 5 分钟，窗口只影响聚合，不影响落库。
USAGE_WINDOW_SECONDS = 300
#: 「关页」行的机器码（§8.1 第 1、2 条；判据见模块 docstring 第三条与 `_clean_error_type`）。
#: 既有列的合法值，不是新列。
ERROR_TYPE_CLIENT_ABORTED = "client_aborted"
#: `error_type` 缺失且未成功、**又没有交付事实**时的兜底归类：它是一次失败，留在
#: `success_rate` 的分母里（§8.1 第 1 条：绝不允许从「生产者漏填归类」反推出「用户关页」）。
ERROR_TYPE_UNKNOWN = "unknown"
#: status 路径的健康探针**整轮共享**预算：超了就用上一轮缓存，没有缓存则 `unknown`。
HEALTH_BUDGET_MS = 1500
#: 写库连接的锁等待上限。超过即放弃这条账（fail-open），绝不把生成链挂在 DB 上。
WRITE_TIMEOUT_SECONDS = 2.0
#: 聚合扫描的行数上限（5 分钟窗口内的兜底：LLM 请求量不可能撞上，撞上了也只取**最近**
#: N 行——SQL 按 `created_at DESC` 排，所以被砍掉的是窗口里最老的那一段）。
AGGREGATE_ROW_CAP = 5000

ERROR_TYPE_MAX_CHARS = 32
IDENTIFIER_MAX_CHARS = 64
MODEL_MAX_CHARS = 128
#: `route_reason` 的长度上限 = §5 冻结枚举的**基数**（`REASON_CODES` 是它的唯一出处）。
#: 曾经这里是硬编码的 12，而枚举只有 9 枚 ⇒ 上限永不生效（评审 Minor 2 的「死码」）。
#: 现在它与去重后的合法码集同宽：正常计划永不触顶，而它仍是「把整张表倒进一列」的闸。
ROUTE_REASON_MAX_ITEMS = len(REASON_CODES)
#: `status_code` 列与 `error_type` 的 `:<状态码>` 后缀**共用**的定义域（评审 Minor 3）。
#: 两件套在历史上不一致（列收 0..1000、正则只收 1..3 位），于是 `retryable:1000` 会退化
#: 成 `unknown`——白丢一格信息。收口方式：把数值判定抽成 `_status_in_range()` 给两处用。
_STATUS_CODE_MIN = 0
_STATUS_CODE_MAX = 1000
#: 成本列的精度（两条分支共用同一个尺度，见 `_caller_cost`）。
_COST_PRECISION = 8
#: trace 的 `model_route` 里两张列表（`fallbacks` / `attempts`）的长度上限：候选链由
#: 注册表规模决定，一个 16 的上限足够容纳任何真实计划，又挡住「把整张注册表倒进 trace」。
TRACE_LIST_MAX_ITEMS = 16
#: `Attempt.result` 的封闭值域（= `app.llm.fallback.AttemptResult`，那里是权威定义）。
_ATTEMPT_RESULTS = frozenset({"success", "failed", "skipped_circuit"})
#: trace 面「读到了不该读到的形状」的兜底值（与 `unknown` 同族：机器码，不是文案）。
TRACE_UNKNOWN = "unknown"

# --------------------------------------------------------------------------
# 白名单（禁存项的执行处，而不是散文里的「请不要」）
# --------------------------------------------------------------------------
#: §6 冻结的四值 + §8.1 第 1 条的两枚账本侧哨兵（`client_aborted` / `unknown`），可选
#: `:no_fallback` 或 `:<状态码>` 后缀（Task 2 评审 M-7：只存 kind 与状态码，**不存**
#: `str(LLMError)`）。数字的**位数**只是形状，**取值域**由 `_status_in_range()` 裁决——
#: 后缀能写的数与 `status_code` 列能存的数必须是同一个区间（评审 Minor 3）。
_ERROR_TYPE_PATTERN = re.compile(
    r"^(?:retryable|config|hard|model_unavailable|client_aborted|unknown)"
    r"(?::no_fallback|:\d{1,4})?$")
#: provider / route_mode / trace_id 这类「机器名」字段。
_IDENTIFIER_PATTERN = re.compile(
    rf"^[A-Za-z0-9_.:-]{{1,{IDENTIFIER_MAX_CHARS}}}$")
#: 模型名允许 `:`（`phi3:mini`）与 `/`（带 org 的 HF 名），其余照旧收紧。
_MODEL_PATTERN = re.compile(
    rf"^[A-Za-z0-9_.:/+\-]{{1,{MODEL_MAX_CHARS}}}$")
#: 币种：§3 `pricing.currency` 是 ISO-4217 三字母，账本不接受别的写法。
_CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")
_REASON_CODES = frozenset(REASON_CODES)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT,
    request_id TEXT,
    route_mode TEXT,
    route_reason TEXT,
    provider TEXT,
    model TEXT,
    fallback_index INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    ttft_ms REAL,
    latency_ms REAL,
    estimated_cost REAL,
    currency TEXT,
    success INTEGER,
    error_type TEXT,
    status_code INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_created_at ON {TABLE_NAME}(created_at);
"""

_INSERT_COLUMNS = (
    "trace_id", "request_id", "route_mode", "route_reason", "provider", "model",
    "fallback_index", "input_tokens", "output_tokens", "total_tokens", "ttft_ms",
    "latency_ms", "estimated_cost", "currency", "success", "error_type", "status_code",
    "created_at",
)
_INSERT_SQL = (
    f"INSERT INTO {TABLE_NAME} ({', '.join(_INSERT_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _INSERT_COLUMNS)})")
_WINDOW_SQL = (
    f"SELECT success, error_type, fallback_index, latency_ms FROM {TABLE_NAME} "
    "WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?")

# --------------------------------------------------------------------------
# 模块状态（写锁 + 建表幂等旗标 + DB 路径覆盖 + 探针线程池）
# --------------------------------------------------------------------------
_WRITE_MUTEX = threading.Lock()
_STATE_GUARD = threading.Lock()
_state: dict[str, Any] = {"schema_ready": False, "db_path": None}
_health_busy = threading.Event()
_health_executor: ThreadPoolExecutor | None = None


def database_path() -> Path:
    """账本落在哪个文件：`init_usage_db(path)` 的覆盖值优先，否则与 `ConversationStore`
    同源（env `CONVERSATION_DB_PATH`，默认 `data/conversations.db`）。"""
    override = _state.get("db_path")
    if override is not None:
        return Path(str(override))
    return Path(os.getenv("CONVERSATION_DB_PATH", "data/conversations.db")).expanduser()


def init_usage_db(path: str | os.PathLike[str] | None = None) -> Path:
    """建表（`IF NOT EXISTS`，幂等）并记下 DB 路径；返回实际使用的文件。

    与 `log_usage` 相反，这里**该抛就抛**：调用方是启动钩子（`warmup()`）与测试，
    「表建不出来」在那里是需要看见的事故。运行期写路径由 `_connect()` 的惰性建表兜住，
    所以启动时点没建成也不会从此丢掉全部账。
    """
    if path is not None:
        with _STATE_GUARD:
            _state["db_path"] = Path(str(path)).expanduser()
            _state["schema_ready"] = False
    target = database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_MUTEX:
        _execute(target, lambda connection: connection.executescript(_SCHEMA))
    with _STATE_GUARD:
        _state["schema_ready"] = True
    return target


def reset_usage_state() -> None:
    """清路径覆盖 / 建表旗标 / 探针线程池。测试换 DB 与收尾必须调用。"""
    global _health_executor
    with _STATE_GUARD:
        _state["db_path"] = None
        _state["schema_ready"] = False
        executor, _health_executor = _health_executor, None
    _health_busy.clear()
    if executor is not None:
        executor.shutdown(wait=False)


def log_usage(record: UsageRecord) -> None:
    """写一行账。**任何异常都不上抛**（D3：记账失败绝不影响生成）。"""
    try:
        row = _row_of(_prepare_record(record))
        with _WRITE_MUTEX:
            _execute(None, lambda connection: connection.execute(_INSERT_SQL, row))
    except Exception as exc:                            # noqa: BLE001 - fail-open 是义务
        logger.warning("LLM usage 落库失败（fail-open，不影响生成）：%s: %s",
                       type(exc).__name__, exc)


def aggregate_status(window_s: int = USAGE_WINDOW_SECONDS) -> dict[str, Any]:
    """§8 的 status 聚合块（§8 明列的五键 + §8.1 第 3 条授权的两枚 additive 键
    `aborted_rate` / `breaker`）。

    返回形状（值可能为 None，键**恒在**——响应面等式测试钉的就是这个键集）::

        {requests_5m: int, success_rate: float|None, fallback_rate: float|None,
         aborted_rate: float|None, p95_latency_ms: float|None,
         providers: {name: {"healthy": bool|"unknown"}},
         breaker: {name: {"state": "closed"|"half_open"|"open"}}}

    口径三条：
    - `success_rate` 的分子分母**都不含** `error_type='client_aborted'` 的行（模块
      docstring 第三条）；`fallback_rate` 与 `aborted_rate` 的分母是窗口内全部行。
    - 任何比率分母为 0 ⇒ `None`（不是 0.0）：「没有样本」与「全失败」是两件事。
    - `LLM_ROUTER_ENABLED=false` ⇒ 整块 no-op：不读库、不探测、不建表，只回空形状。
      开启时也一样：**任何异常都收成空形状**，本函数不外抛。
    """
    if not settings.llm_router_enabled:
        return _empty_status()
    try:
        rows = _fetch_window(max(1, int(window_s)))
        metrics = _metrics_of(rows)
        registry = _registry_or_none()
        return {
            **metrics,
            "providers": _providers_block(registry),
            "breaker": _breaker_block(registry),
        }
    except Exception as exc:                            # noqa: BLE001 - 观测面 fail-open
        # 外层再兜一道：`/api/system/status` 不能因为观测面炸成 500——里面那些 try 只
        # 覆盖了「读库 / 探针 / 注册表」三条外部依赖，聚合口径本身写错了也要能看见。
        logger.warning("LLM usage 聚合失败（fail-open，返回空块）：%s: %s",
                       type(exc).__name__, exc)
        return _empty_status()


def warmup() -> None:
    """lifespan 的 LLM 侧钩子（`app/main.py` 里与 `identity.warmup` 并排）。

    `LLM_ROUTER_ENABLED=false` ⇒ **全链 no-op**：不读注册表、不建表、不接 sink、不探测。
    两步的失败语义刻意不同：
    - `registry_warmup()` 原样上抛 ⇒ 坏注册表是启动事故（沿用 identity 的门闸语义）；
    - 建表失败只 warning ⇒ 观测面塌了不该拖走生成（D3），且 `_connect()` 会在第一次
      真正写账时再试一次建表，所以启动时点 Ollama/磁盘忙不会永久关掉记账。
    """
    if not settings.llm_router_enabled:
        return
    registry_warmup()
    from app.llm import set_usage_sink                  # 包级接缝（避开模块级环）
    set_usage_sink(log_usage)
    try:
        init_usage_db()
    except Exception as exc:                            # noqa: BLE001 - 观测面 fail-open
        logger.warning("LLM usage 表初始化失败（记账 fail-open）：%s: %s",
                       type(exc).__name__, exc)


# --------------------------------------------------------------------------
# trace 的 model_route（§8 的「这次为什么用这个模型」出口，矩阵 #17 的被测面）
# --------------------------------------------------------------------------
def model_route_trace(plan: RoutePlan,
                      result: FallbackResult | StreamSummary | AllCandidatesFailedError,
                      *, profile: RequestProfile | None = None,
                      registry: Registry | None = None) -> dict[str, Any]:
    """§8 trace `model_route` 对象的**唯一构造点**（纯函数：不读库、不外呼、不打日志）。

    输出形状 = §8.1 第 4 条回写后的**九键**，逐字按此顺序（等式测试钉键集合与键序）::

        {mode, requirements{complexity, needs_tools, needs_stream, needs_reasoning},
         primary{id, provider, model, score, reason_codes[]},
         fallbacks[同上], selected_reason_codes[],
         attempts[{model, result, error_type}],
         stage, selected_index, context_dropped}

    末三枚是**执行面**事实（第 0 候选交付 = `primary`、更靠后 = `fallback`、没选中任何
    候选 = `none`；被上下文收口吃掉的候选条数）。§8.1 第 4 条把它们写进了清单：原六键与
    §5（trace 要「带 stage + 被剔计数」）互相矛盾，而丢弃执行面事实比给 trace 补三枚键更坏。
    **同一份事实只在这里构造一次**——`app.llm.model_route_payload()` 曾把这三枚另算一遍
    （且绕过 `_stored_model_name`，对同一个 attempt 给出与账本不同的模型名），已按评审
    裁定 C 删除；防回潮见 `tests/test_llm_usage_contract.py` 的
    `test_there_is_exactly_one_model_route_producer`。

    **归属本模块（而不是 `app/llm/__init__.py`）的理由**：它和 `aggregate_status` 是 §8
    同一条款下的两个观测出口，而它必须复用账本那三件净化件——`_clean_codes`（§5 冻结枚举
    闸门）、`_model_name`（字符集白名单）、`_stored_model_name`（M2 的「生效模型名」单一
    口径）。trace 里的模型名和账本 `model` 列**得是同一个词**，否则「拿 trace 去对账」这条
    运维动作从字形上就对不上；口径放在写账的那一处，两边就只有一份实现。

    输入侧的诚实边界（本轮只建接缝，真实注入点在 T6/T7/T8）：
    - 只读 `profile` 的**五个冻结字段名**（`mode` / `complexity` / `needs_*`）。不 `vars()`、
      不 `dataclasses.asdict()`、不遍历属性——所以调用方哪怕在 profile 上临时挂了
      `query` / `prompt`，也不会有它的任何一个字节进 trace（契约测试用 canary 钉住）。
    - `ModelDefinition` 只取 `id` / `provider` / `model` 三个名字字段，配 `RouteCandidate`
      的 `score` / `reason_codes`；`limits` / `pricing` 不在这里出现（牌价是账本的事）。
    - `attempts[].model` 同样按 M2 口径归一：`Attempt.model_id` 是条目 id（T4 移交 M4），
      回查注册表换成生效模型名；条目已删 / 注册表不可用 ⇒ 原样留 id（可解释的 id 优于空串）。
    - 类型闸门：静默返回一个「形状对但全是默认值」的对象，比当场 `TypeError` 难查——
      trace 里会躺一条从没发过请求的链。第三个可接受类型是 `AllCandidatesFailedError`：
      全链失败时它带的就是同一份 `attempts` / `reason_codes`，而 D2 的降级路径（Agent
      fast-path、RAG 兜底文案）**尤其**需要一条能解释的 route。它**没有** `selected_index`
      这一枚事实（一条候选都没跑通，也就没有「选中第几条」）⇒ 该枚连同由它推出来的
      `stage` 按「没有事实」落：`selected_index=-1`、`stage="none"`（不猜）。
      `context_dropped` 则**自 Task 6 起是它带的字段**（§8.1 第 4 条：降级路最需要解释的
      恰好是「有几条候选根本没被允许尝试」）⇒ 这里读异常里的那个真数，不再恒 0。
    """
    if not isinstance(plan, RoutePlan):
        raise TypeError(
            "model_route_trace 的第一参数需要 RoutePlan（计划面的事实），收到 "
            f"{type(plan).__name__}")
    if not isinstance(result, (FallbackResult, StreamSummary, AllCandidatesFailedError)):
        raise TypeError(
            "model_route_trace 只接受 FallbackResult / StreamSummary / "
            f"AllCandidatesFailedError，收到 {type(result).__name__}")
    snapshot = registry if registry is not None else _registry_or_none()
    plan_side = tuple(plan.fallbacks or ())[:TRACE_LIST_MAX_ITEMS]
    run_side = tuple(getattr(result, "attempts", ()) or ())[:TRACE_LIST_MAX_ITEMS]
    selected_index = _int_or(getattr(result, "selected_index", -1), -1)
    return {
        "mode": _trace_mode(profile),
        "requirements": _trace_requirements(profile),
        "primary": _candidate_view(plan.primary, snapshot),
        "fallbacks": [_candidate_view(candidate, snapshot) for candidate in plan_side],
        "selected_reason_codes": list(_clean_codes(getattr(result, "reason_codes", ()))),
        "attempts": [_attempt_view(attempt, snapshot) for attempt in run_side],
        "stage": _trace_stage(selected_index),
        "selected_index": selected_index,
        "context_dropped": _non_negative_int(getattr(result, "context_dropped", 0) or 0),
    }


def _trace_stage(selected_index: int) -> str:
    """交付面那一个词（§5/T3 移交要求的 `stage`）：第 0 候选 = `primary`。

    值域是 `"none"` 而不是空串：`selected_index < 0` 是一个**事实**（一条候选都没跑通），
    与「读不到 selected_index」在这一点上同形，而 trace 读者要的是能判的词。
    """
    if selected_index < 0:
        return "none"
    return "primary" if selected_index == 0 else "fallback"


def _trace_mode(profile: RequestProfile | None) -> str:
    if profile is None:
        return ""
    return _identifier(getattr(profile, "mode", None)) or ""


def _trace_requirements(profile: RequestProfile | None) -> dict[str, Any]:
    """需求面 = 画像的**四个机器字段**，逐枚按名字读（见 `model_route_trace` 的边界段）。"""
    if profile is None:
        return {}
    return {
        "complexity": _identifier(getattr(profile, "complexity", None)) or "",
        "needs_tools": _trace_flag(getattr(profile, "needs_tools", False)),
        "needs_stream": _trace_flag(getattr(profile, "needs_stream", False)),
        "needs_reasoning": _trace_flag(getattr(profile, "needs_reasoning", False)),
    }


#: 需求旗标允许出现的「真」写法（评审 Minor 4：不再用 `bool(...)` 收 `needs_*`）。
_TRUTHY_FLAGS = frozenset({"1", "true", "yes"})


def _trace_flag(raw: Any) -> bool:
    """`needs_*` 的**显式**真值判定。

    `bool(raw)` 在这里是错的：画像今天由 `classifier` 产出、是真 `bool`，但 trace 是
    跨进程的观测面——只要有人从 JSON / 表单 / 环境变量把 `"false"` 塞进画像，`bool()`
    就会把它读成 `True`，于是 trace 声称「这次要工具」而路由其实没要。观测面报出一个
    不存在的需求，比报不出需求更坏。判定表：`bool` 原样；其余只看
    `"1" / "true" / "yes"`（大小写与首尾空白不敏感），别的都是 `False`。
    """
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in _TRUTHY_FLAGS


def _candidate_view(candidate: Any, registry: Registry | None) -> dict[str, Any]:
    """一个 `RouteCandidate` 的解释视图：名字 + 打分 + 该候选自己的理由码。"""
    definition = getattr(candidate, "model", None)
    entry_id = _identifier(getattr(definition, "id", None)) or ""
    declared = _model_name(getattr(definition, "model", None))
    entry = _entry_by_id(entry_id, registry)
    return {
        "id": entry_id,
        "provider": _identifier(getattr(definition, "provider", None)) or "",
        # 注册表里的这条声明就是权威：`_stored_model_name` 只会套上 D1 的别名，
        # 不会把牌价名换成一个来路不明的回显（`entry is None` 时它原样返回声明名）。
        "model": _stored_model_name(entry, declared),
        "score": max(0, _int_or(getattr(candidate, "score", 0), 0)),
        "reason_codes": list(_clean_codes(getattr(candidate, "reason_codes", ()))),
    }


def _attempt_view(attempt: Any, registry: Registry | None) -> dict[str, Any]:
    """一次候选级回执（§8 冻结的三个字段）。不合形状的名字一律**不猜**：空串。"""
    raw = str(getattr(attempt, "model_id", "") or "")
    name = _model_name(raw)                        # 先白名单，再按条目 id 归一
    return {
        "model": _stored_model_name(_entry_by_id(name, registry), name) if name else "",
        "result": _trace_result(getattr(attempt, "result", None)),
        "error_type": _trace_error_code(getattr(attempt, "error_type", None)),
    }


def _trace_result(raw: Any) -> str:
    """`Attempt.result` 的封闭值域（T4 的 `AttemptResult`）+ 一个显式的 `unknown`。"""
    text = str(raw or "")
    return text if text in _ATTEMPT_RESULTS else TRACE_UNKNOWN


def _trace_error_code(raw: Any) -> str | None:
    """attempt 的错误位：只收 §6 的机器码，缺失给 None（不是 `unknown`——没错误就是没错误）。

    形状判定与账本 `error_type` 列走**同一个** `_error_type_value()`：同一枚码在两处
    （trace 的 attempt / 账本的列）必须能写成同一个词，否则拿 trace 对账时对不上。
    """
    if raw is None or not str(raw).strip():
        return None
    return _error_type_value(raw)


def _entry_by_id(entry_id: str, registry: Registry | None) -> ModelDefinition | None:
    """按条目 id 回查注册表；查不到（条目被删 / 注册表不可用）即 None，不抛。"""
    if registry is None or not entry_id:
        return None
    try:
        return registry.get(entry_id)
    except RegistryError:
        return None


# --------------------------------------------------------------------------
# 落库前的收口（纯函数：可单测，不碰 IO）
# --------------------------------------------------------------------------
def _prepare_record(record: UsageRecord) -> UsageRecord:
    """返回**可直接落库**的副本：类型收口 + 禁存项净化 + 关页归因 + 牌价折算。

    注册表在这里只查**一次**（`_registry_or_none`）：`model` 列的口径归一和
    `estimated_cost` 的折算问的是同一个问题（「这条账说的是哪个条目？」），查两遍会
    让两次答案有机会不一致。查不到（注册表不可用）时两者各自退回安全的第二答案：
    模型名原样落库、成本走 `_cost_for` 的第 ② / ③ 支。

    顺序上有一处**不能调换**：`error_type` 的关页判据要读「有没有交付事实」，而那个事实
    是收口**之后**的 token 数与 `fallback_index`（`"n/a"` 的 token 收口成 0 ⇒ 没有交付 ⇒
    不是关页）。先判归类再收口，就会把一条坏数据的账本说成「用户关了页面」。
    """
    codes = _clean_codes(record.route_reason)
    success = bool(record.success)
    provider = _identifier(record.provider) or ""
    name = _model_name(record.model)
    registry = _registry_or_none()
    entry = _match_entry(registry, provider, name)
    # 牌价折算吃的是**收口后**的 token 数：生产者递来 `"n/a"` 时原始值连乘都不行，
    # 让账本自己因为一次类型错误丢整行（fail-open 会吞掉它）是最亏的一种错。
    input_tokens = _non_negative_int(record.input_tokens)
    output_tokens = _non_negative_int(record.output_tokens)
    fallback_index = _int_or(record.fallback_index, -1)
    cost, currency = _cost_for(entry, record, input_tokens=input_tokens,
                               output_tokens=output_tokens)
    return UsageRecord(
        trace_id=_identifier(record.trace_id),
        request_id=_identifier(record.request_id),
        route_mode=_identifier(record.route_mode) or "",
        route_reason=codes,
        provider=provider,
        model=_stored_model_name(entry, name),
        fallback_index=fallback_index,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_non_negative_int(record.total_tokens),
        ttft_ms=_non_negative_float(record.ttft_ms) if record.ttft_ms is not None else None,
        latency_ms=_non_negative_float(record.latency_ms),
        estimated_cost=cost,
        currency=currency,
        success=success,
        error_type=_clean_error_type(
            record.error_type, success=success,
            delivered=_has_delivery(fallback_index, input_tokens, output_tokens)),
        status_code=_status_code(record.status_code),
        created_at=_created_at(record.created_at))


def _row_of(record: UsageRecord) -> tuple[Any, ...]:
    """19 列里的 18 个可写列（`id` 交给 AUTOINCREMENT）。"""
    return (
        record.trace_id, record.request_id, record.route_mode,
        json.dumps(list(record.route_reason)),                      # 纯 ASCII 码数组
        record.provider, record.model, record.fallback_index,
        record.input_tokens, record.output_tokens, record.total_tokens,
        record.ttft_ms, record.latency_ms, record.estimated_cost, record.currency,
        1 if record.success else 0, record.error_type, record.status_code,
        record.created_at)


def _clean_error_type(raw: Any, *, success: bool, delivered: bool) -> str | None:
    """`error_type` 只收机器码；不合形状一律 `unknown`（把原文挡在列外）。

    `success=False ∧ error_type` 缺失时**分两支**（§8.1 第 2 条，评审 I-4 的收窄）：
    - 有交付事实（`delivered`，见 `_has_delivery`）⇒ `client_aborted`：内容已经吐给用户、
      消费方随后离开，这是真实等待而不是模型故障。
    - 没有交付事实 ⇒ `unknown`：**从「生产者没归类」反推「用户关页」是编事实**。那条行
      留在 `success_rate` 的分母里（它是一次失败），否则一次全链故障会在 status 页读成
      「1.0 的关页 + 零失败样本」——两头都被吃掉，运维无从判断。
    交付闸对**两个来源**都关：`client_aborted` 只能由账本在「失败 + 有交付事实」时产出，
    生产者自己把这个词写进 `error_type` 也同样退回 `unknown`（评审复验 N1——否则 §8.1 要防的
    那个误读换一条路就能复现，而 `unknown` 那一侧的闸是开的、这一侧是关的，两半不对称）。
    成功行也不许带这个哨兵：`scored_rows` 按 `error_type` 剔行，一枚贴在成功行上的
    `client_aborted` 会把一次真实成功从 `success_rate` 的分子与分母里一起请走。
    """
    if isinstance(raw, str) and raw.strip():
        value = _error_type_value(raw)
        if value == ERROR_TYPE_CLIENT_ABORTED and (success or not delivered):
            return ERROR_TYPE_UNKNOWN
        return value
    if success:
        return None
    return ERROR_TYPE_CLIENT_ABORTED if delivered else ERROR_TYPE_UNKNOWN


def _has_delivery(fallback_index: int, input_tokens: int, output_tokens: int) -> bool:
    """「这次真的交付过内容」的最小事实：选中过候选 **且** 算出过 token。

    两个条件都要：`fallback_index >= 0` 说明有候选跑通到被选中，`tokens > 0` 说明它真的
    吐过字。全链 pre-commit 皆败的行是 `(-1, 0, 0)`——那种行没有一行内容到达过用户，
    把它叫「关页」就是把故障改写成用户体验。收口后的值才进这里（见 `_prepare_record`）。
    """
    return fallback_index >= 0 and (input_tokens + output_tokens) > 0


def _error_type_value(raw: Any) -> str | None:
    """把一个外来的 `error_type` 折成机器码：空 ⇒ None，不合形状 ⇒ `unknown`。

    先压空白再截断**再**匹配整串（顺序即口径）：截断留着前缀照样能把中文 prompt 的头
    几十字带进列，所以白名单必须在截断之后仍然整串成立。
    """
    text = " ".join(str(raw or "").split())
    if not text:
        return None
    candidate = text[:ERROR_TYPE_MAX_CHARS]
    return candidate if _error_type_shape_ok(candidate) else ERROR_TYPE_UNKNOWN


def _error_type_shape_ok(candidate: str) -> bool:
    """形状 + **取值域**双闸：`kind[:no_fallback|:状态码]`，状态码必须落在列允许的区间。

    评审 Minor 3：历史上这里只看正则（`:\\d{1,3}`），而 `status_code` 列收到 0..1000，
    两条边界对同一个数给出不同答案（`retryable:1000` 被正则判死 ⇒ `unknown`，白丢一格
    信息）。现在两处共用 `_status_in_range()`：能写进 `status_code` 列的数，就能出现在
    `error_type` 的后缀里，反之两边都不收。
    """
    if not _ERROR_TYPE_PATTERN.match(candidate):
        return False
    _, separator, suffix = candidate.partition(":")
    if separator and suffix.isdigit():
        return _status_in_range(int(suffix))
    return True


def _clean_codes(raw: Any) -> tuple[str, ...]:
    """理由码过 §5 的冻结枚举：越界值**丢弃**（不截断、不转写），按首次出现去重后截顶。

    去重与上限两件事都在这里（`ROUTE_REASON_MAX_ITEMS` = 枚举基数）：一列 JSON 里躺同
    一枚码两次是计划面某处 concat 写错的信号，而「无上限」意味着一列可以长到把整张表
    拖下水。两者都有测试钉（评审 Minor 2 的存活变异就是缺这一例）。
    """
    kept = [str(code) for code in (raw or ()) if str(code) in _REASON_CODES]
    return tuple(dict.fromkeys(kept))[:ROUTE_REASON_MAX_ITEMS]


def _identifier(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw)
    return text if _IDENTIFIER_PATTERN.match(text) else None


def _model_name(raw: Any) -> str:
    """`model` 列的取值来自 provider 回显 ⇒ 按「模型名字符集」收，不合形状即空串。

    这里不 `redact`：`redact_text` 只认 `apikey_*`/`Bearer` 两种形状，认不出「上游把
    用户问题回显进 model 字段」——而模型名的合法字符集里根本没有汉字与空格，白名单比
    黑名单在这里更便宜也更严。
    """
    text = str(raw or "")
    return text if len(text) <= MODEL_MAX_CHARS and _MODEL_PATTERN.match(text) else ""


def _currency(raw: Any) -> str:
    text = str(raw or "")
    return text.upper() if _CURRENCY_PATTERN.match(text) else ""


def _int_or(raw: Any, default: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return default
    return raw


def _non_negative_int(raw: Any) -> int:
    value = _int_or(raw, 0)
    return value if value > 0 else 0


def _non_negative_float(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    # NaN 与负数都落 0.0：`NaN > 0` 为假，所以一个比较就把两类坏值一起挡掉了。
    return round(value, 3) if value > 0 else 0.0


def _status_in_range(value: int) -> bool:
    """状态码的定义域（`status_code` 列与 `error_type` 的 `:状态码` 后缀共用）。"""
    return _STATUS_CODE_MIN <= value <= _STATUS_CODE_MAX


def _status_code(raw: Any) -> int | None:
    value = _int_or(raw, -1)
    return value if _status_in_range(value) else None


def _created_at(raw: Any) -> str:
    """统一成 `YYYY-MM-DDTHH:MM:SSZ`（UTC）：字典序即时间序，窗口过滤才能用字符串比较。"""
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            return _iso_utc(_now())
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return _iso_utc(parsed.astimezone(timezone.utc))
    return _iso_utc(_now())


def _match_entry(registry: Registry | None, provider: str,
                 name: str) -> ModelDefinition | None:
    """这条账说的是注册表里的哪个条目：`provider` 相符，且 `model`（生效名）或 `id` 命中。

    同名歧义时**先按 `model` 判**：`model` 是 provider 真正调用的名字，而 `id` 只是文件里
    的标签。反过来（先按 id）会让「一条声明里 `id` 恰好等于另一条的 `model`」把账指错条目，
    从而套错牌价。找不到即 None（不猜、不做模糊匹配）。
    """
    if registry is None or not provider or not name:
        return None
    by_id: ModelDefinition | None = None
    for entry in registry.models:
        if entry.provider != provider:
            continue
        if entry.model == name:
            return entry
        if entry.id == name and by_id is None:
            by_id = entry
    return by_id


def _entry_effective_name(entry: ModelDefinition) -> str:
    """条目 → **生效模型名**（含 D1 的 `{PROVIDER}_MODEL_OVERRIDE`）净化后的值。

    解析本身**不在这里**：它住在 `app.llm.effective_model_name_for_entry`（包级唯一实现，
    出处是 `app/llm/provider.py::effective_model_name`）。账本这一层只多套一道字符集白名单
    （`_model_name`），因为这里出来的字符串要直接进 `model` 列。
    评审 Minor 7 曾数出两份实现（这里 + `__init__.py::_effective_model_name`）——两份都调
    同一个 `provider` 解析所以别名不会漂，但代码是两份；现已并成一份。
    """
    return _model_name(effective_model_name_for_entry(entry))


def _stored_model_name(entry: ModelDefinition | None, name: str) -> str:
    """M2 的最终口径：`model` 列**恒**存生效模型名（Task 4 移交项的落地点）。

    三条出口的实测差异见模块 docstring 第四条：非流式成功行本来就是生效名，流式行在 T4
    修复轮后也是，只有失败行写 `Attempt.model_id`（条目 id）。账本不打算记住「哪一行来自
    哪条链」，所以在这里统一：
    - 命中条目 ⇒ 写该条目的生效模型名（匹到的是 `id` 就把 id 换成名字；匹到的是 `model`
      则这一步是幂等的，只在 override 生效时把声明名换成别名——那正是真正被调用的名字）；
    - 匹不到（条目被删、provider 名不合法、注册表不可用）⇒ 原样留 `_model_name` 的结果。
      宁可留一个可解释的 id，也不要空串（同 `test_entry_missing_from_the_registry_falls_back_to_the_id`
      那条裁定）；
    - `name` 为空（被字符集白名单挡掉的回显，例如 provider 把用户问题塞进 model 字段）
      ⇒ 仍为空：**这里没有信息可以恢复**，不拿 provider 去猜一个模型名。
    """
    if entry is None or not name:
        return name
    return _entry_effective_name(entry) or name


def _caller_cost(raw: Any) -> float | None:
    """调用方自带的成本：**只有真的算出来过**才算数（有限、严格为正）。

    这里不复用 `_non_negative_float`：那个的 3 位小数是给延迟用的，而成本在「每次几千
    token」这一档上就是 1e-4 量级（200 输入 token × $2/1m = 0.0004），按 3 位四舍五入会
    把一条算过的账折成 0.0 —— 然后被下面这一问判成「没算过」。精度对齐 §3 牌价那一支的
    8 位小数，两条分支才在同一个尺度上。

    `0.0` 不算数，因为它分不开「算过了，这一路免费」与「压根没算」（`UsageRecord` 的字段
    默认值就是 0.0）。把后者当前者落库会给 `currency` 一个它没资格拿的币种，于是库里出现
    「USD 且 0 成本」的行，而 §8 的口径是**空币种才是「不知道牌价」的唯一标记**。
    免费路因此与牌价未知的免费路同形（`0.0` + 空币种）：成本面 V2.6 才进决策路径，
    这个信息损失是已记账的（→ 报告「遗留 minor」）。
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return round(value, _COST_PRECISION)


def _cost_for(entry: ModelDefinition | None, record: UsageRecord, *,
              input_tokens: int, output_tokens: int) -> tuple[float, str]:
    """`estimated_cost` / `currency` 两列的三分支口径（§8 冻结了这两列，不许静默清零）。

    ① **注册表匹到条目**（`provider` + `entry.model` 或 `entry.id`）⇒ 牌价是权威，按 §3 的
       每 100 万 token 单价折算，币种取条目的 `pricing.currency`。此时调用方传什么成本都不
       认——同一张表里两套价格来源，聚合出来的总额就取决于哪条链先写。
    ② **匹不到，但调用方算过成本**（`estimated_cost` 有限且 > 0）⇒ 持久化调用方的值，币种
       取它自带的 `currency`（过 `_CURRENCY_PATTERN` 白名单并大写，不合形状即空串）。账本
       必须能承载上游已经算好的成本：`{PROVIDER}_MODEL_OVERRIDE` 生效、上游回显了别名、
       或注册表按 provider 名对不上时，牌价查不到，但调用方未必不知道价。
    ③ **调用方也没给** ⇒ `(0.0, "")`。空币种仍是「不知道牌价」的唯一标记（本地模型牌价为 0
       与牌价未知在 `estimated_cost` 上都是 0，靠这一位区分）。

    token 数用调用方传进来的**收口值**（见 `_prepare_record`），不在这一步二次收口。
    """
    if entry is not None:
        pricing = entry.pricing
        cost = (input_tokens * float(pricing.input_per_1m)
                + output_tokens * float(pricing.output_per_1m)) / 1_000_000.0
        return round(cost, _COST_PRECISION), _currency(pricing.currency)
    supplied = _caller_cost(record.estimated_cost)
    if supplied is not None:
        return supplied, _currency(record.currency)
    return 0.0, ""


# --------------------------------------------------------------------------
# 聚合
# --------------------------------------------------------------------------
def _metrics_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """四个率 + p95。关页那一刀**只筛一次**（`scored_rows`），分子分母共用它：
    两处各自实现「谁不进 success_rate」时，改一处漏一处正好是那种没人报修的漂移。
    """
    total = len(rows)
    scored = scored_rows(rows)
    aborted = total - len(scored)
    succeeded = sum(1 for row in scored if _truthy(row.get("success")))
    fallbacks = sum(1 for row in rows if _int_or(row.get("fallback_index"), -1) > 0)
    latencies = [_non_negative_float(row.get("latency_ms")) for row in rows
                 if row.get("latency_ms") is not None]
    return {
        "requests_5m": total,
        "success_rate": _ratio(succeeded, len(scored)),
        "fallback_rate": _ratio(fallbacks, total),
        "aborted_rate": _ratio(aborted, total),
        "p95_latency_ms": _percentile(latencies, 0.95),
    }


def scored_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """进 `success_rate` 分母的行：**只**排除 `client_aborted`（口径见 `aggregate_status`）。

    `unknown` **不在**剔除名单里：它是「确实失败、只是没人给出归类」，把它也请出分母就等于
    用第二个哨兵把第一批失败一起抹掉（§8.1 第 1、2 条要区分的是「用户离开」与「链坏了」，
    不是「失败的两种写法」）。
    """
    return [r for r in rows if r.get("error_type") != ERROR_TYPE_CLIENT_ABORTED]


def _empty_status() -> dict[str, Any]:
    return {
        "requests_5m": 0, "success_rate": None, "fallback_rate": None,
        "aborted_rate": None, "p95_latency_ms": None, "providers": {}, "breaker": {},
    }


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole > 0 else None


def _percentile(values: list[float], quantile: float) -> float | None:
    """最近秩（nearest-rank）：`ceil(q*n)` 位的值，1 个样本也给。

    与 `knowledge_os._percentile`（trace 面，<5 样本给 None）刻意不同口径：这里的样本是
    请求行，一条 5 分钟窗口里只有一次生成时，「那次多久」就是运维要知道的事实。
    """
    if not values:
        return None
    ordered = sorted(values)
    index = min(max(0, int(-(-quantile * len(ordered) // 1)) - 1), len(ordered) - 1)
    return round(ordered[index], 1)


def _fetch_window(window_s: int) -> list[dict[str, Any]]:
    """读窗口内的行；表还没建 / 库被占用 ⇒ 空集（聚合面 fail-open，不外抛）。"""
    try:
        return _query(_WINDOW_SQL, (_cutoff_iso(window_s), AGGREGATE_ROW_CAP),
                      _WINDOW_SQL_COLUMNS)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            logger.debug("LLM usage 表尚未建立，聚合返回空窗口：%s", exc)
        else:
            logger.warning("LLM usage 聚合读库失败（fail-open）：%s", exc)
        return []
    except (sqlite3.Error, OSError) as exc:
        logger.warning("LLM usage 聚合读库失败（fail-open）：%s", exc)
        return []


_WINDOW_SQL_COLUMNS = ("success", "error_type", "fallback_index", "latency_ms")


# --------------------------------------------------------------------------
# providers / breaker 观测面
# --------------------------------------------------------------------------
def _providers_block(registry: Registry | None) -> dict[str, dict[str, Any]]:
    """`{provider: {"healthy": bool|"unknown"}}`，**整轮** 1.5s 预算。

    最小实现法：不改 `provider_health_view` 的签名，而是在外面包一层墙钟——探针丢进
    单线程执行池，`result(timeout=1.5)` 拿不到就退到 `health` 的 60s 缓存值，缓存也没有
    则 `unknown`。跑着的那轮探针**不取消**：它会把结果写进缓存，下一次 status 直接命中
    （于是「Ollama 起得慢」表现为 unknown → 下一轮变 true/false，而不是每轮都卡 1.5s）。
    `_health_busy` 保证同时只有一轮探针在跑，慢 provider 不会把线程池堆爆。
    """
    names = _provider_names(registry)
    if not names:
        return {}
    future = _submit_probe(registry)
    if future is not None:
        try:
            view = future.result(timeout=max(0.05, HEALTH_BUDGET_MS / 1000.0))
            return {name: {"healthy": _healthy_of(view, name)} for name in names}
        except FutureTimeout:
            pass                                        # 回调里复位 busy，下轮读缓存
        except Exception as exc:                        # noqa: BLE001 - 观测面 fail-open
            _health_busy.clear()
            logger.warning("LLM provider 健康视图不可用（改读缓存）：%s: %s",
                           type(exc).__name__, exc)
    stale = _cached_health()
    return {name: {"healthy": stale.get(name, "unknown")} for name in names}


def _healthy_of(view: Any, name: str) -> Any:
    """探针视图里取一个 provider 的 `healthy`。

    兼容 `{p: {"healthy": bool}}`（`provider_health_view` 的形状）与 `{p: bool}`
    （`fallback.routing_health_view` 容错过的形状）；视图里没有这个 provider ⇒ `unknown`
    （**不是** False：把「没探到」写成「探到不健康」会让 §5 的 health 过滤面误判）。
    """
    try:
        entry = dict(view).get(name)
    except (TypeError, ValueError):
        return "unknown"
    if isinstance(entry, Mapping):
        value = entry.get("healthy")
    else:
        value = entry
    return value if isinstance(value, bool) else "unknown"


def _submit_probe(registry: Registry | None) -> Future | None:
    global _health_executor
    if registry is None or _health_busy.is_set():
        return None
    with _STATE_GUARD:
        if _health_busy.is_set():
            return None
        _health_busy.set()
        if _health_executor is None:
            _health_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="llm-health")
        executor = _health_executor
    try:
        future = executor.submit(provider_health_view, registry)
    except Exception:                                   # noqa: BLE001 - 观测面 fail-open
        _health_busy.clear()
        return None
    future.add_done_callback(lambda _f: _health_busy.clear())
    return future


def _cached_health() -> dict[str, bool]:
    """`health` 的进程内缓存快照（同包读私有表：60s 缓存的所有权在 health 侧）。"""
    now = health_module._now()
    snapshot: dict[str, bool] = {}
    for name, entry in dict(getattr(health_module, "_health_cache", {})).items():
        try:
            written, healthy = entry
        except (TypeError, ValueError):
            continue
        if now - float(written) < health_module.HEALTH_CACHE_TTL_SECONDS:
            snapshot[str(name)] = bool(healthy)
    return snapshot


def _breaker_block(registry: Registry | None) -> dict[str, dict[str, str]]:
    """`{provider: {"state": "closed"|"half_open"|"open"}}`。

    读 `CircuitBreaker.state`（`app/resilience.py` 文档化的观测口，**有副作用**：冷却到
    期时惰性推进 OPEN→HALF_OPEN）。这与 typesafe 块的 `breaker_state` 同一先例：本端点
    只在系统页手动加载/刷新时采样，不是轮询热路径。没有实例的 provider = 还没流过流量
    = `closed`（不懒创建，那会凭空造出一把熔断器）。
    """
    names = set(_provider_names(registry)) | set(BREAKERS)
    return {name: {"state": _breaker_state(name)} for name in sorted(names)}


def _breaker_state(name: str) -> str:
    breaker = BREAKERS.get(name)
    if breaker is None or not settings.llm_breaker_enabled:
        return "closed"
    state = str(getattr(breaker, "state", "closed"))
    return state if state in ("closed", "half_open", "open") else "closed"


def _provider_names(registry: Registry | None) -> tuple[str, ...]:
    if registry is None:
        return tuple(sorted(BREAKERS))
    seen: dict[str, None] = {}
    for model in registry.models:
        if model.enabled:
            seen.setdefault(model.provider, None)
    return tuple(seen)


def _registry_or_none() -> Registry | None:
    try:
        return get_registry()
    except Exception as exc:                            # noqa: BLE001 - 观测面 fail-open
        logger.warning("LLM 注册表不可用，观测面按空视图处理：%s: %s",
                       type(exc).__name__, exc)
        return None


# --------------------------------------------------------------------------
# 连接与时钟
# --------------------------------------------------------------------------
def _connect(path: Path | str | None = None, *, ensure_schema: bool = True) -> sqlite3.Connection:
    """每调短连接（模块 docstring 第一条口径）。**调用方负责 close/commit**——用 `_execute`
    / `_query`，别直接用这个。"""
    target = Path(str(path)) if path is not None else database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=WRITE_TIMEOUT_SECONDS)
    if ensure_schema and not _state.get("schema_ready"):
        connection.executescript(_SCHEMA)
        with _STATE_GUARD:
            _state["schema_ready"] = True
    return connection


def _execute(path: Path | str | None, action: Callable[[sqlite3.Connection], Any]) -> Any:
    """写路径的唯一收口：短连接 → 动作 → commit → close。异常原样上抛（由调用方裁决）。"""
    connection = _connect(path)
    try:
        result = action(connection)
        connection.commit()
        return result
    finally:
        connection.close()


def _query(sql: str, params: tuple[Any, ...], columns: tuple[str, ...]) -> list[dict[str, Any]]:
    """读路径：短连接 → SELECT → 折叠成 dict 列表 → close。**表存在**为前提（不建表）。"""
    connection = _connect(ensure_schema=False)
    try:
        cursor = connection.execute(sql, params)
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def _now() -> datetime:
    """时间源接缝：窗口过滤与 `created_at` 共用（测试换它，不等 5 分钟）。"""
    return datetime.now(timezone.utc)


def _iso_utc(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cutoff_iso(window_s: int) -> str:
    return _iso_utc(_now() - timedelta(seconds=window_s))


def _truthy(value: Any) -> bool:
    """SQLite 的 `success` 是 INTEGER：1/0/None 都可能出现。"""
    if isinstance(value, bool):
        return value
    try:
        return int(value or 0) != 0
    except (TypeError, ValueError):
        return bool(value)
