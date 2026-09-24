"""Model Router V2.3 · Task 5 契约测试（测试类⑤：usage 记账 + 观测）。

覆盖 brief 点名的五组：

1. **§8 冻结面**：`llm_request_logs` 的 19 列逐字（DDL ↔ §8 常量 ↔ `UsageRecord` 三方等式）、
   写读往返、`route_reason` 的 JSON 数组、`init_usage_db` 幂等与「路径与 `ConversationStore`
   同源」。
2. **禁存项反测试（D3）**：把超长中文 prompt 掺进每一个字符串列、把 `str(LLMError)`（带上游
   body canary）掺进 `error_type`，落库后 `SELECT *` 全列扫 0 命中；`error_type` 只收机器码
   词表 + 长度上限；越界数字与不合字符集的标识符整值丢弃。
3. **关页语义（§8.1 第 1、2 条）**：`success=False ∧ error_type 缺失` **只在有交付事实时**
   落库写成 `client_aborted`，其余落 `unknown`；聚合把前者从 `success_rate` 的**分子与分母
   同时**剔除并单列 `aborted_rate`，后者**留在分母里**；`fallback_rate` /
   `aborted_rate` 的分母仍是窗口全部行；分母 0 ⇒ None。10 行窗口内/外组合逐值断言。
4. **fail-open**：DB 被占用时 `log_usage` 不抛、`llm.complete()` 主链照旧交付内容；聚合读库
   失败退化成空块；`aggregate_status` 任何异常都不外抛。
5. **观测出口**：providers 走 `provider_health_view` 但整轮 1.5s 预算（超时退缓存 /
   unknown、同时只允许一轮探针在跑）；breaker 状态只读不建，且**不渗透进 `healthy`**
   （D4）；`public_llm_status` 的 deny-by-default 等式（白名单逐枚列举，同前缀邻近键与
   URL 形状的 provider 名都不许过——provider 名的字符集与注册表同源）；
   `/api/system/status` 的 `llm` 块形状。
6. **`estimated_cost` 三分支 + `model` 列单一口径（Task 4 移交 M2）**：注册表匹到 ⇒ 牌价
   权威；匹不到 ⇒ 持久化调用方算好的成本（币种过白名单）；都没给 ⇒ `(0.0, "")`。跨路
   一致性：非流式成功 / 非流式失败（写的是条目 id）/ 流式三条出口在 `model` 列上落同一个
   词，`{PROVIDER}_MODEL_OVERRIDE` 生效时也是。
7. **trace `model_route`（§8.1 第 4 条的九键 + T6/7/8 的接缝）**：`usage.model_route_trace()`
   的形状逐字（顶层 / requirements / candidate / attempt 四层键序 + 末三枚执行面事实
   `stage` / `selected_index` / `context_dropped`）、越界值收成机器码兜底、
   画像里塞 `query` canary 后 0 命中、两张列表封顶、类型闸门；
   `agent_trace.attach_model_route()` 的 additive（只多一个键）、fail-open、以及落盘
   JSONL 读回来的集成半段；再加一枚**防回潮钉**：同一个事实不许有第二个 `model_route`
   生产者（`llm.model_route_payload` 已按评审裁定 C 删除，不得复活）。
8. **lifespan 接线**：`warmup` 的「门闸 → sink → 建表」链（`LLM_ROUTER_ENABLED=false` 全链
   no-op；坏注册表 fail-fast、坏观测面 fail-open）。

隔离手法沿用 Task 1–4：`Settings(_env_file=None)` + 清 OS env + 每用例一个临时
`conversations.db` + 冻结 `usage._now`（窗口算术不必真等 5 分钟）。
注册表由 `_UsageFixture.setUp` **统一注入**（评审 I-5）：聚合的 `providers` / `breaker`
两面读注册表，早先两例把这件事交给了运行目录——从 `backend/` 跑绿、从仓库根跑红。
现在夹具负责它，本文件在任意 cwd 下都是同一组数字。
"""
from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

import app.agent_trace as agent_trace_module  # noqa: E402
import app.knowledge_os as knowledge_os_module  # noqa: E402
import app.llm as llm  # noqa: E402
import app.llm.fallback as fallback_module  # noqa: E402
import app.llm.health as health_module  # noqa: E402
import app.llm.provider as provider_module  # noqa: E402
import app.llm.registry as registry_module  # noqa: E402
import app.llm.usage as usage_module  # noqa: E402
import app.main as main_module  # noqa: E402
import app.main_agent  # noqa: E402  F401  —— knowledge_os 路由由这个入口挂上（同一个 app 实例）
from app.agent_trace import MODEL_ROUTE_KEY, attach_model_route  # noqa: E402
from app.config import Settings  # noqa: E402
from app.conversation_store import ConversationStore  # noqa: E402
from app.llm.errors import LLMError  # noqa: E402
from app.llm.fallback import (  # noqa: E402
    AllCandidatesFailedError,
    Attempt,
    FallbackResult,
    StreamSummary,
)
from app.llm.models import (  # noqa: E402
    LLMResponse,
    ModelDefinition,
    RequestProfile,
    RouteCandidate,
    RoutePlan,
    UsageRecord,
)
from app.llm.registry import Registry, RegistryError, reset_registry  # noqa: E402
from app.llm.router import REASON_CODES, NoCapableModelError  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.security import PUBLIC_LLM_STATUS_KEYS, public_llm_status  # noqa: E402

OLLAMA_URL = "http://ollama.test"
OPENAI_URL = "http://openai.test/v1"
FIXED_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

#: §8 冻结的 19 列（顺序 = `UsageRecord` 字段顺序 = DDL 列序）。
SPEC_COLUMNS = (
    "id", "trace_id", "request_id", "route_mode", "route_reason", "provider", "model",
    "fallback_index", "input_tokens", "output_tokens", "total_tokens", "ttft_ms",
    "latency_ms", "estimated_cost", "currency", "success", "error_type", "status_code",
    "created_at",
)

#: 聚合块在 §8 + §8.1 第 3 条里的键集（等式测试用；`aborted_rate` / `breaker` 是 §8.1
#: 回写授权的两枚 additive 键，不是实现侧自扩）。
AGGREGATE_KEYS = {"requests_5m", "success_rate", "fallback_rate", "aborted_rate",
                  "p95_latency_ms", "providers", "breaker"}

#: 一段「超长中文 prompt」：它可能以任何方式被顺手落库，所以每个用例都拿它当 canary。
LONG_PROMPT = (
    "客户甲与乙于2026年3月签订的保密协议约定违约金上限为人民币捌佰万元整，"
    "请逐条分析该条款在跨境交付场景下的可执行性与风险敞口，并给出修改建议，"
    "同时引用知识库中相关的历史判例与内部审批记录原文。" * 6
)

#: §8.1 第 4 条回写后的 trace `model_route` 顶层**九键**（顺序逐字；等式测试钉这个元组）。
#: 末三枚是执行面事实：原 §8 的六键与 §5（trace 要带 stage + 被剔计数）互相矛盾，
#: 而 19 列里没有它们的位置 ⇒ 回写成九键，唯一生产者 `usage.model_route_trace`。
MODEL_ROUTE_KEYS = ("mode", "requirements", "primary", "fallbacks",
                    "selected_reason_codes", "attempts",
                    "stage", "selected_index", "context_dropped")
#: §8 里 `attempts[{model,result,error_type}]` 的三个字段。
MODEL_ROUTE_ATTEMPT_KEYS = ("model", "result", "error_type")
#: 计划面一个候选的解释字段（`limits`/`pricing` 不在其中：牌价是账本的事，不是解释）。
MODEL_ROUTE_CANDIDATE_KEYS = ("id", "provider", "model", "score", "reason_codes")
#: §8 需求面的四个机器字段（`mode` 在顶层，不在此处）。
MODEL_ROUTE_REQUIREMENT_KEYS = ("complexity", "needs_tools", "needs_stream",
                                "needs_reasoning")


def make_settings(**overrides) -> Settings:
    with mock.patch.dict(os.environ, {}, clear=True):
        base = {"ollama_base_url": OLLAMA_URL, "openai_base_url": OPENAI_URL,
                "openai_api_key": ""}
        base.update(overrides)
        return Settings(_env_file=None, **base)


