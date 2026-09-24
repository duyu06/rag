from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.retrieval import RetrievalService
from app.typesafe_judgments import (
    JudgmentBatch,
    PassageJudgment,
    judgment_cache,
    reset_typesafe_stats,
)


def vector_rows() -> list[dict]:
    return [
        {
            "id": point_id,
            "file_name": f"{point_id}.md",
            "knowledge_base_id": "kb_product",
            "knowledge_base_name": "Product",
            "content": f"content {point_id}",
            "vector_raw_score": score,
        }
        for point_id, score in (("a", 0.9), ("b", 0.8), ("c", 0.7))
    ]


class FakeReranker:
    """V2 判定段把本地 Cross-Encoder 提成了前置阶段 ⇒ 这些用例不再加载真模型。

    分数按 content 末位的 id 查表；表里没有的 id（compound 用例的 row-XX）退化成
    "按入参位置递减"，这样归一化后 top1=1.0，§4 的 floor 档不会被误触发。
    刻意让 b > c > a，与 RRF 的 a > b > c **不同序**，用来区分"CE 序"和"融合序"。
    """

    SCORES = {"a": 0.1, "b": 0.9, "c": 0.2, "d": 0.3}

    def predict(self, pairs: list[list[str]]) -> list[float]:
        return [
            self.SCORES.get(str(pair[1]).rsplit(" ", 1)[-1], float(len(pairs) - index))
            for index, pair in enumerate(pairs)
        ]


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


class FakeJudgmentService:
    def __init__(self, batch: JudgmentBatch):
        self.batch = batch
        self.calls: list[dict] = []

    def judge_candidates(self, query, rows, *, knowledge_base_ids, budget=None):
        # `budget` 是 Task 5 冻结的可选关键字形参；Task 6 的判定段必须把它传进来。
        self.calls.append(
            {
                "query": query,
                "ids": [row["id"] for row in rows],
                "knowledge_base_ids": knowledge_base_ids,
                "budget": budget,
            }
        )
        return self.batch


class TypeSafeRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(settings, "retrieval_vector_query_instruction", ""))
        self.stack.enter_context(patch.object(settings, "retrieval_max_chunks_per_document", 3))
        self.vector_patch = self.stack.enter_context(
            patch("app.retrieval.vector_store.vector_search", return_value=vector_rows())
        )
        # Task 6 前置阶段会批量取向量做语义去重：本文件不关心去重，一律给"取不到向量"
        # （`dedupe_by_similarity` 因此是恒等映射），以免依赖本机 Qdrant 是否在跑。
        self.stack.enter_context(
            patch("app.retrieval.vector_store.fetch_vectors", return_value={})
        )
        # Task 5 起缓存/熔断/滚动聚合是模块级共享态 ⇒ 用例从空账开始，跑完也不留账。
        judgment_cache.clear()
        reset_typesafe_stats()
        self.stack.callback(judgment_cache.clear)
        self.stack.callback(reset_typesafe_stats)
        fake = FakeReranker()
        self.stack.enter_context(
            patch.object(
                RetrievalService,
                "reranker",
                property(lambda self: self._reranker if self._reranker is not None else fake),
            )
        )

    def tearDown(self) -> None:
        self.stack.close()

    def test_disabled_typesafe_preserves_existing_local_reranker(self) -> None:
        service = RetrievalService()
        service._reranker = SimpleNamespace(predict=lambda pairs: [0.1, 0.9, 0.2])
        external = FakeJudgmentService(JudgmentBatch({}, {}))

        with (
            patch.object(settings, "typesafe_enabled", False),
            patch.object(settings, "rerank_provider", "typesafe"),
            patch("app.retrieval.typesafe_judgment_service", external),
        ):
            rows, timings = service.search_with_timings(
                "question",
                top_k=3,
                mode="vector",
                rerank=True,
                knowledge_base_ids=["kb_product"],
            )

        self.assertEqual([row["id"] for row in rows], ["b", "c", "a"])
        self.assertEqual(external.calls, [])
        self.assertNotIn("typesafe_enabled", timings)

    def test_active_mode_filters_and_routes_conflicting_evidence(self) -> None:
        # V2 的 active 先过置信度/风险路由（§3），高置信单一事实会免判；这里要钉的是
        # "触发判定后 active 会应用路由"，所以用一条命中风险词表（合同/违约/赔偿）的问句。
        batch = JudgmentBatch(
            {
                "a": judgment("a", "exclude"),
                "b": judgment("b", "include", evidence=0.95),
                "c": judgment("c", "conflicting_evidence", contradiction=0.90),
            },
            {
                "typesafe_degraded": False,
                "typesafe_total_ms": 12.0,
                "typesafe_request_count": 3,
            },
        )
        external = FakeJudgmentService(batch)

        with (
            patch.object(settings, "typesafe_enabled", True),
            patch.object(settings, "typesafe_mode", "active"),
            patch.object(settings, "rerank_provider", "typesafe"),
            patch("app.retrieval.typesafe_judgment_service", external),
        ):
            rows, timings = RetrievalService().search_with_timings(
                "合同违约的赔偿上限是多少",
                top_k=3,
                mode="vector",
                rerank=True,
                knowledge_base_ids=["kb_product"],
            )

        self.assertEqual([row["id"] for row in rows], ["b", "c"])
        self.assertEqual(rows[1]["typesafe_route"], "conflicting_evidence")
        self.assertEqual(external.calls[0]["knowledge_base_ids"], ["kb_product"])
        self.assertEqual(timings["typesafe_request_count"], 3)

    def test_shadow_mode_records_metrics_without_changing_rows(self) -> None:
        batch = JudgmentBatch(
            {
                "a": judgment("a", "exclude"),
                "b": judgment("b", "include", evidence=0.95),
                "c": judgment("c", "conflicting_evidence", contradiction=0.90),
            },
            {
                "typesafe_degraded": False,
                "typesafe_total_ms": 12.0,
                # `typesafe_request_count` 是**判定服务实收行数**的上报面：本用例下面钉住
                # 判定输入是 ["b","d","c"] 三行 ⇒ 计数取 3（V1 时代写 2 是"candidates=2"的
                # 遗留值，Task 6 换成 §4 动态 TopK 后它对不上任何一条被测语义）。
                "typesafe_request_count": 3,
            },
        )
        external = FakeJudgmentService(batch)

        scoped_rows = vector_rows() + [
            {
                "id": "d",
                "file_name": "d.md",
                "knowledge_base_id": "kb_product",
                "knowledge_base_name": "Product",
                "content": "content d",
                "vector_raw_score": 0.6,
            }
        ]
        scoped_rows[0]["file_name"] = "same.md"
        scoped_rows[1]["file_name"] = "same.md"
        self.vector_patch.return_value = scoped_rows

        with (
            patch.object(settings, "typesafe_enabled", True),
            patch.object(settings, "typesafe_mode", "shadow"),
            patch.object(settings, "rerank_provider", "typesafe"),
            patch("app.retrieval.typesafe_judgment_service", external),
        ):
            rows, timings = RetrievalService().search_with_timings(
                "question",
                top_k=2,
                mode="vector",
                rerank=True,
                knowledge_base_ids=["kb_product"],
            )

        # V2 定案：shadow 仍然"只观测不应用"，但可见序换成**本地 CE 序**（§2 把 CE 提成了
        # 判定段前置阶段），不再是 V1 的融合序；下面同时钉分数，证明它是 CE 序而非 RRF 序。
        self.assertEqual([row["id"] for row in rows], ["b", "d"])
        self.assertEqual([row["rerank_score"] for row in rows], [1.0, 0.25])
        self.assertNotIn("typesafe_route", rows[0])
        # 计数与"实判行数"对齐（不是替身想写几就几）：批次报 3、判定层实收 3。
        self.assertEqual(timings["typesafe_request_count"], len(external.calls[0]["ids"]))
        self.assertEqual(timings["typesafe_request_count"], 3)
        # §4 动态 TopK 取代 V1 的固定 `typesafe_candidates` 池：分差 > high_margin ⇒ min 档 3。
        self.assertEqual(external.calls[0]["ids"], ["b", "d", "c"])
        self.assertEqual(timings["judge_input_count"], 3)

    def test_degraded_batch_falls_back_to_local_cross_encoder_order(self) -> None:
        external = FakeJudgmentService(
            JudgmentBatch(
                {"b": judgment("b", "include", evidence=0.99)},
                {
                    "typesafe_degraded": True,
                    "typesafe_total_ms": 8.0,
                    "typesafe_request_count": 3,
                    "typesafe_errors": ["TypeSafeAPITimeoutError"],
                },
            )
        )

        with (
            patch.object(settings, "typesafe_enabled", True),
            patch.object(settings, "typesafe_mode", "active"),
            patch.object(settings, "rerank_provider", "typesafe"),
            patch("app.retrieval.typesafe_judgment_service", external),
        ):
            rows, timings = RetrievalService().search_with_timings(
                # 同上一条用例：active 得先让路由放行，才谈得上"判定层降级"。
                "合同违约的赔偿上限是多少",
                top_k=3,
                mode="vector",
                rerank=True,
                knowledge_base_ids=["kb_product"],
            )

        self.assertTrue(timings["typesafe_degraded"])
        # 可辨识断言（fix round 1 / I1）：假 CE 给 b > c > a，与融合序 a > b > c **不同序**，
        # 所以这条才真的证明"降级退的是本地 CE 序"，而不是碰巧和融合序重合。
        self.assertEqual([row["id"] for row in rows], ["b", "c", "a"])
        for row in rows:
            self.assertNotIn("typesafe_route", row)

    def test_compound_query_uses_the_larger_candidate_pool(self) -> None:
        rows = [
            {
                "id": f"row-{index:02d}",
                "file_name": f"row-{index:02d}.md",
                "knowledge_base_id": "kb_product",
                "knowledge_base_name": "Product",
                "content": f"content {index}",
                "vector_raw_score": 1.0 - index / 100,
            }
            for index in range(15)
        ]
        self.vector_patch.return_value = rows
        external = FakeJudgmentService(
            JudgmentBatch(
                {},
                {
                    "typesafe_degraded": False,
                    "typesafe_total_ms": 12.0,
                    "typesafe_request_count": 12,
                },
            )
        )

        with (
            patch.object(settings, "typesafe_enabled", True),
            patch.object(settings, "typesafe_mode", "shadow"),
            patch.object(settings, "typesafe_compound_candidates", 12),
            patch.object(settings, "rerank_provider", "typesafe"),
            patch("app.retrieval.typesafe_judgment_service", external),
        ):
            _, timings = RetrievalService().search_with_timings(
                "X200温度范围是多少，断网后又能缓存多久？",
                top_k=3,
                mode="vector",
                rerank=True,
                knowledge_base_ids=["kb_product"],
            )

        # 结论不变（compound ⇒ 12 档），但依据换了：V1 是固定池 `max(candidates, compound)`，
        # V2 是 §4 动态 TopK 的 compound 档，并且 CE 前置池本身也并入了 low_confidence 宽度。
        self.assertEqual(
            external.calls[0]["ids"],
            [f"row-{index:02d}" for index in range(12)],
        )
        self.assertEqual(timings["rerank_candidates"], 12)
        self.assertEqual(timings["judge_input_count"], 12)


if __name__ == "__main__":
    unittest.main()
