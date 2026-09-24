from __future__ import annotations

import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import SecretStr


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.typesafe_judgments import (
    TypeSafeJudgmentService,
    judgment_cache,
    query_requirements,
    reset_typesafe_stats,
    route_probabilities,
)


class FakeClient:
    def __init__(self, responses: dict[str, dict[str, float]] | None = None, error=None):
        self.responses = responses or {}
        self.error = error
        self.calls: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def system_one(self, *, state, questions, **kwargs):
        self.calls.append({"state": state, "questions": questions, **kwargs})
        if self.error is not None:
            raise self.error
        point_key = state["candidate_passage"]["document_title"]
        values = self.responses[point_key]
        return SimpleNamespace(
            model="jev-test",
            usage=SimpleNamespace(input_tokens=100, output_tokens=4),
            answers={
                key: SimpleNamespace(noul=value)
                for key, value in values.items()
            },
        )


def candidate(point_id: str, *, kb: str = "kb_product") -> dict:
    return {
        "id": point_id,
        "file_name": point_id,
        "section_title": "section",
        "knowledge_base_id": kb,
        "knowledge_base_name": "Product",
        "content": f"content for {point_id}",
    }


class TypeSafeJudgmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        # cwd 收口（Task 9 段 A / T5 N3 同族）：`app.config.settings` 的 `env_file=".env"`
        # 是**相对**路径 ⇒ 只有从 `backend/` 起进程才读得到宿主 `.env`
        # （`TYPESAFE_ENABLED=true` / `TYPESAFE_MODE=selective`）。本文件的用例过去把这
        # 两枚当成「当然成立」，于是从仓库根跑就整体退化成 `effective_typesafe_mode="off"`
        # 的早退分支（6 例红）。这里把它们**显式打进夹具**：不放宽任何断言，只是把原本
        # 隐性依赖宿主配置的事实写成前提——换 cwd 也得到同一组数字。
        self.stack.enter_context(patch.object(settings, "typesafe_enabled", True))
        self.stack.enter_context(patch.object(settings, "typesafe_mode", "selective"))
        self.stack.enter_context(
            patch.object(settings, "typesafe_api_key", SecretStr("test-server-key"))
        )
        self.stack.enter_context(patch.object(settings, "typesafe_max_concurrency", 2))
        self.stack.enter_context(
            patch.object(settings, "typesafe_input_price_per_million_usd", 0.042)
        )
        # Task 5 起判定缓存/滚动聚合是模块级共享态：用例从空账开始，跑完也不留账。
        judgment_cache.clear()
        reset_typesafe_stats()
        self.stack.callback(judgment_cache.clear)
        self.stack.callback(reset_typesafe_stats)

    def tearDown(self) -> None:
        self.stack.close()

    def test_policy_precedence_is_injection_then_conflict_then_relevance(self) -> None:
        base = {
            "is_relevant": 0.99,
            "contains_answer_evidence": 0.99,
            "contradicts_query_premise": 0.0,
            "contains_prompt_injection": 0.0,
        }
        self.assertEqual(route_probabilities(base), "include")
        self.assertEqual(
            route_probabilities({**base, "contradicts_query_premise": 0.99}),
            "conflicting_evidence",
        )
        self.assertEqual(
            route_probabilities(
                {
                    **base,
                    "contradicts_query_premise": 0.99,
                    "contains_prompt_injection": 0.99,
                }
            ),
            "exclude",
        )
        self.assertEqual(
            route_probabilities({**base, "is_relevant": 0.1}),
            "exclude",
        )

    def test_success_judges_each_passage_and_records_usage(self) -> None:
        fake = FakeClient(
            {
                "a": {
                    "is_relevant": 0.95,
                    "contains_answer_evidence": 0.91,
                    "contradicts_query_premise": 0.02,
                    "contains_prompt_injection": 0.01,
                },
                "b": {
                    "is_relevant": 0.92,
                    "contains_answer_evidence": 0.2,
                    "contradicts_query_premise": 0.88,
                    "contains_prompt_injection": 0.01,
                },
            }
        )
        batch = TypeSafeJudgmentService(lambda: fake).judge_candidates(
            "question",
            [candidate("a"), candidate("b")],
            knowledge_base_ids=["kb_product"],
        )

        self.assertFalse(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_request_count"], 2)
        self.assertEqual(batch.metrics["typesafe_input_tokens"], 200)
        self.assertEqual(batch.metrics["typesafe_output_tokens"], 8)
        self.assertEqual(batch.metrics["typesafe_estimated_cost_usd"], 0.0000084)
        self.assertEqual(batch.metrics["typesafe_models"], ["jev-test"])
        self.assertEqual(
            batch.metrics["typesafe_route_counts"],
            {"include": 1, "conflicting_evidence": 1, "exclude": 0},
        )
        self.assertEqual(batch.judgments["a"].route, "include")
        self.assertEqual(batch.judgments["b"].route, "conflicting_evidence")
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(
            set(fake.calls[0]["questions"]),
            {
                "is_relevant",
                "contains_answer_evidence",
                "contradicts_query_premise",
                "contains_prompt_injection",
            },
        )

    def test_compound_query_scores_each_requirement_independently(self) -> None:
        query = "X200的工作温度范围是多少，断网后默认又能缓存多久？"
        fake = FakeClient(
            {
                "a": {
                    "is_relevant": 0.31,
                    "contains_answer_evidence": 0.22,
                    "contradicts_query_premise": 0.01,
                    "contains_prompt_injection": 0.01,
                    "supports_requirement_0": 0.94,
                    "supports_requirement_1": 0.08,
                }
            }
        )

        batch = TypeSafeJudgmentService(lambda: fake).judge_candidates(
            query,
            [candidate("a")],
            knowledge_base_ids=["kb_product"],
        )

        self.assertEqual(
            query_requirements(query),
            ["X200的工作温度范围是多少", "断网后默认又能缓存多久"],
        )
        self.assertEqual(batch.judgments["a"].route, "include")
        self.assertEqual(batch.judgments["a"].is_relevant, 0.94)
        self.assertEqual(batch.judgments["a"].contains_answer_evidence, 0.94)
        self.assertIn("supports_requirement_0", fake.calls[0]["questions"])
        self.assertIn("supports_requirement_1", fake.calls[0]["questions"])

    def test_contextual_comma_stays_on_single_question_path(self) -> None:
        query = "我只是普通员工，去深圳住一晚最多报多少？"
        self.assertEqual(query_requirements(query), [query.rstrip("？")])

    def test_scope_mismatch_sends_zero_requests(self) -> None:
        fake = FakeClient()
        batch = TypeSafeJudgmentService(lambda: fake).judge_candidates(
            "question",
            [candidate("allowed"), candidate("forbidden", kb="kb_hr")],
            knowledge_base_ids=["kb_product"],
        )

        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_request_count"], 0)
        self.assertEqual(batch.metrics["typesafe_unauthorized_candidates_blocked"], 1)
        self.assertEqual(batch.metrics["typesafe_errors"], ["authorization_scope_mismatch"])
        self.assertEqual(fake.calls, [])

    def test_api_failure_is_sanitized_and_never_raises(self) -> None:
        secret = "never-persist-this-key"
        fake = FakeClient(error=RuntimeError(f"provider failed with {secret}"))
        batch = TypeSafeJudgmentService(lambda: fake).judge_candidates(
            "question",
            [candidate("a")],
            knowledge_base_ids=["kb_product"],
        )

        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_errors"], ["RuntimeError"])
        self.assertNotIn(secret, repr(batch.metrics))
        self.assertEqual(batch.judgments, {})

    def test_missing_key_degrades_without_constructing_client(self) -> None:
        calls = []

        def factory():
            calls.append(True)
            return FakeClient()

        with patch.object(settings, "typesafe_api_key", SecretStr("")):
            batch = TypeSafeJudgmentService(factory).judge_candidates(
                "question",
                [candidate("a")],
                knowledge_base_ids=["kb_product"],
            )

        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_request_count"], 0)
        self.assertEqual(batch.metrics["typesafe_errors"], ["api_key_not_configured"])
        self.assertEqual(calls, [])

    def test_client_construction_failure_records_zero_requests(self) -> None:
        def factory():
            raise RuntimeError("client construction failed")

        batch = TypeSafeJudgmentService(factory).judge_candidates(
            "question",
            [candidate("a")],
            knowledge_base_ids=["kb_product"],
        )

        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_request_count"], 0)
        self.assertEqual(batch.metrics["typesafe_errors"], ["RuntimeError"])


if __name__ == "__main__":
    unittest.main()
