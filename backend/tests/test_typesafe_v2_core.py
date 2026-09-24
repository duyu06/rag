from __future__ import annotations

import os
import re
import sys
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from pydantic import SecretStr, ValidationError  # noqa: E402

from app.config import Settings, settings  # noqa: E402
from app.resilience import CircuitBreaker, TimeoutBudget  # noqa: E402


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class CircuitBreakerTests(unittest.TestCase):
    def make(self, **kw):
        clock = _FakeClock()
        params = dict(window=10, failure_ratio=0.3, open_seconds=60.0,
                      half_open_probes=3, clock=clock)
        params.update(kw)
        return CircuitBreaker(name="t", **params), clock

    def test_stays_closed_below_threshold(self):
        br, _ = self.make()
        for _ in range(7):
            br.record(True)
        for _ in range(2):
            br.record(False)
        self.assertEqual(br.state, "closed")
        self.assertTrue(br.allow())

    def test_opens_when_failure_ratio_exceeded(self):
        br, clock = self.make()
        for _ in range(7):
            br.record(False)
        self.assertEqual(br.state, "open")
        self.assertFalse(br.allow())

    def test_half_open_probe_success_closes(self):
        br, clock = self.make()
        for _ in range(7):
            br.record(False)
        clock.advance(61)
        self.assertTrue(br.allow())          # half-open：放行探测
        self.assertEqual(br.state, "half_open")
        for _ in range(3):
            br.record(True)
        self.assertEqual(br.state, "closed")

    def test_half_open_probe_failure_reopens(self):
        br, clock = self.make()
        for _ in range(7):
            br.record(False)
        clock.advance(61)
        br.allow()
        br.record(False)
        self.assertEqual(br.state, "open")
        self.assertFalse(br.allow())

    def test_window_only_counts_recent_calls(self):
        br, clock = self.make()
        for _ in range(1):
            br.record(False)
        for _ in range(9):
            br.record(True)
        for _ in range(3):
            br.record(False)
        # 早先那次失败已被滑窗淘汰：最近 10 次里失败 3/10 == 0.3，未超过阈值。
        # （若按累计历史算则是 4/13 > 0.3，会误熔断——本用例即锁死"滑窗"语义。）
        # 浮点等号这一职责由下面 test_sliding_window_denominator_trips_at_four_failures 兜底。
        self.assertEqual(br.state, "closed")

    def test_sliding_window_denominator_trips_at_four_failures(self):
        br, _ = self.make()
        for _ in range(10):
            br.record(True)
        for _ in range(4):
            br.record(False)
        # 滑窗分母锁死：满窗 10 个样本、4 败 → 4/10 = 0.4 > 0.3 → open。
        # 不依赖 3/10 == 0.3 的浮点等号（那是上一条用例的职责）；
        # 且它专门排除"分母退化成累计历史"的实现：累计口径 4/14 = 0.286 < 0.3 → 不会熔断。
        self.assertEqual(br.state, "open")
        self.assertFalse(br.allow())

    def test_window_below_minimum_is_rejected(self):
        # window < 8 时门槛 max(4, window // 2) 超过 deque 可达长度 → 判定静默失效，
        # 必须构造期报错而不是悄悄永不熔断（门槛表达式本身保持不变）。
        for bad in (1, 4, 7):
            with self.assertRaises(ValueError):
                self.make(window=bad)
        ok, _ = self.make(window=8)     # 最小合法值仍可用
        self.assertEqual(ok.state, "closed")

    def test_expired_open_becomes_half_open_by_reading_state_alone(self):
        # "观测即推进"：state 是带副作用的 getter，全程不调 allow() 也会 OPEN → HALF_OPEN。
        br, clock = self.make()
        for _ in range(7):
            br.record(False)
        self.assertEqual(br.state, "open")
        clock.advance(61)               # 冷却到期，此后不碰 allow()
        self.assertEqual(br.state, "half_open")
        self.assertEqual(br.state, "half_open")   # 幂等，不会二次推进

    def test_half_open_admits_at_most_probes(self):
        br, clock = self.make()
        for _ in range(7):
            br.record(False)
        clock.advance(61)
        # half_open_probes=3：50 并发同时到也只放行 3 个，第 4/5 次 False。
        admits = [br.allow() for _ in range(5)]
        self.assertEqual(admits, [True, True, True, False, False])
        self.assertEqual(br.state, "half_open")

    def test_half_open_receipt_releases_probe_slot(self):
        br, clock = self.make()
        for _ in range(7):
            br.record(False)
        clock.advance(61)
        # allow→record 成对推进：每次回执都要归还槽位，否则探测名额会被"已放行"累计吃掉。
        for _ in range(2):
            self.assertTrue(br.allow())
            br.record(True)
        self.assertTrue(br.allow())    # half_success=2，仍剩 1 个名额
        self.assertFalse(br.allow())   # 名额满（inflight 1 + success 2 == probes）
        br.record(True)                # 第 3 次成功 → closed
        self.assertEqual(br.state, "closed")

    def test_half_open_leaked_slots_recover_on_reentry(self):
        br, clock = self.make()
        for _ in range(7):
            br.record(False)
        clock.advance(61)
        # 放行 3 个探测后全部不回执（在飞请求超时/丢失）：无租约回收，槽位就此泄漏。
        self.assertEqual([br.allow() for _ in range(4)], [True, True, True, False])
        br.record(False)                # 任一回执失败 → 重新 OPEN，计数清零
        self.assertEqual(br.state, "open")
        clock.advance(61)
        # 已知限制的兜底：重新进入 half_open 一定拿到满额探测槽位。
        self.assertEqual([br.allow() for _ in range(4)], [True, True, True, False])
        self.assertEqual(br.state, "half_open")


class TimeoutBudgetTests(unittest.TestCase):
    def test_soft_then_hard(self):
        clock = _FakeClock()
        # TimeoutBudget 的 clock 与 time.perf_counter 同纲：秒（实现内部 *1000 换算 ms）
        budget = TimeoutBudget(soft_ms=1200, hard_ms=1800,
                               clock=lambda: clock.now)
        clock.advance(0.5)   # 500ms
        self.assertFalse(budget.over_soft())
        self.assertFalse(budget.exhausted())
        self.assertAlmostEqual(budget.remaining_ms(), 1300, places=6)
        clock.advance(1.0)   # 1500ms
        self.assertTrue(budget.over_soft())
        self.assertFalse(budget.exhausted())
        clock.advance(0.5)   # 2000ms
        self.assertTrue(budget.exhausted())
        self.assertLessEqual(budget.remaining_ms(), 0.0)

    def test_exact_threshold_boundaries(self):
        clock = _FakeClock()
        # 用可精确表示的秒数（1.0 / 2.0），让 elapsed 恰好落在 soft_ms / hard_ms 上，
        # 钉死两处边界语义：等于 soft 不算"超过"（严格 >）、等于 hard 算"已耗尽"（<= 0）。
        budget = TimeoutBudget(soft_ms=1000, hard_ms=2000, clock=lambda: clock.now)
        clock.advance(1.0)   # elapsed == soft_ms
        self.assertAlmostEqual(budget.elapsed_ms(), 1000.0, places=9)
        self.assertFalse(budget.over_soft())
        self.assertFalse(budget.exhausted())
        clock.advance(1.0)   # elapsed == hard_ms，remaining == 0
        self.assertAlmostEqual(budget.remaining_ms(), 0.0, places=9)
        self.assertTrue(budget.exhausted())
        self.assertTrue(budget.over_soft())
        clock.advance(0.5)   # 越界后持续为已耗尽
        self.assertTrue(budget.exhausted())
        self.assertLess(budget.remaining_ms(), 0.0)


