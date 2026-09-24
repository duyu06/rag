from __future__ import annotations

import json
import importlib.util
from collections import Counter
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "backend" / "eval_dataset_complex.json"
SCRIPT_PATH = ROOT / "scripts" / "complex_accuracy.py"
DEMO_DIR = ROOT / "demo-data"


class ComplexAccuracyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("complex_accuracy", SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_complex_retrieval_dataset_is_large_balanced_and_unique(self):
        cases = self.dataset["retrieval_cases"]
        self.assertGreaterEqual(len(cases), 50)
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertEqual(len(cases), len({case["question"] for case in cases}))

        counts = Counter(case["knowledge_base_id"] for case in cases)
        self.assertEqual(
            {"kb_public", "kb_hr", "kb_product", "kb_sales", "kb_service"},
            set(counts),
        )
        self.assertTrue(all(count >= 10 for count in counts.values()), counts)

        categories = {case["category"] for case in cases}
        self.assertTrue(
            {
                "adversarial",
                "ambiguous",
                "boundary",
                "conditional",
                "multi_constraint",
                "negation",
                "numeric",
                "paraphrase",
                "temporal",
                "threshold",
            }.issubset(categories),
            categories,
        )

    def test_all_expected_sources_exist(self):
        known_files = {path.name for path in DEMO_DIR.glob("*.md")}
        referenced: set[str] = set()
        for case in self.dataset["retrieval_cases"]:
            self.assertTrue(case["acceptable_files"], case["id"])
            referenced.update(case["acceptable_files"])
        for case in self.dataset["compound_cases"]:
            self.assertGreaterEqual(len(case["required_files"]), 2, case["id"])
            referenced.update(case["required_files"])
        for case in self.dataset["conversation_cases"]:
            self.assertGreaterEqual(len(case["turns"]), 2, case["id"])
            for turn in case["turns"]:
                referenced.update(turn["acceptable_files"])
        self.assertFalse(referenced - known_files, referenced - known_files)

    def test_security_and_llm_boundaries_are_present(self):
        self.assertGreaterEqual(len(self.dataset["access_cases"]), 4)
        self.assertGreaterEqual(len(self.dataset["scope_cases"]), 3)
        self.assertGreaterEqual(len(self.dataset["compound_cases"]), 5)
        self.assertGreaterEqual(len(self.dataset["conversation_cases"]), 2)
        self.assertGreaterEqual(len(self.dataset["no_answer_cases"]), 2)
        self.assertTrue(
            all(case["expected_status"] == 403 for case in self.dataset["access_cases"])
        )

    def test_runner_exposes_quality_gates_and_live_llm_mode(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        for marker in (
            "--min-hit1",
            "--min-hit3",
            "--min-mrr",
            "--with-llm",
            "--llm-only",
            "--rerank-llm-boundaries",
            "--require-typesafe",
            "--expect-typesafe-mode",
            "--max-typesafe-degraded",
            "--min-typesafe-requests",
            "--max-avg-typesafe-requests-per-query",
            "--report-typesafe-rollup",
            "--json-output",
            "evaluate_compound",
            "evaluate_llm_boundaries",
            "validate_typesafe_gate",
            "Complex accuracy gate",
        ):
            self.assertIn(marker, source)

    def test_cli_advertises_the_five_modes_and_the_v2_flags(self):
        # ``--help`` 是唯一便宜的"参数真的注册进 argparse"证据：只改字符串常量而忘了
        # ``choices=`` / ``add_argument`` 时，上一条源码 grep 仍会绿。
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        help_text = " ".join((result.stdout or "").split())
        self.assertIn(
            "{off,shadow,selective,active,strict}",
            help_text,
            help_text,
        )
        self.assertIn("--max-avg-typesafe-requests-per-query", help_text)
        self.assertIn("--report-typesafe-rollup", help_text)
        self.assertIn("--expect-typesafe-mode", help_text)

    def test_rollup_reader_only_prints_whitelisted_aggregate_keys(self):
        # `--report-typesafe-rollup` 读的是响应面已经过白名单的 typesafe 块；这里钉住
        # 脚本**点名**的键集合，防止以后"顺手"把整块原样吐进终端。
        expected = {
            "mode",
            "breaker_state",
            "sample_count",
            "trigger_rate",
            "skip_rate",
            "cache_hit_ratio",
            "requests_per_query_p50",
            "requests_per_query_p95",
            "input_tokens_per_query_p50",
            "cost_per_query_p50",
            "timeout_rate",
            "degraded_rate",
            "latency_p50_ms",
            "latency_p95_ms",
        }
        self.assertEqual(expected, set(self.runner.ROLLUP_KEYS))

    def test_calls_per_query_gate_uses_the_run_output_set(self):
        judged = [
            {
                "typesafe_mode": "selective",
                "typesafe_request_count": count,
                "typesafe_models": ["jev-latest"],
                "typesafe_trigger": True,
                "judge_input_count": count,
                "result_rows": 3,
            }
            for count in (6, 3, 8)
        ]
        skipped = [
            {
                "typesafe_mode": "selective",
                "typesafe_skipped": "router",
                "typesafe_trigger": False,
                "judge_input_count": 3,
                "result_rows": 3,
            }
            for _ in range(2)
        ]
        summary = self.runner.summarize_typesafe(judged + skipped)
        # 免判查询按 0 次外呼进分母：17 次 / 5 查询 = 3.4，而不是 17/3 = 5.67。
        self.assertEqual(summary["sample_count"], 5)
        self.assertEqual(summary["request_count"], 17)
        self.assertEqual(summary["requests_per_query_avg"], 3.4)
        self.assertEqual(summary["requests_per_query_p50"], 3.0)
        self.assertEqual(summary["requests_per_query_p95"], 8.0)
        self.assertEqual(summary["router_skipped_cases"], 2)
        self.assertEqual(summary["triggered_cases"], 3)
        self.assertEqual(summary["judge_input_count_hist"], {"3": 3, "6": 1, "8": 1})
        # 分位只收真发过外呼的样本：免判的零值不许把 P50 拉成 0。
        self.assertEqual(summary["latency_p50_ms"], 0.0)

        aggregate = self.runner.combine_typesafe_summaries([summary])
        self.assertEqual(aggregate["requests_per_query_avg"], 3.4)
        self.assertEqual(aggregate["requests_per_query_p95"], 8.0)

        tight = self.runner.validate_typesafe_gate(
            aggregate,
            required_stages=["hybrid_rerank"],
            observed_stages=["hybrid_rerank"],
            stage_summaries={"hybrid_rerank": summary},
            expected_stage_samples={"hybrid_rerank": 5},
            require_typesafe=True,
            expect_mode="selective",
            max_degraded=0,
            min_requests=1,
            max_avg_requests_per_query=3.0,
        )
        self.assertTrue(any("requests per query above limit" in item for item in tight))
        loose = self.runner.validate_typesafe_gate(
            aggregate,
            required_stages=["hybrid_rerank"],
            observed_stages=["hybrid_rerank"],
            stage_summaries={"hybrid_rerank": summary},
            expected_stage_samples={"hybrid_rerank": 5},
            require_typesafe=True,
            expect_mode="selective",
            max_degraded=0,
            min_requests=1,
            max_avg_requests_per_query=4.0,
        )
        self.assertEqual(loose, [])

        # 只传新门禁（不带 --require-typesafe）也不得触发旧的逐阶段强检查。
        avg_only = self.runner.validate_typesafe_gate(
            aggregate,
            required_stages=[],
            observed_stages=["hybrid_rerank"],
            stage_summaries={"hybrid_rerank": summary},
            expected_stage_samples={},
            require_typesafe=False,
            expect_mode=None,
            max_degraded=None,
            min_requests=None,
            max_avg_requests_per_query=4.0,
        )
        self.assertEqual(avg_only, [])

    def test_observation_counts_exclusion_gaps_without_gating_them(self):
        cases = [
            {
                "typesafe_request_count": 8,
                "judge_input_count": 8,
                "typesafe_route_counts": {"include": 0, "exclude": 8, "conflicting_evidence": 0},
                "typesafe_degraded": False,
                "result_rows": 0,
            },
            {
                "typesafe_request_count": 3,
                "judge_input_count": 3,
                "typesafe_route_counts": {"include": 3, "exclude": 0, "conflicting_evidence": 0},
                "typesafe_degraded": False,
                "result_rows": 3,
            },
        ]
        observation = self.runner.summarize_case_observations(cases, top_k=3)
        self.assertEqual(observation["cases"], 2)
        self.assertEqual(observation["all_excluded_gap_cases"], 1)
        self.assertEqual(observation["empty_result_non_degraded_cases"], 1)
        self.assertEqual(observation["short_result_cases"], 1)
        self.assertEqual(observation["requests_per_query_avg"], 5.5)
        self.assertEqual(observation["result_rows_hist"], {"0": 1, "3": 1})

    def test_typesafe_gate_checks_each_stage_and_preserves_mixed_modes(self):
        active = self.runner.summarize_typesafe(
            [
                {
                    "typesafe_mode": "active",
                    "typesafe_request_count": 2,
                    "typesafe_models": ["jev-a"],
                    "typesafe_route_counts": {"include": 1, "exclude": 1},
                }
            ]
        )
        mixed = self.runner.summarize_typesafe(
            [
                {
                    "typesafe_mode": "active",
                    "typesafe_request_count": 1,
                    "typesafe_models": ["jev-a"],
                },
                {
                    "typesafe_mode": "shadow",
                    "typesafe_request_count": 1,
                    "typesafe_models": ["jev-a"],
                },
            ]
        )
        aggregate = self.runner.combine_typesafe_summaries([active, mixed])
        self.assertEqual(aggregate["modes"], ["active", "shadow"])
        self.assertEqual(aggregate["route_counts"], {"exclude": 1, "include": 1})

        empty_stage = self.runner.summarize_typesafe(
            [{"typesafe_mode": "active", "typesafe_request_count": 0}]
        )
        failures = self.runner.validate_typesafe_gate(
            self.runner.combine_typesafe_summaries([active, empty_stage]),
            required_stages=["retrieval", "compound"],
            observed_stages=["retrieval", "compound"],
            stage_summaries={"retrieval": active, "compound": empty_stage},
            expected_stage_samples={"retrieval": 1, "compound": 2},
            require_typesafe=True,
            expect_mode="active",
            max_degraded=None,
            min_requests=1,
        )
        self.assertTrue(any("compound reported no real requests" in item for item in failures))
        self.assertTrue(any("compound metrics incomplete" in item for item in failures))
        self.assertTrue(any("compound reported no response model" in item for item in failures))

    def test_llm_only_passes_rerank_flag_and_writes_consistent_json(self):
        summary = self.runner.summarize_typesafe(
            [
                {
                    "typesafe_mode": "active",
                    "typesafe_request_count": 1,
                    "typesafe_models": ["jev-test"],
                }
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset_path = root / "dataset.json"
            output_path = root / "report.json"
            dataset_path.write_text('{"version":"test"}', encoding="utf-8")
            argv = [
                str(SCRIPT_PATH),
                "--dataset",
                str(dataset_path),
                "--llm-only",
                "--rerank-llm-boundaries",
                "--require-typesafe",
                "--expect-typesafe-mode",
                "active",
                "--json-output",
                str(output_path),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(self.runner, "login", return_value="token"),
                patch.object(
                    self.runner,
                    "evaluate_llm_boundaries",
                    return_value=(1, 1, [], summary),
                ) as evaluate,
            ):
                self.assertEqual(self.runner.main(), 0)
            self.assertTrue(evaluate.call_args.kwargs["rerank"])
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["gate_passed"])
            self.assertIn("retrieval", payload)
            self.assertIn("compound", payload)
            self.assertIn("typesafe", payload)

    def test_failure_path_still_writes_machine_readable_json(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "failure.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--dataset",
                    str(Path(directory) / "missing.json"),
                    "--json-output",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["gate_passed"])
            self.assertIn("error", payload)
            self.assertIn("typesafe", payload)


if __name__ == "__main__":
    unittest.main()
