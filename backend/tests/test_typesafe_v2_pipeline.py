"""Task 6：`retrieval.py` 判定段按 TypeSafe V2 管道重排（设计 §2/§3/§4/§6/§7）。

注入模式沿用 `tests/test_typesafe_retrieval.py`：假 store（patch `vector_search` /
`fetch_vectors`）+ 假 Cross-Encoder（`service._reranker`）+ 假判定服务
（patch `app.retrieval.typesafe_judgment_service`）。**全程零真实外呼**。

本文件钉的是只有"整合层"才有的两类语义：
1. 管道顺序：本地 CE 前置 → 语义去重 → 动态 TopK → 置信度路由 → 判定（带预算）→ diversify；
2. 门：五档各自的调用/应用面，以及 degraded / circuit_open / skipped 三条"判定不全"退路。

fix round 1 另补第三类（评审 (b) 矩阵缺口 + I2 裁决"尾部保留"）：**判定集 ≠ 返回集**——
未进判定的尾行按 CE 序留在结果尾部，应用支路的返回条数 ≥ min(top_k, 池)。
"""
from __future__ import annotations

import sys
import time
import unittest
from contextlib import ExitStack
from itertools import product
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.retrieval import RetrievalService
from app.resilience import TimeoutBudget
from app.typesafe_judgments import (
    JudgmentBatch,
    PassageJudgment,
    judgment_cache,
    reset_typesafe_stats,
    typesafe_judgment_service,
)
from app.typesafe_router import REASON_RISK, REASON_TOKENS, pick_candidate_count


# provider=local / mode=off 两条路的 timings 键集合必须**逐字等于**现网（V1）键集合：
# 判定段的新键只允许出现在 provider=typesafe 且 mode!=off 的支路（spec §2 不变式）。
V1_TIMING_KEYS = frozenset(
    {
        "vector_ms",
        "bm25_ms",
        "fusion_ms",
        "rerank_ms",
        "diversity_ms",
        "total_ms",
        "bm25_cache_hit",
        "parallel_hybrid",
        "fusion",
        "vector_query_instruction",
        "vector_candidates",
        "bm25_candidates",
        "rerank_candidates",
        "max_chunks_per_document",
        "returned_documents",
    }
)

# 判定段自造的 V2 timings 键（§7 的本地段计时）。
V2_STAGE_TIMING_KEYS = frozenset({"rerank_stage_ms", "dedup_ms", "judge_input_count"})

# 批次 metrics 的 19 枚键（与 `app/typesafe_judgments.py::base_metrics` 同集合）。
BATCH_METRIC_KEYS = frozenset(
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
        "typesafe_trigger",
        "typesafe_skipped",
        "typesafe_cache_hit",
        "typesafe_circuit_open",
        "typesafe_slow",
    }
)

# 路由免判时检索层自造的 metrics 键（没有批次可并入，故只有这几枚，不冒充全量）。
# `typesafe_reasons` 由**检索层**注入（判/免判两条路都有，段B2），不在批次 metrics 里。
ROUTER_SKIP_KEYS = frozenset(
    {
        "typesafe_enabled",
        "typesafe_mode",
        "typesafe_trigger",
        "typesafe_skipped",
        "typesafe_cache_hit",
        "typesafe_circuit_open",
        "typesafe_slow",
        "typesafe_skip",
        "typesafe_reasons",
    }
)

# 一条"高置信单一事实"问句：无风险词、无数字/参数、非复合（与 Task 4 用例同型）。
BENIGN_QUERY = "会议楼的预定规则是什么"
# 一条必然触发的问句：命中 RISK_MARKERS（保密/协议/违约）且复合。
RISKY_QUERY = "保密协议里违约怎么处理，同时薪资多久调一次"
# 一条 §4 compound 档问句（两个带问语标记的分句）：判定头部 = `typesafe_compound_candidates`。
COMPOUND_QUERY = "X200温度范围是多少，断网后又能缓存多久？"


def make_rows(count: int = 3) -> list[dict]:
    """候选行：content 末位即 id，假 reranker 据此反查打分。"""
    return [
        {
            "id": point_id,
            "file_name": f"{point_id}.md",
            "knowledge_base_id": "kb_product",
            "knowledge_base_name": "Product",
            "content": f"content {point_id}",
            "vector_raw_score": 0.9 - index / 10,
        }
        for index, point_id in enumerate(("a", "b", "c", "d")[:count])
    ]


class FakeReranker:
    """按 content 查表给 CE 原始分，并记录每次调用看到的池（id 顺序）。

    分差刻意做成整档：`normalize` 后 4/3/2/1 → 1.0/0.667/0.333/0.0，断言可读。
    """

    def __init__(self, scores: dict[str, float]):
        self.scores = scores
        self.pools: list[list[str]] = []

    def predict(self, pairs: list[list[str]]) -> list[float]:
        ids = [str(pair[1]).rsplit(" ", 1)[-1] for pair in pairs]
        self.pools.append(ids)
        return [self.scores[point_id] for point_id in ids]


def judgment(
    point_id: str,
    route: str,
    *,
    evidence: float = 0.0,
    contradiction: float = 0.0,
) -> PassageJudgment:
    return PassageJudgment(
        point_id=point_id,
        route=route,
        is_relevant=0.9,
        contains_answer_evidence=evidence,
        contradicts_query_premise=contradiction,
        contains_prompt_injection=0.0,
        model="jev-test",
        latency_ms=1.0,
        input_tokens=10,
        output_tokens=1,
    )


def pool_rows(count: int) -> list[dict]:
    """`count` 行候选池（id = `row-00..`）。

    `make_rows()` 最多四行，而"尾部保留"与 §4 的 4/6/8/12 档都要**判定头 < 池宽**才看得出
    尾行去哪了，故这些用例需要更宽的池。
    """
    return [
        {
            "id": f"row-{index:02d}",
            "file_name": f"row-{index:02d}.md",
            "knowledge_base_id": "kb_product",
            "knowledge_base_name": "Product",
            "content": f"content row-{index:02d}",
            "vector_raw_score": 1.0 - index / 100,
        }
        for index in range(count)
    ]


def wide_head_scores(count: int) -> dict[str, float]:
    """假 CE 分：top1 远高于 top2 ⇒ 归一化分差 ≈0.84 > `high_margin` ⇒ §4 走 min 档（3）。

    除首行外彼此等距，且 top1 归一化后是 1.0（≥ `confidence_floor`）⇒ 既不掉进 12 档、
    也不会因为地板信号把档位放宽。四行以上的池因此天然分成"判定头部 + 尾行"两段。
    """
    return {
        f"row-{index:02d}": (10.0 if index == 0 else 5.0 - index / 10)
        for index in range(count)
    }


def partial_judgment_batch(**overrides) -> JudgmentBatch:
    """只有 b 有判定的批次：一旦误应用，三行会被打成一两行（V1 对无判定的行是 `continue` 丢弃）。"""
    return JudgmentBatch(
        {"b": judgment("b", "include", evidence=0.99)},
        batch_metrics(**overrides),
    )


def ids_of(rows: list[dict]) -> list[str]:
    return [str(row["id"]) for row in rows]