def entry_of(**overrides) -> ModelDefinition:
    data = {
        "id": "fb-a", "provider": "ollama", "model": "fb-a-model",
        "enabled": True, "external": False,
        "capabilities": {"chat": True, "rag": True, "tools": True, "stream": True,
                         "reasoning": False},
        "priority": {"chat": 10, "rag": 10, "tools": 10},
        "limits": {"context_tokens": 8192, "max_output_tokens": 2048},
        "pricing": {"input_per_1m": 0.0, "output_per_1m": 0.0, "currency": "USD"},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def registry_of(*models: ModelDefinition) -> Registry:
    return Registry(models=models or (entry_of(),))


def profile_of(mode: str = "rag") -> RequestProfile:
    return RequestProfile(mode=mode, complexity="low", needs_tools=False, needs_stream=False)


def iso_at(seconds_from_now: float) -> str:
    return usage_module._iso_utc(FIXED_NOW + timedelta(seconds=seconds_from_now))


def record_at(seconds_from_now: float, **overrides) -> UsageRecord:
    """窗口用例的一行：默认「成功、主选、非关页」，只改测试关心的那一维。"""
    data: dict = {
        "trace_id": f"t{-int(abs(seconds_from_now))}",
        "request_id": "r-1",
        "route_mode": "rag",
        "route_reason": ("CAPABILITY_MATCH", "LOCAL_PREFERRED"),
        "provider": "ollama",
        "model": "fb-a-model",
        "fallback_index": 0,
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "latency_ms": 100.0,
        "success": True,
        "error_type": None,
        "status_code": None,
        "created_at": iso_at(seconds_from_now),
    }
    data.update(overrides)
    return UsageRecord(**data)


def attempt(model_id: str = "fb-a", result: str = "success", error_type: str | None = None,
            latency_ms: float = 100.0, provider: str = "ollama") -> Attempt:
    return Attempt(model_id, provider, result, error_type, latency_ms)


def candidate_of(**overrides) -> RouteCandidate:
    """一个计划面候选（§5 的 `RouteCandidate`）：条目 + 打分 + 候选自己的理由码。"""
    data: dict = {"model": entry_of(), "score": 10,
                  "reason_codes": ("CAPABILITY_MATCH", "LOCAL_PREFERRED")}
    data.update(overrides)
    return RouteCandidate(**data)


def plan_of(*candidates: RouteCandidate, reason_codes: tuple[str, ...] = (
        "CAPABILITY_MATCH", "HIGHER_PRIORITY", "LOCAL_PREFERRED")) -> RoutePlan:
    """一份 `RoutePlan`：首枚是 primary，其余按顺序是 fallbacks。"""
    pool = candidates or (candidate_of(),)
    return RoutePlan(primary=pool[0], fallbacks=pool[1:], reason_codes=reason_codes)


class _ModelRouteFixture(unittest.TestCase):
    """`model_route` 一族的公共零件：一条真计划 + 一份真执行回执。"""

    def plan(self, *candidates: RouteCandidate) -> RoutePlan:
        return plan_of(*candidates)

    def result(self, **overrides) -> FallbackResult:
        data: dict = {
            "response": LLMResponse(content=LONG_PROMPT, model="fb-a-model",
                                    provider="ollama"),
            "attempts": (attempt("fb-a", "failed", "retryable", 120.0),
                         attempt("fb-b", "success", None, 300.0)),
            "selected_index": 1,
            "reason_codes": ("CAPABILITY_MATCH", "LOCAL_PREFERRED",
                             "NOT_A_CODE", "FALLBACK_AFTER_TIMEOUT"),
            "budget_ms": 30000.0,
            "context_dropped": 1,
        }
        data.update(overrides)
        return FallbackResult(**data)

    def profile(self, **overrides) -> RequestProfile:
        data: dict = {"mode": "rag", "complexity": "medium", "needs_tools": False,
                      "needs_stream": True, "needs_reasoning": False}
        data.update(overrides)
        return RequestProfile(**data)


class _UsageFixture(unittest.TestCase):
    """临时库 + 冻结时钟 + 假 settings + 熔断/注册表/健康缓存复位。"""

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "conversations.db"
        usage_module.reset_usage_state()
        self.addCleanup(usage_module.reset_usage_state)
        reset_registry()
        self.addCleanup(reset_registry)
        health_module.reset_health_cache()
        self.addCleanup(health_module.reset_health_cache)
        fallback_module.reset_circuit_breakers()
        self.addCleanup(fallback_module.reset_circuit_breakers)
        clock = mock.patch.object(usage_module, "_now", lambda: FIXED_NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.sink_records: list[UsageRecord] = []
        previous = llm.set_usage_sink(self.sink_records.append)
        self.addCleanup(lambda: llm.set_usage_sink(previous))
        self.use_settings()
        usage_module.init_usage_db(self.db_path)
        # 注册表是**夹具的责任**，不是运行目录的巧合（评审 I-5）：`providers` / `breaker`
        # 两面与 `model`/`cost` 的条目匹配都要读它，而 `settings.llm_registry_file` 是相对
        # 路径——不注入时从 `backend/` 跑绿、从仓库根跑红（`RegistryError` ⇒ 名字面塌空）。
        # 条目故意取一个**不与账本行同名**的 model：`record_at()` 默认写 `fb-a-model`，
        # 若这里注入同名条目，牌价匹配会凭空生效，红 1 那族「调用方自带成本」的用例就
        # 测不到它本要测的第 ② 支了。provider 必须是 `ollama`：两例聚合断言的就是它。
        self.use_registry(entry_of(id="usage-fixture-entry",
                                   provider="ollama",
                                   model="usage-fixture-model"))

    def use_settings(self, **overrides) -> Settings:
        fake = make_settings(**overrides)
        for module in (usage_module, fallback_module, llm, knowledge_os_module,
                       registry_module, health_module):
            patcher = mock.patch.object(module, "settings", fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.settings = fake
        return fake

    def raw_rows(self) -> list[dict]:
        """绕过聚合直读全列：断言的是「库里到底存了什么」。"""
        connection = sqlite3.connect(self.db_path)
        try:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(
                f"SELECT * FROM {usage_module.TABLE_NAME} ORDER BY id")]
        finally:
            connection.close()

    def use_registry(self, *models: ModelDefinition) -> Registry:
        registry = registry_of(*models)
        for module in (usage_module, llm):
            patcher = mock.patch.object(module, "get_registry", lambda: registry)
            patcher.start()
            self.addCleanup(patcher.stop)
        return registry

    def no_probes(self) -> None:
        """本类里不打网络的 providers 视图：探针本身另有专测组。"""
        def fake_view(registry):
            return {name: {"healthy": True}
                    for name in usage_module._provider_names(registry)}
        patcher = mock.patch.object(usage_module, "provider_health_view", fake_view)
        patcher.start()
        self.addCleanup(patcher.stop)


# ==========================================================================
# 1. §8 冻结面
# ==========================================================================
class UsageSchemaTests(_UsageFixture):
    def test_table_has_the_frozen_nineteen_columns_in_order(self):
        connection = sqlite3.connect(self.db_path)
        try:
            shipped = tuple(row[1] for row in connection.execute(
                f"PRAGMA table_info({usage_module.TABLE_NAME})"))
        finally:
            connection.close()                               # Windows：不关就删不掉临时目录
        self.assertEqual(SPEC_COLUMNS, shipped)
        # 三方等式：DDL ↔ §8 常量 ↔ `UsageRecord` 字段序。任何一侧长/删/换序都红。
        self.assertEqual(SPEC_COLUMNS, tuple(f.name for f in fields(UsageRecord)))
        self.assertEqual(19, len(shipped))
        for forbidden in ("prompt", "messages", "context", "reasoning", "api_key",
                          "authorization"):
            self.assertNotIn(forbidden, shipped)

    def test_init_is_idempotent_and_creates_the_missing_parent_directory(self):
        nested = self.db_path.parent / "deeper" / "still" / "conversations.db"
        self.assertFalse(nested.exists())
        usage_module.init_usage_db(nested)
        usage_module.init_usage_db(nested)                       # IF NOT EXISTS：第二次不炸
        self.assertTrue(nested.is_file())
        self.assertTrue(nested.parent.is_dir())
        usage_module.init_usage_db(self.db_path)                 # 复位到本用例的库

    def test_a_record_round_trips_through_every_column(self):
        usage_module.log_usage(record_at(
            -5, ttft_ms=123.5, estimated_cost=0.004, currency="USD",
            fallback_index=2, error_type="retryable:503", status_code=503,
            route_reason=("CAPABILITY_MATCH", "PRIMARY_UNHEALTHY", "CIRCUIT_OPEN")))
        rows = self.raw_rows()
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual(["CAPABILITY_MATCH", "PRIMARY_UNHEALTHY", "CIRCUIT_OPEN"],
                         json.loads(row["route_reason"]))          # §8：码数组 JSON
        self.assertEqual(("t-5", "r-1", "rag", "ollama", "fb-a-model"),
                         (row["trace_id"], row["request_id"], row["route_mode"],
                          row["provider"], row["model"]))
        self.assertEqual((2, 10, 5, 15, 123.5, 100.0, 0.004, "USD"),
                         (row["fallback_index"], row["input_tokens"], row["output_tokens"],
                          row["total_tokens"], row["ttft_ms"], row["latency_ms"],
                          row["estimated_cost"], row["currency"]))
        self.assertEqual(("retryable:503", 503, iso_at(-5), 1),
                         (row["error_type"], row["status_code"], row["created_at"],
                          row["success"]))
        self.assertIsInstance(row["id"], int)                      # 自增主键交给 SQLite

    def test_database_path_shares_the_conversation_store_source(self):
        """§8：账建在**现有** `data/conversations.db`，所以路径必须同源。"""
        target = self.db_path.parent / "shared.db"
        with mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": str(target)}):
            usage_module.reset_usage_state()                      # 没有覆盖值 ⇒ 走 env
            self.assertEqual(ConversationStore().path, usage_module.database_path())
        usage_module.init_usage_db(self.db_path)

    def test_every_router_reason_code_survives_the_sink(self):
        """§5 的冻结枚举与 §8 的 `route_reason` 列必须**闭合**：router 那侧一枚码，账里
        就得原样出现一枚。少一枚 = router 新加的码被净化层吃掉，trace 与账本同时失去解释。

        反向的一半（越界码被丢弃）在 `test_long_chinese_prompt_never_survives_any_column`
        里钉；`PRIMARY_UNHEALTHY` 的措辞与 router 同源（`app/llm/router.py` 是它的出处，
        本测试不重述词表，只等式引用 `REASON_CODES`）。
        """
        for index, code in enumerate(REASON_CODES):
            usage_module.log_usage(record_at(-(20 + index), trace_id=f"t-code-{index}",
                                             route_reason=(code,)))
        stored = [json.loads(row["route_reason"]) for row in self.raw_rows()]
        self.assertEqual([[code] for code in REASON_CODES], stored)

    def test_route_reason_codes_are_deduped_and_capped(self):
        """`_clean_codes` 的两件事都有测试（评审 Minor 2：曾经两件事**零测试**，内存变异
        「去掉去重 + 去掉上限」存活）。

        - **按首次出现去重**：同一枚码出现两次是某处 concat 写错的信号（计划面 + 执行面
          各带一份），一列 JSON 里躺两枚 `CAPABILITY_MATCH` 既没信息又撑大长度。
        - **上限 = §5 枚举基数**：历史上这里是硬编码的 12，而枚举只有 9 枚 ⇒ 上限永不
          生效（死码）。改成 `len(REASON_CODES)` 之后两者由同一个出处决定，所以本例同时
          钉住「上限等于枚举基数」与「截断这一支是活代码」——后者靠把枚举面暂时放宽来
          触发：真实的 §5 枚举去重后不可能超过 9 枚，能超过的唯一途径是枚举自己扩了。
        """
        kept = usage_module._clean_codes(
            ("CAPABILITY_MATCH", "LOCAL_PREFERRED", "CAPABILITY_MATCH",
             "NOT_A_CODE", "LOCAL_PREFERRED", "CIRCUIT_OPEN"))
        self.assertEqual(("CAPABILITY_MATCH", "LOCAL_PREFERRED", "CIRCUIT_OPEN"), kept)
        # 上限与 §5 同源（9 枚），不是另一处魔数。
        self.assertEqual(len(usage_module.REASON_CODES), usage_module.ROUTE_REASON_MAX_ITEMS)
        self.assertEqual(list(REASON_CODES),
                         list(usage_module._clean_codes(tuple(REASON_CODES) * 3)))
        # 截断那一支必须是**活**代码：把合法码面临时放宽到 2 倍，超出上限的部分被砍掉，
        # 且砍的是尾部（保留首次出现序）——去掉 `[:ROUTE_REASON_MAX_ITEMS]` 这条就红。
        widened = tuple(f"CODE_{index}" for index
                        in range(usage_module.ROUTE_REASON_MAX_ITEMS * 2))
        with mock.patch.object(usage_module, "_REASON_CODES", frozenset(widened)):
            capped = usage_module._clean_codes(widened)
        self.assertEqual(usage_module.ROUTE_REASON_MAX_ITEMS, len(capped))
        self.assertEqual(widened[:usage_module.ROUTE_REASON_MAX_ITEMS], tuple(capped))
        # 落库那一头：越界码整枚丢弃，不截断成半个词。
        usage_module.log_usage(record_at(-5, route_reason=("CAPABILITY_MATCH",)))
        self.assertEqual(["CAPABILITY_MATCH"],
                         json.loads(self.raw_rows()[0]["route_reason"]))

    def test_success_is_stored_as_an_int_and_optionals_stay_null(self):
        usage_module.log_usage(record_at(-3, success=True))
        usage_module.log_usage(record_at(-4, success=False, error_type="config",
                                         status_code=401, ttft_ms=None))
        first, second = self.raw_rows()
        self.assertEqual(1, first["success"])
        self.assertEqual(0, second["success"])
        self.assertIsNone(first["error_type"])
        self.assertIsNone(first["status_code"])
        self.assertIsNone(first["ttft_ms"])
        self.assertIsNone(second["ttft_ms"])


# ==========================================================================
# 2. 禁存项反测试（D3）
# ==========================================================================
class ForbiddenContentTests(_UsageFixture):
    def test_long_chinese_prompt_never_survives_any_column(self):
        """把 prompt 掺进**每一个**字符串列，落库后 `SELECT *` 全列扫 0 命中。

        这是 brief 点名的反测试：生产者（未来任何一条链）把用户问题塞进 `model` /
        `error_type` / `route_reason` 时，净化层整值丢弃而不是截断保留——截断留着前缀
        照样能把原文的头几十字带进库。
        """
        usage_module.log_usage(record_at(
            -7,
            trace_id=LONG_PROMPT,
            request_id=LONG_PROMPT[:40],
            route_mode=LONG_PROMPT[:8],
            provider=LONG_PROMPT[:8],
            model=LONG_PROMPT,                                    # provider 回显带原文
            error_type=f"上游 500：{LONG_PROMPT}",
            currency=LONG_PROMPT[:6],
            route_reason=(LONG_PROMPT[:10], "CAPABILITY_MATCH", "NOT_A_CODE"),
        ))
        rows = self.raw_rows()
        self.assertEqual(1, len(rows))
        for column, value in rows[0].items():
            text = str(value)
            for probe in (LONG_PROMPT[:12], LONG_PROMPT[-12:], "保密协议", "违约金"):
                self.assertNotIn(probe, text, f"{column} 列泄出了 prompt 片段")
        self.assertNotIn("保密协议", repr(rows))
        # 丢弃之后仍是一行合法的账：错误位被 `unknown` 占住，字符集列回到空值。
        self.assertEqual("unknown", rows[0]["error_type"])
        self.assertEqual("", rows[0]["model"])
        self.assertEqual(["CAPABILITY_MATCH"], json.loads(rows[0]["route_reason"]))
        self.assertIsNone(rows[0]["trace_id"])

    def test_error_type_only_admits_machine_codes(self):
        accepted = ("retryable", "config", "hard", "model_unavailable", "client_aborted",
                    "unknown", "hard:400", "retryable:429", "hard:no_fallback")
        for index, code in enumerate(accepted):
            usage_module.log_usage(record_at(-(100 + index), success=False, error_type=code))
        self.assertEqual(list(accepted),
                         [row["error_type"] for row in self.raw_rows()])

    def test_error_type_rejects_human_text_and_is_length_capped(self):
        rejected = (
            'Traceback (most recent call last): File "app/llm/usage.py", line 1',
            f"LLMError: retryable 503 上游暂时不可用：{{\"error\":\"{LONG_PROMPT[:60]}\"}}",
            "RETRYABLE", "retryable:503 body=boom", "hard: 400", "model_unavailable " * 40,
        )
        for index, value in enumerate(rejected):
            usage_module.log_usage(record_at(-(200 + index), success=False, error_type=value))
        stored = [row["error_type"] for row in self.raw_rows()]
        self.assertEqual(["unknown"] * len(rejected), stored)
        self.assertTrue(all(len(code) <= usage_module.ERROR_TYPE_MAX_CHARS
                            for code in stored))

    def test_the_error_type_suffix_and_the_status_column_share_one_domain(self):
        """`kind:<状态码>` 后缀与 `status_code` 列**必须**收同一个区间（评审 Minor 3）。

        历史上两件套不一致：正则只放行 1..3 位数字，而 `_status_code` 收到 0..1000。
        于是 `retryable:1000` 这一条合法组合被整值判死成 `unknown`——**白丢一格信息**，
        而且是最贵的那一格（状态码）。修法不是把某一侧随手挪一位，而是把定义域抽成
        `_status_in_range()` 给两处共用：能进 `status_code` 列的数就能写进后缀，反之两边
        都不收。这里的四个数就是围着这条边界选的：999（两侧都收）、1000（列收 ⇒ 后缀
        也必须收）、1001（两侧都拒）、以及 `no_fallback` 那个非数字后缀（不走区间判定）。
        """
        cases = (("retryable:999", "retryable:999", 999),
                 ("retryable:1000", "retryable:1000", 1000),
                 ("hard:1001", "unknown", None),
                 ("hard:99999", "unknown", None),
                 ("config:no_fallback", "config:no_fallback", None))
        for index, (supplied, expected, status) in enumerate(cases):
            with self.subTest(error_type=supplied):
                usage_module.log_usage(record_at(-(300 + index), success=False,
                                                 error_type=supplied,
                                                 status_code=status))
        stored = [(row["error_type"], row["status_code"]) for row in self.raw_rows()]
        self.assertEqual([("retryable:999", 999), ("retryable:1000", 1000),
                          ("unknown", None), ("unknown", None),
                          ("config:no_fallback", None)], stored)
        # trace 的 attempt 位与账本用**同一个**净化函数：同一枚码在两处必须是同一个词。
        self.assertEqual(
            ["retryable:999", "retryable:1000", "unknown", "unknown",
             "config:no_fallback"],
            [usage_module._trace_error_code(code) for code, _, _ in cases])

    def test_error_message_canary_from_a_failed_response_never_reaches_the_table(self):
        """Task 2 评审 M-7 的落地面：存 `kind` + `status_code`，不存 `str(LLMError)`。"""
        body_canary = "UPSTREAM_BODY_CANARY_分配失败_" + LONG_PROMPT[:20]
        error = LLMError("hard", 400, f"请求不被接受：{body_canary}")
        record = llm._usage_from_failure(error, profile_of(), "rag",
                                         trace_id="t-1", request_id="r-1")
        self.assertEqual("hard", record.error_type)
        self.assertEqual(400, record.status_code)
        usage_module.log_usage(record)
        stored = repr(self.raw_rows())
        self.assertNotIn(body_canary, stored)
        self.assertNotIn("请求不被接受", stored)

    def test_numbers_out_of_range_are_clamped_and_bad_identifiers_dropped(self):
        usage_module.log_usage(record_at(
            -9, input_tokens=-7, output_tokens="n/a", total_tokens=1e9,
            latency_ms=-1.0, ttft_ms=float("nan"), fallback_index=99999,
            status_code=70000, provider="Ollama Prod http://x.test"))
        row = self.raw_rows()[0]
        self.assertEqual((0, 0, 1000000000, 0.0, 0.0, 99999, None, ""),
                         (row["input_tokens"], row["output_tokens"], row["total_tokens"],
                          row["latency_ms"], row["ttft_ms"], row["fallback_index"],
                          row["status_code"], row["provider"]))

    def test_currency_follows_the_registry_and_rejects_arbitrary_text(self):
        """币种的两个方向：匹到条目就以**牌价币种**为准，匹不到就是空串。"""
        self.use_registry(entry_of())                              # pricing.currency = USD
        usage_module.log_usage(record_at(-9, currency="金本位"))     # 入参不合字符集 ⇒ 弃用
        usage_module.log_usage(record_at(-10, model="ghost-model"))  # 匹不到条目
        matched, unmatched = self.raw_rows()
        self.assertEqual("USD", matched["currency"])
        self.assertEqual("", unmatched["currency"])


# ==========================================================================
# 3. 关页（client_aborted）语义
# ==========================================================================
class ClientAbortTests(_UsageFixture):
    def test_aborted_row_is_written_as_client_aborted(self):
        """流式 commit 后关页：`success=False` 且没有 provider 归类 ⇒ 既有列的合法值。

        这一支成立的**前提**是有交付事实：`record_at()` 默认 `fallback_index=0` +
        `input/output = 10/5`，即「候选选中过、内容吐过字」——正是 §8.1 第 2 条里
        「消费方在 commit 之后离开」的形状。没有那半截事实的失败行见下一例。
        """
        usage_module.log_usage(record_at(-5, success=False, error_type=None))
        row = self.raw_rows()[0]
        self.assertEqual(usage_module.ERROR_TYPE_CLIENT_ABORTED, row["error_type"])
        self.assertEqual(0, row["success"])

    def test_a_failure_row_without_error_type_is_not_silently_called_an_abort(self):
        """**没有交付事实**的失败行不许被反推成关页（§8.1 第 2 条，评审 I-4）。

        判据曾经只是「`success=False ∧ error_type` 缺失」，也就是**从缺席推**——而生产者
        漏填归类的全链失败行恰好就是这个形状（`fallback_index=-1`、token 全 0：一次内容
        都没到用户手上）。后果不是「数字不好看」：`client_aborted` 会被 `success_rate`
        的分子与分母**同时**剔走，于是一次真实故障在 status 页读成「1.0 的用户关页 +
        零失败样本」，运维连「有东西坏了」都看不出来。收窄后它落 `unknown` 并留在分母里。
        """
        for label, overrides in {
            "no_candidate_no_tokens": {"fallback_index": -1, "input_tokens": 0,
                                       "output_tokens": 0},
            "candidate_chosen_but_nothing_generated": {"fallback_index": 1,
                                                       "input_tokens": 0,
                                                       "output_tokens": 0},
            "tokens_but_no_candidate": {"fallback_index": -1, "input_tokens": 40,
                                        "output_tokens": 12},
        }.items():
            with self.subTest(case=label):
                usage_module.log_usage(record_at(-5, trace_id=f"t-{label}",
                                                 success=False, error_type=None,
                                                 **overrides))
        self.no_probes()
        rows = self.raw_rows()
        self.assertEqual(3, len(rows))
        self.assertEqual(["unknown"] * 3, [row["error_type"] for row in rows])
        # 库里仍是失败行 ⇒ 它进 `success_rate` 的分母（三行全失败 = 0.0，不是 None）。
        block = usage_module.aggregate_status(window_s=300)
        self.assertEqual(3, block["requests_5m"])
        self.assertEqual(0.0, block["success_rate"])
        self.assertEqual(0.0, block["aborted_rate"])                # 没有一行算关页
        # 反证：同一形状**加上**交付事实才配得上 `client_aborted`，那时它才两头剔除。
        usage_module.log_usage(record_at(-6, trace_id="t-delivered", success=False,
                                         error_type=None, fallback_index=1,
                                         input_tokens=30, output_tokens=90))
        delivered = [row for row in self.raw_rows() if row["trace_id"] == "t-delivered"]
        self.assertEqual([usage_module.ERROR_TYPE_CLIENT_ABORTED],
                         [row["error_type"] for row in delivered])
        after = usage_module.aggregate_status(window_s=300)
        self.assertEqual(4, after["requests_5m"])
        self.assertEqual(0.0, after["success_rate"])                # 3 失败 / 3 计入
        self.assertEqual(0.25, after["aborted_rate"])               # 1/4

    def test_a_producer_written_client_aborted_still_needs_the_delivery_fact(self):
        """两枚哨兵是**账本的产物**，生产者自写一律不认（复审 N1 的补闸）。

        上一例关的是「从缺席反推」那一支，但显式值那一支当时是敞的：把
        `error_type="client_aborted"` 直接写进 `log_usage` 会照原样入库（它是
        `_ERROR_TYPE_PATTERN` 的合法值），于是 §8.1 第 2 条要防的那次误读换一条路就能
        复现——`unknown` 那侧有闸、这侧没有，两半不对称。今天没有生产者会写这个词
        （provider 的 kind 只有四值），但账本对 T6/T7/T8 三条链公开着这个写入口。
        成功行是同一个洞的另一个形状：`scored_rows` 按 `error_type` 剔行，一枚贴在
        `success=True` 上的 `client_aborted` 会把一次真实成功从分子与分母一起请走。
        """
        abort = usage_module.ERROR_TYPE_CLIENT_ABORTED
        shapes = {
            "failure_no_delivery": {"success": False, "fallback_index": -1,
                                    "input_tokens": 0, "output_tokens": 0},
            "failure_with_delivery": {"success": False, "fallback_index": 1,
                                      "input_tokens": 30, "output_tokens": 90},
            "success_with_delivery": {"success": True, "fallback_index": 0,
                                      "input_tokens": 30, "output_tokens": 90},
        }
        for label, overrides in shapes.items():
            with self.subTest(case=label):
                usage_module.log_usage(record_at(-5, trace_id=f"t-{label}",
                                                 error_type=abort, **overrides))
        self.no_probes()
        rows = {row["trace_id"]: row for row in self.raw_rows()}
        self.assertEqual(3, len(rows))
        self.assertEqual(["unknown", abort, "unknown"],
                         [rows[f"t-{label}"]["error_type"] for label in (
                             "failure_no_delivery",
                             "failure_with_delivery",        # 事实齐 ⇒ 这个哨兵才认
                             "success_with_delivery")])
        block = usage_module.aggregate_status(window_s=300)
        self.assertEqual(3, block["requests_5m"])
        # 两行 `unknown` 留在分母（一行成功一行失败 = 1/2），只有一行真关页被两头剔走。
        self.assertEqual(0.5, block["success_rate"])
        self.assertEqual(round(1 / 3, 4), block["aborted_rate"])

    def test_provider_failure_keeps_its_kind_and_success_rows_keep_null(self):
        usage_module.log_usage(record_at(-6, success=False, error_type="retryable",
                                         status_code=503))
        usage_module.log_usage(record_at(-7, success=True, error_type=None))
        failed, succeeded = self.raw_rows()
        self.assertEqual("retryable", failed["error_type"])
        self.assertIsNone(succeeded["error_type"])

    def test_the_aborted_value_is_a_column_value_not_a_new_column(self):
        """关页这条事实**没有**自己的列：它只能是 `error_type` 的一个合法取值。"""
        connection = sqlite3.connect(self.db_path)
        try:
            columns = [row[1] for row in connection.execute(
                f"PRAGMA table_info({usage_module.TABLE_NAME})")]
        finally:
            connection.close()
        self.assertNotIn("aborted", columns)
        self.assertNotIn("client_aborted", columns)

    def test_no_capable_model_writes_no_row_and_stays_out_of_the_denominator(self):
        """M3（Task 4 移交）：`NoCapableModelError` 在任何一次外呼**之前**抛出 ⇒ 没有
        attempt、没有账，于是它不进 `requests_5m` 的分母。

        把「路由没找到模型」算成「模型失败」，`success_rate` 就会为一条根本没发出的请求
        记账，而 D2 的降级（Agent fast-path / RAG 兜底文案）是**设计内**的出口，不是故障。
        它与关页那一支的共同点是：两支都不该进 success_rate 的分子——区别在于关页有一行
        真实执行过的事实要留（`client_aborted`），而零候选连一行都不该存在。
        """
        llm.set_usage_sink(None)                                   # 用真落库函数
        self.use_registry(entry_of())
        boom = NoCapableModelError(profile=profile_of("rag"), stage="health",
                                   reason_codes=("PRIMARY_UNHEALTHY",))
        with mock.patch.object(llm, "_plan", side_effect=boom):
            with self.assertRaises(NoCapableModelError):
                llm.complete([{"role": "user", "content": "你好"}], mode="rag")
        self.assertEqual([], self.raw_rows())
        self.no_probes()
        block = usage_module.aggregate_status(window_s=300)
        self.assertEqual(0, block["requests_5m"])
        self.assertIsNone(block["success_rate"])                   # 分母 0，不是 0.0


# ==========================================================================
# 4. 聚合正确性（窗口 / 四个率 / p95）
# ==========================================================================
class AggregateMathTests(_UsageFixture):
    def seed(self) -> None:
        self.no_probes()
        usage_module.log_usage(record_at(-10, latency_ms=100.0))
        usage_module.log_usage(record_at(-20, latency_ms=200.0, fallback_index=1))
        usage_module.log_usage(record_at(-30, latency_ms=300.0, success=False,
                                         error_type="retryable", status_code=503))
        usage_module.log_usage(record_at(-40, latency_ms=400.0, success=False))       # 关页
        usage_module.log_usage(record_at(-50, latency_ms=500.0))
        usage_module.log_usage(record_at(-60, latency_ms=600.0, success=False))       # 关页
        usage_module.log_usage(record_at(-70, latency_ms=700.0, success=False,
                                         error_type="hard", status_code=400))
        usage_module.log_usage(record_at(-80, latency_ms=800.0, fallback_index=2))
        usage_module.log_usage(record_at(-90, latency_ms=900.0))
        usage_module.log_usage(record_at(-4000, latency_ms=1000.0))                   # 窗口外

    def test_window_rates_and_p95_on_ten_seeded_rows(self):
        self.seed()
        block = usage_module.aggregate_status(window_s=300)
        self.assertEqual(AGGREGATE_KEYS, set(block))
        self.assertEqual(9, block["requests_5m"])                 # 第 10 行在窗口外
        # 关页 2 行从分子分母同时剔除：5 成功 / (9 - 2)
        self.assertEqual(0.7143, block["success_rate"])
        self.assertEqual(0.2222, block["fallback_rate"])           # 2/9（分母=窗口全部行）
        self.assertEqual(0.2222, block["aborted_rate"])            # 2/9
        self.assertEqual(900.0, block["p95_latency_ms"])           # 最近秩 ceil(0.95*9)=9
        self.assertEqual({"ollama"}, set(block["providers"]))
        self.assertEqual({"healthy"}, set(block["providers"]["ollama"]))
        self.assertEqual({"ollama"}, set(block["breaker"]))
        self.assertEqual({"state"}, set(block["breaker"]["ollama"]))

    def test_aborted_rows_would_otherwise_poison_the_success_rate(self):
        """反证：算进分母是 5/9、只剔分子会凑出别的数；0.7143 才是「两头都剔」。"""
        self.seed()
        rate = usage_module.aggregate_status(window_s=300)["success_rate"]
        self.assertNotEqual(round(5 / 9, 4), rate)                 # 分母含关页 ⇒ 错
        self.assertNotEqual(round(7 / 9, 4), rate)                 # 只剔分子 ⇒ 错

    def test_empty_denominators_are_none_not_zero(self):
        self.no_probes()
        block = usage_module.aggregate_status(window_s=300)
        self.assertEqual({"requests_5m": 0, "success_rate": None, "fallback_rate": None,
                          "aborted_rate": None, "p95_latency_ms": None},
                         {key: block[key] for key in
                          ("requests_5m", "success_rate", "fallback_rate", "aborted_rate",
                           "p95_latency_ms")})

    def test_all_aborted_window_has_no_success_samples_at_all(self):
        self.no_probes()
        usage_module.log_usage(record_at(-5, success=False))
        usage_module.log_usage(record_at(-6, success=False))
        block = usage_module.aggregate_status(window_s=300)
        self.assertEqual(2, block["requests_5m"])
        self.assertIsNone(block["success_rate"])                  # 分母 0 ⇒ None
        self.assertEqual(1.0, block["aborted_rate"])

    def test_window_boundary_is_inclusive_at_the_cutoff(self):
        self.no_probes()
        usage_module.log_usage(record_at(-300, latency_ms=1.0))    # 恰好压线 ⇒ 在窗口内
        usage_module.log_usage(record_at(-301, latency_ms=2.0))    # 早一秒 ⇒ 窗口外
        self.assertEqual(1, usage_module.aggregate_status(window_s=300)["requests_5m"])
        self.assertEqual(2, usage_module.aggregate_status(window_s=400)["requests_5m"])

    def test_p95_reports_a_single_sample_instead_of_hiding_it(self):
        self.no_probes()
        usage_module.log_usage(record_at(-5, latency_ms=421.0))
        self.assertEqual(421.0, usage_module.aggregate_status()["p95_latency_ms"])

    def test_p95_keeps_the_aborted_rows_because_latency_is_real(self):
        """延迟面**不**剔关页：它量的是「用户等了多久」，关页之前也是真实等待。"""
        self.no_probes()
        usage_module.log_usage(record_at(-5, latency_ms=100.0, success=False))
        self.assertEqual(100.0, usage_module.aggregate_status()["p95_latency_ms"])

    def test_disabled_router_does_not_touch_the_database_or_the_probes(self):
        self.use_settings(llm_router_enabled=False)
        with (mock.patch.object(usage_module, "_fetch_window") as fetch,
              mock.patch.object(usage_module, "provider_health_view") as probes):
            block = usage_module.aggregate_status(window_s=300)
        fetch.assert_not_called()
        probes.assert_not_called()
        self.assertEqual({"requests_5m": 0, "success_rate": None, "fallback_rate": None,
                          "aborted_rate": None, "p95_latency_ms": None, "providers": {},
                          "breaker": {}}, block)


# ==========================================================================
# 5. providers 的 1.5s 整轮预算 + breaker 面
# ==========================================================================
class SlowBreaker:
    def __init__(self, state: str) -> None:
        self._state = state

    @property
    def state(self) -> str:
        return self._state


class ProviderHealthBudgetTests(_UsageFixture):
    def setUp(self) -> None:
        super().setUp()
        self.use_registry(entry_of(id="fb-a", provider="ollama"),
                          entry_of(id="fb-o", provider="openai", model="gpt-x",
                                   external=True))

    def test_providers_come_from_the_health_view(self):
        with mock.patch.object(usage_module, "provider_health_view",
                               lambda registry: {"ollama": {"healthy": True},
                                                 "openai": {"healthy": False}}):
            block = usage_module.aggregate_status()
        self.assertEqual({"ollama": {"healthy": True}, "openai": {"healthy": False}},
                         block["providers"])

    def test_a_provider_that_is_actually_down_is_reported_as_down(self):
        """`healthy=False` 是探针跑完的**事实**，不许被 `unknown` 冒领。"""
        with mock.patch.object(usage_module, "provider_health_view",
                               lambda registry: {"ollama": {"healthy": False},
                                                 "openai": {"healthy": True}}):
            block = usage_module.aggregate_status()
        self.assertIs(False, block["providers"]["ollama"]["healthy"])

    def test_absent_from_the_view_is_unknown_not_false(self):
        with mock.patch.object(usage_module, "provider_health_view",
                               lambda registry: {"ollama": {"healthy": True}}):
            block = usage_module.aggregate_status()
        self.assertEqual({"ollama": {"healthy": True}, "openai": {"healthy": "unknown"}},
                         block["providers"])

    def test_health_budget_timeout_falls_back_to_unknown_without_hanging(self):
        release = threading.Event()

        def slow(_registry):
            release.wait(2.0)
            return {"ollama": {"healthy": True}, "openai": {"healthy": True}}

        started = time.perf_counter()
        with (mock.patch.object(usage_module, "HEALTH_BUDGET_MS", 20),
              mock.patch.object(usage_module, "provider_health_view", slow)):
            try:
                block = usage_module.aggregate_status()
                elapsed = time.perf_counter() - started
            finally:
                release.set()
        self.assertEqual({"ollama": {"healthy": "unknown"},
                          "openai": {"healthy": "unknown"}}, block["providers"])
        self.assertLess(elapsed, 0.5)                             # 预算生效，不等那 2 秒

    def test_timeout_then_next_round_reads_the_probe_cache(self):
        """慢 provider 的退路：这一轮 unknown，**探针不取消**；它跑完落进 60s 缓存。

        两次 timeout 之间再调一次 status，必须**不再**排第二轮（在飞去重），否则一个慢
        provider 会被 status 的手动刷新打成排队。缓存那一侧单独测：本轮拿不到新视图时，
        读到的就是上一轮留下的事实。
        """
        release = threading.Event()
        calls: list[int] = []

        def slow(_registry):
            calls.append(1)
            release.wait(2.0)
            health_module._health_cache["ollama"] = (health_module._now(), True)
            return {"ollama": {"healthy": True}, "openai": {"healthy": True}}

        with (mock.patch.object(usage_module, "HEALTH_BUDGET_MS", 20),
              mock.patch.object(usage_module, "provider_health_view", slow)):
            first = usage_module.aggregate_status()["providers"]
            self.assertEqual("unknown", first["ollama"]["healthy"])
            usage_module.aggregate_status()                       # 在飞 ⇒ 不排第二轮
            usage_module.aggregate_status()
            self.assertEqual([1], calls)
            release.set()
            for _ in range(100):                                  # 等后台那一轮落地
                if "ollama" in health_module._health_cache:
                    break
                time.sleep(0.01)
        self.assertIn("ollama", health_module._health_cache)       # 没被取消，事实留下了
        with mock.patch.object(usage_module, "_submit_probe", lambda registry: None):
            cached = usage_module.aggregate_status()["providers"]
        self.assertIs(True, cached["ollama"]["healthy"])
        self.assertEqual("unknown", cached["openai"]["healthy"])

    def test_only_one_probe_round_is_in_flight(self):
        release = threading.Event()
        calls: list[int] = []

        def slow(_registry):
            calls.append(1)
            release.wait(2.0)
            return {"ollama": {"healthy": True}}

        with (mock.patch.object(usage_module, "HEALTH_BUDGET_MS", 10),
              mock.patch.object(usage_module, "provider_health_view", slow)):
            try:
                usage_module.aggregate_status()
                usage_module.aggregate_status()
                usage_module.aggregate_status()
            finally:
                release.set()
        self.assertEqual([1], calls)                              # 慢探针不排队、不堆线程

    def test_stale_cache_until_its_ttl_then_unknown(self):
        """缓存里还留着的用缓存，过了 60s TTL 的宁缺毋滥（`unknown`）。"""
        health_module._health_cache["ollama"] = (health_module._now(), False)
        health_module._health_cache["openai"] = (
            health_module._now() - health_module.HEALTH_CACHE_TTL_SECONDS - 1.0, True)
        with (mock.patch.object(usage_module, "HEALTH_BUDGET_MS", 10),
              mock.patch.object(usage_module, "provider_health_view",
                                lambda registry: (_ for _ in ()).throw(RuntimeError("炸了")))):
            with self.assertLogs("app.llm.usage", level="WARNING"):
                providers = usage_module.aggregate_status()["providers"]
        self.assertIs(False, providers["ollama"]["healthy"])        # 缓存里还有
        self.assertEqual("unknown", providers["openai"]["healthy"])   # 陈旧 ⇒ 不冒领

    def test_an_open_breaker_never_leaks_into_the_healthy_face(self):
        """D4（Task 3 移交）：`providers.healthy` **只**来自 probe（60s 缓存），熔断态另开
        `breaker` 一键，两键互不渗透。

        混起来的后果不是「数字不好看」，而是两个语义相反的东西被写成同一个词：熔断是
        「这个 provider 通着，但我暂时不派活」，不健康是「根本不通」。前者是 router 的
        两道门（`routing_health_view` 里 `healthy` 与 `circuit_open` 分列），后者是运维
        判断要不要去查 Ollama 的唯一依据。
        """
        with mock.patch.object(usage_module, "provider_health_view",
                               lambda registry: {"ollama": {"healthy": True},
                                                 "openai": {"healthy": True}}):
            with mock.patch.dict(fallback_module.BREAKERS,
                                 {"ollama": SlowBreaker("open")}, clear=True):
                block = usage_module.aggregate_status()
        self.assertIs(True, block["providers"]["ollama"]["healthy"])
        self.assertIs(True, block["providers"]["openai"]["healthy"])
        self.assertEqual({"ollama": {"state": "open"},
                          "openai": {"state": "closed"}}, block["breaker"])
        # 两键的**值域**也不交叉：healthy 只有 bool/"unknown"，state 只有四枚熔断词。
        self.assertTrue(all(isinstance(v["healthy"], bool)
                            for v in block["providers"].values()))
        self.assertNotIn("healthy", block["breaker"]["ollama"])
        self.assertNotIn("state", block["providers"]["ollama"])

    def test_breaker_states_are_read_not_inferred_and_nothing_is_created(self):
        # 评审 Minor 12：这两例曾经没关探针，实测 `provider.probe` 被真调用 2 次——隔离
        # 靠的是 `ollama.test` 这个主机名解析失败（环境运气），不是测试自己的决定。
        # 聚合本身不测探针面（那是 `ProviderHealthBudgetTests` 前几例的事），这里关掉它。
        self.no_probes()
        with mock.patch.dict(fallback_module.BREAKERS,
                             {"ollama": SlowBreaker("open"),
                              "openai": SlowBreaker("half_open")}, clear=True):
            block = usage_module.aggregate_status()["breaker"]
        self.assertEqual({"ollama": {"state": "open"},
                          "openai": {"state": "half_open"}}, block)
        with mock.patch.dict(fallback_module.BREAKERS, {}, clear=True):
            block = usage_module.aggregate_status()["breaker"]
            self.assertEqual({"ollama": {"state": "closed"},
                              "openai": {"state": "closed"}}, block)
            self.assertEqual({}, fallback_module.BREAKERS)          # 观测不创建熔断器

    def test_breaker_disabled_reports_closed_even_when_open(self):
        self.no_probes()                                      # 理由见上一例（Minor 12）
        self.use_settings(llm_breaker_enabled=False)
        with mock.patch.dict(fallback_module.BREAKERS, {"ollama": SlowBreaker("open")}):
            self.assertEqual({"ollama": {"state": "closed"}, "openai": {"state": "closed"}},
                             usage_module.aggregate_status()["breaker"])


# ==========================================================================
# 6. fail-open
# ==========================================================================
class FailOpenTests(_UsageFixture):
    def test_log_usage_swallows_every_database_error(self):
        with mock.patch.object(usage_module, "_connect",
                               side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertLogs("app.llm.usage", level="WARNING") as caught:
                self.assertIsNone(usage_module.log_usage(record_at(-5)))
        self.assertIn("fail-open", "".join(caught.output))

    def test_a_locked_database_cannot_break_the_generation_chain(self):
        """端到端：真 `log_usage` 当 sink、DB 被占用 ⇒ `llm.complete()` 照常交付内容。"""
        candidate = entry_of()
        self.use_registry(candidate)
        health_patcher = mock.patch.object(fallback_module, "routing_health_view",
                                           lambda *args, **kwargs: {})
        health_patcher.start()
        self.addCleanup(health_patcher.stop)
        complete_patcher = mock.patch.object(
            provider_module, "complete",
            lambda model, req, timeout: LLMResponse(content="答", model=model.model,
                                                    provider=model.provider))
        complete_patcher.start()
        self.addCleanup(complete_patcher.stop)
        llm.set_usage_sink(None)                                   # 用真的落库函数
        with mock.patch.object(usage_module, "_connect",
                               side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertLogs("app.llm.usage", level="WARNING"):
                result = llm.complete([{"role": "user", "content": "你好"}], mode="chat")
        self.assertEqual("答", result.response.content)
        self.assertEqual([], self.raw_rows())                      # 一行都没写成

    def test_aggregate_degrades_to_an_empty_block_when_the_read_fails(self):
        self.no_probes()
        usage_module.log_usage(record_at(-5))
        with mock.patch.object(usage_module, "_query",
                               side_effect=sqlite3.OperationalError("database is locked")):
            block = usage_module.aggregate_status()
        self.assertEqual(0, block["requests_5m"])
        self.assertIsNone(block["success_rate"])
        self.assertEqual({"ollama": {"healthy": True}}, block["providers"])  # 探针面照旧

    def test_aggregate_swallows_its_own_bug_and_still_returns_the_empty_shape(self):
        """外层兜底：聚合内部**任何**异常（含非 sqlite 的编程错）都不许冒到端点。"""
        with mock.patch.object(usage_module, "_metrics_of",
                               side_effect=ValueError("聚合口径写错了")):
            with self.assertLogs("app.llm.usage", level="WARNING"):
                block = usage_module.aggregate_status()
        self.assertEqual(AGGREGATE_KEYS, set(block))
        self.assertEqual(0, block["requests_5m"])
        self.assertIsNone(block["success_rate"])

    def test_missing_table_reads_as_an_empty_window(self):
        """表还不存在（fresh 部署、没走 warmup）⇒ 空窗口，不炸也**不**顺手建表。"""
        self.no_probes()
        virgin = str(self.db_path.parent / "virgin.db")
        closed = sqlite3.connect(virgin)
        closed.close()
        usage_module._state["db_path"] = Path(virgin)
        usage_module._state["schema_ready"] = True                # 假装早已建过表
        self.assertEqual(0, usage_module.aggregate_status()["requests_5m"])
        probe = sqlite3.connect(virgin)
        try:
            tables = [row[0] for row in probe.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
        finally:
            probe.close()
        self.assertEqual([], tables)
        usage_module._state["db_path"] = self.db_path

    def test_broken_registry_still_reports_the_rates(self):
        """注册表不可用只影响 providers/breaker 的名字面，率与延迟照样聚合。"""
        self.no_probes()
        usage_module.log_usage(record_at(-5))
        with (mock.patch.object(usage_module, "get_registry",
                                side_effect=RegistryError("注册表文件不可用")),
              self.assertLogs("app.llm.usage", level="WARNING")):
            block = usage_module.aggregate_status()
        self.assertEqual(1, block["requests_5m"])
        self.assertEqual(1.0, block["success_rate"])
        self.assertEqual({}, block["providers"])


# ==========================================================================
# 7. estimated_cost（牌价折算）
# ==========================================================================
class CostTests(_UsageFixture):
    def test_cost_comes_from_the_registry_pricing(self):
        self.use_registry(entry_of(id="fb-o", provider="openai", model="gpt-x",
                                   external=True,
                                   pricing={"input_per_1m": 2.0, "output_per_1m": 6.0,
                                            "currency": "CNY"}))
        usage_module.log_usage(record_at(-5, provider="openai", model="gpt-x",
                                         input_tokens=1_000_000, output_tokens=500_000,
                                         currency="USD"))
        row = self.raw_rows()[0]
        self.assertEqual(5.0, row["estimated_cost"])               # 2.0 + 3.0
        self.assertEqual("CNY", row["currency"])                   # 条目币种为准，不是入参

    def test_entry_id_and_effective_name_are_both_matchable(self):
        self.use_registry(entry_of(id="fb-a", model="fb-a-model",
                                   pricing={"input_per_1m": 1.0, "output_per_1m": 0.0,
                                            "currency": "USD"}))
        usage_module.log_usage(record_at(-5, model="fb-a-model", input_tokens=500_000,
                                         output_tokens=0))
        usage_module.log_usage(record_at(-6, model="fb-a", input_tokens=500_000,
                                         output_tokens=0))
        self.assertEqual([0.5, 0.5],
                         [row["estimated_cost"] for row in self.raw_rows()])

    def test_unknown_model_costs_zero_with_an_empty_currency(self):
        self.use_registry(entry_of())
        usage_module.log_usage(record_at(-5, model="ghost-model", provider="ollama",
                                         input_tokens=900, currency="USD"))
        row = self.raw_rows()[0]
        self.assertEqual((0.0, ""), (row["estimated_cost"], row["currency"]))

    def test_an_unmatched_entry_still_persists_the_callers_own_cost(self):
        """三分支的 **②**：匹不到条目 ⇒ 账本承载调用方算好的成本（§8 两列不许清零）。

        真实触发点是 D1 的 `{PROVIDER}_MODEL_OVERRIDE`（回显的是别名，注册表里查不到）、
        上游回显了注册表没声明的变体名、以及注册表自身读不到。静默把 0.004 折成 0.0 就是
        把账本里唯一有信息的那一位扔了——成本面 V2.6 要进决策路径，届时没人能补回这段历史。
        """
        self.use_registry(entry_of())                              # 只有 fb-a/fb-a-model
        usage_module.log_usage(record_at(-5, model="alias-not-in-registry",
                                         estimated_cost=0.004, currency="usd"))
        usage_module.log_usage(record_at(-6, model="alias-not-in-registry",
                                         estimated_cost=0.004))    # 币种沿用默认 USD
        alias, blanked = self.raw_rows()
        self.assertEqual((0.004, "USD"), (alias["estimated_cost"], alias["currency"]))
        self.assertEqual((0.004, "USD"), (blanked["estimated_cost"], blanked["currency"]))

    def test_the_registry_price_wins_over_a_supplied_cost(self):
        """**①**：匹到条目 ⇒ 牌价是权威，调用方自带多少成本都不认。

        一张表里两套价格来源时，聚合出来的总成本取决于「哪条链先写」——那是最难查的一类
        账务漂移。牌价唯一出处是 §3 的 `pricing`，所以它优先。
        """
        self.use_registry(entry_of(pricing={"input_per_1m": 2.0, "output_per_1m": 0.0,
                                            "currency": "CNY"}))
        usage_module.log_usage(record_at(-5, model="fb-a-model", input_tokens=500_000,
                                         output_tokens=0, estimated_cost=99.0,
                                         currency="USD"))
        row = self.raw_rows()[0]
        self.assertEqual((1.0, "CNY"), (row["estimated_cost"], row["currency"]))

    def test_branch_three_keeps_empty_currency_as_the_only_price_unknown_marker(self):
        """**③**：调用方「没给成本」的判据是 `estimated_cost <= 0`——它的默认值就是 0.0。

        负数 / NaN / Infinity 一律收成 0.0（坏值不许进成本列），且此时币种跟着回到空串：
        「USD 且 0 成本」与「免费」在库里就分不开了，而 §8 的口径是**空币种**才是
        「不知道牌价」的唯一标记。免费路因此与牌价未知的免费路同形，这是已记账的取舍。
        """
        self.use_registry(entry_of())
        for index, bad in enumerate((0.0, -1.0, float("nan"), float("inf"), "n/a", None)):
            usage_module.log_usage(record_at(-(10 + index), model="ghost-model",
                                             estimated_cost=bad, currency="USD"))
        rows = self.raw_rows()
        self.assertEqual(6, len(rows))
        self.assertEqual({(0.0, "")}, {(row["estimated_cost"], row["currency"])
                                       for row in rows})

    def test_a_supplied_cost_does_not_borrow_a_currency_it_cannot_prove(self):
        """②的币种那一半：`currency` 仍要过 ISO-4217 白名单，中文/超长即空串。"""
        self.use_registry(entry_of())
        usage_module.log_usage(record_at(-5, model="ghost-model", estimated_cost=0.004,
                                         currency=LONG_PROMPT[:3]))
        usage_module.log_usage(record_at(-6, model="ghost-model", estimated_cost=0.004,
                                         currency="美元金"))
        for row in self.raw_rows():
            self.assertEqual((0.004, ""), (row["estimated_cost"], row["currency"]))

    def test_the_provider_narrows_the_price_lookup_when_two_sides_share_a_name(self):
        """两个 provider 挂同一个模型名时，钥匙是 `provider` 列而不是模型名。

        真实形状：`qwen-plus` 既可能走 DashScope、也可能被某个网关同名转发；牌价差一个
        数量级。匹配少了 provider 这一维，账就会去套**声明序更靠前**的那条，于是本地免费
        路把云端账单折成 0——这是最不容易被发现的一类成本漂移。
        """
        self.use_registry(entry_of(id="loc-x", provider="ollama", model="qwen-plus"),
                          entry_of(id="cloud-x", provider="deepseek", model="qwen-plus",
                                   external=True,
                                   pricing={"input_per_1m": 4.0, "output_per_1m": 0.0,
                                            "currency": "CNY"}))
        usage_module.log_usage(record_at(-5, trace_id="t-local", provider="ollama",
                                         model="qwen-plus", input_tokens=1_000_000,
                                         output_tokens=0))
        usage_module.log_usage(record_at(-6, trace_id="t-cloud", provider="deepseek",
                                         model="qwen-plus", input_tokens=1_000_000,
                                         output_tokens=0))
        rows = {row["trace_id"]: row for row in self.raw_rows()}
        self.assertEqual((0.0, "USD"), (rows["t-local"]["estimated_cost"],
                                        rows["t-local"]["currency"]))
        self.assertEqual((4.0, "CNY"), (rows["t-cloud"]["estimated_cost"],
                                        rows["t-cloud"]["currency"]))
        self.assertEqual(("ollama", "deepseek"), (rows["t-local"]["provider"],
                                                  rows["t-cloud"]["provider"]))

    def test_bad_token_values_are_clamped_before_the_price_is_applied(self):
        """收口后的 token 才进牌价乘法：一条 `"n/a"` 不许把整行账炸掉。

        `log_usage` 的 fail-open 会吞下这个异常——但那意味着**丢一行账**，不是丢一点精度。
        观测面自身也不能成为故障源（与「只读库/坏路径不得影响生成」同一条 D3 对称）。
        """
        self.use_registry(entry_of(pricing={"input_per_1m": 2.0, "output_per_1m": 0.0,
                                            "currency": "USD"}))
        usage_module.log_usage(record_at(-5, model="fb-a-model", input_tokens="250000",
                                         output_tokens=None))
        row = self.raw_rows()[0]
        self.assertEqual((250000, 0), (row["input_tokens"], row["output_tokens"]))
        self.assertEqual((0.5, "USD"), (row["estimated_cost"], row["currency"]))

    def test_the_cost_survives_even_when_the_registry_is_unreadable(self):
        """注册表读不到只影响「能不能核对牌价」，不影响「能不能把已算出的成本留下」。"""
        usage_module.log_usage(record_at(-5, model="fb-a-model", estimated_cost=0.004,
                                         currency="USD"))
        with (mock.patch.object(usage_module, "get_registry",
                                side_effect=RegistryError("注册表文件不可用")),
              self.assertLogs("app.llm.usage", level="WARNING")):
            usage_module.log_usage(record_at(-6, model="fb-a-model", estimated_cost=0.008,
                                             currency="USD", trace_id="t-offline"))
        rows = {row["trace_id"]: row for row in self.raw_rows()}
        self.assertEqual((0.008, "USD"), (rows["t-offline"]["estimated_cost"],
                                          rows["t-offline"]["currency"]))


# ==========================================================================
# 8. `public_llm_status` 白名单（deny-by-default）
# ==========================================================================
class LlmStatusWhitelistTests(unittest.TestCase):
    CANARY = "apikey_" + "C" * 40

    def full_block(self, **overrides) -> dict:
        block = {
            "status": "ONLINE", "model": "fb-a-model", "provider": "ollama",
            "p50_ms": 410.0, "p95_ms": 900.0, "ttft_ms": 210.0,
            "requests_5m": 9, "success_rate": 0.7143, "fallback_rate": 0.2222,
            "aborted_rate": 0.2222, "p95_latency_ms": 900.0,
            "providers": {"ollama": {"healthy": True}, "openai": {"healthy": "unknown"}},
            "breaker": {"ollama": {"state": "open"}},
            # §8 之外的键：同前缀近邻 + 凭据形状 + 「把行吐出去」的诱惑。
            "llm_api_key": self.CANARY,
            "llm_base_url": self.CANARY,
            "requests_5m_detail": self.CANARY,
            "requests_5m_prompt": self.CANARY,
            "success_rate_reason": self.CANARY,
            "fallback_rate_internal": self.CANARY,
            "providers_detail": {f"https://x.test/v1?k={self.CANARY}": {"healthy": True}},
            "breaker_history": [self.CANARY],
            "rows": [{self.CANARY: self.CANARY}],
            "aborted": self.CANARY,
        }
        block.update(overrides)
        return block

    def test_field_set_is_exactly_the_whitelist(self):
        public = public_llm_status(self.full_block())
        self.assertEqual(set(PUBLIC_LLM_STATUS_KEYS), set(public))
        self.assertEqual(
            {"status", "model", "provider", "p50_ms", "p95_ms", "ttft_ms", "requests_5m",
             "success_rate", "fallback_rate", "aborted_rate", "p95_latency_ms",
             "providers", "breaker"}, set(PUBLIC_LLM_STATUS_KEYS))

    def test_no_lookalike_key_or_credential_crosses(self):
        public = public_llm_status(self.full_block())
        self.assertNotIn("apikey_C", repr(public))
        self.assertEqual({"ollama": {"healthy": True},
                          "openai": {"healthy": "unknown"}}, public["providers"])
        self.assertEqual({"ollama": {"state": "open"}}, public["breaker"])

    def test_prefix_admission_is_not_a_rule(self):
        """白名单是逐枚列举：把新键起成 `requests_5m_*` / `success_*` 也进不来。"""
        sneaked = {
            "requests_5m_raw_rows": ["prompt text"],
            "success_rate_debug": {"messages": ["问题原文"]},
            "p95_latency_ms_samples": [1, 2, 3],
            "provider_credentials": {"ollama": "sk-secret"},
            "models": ["secret-entry"],
        }
        public = public_llm_status({**sneaked, "requests_5m": 1})
        self.assertEqual({"requests_5m": 1}, public)

    def test_scalars_are_retyped_not_passed_through(self):
        public = public_llm_status({
            "requests_5m": "9",                                    # 字符串数字 ⇒ None
            "success_rate": "0.5",                                 # 同上
            "fallback_rate": 3.5,                                  # 越界比率 ⇒ None
            "aborted_rate": -0.1,                                  # 负 ⇒ None
            "p95_latency_ms": "很慢了",                             # 非数 ⇒ None
            "p50_ms": True,                                         # bool 不是计时 ⇒ None
            "status": "ONLINE" * 100,                              # 超长 ⇒ 截断
            "ttft_ms": None,
        })
        self.assertEqual(
            {"requests_5m": None, "success_rate": None, "fallback_rate": None,
             "aborted_rate": None, "p95_latency_ms": None, "p50_ms": None,
             "ttft_ms": None},
            {key: public[key] for key in
             ("requests_5m", "success_rate", "fallback_rate", "aborted_rate",
              "p95_latency_ms", "p50_ms", "ttft_ms")})
        self.assertLessEqual(len(public["status"]), 128)

    def test_provider_names_must_look_like_names(self):
        secret = "Bearer super-secret-token-value"
        public = public_llm_status({
            "providers": {f"https://api.x.test/v1?key={secret}": {"healthy": True},
                          "ok_name": {"healthy": "yes-please", "extra": secret},
                          "1" * 200: {"healthy": True},
                          # 评审 Minor 1：注释承诺「键名若被换成 base url，正则就是那道闸」,
                          # 而旧的 `[A-Za-z0-9_.:-]` 字符集**放过**下面这两枚——闸只到
                          # 散文为止。收紧到与注册表同源（`^[a-z0-9_]{1,64}$`）之后,
                          # 点号 / 冒号 / 斜杠 / 大写都不再是 provider 名的合法形状。
                          "api.openai.com": {"healthy": True},
                          "127.0.0.1:11434": {"healthy": True},
                          "Ollama": {"healthy": True},
                          None: {"healthy": True}},
            "breaker": {"ollama": {"state": "exploded", "detail": secret},
                        "http://x/": {"state": "open"}},
        })
        self.assertEqual({"ok_name": {"healthy": "unknown"}}, public["providers"])
        self.assertEqual({"ollama": {"state": "unknown"}}, public["breaker"])
        self.assertNotIn(secret, repr(public))
        self.assertNotIn("openai.com", repr(public))
        self.assertNotIn("11434", repr(public))

    def test_non_mapping_provider_blocks_collapse_to_empty(self):
        public = public_llm_status({"providers": ["ollama"], "breaker": None})
        self.assertEqual({"providers": {}, "breaker": {}}, public)

    def test_known_breaker_states_pass_verbatim(self):
        states = ("closed", "half_open", "open")
        public = public_llm_status({"breaker": {f"p{i}": {"state": state}
                                                for i, state in enumerate(states)}})
        self.assertEqual(["closed", "half_open", "open"],
                         [entry["state"] for entry in public["breaker"].values()])


# ==========================================================================
# 9. `/api/system/status` 的 llm 块
# ==========================================================================
class SystemStatusLlmBlockTests(_UsageFixture):
    CANARY = "apikey_" + "D" * 40

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(fastapi_app)
        login = cls.client.post("/api/auth/login",
                                json={"username": "admin", "password": "admin123"})
        assert login.status_code == 200, login.text
        cls.admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def aggregate(self) -> dict:
        return {
            "requests_5m": 9, "success_rate": 0.7143, "fallback_rate": 0.2222,
            "aborted_rate": 0.2222, "p95_latency_ms": 900.0,
            "providers": {"ollama": {"healthy": True}},
            "breaker": {"ollama": {"state": "closed"}},
            "llm_api_key": self.CANARY,
            "rows": [{self.CANARY: LONG_PROMPT}],
        }

    def get_status(self, aggregate: dict):
        with (
            mock.patch.object(knowledge_os_module.vector_store, "ping", return_value=True),
            mock.patch.object(knowledge_os_module.vector_store, "stats",
                              return_value={"total_chunks": 1, "collection_name": "c",
                                            "embedding_dimension": 4}),
            mock.patch.object(knowledge_os_module, "probe_llm", return_value=(True, "ok")),
            mock.patch.object(knowledge_os_module, "current_model_name",
                              return_value="test-model"),
            mock.patch.object(knowledge_os_module, "_trace_latency_stats",
                              return_value={"p50_ms": 410.0, "p95_ms": 900.0,
                                            "ttft_ms": 210.0}),
            mock.patch.object(usage_module, "aggregate_status", return_value=aggregate),
        ):
            return self.client.get("/api/system/status", headers=self.admin_headers)

    def test_llm_block_is_the_legacy_probe_face_plus_the_aggregate(self):
        response = self.get_status(self.aggregate())
        self.assertEqual(200, response.status_code, response.text)
        block = response.json()["llm"]
        self.assertEqual(set(PUBLIC_LLM_STATUS_KEYS), set(block))
        # §9 additive only：V2.3 之前就有的六个键一个都不动（前端 SystemView 在消费）。
        self.assertEqual({"status": "ONLINE", "model": "test-model", "provider": "ollama",
                          "p50_ms": 410.0, "p95_ms": 900.0, "ttft_ms": 210.0},
                         {key: block[key] for key in ("status", "model", "provider",
                                                      "p50_ms", "p95_ms", "ttft_ms")})
        self.assertEqual(0.7143, block["success_rate"])
        self.assertEqual(900.0, block["p95_latency_ms"])
        self.assertEqual({"ollama": {"healthy": True}}, block["providers"])

    def test_unknown_aggregate_keys_never_reach_the_response(self):
        response = self.get_status(self.aggregate())
        self.assertNotIn(self.CANARY, response.text)
        self.assertNotIn("保密协议", response.text)
        self.assertNotIn("rows", response.json()["llm"])

    def test_disabled_router_yields_an_empty_aggregate_block(self):
        self.use_settings(llm_router_enabled=False)
        block = self.get_status(usage_module.aggregate_status()).json()["llm"]
        self.assertEqual(set(PUBLIC_LLM_STATUS_KEYS), set(block))
        self.assertEqual(0, block["requests_5m"])
        self.assertIsNone(block["success_rate"])
        self.assertEqual({}, block["providers"])
        self.assertEqual("ONLINE", block["status"])               # legacy 面不受旗标影响

    def test_the_other_status_blocks_are_untouched(self):
        payload = self.get_status(self.aggregate()).json()
        self.assertEqual({"overall", "llm", "embedding", "bm25", "reranker", "vector_db",
                          "index", "typesafe"}, set(payload))


# ==========================================================================
# 10. trace 的 `model_route` 对象（§8.1 的九键 + T6/7/8 的一行接缝 + 防回潮钉）
# ==========================================================================
class ModelRouteTraceShapeTests(_ModelRouteFixture):
    """`usage.model_route_trace()`：矩阵 #17 的被测面（纯函数，不碰库、不碰网络）。"""

    def trace_object(self, **kwargs) -> dict:
        kwargs.setdefault("profile", self.profile())
        kwargs.setdefault("registry", registry_of(
            entry_of(id="fb-a", model="fb-a-model"),
            entry_of(id="fb-b", model="fb-b-model")))
        return usage_module.model_route_trace(self.plan(), self.result(), **kwargs)

    def test_the_object_is_exactly_the_nine_frozen_keys(self):
        payload = self.trace_object()
        self.assertEqual(list(MODEL_ROUTE_KEYS), list(payload))           # 键序也钉
        self.assertEqual(9, len(payload))
        self.assertEqual(list(MODEL_ROUTE_REQUIREMENT_KEYS),
                         list(payload["requirements"]))
        self.assertEqual(list(MODEL_ROUTE_CANDIDATE_KEYS), list(payload["primary"]))
        self.assertEqual([list(MODEL_ROUTE_ATTEMPT_KEYS)] * 2,
                         [list(item) for item in payload["attempts"]])
        self.assertEqual([], payload["fallbacks"])                        # 键恒在，可为空
        # 九键的**键集合**本身也是契约：末三枚执行面事实是 §8.1 第 4 条写进来的，
        # 少一枚就是「丢弃执行面事实」，多一枚就是「实现侧自扩 §8」。
        self.assertEqual({"mode", "requirements", "primary", "fallbacks",
                          "selected_reason_codes", "attempts",
                          "stage", "selected_index", "context_dropped"},
                         set(payload))

    def test_mode_and_requirements_come_from_the_profile(self):
        payload = self.trace_object(profile=self.profile(mode="agent", complexity="high",
                                                         needs_tools=True,
                                                         needs_stream=False,
                                                         needs_reasoning=True))
        self.assertEqual("agent", payload["mode"])
        self.assertEqual({"complexity": "high", "needs_tools": True,
                          "needs_stream": False, "needs_reasoning": True},
                         payload["requirements"])
        no_profile = usage_module.model_route_trace(self.plan(), self.result())
        self.assertEqual("", no_profile["mode"])
        self.assertEqual({}, no_profile["requirements"])                  # 不猜需求

    def test_the_three_execution_face_facts_come_from_the_result(self):
        """§8.1 第 4 条末三枚键：`stage` / `selected_index` / `context_dropped`。

        这三枚原先由 `llm.model_route_payload()` 另算一遍（且模型名口径与账本分叉），
        评审裁定 C 之后并进来这里就是**唯一**一份。语义逐值钉：第 0 候选交付 = `primary`、
        更靠后 = `fallback`、没选中任何候选 = `none`；`selected_index` 是**原值**（不翻译、
        不夹到 0）；`context_dropped` 是被上下文收口吃掉的候选条数。
        """
        cases = (
            (0, "primary"), (1, "fallback"), (2, "fallback"), (-1, "none"))
        for index, stage in cases:
            with self.subTest(selected_index=index):
                payload = usage_module.model_route_trace(
                    self.plan(), self.result(selected_index=index, context_dropped=3),
                    profile=self.profile(), registry=registry_of(entry_of()))
                self.assertEqual(stage, payload["stage"])
                self.assertEqual(index, payload["selected_index"])
                self.assertEqual(3, payload["context_dropped"])
                self.assertEqual(("stage", "selected_index", "context_dropped"),
                                 tuple(list(payload)[-3:]))    # 键序：末三枚在执行面

    def test_the_d2_object_reports_the_three_facts_as_nothing_delivered(self):
        """`AllCandidatesFailedError` 没有 `selected_index` / `context_dropped` 两枚字段。

        「读不到」在这里必须落成**没有交付**那一组值（`none` / -1 / 0），而不是抛出去把
        整条 trace 丢掉，也不是猜一个 `primary`——D2 的降级路径恰恰是最需要一条能解释的
        route 的那一条，而「这次什么都没交付」正是它的解释。
        """
        error = AllCandidatesFailedError(
            (attempt("fb-a", "failed", "model_unavailable", 200.0),),
            reason_codes=("CAPABILITY_MATCH",))
        payload = usage_module.model_route_trace(self.plan(), error,
                                                profile=self.profile(),
                                                registry=registry_of(entry_of()))
        self.assertEqual("none", payload["stage"])
        self.assertEqual(-1, payload["selected_index"])
        self.assertEqual(0, payload["context_dropped"])

    def test_a_stringified_false_flag_is_not_read_as_a_demand(self):
        """需求旗标是**显式真值判定**，不是 `bool(...)`（评审 Minor 4）。

        `bool("false")` 是 `True`。画像今天由 classifier 产出、确实是真 `bool`，但 trace
        是跨进程读回来的观测面：只要有人从 JSON / 表单把字符串塞进 `needs_tools`，用
        `bool()` 收就会让 trace 声称「这次要工具」而路由其实没要——观测面凭空报出一个不
        存在的需求，比报不出来更坏。判定表在 `_trace_flag` 的注释里，这里逐枚钉。
        """
        from types import SimpleNamespace

        cases = (("false", False), ("true", True), ("TRUE", True), ("1", True),
                 ("yes", True), ("0", False), ("", False), (None, False),
                 (1, True), (0, False), (True, True), (False, False))
        for raw, expected in cases:
            with self.subTest(raw=repr(raw)):
                profile = SimpleNamespace(mode="rag", complexity="low",
                                          needs_tools=raw, needs_stream=raw,
                                          needs_reasoning=raw)
                requirements = usage_module.model_route_trace(
                    self.plan(), self.result(), profile=profile,
                    registry=registry_of(entry_of()))["requirements"]
                self.assertEqual({"complexity": "low", "needs_tools": expected,
                                  "needs_stream": expected,
                                  "needs_reasoning": expected}, requirements)
                # 出门的仍是 bool：字符串形状的事实不许原样进 trace（观测面只发机器值）。
                for flag in ("needs_tools", "needs_stream", "needs_reasoning"):
                    self.assertIsInstance(requirements[flag], bool)

    def test_plan_side_candidates_are_explained_by_machine_values(self):
        plan = self.plan(candidate_of(),
                         candidate_of(model=entry_of(id="fb-b", model="fb-b-model"),
                                      score=8, reason_codes=("CAPABILITY_MATCH",)),
                         candidate_of(model=entry_of(id="fb-c", model="fb-c-model",
                                                      external=True),
                                      score=6, reason_codes=("NOT_A_CODE",)))
        payload = usage_module.model_route_trace(
            plan, self.result(), profile=self.profile(),
            registry=registry_of(entry_of(id="fb-a", model="fb-a-model"),
                                 entry_of(id="fb-b", model="fb-b-model")))
        self.assertEqual("fb-a-model", payload["primary"]["model"])
        self.assertEqual([{"id": "fb-b", "provider": "ollama", "model": "fb-b-model",
                           "score": 8, "reason_codes": ["CAPABILITY_MATCH"]},
                          {"id": "fb-c", "provider": "ollama", "model": "fb-c-model",
                           "score": 6, "reason_codes": []}],
                         payload["fallbacks"])
        self.assertNotIn("pricing", payload["primary"])                   # 牌价不是解释
        self.assertNotIn("limits", payload["primary"])

    def test_selected_reason_codes_are_filtered_to_the_frozen_enum(self):
        payload = self.trace_object()
        self.assertEqual(["CAPABILITY_MATCH", "LOCAL_PREFERRED",
                          "FALLBACK_AFTER_TIMEOUT"], payload["selected_reason_codes"])
        self.assertNotIn("NOT_A_CODE", payload["selected_reason_codes"])

    def test_attempts_report_the_effective_model_name_and_machine_results(self):
        payload = self.trace_object()
        self.assertEqual([{"model": "fb-a-model", "result": "failed",
                           "error_type": "retryable"},
                          {"model": "fb-b-model", "result": "success",
                           "error_type": None}],
                         payload["attempts"])                             # 条目 id 已归一

    def test_attempt_fields_degrade_to_machine_readable_fallbacks(self):
        """越界值不猜、不截断留前缀：`result` ⇒ `unknown`、坏 `error_type` ⇒ `unknown`、
        不合字符集的 `model_id` ⇒ 空串（同账本 `model` 列那一枚闸）。"""
        result = self.result(attempts=(
            attempt("fb-a", "exploded", None, 1.0),                       # 越界 result
            attempt("fb-b", "failed", "上游 500：" + LONG_PROMPT[:20], 2.0),
            attempt("模型名带中文", "success", None, 3.0),
            attempt("fb-c", "skipped_circuit", None, 0.0)))
        payload = usage_module.model_route_trace(self.plan(), result,
                                                 profile=self.profile(),
                                                 registry=registry_of(
                                                     entry_of(),
                                                     entry_of(id="fb-b",
                                                              model="fb-b-model")))
        self.assertEqual([{"model": "fb-a-model", "result": "unknown",
                           "error_type": None},
                          {"model": "fb-b-model", "result": "failed",
                           "error_type": "unknown"},
                          {"model": "", "result": "success", "error_type": None},
                          {"model": "fb-c", "result": "skipped_circuit",
                           "error_type": None}],
                         payload["attempts"])
        self.assertNotIn("保密协议", repr(payload))

    def test_the_object_survives_a_json_round_trip(self):
        payload = self.trace_object()
        self.assertEqual(payload, json.loads(json.dumps(payload, ensure_ascii=False)))

    def test_a_profile_carrying_a_query_leaves_not_a_single_byte_in_the_object(self):
        """契约：构造函数**只按名字读**画像的五个冻结字段。

        这里故意用一个带 `query` / `prompt` / `reasoning` / `messages` 的假画像
        （duck-typed，每枚值带一个唯一标记），并把中文 canary 塞进执行回执的响应文本里。
        任何 `vars()` / `dataclasses.asdict()` / 属性遍历的写法都会在这里红——而 T6/7/8
        真的会把画像、消息体和回执放在同一个作用域里。
        """
        from types import SimpleNamespace

        markers = {
            "query": "QMARK-" + LONG_PROMPT[:10],
            "prompt": "PMARK-" + LONG_PROMPT[10:20],
            "reasoning": "RMARK-" + LONG_PROMPT[-10:],
            "messages": [{"role": "user", "content": "MMARK-" + LONG_PROMPT[:10]}],
            "system_prompt": "SMARK-" + LONG_PROMPT[20:30],
        }
        poisoned = SimpleNamespace(mode="rag", complexity="low", needs_tools=False,
                                   needs_stream=False, needs_reasoning=False, **markers)
        payload = usage_module.model_route_trace(
            self.plan(), self.result(), profile=poisoned,
            registry=registry_of(entry_of()))
        self.assertEqual(set(MODEL_ROUTE_KEYS), set(payload))
        rendered = repr(payload)
        for probe in ("QMARK", "PMARK", "RMARK", "MMARK", "SMARK",
                      LONG_PROMPT[:12], LONG_PROMPT[-12:], "保密协议", "违约金",
                      "答案"):
            self.assertNotIn(probe, rendered)

    def test_both_lists_are_capped(self):
        plan = self.plan(candidate_of(),
                         *[candidate_of(model=entry_of(id=f"fb-{i}", model=f"fb-{i}-name"))
                           for i in range(30)])
        result = self.result(attempts=tuple(attempt(f"fb-{i % 30}") for i in range(40)))
        payload = usage_module.model_route_trace(plan, result, registry=None)
        self.assertEqual(usage_module.TRACE_LIST_MAX_ITEMS, len(payload["fallbacks"]))
        self.assertEqual(usage_module.TRACE_LIST_MAX_ITEMS, len(payload["attempts"]))

    def test_both_argument_gates_are_type_errors(self):
        for bad_plan in ({"primary": None}, None, "plan"):
            with self.subTest(plan=type(bad_plan).__name__):
                with self.assertRaises(TypeError):
                    usage_module.model_route_trace(bad_plan, self.result())
        for bad_result in ({"attempts": ()}, None, LLMResponse(content="x")):
            with self.subTest(result=type(bad_result).__name__):
                with self.assertRaises(TypeError):
                    usage_module.model_route_trace(self.plan(), bad_result)

    def test_the_d2_failure_shape_is_supported(self):
        """`AllCandidatesFailedError`：一条候选都没跑通时 trace 仍然要能解释（D2）。"""
        error = AllCandidatesFailedError(
            (attempt("fb-a", "failed", "model_unavailable", 200.0),
             attempt("fb-b", "skipped_circuit", None, 0.0)),
            reason_codes=("CAPABILITY_MATCH", "PRIMARY_UNHEALTHY", "CIRCUIT_OPEN"))
        payload = usage_module.model_route_trace(self.plan(), error,
                                                 profile=self.profile(),
                                                 registry=registry_of(entry_of()))
        self.assertEqual(["CAPABILITY_MATCH", "PRIMARY_UNHEALTHY", "CIRCUIT_OPEN"],
                         payload["selected_reason_codes"])
        self.assertEqual([{"model": "fb-a-model", "result": "failed",
                           "error_type": "model_unavailable"},
                          {"model": "fb-b", "result": "skipped_circuit",
                           "error_type": None}],
                         payload["attempts"])

    def test_an_unreadable_registry_still_yields_a_complete_object(self):
        with (mock.patch.object(usage_module, "get_registry",
                                side_effect=RegistryError("注册表文件不可用")),
              self.assertLogs("app.llm.usage", level="WARNING")):
            payload = usage_module.model_route_trace(self.plan(), self.result(),
                                                     profile=self.profile())
        self.assertEqual(list(MODEL_ROUTE_KEYS), list(payload))
        self.assertEqual("fb-a-model", payload["primary"]["model"])        # 声明名兜底
        self.assertEqual(["fb-a", "fb-b"], [a["model"] for a in payload["attempts"]])

    def test_the_routers_own_vocabulary_survives_into_the_trace_object(self):
        """T3 移交：`PRIMARY_UNHEALTHY` 与「被剔候选」的解释必须和 **router 同源**。

        这里不重述词表：计划由真的 `plan()` 产出（health_view 把 ollama 标成不健康），
        再原样交给回执 → trace 对象。任何一侧另立一套码（或净化层把它当越界值丢掉）都会
        让等式红。`context_dropped` / `stage` 自 §8.1 第 4 条起**就在**九键清单里（上一版
        这条测试钉的是「它不在」，因为当时 §8 只列了六键）——回执里那个数于是必须原样
        出现在 trace 上，而不是被另一条通道搬走。
        """
        registry = registry_of(entry_of(id="fb-a", model="fb-a-model"),
                               entry_of(id="fb-o", provider="openai", model="fb-o-model",
                                        external=True))
        route_plan = llm.plan(profile_of("rag"), registry,
                              {"ollama": {"healthy": False, "circuit_open": False},
                               "openai": {"healthy": True, "circuit_open": False}})
        self.assertEqual("fb-o", route_plan.primary.model.id)
        self.assertIn("PRIMARY_UNHEALTHY", route_plan.reason_codes)
        payload = usage_module.model_route_trace(
            route_plan, self.result(reason_codes=route_plan.reason_codes),
            profile=profile_of("rag"), registry=registry)
        self.assertEqual(set(route_plan.reason_codes),
                         set(payload["selected_reason_codes"]))
        self.assertIn("PRIMARY_UNHEALTHY", payload["selected_reason_codes"])
        self.assertEqual("fb-o-model", payload["primary"]["model"])
        self.assertIn("context_dropped", payload)               # §8.1 九键之内
        self.assertEqual(1, payload["context_dropped"])          # 回执里那个数原样出门
        self.assertEqual("fallback", payload["stage"])           # selected_index=1


class AgentTraceModelRouteSeamTests(_ModelRouteFixture):
    """`agent_trace.attach_model_route()`：T6/7/8 那一行调用的接缝（additive + fail-open）。"""

    def sample_trace(self) -> dict:
        return {"trace_id": "t-1", "query_preview": "历史字段",
                "events": [{"type": "retrieval", "top_k": 5}], "answer": "答"}

    def test_attaching_writes_exactly_one_new_key(self):
        trace = self.sample_trace()
        before = json.dumps(trace, ensure_ascii=False, sort_keys=True)
        returned = attach_model_route(trace, self.plan(), self.result(),
                                      profile=self.profile())
        self.assertIs(trace, returned)                                    # 就地 additive
        self.assertEqual({"trace_id", "query_preview", "events", "answer",
                          MODEL_ROUTE_KEY}, set(trace))
        self.assertEqual(MODEL_ROUTE_KEY, "model_route")                   # §8 的键名
        payload = trace[MODEL_ROUTE_KEY]
        self.assertEqual(list(MODEL_ROUTE_KEYS), list(payload))
        self.assertEqual("rag", payload["mode"])
        # 已有字段一个字节都没动（§9「既有响应结构对外不变」）
        rest = {key: value for key, value in trace.items() if key != MODEL_ROUTE_KEY}
        self.assertEqual(before, json.dumps(rest, ensure_ascii=False, sort_keys=True))

    def test_the_seam_is_fail_open(self):
        trace = self.sample_trace()
        with self.assertLogs("app.agent_trace", level="WARNING"):
            returned = attach_model_route(trace, self.plan(), None)
        self.assertIs(trace, returned)
        self.assertNotIn(MODEL_ROUTE_KEY, trace)                           # 不写坏键
        self.assertEqual(self.sample_trace(), trace)

    def test_the_persisted_line_carries_model_route_and_no_prompt(self):
        """矩阵 #17 的集成半段：落盘的 JSONL 里读回来就是那个对象，且没有 canary 字节。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent_traces.jsonl"
            with mock.patch.object(agent_trace_module, "TRACE_PATH", path):
                trace = self.sample_trace()
                attach_model_route(trace, self.plan(), self.result(),
                                   profile=self.profile())
                agent_trace_module.save_trace(trace)
                line = path.read_text(encoding="utf-8")
                self.assertNotIn("保密协议", line)
                self.assertNotIn("违约金", line)
                self.assertEqual(trace[MODEL_ROUTE_KEY],
                                 json.loads(line)[MODEL_ROUTE_KEY])
                self.assertEqual(json.loads(line),
                                 agent_trace_module.get_trace("t-1"))


# ==========================================================================
# 10c. 防回潮钉：`model_route` 只有一处构造（评审裁定 C / §8.1 第 4 条）
# ==========================================================================
#: 允许「说到 model_route 这个键」的文件：唯一挂载点。**相对 `backend/` 的 posix 路径**
#: （T5 复审 N2：按 `path.name` 比对会让子目录里的同名文件自动免检）。
ROUTE_KEY_MOUNT_FILES = frozenset({"app/agent_trace.py"})
#: 允许「构造九键那个对象」的文件：唯一生产者。同样是相对路径。
ROUTE_OBJECT_PRODUCER_FILES = frozenset({"app/llm/usage.py"})
#: **值搬运面**额外允许的一档：`app/llm/fallback.py` 是 `selected_index` / `context_dropped`
#: 这两枚事实的**定义方**（dataclass 字段 + 构造 kwargs），它一处九键的**键名字面量**都不写
#: ⇒ 键名字面量面（`*_PATTERN` + AST 常量面）对它仍是零命中、生产者仍然只剩 `usage.py` 一处。
#: Task 9 复审 I-2 加 kwargs 形谓词时必须面对的既有事实，写成显式豁免而不是把谓词放宽。
ROUTE_FACT_TRANSPORT_FILES = ROUTE_OBJECT_PRODUCER_FILES | {"app/llm/fallback.py"}
#: 谓词（N2 的收紧 + T9 复审 I-2 的再收紧）：单引号与双引号在 Python 里是同一个字面量，
#: 只认双引号＝一半免检面。成对判据保持 brief 的形状（两枚各 `search` 再 `and`），不引入顺序假设。
SELECTED_INDEX_PATTERN = re.compile(r"[\"']selected_index[\"']")
CONTEXT_DROPPED_PATTERN = re.compile(r"[\"']context_dropped[\"']")
KEY_NAME_PATTERN = re.compile(r"[\"']model_route[\"']")
#: I-2 第三支：kwargs / 赋值形（`dict(stage=…, selected_index=…, context_dropped=…)` 在源码里
#: **不带引号** ⇒ 上面两枚正则整族免检）。与 brief 同形：两枚各 `search` 再 `and`。
SELECTED_INDEX_KWARG_PATTERN = re.compile(r"\bselected_index\s*=")
CONTEXT_DROPPED_KWARG_PATTERN = re.compile(r"\bcontext_dropped\s*=")
#: I-2 第四支：相邻字符串字面量会被 CPython 合成**一枚** `ast.Constant`
#: （`{"selected_" "index": …}` 文本面零命中，但它就是源码字面量）。走 AST 而不是再堆正则，
#: 与 `SingleEgressStructureTests` 同一手法，且**整枚相等**判定天然不误伤注释与 docstring。
ROUTE_FACT_CONSTANTS = frozenset({"selected_index", "context_dropped"})


def _relative_source_path(path: Path) -> str:
    """`backend/app/**` 下任一源文件相对 `backend/` 的 posix 路径（豁免表的键形）。"""
    return path.relative_to(BACKEND_DIR).as_posix()


def _app_source_files() -> list[Path]:
    """`backend/app` 下全部 .py（不含 __pycache__）。扫描面 = 交付面。"""
    return [path for path in (BACKEND_DIR / "app").rglob("*.py")
            if "__pycache__" not in path.parts]


def _string_constants(path: Path) -> set[str]:
    """该文件里**整枚相等**的字符串常量（隐式拼接在 AST 里已经是单枚 `Constant`）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


class ModelRouteProducerUniquenessTests(_ModelRouteFixture):
    """「同一个事实只有一处构造」的机器化表达。

    评审 C 的实测后果不是抽象的：同一份 `FallbackResult` 下，被删掉的
    `llm.model_route_payload()` 给出 `attempts[].model = ['fb-a','fb-b']`（条目 id，绕过
    M2 口径），而 `usage.model_route_trace()` 给出 `['fb-a-model','fb-b-model']`。两条
    通道对同一次请求说两个词，「拿 trace 对账」这条运维动作当场失效。所以这里钉三件事：
    那个函数不存在、它不在导出面上、九键对象除了 `model_route_trace` 没有别的产地。
    """

    def test_there_is_exactly_one_model_route_producer(self):
        # ① 被删的第二个生产者不许复活（属性 + 导出面两枚都钉：只删实现不删 `__all__`
        #    会留下一个 `from app.llm import *` 就能拿到的悬空名字）。
        self.assertFalse(hasattr(llm, "model_route_payload"),
                         "llm.model_route_payload 复活了：同一份执行面事实不许有两处构造")
        self.assertNotIn("model_route_payload", llm.__all__)
        # ② 包出口面上「以 model_route 命名」的可调用对象只剩零枚（`app.llm` 不许再产出）。
        route_named = [name for name, value in vars(llm).items()
                       if callable(value)
                       and getattr(value, "__name__", "").startswith("model_route")]
        self.assertEqual([], route_named)
        # ③ 账本侧只剩一枚：`app.llm.usage` 里 `model_route*` 命名的函数就是
        #    `model_route_trace` 本身，且它就是 `MODEL_ROUTE_KEY` 那个键的唯一产地。
        producer_names = sorted(name for name in vars(usage_module)
                                if name.startswith("model_route"))
        self.assertEqual(["model_route_trace"], producer_names)
        self.assertEqual("model_route", MODEL_ROUTE_KEY)
        produced = usage_module.model_route_trace(self.plan(), self.result(),
                                                 profile=self.profile(),
                                                 registry=registry_of(entry_of()))
        self.assertEqual(list(MODEL_ROUTE_KEYS), list(produced))
        trace = attach_model_route({}, self.plan(), self.result(),
                                   profile=self.profile())
        self.assertEqual({"model_route"}, set(trace))
        self.assertEqual(produced["stage"], trace[MODEL_ROUTE_KEY]["stage"])

    def test_no_other_module_names_the_route_key_or_rebuilds_its_facts(self):
        """源码级扫描：键名与「执行面三键」的字面量各自只许出现在被允许的文件里。

        属性级的 `hasattr` 只挡得住同名函数；下一轮完全可能换个名字（
        `route_execution_summary`）再拼一遍九键。这里钉的是**字面量**：
        `MODEL_ROUTE_KEY` / `"model_route"` 只许出现在挂载点，
        `"selected_index"` + `"context_dropped"` 成对出现只许出现在生产者那一处。

        **T5 复审 N2 的两处收紧**（与 `tests/test_llm_egress_guard.py` 的 D6 扫描同族化：
        同一份文件枚举、同一份「相对路径 + 等式」豁免结构）：
        ① 谓词不再只认双引号——单引号与双引号在 Python 里是同一个字面量，旧写法下把
           两枚键的字面量换成单引号就能整族免检；
        ② 豁免键是 `app/agent_trace.py` / `app/llm/usage.py` 这样的**相对路径**，
           旧写法按 `path.name` 比对 ⇒ 谁在子目录再放一个 `usage.py` 就自动免检。

        **T9 复审 I-2 的再收紧**（四枚谓词，同一份文件枚举里 `or` 起来）：
        ③ kwargs / 赋值形 `dict(stage=…, selected_index=…, context_dropped=…)`——源码里
           根本不出现引号，①②两枚正则一起漏；
        ④ 隐式拼接形 `{"selected_" "index": …}`——CPython 把相邻常量合成**一枚**
           `ast.Constant`，语义上就是源码字面量，但文本面零命中 ⇒ 改走 AST 整枚相等判定。
        ③ 那一支对 `app/llm/fallback.py`（两枚事实的**定义方**）必然命中，故它的豁免写进
        `ROUTE_FACT_TRANSPORT_FILES` 单独一档；同时下面把「键名字面量面只有 `usage.py` 一处」
        钉成等式，所以这档豁免**买不到**任何九键构造权（fallback.py 在字面量面零命中）。

        本钉覆盖的是**写在源码里的键名**（带引号 / kwargs / 隐式拼接三形，含注释之外的字符串
        常量）；仍挡不住的是**运行期拼出来的键名**（例如 `f"{'selected'}_index"`、
        `"".join(["selected", "_index"])`），那一类由 #17 的集成用例兜
        （`ModelRouteIntegrationTests` / `SseTraceIntegrationTests` /
        `AgentModelRouteTraceTests` 三枚真落盘断言：键是运行期拼的也一样落不进九键）。
        """
        key_speakers, fact_speakers = [], []
        key_literal_speakers: list[str] = []       # 把两枚事实**写成字面量**的文件
        fact_transport_speakers: list[str] = []    # 以 kwargs / 赋值形搬运事实的文件
        for path in _app_source_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = _relative_source_path(path)
            names_the_key = (bool(KEY_NAME_PATTERN.search(text))
                             or "MODEL_ROUTE_KEY" in text)
            quoted_facts = (bool(SELECTED_INDEX_PATTERN.search(text))
                            and bool(CONTEXT_DROPPED_PATTERN.search(text)))
            kwarg_facts = (bool(SELECTED_INDEX_KWARG_PATTERN.search(text))
                           and bool(CONTEXT_DROPPED_KWARG_PATTERN.search(text)))
            spliced_facts = ROUTE_FACT_CONSTANTS <= _string_constants(path)
            if quoted_facts or spliced_facts:
                key_literal_speakers.append(rel)
            if kwarg_facts:
                fact_transport_speakers.append(rel)
            rebuilds_the_facts = quoted_facts or kwarg_facts or spliced_facts
            if names_the_key and rel not in ROUTE_KEY_MOUNT_FILES:
                key_speakers.append(rel)
            if rebuilds_the_facts and rel not in ROUTE_FACT_TRANSPORT_FILES:
                fact_speakers.append(rel)
        self.assertEqual([], key_speakers, "第二处写 trace 键名的文件")
        self.assertEqual([], fact_speakers, "第二处构造执行面三键的文件")
        # 外圈等式（评审 I-2 之后才有的牙）：键名字面量面 = 生产者一处，值搬运面 = 事实定义方。
        self.assertEqual(sorted(ROUTE_OBJECT_PRODUCER_FILES), sorted(key_literal_speakers),
                         "把九键的键名写成字面量的文件必须恰是那枚唯一生产者")
        self.assertEqual(["app/llm/fallback.py"], sorted(fact_transport_speakers),
                         "kwargs/赋值形搬运 `selected_index`+`context_dropped` 的只许事实定义方")
        # 扫描面本身不能是空的（否则这两条等式永远绿）：挂载点与生产者各被看见一次。
        scanned = {_relative_source_path(path) for path in _app_source_files()}
        self.assertIn("app/agent_trace.py", scanned)
        self.assertIn("app/llm/usage.py", scanned)
        # 豁免集合不许养闲条目：表里的每一枚都必须在扫描面上。
        self.assertTrue(ROUTE_KEY_MOUNT_FILES <= scanned, "挂载点豁免指向了不存在的文件")
        self.assertTrue(ROUTE_FACT_TRANSPORT_FILES <= scanned,
                        "生产者/事实搬运方豁免指向了不存在的文件")


# ==========================================================================
# 11. `model` 列的单一口径（Task 4 移交的劈叉）
# ==========================================================================
class ModelColumnCaliberTests(_UsageFixture):
    def setUp(self) -> None:
        super().setUp()
        previous = llm.set_usage_sink(None)                        # 用真落库函数
        self.addCleanup(lambda: llm.set_usage_sink(previous))

    def summary(self, model_id: str = "fb-a", provider: str = "ollama") -> StreamSummary:
        return StreamSummary(response_text="答",
                             usage={"input_tokens": 1, "output_tokens": 2,
                                    "total_tokens": 3, "estimated": False},
                             ttft_ms=50.0, attempts=(attempt(model_id, provider=provider),),
                             selected_index=0, reason_codes=(), committed=True,
                             completed=True, model_id=model_id, provider_name=provider)

    def test_stream_row_uses_the_effective_model_name_not_the_entry_id(self):
        self.use_registry(entry_of(id="fb-a", model="fb-a-model"))
        record = llm.log_stream_usage(self.summary(), mode="rag")
        self.assertEqual("fb-a-model", record.model)
        self.assertNotEqual("fb-a", record.model)
        usage_module.log_usage(record)
        self.assertEqual("fb-a-model", self.raw_rows()[0]["model"])

    def test_both_entries_write_the_same_kind_of_value(self):
        """两行账（非流式 / 流式）在 `model` 列上必须指同一个东西。"""
        candidate = entry_of(id="fb-a", model="fb-a-model")
        self.use_registry(candidate)
        non_stream = llm._usage_from_result(
            FallbackResult(response=LLMResponse(content="x", model="fb-a-model",
                                                provider="ollama"),
                           attempts=(attempt(),), selected_index=0),
            profile_of("chat"), "chat", trace_id=None, request_id=None)
        stream = llm.log_stream_usage(self.summary(), mode="rag")
        self.assertEqual(non_stream.model, stream.model)

    def test_model_override_alias_is_used_on_both_sides(self):
        self.use_registry(entry_of(id="fb-o", provider="openai", model="registry-name",
                                   external=True))
        self.use_settings(openai_api_key="sk-test-key")
        with mock.patch.dict(os.environ, {"OPENAI_MODEL_OVERRIDE": "prod-alias-2026"}):
            stream = llm.log_stream_usage(self.summary("fb-o", provider="openai"),
                                          mode="rag")
            non_stream = llm._usage_from_result(
                FallbackResult(response=LLMResponse(content="x", model="prod-alias-2026",
                                                    provider="openai"),
                               attempts=(attempt("fb-o", provider="openai"),),
                               selected_index=0),
                profile_of("rag"), "rag", trace_id=None, request_id=None)
        self.assertEqual("prod-alias-2026", stream.model)
        self.assertEqual(non_stream.model, stream.model)

    def test_entry_missing_from_the_registry_falls_back_to_the_id(self):
        self.use_registry(entry_of(id="fb-a"))
        record = llm.log_stream_usage(self.summary("deleted-entry"), mode="rag")
        self.assertEqual("deleted-entry", record.model)           # 可解释的 id 优于空串

    def test_the_sink_still_sanitizes_an_unsafe_name(self):
        """**中文 canary ⇒ `model` 列空串**：这条闸一个字都不许松。

        取行按 `trace_id` 定位，不按结果列表的下标——`llm.log_stream_usage()` 本身就会经
        sink 落一行（T4 的接缝语义，`set_usage_sink(None)` 时惰性解析到真 `log_usage`），
        所以下一行不再是「那条 canary 账」而是「同一条流式账的第二行」。按位置取就会把
        这件事读成净化层坏了，而净化层其实什么都没做错。
        """
        self.use_registry(entry_of(id="fb-a", model="fb-a-model"))
        llm.log_stream_usage(self.summary(), mode="rag", trace_id="t-stream")
        usage_module.log_usage(record_at(-3, trace_id="t-canary", model=LONG_PROMPT[:20]))
        rows = self.raw_rows()
        # 钉住「到底落了哪些行、每行是谁」：两行、两个 trace_id、没有第三次写。
        self.assertEqual(2, len(rows))
        self.assertEqual({"t-stream", "t-canary"}, {row["trace_id"] for row in rows})
        by_trace = {row["trace_id"]: row for row in rows}
        self.assertEqual("fb-a-model", by_trace["t-stream"]["model"])   # 生效模型名（M2）
        self.assertIsNone(by_trace["t-stream"]["status_code"])          # M1：流式行无状态码
        self.assertEqual("", by_trace["t-canary"]["model"])             # 中文 canary ⇒ 空串
        self.assertEqual("rag", by_trace["t-canary"]["route_mode"])     # 其余列照常落

    def test_all_three_producer_paths_land_on_one_model_string(self):
        """M2 的最终口径：**一列一种值**。三条出口实测写两种东西（见 `usage.py` 模块
        docstring 第四条：失败行写 `Attempt.model_id`），归一发生在落库前。

        这条测试是「跨路一致性」的那枚钉子：把 `usage._stored_model_name` 换成直接透传，
        失败行就会以 `fb-a` 落库，等式立刻红——按模型聚合的账不必再判来源。
        """
        self.use_registry(entry_of(id="fb-a", model="fb-a-model"))
        profile = profile_of("chat")
        non_stream = llm._usage_from_result(
            FallbackResult(response=LLMResponse(content="x", model="fb-a-model",
                                                provider="ollama"),
                           attempts=(attempt(),), selected_index=0),
            profile, "chat", trace_id="t-nonstream", request_id=None)
        failure = llm._usage_from_failure(
            AllCandidatesFailedError((attempt("fb-a", "failed", "retryable", 50.0),),
                                     reason_codes=("CAPABILITY_MATCH",),
                                     last_error=LLMError("retryable", 503,
                                                         "上游暂时不可用")),
            profile, "chat", trace_id="t-failure", request_id=None)
        stream = llm.log_stream_usage(self.summary(), mode="rag", trace_id="t-stream")
        # 生产者在内存里写的仍然**不是**同一个词（失败行是条目 id）：口径由账本兜住。
        self.assertEqual(("fb-a-model", "fb-a", "fb-a-model"),
                         (non_stream.model, failure.model, stream.model))
        usage_module.log_usage(non_stream)                 # 两条非流式路由调用点落库
        usage_module.log_usage(failure)                    # 流式那条已由 sink 落过
        rows = {row["trace_id"]: row for row in self.raw_rows()}
        self.assertEqual({"t-nonstream", "t-failure", "t-stream"}, set(rows))
        self.assertEqual({"fb-a-model"}, {row["model"] for row in rows.values()})
        self.assertEqual(("retryable", 503, 0), (rows["t-failure"]["error_type"],
                                                 rows["t-failure"]["status_code"],
                                                 rows["t-failure"]["success"]))
        self.assertEqual((1, 1), (rows["t-nonstream"]["success"],
                                  rows["t-stream"]["success"]))

    def test_the_model_override_alias_is_the_stored_value_on_every_path(self):
        """带别名时三条出口落在**别名**上：真正被调用的名字才是那一个词。

        这是 M2 更深的一半：如果账本只把条目 id 换成注册表声明名，override 生效时失败行
        会写 `registry-name`、成功行写 `prod-alias-2026`，同一模型在库里裂成两行。
        """
        self.use_registry(entry_of(id="fb-o", provider="openai", model="registry-name",
                                   external=True))
        self.use_settings(openai_api_key="sk-test-key")
        profile = profile_of("rag")
        with mock.patch.dict(os.environ, {"OPENAI_MODEL_OVERRIDE": "prod-alias-2026"}):
            usage_module.log_usage(llm._usage_from_failure(
                AllCandidatesFailedError(
                    (attempt("fb-o", "failed", "hard", 10.0, provider="openai"),)),
                profile, "rag", trace_id="t-failure", request_id=None))
            usage_module.log_usage(llm._usage_from_result(
                FallbackResult(response=LLMResponse(content="x", model="prod-alias-2026",
                                                    provider="openai"),
                               attempts=(attempt("fb-o", provider="openai"),),
                               selected_index=0),
                profile, "rag", trace_id="t-nonstream", request_id=None))
            llm.log_stream_usage(self.summary("fb-o", provider="openai"), mode="rag",
                                 trace_id="t-stream")
        rows = {row["trace_id"]: row for row in self.raw_rows()}
        self.assertEqual({"t-failure", "t-nonstream", "t-stream"}, set(rows))
        self.assertEqual({"prod-alias-2026"}, {row["model"] for row in rows.values()})

    def test_an_unmatchable_name_is_left_alone(self):
        """匹不到条目（模型被删 / provider 名不合法）⇒ 原样留那个可解释的名字，不猜。"""
        self.use_registry(entry_of(id="fb-a", model="fb-a-model"))
        usage_module.log_usage(record_at(-4, trace_id="t-ghost", model="deleted-entry"))
        self.assertEqual("deleted-entry", self.raw_rows()[0]["model"])


# ==========================================================================
# 12. lifespan 接线
# ==========================================================================
class WarmupWiringTests(_UsageFixture):
    def test_warmup_chains_the_gate_the_sink_and_the_table(self):
        with (mock.patch.object(usage_module, "registry_warmup") as gate,
              mock.patch.object(llm, "set_usage_sink") as setter):
            usage_module.warmup()
        gate.assert_called_once_with()
        self.assertEqual([usage_module.log_usage],
                         [call.args[0] for call in setter.call_args_list])

    def test_warmup_creates_a_table_a_fresh_deployment_does_not_have(self):
        fresh = self.db_path.parent / "fresh" / "conversations.db"
        usage_module.reset_usage_state()                          # 回到 env 源
        with (mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": str(fresh)}),
              mock.patch.object(usage_module, "registry_warmup"),
              mock.patch.object(llm, "set_usage_sink")):
            self.assertFalse(fresh.exists())
            usage_module.warmup()
        self.assertTrue(fresh.is_file())
        usage_module.init_usage_db(self.db_path)

    def test_warmup_is_a_full_noop_when_the_router_is_off(self):
        self.use_settings(llm_router_enabled=False)
        with (mock.patch.object(usage_module, "registry_warmup") as gate,
              mock.patch.object(llm, "set_usage_sink") as setter,
              mock.patch.object(usage_module, "init_usage_db") as init):
            usage_module.warmup()
        gate.assert_not_called()
        setter.assert_not_called()
        init.assert_not_called()

    def test_a_broken_table_still_boots_but_a_broken_registry_does_not(self):
        with (mock.patch.object(usage_module, "registry_warmup"),
              mock.patch.object(llm, "set_usage_sink"),
              mock.patch.object(usage_module, "init_usage_db",
                                side_effect=sqlite3.OperationalError("readonly"))):
            with self.assertLogs("app.llm.usage", level="WARNING"):
                self.assertIsNone(usage_module.warmup())           # 观测面 fail-open
        with (mock.patch.object(usage_module, "registry_warmup",
                                side_effect=RegistryError("注册表结构不合法")),
              mock.patch.object(llm, "set_usage_sink") as setter,
              mock.patch.object(usage_module, "init_usage_db") as init):
            with self.assertRaises(RegistryError):                 # 配置面 fail-fast
                usage_module.warmup()
        setter.assert_not_called()
        init.assert_not_called()

    def test_lifespan_calls_both_warmups_side_by_side(self):
        with (mock.patch.object(main_module, "warmup_identity_permissions") as identity,
              mock.patch.object(main_module, "warmup_llm_router") as router):
            with TestClient(fastapi_app):
                pass
        identity.assert_called_once_with()
        router.assert_called_once_with()

    def test_the_seam_autowires_without_any_change_in_the_package(self):
        """`usage_sink()` 的惰性解析 = T5 不需要回来改 T4：sink 未注册也照样落到真库。"""
        llm.set_usage_sink(None)
        self.assertIs(llm.usage_sink(), usage_module.log_usage)
        llm._log_usage(record_at(-5))
        self.assertEqual(1, len(self.raw_rows()))

    def test_the_late_bound_sink_writes_a_real_row_for_llm_complete(self):
        """端到端：sink **未注册**时 `llm.complete()` 的账真的落到库里（不是只解析到函数）。

        这条是从 T4 的 `test_usage_sink_falls_back_to_late_bound_app_llm_usage` 在 T5
        落地时**没能带过来**的那半枚断言：那一例旧钉用假模块证明「complete() 把账交给了
        惰性解析到的 sink」（`assertEqual(1, len(rows))` + `route_mode == "chat"`），改成
        三面之后它只断言 `usage_sink() is log_usage`，交付那一步在这一例里就没人管了。
        这里把它补回账本这一侧——用真 `log_usage`、真临时库、真 `complete()`。
        """
        health_patcher = mock.patch.object(fallback_module, "routing_health_view",
                                           lambda *args, **kwargs: {})
        health_patcher.start()
        self.addCleanup(health_patcher.stop)
        complete_patcher = mock.patch.object(
            provider_module, "complete",
            lambda model, req, timeout: LLMResponse(content="答", model=model.model,
                                                    provider=model.provider))
        complete_patcher.start()
        self.addCleanup(complete_patcher.stop)
        llm.set_usage_sink(None)                                   # 只靠惰性解析
        result = llm.complete([{"role": "user", "content": "你好"}], mode="chat",
                              trace_id="t-lazy")
        self.assertEqual("答", result.response.content)
        rows = self.raw_rows()
        self.assertEqual(1, len(rows))
        self.assertEqual(("t-lazy", "chat", "usage-fixture-model"),
                         (rows[0]["trace_id"], rows[0]["route_mode"], rows[0]["model"]))
        self.assertEqual(1, rows[0]["success"])


if __name__ == "__main__":
    unittest.main()