class SettingsModeTests(unittest.TestCase):
    """TypeSafe V2 设计 §3（五档模式）+ §8（配置键）：默认值与边界。"""

    TYPESAFE_FIELDS = (
        "typesafe_mode", "typesafe_soft_timeout_ms", "typesafe_hard_timeout_ms",
        "typesafe_min_candidates", "typesafe_max_candidates",
        "typesafe_compound_candidates", "typesafe_low_confidence_candidates",
        "typesafe_high_margin", "typesafe_medium_margin", "typesafe_confidence_floor",
        "typesafe_dedup_cosine", "typesafe_cache_enabled", "typesafe_cache_ttl_seconds",
        "typesafe_cache_max_entries", "typesafe_breaker_enabled", "typesafe_breaker_window",
        "typesafe_breaker_failure_ratio", "typesafe_breaker_open_seconds",
        "typesafe_breaker_half_open_probes",
    )

    @staticmethod
    def make_settings(**overrides):
        """确定性构造：`_env_file=None` 屏蔽 backend/.env，`patch.dict(clear=True)`
        屏蔽宿主 OS 环境变量（pydantic-settings 的 EnvSource 与 _env_file 无关），
        于是字段只由显式 kwargs + 类默认值决定。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            return Settings(_env_file=None, **overrides)

    # --- §3 模式语义 ---------------------------------------------------------
    def test_effective_mode_off_when_disabled(self):
        s = self.make_settings(typesafe_enabled=False, typesafe_mode="strict")
        self.assertEqual(s.effective_typesafe_mode, "off")

    def test_effective_mode_passthrough_when_enabled(self):
        s = self.make_settings(typesafe_enabled=True, typesafe_mode="selective")
        self.assertEqual(s.effective_typesafe_mode, "selective")

    def test_legacy_mode_values_still_valid(self):
        for legacy in ("shadow", "active"):
            self.assertEqual(
                self.make_settings(typesafe_mode=legacy).typesafe_mode, legacy)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValidationError):
            self.make_settings(typesafe_mode="yolo")

    def test_all_five_modes_accepted_and_enabled_matrix(self):
        # 五档全合法；enabled=True 时 effective 与 mode 逐字相等。
        for mode in ("off", "shadow", "selective", "active", "strict"):
            s = self.make_settings(typesafe_enabled=True, typesafe_mode=mode)
            self.assertEqual(s.typesafe_mode, mode)
            self.assertEqual(s.effective_typesafe_mode, mode)
        # enabled=False 恒等价 off，连显式 off 也不例外（判定层不得被 mode 反向打开）。
        off = self.make_settings(typesafe_enabled=False, typesafe_mode="off")
        self.assertEqual(off.effective_typesafe_mode, "off")

    def test_default_mode_stays_shadow_for_production_safety(self):
        # 生产建议值是 selective，但默认值不改现网口径：仍是 shadow。
        self.assertEqual(self.make_settings().typesafe_mode, "shadow")
        self.assertEqual(self.make_settings().effective_typesafe_mode, "off")  # enabled 默认 False

    # --- §8 默认值 -----------------------------------------------------------
    def test_new_keys_carry_design_defaults(self):
        s = self.make_settings()
        expected = {
            "typesafe_soft_timeout_ms": 1200,
            # 硬线终值 3000：Task 8 §8/§9 预留的标定动作（段A 单请求 P95 1835ms > 1800、
            # 段B 批次墙钟尾 3.0-4.9s），spec 原值 1800 已被实测否证为配置错配。
            "typesafe_hard_timeout_ms": 3000,
            "typesafe_min_candidates": 3,
            "typesafe_max_candidates": 6,
            "typesafe_compound_candidates": 8,
            "typesafe_low_confidence_candidates": 12,
            "typesafe_high_margin": 0.25,
            "typesafe_medium_margin": 0.10,
            "typesafe_confidence_floor": 0.20,
            "typesafe_dedup_cosine": 0.97,
            "typesafe_cache_enabled": True,
            "typesafe_cache_ttl_seconds": 86400,
            "typesafe_cache_max_entries": 2048,
            "typesafe_breaker_enabled": True,
            "typesafe_breaker_window": 20,
            "typesafe_breaker_failure_ratio": 0.30,
            "typesafe_breaker_open_seconds": 60,
            "typesafe_breaker_half_open_probes": 3,
            "typesafe_max_concurrency": 6,  # 4 -> 6（本任务唯一改动的旧默认值）
        }
        for name, value in expected.items():
            with self.subTest(key=name):
                self.assertEqual(getattr(s, name), value)

    def test_existing_keys_untouched(self):
        # "现有键不动"= 键名/边界保留，仍作 active/shadow 判定前池尺寸与 client 上限；
        # 唯一默认值变化：max_concurrency 4 -> 6、compound_candidates 12 -> 8（§4 compound 档）。
        s = self.make_settings()
        self.assertFalse(s.typesafe_enabled)
        self.assertEqual(s.typesafe_timeout_seconds, 8.0)
        self.assertEqual(s.typesafe_candidates, 6)
        self.assertEqual(s.typesafe_compound_candidates, 8)
        self.assertEqual(s.typesafe_max_passage_chars, 2400)
        self.assertEqual(s.typesafe_injection_max, 0.70)

    def test_all_new_fields_have_env_style_names(self):
        s = self.make_settings()
        for name in self.TYPESAFE_FIELDS:
            with self.subTest(key=name):
                self.assertTrue(hasattr(s, name))

    # --- §8 边界 -------------------------------------------------------------
    BOUNDS = {
        "typesafe_soft_timeout_ms": (500, 30000),
        "typesafe_hard_timeout_ms": (1000, 60000),
        "typesafe_min_candidates": (1, 12),
        "typesafe_max_candidates": (1, 20),
        "typesafe_compound_candidates": (2, 30),
        "typesafe_low_confidence_candidates": (2, 40),
        "typesafe_high_margin": (0.0, 1.0),
        "typesafe_medium_margin": (0.0, 1.0),
        "typesafe_confidence_floor": (0.0, 1.0),
        "typesafe_dedup_cosine": (0.0, 1.0),
        "typesafe_cache_ttl_seconds": (60, 604800),
        "typesafe_cache_max_entries": (128, 65536),
        "typesafe_breaker_window": (8, 200),
        "typesafe_breaker_failure_ratio": (0.0, 1.0),
        "typesafe_breaker_open_seconds": (1, 3600),
        "typesafe_breaker_half_open_probes": (1, 10),
    }

    def test_boundary_edges_are_inclusive_and_out_of_range_rejected(self):
        step = {int: 1, float: 0.01}
        defaults = self.make_settings()
        for name, (low, high) in self.BOUNDS.items():
            delta = step[type(getattr(defaults, name))]
            with self.subTest(key=name, edge="lower_inclusive"):
                self.assertEqual(
                    getattr(self.make_settings(**{name: low}), name), low)
            with self.subTest(key=name, edge="upper_inclusive"):
                self.assertEqual(
                    getattr(self.make_settings(**{name: high}), name), high)
            with self.subTest(key=name, edge="below_range"):
                with self.assertRaises(ValidationError):
                    self.make_settings(**{name: low - delta})
            with self.subTest(key=name, edge="above_range"):
                with self.assertRaises(ValidationError):
                    self.make_settings(**{name: high + delta})

    def test_defaults_sit_strictly_inside_their_declared_bounds(self):
        # 防"默认值被自己的边界掐死"：默认必须合法且非贴边（贴边说明约束写歪了）。
        s = self.make_settings()
        for name, (low, high) in self.BOUNDS.items():
            with self.subTest(key=name):
                value = getattr(s, name)
                self.assertGreaterEqual(value, low)
                self.assertLessEqual(value, high)

    # --- §5/§6/§8 与 Task 1 原语的契约 ---------------------------------------
    def test_default_breaker_and_budget_values_construct_resilience_primitives(self):
        # 配置键默认值必须能直接喂给 Task 1 的韧性原语（含 window>=8、soft<=hard 约束）。
        s = self.make_settings()
        breaker = CircuitBreaker(
            name="typesafe", window=s.typesafe_breaker_window,
            failure_ratio=s.typesafe_breaker_failure_ratio,
            open_seconds=s.typesafe_breaker_open_seconds,
            half_open_probes=s.typesafe_breaker_half_open_probes)
        self.assertEqual(breaker.state, "closed")
        budget = TimeoutBudget(soft_ms=s.typesafe_soft_timeout_ms,
                               hard_ms=s.typesafe_hard_timeout_ms)
        self.assertGreater(budget.remaining_ms(), 0)

    def test_settings_reject_values_the_resilience_primitives_would_refuse(self):
        # breaker_window 的 ge 必须与 CircuitBreaker 的 window>=8 同轨，
        # 否则坏配置会活到运行期第一个判定请求才炸。
        with self.assertRaises(ValidationError):
            self.make_settings(typesafe_breaker_window=7)
        with self.assertRaises(ValueError):
            CircuitBreaker(name="typesafe", window=7)

    def test_default_settings_still_construct_without_arguments(self):
        # 无参 Settings() 读本地 .env / OS 环境：仍必须可构造（app 启动路径不变）。
        s = Settings()
        self.assertIn(s.effective_typesafe_mode,
                      ("off", "shadow", "selective", "active", "strict"))

    # --- §8 .env.example 同步 ------------------------------------------------
    def _documented_typesafe_env(self):
        text = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
        documented = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, sep, value = stripped.partition("=")
            if sep and key.strip().startswith("TYPESAFE_"):
                documented[key.strip()] = value.strip()
        return documented

    def test_env_example_documents_every_key_and_matches_defaults(self):
        # 示例文件漂移 = 生产照抄出一份非预期配置：逐键校验"能被 env 解析 + 等于类默认值"。
        documented = self._documented_typesafe_env()
        required = {"TYPESAFE_" + f.upper().removeprefix("TYPESAFE_")
                    for f in self.TYPESAFE_FIELDS}
        missing = required - set(documented)
        self.assertEqual(set(), missing, msg=f".env.example 缺少 §8 键: {sorted(missing)}")
        reference = self.make_settings()
        with mock.patch.dict(os.environ, documented, clear=True):
            loaded = Settings(_env_file=None)  # 走真实 env 解析路径（含 bool/float/SecretStr）
        for key, value in documented.items():
            name = key.lower()
            with self.subTest(key=key):
                self.assertIn(name, Settings.model_fields)
                if not value:
                    continue
                actual, expected = getattr(loaded, name), getattr(reference, name)
                self.assertEqual(actual, expected)


class JudgmentCacheTests(unittest.TestCase):
    """设计 §6 判定缓存：键稳定性、TTL 过期、LRU 淘汰、命中零泄漏。"""

    def make_judgment(self, evidence=0.9, latency_ms=100.0, input_tokens=10,
                      output_tokens=2):
        from app.typesafe_judgments import PassageJudgment
        return PassageJudgment(point_id="p1", route="include", is_relevant=0.9,
                               contains_answer_evidence=evidence,
                               contradicts_query_premise=0.0,
                               contains_prompt_injection=0.0,
                               model="jev-test", latency_ms=latency_ms,
                               input_tokens=input_tokens,
                               output_tokens=output_tokens)

    def test_key_stable_and_content_sensitive(self):
        from app.typesafe_judgments import cache_key
        row = {"id": "p1", "content": "保修两年"}
        self.assertEqual(cache_key("保修期", row, "m"), cache_key("  保修期 ", row, "m"))
        self.assertNotEqual(cache_key("保修期", row, "m"),
                            cache_key("保修期", {**row, "content": "保修三年"}, "m"))

    def test_key_separates_model_prompt_version_and_chunk(self):
        import app.typesafe_judgments as tj
        row = {"id": "p1", "content": "保修两年"}
        self.assertNotEqual(tj.cache_key("保修期", row, "m"),
                            tj.cache_key("保修期", row, "other"))
        self.assertNotEqual(tj.cache_key("保修期", row, "m"),
                            tj.cache_key("保修期", {**row, "id": "p2"}, "m"))
        # 键必须含 PROMPT_VERSION：改提示词要让整批缓存自然作废
        self.assertEqual(tj.PROMPT_VERSION, "v1")
        before = tj.cache_key("保修期", row, "m")
        with mock.patch.object(tj, "PROMPT_VERSION", "v2"):
            self.assertNotEqual(before, tj.cache_key("保修期", row, "m"))

    def test_key_normalizes_case_and_whitespace_only(self):
        from app.typesafe_judgments import cache_key
        row = {"id": "p1", "content": "  保修   两年 "}
        self.assertEqual(cache_key("How LONG", row, "m"), cache_key("how  long", row, "m"))
        self.assertEqual(cache_key("x", row, "m"),
                         cache_key("x", {**row, "content": "保修 两年"}, "m"))
        self.assertEqual(cache_key("x", {}, "m"), cache_key("x", {"content": None}, "m"))

    def test_put_strips_freshness_fields_but_keeps_the_judgment_intact(self):
        from app.typesafe_judgments import JudgmentCache
        cache = JudgmentCache(max_entries=2, ttl_seconds=100, clock=_FakeClock())
        judged = self.make_judgment(evidence=0.4, latency_ms=1234.5,
                                    input_tokens=777, output_tokens=88)
        cache.put("k", judged)
        hit = cache.get("k")
        # 时效性字段恒 0：缓存命中不得复活陈旧延迟/用量（聚合与成本口径）
        self.assertEqual(hit.latency_ms, 0.0)
        self.assertEqual(hit.input_tokens, 0)
        self.assertEqual(hit.output_tokens, 0)
        # 判定五字段 + 身份/模型完好，且与入缓存那条逐字一致
        self.assertEqual(hit.point_id, judged.point_id)
        self.assertEqual(hit.route, judged.route)
        self.assertEqual(hit.is_relevant, judged.is_relevant)
        self.assertEqual(hit.contains_answer_evidence, judged.contains_answer_evidence)
        self.assertEqual(hit.contradicts_query_premise, judged.contradicts_query_premise)
        self.assertEqual(hit.contains_prompt_injection, judged.contains_prompt_injection)
        self.assertEqual(hit.model, judged.model)
        self.assertEqual(hit.row_fields(), judged.row_fields())
        self.assertTrue(hit.from_cache)
        # put 不就地改写调用方手里的原对象（它仍带着真实延迟/用量供本次聚合）
        self.assertEqual(judged.latency_ms, 1234.5)
        self.assertEqual(judged.input_tokens, 777)
        self.assertEqual(judged.output_tokens, 88)

    def test_cache_hit_metric_key_spelling_is_pinned_to_design_section_7(self):
        import app.typesafe_judgments as tj
        # 设计 §7 的 timings 键是单数 typesafe_cache_hit；复数拼写会在 Task 7 白名单上失联。
        self.assertEqual(tj.CACHE_HIT_METRIC_KEY, "typesafe_cache_hit")
        drift = tj.CACHE_HIT_METRIC_KEY + "s"      # 禁用的复数写法（拼出来，别写进源码）
        for source in (Path(tj.__file__), Path(__file__)):
            with self.subTest(source=source.name):
                self.assertNotIn(drift, source.read_text(encoding="utf-8"))

    def test_hit_after_put_and_ttl_expiry(self):
        from app.typesafe_judgments import JudgmentCache
        clock = _FakeClock()
        cache = JudgmentCache(max_entries=2, ttl_seconds=100, clock=clock)
        key = "k1"
        cache.put(key, self.make_judgment())
        self.assertIsNotNone(cache.get(key))
        clock.advance(101)
        self.assertIsNone(cache.get(key))

    def test_put_refreshes_ttl_and_entry_count(self):
        from app.typesafe_judgments import JudgmentCache
        clock = _FakeClock()
        cache = JudgmentCache(max_entries=2, ttl_seconds=100, clock=clock)
        cache.put("k1", self.make_judgment())
        clock.advance(90)
        cache.put("k1", self.make_judgment(evidence=0.5))   # 覆盖写：续期 + 换新值
        clock.advance(90)                                   # 距首次 180s、距覆盖 90s
        hit = cache.get("k1")
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.contains_answer_evidence, 0.5)
        self.assertEqual(len(cache), 1)

    def test_lru_eviction(self):
        from app.typesafe_judgments import JudgmentCache
        cache = JudgmentCache(max_entries=2, ttl_seconds=100, clock=_FakeClock())
        cache.put("a", self.make_judgment()); cache.put("b", self.make_judgment())
        cache.get("a")                        # a 变最近使用
        cache.put("c", self.make_judgment())
        self.assertIsNotNone(cache.get("a")); self.assertIsNone(cache.get("b"))

    def test_expired_entries_are_dropped_not_resurrected(self):
        from app.typesafe_judgments import JudgmentCache
        clock = _FakeClock()
        cache = JudgmentCache(max_entries=5, ttl_seconds=10, clock=clock)
        cache.put("k", self.make_judgment())
        clock.advance(11)
        self.assertIsNone(cache.get("k"))
        self.assertEqual(len(cache), 0)       # 过期即删，不留尸体占名额
        cache.put("k", self.make_judgment(evidence=0.2))
        self.assertIsNotNone(cache.get("k"))

    def test_hit_is_marked_from_cache_without_leaking_row_fields(self):
        from app.typesafe_judgments import JudgmentCache
        cache = JudgmentCache(max_entries=2, ttl_seconds=100, clock=_FakeClock())
        fresh = self.make_judgment()
        self.assertFalse(fresh.from_cache)
        cache.put("k", fresh)
        hit = cache.get("k")
        self.assertTrue(hit.from_cache)
        self.assertFalse(fresh.from_cache)    # 存进去的对象不被就地改写
        self.assertEqual(hit.row_fields(), fresh.row_fields())   # 响应字段零差异
        self.assertNotIn("from_cache", hit.row_fields())
        self.assertNotIn("from_cache", fresh.row_fields())

    def test_disabled_cache_never_hits(self):
        from app.typesafe_judgments import JudgmentCache
        cache = JudgmentCache(max_entries=10, ttl_seconds=100,
                              clock=_FakeClock(), enabled=False)
        cache.put("k", self.make_judgment())
        self.assertEqual(len(cache), 0)
        self.assertIsNone(cache.get("k"))

    def test_module_singleton_defaults_follow_settings(self):
        from app.config import settings
        from app.typesafe_judgments import JudgmentCache, judgment_cache
        self.assertIsInstance(judgment_cache, JudgmentCache)
        self.assertTrue(settings.typesafe_cache_enabled)
        key = "typesafe-v2-core-singleton-probe"
        try:
            judgment_cache.put(key, self.make_judgment())
            self.assertIsNotNone(judgment_cache.get(key))
        finally:
            judgment_cache.clear()
        self.assertIsNone(judgment_cache.get(key))
        self.assertLessEqual(len(judgment_cache), int(settings.typesafe_cache_max_entries))


class DedupeTests(unittest.TestCase):
    """设计 §6 语义去重：cosine≥阈值合并、保留入参序首位（高分块）、无向量原样放行。"""

    def test_merge_keeps_first_high_score(self):
        from app.typesafe_judgments import dedupe_by_similarity
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        vectors = {"a": [1.0, 0.0], "b": [0.999, 0.01], "c": [0.0, 1.0]}
        kept = dedupe_by_similarity(rows, vectors, threshold=0.97)
        self.assertEqual([r["id"] for r in kept], ["a", "c"])

    def test_rows_without_vectors_pass_through(self):
        from app.typesafe_judgments import dedupe_by_similarity
        rows = [{"id": "a"}, {"id": "x"}]
        kept = dedupe_by_similarity(rows, {"a": [1.0, 0.0]}, threshold=0.97)
        self.assertEqual([r["id"] for r in kept], ["a", "x"])

    def test_rows_without_vectors_keep_their_original_rank(self):
        from app.typesafe_judgments import dedupe_by_similarity
        # x 在最前且无向量、a/b 向量重复：位次钉——无向量行必须留在原位次，
        # 既不能被"攒到尾部重排"，也不能因此让位给后面的重复块（a 仍是 a/b 组的幸存者）。
        rows = [{"id": "x"}, {"id": "a"}, {"id": "b"}]
        vectors = {"a": [1.0, 0.0], "b": [1.0, 0.0]}
        kept = dedupe_by_similarity(rows, vectors, threshold=0.97)
        self.assertEqual([r["id"] for r in kept], ["x", "a"])

    def test_exact_threshold_merges_and_rows_are_returned_unchanged(self):
        from app.typesafe_judgments import dedupe_by_similarity
        rows = [{"id": "a", "score": 9.0}, {"id": "b", "score": 8.0}]
        # dot([3,4],[5,0]) = 15，两范数皆为 5 → cosine 恰为 0.6（浮点可精确表示）
        vectors = {"a": [3.0, 4.0], "b": [5.0, 0.0]}
        self.assertEqual([r["id"] for r in dedupe_by_similarity(rows, vectors, 0.6)], ["a"])
        self.assertEqual([r["id"] for r in dedupe_by_similarity(rows, vectors, 0.61)],
                         ["a", "b"])
        # 纯函数：不改写入参行对象
        self.assertEqual(rows[0]["score"], 9.0)
        self.assertEqual(rows, [{"id": "a", "score": 9.0}, {"id": "b", "score": 8.0}])

    def test_one_kept_block_absorbs_every_duplicate(self):
        from app.typesafe_judgments import dedupe_by_similarity
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        vectors = {"a": [1.0, 0.0], "b": [1.0, 0.0], "c": [0.999, 0.01], "d": [0.0, 1.0]}
        kept = dedupe_by_similarity(rows, vectors, threshold=0.97)
        self.assertEqual([r["id"] for r in kept], ["a", "d"])

    def test_incomparable_vectors_never_merge(self):
        from app.typesafe_judgments import dedupe_by_similarity
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        # 零向量与维度不等都没有可比的 cosine：即便阈值为 0（最激进）也必须全部保留
        vectors = {"a": [0.0, 0.0], "b": [0.0, 0.0], "c": [1.0]}
        kept = dedupe_by_similarity(rows, vectors, threshold=0.0)
        self.assertEqual([r["id"] for r in kept], ["a", "b", "c"])

    def test_empty_inputs(self):
        from app.typesafe_judgments import dedupe_by_similarity
        self.assertEqual(dedupe_by_similarity([], {}, threshold=0.97), [])
        self.assertEqual(dedupe_by_similarity([{"id": "a"}], {}, threshold=0.97), [{"id": "a"}])


class _FakeRecord:
    def __init__(self, point_id, vector):
        self.id = point_id
        self.vector = vector


class _FakeQdrantForVectors:
    """只实现 retrieve()：记录调用参数，按预设返回或抛错。"""

    def __init__(self, records=(), error=None):
        self.records = list(records)
        self.error = error
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.records


class FetchVectorsTests(unittest.TestCase):
    """store.fetch_vectors：一次批量取向量，任何异常都降级为 {}（绝不丢块）。"""

    def make_store(self, fake):
        from app.store import VectorStore
        store = VectorStore()
        store._client = fake        # 注入点：绕开真实 Qdrant 连接
        return store

    def test_single_batch_call_with_vectors_only(self):
        from app.config import settings
        fake = _FakeQdrantForVectors(
            records=[_FakeRecord("p1", [0.1, 0.2]), _FakeRecord("p2", (0.3, 0.4))]
        )
        result = self.make_store(fake).fetch_vectors(["p1", "p2"])
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertEqual(call["collection_name"], settings.qdrant_collection)
        self.assertEqual(list(call["points"]), ["p1", "p2"])
        self.assertFalse(call["with_payload"])
        self.assertTrue(call["with_vectors"])
        self.assertEqual(result, {"p1": [0.1, 0.2], "p2": [0.3, 0.4]})

    def test_any_qdrant_failure_degrades_to_empty(self):
        for error in (RuntimeError("boom"), ValueError("bad response"), OSError()):
            with self.subTest(error=type(error).__name__):
                fake = _FakeQdrantForVectors(error=error)
                self.assertEqual(self.make_store(fake).fetch_vectors(["p1"]), {})

    def test_empty_request_skips_qdrant(self):
        for ids in ([], None):
            with self.subTest(ids=ids):
                fake = _FakeQdrantForVectors(records=[_FakeRecord("p1", [1.0])])
                self.assertEqual(self.make_store(fake).fetch_vectors(ids), {})
                self.assertEqual(fake.calls, [])

    def test_unusable_point_vectors_are_skipped_not_fatal(self):
        fake = _FakeQdrantForVectors(records=[
            _FakeRecord("ok", [1.0, 0.0]),
            _FakeRecord("missing", None),
            _FakeRecord("stringy", ["a", "b"]),
            _FakeRecord("named", {"dense": [0.5, 0.5]}),
        ])
        result = self.make_store(fake).fetch_vectors(["ok", "missing", "stringy", "named"])
        self.assertEqual(sorted(result), ["named", "ok"])


class RouterTests(unittest.TestCase):
    """设计 §3 路由信号矩阵 + §4 动态 TopK（Task 4：`app/typesafe_router.py`）。

    brief 的 7 条用例逐字保留。其中 `X200 的工作温度是多少` 必须 skip，靠的是主控预裁决：
    数字/时间信号须**伴随参数词**且**纯产品型号里的数字不算量值**（否则 selective 触发率
    虚高，P50≤4 calls/query 的成本目标打不到）。
    """

    BRIEF_DOCS = ("a.md", "b.md", "c.md", "d.md")

    def rows(self, top1, second_gap, docs=("a.md", "b.md", "c.md", "d.md")):
        base = top1
        out = []
        for i, doc in enumerate(docs):
            out.append({"id": str(i), "file_name": doc,
                        "rerank_score": max(0.0, base - i * second_gap)})
        return out

    def scored(self, scores, docs=None):
        """显式分数谱：用于分散/缺分/单行等 brief 生成器覆盖不到的形状。"""
        docs = docs or self.BRIEF_DOCS
        return [{"id": str(i), "file_name": docs[i % len(docs)], "rerank_score": s}
                for i, s in enumerate(scores)]

    # --- brief 逐字用例 -----------------------------------------------------
    def test_selective_skips_high_confidence_single_fact(self):
        from app.typesafe_router import should_judge
        need, reasons = should_judge("X200 的工作温度是多少", self.rows(0.9, 0.3))
        self.assertFalse(need, reasons)

    def test_low_margin_triggers(self):
        from app.typesafe_router import should_judge
        need, reasons = should_judge("年假怎么算", self.rows(0.8, 0.05))
        self.assertTrue(need); self.assertIn("margin", reasons)

    def test_floor_triggers_with_widest_pool(self):
        from app.typesafe_router import pick_candidate_count, should_judge
        rows = self.rows(0.1, 0.01)
        need, reasons = should_judge("随便说点什么", rows)
        self.assertTrue(need); self.assertIn("floor", reasons)
        self.assertEqual(pick_candidate_count("随便说点什么", rows), 12)

    def test_compound(self):
        from app.typesafe_router import pick_candidate_count, should_judge
        q = "对比 X100 和 X200 的工作温度，同时给出价格"
        # brief 脚注授权：现有 `is_compound_query` 要求每个分句自带疑问标记，
        # 该样例的分句都没有（"给出价格"非问句），故按 brief 允许在测试内 monkeypatch，
        # 不改判定器；真复合句另见 test_real_compound_query_needs_no_patch。
        with mock.patch("app.typesafe_router.is_compound_query", return_value=True):
            need, _ = should_judge(q, self.rows(0.9, 0.3))
            self.assertTrue(need)
            self.assertEqual(pick_candidate_count(q, self.rows(0.9, 0.3)), 8)

    def test_risk_marker_triggers(self):
        from app.typesafe_router import should_judge
        need, reasons = should_judge("劳动合同违约金的赔偿怎么算", self.rows(0.9, 0.3))
        self.assertTrue(need); self.assertIn("risk", reasons)

    def test_medium_margin_pool_size(self):
        from app.typesafe_router import pick_candidate_count
        self.assertEqual(pick_candidate_count("保修多久", self.rows(0.9, 0.15)), 4)

    def test_default_pool_size(self):
        from app.typesafe_router import pick_candidate_count
        self.assertEqual(pick_candidate_count("保修多久", self.rows(0.9, 0.05)), 6)

    # --- 信号矩阵补全（brief 要求 ≥8 例） -----------------------------------
    def test_real_compound_query_needs_no_patch(self):
        # 真实走 `is_compound_query`：两个分句各自带"是多少"，无需 monkeypatch。
        from app.typesafe_router import pick_candidate_count, should_judge
        q = "X100 的额定功率是多少瓦，同时 X200 的价格是多少元"
        need, reasons = should_judge(q, self.rows(0.9, 0.3))
        self.assertTrue(need)
        self.assertIn("compound", reasons)
        # 型号里的数字不算量值：复合句本身不应再叠出 param 信号。
        self.assertNotIn("param", reasons)
        self.assertEqual(pick_candidate_count(q, self.rows(0.9, 0.3)), 8)

    def test_cross_document_dispersion_triggers(self):
        from app.typesafe_router import should_judge
        # top1=0.55（<0.6）且四行文档互不相同；margin=0.30 > high ⇒ 只剩分散信号。
        need, reasons = should_judge("会议楼的预定规则是什么", self.rows(0.55, 0.30))
        self.assertTrue(need)
        self.assertIn("dispersed", reasons)

    def test_dispersion_needs_all_different_documents(self):
        from app.typesafe_router import should_judge
        rows = self.rows(0.55, 0.30, docs=("a.md", "b.md", "a.md", "c.md"))
        need, reasons = should_judge("会议楼的预定规则是什么", rows)
        self.assertNotIn("dispersed", reasons)
        self.assertFalse(need, reasons)     # 同文重复块 = 集中在一份文档，不算分散

    def test_dispersion_silent_when_top1_confident(self):
        from app.typesafe_router import should_judge
        need, reasons = should_judge("会议楼的预定规则是什么", self.rows(0.70, 0.30))
        self.assertFalse(need, reasons)     # 0.70 ≥ 0.60：分散阈值不看

    # --- F1（Fix round 1）：分散只在"确证的文档名"上触发 ----------------------
    def test_dispersion_needs_every_head_row_to_name_a_document(self):
        # `_is_dispersed` 的"缺文档名 ⇒ 整体不判分散"守卫此前无钉：把 `return False` 改成
        # `continue`（缺名行跳过、剩下的照比）三种形状全部误触发 ⇒ 本用例三条全红。
        from app.typesafe_router import _is_dispersed, should_judge
        shapes = {
            "缺 file_name 键": [
                {"id": "0", "file_name": "a.md", "rerank_score": 0.55},
                {"id": "1", "rerank_score": 0.25},          # 文档名缺失：无法确证跨文档
                {"id": "2", "file_name": "c.md", "rerank_score": 0.20},
                {"id": "3", "file_name": "d.md", "rerank_score": 0.15},
            ],
            "file_name 为空白": [
                {"id": "0", "file_name": "a.md", "rerank_score": 0.55},
                {"id": "1", "file_name": "   ", "rerank_score": 0.25},
                {"id": "2", "file_name": "c.md", "rerank_score": 0.20},
                {"id": "3", "file_name": "d.md", "rerank_score": 0.15},
            ],
            "行不是 dict": [
                {"id": "0", "file_name": "a.md", "rerank_score": 0.55},
                None,
            ],
        }
        for label, rows in shapes.items():
            with self.subTest(shape=label):
                self.assertFalse(_is_dispersed(rows))
                _, reasons = should_judge("会议楼的预定规则是什么", rows)
                self.assertNotIn("dispersed", reasons)

    def test_dispersion_is_false_when_no_document_name_is_confirmed(self):
        # F1 的另一半：头部候选**全部**缺文档名 + top1 < 0.6。这正是"跳过缺名行"实现里
        # `len(set(docs)) == len(docs)` 的真空真（0 == 0）形状，必须显式判 False；
        # 后半段的对照则锁"不是永远不触发"（否则本文件的 False 断言可被常量 False 蒙过）。
        from app.typesafe_router import _is_dispersed, should_judge
        anonymous = [{"id": "0", "rerank_score": 0.55}, {"id": "1", "rerank_score": 0.20}]
        self.assertFalse(_is_dispersed(anonymous))
        self.assertNotIn("dispersed", should_judge("会议楼的预定规则是什么", anonymous)[1])

        confirmed = [{"id": "0", "file_name": "a.md", "rerank_score": 0.55},
                     {"id": "1", "file_name": "b.md", "rerank_score": 0.20}]
        self.assertTrue(_is_dispersed(confirmed))
        self.assertIn("dispersed", should_judge("会议楼的预定规则是什么", confirmed)[1])

    def test_param_signal_needs_number_and_parameter_word(self):
        from app.typesafe_router import should_judge
        need, reasons = should_judge("X200 在 45 摄氏度下的功率是多少瓦", self.rows(0.9, 0.3))
        self.assertTrue(need)
        self.assertIn("param", reasons)     # 独立量值 45 + 参数词（功率/瓦）

    def test_model_number_alone_is_not_a_fact_signal(self):
        # 预裁决的另一半：型号里的数字（X200）与"支持/多少"共现都不算参数敏感。
        from app.typesafe_router import should_judge
        for query in ("X200 支持多少种接口", "X200 有几个型号 X300"):
            with self.subTest(query=query):
                need, reasons = should_judge(query, self.rows(0.9, 0.3))
                self.assertNotIn("param", reasons)
                self.assertFalse(need, reasons)

    def test_bare_number_without_parameter_word_is_not_a_fact_signal(self):
        # 预裁决的两条腿都要在：剔掉型号后仍有数字，但**没有参数词**同样不算参数敏感。
        # （变异自查：删掉 PARAMETER_WORDS 共现要求 → 本用例必须红。）
        from app.typesafe_router import should_judge
        for query in ("X200 有 3 个版本", "这份说明是 2020 年的第 5 版"):
            with self.subTest(query=query):
                need, reasons = should_judge(query, self.rows(0.9, 0.3))
                self.assertNotIn("param", reasons)
                self.assertFalse(need, reasons)

    def test_parameter_word_without_quantity_is_not_a_fact_signal(self):
        from app.typesafe_router import should_judge
        need, reasons = should_judge("设备功率看哪个指标", self.rows(0.9, 0.3))
        self.assertNotIn("param", reasons)
        self.assertFalse(need, reasons)

    def test_chinese_numeral_quantity_counts_and_measure_words_stay_narrow(self):
        from app.typesafe_router import should_judge
        # 中文数词 + 时长单位 = 量值（配参数词"小时"），与阿拉伯数字同权。
        need, reasons = should_judge("单程要坐六个小时吗", self.rows(0.9, 0.3))
        self.assertTrue(need)
        self.assertIn("param", reasons)
        # "十分"是副词不是量值：量词表刻意不含 分/人/件… 以免这类误报抬高触发率。
        need, reasons = should_judge("这个问题十分感谢你的帮助", self.rows(0.9, 0.3))
        self.assertNotIn("param", reasons)
        self.assertFalse(need, reasons)

    def test_single_char_units_do_not_leak_into_common_words(self):
        # 中文是子串匹配：单字单位（米/伏/安）会命中"米价/埋伏/安排"，故不入词表。
        from app.typesafe_router import PARAMETER_WORDS, should_judge
        for unit in ("米", "伏", "安"):
            self.assertNotIn(unit, PARAMETER_WORDS)
        need, reasons = should_judge("3 个工作日内安排好对接同事", self.rows(0.9, 0.3))
        self.assertNotIn("param", reasons)
        self.assertFalse(need, reasons)

    def test_negation_marker_triggers_fact_signal(self):
        # §3 的"否定"一支：显式排除短语命中即算参数/事实敏感。
        from app.typesafe_router import should_judge
        need, reasons = should_judge("加班补贴不包括外包人员吗", self.rows(0.9, 0.3))
        self.assertTrue(need)
        self.assertIn("param", reasons)

    # --- F2（Fix round 1）：`[Qq][1-4]` 时间支必须真的可达 ---------------------
    def test_quarter_time_signal_survives_model_stripping(self):
        # 缺陷原形：`_PRODUCT_MODEL` 在匹配**前**剔除字母+数字，`Q3` 形态上正好像型号，
        # 于是 `_QUERY_FACT_SIGNAL` 的 `[Qq][1-4]` 一支永不可达（"Q3 的价格是多少" 实测 False）。
        # 修复 = 在剔除正则开头加 lookahead 豁免 Q1-4；变异自查 = 撤掉豁免 ⇒ 前三条转红。
        from app.typesafe_router import _has_fact_signal
        for query in ("Q3 的价格是多少", "Q3 价格", "q4 的报价是多少"):
            with self.subTest(query=query):
                self.assertTrue(_has_fact_signal(query))
        # 豁免只到"字母恰为 Q + 数字恰为 1-4 且后面不接字母/数字/连接符"为止：
        # 真型号照旧剔干净（撤掉豁免只影响上面三条，这四条才是"豁免过头"的哨兵）。
        # 注：评审原文给的 `("X200 价格") True` 与 brief 逐字用例
        # `X200 的工作温度是多少` ⇒ 必须 skip 同构（型号 + 参数词、无独立量值），
        # 按 True 断言会直接推翻那条 brief 钉，故此处钉 False（详见报告"偏离"）。
        for query in ("X200", "X200 价格", "Q3S 的价格是多少", "XQ3 的价格是多少"):
            with self.subTest(query=query):
                self.assertFalse(_has_fact_signal(query))

    def test_quarter_price_question_reaches_public_param_reason(self):
        # 同一修复在公开面上的落点：季度价格题既进 selective 的 `param`，也不再被 active 免判。
        from app.typesafe_router import is_high_confidence_single_fact, should_judge
        query = "Q3 的价格是多少"
        need, reasons = should_judge(query, self.rows(0.9, 0.3))
        self.assertTrue(need, reasons)
        self.assertIn("param", reasons)
        self.assertFalse(is_high_confidence_single_fact(query, self.rows(0.9, 0.3)))

    def test_missing_rerank_score_is_treated_as_zero(self):
        from app.typesafe_router import should_judge
        rows = [{"id": "0", "file_name": "a.md"}, {"id": "1", "file_name": "b.md"}]
        need, reasons = should_judge("年假怎么算", rows)
        self.assertTrue(need)
        self.assertIn("floor", reasons)     # 缺分 ⇒ 0.0 < confidence_floor

    def test_single_row_counts_as_margin_trigger(self):
        # rows<2 无法算分差：视为触发（宁可多判，不做无依据的跳过）。
        from app.typesafe_router import pick_candidate_count, should_judge
        rows = self.scored([0.95])
        need, reasons = should_judge("年假怎么算", rows)
        self.assertTrue(need)
        self.assertIn("margin", reasons)
        # 但 TopK 分档仍按 margin=0 走默认档：触发语义与池宽解耦。
        self.assertEqual(pick_candidate_count("年假怎么算", rows), 6)

    def test_empty_rows_do_not_crash(self):
        from app.typesafe_router import pick_candidate_count, should_judge
        need, reasons = should_judge("随便问点什么", [])
        self.assertTrue(need)
        self.assertIn("margin", reasons)
        self.assertEqual(pick_candidate_count("随便问点什么", []), 12)

    def test_floor_wins_over_compound_in_topk(self):
        # spec §4 顺序：低置信（12）优先于复合（8）——两者冲突时取更宽池。
        from app.typesafe_router import pick_candidate_count
        rows = self.rows(0.1, 0.01)
        with mock.patch("app.typesafe_router.is_compound_query", return_value=True):
            self.assertEqual(pick_candidate_count("任意复合问句", rows), 12)

    def test_high_margin_pool_stays_narrowest_without_signals(self):
        from app.typesafe_router import pick_candidate_count
        self.assertEqual(pick_candidate_count("年假怎么算", self.rows(0.9, 0.3)), 3)

    def test_margin_tier_boundaries_are_exclusive(self):
        # 0.5 - 0.25 = 0.25 可被浮点精确表示：正好落在 high_margin 上。
        # spec §4 写的是 `margin > high_margin` ⇒ 等号不升档，落进 medium 档取 4。
        from app.typesafe_router import pick_candidate_count, should_judge
        rows = self.scored([0.50, 0.25, 0.20, 0.15])
        self.assertEqual(pick_candidate_count("年假怎么算", rows), 4)
        _, reasons = should_judge("会议楼的预定规则是什么", rows)
        self.assertNotIn("margin", reasons)     # 分差远大于 medium，不该报 margin
        # 刚过线即升档：0.5 - 0.24 = 0.26 > 0.25 → min 档。
        self.assertEqual(pick_candidate_count("年假怎么算", self.scored([0.50, 0.24, 0.2, 0.15])), 3)

    def test_nan_rerank_score_is_treated_as_zero(self):
        # NaN 会让 `top1 < floor` 静默为 False（等于永不触发）：必须先归零。
        from app.typesafe_router import should_judge
        rows = self.scored([float("nan"), float("nan")])
        need, reasons = should_judge("年假怎么算", rows)
        self.assertTrue(need)
        self.assertIn("floor", reasons)

    def test_reasons_order_is_the_declared_token_order(self):
        from app.typesafe_router import should_judge
        need, reasons = should_judge("劳动合同违约金的赔偿怎么算", self.rows(0.1, 0.01))
        self.assertTrue(need)
        self.assertEqual(reasons, ["margin", "floor", "risk", "dispersed"])

    def test_reasons_are_stable_known_tokens(self):
        from app.typesafe_router import REASON_TOKENS, should_judge
        cases = ("劳动合同违约金的赔偿怎么算", "X200 在 45 摄氏度下的功率是多少瓦",
                 "年假怎么算", "会议楼的预定规则是什么")
        for query, gap in ((cases[0], 0.3), (cases[1], 0.3), (cases[2], 0.05),
                           (cases[3], 0.30)):
            with self.subTest(query=query):
                need, reasons = should_judge(query, self.rows(0.55 if gap == 0.30 else 0.9, gap))
                self.assertTrue(need)
                self.assertTrue(set(reasons) <= set(REASON_TOKENS), reasons)
                self.assertEqual(reasons, sorted(reasons, key=REASON_TOKENS.index))
                self.assertEqual(should_judge(query, self.rows(0.55 if gap == 0.30 else 0.9, gap))[1],
                                 reasons)     # 同输入必同输出（纯函数）

    def test_router_is_pure_and_does_not_mutate_rows(self):
        from app.typesafe_router import pick_candidate_count, should_judge
        rows = self.rows(0.8, 0.05)
        snapshot = [dict(row) for row in rows]
        should_judge("年假怎么算", rows)
        pick_candidate_count("年假怎么算", rows)
        self.assertEqual(rows, snapshot)

    # --- active 档跳过组合（Task 6 消费） ------------------------------------
    def test_active_skip_only_for_high_confidence_single_fact(self):
        from app.typesafe_router import is_high_confidence_single_fact
        self.assertTrue(is_high_confidence_single_fact(
            "X200 的工作温度是多少", self.rows(0.9, 0.3)))
        for query, top1, gap in (
            ("劳动合同违约金的赔偿怎么算", 0.9, 0.3),      # 风险词
            ("年假怎么算", 0.9, 0.05),                     # 分差不够大
            ("会议楼的预定规则是什么", 0.55, 0.30),         # 跨文档分散
            ("X200 在 45 摄氏度下的功率是多少瓦", 0.9, 0.3),  # 参数敏感
        ):
            with self.subTest(query=query):
                self.assertFalse(is_high_confidence_single_fact(
                    query, self.rows(top1, gap)))

    def test_active_skip_is_never_wider_than_selective(self):
        # 模式单调性：active 比 selective 更费钱，凡 active 免判的 selective 必也免判。
        from app.typesafe_router import (is_high_confidence_single_fact, should_judge)
        queries = ("X200 的工作温度是多少", "劳动合同违约金的赔偿怎么算", "年假怎么算",
                   "会议楼的预定规则是什么", "X200 在 45 摄氏度下的功率是多少瓦",
                   "X100 的额定功率是多少瓦，同时 X200 的价格是多少元", "随便说点什么")
        for query in queries:
            for top1, gap in ((0.95, 0.30), (0.9, 0.3), (0.65, 0.3), (0.55, 0.3),
                              (0.8, 0.05), (0.1, 0.01), (0.9, 0.0)):
                with self.subTest(query=query, top1=top1, gap=gap):
                    rows = self.rows(top1, gap)
                    if is_high_confidence_single_fact(query, rows):
                        self.assertFalse(should_judge(query, rows)[0])

    # --- 公共面与阈值出处 ----------------------------------------------------
    def test_public_surface_matches_brief(self):
        import app.typesafe_router as router
        self.assertIsInstance(router.RISK_MARKERS, tuple)
        self.assertTrue(all(isinstance(m, str) and m for m in router.RISK_MARKERS))
        # brief 点名 `_QUERY_FACT_SIGNAL` 是"数字/时间/参数正则"：必须是已编译 pattern。
        self.assertIsInstance(router._QUERY_FACT_SIGNAL, re.Pattern)
        self.assertGreaterEqual(len(router.PARAMETER_WORDS), 8)

    def test_spec_thresholds_are_constants_not_magic_numbers(self):
        import app.typesafe_router as router
        # §3 的 0.6 分散经验线与 §4 的 medium 档 4（§8 无对应键，故留在代码里）。
        self.assertEqual(router._DISPERSED_TOP, 0.60)
        self.assertEqual(router._MEDIUM_MARGIN_CANDIDATES, 4)
        # nit（Fix round 1）：active 的高置信硬底线从 `_DISPERSED_TOP` 里拆出来单独命名，
        # 同值但语义无关；两者必须同值起步，且 `_ACTIVE_FLOOR >= _DISPERSED_TOP`
        # 是"active 免判集 ⊆ selective 免判集"的前提（Task 8 独立标定时也要守住）。
        self.assertEqual(router._ACTIVE_FLOOR, 0.60)
        self.assertGreaterEqual(router._ACTIVE_FLOOR, router._DISPERSED_TOP)

    def test_active_floor_and_dispersion_line_calibrate_independently(self):
        # 拆常量的唯一收益：Task 8 能各调各的。本用例证明 active 只读 `_ACTIVE_FLOOR`、
        # 分散只读 `_DISPERSED_TOP`，互不牵连（共用一个常量时任一方向的 patch 都会串味）。
        import app.typesafe_router as router
        rows = self.rows(0.65, 0.30)          # top1 ∈ (0.60, 0.70)，四文互不相同
        with mock.patch.object(router, "_ACTIVE_FLOOR", 0.70):
            self.assertFalse(router.is_high_confidence_single_fact("年假怎么算", rows))
        with mock.patch.object(router, "_ACTIVE_FLOOR", 0.60):
            self.assertTrue(router.is_high_confidence_single_fact("年假怎么算", rows))
        with mock.patch.object(router, "_DISPERSED_TOP", 0.70):
            self.assertIn("dispersed", router.should_judge("会议楼的预定规则是什么", rows)[1])
        with mock.patch.object(router, "_DISPERSED_TOP", 0.65):
            self.assertNotIn("dispersed", router.should_judge("会议楼的预定规则是什么", rows)[1])


class JudgeWiringTests(unittest.TestCase):
    """Task 5：`judge_candidates` 接入熔断/预算/缓存/滚动聚合（设计 §5/§6/§7）。

    隔离口径：本类**不碰**任何模块级共享态——`judgment_cache`、`typesafe_breaker`
    都被换成用例私有的实例（`ExitStack` 收尾还原），滚动聚合 setUp/tearDown 双向
    `reset_typesafe_stats()`，settings 逐键 patch。故既不读也不写现网单例的账。
    """

    LEGACY_METRIC_KEYS = {
        "typesafe_enabled", "typesafe_mode", "typesafe_degraded",
        "typesafe_request_count", "typesafe_input_tokens", "typesafe_output_tokens",
        "typesafe_estimated_cost_usd", "typesafe_latency_p50_ms",
        "typesafe_latency_p95_ms", "typesafe_total_ms",
        "typesafe_unauthorized_candidates_blocked", "typesafe_route_counts",
        "typesafe_models", "typesafe_errors",
    }
    NEW_METRIC_KEYS = {
        "typesafe_trigger", "typesafe_skipped", "typesafe_cache_hit",
        "typesafe_circuit_open", "typesafe_slow",
    }

    def setUp(self) -> None:
        import app.typesafe_judgments as tj

        self.tj = tj
        self.stack = ExitStack()
        for name, value in (
            ("typesafe_api_key", SecretStr("wire-test-key")),
            ("typesafe_enabled", True),
            ("typesafe_mode", "shadow"),
            ("typesafe_cache_enabled", True),
            ("typesafe_cache_max_entries", 64),
            ("typesafe_cache_ttl_seconds", 3600),
            ("typesafe_breaker_enabled", True),
            ("typesafe_max_concurrency", 2),
            ("typesafe_timeout_seconds", 8.0),
        ):
            self.stack.enter_context(mock.patch.object(settings, name, value))
        # 私有缓存实例：绝不污染模块单例（Task 3 的交接要求同样对测试成立）。
        self.stack.enter_context(
            mock.patch.object(
                tj, "judgment_cache",
                tj.JudgmentCache(max_entries=64, ttl_seconds=3600),
            )
        )
        self.use_breaker(
            CircuitBreaker(name="wire", window=8, failure_ratio=0.3,
                           open_seconds=60.0, half_open_probes=3)
        )
        tj.reset_typesafe_stats()
        self.stack.callback(tj.reset_typesafe_stats)
        self.factory_calls: list[str] = []

    def tearDown(self) -> None:
        self.stack.close()

    # --- 脚手架 --------------------------------------------------------------
    def use_breaker(self, breaker):
        self.stack.enter_context(mock.patch.object(self.tj, "typesafe_breaker", breaker))
        return breaker

    def service_for(self, client):
        def factory():
            self.factory_calls.append("constructed")
            return client
        return self.tj.TypeSafeJudgmentService(factory)

    def failing_factory_service(self):
        def factory():
            self.factory_calls.append("constructed")
            raise RuntimeError("client construction failed")
        return self.tj.TypeSafeJudgmentService(factory)

    def candidate(self, point_id: str, *, kb: str = "kb_product") -> dict:
        return {
            "id": point_id,
            "file_name": f"{point_id}.md",
            "section_title": "section",
            "knowledge_base_id": kb,
            "knowledge_base_name": "Product",
            "content": f"接线用例正文 {point_id}",
        }

    def make_client(self, *, clock=None, advance_seconds: float = 0.0, fail_for=(),
                    sleep_seconds: float = 0.003):
        """假客户端：默认每次外呼睡 3ms，让延迟分位落在可断言的正数上（而不是被 round 抹成 0）。"""
        return _WireClient(clock=clock, advance_seconds=advance_seconds,
                           fail_for=fail_for, sleep_seconds=sleep_seconds)

    def make_budget(self, *, soft_ms=1200.0, hard_ms=1800.0, elapsed_seconds=0.0):
        """假预算：`TimeoutBudget` 以构造时刻为零点，所以预算要先建、钟后推。"""
        clock = _WireClock()
        budget = TimeoutBudget(soft_ms=soft_ms, hard_ms=hard_ms, clock=clock)
        if elapsed_seconds:
            clock.advance(elapsed_seconds)
        return budget, clock

    def open_breaker(self, breaker: CircuitBreaker) -> CircuitBreaker:
        """用真实状态机把熔断器打开（window=8 ⇒ 门槛 max(4,4)=4 条失败即 trip）。"""
        for _ in range(4):
            breaker.record(False)
        self.assertEqual(breaker.state, "open")
        return breaker

    # --- 需求 2：mode 门 -----------------------------------------------------
    def test_mode_off_returns_empty_batch_with_zero_calls_and_zero_reads(self) -> None:
        query = "接线-off-模式-问句"
        rows = [self.candidate("tsv2-off-a")]
        # 先跑一次真实外呼把缓存喂热：off 分支必须连缓存都不读。
        warm = self.make_client()
        self.service_for(warm).judge_candidates(query, rows, knowledge_base_ids=["kb_product"])
        self.assertEqual(len(warm.calls), 1)
        self.factory_calls.clear()

        client = self.make_client()
        with mock.patch.object(settings, "typesafe_enabled", False), \
                mock.patch.object(settings, "typesafe_mode", "strict"):
            batch = self.service_for(client).judge_candidates(
                query, rows, knowledge_base_ids=["kb_product"])

        self.assertEqual(batch.judgments, {})          # enabled=false 恒等价 off
        self.assertEqual(client.calls, [])
        self.assertEqual(self.factory_calls, [])       # 连 client 都不构造
        self.assertEqual(batch.metrics["typesafe_skipped"], "off")
        self.assertFalse(batch.metrics["typesafe_trigger"])
        self.assertEqual(batch.metrics["typesafe_cache_hit"], 0)   # 预筛未发生
        self.assertFalse(batch.metrics["typesafe_degraded"])
        self.assertFalse(batch.metrics["typesafe_circuit_open"])
        self.assertEqual(batch.metrics["typesafe_errors"], [])
        # off 不进滚动样本：否则 trigger_rate 会被"根本没到判定层"的请求稀释。
        self.assertEqual(self.tj.typesafe_stats()["sample_count"], 1)  # 只有 warm 那次

    def test_mode_off_from_explicit_off_value(self) -> None:
        client = self.make_client()
        with mock.patch.object(settings, "typesafe_mode", "off"):
            batch = self.service_for(client).judge_candidates(
                "接线-off-字面值", [self.candidate("tsv2-off-b")],
                knowledge_base_ids=["kb_product"])
        self.assertEqual(client.calls, [])
        self.assertEqual(batch.metrics["typesafe_skipped"], "off")

    # --- 需求 3：熔断闸 ------------------------------------------------------
    def test_circuit_open_skips_calls_without_degrading(self) -> None:
        self.open_breaker(self.tj.typesafe_breaker)
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(
            "接线-熔断-问句",
            [self.candidate("tsv2-brk-a"), self.candidate("tsv2-brk-b")],
            knowledge_base_ids=["kb_product"],
        )
        self.assertEqual(client.calls, [])             # 零外呼
        self.assertEqual(self.factory_calls, [])
        self.assertTrue(batch.metrics["typesafe_circuit_open"])
        self.assertEqual(batch.metrics["typesafe_skipped"], "circuit_open")
        self.assertFalse(batch.metrics["typesafe_degraded"])   # 主动避险 ≠ 故障
        self.assertEqual(batch.metrics["typesafe_errors"], [])
        self.assertEqual(batch.metrics["typesafe_request_count"], 0)
        self.assertFalse(batch.metrics["typesafe_trigger"])
        sample = self.tj.typesafe_stats()
        self.assertEqual(sample["sample_count"], 1)
        self.assertEqual(sample["skip_rate"], 1.0)
        self.assertEqual(sample["degraded_rate"], 0.0)

    def test_circuit_open_never_records_receipts(self) -> None:
        # Task 1 交接第 2 条：allow() 为 False 时不得 record（否则污染切换后的新账）。
        spy = _BreakerSpy(allow_result=False)
        self.use_breaker(spy)
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(
            "接线-熔断-不回执", [self.candidate("tsv2-brk-c")],
            knowledge_base_ids=["kb_product"])
        self.assertEqual(spy.records, [])
        self.assertEqual(spy.allow_calls, 1)           # 一批一次预检，不轮询
        self.assertEqual(client.calls, [])
        self.assertTrue(batch.metrics["typesafe_circuit_open"])

    def test_circuit_open_still_delivers_cached_judgments(self) -> None:
        """自决口径（报告"偏离"）：命中是零成本的既有事实，熔断不该把它一起丢掉。"""
        query = "接线-熔断-含命中"
        rows = [self.candidate("tsv2-brk-d"), self.candidate("tsv2-brk-e")]
        warm = self.make_client()
        first = self.service_for(warm).judge_candidates(
            query, rows[:1], knowledge_base_ids=["kb_product"])
        self.assertEqual(first.metrics["typesafe_request_count"], 1)

        spy = _BreakerSpy(allow_result=False)
        self.use_breaker(spy)
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(
            query, rows, knowledge_base_ids=["kb_product"])
        self.assertEqual(client.calls, [])
        self.assertEqual(list(batch.judgments), ["tsv2-brk-d"])
        self.assertEqual(batch.metrics["typesafe_cache_hit"], 1)
        self.assertTrue(batch.metrics["typesafe_circuit_open"])
        self.assertFalse(batch.metrics["typesafe_degraded"])

    def test_half_open_probe_slots_are_not_wasted_on_all_cache_hits(self) -> None:
        # 全命中批次不该碰 allow()：HALF_OPEN 名额无租约回收，白拿=泄漏一个窗口。
        spy = _BreakerSpy(allow_result=True)
        self.use_breaker(spy)
        query = "接线-名额-问句"
        rows = [self.candidate("tsv2-slot-a")]
        warm = self.make_client()
        self.service_for(warm).judge_candidates(query, rows, knowledge_base_ids=["kb_product"])
        self.assertEqual(spy.allow_calls, 1)
        self.assertEqual(spy.records, [True])
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(
            query, rows, knowledge_base_ids=["kb_product"])
        self.assertEqual(client.calls, [])
        self.assertEqual(spy.allow_calls, 1)           # 第二次没拿名额
        self.assertEqual(spy.records, [True])
        self.assertEqual(batch.metrics["typesafe_cache_hit"], 1)

    def test_breaker_disabled_bypasses_gate_and_accounting(self) -> None:
        spy = _BreakerSpy(allow_result=False)
        self.use_breaker(spy)
        with mock.patch.object(settings, "typesafe_breaker_enabled", False):
            client = self.make_client()
            batch = self.service_for(client).judge_candidates(
                "接线-旁路-问句",
                [self.candidate("tsv2-byp-a"), self.candidate("tsv2-byp-b")],
                knowledge_base_ids=["kb_product"],
            )
        self.assertEqual(len(client.calls), 2)         # 旁路 = 照旧外呼
        self.assertEqual(spy.allow_calls, 0)
        self.assertEqual(spy.records, [])              # 旁路也不记账
        self.assertFalse(batch.metrics["typesafe_circuit_open"])
        self.assertEqual(batch.metrics["typesafe_request_count"], 2)

    # --- 需求 6：breaker 逐请求记账 ------------------------------------------
    def test_each_http_result_records_its_own_receipt(self) -> None:
        spy = _BreakerSpy(allow_result=True)
        self.use_breaker(spy)
        client = self.make_client(fail_for=("tsv2-acct-b.md",))
        batch = self.service_for(client).judge_candidates(
            "接线-回执-问句",
            [self.candidate("tsv2-acct-a"), self.candidate("tsv2-acct-b")],
            knowledge_base_ids=["kb_product"],
        )
        self.assertEqual(sorted(spy.records), [False, True])   # 2 次，不是一次"整批"回执
        self.assertEqual(spy.allow_calls, 1)
        self.assertEqual(batch.metrics["typesafe_request_count"], 2)
        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_errors"], ["RuntimeError"])

    def test_success_records_only_positive_receipts(self) -> None:
        spy = _BreakerSpy(allow_result=True)
        self.use_breaker(spy)
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(
            "接线-全成功-问句",
            [self.candidate("tsv2-ok-a"), self.candidate("tsv2-ok-b"),
             self.candidate("tsv2-ok-c")],
            knowledge_base_ids=["kb_product"],
        )
        self.assertEqual(spy.records, [True, True, True])
        self.assertFalse(batch.metrics["typesafe_degraded"])

    def test_client_construction_failure_is_not_a_dependency_failure(self) -> None:
        # 配置坏 ≠ 依赖坏：没发过 HTTP 就不该喂熔断器（否则坏 key 会误熔断）。
        spy = _BreakerSpy(allow_result=True)
        self.use_breaker(spy)
        batch = self.failing_factory_service().judge_candidates(
            "接线-构造失败", [self.candidate("tsv2-cfail-a")],
            knowledge_base_ids=["kb_product"])
        self.assertEqual(spy.allow_calls, 1)
        self.assertEqual(spy.records, [])
        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_request_count"], 0)
        self.assertEqual(batch.metrics["typesafe_errors"], ["RuntimeError"])

    # --- 需求 4：缓存预筛 ----------------------------------------------------
    def test_second_identical_call_is_served_from_cache_at_zero_cost(self) -> None:
        query = "接线-缓存-问句"
        rows = [self.candidate("tsv2-cache-a"), self.candidate("tsv2-cache-b")]
        first_client = self.make_client()
        first = self.service_for(first_client).judge_candidates(
            query, rows, knowledge_base_ids=["kb_product"])
        self.assertEqual(first.metrics["typesafe_request_count"], 2)
        self.assertEqual(first.metrics["typesafe_cache_hit"], 0)
        self.assertEqual(first.metrics["typesafe_input_tokens"], 200)
        self.assertTrue(first.metrics["typesafe_trigger"])
        self.assertGreater(first.metrics["typesafe_latency_p50_ms"], 0.0)

        second_client = self.make_client()
        second = self.service_for(second_client).judge_candidates(
            query, rows, knowledge_base_ids=["kb_product"])
        self.assertEqual(second_client.calls, [])           # 零外呼（新客户端也没被打过）
        self.assertEqual(second.metrics["typesafe_request_count"], 0)
        self.assertEqual(second.metrics["typesafe_cache_hit"], 2)   # 计数 = 命中条数
        self.assertEqual(second.metrics["typesafe_input_tokens"], 0)
        self.assertEqual(second.metrics["typesafe_output_tokens"], 0)
        self.assertEqual(second.metrics["typesafe_estimated_cost_usd"], 0.0)
        # 命中的 0ms 不进分位：否则 p50 被零值拉歪（Task 3 交接的"代价"）。
        self.assertEqual(second.metrics["typesafe_latency_p50_ms"], 0.0)
        self.assertEqual(second.metrics["typesafe_latency_p95_ms"], 0.0)
        self.assertFalse(second.metrics["typesafe_trigger"])
        self.assertFalse(second.metrics["typesafe_degraded"])
        self.assertEqual(sorted(second.judgments), ["tsv2-cache-a", "tsv2-cache-b"])
        self.assertEqual(
            second.metrics["typesafe_route_counts"], first.metrics["typesafe_route_counts"])
        for point_id in ("tsv2-cache-a", "tsv2-cache-b"):
            hit = second.judgments[point_id]
            fresh = first.judgments[point_id]
            self.assertTrue(hit.from_cache)
            self.assertEqual(hit.row_fields(), fresh.row_fields())  # 判定本身完整

    def test_cache_disabled_still_calls_out(self) -> None:
        query = "接线-缓存关闭-问句"
        rows = [self.candidate("tsv2-nocache-a")]
        warm = self.make_client()
        self.service_for(warm).judge_candidates(query, rows, knowledge_base_ids=["kb_product"])
        with mock.patch.object(settings, "typesafe_cache_enabled", False):
            client = self.make_client()
            batch = self.service_for(client).judge_candidates(
                query, rows, knowledge_base_ids=["kb_product"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(batch.metrics["typesafe_request_count"], 1)
        self.assertEqual(batch.metrics["typesafe_cache_hit"], 0)

    # --- 需求 5：预算 --------------------------------------------------------
    def test_pre_exhausted_budget_stops_calls_before_breaker(self) -> None:
        spy = _BreakerSpy(allow_result=True)
        self.use_breaker(spy)
        budget, _clock = self.make_budget(soft_ms=100.0, hard_ms=1000.0, elapsed_seconds=5.0)
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(
            "接线-预算耗尽", [self.candidate("tsv2-bud-a")],
            knowledge_base_ids=["kb_product"], budget=budget)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.factory_calls, [])
        self.assertEqual(spy.allow_calls, 0)           # 预算先于名额：不白拿不泄漏
        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_errors"], ["budget_exhausted"])
        self.assertEqual(batch.metrics["typesafe_skipped"], "budget_exhausted")
        self.assertFalse(batch.metrics["typesafe_circuit_open"])
        self.assertTrue(batch.metrics["typesafe_slow"])          # 5000ms > soft 100ms
        self.assertEqual(batch.metrics["typesafe_request_count"], 0)

    def test_budget_without_hard_stop_marks_slow_only(self) -> None:
        budget, clock = self.make_budget(soft_ms=1000.0, hard_ms=5000.0)
        client = self.make_client(clock=clock, advance_seconds=1.5)
        batch = self.service_for(client).judge_candidates(
            "接线-超软线",
            [self.candidate("tsv2-slow-a"), self.candidate("tsv2-slow-b"),
             self.candidate("tsv2-slow-c")],
            knowledge_base_ids=["kb_product"], budget=budget)
        self.assertEqual(batch.metrics["typesafe_request_count"], 3)
        self.assertEqual(batch.metrics["typesafe_cache_hit"], 0)
        self.assertTrue(batch.metrics["typesafe_slow"])
        self.assertFalse(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_errors"], [])
        self.assertIsNone(batch.metrics["typesafe_skipped"])
        self.assertTrue(batch.metrics["typesafe_trigger"])

    def test_no_budget_keeps_v1_timeout_and_slow_semantics(self) -> None:
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(
            "接线-无预算", [self.candidate("tsv2-nobud-a")],
            knowledge_base_ids=["kb_product"])
        self.assertEqual(client.calls[0]["timeout"], float(settings.typesafe_timeout_seconds))
        self.assertFalse(batch.metrics["typesafe_slow"])     # 没有预算就没有软线

    def test_budget_caps_per_request_timeout_and_floors_it(self) -> None:
        budget, _clock = self.make_budget(soft_ms=300.0, hard_ms=1800.0)
        client = self.make_client()
        self.service_for(client).judge_candidates(
            "接线-预算上限", [self.candidate("tsv2-cap-a")],
            knowledge_base_ids=["kb_product"], budget=budget)
        used = client.calls[0]["timeout"]
        self.assertLessEqual(used, 1.8)
        self.assertLess(used, float(settings.typesafe_timeout_seconds))
        self.assertGreater(used, self.tj.MIN_REQUEST_TIMEOUT_SECONDS)

        # 只剩 50ms：min(8, 0.05) 会喂出近乎必死的超时 ⇒ 必须钳到下限。
        tight, _ = self.make_budget(soft_ms=100.0, hard_ms=2000.0, elapsed_seconds=1.95)
        late = self.make_client()
        batch = self.service_for(late).judge_candidates(
            "接线-超时下限", [self.candidate("tsv2-cap-b")],
            knowledge_base_ids=["kb_product"], budget=tight)
        self.assertAlmostEqual(late.calls[0]["timeout"], self.tj.MIN_REQUEST_TIMEOUT_SECONDS,
                               places=9)
        self.assertFalse(batch.metrics["typesafe_degraded"])

    def test_budget_tripping_mid_batch_degrades_and_cancels_pending(self) -> None:
        budget, clock = self.make_budget(soft_ms=100.0, hard_ms=1000.0)
        client = self.make_client(clock=clock, advance_seconds=1.2)
        batch = self.service_for(client).judge_candidates(
            "接线-中途耗尽",
            [self.candidate("tsv2-mid-a"), self.candidate("tsv2-mid-b"),
             self.candidate("tsv2-mid-c")],
            knowledge_base_ids=["kb_product"], budget=budget)
        # 完成顺序/取消时机由线程调度决定 ⇒ 只断言"与调度无关"的不变式；
        # 其中 request_count == 真外呼次数这条正是评审 M1 的口径（被取消的没发 HTTP）。
        self.assertIn("budget_exhausted", batch.metrics["typesafe_errors"])
        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertTrue(batch.metrics["typesafe_slow"])
        self.assertEqual(batch.metrics["typesafe_skipped"], "budget_exhausted")
        self.assertGreaterEqual(batch.metrics["typesafe_request_count"], 1)
        self.assertLessEqual(batch.metrics["typesafe_request_count"], 3)
        self.assertEqual(batch.metrics["typesafe_request_count"], len(client.calls))
        self.assertLessEqual(len(batch.judgments), 3)

    def test_request_count_drops_the_tasks_the_budget_cancelled(self) -> None:
        """评审 M1：排队中被 `cancel()` 的任务没发过 HTTP，不得进 `typesafe_request_count`。

        单 worker + 0.4s 外呼把取消时刻钉死：第 1 条跑完 ⇒ 第 2 条接手在跑（取消失败）、
        第 3 条还在队列里（取消必成）⇒ 真外呼 2 次，而"提交即计数"的旧口径会报 3 次。
        """
        budget = _StubBudget(exhausted_after=4)   # 1 次预筛 + 3 次提交都说"还有预算"
        client = self.make_client(sleep_seconds=0.4)
        with mock.patch.object(settings, "typesafe_max_concurrency", 1):
            batch = self.service_for(client).judge_candidates(
                "接线-取消不计",
                [self.candidate("tsv2-cancel-a"), self.candidate("tsv2-cancel-b"),
                 self.candidate("tsv2-cancel-c")],
                knowledge_base_ids=["kb_product"], budget=budget)
        self.assertGreaterEqual(budget.asked, 5)             # 取消确实发生在收集循环那道闸
        self.assertEqual(batch.metrics["typesafe_request_count"], 2)
        self.assertEqual(batch.metrics["typesafe_request_count"], len(client.calls))
        self.assertEqual(
            sorted(call["title"] for call in client.calls),
            ["tsv2-cancel-a.md", "tsv2-cancel-b.md"])
        self.assertEqual(list(batch.judgments), ["tsv2-cancel-a", "tsv2-cancel-b"])
        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_skipped"], "budget_exhausted")
        # 聚合样本用的是同一个数：预算窗口里的 calls/query 不能被虚高污染。
        self.assertEqual(
            self.tj.typesafe_stats()["requests_per_query_p95"], 2.0)

    def test_budget_present_disables_sdk_retry_and_absent_keeps_client_policy(self) -> None:
        """评审 I1：预算在场时每请求必须带 `max_retries=0` 的 per-call 重试策略。

        不传的话就吃 client 级 `max_retries=2 + backoff`，最坏 3 次尝试 × 8s 直接突破硬线。
        `system_one` 的 `retry=` 是 per-call 覆盖（SDK 签名已确认），故不需要另造 client。
        """
        from typesafe_sdk import RetryPolicy

        budget, _clock = self.make_budget(soft_ms=1200.0, hard_ms=1800.0)
        client = self.make_client()
        self.service_for(client).judge_candidates(
            "接线-重试钳制",
            [self.candidate("tsv2-retry-a"), self.candidate("tsv2-retry-b")],
            knowledge_base_ids=["kb_product"], budget=budget)
        self.assertEqual(len(client.calls), 2)
        for call in client.calls:
            with self.subTest(title=call["title"]):
                policy = call.get("retry")
                self.assertIsInstance(policy, RetryPolicy)
                self.assertEqual(policy.max_retries, 0)          # 一次调用 == 一次尝试
                self.assertEqual(policy.backoff_initial, 0.0)    # 不许长出退避等待
                self.assertEqual(policy.backoff_max, 0.0)
                # 整次调用（含重试预算）不超过本次请求的预算派生上限。
                self.assertEqual(policy.timeout, call["timeout"])
                self.assertLessEqual(policy.timeout, 1.8)

        # 无预算 = V1 调用式：连 `retry` 这个 kwargs 都不出现，重试口径逐字不变。
        plain = self.make_client()
        self.service_for(plain).judge_candidates(
            "接线-无预算不覆盖重试", [self.candidate("tsv2-retry-c")],
            knowledge_base_ids=["kb_product"])
        self.assertNotIn("retry", plain.calls[0])
        self.assertEqual(plain.calls[0]["timeout"], float(settings.typesafe_timeout_seconds))

    def test_submission_loop_stops_at_the_first_budget_check_that_says_no(self) -> None:
        # 需求 5 的"提交任务前逐条问预算"：真钟 + 线程的时序不可复现，故用替身把
        # 这条闸单独逼出来（第 1 问 = 预筛闸说"还能跑"，第 2 问 = 首次提交前说"没了"）。
        budget = _StubBudget(exhausted_after=1)
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(
            "接线-提交闸",
            [self.candidate("tsv2-stop-a"), self.candidate("tsv2-stop-b")],
            knowledge_base_ids=["kb_product"], budget=budget)
        self.assertGreaterEqual(budget.asked, 2)
        self.assertEqual(client.calls, [])             # 一条都没发出去（省的是真金白银）
        # 预筛那一次问的是"还能跑"，所以 client 已按 Promise 构造好但从未被使用：
        # 构造 HTTP client 本身不外呼（零外呼口径仍成立），真正省钱的是下面的 0 请求。
        self.assertEqual(len(self.factory_calls), 1)
        self.assertEqual(batch.metrics["typesafe_request_count"], 0)
        self.assertEqual(batch.metrics["typesafe_errors"], ["budget_exhausted"])
        self.assertTrue(batch.metrics["typesafe_degraded"])
        self.assertEqual(batch.metrics["typesafe_skipped"], "budget_exhausted")
        # slow 只由 over_soft 决定（替身说没过软线）：预算耗尽与超慢是两个独立信号。
        self.assertFalse(batch.metrics["typesafe_slow"])

    # --- 需求 7：滚动聚合 ----------------------------------------------------
    def test_stats_roll_up_trigger_skip_cache_and_latency(self) -> None:
        query = "接线-聚合-问句"
        rows = [self.candidate("tsv2-agg-a"), self.candidate("tsv2-agg-b")]
        fresh = self.make_client()
        self.service_for(fresh).judge_candidates(
            query, rows, knowledge_base_ids=["kb_product"])                  # 样本 1
        cached = self.make_client()
        self.service_for(cached).judge_candidates(
            query, rows, knowledge_base_ids=["kb_product"])                  # 样本 2（全命中）
        budget, _clock = self.make_budget(soft_ms=100.0, hard_ms=1000.0, elapsed_seconds=5.0)
        skipped = self.make_client()
        self.service_for(skipped).judge_candidates(
            "接线-聚合-第三条", [self.candidate("tsv2-agg-c")],
            knowledge_base_ids=["kb_product"], budget=budget)                # 样本 3

        stats = self.tj.typesafe_stats()
        self.assertEqual(stats["sample_count"], 3)
        self.assertAlmostEqual(stats["trigger_rate"], 1 / 3, places=5)
        self.assertAlmostEqual(stats["skip_rate"], 1 / 3, places=5)
        self.assertAlmostEqual(stats["degraded_rate"], 1 / 3, places=5)
        self.assertAlmostEqual(stats["timeout_rate"], 1 / 3, places=5)
        self.assertAlmostEqual(stats["slow_rate"], 1 / 3, places=5)
        # 2 次外呼 + 2 次命中 ⇒ 送出的判定里一半来自缓存。
        self.assertAlmostEqual(stats["cache_hit_ratio"], 0.5, places=6)
        self.assertEqual(stats["requests_per_query_p50"], 0.0)   # [2,0,0] 的中位数
        self.assertEqual(stats["requests_per_query_p95"], 2.0)
        self.assertEqual(stats["input_tokens_per_query_p50"], 0.0)
        self.assertGreater(stats["latency_p50_ms"], 0.0)         # 只有真实外呼入样
        self.assertGreaterEqual(stats["latency_p95_ms"], stats["latency_p50_ms"])
        self.assertEqual(stats["breaker_state"], "closed")

        self.tj.reset_typesafe_stats()
        blank = self.tj.typesafe_stats()
        self.assertEqual(blank["sample_count"], 0)
        for name in ("trigger_rate", "skip_rate", "cache_hit_ratio", "timeout_rate",
                     "degraded_rate", "slow_rate", "requests_per_query_p50",
                     "requests_per_query_p95", "input_tokens_per_query_p50",
                     "cost_per_query_p50", "latency_p50_ms", "latency_p95_ms"):
            with self.subTest(key=name):
                self.assertEqual(blank[name], 0.0)

    def test_stats_report_cost_per_query_p50_on_the_design_price_formula(self) -> None:
        """§7 的 `cost_per_query`：单价在读取时现取，样本只存 tokens（避免双口径）。"""
        with mock.patch.object(settings, "typesafe_input_price_per_million_usd", 0.042):
            client = self.make_client()
            batch = self.service_for(client).judge_candidates(
                "接线-成本-问句",
                [self.candidate("tsv2-cost-a"), self.candidate("tsv2-cost-b")],
                knowledge_base_ids=["kb_product"])
            stats = self.tj.typesafe_stats()
            # 2 条外呼 × 100 input tokens，与 metrics 侧 typesafe_estimated_cost_usd 同式。
            self.assertEqual(batch.metrics["typesafe_input_tokens"], 200)
            self.assertEqual(
                stats["cost_per_query_p50"],
                batch.metrics["typesafe_estimated_cost_usd"],
            )
            self.assertEqual(stats["cost_per_query_p50"], round(200 / 1_000_000 * 0.042, 8))
            # 改单价后旧样本按当前价重算（证明存的是 tokens 不是钱）。
            with mock.patch.object(settings, "typesafe_input_price_per_million_usd", 1.0):
                self.assertEqual(
                    self.tj.typesafe_stats()["cost_per_query_p50"], 200 / 1_000_000)
        # 缓存命中的判定 tokens 恒 0 ⇒ 成本分位也恒 0，不会把零请求算成开销。
        self.tj.reset_typesafe_stats()
        cached_client = self.make_client()
        cached = self.service_for(cached_client).judge_candidates(
            "接线-成本-问句",
            [self.candidate("tsv2-cost-a"), self.candidate("tsv2-cost-b")],
            knowledge_base_ids=["kb_product"])
        self.assertEqual(cached_client.calls, [])
        self.assertEqual(cached.metrics["typesafe_cache_hit"], 2)
        self.assertEqual(self.tj.typesafe_stats()["cost_per_query_p50"], 0.0)

    def test_stats_window_rolls_and_drops_the_oldest_sample(self) -> None:
        self.tj._record_typesafe_sample(
            {"request_count": 0, "cache_hit": 0, "triggered": False, "skipped": False,
             "degraded": False, "slow": False, "timeout": False, "input_tokens": 0,
             "latencies": []})
        for _ in range(self.tj.STATS_WINDOW):
            self.tj._record_typesafe_sample(
                {"request_count": 3, "cache_hit": 0, "triggered": True, "skipped": False,
                 "degraded": False, "slow": False, "timeout": False, "input_tokens": 300,
                 "latencies": [10.0]})
        stats = self.tj.typesafe_stats()
        self.assertEqual(stats["sample_count"], self.tj.STATS_WINDOW)   # 溢出即滚掉最旧
        self.assertEqual(stats["trigger_rate"], 1.0)
        self.assertEqual(stats["requests_per_query_p95"], 3.0)
        self.assertEqual(stats["cache_hit_ratio"], 0.0)

    def test_aggregate_keys_never_reach_batch_metrics(self) -> None:
        # 需求 7：stats 不上任何响应，Task 7 才经白名单出。
        client = self.make_client()
        metrics = self.service_for(client).judge_candidates(
            "接线-不外泄", [self.candidate("tsv2-leak-a")],
            knowledge_base_ids=["kb_product"]).metrics
        for name in self.tj.typesafe_stats():
            with self.subTest(key=name):
                self.assertNotIn(name, metrics)

    # --- 需求 9：预算工厂（Task 2 移交的跨字段兜底） -------------------------
    def test_make_budget_returns_none_when_mode_off(self) -> None:
        with mock.patch.object(settings, "typesafe_enabled", False):
            self.assertIsNone(self.tj.make_budget_from_settings())
        with mock.patch.object(settings, "typesafe_mode", "off"):
            self.assertIsNone(self.tj.make_budget_from_settings())

    def test_make_budget_uses_configured_soft_and_hard_lines(self) -> None:
        budget = self.tj.make_budget_from_settings()
        self.assertIsNotNone(budget)
        self.assertEqual(budget._soft, float(settings.typesafe_soft_timeout_ms))
        self.assertEqual(budget._hard, float(settings.typesafe_hard_timeout_ms))
        self.assertLessEqual(budget._soft, budget._hard)

    def test_make_budget_is_fresh_per_call_and_not_a_process_singleton(self) -> None:
        # 段B2 缺陷1 定案后的钉：spec §5「批次以 `typesafe_hard_timeout_ms` 包预算」的语义对象
        # 是**一个判定批次** ⇒ 工厂必须逐 call 造新预算（`TimeoutBudget` 以构造时刻为零点）。
        # 若日后有人把它提成模块级单例（或挪到循环外造一条复用），第二条批次会继承第一条的
        # 已耗时而凭空 `budget_exhausted` —— 那正是段B 报告怀疑的症状，此处反向钉死。
        with ExitStack() as stack:
            for name, value in (("typesafe_enabled", True), ("typesafe_mode", "strict")):
                stack.enter_context(mock.patch.object(settings, name, value))
            first = self.tj.make_budget_from_settings()
            second = self.tj.make_budget_from_settings()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNot(first, second)
        self.assertIsNot(second, self.tj.make_budget_from_settings())
        # 把第一条"烧穿"（`_started` 前移 10s == 已耗 10000ms）：只有独立计时才会互不影响。
        first._started -= 10.0
        self.assertTrue(first.exhausted())
        self.assertFalse(second.exhausted())
        self.assertGreater(second.remaining_ms(), 0.95 * second._hard)
        # 终值本身也是标定结论：类默认值 hard=3000 / soft=1200（段A/段B 实测否证 1800 属
        # 低于现网 P95 的配置错配）。取类默认值而非全局 `settings`——宿主 backend/.env 可以
        # 合法覆盖 env 面，那样钉的就不是"出厂终值"。
        with mock.patch.dict(os.environ, {}, clear=True):
            shipped = Settings(_env_file=None)
        self.assertEqual(int(second._hard), int(settings.typesafe_hard_timeout_ms))
        self.assertEqual(shipped.typesafe_hard_timeout_ms, 3000)
        self.assertEqual(shipped.typesafe_soft_timeout_ms, 1200)

    def test_make_budget_clamps_soft_above_hard_instead_of_raising(self) -> None:
        # TimeoutBudget 构造期对 soft>hard 抛 ValueError；软线写歪不该把检索打成 500。
        with mock.patch.object(settings, "typesafe_soft_timeout_ms", 99999), \
                mock.patch.object(settings, "typesafe_hard_timeout_ms", 1800):
            budget = self.tj.make_budget_from_settings()
        self.assertIsNotNone(budget)
        self.assertEqual(budget._soft, 1800.0)
        self.assertEqual(budget._hard, 1800.0)
        self.assertFalse(budget.over_soft())          # 钳制生效：刚构造不算"超软线"
        self.assertFalse(budget.exhausted())

    def test_make_budget_clamps_non_positive_soft_and_hard(self) -> None:
        with mock.patch.object(settings, "typesafe_soft_timeout_ms", 0), \
                mock.patch.object(settings, "typesafe_hard_timeout_ms", 1800):
            budget = self.tj.make_budget_from_settings()
        self.assertIsNotNone(budget)
        self.assertEqual(budget._soft, 1800.0)
        with mock.patch.object(settings, "typesafe_hard_timeout_ms", 0):
            self.assertIsNone(self.tj.make_budget_from_settings())

    # --- 需求 1/8：接口冻结（签名 + 键集合） ---------------------------------
    def test_budget_argument_is_optional_and_metrics_keys_are_frozen(self) -> None:
        client = self.make_client()
        batch = self.service_for(client).judge_candidates(   # 不传 budget = V1 调用式
            "接线-签名", [self.candidate("tsv2-sig-a")], knowledge_base_ids=["kb_product"])
        self.assertEqual(set(batch.metrics), self.LEGACY_METRIC_KEYS | self.NEW_METRIC_KEYS)
        self.assertFalse(batch.metrics["typesafe_degraded"])

    # --- 不变式（评审 (a)②）：三元组只可能出自熔断路径 -----------------------
    def probe_path(self, *, query, rows, eligible, kb=("kb_product",), patches=(),
                   breaker=None, budget=None, service=None, fail_for=()):
        """跑一条早退/异常路径，返回 `(degraded, typesafe_circuit_open, 判定不全)` 三元组。

        顺带在每条路径上复核评审 M1 的口径：`typesafe_request_count` == 真实外呼次数。
        """
        client = self.make_client(fail_for=fail_for)
        with ExitStack() as stack:
            for name, value in patches:
                stack.enter_context(mock.patch.object(settings, name, value))
            if breaker is not None:
                stack.enter_context(mock.patch.object(self.tj, "typesafe_breaker", breaker))
            batch = (service or self.service_for(client)).judge_candidates(
                query, rows, knowledge_base_ids=(list(kb) if kb else None), budget=budget)
        metrics = batch.metrics
        self.assertEqual(metrics["typesafe_request_count"], len(client.calls))
        return (
            metrics["typesafe_degraded"],
            metrics["typesafe_circuit_open"],
            len(batch.judgments) < eligible,
        )

    def test_incomplete_but_not_degraded_only_comes_from_the_circuit_open_branch(self) -> None:
        """三元组 `(degraded=False ∧ circuit_open=True ∧ 判定不全)` 是熔断路径的专属签名。

        这条不变式是 Task 6 应用条件的地基：除熔断外，任何"没 degraded 却判定不全"的路径
        都不存在（off 虽然不全但 `circuit_open=False`，故它不落入该组合）。
        """
        open_spy = _BreakerSpy(allow_result=False)
        pre_exhausted, _clock = self.make_budget(
            soft_ms=100.0, hard_ms=1000.0, elapsed_seconds=5.0)
        warm_rows = [self.candidate("tsv2-tri-warm")]
        warm = self.make_client()
        self.service_for(warm).judge_candidates(
            "接线-三元组-预热", warm_rows, knowledge_base_ids=["kb_product"])

        triples = {
            "off": self.probe_path(
                query="接线-三元组-off", rows=[self.candidate("tsv2-tri-off")], eligible=1,
                patches=(("typesafe_enabled", False),)),
            "空候选行": self.probe_path(
                query="接线-三元组-空", rows=[], eligible=0),
            "无授权范围": self.probe_path(
                query="接线-三元组-范围", rows=[self.candidate("tsv2-tri-scope")],
                kb=None, eligible=0),
            "越权块": self.probe_path(
                query="接线-三元组-越权",
                rows=[self.candidate("tsv2-tri-deny", kb="kb_hr")], eligible=0),
            "无 key": self.probe_path(
                query="接线-三元组-key", rows=[self.candidate("tsv2-tri-key")], eligible=1,
                patches=(("typesafe_api_key", SecretStr("")),)),
            "预算预耗尽": self.probe_path(
                query="接线-三元组-预耗尽", rows=[self.candidate("tsv2-tri-bud")],
                eligible=1, budget=pre_exhausted),
            "提交闸耗尽": self.probe_path(
                query="接线-三元组-提交闸",
                rows=[self.candidate("tsv2-tri-stop-a"), self.candidate("tsv2-tri-stop-b")],
                eligible=2, budget=_StubBudget(exhausted_after=1)),
            "熔断-零命中": self.probe_path(
                query="接线-三元组-熔断",
                rows=[self.candidate("tsv2-tri-brk-a"), self.candidate("tsv2-tri-brk-b")],
                eligible=2, breaker=open_spy),
            "熔断-含命中": self.probe_path(
                query="接线-三元组-预热", rows=warm_rows + [self.candidate("tsv2-tri-brk-c")],
                eligible=2, breaker=open_spy),
            "全命中": self.probe_path(
                query="接线-三元组-预热", rows=warm_rows, eligible=1),
            "全成功": self.probe_path(
                query="接线-三元组-成功", rows=[self.candidate("tsv2-tri-ok")], eligible=1),
            "部分失败": self.probe_path(
                query="接线-三元组-半失败",
                rows=[self.candidate("tsv2-tri-half-a"), self.candidate("tsv2-tri-half-b")],
                eligible=2, fail_for=("tsv2-tri-half-b.md",)),
            "client构造失败": self.probe_path(
                query="接线-三元组-构造失败", rows=[self.candidate("tsv2-tri-cfail")],
                eligible=1, service=self.failing_factory_service()),
        }
        expected = {
            "off": (False, False, True),               # 不判定 ≠ 故障：但也不算熔断
            "空候选行": (False, False, False),
            "无授权范围": (True, False, False),
            "越权块": (True, False, False),
            "无 key": (True, False, True),
            "预算预耗尽": (True, False, True),
            "提交闸耗尽": (True, False, True),
            "熔断-零命中": (False, True, True),         # ← 目标组合
            "熔断-含命中": (False, True, True),         # ← 目标组合（只交付缓存命中）
            "全命中": (False, False, False),
            "全成功": (False, False, False),
            "部分失败": (True, False, True),
            "client构造失败": (True, False, True),
        }
        self.assertEqual(set(triples), set(expected))
        for label, got in triples.items():
            with self.subTest(path=label):
                self.assertEqual(got, expected[label])
        matching = {label for label, got in triples.items() if got == (False, True, True)}
        self.assertEqual(matching, {"熔断-零命中", "熔断-含命中"})
        # 反面同样成立：`circuit_open=True` 只出现在那两条，且它们恒不 degraded。
        open_labels = {label for label, (_, circuit_open, _) in triples.items() if circuit_open}
        self.assertEqual(open_labels, matching)

    def metrics_for(self, query, rows, *, kb, settings_patches=(), breaker=None):
        """跑一次 judge 并先钉住键集合：早退路径也不许漏键（Task 7 白名单按全集出）。"""
        client = self.make_client()
        with ExitStack() as stack:
            for name, value in settings_patches:
                stack.enter_context(mock.patch.object(settings, name, value))
            if breaker is not None:
                stack.enter_context(mock.patch.object(self.tj, "typesafe_breaker", breaker))
            batch = self.service_for(client).judge_candidates(
                query, rows, knowledge_base_ids=kb)
        self.assertEqual(set(batch.metrics), self.LEGACY_METRIC_KEYS | self.NEW_METRIC_KEYS)
        self.assertEqual(client.calls, [])      # 这些路径全都零外呼
        return batch.metrics

    def test_new_keys_are_present_on_every_early_return_path(self) -> None:
        cases = {
            "off": self.metrics_for(
                "接线-键-off", [self.candidate("tsv2-key-off")],
                kb=["kb_product"], settings_patches=(("typesafe_enabled", False),)),
            "无候选行": self.metrics_for("接线-键-空", [], kb=["kb_product"]),
            "无授权范围": self.metrics_for(
                "接线-键-范围", [self.candidate("tsv2-key-scope")], kb=None),
            "越权块": self.metrics_for(
                "接线-键-越权", [self.candidate("tsv2-key-deny", kb="kb_hr")],
                kb=["kb_product"]),
            "无 key": self.metrics_for(
                "接线-键-key", [self.candidate("tsv2-key-none")],
                kb=["kb_product"],
                settings_patches=(("typesafe_api_key", SecretStr("")),)),
            "熔断": self.metrics_for(
                "接线-键-熔断", [self.candidate("tsv2-key-brk")], kb=["kb_product"],
                breaker=_BreakerSpy(allow_result=False)),
        }
        self.assertEqual(len(cases), 6)
        for label, metrics in cases.items():
            with self.subTest(path=label):
                self.assertIsInstance(metrics["typesafe_trigger"], bool)
                self.assertIsInstance(metrics["typesafe_circuit_open"], bool)
                self.assertIsInstance(metrics["typesafe_slow"], bool)
                self.assertIsInstance(metrics["typesafe_cache_hit"], int)
                self.assertIn(metrics["typesafe_skipped"],
                              (None, "off", "circuit_open", "budget_exhausted"))
                self.assertEqual(metrics["typesafe_request_count"], 0)


class _WireClock:
    """与 time.perf_counter 同纲（秒）的假钟：`TimeoutBudget` 内部做 *1000 换算。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _WireClient:
    """假 TypeSafeClient：计外呼次数、记录 kwargs（含 per-request timeout）、可注入故障。

    `calls` 由用例共享，因此同一用例里多次 judge_candidates 也能对得上总数。
    """

    ANSWERS = {
        "is_relevant": 0.95,
        "contains_answer_evidence": 0.90,
        "contradicts_query_premise": 0.0,
        "contains_prompt_injection": 0.0,
    }

    def __init__(self, *, clock=None, advance_seconds: float = 0.0,
                 fail_for=(), sleep_seconds: float = 0.0) -> None:
        self.clock = clock
        self.advance_seconds = advance_seconds
        self.fail_for = set(fail_for)
        self.sleep_seconds = sleep_seconds
        self.calls: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def system_one(self, *, state, questions, **kwargs):
        title = state["candidate_passage"]["document_title"]
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        self.calls.append({"title": title, "questions": questions, **kwargs})
        if self.clock is not None and self.advance_seconds:
            self.clock.advance(self.advance_seconds)
        if title in self.fail_for:
            raise RuntimeError(f"provider exploded for {title}")
        return SimpleNamespace(
            model="jev-wire",
            usage=SimpleNamespace(input_tokens=100, output_tokens=4),
            answers={
                key: SimpleNamespace(noul=self.ANSWERS.get(key, 0.9))
                for key in questions
            },
        )