def pool_ids(start: int = 0, stop: int = 12) -> list[str]:
    """`pool_rows()` 的 id 序列（半开区间），尾行/头部行的期望值都按它拼。"""
    return [f"row-{index:02d}" for index in range(start, stop)]


def score_map(values: tuple[float, ...]) -> dict[str, float]:
    """把一列**已归一化**的假 CE 分贴到 `row-00..` 上（首尾给 1.0/0.0 时 normalize 即恒等）。"""
    return {point_id: value for point_id, value in zip(pool_ids(0, len(values)), values)}


def batch_metrics(**overrides) -> dict:
    """一枚结构完整的批次 metrics（19 键），只覆盖用例关心的字段。"""
    metrics = {
        "typesafe_enabled": True,
        "typesafe_mode": settings.typesafe_mode,
        "typesafe_degraded": False,
        "typesafe_request_count": 3,
        "typesafe_input_tokens": 30,
        "typesafe_output_tokens": 3,
        "typesafe_estimated_cost_usd": 0.00000126,
        "typesafe_latency_p50_ms": 4.0,
        "typesafe_latency_p95_ms": 6.0,
        "typesafe_total_ms": 12.0,
        "typesafe_unauthorized_candidates_blocked": 0,
        "typesafe_route_counts": {"include": 1, "conflicting_evidence": 1, "exclude": 1},
        "typesafe_models": ["jev-test"],
        "typesafe_errors": [],
        "typesafe_trigger": True,
        "typesafe_skipped": None,
        "typesafe_cache_hit": 0,
        "typesafe_circuit_open": False,
        "typesafe_slow": False,
    }
    metrics.update(overrides)
    return metrics


class RecordingJudgmentService:
    """假判定服务：签名与 Task 5 冻结面一致（含 `budget` 关键字形参）。

    不传 batch 时自动回"全 include、证据 0"的批次 ⇒ 应用段是恒等变换，
    结构类用例因此可以只钉管道，不必先跟路由算法较劲。
    """

    def __init__(self, batch: JudgmentBatch | None = None):
        self.batch = batch
        self.calls: list[dict] = []

    @property
    def ids(self) -> list[list[str]]:
        return [call["ids"] for call in self.calls]

    def judge_candidates(self, query, rows, *, knowledge_base_ids, budget=None):
        self.calls.append(
            {
                "query": query,
                "ids": [str(row["id"]) for row in rows],
                "knowledge_base_ids": knowledge_base_ids,
                "budget": budget,
            }
        )
        if self.batch is not None:
            return self.batch
        judgments = {
            str(row["id"]): judgment(str(row["id"]), "include") for row in rows
        }
        return JudgmentBatch(judgments, batch_metrics(typesafe_request_count=len(rows)))


class PipelineTestsBase(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        for name, value in (
            ("retrieval_vector_query_instruction", ""),
            ("retrieval_max_chunks_per_document", 3),
            ("rerank_provider", "typesafe"),
            ("typesafe_enabled", True),
            ("typesafe_mode", "strict"),
        ):
            self.stack.enter_context(patch.object(settings, name, value))
        self.rows = make_rows()
        self.vector_patch = self.stack.enter_context(
            patch("app.retrieval.vector_store.vector_search", side_effect=lambda *a, **k: list(self.rows))
        )
        # 去重默认取不到向量 ⇒ `dedupe_by_similarity` 退化成恒等映射（各用例按需替换）。
        self.vectors_patch = self.stack.enter_context(
            patch("app.retrieval.vector_store.fetch_vectors", return_value={})
        )
        # Task 5 把缓存/熔断/滚动聚合做成了模块级共享态 ⇒ 管道用例从空账开始。
        judgment_cache.clear()
        reset_typesafe_stats()

    def tearDown(self) -> None:
        self.stack.close()
        judgment_cache.clear()
        reset_typesafe_stats()

    def make_service(self, scores: dict[str, float]) -> RetrievalService:
        service = RetrievalService()
        service._reranker = FakeReranker(scores)
        return service

    def search(
        self,
        service: RetrievalService,
        external: RecordingJudgmentService,
        *,
        query: str = BENIGN_QUERY,
        top_k: int = 3,
        mode: str = "vector",
        rerank: bool = True,
    ):
        with patch("app.retrieval.typesafe_judgment_service", external):
            return service.search_with_timings(
                query,
                top_k=top_k,
                mode=mode,
                rerank=rerank,
                knowledge_base_ids=["kb_product"],
            )


class SelectiveRouterTests(PipelineTestsBase):
    def test_high_confidence_single_fact_skips_with_zero_calls_and_ce_order(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        with patch.object(settings, "typesafe_mode", "selective"):
            rows, timings = self.search(service, external)

        # 成本目标的硬面：路由免判 ⇒ 判定服务一次都没被问。
        self.assertEqual(external.calls, [])
        self.assertFalse(timings["typesafe_trigger"])
        self.assertIs(timings["typesafe_skip"], True)
        self.assertEqual(timings["typesafe_skipped"], "router")
        self.assertEqual(timings["typesafe_cache_hit"], 0)
        self.assertFalse(timings["typesafe_circuit_open"])
        self.assertFalse(timings["typesafe_slow"])
        # 用户可见序 = 本地 CE 序（不再是 V1 的 RRF/hybrid 序）。
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])
        self.assertEqual([row["rerank_score"] for row in rows], [1.0, 0.666667, 0.0])
        self.assertNotIn("typesafe_route", rows[0])
        # skip 时判定段总时长 == 本地 CE 段（`rerank_ms = ce_ms + typesafe_total_ms`）。
        self.assertEqual(timings["rerank_ms"], timings["rerank_stage_ms"])
        self.assertEqual(timings["judge_input_count"], 3)

    def test_router_skip_bag_has_no_fake_batch_keys(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        with patch.object(settings, "typesafe_mode", "selective"):
            _, timings = self.search(service, external)

        self.assertTrue(ROUTER_SKIP_KEYS.issubset(set(timings)))
        self.assertNotIn("typesafe_request_count", timings)
        self.assertNotIn("typesafe_route_counts", timings)
        self.assertEqual(V2_STAGE_TIMING_KEYS.difference(set(timings)), set())

    def test_risk_signal_triggers_judgment_and_applies_routing(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            JudgmentBatch(
                {
                    "a": judgment("a", "exclude"),
                    "b": judgment("b", "include", evidence=0.95),
                    "c": judgment("c", "conflicting_evidence", contradiction=0.90),
                },
                batch_metrics(),
            )
        )

        with patch.object(settings, "typesafe_mode", "selective"):
            rows, timings = self.search(service, external, query=RISKY_QUERY)

        self.assertEqual(len(external.calls), 1)
        self.assertTrue(timings["typesafe_trigger"])
        self.assertIs(timings["typesafe_skip"], False)
        self.assertIsNone(timings["typesafe_skipped"])
        # spec §3 模式表：selective 的"应用路由=是" ⇒ exclude 的 a 被剔除，b/c 按证据强度排。
        self.assertEqual([row["id"] for row in rows], ["b", "c"])
        self.assertEqual(rows[1]["typesafe_route"], "conflicting_evidence")

    def test_selective_reports_trigger_reasons_on_the_judged_path(self) -> None:
        # 段B2 缺陷2：`should_judge` 的 reasons 必须进 timings（旧代码写作
        # `need, _reasons = should_judge(...)` 显式丢弃 ⇒ selective 标定只看得到"判/没判"。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        with patch.object(settings, "typesafe_mode", "selective"):
            _, timings = self.search(service, external, query=RISKY_QUERY)

        self.assertEqual(len(external.calls), 1)
        self.assertEqual(timings["typesafe_reasons"], ["compound", "risk"])
        # 值域契约：成员只可能是 §3 六 token ⇒ 白名单放行没有泄密面。
        self.assertTrue(set(timings["typesafe_reasons"]) <= set(REASON_TOKENS))
        # reasons 不改判定顺序也不新增外呼：它只是观测键，与批次 metrics 并列。
        self.assertIs(timings["typesafe_skip"], False)

    def test_selective_reports_trigger_reasons_on_the_router_skip_path(self) -> None:
        # 免判侧同样要带键（值为空数组）：标定要的是"为什么免判"的分布，缺键就等于
        # 只有判题那半边有数据；同时钉住"存在且为 list"，不靠前端猜 undefined。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        with patch.object(settings, "typesafe_mode", "selective"):
            _, timings = self.search(service, external)

        self.assertEqual(external.calls, [])
        self.assertIn("typesafe_reasons", timings)
        self.assertEqual(timings["typesafe_reasons"], [])
        self.assertIsInstance(timings["typesafe_reasons"], list)
        self.assertEqual(timings["typesafe_skipped"], "router")

    def test_reasons_are_reported_in_every_mode_without_changing_the_gate(self) -> None:
        # 恒判档带同一份信号读数（"selective 反事实"），但**门不许被观测改动**：
        # strict 在同样输入下依旧 1 次外呼、active 的免判条件依旧是"高置信单一事实"。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        _, strict_timings = self.search(service, external, query=RISKY_QUERY)
        self.assertEqual(strict_timings["typesafe_reasons"], ["compound", "risk"])
        self.assertEqual(len(external.calls), 1)
        self.assertIs(strict_timings["typesafe_skip"], False)

        external_reset = RecordingJudgmentService()
        with patch.object(settings, "typesafe_mode", "active"):
            _, active_timings = self.search(service, external_reset)
        self.assertEqual(active_timings["typesafe_reasons"], [])
        self.assertEqual(external_reset.calls, [])
        self.assertEqual(active_timings["typesafe_skipped"], "router")

    def test_reasons_key_always_present_and_token_valued(self) -> None:
        # 键恒在且恒为 list（任何一档、判与免判两条路都一样）：前端/脚本不必处理 undefined。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        for mode in ("strict", "shadow", "selective", "active"):
            for query in (BENIGN_QUERY, RISKY_QUERY, COMPOUND_QUERY):
                external = RecordingJudgmentService()
                with patch.object(settings, "typesafe_mode", mode):
                    _, timings = self.search(service, external, query=query)
                with self.subTest(mode=mode, query=query):
                    reasons = timings["typesafe_reasons"]
                    self.assertIsInstance(reasons, list)
                    self.assertTrue(set(reasons) <= set(REASON_TOKENS), reasons)
                    # 门与读数的唯一耦合：selective 判 ⇔ reasons 非空。
                    if mode == "selective":
                        self.assertEqual(bool(external.calls), bool(reasons))

    def test_active_skips_the_same_case_selective_skips(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        with patch.object(settings, "typesafe_mode", "active"):
            rows, timings = self.search(service, external)

        self.assertEqual(external.calls, [])
        self.assertEqual(timings["typesafe_skipped"], "router")
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])


class StrictModeTests(PipelineTestsBase):
    def test_strict_always_judges_applies_and_passes_budget(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            JudgmentBatch(
                {
                    "a": judgment("a", "exclude"),
                    "b": judgment("b", "include", evidence=0.95),
                    "c": judgment("c", "conflicting_evidence", contradiction=0.90),
                },
                batch_metrics(),
            )
        )

        rows, timings = self.search(service, external)

        self.assertEqual(len(external.calls), 1)
        self.assertEqual(external.calls[0]["ids"], ["a", "b", "c"])
        self.assertEqual(external.calls[0]["knowledge_base_ids"], ["kb_product"])
        # 需求 5：预算来自 Task 5 工厂，而不是检索层裸构造。
        self.assertIsInstance(external.calls[0]["budget"], TimeoutBudget)
        self.assertEqual([row["id"] for row in rows], ["b", "c"])
        self.assertEqual(timings["typesafe_request_count"], 3)
        self.assertEqual(timings["judge_input_count"], 3)
        # rerank_ms = 本地 CE 段 + 判定段（批次报 12.0ms）。
        self.assertAlmostEqual(
            timings["rerank_ms"] - timings["rerank_stage_ms"], 12.0, delta=0.02
        )
        self.assertIn("dedup_ms", timings)

    def test_budget_comes_from_the_settings_factory(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()
        sentinel = object()

        with patch(
            "app.retrieval.make_budget_from_settings", return_value=sentinel
        ) as factory:
            self.search(service, external)

        self.assertEqual(factory.call_count, 1)
        self.assertIs(external.calls[0]["budget"], sentinel)

    def test_budget_soft_and_hard_lines_follow_settings(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        with (
            patch.object(settings, "typesafe_soft_timeout_ms", 4000),
            patch.object(settings, "typesafe_hard_timeout_ms", 5000),
        ):
            self.search(service, external)

        budget = external.calls[0]["budget"]
        self.assertIsInstance(budget, TimeoutBudget)
        self.assertGreater(budget.remaining_ms(), 4000.0)
        self.assertLessEqual(budget.remaining_ms(), 5000.0)

    def test_budget_is_not_shared_across_judgment_batches(self) -> None:
        """段B2 缺陷1 定案钉：一条 `TimeoutBudget` 只活一个判定批次，批次之间不累计。

        spec §5「批次以 `typesafe_hard_timeout_ms` 包预算」⇒ 预算的语义对象是**一次判定段**，
        不是"一次查询会话"。这里用可控时钟跑两个批次（= 两次检索调用），中间把墙钟推走 5s：
        - 第一个批次的预算此刻必须已耗尽（它只该活到自己那一段）；
        - 第二个批次的预算必须**满额起步**（remaining == hard）。
        任何"把工厂提到循环外 / 做成模块级单例 / 跨批次传同一条预算"的实现，都会让第二批
        拿到负余额并凭空 `budget_exhausted`，这里立刻红。
        批次**内部** N 条逐判定请求共用同一条预算是规格本义（per-request timeout 取剩余），
        那半边由 `tests/test_typesafe_v2_core.py` 的预算用例钉。
        """
        now = {"t": 100.0}
        hard_ms = 3000.0

        def factory() -> TimeoutBudget:
            return TimeoutBudget(soft_ms=1200.0, hard_ms=hard_ms, clock=lambda: now["t"])

        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        with patch("app.retrieval.make_budget_from_settings", side_effect=factory) as made:
            self.search(service, external)
            now["t"] += hard_ms / 1000.0 + 2.0  # 第一个批次"跑了" 5s：远超硬线
            self.search(service, external)

        self.assertEqual(made.call_count, 2)
        self.assertEqual(len(external.calls), 2)
        first = external.calls[0]["budget"]
        second = external.calls[1]["budget"]
        self.assertIsNot(first, second)
        self.assertTrue(first.exhausted())
        self.assertFalse(second.exhausted())
        self.assertAlmostEqual(second.remaining_ms(), hard_ms, places=6)
        self.assertFalse(second.over_soft())

    def test_high_confidence_single_fact_still_judged_under_strict(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        rows, timings = self.search(service, external)

        self.assertEqual(len(external.calls), 1)
        self.assertTrue(timings["typesafe_trigger"])
        self.assertIs(timings["typesafe_skip"], False)
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])

    def test_rerank_ms_is_ce_section_plus_judging_section(self) -> None:
        """`rerank_ms = ce_ms + typesafe_total_ms`（需求 7 的口径定义）。

        用一只会"烧时间"的假 CE（每次打分 ≥5ms）把 CE 段顶出 `round(...,2)` 的可断言区间，
        否则两段都趋近 0ms，退回 V1 口径（`rerank_ms = typesafe_total_ms`）也测不出来。
        """

        class SlowReranker(FakeReranker):
            def predict(self, pairs):
                time.sleep(0.005)
                return super().predict(pairs)

        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        service._reranker = SlowReranker({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        _rows, timings = self.search(service, external)

        self.assertGreaterEqual(timings["rerank_stage_ms"], 2.0)
        self.assertAlmostEqual(
            timings["rerank_ms"] - timings["rerank_stage_ms"], 12.0, delta=0.02
        )
        self.assertGreater(timings["rerank_ms"], 12.0)


class ShadowModeTests(PipelineTestsBase):
    def test_shadow_calls_service_but_never_applies_routing(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            JudgmentBatch(
                {
                    "a": judgment("a", "exclude"),
                    "b": judgment("b", "include", evidence=0.95),
                },
                batch_metrics(typesafe_mode="shadow"),
            )
        )

        with patch.object(settings, "typesafe_mode", "shadow"):
            rows, timings = self.search(service, external)

        self.assertEqual(len(external.calls), 1)
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])
        self.assertNotIn("typesafe_route", rows[0])
        self.assertFalse(timings["typesafe_degraded"])

    def test_shadow_and_degraded_share_one_cross_encoder_order(self) -> None:
        # 一份"CE 序 ≠ RRF 序"的分数：两条退路必须给出**同一个** CE 序。
        scores = {"a": 1.0, "b": 2.0, "c": 3.0}
        shadow_external = RecordingJudgmentService(
            JudgmentBatch({"a": judgment("a", "include")}, batch_metrics())
        )
        degraded_external = RecordingJudgmentService(
            JudgmentBatch(
                {"c": judgment("c", "include", evidence=0.9)},
                batch_metrics(
                    typesafe_degraded=True,
                    typesafe_errors=["TypeSafeAPITimeoutError"],
                ),
            )
        )

        with patch.object(settings, "typesafe_mode", "shadow"):
            shadow_rows, shadow_timings = self.search(
                self.make_service(scores), shadow_external
            )
        degraded_rows, degraded_timings = self.search(
            self.make_service(scores), degraded_external
        )

        self.assertEqual([row["id"] for row in shadow_rows], ["c", "b", "a"])
        self.assertEqual([row["id"] for row in degraded_rows], ["c", "b", "a"])
        self.assertNotIn("typesafe_route", degraded_rows[0])
        self.assertTrue(degraded_timings["typesafe_degraded"])
        self.assertFalse(shadow_timings["typesafe_degraded"])
        # 两条都"判过但没应用"⇒ rerank_ms 同为 本地 CE 段 + 批次 12.0ms。
        for timings in (shadow_timings, degraded_timings):
            self.assertAlmostEqual(timings["rerank_ms"], timings["rerank_stage_ms"] + 12.0, delta=0.02)


class ApplyGateFaultPathTests(PipelineTestsBase):
    """Task 5 交接硬前置：degraded / circuit_open / skipped 三条"判定不全"都不得应用。

    本类固定在 strict 下跑（恒判 ⇒ 一定走到应用门），"另两档 × 三信号"的矩阵缺口由
    `ApplyGateModeMatrixTests` 补齐。
    """

    def partial_batch(self, **overrides) -> JudgmentBatch:
        return partial_judgment_batch(**overrides)

    def assert_fell_back_to_ce_order(self, rows: list[dict]) -> None:
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])
        for row in rows:
            self.assertNotIn("typesafe_route", row)

    def test_circuit_open_falls_back_to_non_empty_cross_encoder_order(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            self.partial_batch(
                typesafe_circuit_open=True,
                typesafe_skipped="circuit_open",
                typesafe_trigger=False,
                typesafe_request_count=0,
            )
        )

        rows, timings = self.search(service, external)

        self.assertTrue(timings["typesafe_circuit_open"])
        self.assertIs(timings["typesafe_skip"], True)
        self.assertFalse(timings["typesafe_degraded"])
        self.assert_fell_back_to_ce_order(rows)

    def test_budget_exhausted_skip_does_not_apply(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            self.partial_batch(
                typesafe_skipped="budget_exhausted", typesafe_degraded=True
            )
        )

        rows, timings = self.search(service, external)

        self.assertEqual(timings["typesafe_skipped"], "budget_exhausted")
        self.assert_fell_back_to_ce_order(rows)

    def test_degraded_without_skip_reason_does_not_apply(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(self.partial_batch(typesafe_degraded=True))

        rows, _timings = self.search(service, external)

        self.assert_fell_back_to_ce_order(rows)

    def test_any_skip_reason_is_never_applied_even_without_degraded_flag(self) -> None:
        # 防线：批次自己报告"这一批被跳过了"（判定层的 mode=off 早退就是 degraded=False +
        # skipped="off" 这种形状），检索层也不得应用——应用门读的是三个独立信号，不是等价式。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            self.partial_batch(
                typesafe_skipped="off", typesafe_trigger=False, typesafe_request_count=0
            )
        )

        rows, timings = self.search(service, external)

        self.assertIs(timings["typesafe_skip"], True)
        self.assertFalse(timings["typesafe_degraded"])
        self.assert_fell_back_to_ce_order(rows)

    def test_circuit_open_flag_is_read_independently_of_the_skip_string(self) -> None:
        # Task 5 today always pairs `typesafe_circuit_open=True` with `skipped="circuit_open"`,
        # 但应用门是**三个独立信号的合取**、不是等价式：只要熔断旗立着，哪怕没有 skip 串
        # （未来判定层新增 skip 词表、或两读之间配置被改），也绝不应用。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            self.partial_batch(typesafe_circuit_open=True, typesafe_skipped=None)
        )

        rows, timings = self.search(service, external)

        self.assertTrue(timings["typesafe_circuit_open"])
        self.assertIs(timings["typesafe_skip"], False)
        self.assert_fell_back_to_ce_order(rows)

    def test_healthy_strict_batch_applies_exclusion_and_evidence_sort(self) -> None:
        # 反证：三个否决条件全绿（degraded/circuit_open 假、skipped None）⇒ strict 必须应用。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            JudgmentBatch(
                {
                    "a": judgment("a", "exclude"),
                    "b": judgment("b", "include", evidence=0.5),
                    "c": judgment("c", "include", evidence=0.9),
                },
                batch_metrics(),
            )
        )

        rows, _timings = self.search(service, external)

        self.assertEqual([row["id"] for row in rows], ["c", "b"])