class _BreakerSpy:
    """熔断器替身：只暴露生产代码用到的三个面，并把调用逐条留痕。"""

    def __init__(self, *, allow_result: bool = True) -> None:
        self.allow_result = allow_result
        self.allow_calls = 0
        self.records: list[bool] = []

    def allow(self) -> bool:
        self.allow_calls += 1
        return self.allow_result

    def record(self, ok: bool) -> None:
        self.records.append(bool(ok))

    @property
    def state(self) -> str:
        return "closed" if self.allow_result else "open"


class _StubBudget:
    """`TimeoutBudget` 替身：前 `exhausted_after` 次 `exhausted()` 说"还有预算"，之后恒说没了。

    存在的理由只有一个：提交循环里的那道预算闸在真钟 + 线程下不可复现（要么预筛先挡住、
    要么收集循环先挡住），用它把"第 2 次询问恰好落在首次提交前"这个时序钉成确定值。
    """

    def __init__(self, *, exhausted_after: int, remaining_ms: float = 1500.0,
                 soft: bool = False) -> None:
        self._exhausted_after = exhausted_after
        self._remaining_ms = remaining_ms
        self._soft = soft
        self.asked = 0

    def exhausted(self) -> bool:
        self.asked += 1
        return self.asked > self._exhausted_after

    def remaining_ms(self) -> float:
        return self._remaining_ms

    def over_soft(self) -> bool:
        return self._soft


if __name__ == "__main__":
    unittest.main()