class ApplyGateModeMatrixTests(PipelineTestsBase):
    """应用门的"模式 × 否决信号"矩阵缺口（fix round 1 / 评审 (b)）。

    `ApplyGateFaultPathTests` 的五条全在 strict 下跑（strict 恒判 ⇒ 必定走到应用门），于是
    selective/active 这两档"判了、但判定不全"的六格、以及 shadow+circuit_open 一格都没人管：
    把应用档集合写宽一格（shadow 也应用）或把否决信号读漏一格，现网结果集就变了。
    """

    #: 三条"判定不全"的否决信号 → (批次 metrics 覆盖, timings 里必须看得见的信号键)
    FAULTS: tuple[tuple[str, dict[str, object], str], ...] = (
        ("degraded", {"typesafe_degraded": True}, "typesafe_degraded"),
        (
            "circuit_open",
            {"typesafe_circuit_open": True, "typesafe_skipped": "circuit_open"},
            "typesafe_circuit_open",
        ),
        (
            "budget_exhausted",
            {"typesafe_degraded": True, "typesafe_skipped": "budget_exhausted"},
            "typesafe_skipped",
        ),
    )

    def assert_application_did_not_happen(
        self, rows: list[dict], timings: dict, signal_key: str
    ) -> None:
        # 否决信号本身要看得见（否则这一格是"批次没坏"的空断言）。
        self.assertTrue(timings[signal_key], f"否决信号 {signal_key} 没进 timings")
        # 结果仍是本地 CE 序 a,b,c：一旦误应用，三行会被打成 1 行（批次里只有 b 有判定）。
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])
        for row in rows:
            self.assertNotIn("typesafe_route", row)
            self.assertNotIn("typesafe_contains_answer_evidence", row)

    def test_selective_and_active_never_apply_an_incomplete_batch(self) -> None:
        for mode, (fault, overrides, signal_key) in product(
            ("selective", "active"), self.FAULTS
        ):
            with self.subTest(mode=mode, fault=fault):
                service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
                external = RecordingJudgmentService(
                    partial_judgment_batch(**overrides)
                )
                with patch.object(settings, "typesafe_mode", mode):
                    rows, timings = self.search(service, external, query=RISKY_QUERY)

                # 前置：这一格确实进了判定层（否则"没应用"只是路由免判造成的空断言）。
                self.assertEqual(len(external.calls), 1)
                self.assertEqual(external.calls[0]["ids"], ["a", "b", "c"])
                self.assert_application_did_not_happen(rows, timings, signal_key)

    def test_shadow_with_circuit_open_keeps_the_cross_encoder_order(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService(
            partial_judgment_batch(
                typesafe_circuit_open=True,
                typesafe_skipped="circuit_open",
                typesafe_trigger=False,
                typesafe_request_count=0,
            )
        )

        with patch.object(settings, "typesafe_mode", "shadow"):
            rows, timings = self.search(service, external)

        self.assertEqual(len(external.calls), 1)
        self.assert_application_did_not_happen(rows, timings, "typesafe_circuit_open")
        self.assertIs(timings["typesafe_skip"], True)

    def test_shadow_never_reports_the_router_skip(self) -> None:
        # `typesafe_skipped == "router"` 是检索层为"免判"自造的那枚取值：shadow 恒判 ⇒ 它
        # **绝不**出现在 shadow 的 timings 里。同一份输入在 selective 下确实产出 "router"，
        # 这条对照留在同一个用例里，免得断言对着空集成立。
        scores = {"a": 4.0, "b": 3.0, "c": 1.0}
        shadow_external = RecordingJudgmentService()
        with patch.object(settings, "typesafe_mode", "shadow"):
            rows, timings = self.search(self.make_service(scores), shadow_external)

        self.assertEqual(len(shadow_external.calls), 1)
        self.assertNotEqual(timings["typesafe_skipped"], "router")
        self.assertIsNone(timings["typesafe_skipped"])
        self.assertIs(timings["typesafe_skip"], False)
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])

        selective_external = RecordingJudgmentService()
        with patch.object(settings, "typesafe_mode", "selective"):
            _, selective_timings = self.search(
                self.make_service(scores), selective_external
            )
        self.assertEqual(selective_external.calls, [])
        self.assertEqual(selective_timings["typesafe_skipped"], "router")

    def test_typesafe_slow_is_passed_through_from_the_batch(self) -> None:
        # §7 的慢样本旗标只有判定层知道（Task 5 的 latency/cost 判定）⇒ 检索层原样透传。
        for slow in (True, False):
            with self.subTest(typesafe_slow=slow):
                service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
                external = RecordingJudgmentService(
                    JudgmentBatch(
                        {pid: judgment(pid, "include") for pid in ("a", "b", "c")},
                        batch_metrics(typesafe_slow=slow),
                    )
                )

                _rows, timings = self.search(service, external)

                # 前置：这一格真的打到了判定层（本类固定在 strict 恒判下跑）。缺了它，
                # `slow=False` 那格会在"检索层自造的零外呼替身"上空过——键在、值也对，
                # 但透传的**不是批次里的东西**，等于没测。
                self.assertEqual(len(external.calls), 1)
                self.assertIs(timings["typesafe_slow"], slow)

    def test_unknown_mode_raises_instead_of_defaulting_to_active(self) -> None:
        # M7：调用门原来写成"else ⇒ active"，未来加第六档会**静默按 active 免判**
        # （一个该花钱的档位悄悄变成省钱的档位，不报错也没观测面）。现在显式点名四档 + 抛。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()
        with patch.object(settings, "typesafe_mode", "paranoid"):
            with self.assertRaisesRegex(ValueError, "未知 TypeSafe 模式"):
                self.search(service, external)
        self.assertEqual(external.calls, [])

        head = [
            {"id": "a", "file_name": "a.md", "rerank_score": 1.0},
            {"id": "b", "file_name": "b.md", "rerank_score": 0.5},
        ]
        # 四档逐一点名：strict/shadow 恒判，selective/active 在这份高置信单一事实输入上免判。
        # 段B2 起返回值是 `(need, reasons)` ⇒ 断言**逐元素**写，绝不写 `assertTrue(元组)`：
        # `(False, [])` 也是真值，那样这四行会全部空过。
        self.assertEqual(service._should_judge_by_mode("strict", BENIGN_QUERY, head), (True, []))
        self.assertEqual(service._should_judge_by_mode("shadow", BENIGN_QUERY, head), (True, []))
        self.assertEqual(
            service._should_judge_by_mode("selective", BENIGN_QUERY, head), (False, [])
        )
        self.assertEqual(service._should_judge_by_mode("active", BENIGN_QUERY, head), (False, []))
        # selective 免判的那条触发问句：reasons 非空且是 §3 六 token 的子集（risk + compound）。
        need, reasons = service._should_judge_by_mode("selective", RISKY_QUERY, head)
        self.assertTrue(need)
        self.assertTrue(reasons)
        self.assertTrue(set(reasons) <= set(REASON_TOKENS))
        self.assertIn(REASON_RISK, reasons)
        # 恒判档也带同一份信号读数（selective 的调用门被绕过，观测面不绕过）⇒ 一轮 strict
        # 就是 selective 的反事实标定素材。
        self.assertEqual(service._should_judge_by_mode("strict", RISKY_QUERY, head), (True, reasons))
        self.assertEqual(service._should_judge_by_mode("shadow", RISKY_QUERY, head), (True, reasons))
        self.assertEqual(
            service._should_judge_by_mode("active", RISKY_QUERY, head), (True, reasons)
        )
        # off 由 `use_local_reranker` 支路接走，不该出现在这里 ⇒ 同样抛，不静默降级。
        with self.assertRaisesRegex(ValueError, "未知 TypeSafe 模式"):
            service._should_judge_by_mode("off", BENIGN_QUERY, head)


class DedupAndDynamicTopKTests(PipelineTestsBase):
    def test_near_duplicate_vectors_are_merged_before_judging(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()
        # b 与 a 的 cosine≈0.99997 ≥ 默认 0.97 ⇒ 合并保留高分块 a；c 正交 ⇒ 保留。
        self.vectors_patch.return_value = {
            "a": [1.0, 0.0],
            "b": [0.99997, 0.008],
            "c": [0.0, 1.0],
        }

        rows, timings = self.search(service, external)

        self.assertEqual(external.calls[0]["ids"], ["a", "c"])
        self.assertEqual(timings["judge_input_count"], 2)
        self.assertEqual([row["id"] for row in rows], ["a", "c"])
        self.assertGreaterEqual(timings["dedup_ms"], 0.0)

    def test_missing_vectors_keep_every_row(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()
        self.vectors_patch.return_value = {}

        rows, timings = self.search(service, external)

        self.assertEqual(external.calls[0]["ids"], ["a", "b", "c"])
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])
        self.assertEqual(timings["judge_input_count"], 3)

    def test_vectors_are_fetched_once_for_the_cross_encoder_pool(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()
        seen: list[list[str]] = []

        def fake_fetch(point_ids):
            seen.append(list(point_ids))
            return {}

        self.vectors_patch.side_effect = fake_fetch
        self.search(service, external)

        self.assertEqual(seen, [["a", "b", "c"]])

    def test_judge_input_count_matches_dynamic_topk(self) -> None:
        # 四行、CE 分差 0.333 > high_margin ⇒ §4 走 min_candidates=3 档，判定头部正好 3 行。
        self.rows = make_rows(4)
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0})
        external = RecordingJudgmentService()

        _, timings = self.search(service, external, top_k=4)

        scored = [
            {"id": "a", "file_name": "a.md", "rerank_score": 1.0},
            {"id": "b", "file_name": "b.md", "rerank_score": 0.666667},
            {"id": "c", "file_name": "c.md", "rerank_score": 0.333333},
            {"id": "d", "file_name": "d.md", "rerank_score": 0.0},
        ]
        self.assertEqual(
            timings["judge_input_count"], pick_candidate_count(BENIGN_QUERY, scored)
        )
        self.assertEqual(timings["judge_input_count"], 3)
        self.assertEqual(external.calls[0]["ids"], ["a", "b", "c"])
        self.assertEqual(timings["rerank_candidates"], 4)

    def test_ce_pool_widens_to_the_low_confidence_dynamic_tier(self) -> None:
        # CE 池必须 ≥ 最宽档（low_confidence 12），否则 §4 的 12 档永远拿不满输入。
        self.rows = [
            {
                "id": f"row-{index:02d}",
                "file_name": f"row-{index:02d}.md",
                "knowledge_base_id": "kb_product",
                "knowledge_base_name": "Product",
                "content": f"content row-{index:02d}",
                "vector_raw_score": 1.0 - index / 100,
            }
            for index in range(15)
        ]
        # 全零分 ⇒ normalize 给 0.0 ⇒ top1 落在 confidence_floor 之下 ⇒ 12 档。
        scores = {f"row-{index:02d}": 0.0 for index in range(15)}
        service = self.make_service(scores)
        external = RecordingJudgmentService()

        _, timings = self.search(service, external, top_k=3)

        self.assertEqual(len(service._reranker.pools[0]), 12)
        self.assertEqual(timings["rerank_candidates"], 12)
        self.assertEqual(timings["judge_input_count"], 12)
        self.assertEqual(len(external.calls[0]["ids"]), 12)

    def test_ce_pool_never_smaller_than_requested_top_k(self) -> None:
        self.rows = make_rows(4)
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0})
        external = RecordingJudgmentService()

        rows, timings = self.search(service, external, top_k=4)

        self.assertEqual(timings["rerank_candidates"], 4)
        # fix round 1（"尾部保留"裁决）：判定头部仍是 §4 的 min 档 3 行 —— `judge_input_count`
        # 语义不动 —— 但没进判定的 d 不再凭空消失 ⇒ 返回条数回到 min(top_k, 池) = 4。
        self.assertEqual(timings["judge_input_count"], 3)
        self.assertEqual(external.calls[0]["ids"], ["a", "b", "c"])
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c", "d"])
        self.assertGreaterEqual(len(rows), min(4, len(self.rows)))


class TailRetentionTests(PipelineTestsBase):
    """判定集与返回集解耦（fix round 1 / I2 主控裁决"尾部保留"）。

    §4 的动态 TopK 天然允许"进判定的行"少于池宽（min 档 3 < top_k 5），而 V1 的交付语义是
    "只交出有判定的行"（无判定 ⇒ `continue` 丢弃）。两条搬到一起就成了：**未进判定的尾行被
    静默丢掉**，exclude 越多结果越短，全判 exclude 时返回空结果。裁决后的口径是"尾行按 CE
    序留在结果尾部"，这里钉住它的三条面（+ 退化成一行的边界）。
    """

    POOL = 12

    def test_all_judged_rows_excluded_still_returns_the_tail(self) -> None:
        # 池 12、min 档判 3、三条全判 exclude ⇒ 已判行为空，结果 = 尾行（9 条）截到 top_k。
        self.rows = pool_rows(self.POOL)
        judged = pool_ids(0, 3)
        external = RecordingJudgmentService(
            JudgmentBatch(
                {point_id: judgment(point_id, "exclude") for point_id in judged},
                batch_metrics(typesafe_request_count=len(judged)),
            )
        )
        top_k = 5

        rows, timings = self.search(
            self.make_service(wide_head_scores(self.POOL)), external, top_k=top_k
        )

        self.assertEqual(timings["judge_input_count"], 3)
        self.assertEqual(external.calls[0]["ids"], judged)
        self.assertTrue(rows, "全判 exclude 就返回空结果 = 尾部保留没生效")
        self.assertGreaterEqual(len(rows), min(top_k, len(self.rows)))
        # 尾行保持彼此间的 CE 序，且不带任何判定字段（它们压根没进判定）。
        self.assertEqual(ids_of(rows), pool_ids(3, 8))
        for row in rows:
            self.assertNotIn("typesafe_route", row)
            self.assertNotIn("typesafe_contains_answer_evidence", row)

    def test_partial_exclusion_keeps_evidence_order_then_the_ce_ordered_tail(self) -> None:
        # 3 行被 exclude 但池 12 ⇒ 返回 ≥ top_k 且非空；已判行按证据分在前、尾行接在其后。
        self.rows = pool_rows(self.POOL)
        external = RecordingJudgmentService(
            JudgmentBatch(
                {
                    "row-00": judgment("row-00", "exclude"),
                    "row-01": judgment("row-01", "include", evidence=0.40),
                    "row-02": judgment("row-02", "include", evidence=0.90),
                },
                batch_metrics(typesafe_request_count=3),
            )
        )
        top_k = 5

        rows, timings = self.search(
            self.make_service(wide_head_scores(self.POOL)), external, top_k=top_k
        )

        self.assertEqual(timings["judge_input_count"], 3)
        self.assertGreaterEqual(len(rows), min(top_k, len(self.rows)))
        self.assertEqual(
            ids_of(rows),
            # 证据序 0.9 > 0.4 在前，被 exclude 的 row-00 消失，尾行（未判定）原序接在后。
            ["row-02", "row-01"] + pool_ids(3, 6),
        )
        self.assertTrue(all("typesafe_route" in row for row in rows[:2]))
        self.assertTrue(all("typesafe_route" not in row for row in rows[2:]))

    def test_compound_query_dedupes_then_excludes_without_losing_the_tail(self) -> None:
        # 复合 + 去重后的 exclude：池 12 去掉一条近似重复 ⇒ 11，compound 档判 8 ⇒ 尾行 3。
        self.rows = pool_rows(self.POOL)
        self.vectors_patch.return_value = {
            "row-00": [1.0, 0.0],
            "row-01": [0.99997, 0.008],  # 与 row-00 cosine≈0.99997 ≥ 0.97 ⇒ 合并保留高分块
        }
        judged = pool_ids(0, 1) + pool_ids(2, 9)
        excluded = {"row-00", "row-04"}
        external = RecordingJudgmentService(
            JudgmentBatch(
                {
                    point_id: judgment(
                        point_id, "exclude" if point_id in excluded else "include"
                    )
                    for point_id in judged
                },
                batch_metrics(typesafe_request_count=len(judged)),
            )
        )
        top_k = 9

        rows, timings = self.search(
            self.make_service(wide_head_scores(self.POOL)),
            external,
            query=COMPOUND_QUERY,
            top_k=top_k,
        )

        self.assertEqual(len(judged), 8)
        self.assertEqual(timings["judge_input_count"], 8)
        self.assertEqual(external.calls[0]["ids"], judged)
        # `rerank_candidates` 是 CE 段出口（去重前）的池宽；去重掉的 1 行不占判定名额。
        self.assertEqual(timings["rerank_candidates"], self.POOL)
        self.assertGreaterEqual(len(rows), min(top_k, 11))
        self.assertEqual(
            ids_of(rows),
            [pid for pid in judged if pid not in excluded] + pool_ids(9, 12),
        )

    def test_single_row_pool_has_no_tail_and_follows_the_route(self) -> None:
        # 退化档：池只剩 1 行 ⇒ 判定头部=1、尾行=0。include 必须留下它，exclude 才会空手。
        for route, expected in (("include", ["row-00"]), ("exclude", [])):
            with self.subTest(route=route):
                self.rows = pool_rows(1)
                external = RecordingJudgmentService(
                    JudgmentBatch(
                        {"row-00": judgment("row-00", route)},
                        batch_metrics(typesafe_request_count=1),
                    )
                )

                rows, timings = self.search(
                    self.make_service({"row-00": 7.0}), external, top_k=3
                )

                self.assertEqual(timings["judge_input_count"], 1)
                self.assertEqual(external.calls[0]["ids"], ["row-00"])
                self.assertEqual(ids_of(rows), expected)


class DynamicTopKTierTests(PipelineTestsBase):
    """§4 五档在**管道层**的落点（评审 (b)：现网只钉了 min/compound/low-confidence 三档）。

    档位分差刻意做成整档：min 档 3（分差 > `high_margin`）、4 档
    （`medium_margin` < 分差 ≤ `high_margin`）、max 档 6（分差 ≤ `medium_margin`）。
    """

    POOL = 6

    def test_medium_margin_tier_judges_four_rows_and_leaves_two_unjudged(self) -> None:
        self.rows = pool_rows(self.POOL)
        # 归一化即原值 ⇒ top1-top2 = 0.20 ∈ (medium 0.10, high 0.25] ⇒ §4 的 4 档。
        scores = score_map((1.0, 0.8, 0.6, 0.4, 0.2, 0.0))
        external = RecordingJudgmentService()

        rows, timings = self.search(
            self.make_service(scores), external, top_k=self.POOL
        )

        self.assertEqual(timings["judge_input_count"], 4)
        self.assertEqual(external.calls[0]["ids"], pool_ids(0, 4))
        # 头 4 行带判定字段、尾 2 行没有 ⇒ "判定集 ≠ 返回集"在这一档是可观测的。
        self.assertEqual(ids_of(rows), pool_ids(0, self.POOL))
        self.assertTrue(all("typesafe_route" in row for row in rows[:4]))
        self.assertTrue(all("typesafe_route" not in row for row in rows[4:]))

    def test_narrow_margin_tier_judges_the_full_max_candidates_pool(self) -> None:
        self.rows = pool_rows(self.POOL)
        # top1-top2 = 0.02 ≤ medium_margin ⇒ max 档（`typesafe_max_candidates` = 6）= 整池。
        scores = score_map((1.0, 0.98, 0.5, 0.4, 0.3, 0.0))
        external = RecordingJudgmentService()

        rows, timings = self.search(
            self.make_service(scores), external, top_k=self.POOL
        )

        self.assertEqual(
            timings["judge_input_count"], int(settings.typesafe_max_candidates)
        )
        self.assertEqual(timings["judge_input_count"], self.POOL)
        self.assertEqual(external.calls[0]["ids"], pool_ids(0, self.POOL))
        self.assertEqual(len(rows), self.POOL)
        self.assertTrue(all("typesafe_route" in row for row in rows))


class ModeMonotonicityTests(PipelineTestsBase):
    """模式单调性抽样：同一份 CE 池下，selective 免判 ⇒ active 也必须免判。

    Task 4 用 `is_high_confidence_single_fact` 的收紧定义保证 active 免判集
    ⊆ selective 免判集；这里是**管道层**的复验（走真实 router 函数 + 真实检索段），
    防止接线时把两档的判定条件写反或写漏。
    """

    SCENARIOS: tuple[tuple[str, dict[str, float]], ...] = (
        (BENIGN_QUERY, {"a": 4.0, "b": 3.0, "c": 1.0}),          # 高置信单一事实
        (BENIGN_QUERY, {"a": 4.0, "b": 3.9, "c": 1.0}),           # 分差极窄
        (BENIGN_QUERY, {"a": 0.0, "b": 0.0, "c": 0.0}),           # 全员地板下
        (RISKY_QUERY, {"a": 4.0, "b": 3.0, "c": 1.0}),            # 风险词
        ("X200 的工作温度是多少", {"a": 4.0, "b": 3.0, "c": 1.0}),  # 数字/参数
        ("设备支持哪些接口", {"a": 4.0, "b": 2.5, "c": 1.0}),      # 中间档分差
    )

    def test_selective_skip_implies_active_skip(self) -> None:
        skipped_by_selective = 0
        for query, scores in self.SCENARIOS:
            with self.subTest(query=query, scores=tuple(sorted(scores.items()))):
                selective_external = RecordingJudgmentService()
                active_external = RecordingJudgmentService()
                with patch.object(settings, "typesafe_mode", "selective"):
                    _, selective_timings = self.search(
                        self.make_service(scores), selective_external, query=query
                    )
                with patch.object(settings, "typesafe_mode", "active"):
                    _, active_timings = self.search(
                        self.make_service(scores), active_external, query=query
                    )

                selective_skipped = selective_timings["typesafe_skipped"] == "router"
                active_skipped = active_timings["typesafe_skipped"] == "router"
                if selective_skipped:
                    skipped_by_selective += 1
                    self.assertTrue(
                        active_skipped,
                        f"模式倒退：selective 免判而 active 判了 —— {query}",
                    )
                self.assertEqual(
                    selective_timings["judge_input_count"],
                    active_timings["judge_input_count"],
                )

        self.assertGreater(skipped_by_selective, 0, "抽样里一个免判都没有 ⇒ 断言是空的")

    def test_active_and_selective_both_apply_when_they_judge(self) -> None:
        for mode in ("selective", "active"):
            with self.subTest(mode=mode):
                service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
                external = RecordingJudgmentService(
                    JudgmentBatch(
                        {
                            "a": judgment("a", "exclude"),
                            "b": judgment("b", "include", evidence=0.9),
                            "c": judgment("c", "include", evidence=0.4),
                        },
                        batch_metrics(),
                    )
                )
                with patch.object(settings, "typesafe_mode", mode):
                    rows, _timings = self.search(service, external, query=RISKY_QUERY)

                # spec §3：两档的"应用路由"都是"是" ⇒ exclude 必须落地。
                self.assertEqual([row["id"] for row in rows], ["b", "c"])


class InvariantPathTests(PipelineTestsBase):
    def test_provider_local_matches_production_key_set_and_order(self) -> None:
        external = RecordingJudgmentService()
        with patch.object(settings, "rerank_provider", "local"):
            rows, timings = self.search(
                self.make_service({"a": 1.0, "b": 3.0, "c": 2.0}), external
            )

        self.assertEqual(external.calls, [])
        self.assertEqual([row["id"] for row in rows], ["b", "c", "a"])
        self.assertEqual([row["rerank_score"] for row in rows], [1.0, 0.5, 0.0])
        self.assertEqual(set(timings), set(V1_TIMING_KEYS))
        # 不变式路连"为去重取向量"都不该发生（M4）：多一次 Qdrant 往返就是白付的延迟。
        self.assertEqual(self.vectors_patch.call_count, 0)

    def test_typesafe_disabled_matches_local_path_field_for_field(self) -> None:
        scores = {"a": 1.0, "b": 3.0, "c": 2.0}
        with patch.object(settings, "typesafe_enabled", False):
            off_rows, off_timings = self.search(
                self.make_service(scores), RecordingJudgmentService()
            )
        with patch.object(settings, "rerank_provider", "local"):
            local_rows, local_timings = self.search(
                self.make_service(scores), RecordingJudgmentService()
            )

        self.assertEqual(
            [row["id"] for row in off_rows], [row["id"] for row in local_rows]
        )
        self.assertEqual(
            [row["rerank_score"] for row in off_rows],
            [row["rerank_score"] for row in local_rows],
        )
        self.assertEqual(set(off_timings) - {"total_ms"}, set(local_timings) - {"total_ms"})
        self.assertEqual(set(off_timings), set(V1_TIMING_KEYS))
        self.assertEqual(self.vectors_patch.call_count, 0)

    def test_mode_off_with_typesafe_enabled_uses_cross_encoder_path(self) -> None:
        # 硬前置：mode=off 并入 use_local_reranker，否则判定层关掉会连精排一起消失。
        external = RecordingJudgmentService()
        with patch.object(settings, "typesafe_mode", "off"):
            rows, timings = self.search(
                self.make_service({"a": 1.0, "b": 3.0, "c": 2.0}), external
            )

        self.assertEqual(external.calls, [])
        self.assertEqual([row["id"] for row in rows], ["b", "c", "a"])
        self.assertEqual(set(timings), set(V1_TIMING_KEYS))
        self.assertGreater(timings["rerank_ms"], 0.0)
        self.assertNotIn("judge_input_count", timings)
        self.assertNotIn("typesafe_mode", timings)
        self.assertEqual(self.vectors_patch.call_count, 0)

    def test_rerank_false_touches_neither_ce_nor_judging(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()

        rows, timings = self.search(service, external, rerank=False)

        self.assertEqual(service._reranker.pools, [])
        self.assertEqual(external.calls, [])
        self.assertEqual(set(timings), set(V1_TIMING_KEYS))
        self.assertEqual([row["rerank_score"] for row in rows], [None, None, None])
        self.assertEqual(self.vectors_patch.call_count, 0)

    def test_hybrid_mode_still_flows_through_the_pipeline(self) -> None:
        # bm25 支路不能因为判定段重排而断：hybrid + 无 Qdrant 命中时仍走本地 CE 前置。
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})
        external = RecordingJudgmentService()
        self.stack.enter_context(
            patch("app.retrieval.vector_store.all_chunks", return_value=list(self.rows))
        )

        with patch.object(settings, "typesafe_mode", "selective"):
            rows, timings = self.search(service, external, mode="hybrid")

        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])
        self.assertEqual(timings["fusion"], "rrf")
        self.assertEqual(timings["typesafe_skipped"], "router")


class RealServiceWiringTests(PipelineTestsBase):
    """不替换判定服务：用真实 `judge_candidates` 的配置级早退核对键集合与降级门。"""

    def test_missing_api_key_degrades_without_network_and_keeps_ce_order(self) -> None:
        service = self.make_service({"a": 4.0, "b": 3.0, "c": 1.0})

        def explode(*_args, **_kwargs):
            raise AssertionError("真实外呼被触发：本用例必须走配置级早退")

        with (
            patch.object(settings, "typesafe_api_key", SecretStr("")),
            patch.object(typesafe_judgment_service, "_client", explode),
        ):
            rows, timings = service.search_with_timings(
                BENIGN_QUERY,
                top_k=3,
                mode="vector",
                rerank=True,
                knowledge_base_ids=["kb_product"],
            )

        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])
        self.assertTrue(timings["typesafe_degraded"])
        self.assertEqual(timings["typesafe_errors"], ["api_key_not_configured"])
        self.assertEqual(timings["typesafe_request_count"], 0)
        self.assertFalse(timings["typesafe_trigger"])
        self.assertFalse(timings["typesafe_circuit_open"])
        self.assertIsNone(timings["typesafe_skipped"])
        self.assertEqual(timings["judge_input_count"], 3)
        # 判定段键集合 = V1 键集 + §7 本地段新键 + 批次 metrics 全集，不得多出旁门键。
        # （`typesafe_skip` / `typesafe_reasons` 是检索层自加的两枚，不来自批次。）
        self.assertEqual(
            set(timings) - set(V1_TIMING_KEYS),
            V2_STAGE_TIMING_KEYS
            | BATCH_METRIC_KEYS
            | {"typesafe_skip", "typesafe_reasons"},
        )
        self.assertNotIn("typesafe_api_key", timings)


if __name__ == "__main__":
    unittest.main()
