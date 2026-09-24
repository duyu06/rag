# TypeSafe V2 生产优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本仓库不是 git 仓库**：无提交流程；每个任务收尾 = 定向测试绿 + 全套件失败集合不新增（当前基线 0 failed，共 218 测试）。禁止破坏性回滚操作。

**Goal:** 按 `docs/TYPESAFE_V2_PRODUCTION_DESIGN.md` 把 TypeSafe 从默认 Reranker 降为高价值 Judge：本地精排前置、五档模式、置信度路由、动态 TopK、语义去重、判定缓存、软/硬超时预算与通用熔断器、指标白名单扩展与中文观测面。

**Architecture:** 新增通用 `app/resilience.py`（CircuitBreaker/TimeoutBudget，Model Router V2 复用）与 `app/typesafe_router.py`（纯规则路由决策）；判定缓存内聚在 `app/typesafe_judgments.py`；`app/retrieval.py` 判定段按 spec §2 重排；观测经 `security.py` 白名单 → timings → `/api/system/status` → 前端 SystemView/TraceView。

**Tech Stack:** FastAPI + pydantic v2 settings、Qdrant client、SentenceTransformer CrossEncoder、typesafe-sdk（无批量接口）、unittest 风格契约测试（现有 `tests/test_typesafe_*.py` 是主要回归守门）。

**Spec:** `E:\xiangmu\rag\docs\TYPESAFE_V2_PRODUCTION_DESIGN.md`（执行时两份都读）

## Global Constraints

- `rerank_provider="local"` 或 `typesafe_enabled=false` 时行为与改造前**逐字一致**（现有 218 测试为底线，尤其 `test_typesafe_retrieval.py`/`test_typesafe_api_runtime.py`/`test_typesafe_security_contract.py`）。
- `shadow` 模式：判定执行但结果**永不应用**到行序；`off`：零外呼；`strict`：恒调用恒应用（=V1 active 语义）。旧 `.env` 值 `shadow`/`active` 必须原样可用。
- RBAC 过滤先于判定；未授权候选计数语义不变（`typesafe_unauthorized_candidates_blocked`）。
- 密钥/判定响应不落日志不入响应；白名单仍为**显式键枚举**，禁止 `typesafe_*` 前缀透传（security.py 注释既有铁律）。
- 不新增第三方依赖。前端文案遵循 `docs/UI_COPY_GLOSSARY.md`（中文，保留 P50/P95/Token/HIT@1 等缩写）。
- 测试命令均在 `E:\xiangmu\rag\backend`：`python -m pytest tests/test_typesafe_v2_router.py -v` 等；全套件 `python -m pytest tests -q`。
- margin/floor 默认值（0.25/0.10/0.20）在 Task 8 strict 对照后允许调整，最终值写回本文件"标定结果"节。

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| ★ `app/resilience.py` | 新建 | 通用 CircuitBreaker + TimeoutBudget（无业务耦合） |
| ★ `app/typesafe_router.py` | 新建 | `should_judge` / `pick_candidate_count` 纯规则 |
| ★ `tests/test_typesafe_v2_core.py` | 新建 | resilience + router + cache + dedup 契约测试 |
| ✎ `app/config.py` | 修改 | spec §8 全部新键 + mode 五档 Literal |
| ✎ `app/typesafe_judgments.py` | 修改 | JudgmentCache、预算/熔断接入、滚动聚合 stats |
| ✎ `app/store.py` | 修改 | `fetch_vectors(point_ids)` |
| ✎ `app/retrieval.py` | 修改 | 判定段重排（CE 前置→去重→动态 TopK→路由→判定） |
| ✎ `app/security.py` | 修改 | 白名单新键 |
| ✎ `app/knowledge_os.py` | 修改 | `/system/status` 增"判定层"块 |
| ✎ `scripts/complex_accuracy.py` | 修改 | mode 参数扩展 + calls/query、token、检索段耗时聚合 |
| ✎ `frontend/src/views/SystemView.tsx`、`TraceView.tsx` | 修改 | 中文观测卡片区 |
| ★ `docs/TYPESAFE_V2_ACCEPTANCE_模板.md` | Task 8 生成实际报告 | 真实复跑门禁 |

---

### Task 1: 通用 resilience 模块（CircuitBreaker + TimeoutBudget）

**Files:** Create `app/resilience.py`, `tests/test_typesafe_v2_core.py`（首节）

**Interfaces:**
- Produces: `CircuitBreaker(*, name, window=20, failure_ratio=0.30, open_seconds=60.0, half_open_probes=3, clock=time.monotonic)`，方法 `allow() -> bool`、`record(ok: bool) -> None`、属性 `state -> "closed"|"open"|"half_open"`；`TimeoutBudget(*, soft_ms, hard_ms, clock=time.perf_counter)`，方法 `elapsed_ms() -> float`、`remaining_ms() -> float`、`over_soft() -> bool`、`exhausted() -> bool`。线程安全（Lock）。

- [ ] **Step 1: 写失败测试**（`tests/test_typesafe_v2_core.py`）

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

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
        for _ in range(4):
            br.record(False)
        for _ in range(10):
            br.record(True)
        for _ in range(2):
            br.record(False)
        self.assertEqual(br.state, "closed")  # 最近 10 次里失败 2/10 < 0.3


class TimeoutBudgetTests(unittest.TestCase):
    def test_soft_then_hard(self):
        clock = _FakeClock()
        budget = TimeoutBudget(soft_ms=1200, hard_ms=1800,
                               clock=lambda: clock.now * 1000)
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑红** `python -m pytest tests/test_typesafe_v2_core.py -v`（ModuleNotFoundError）。
- [ ] **Step 3: 实现 `app/resilience.py`**

```python
from __future__ import annotations

import time
from collections import deque
from threading import Lock


class CircuitBreaker:
    """Generic rolling-window breaker. One instance per dependency
    (typesafe today; each LLM provider in Model Router V2)."""

    def __init__(self, *, name: str, window: int = 20, failure_ratio: float = 0.30,
                 open_seconds: float = 60.0, half_open_probes: int = 3,
                 clock=time.monotonic) -> None:
        self.name = name
        self._window = window
        self._ratio = failure_ratio
        self._open_seconds = open_seconds
        self._probes = half_open_probes
        self._clock = clock
        self._results: deque[bool] = deque(maxlen=window)
        self._state = "closed"
        self._opened_at = 0.0
        self._half_success = 0
        self._lock = Lock()

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_leave_open()
            return self._state

    def allow(self) -> bool:
        with self._lock:
            self._maybe_leave_open()
            return self._state != "open"

    def record(self, ok: bool) -> None:
        with self._lock:
            if self._state == "half_open":
                if ok:
                    self._half_success += 1
                    if self._half_success >= self._probes:
                        self._reset_closed()
                    return
                self._trip()
                return
            self._results.append(ok)
            if self._state == "closed" and len(self._results) >= max(4, self._window // 2):
                failures = sum(1 for item in self._results if not item)
                if failures / len(self._results) > self._ratio:
                    self._trip()

    def _maybe_leave_open(self) -> None:
        if self._state == "open" and self._clock() - self._opened_at >= self._open_seconds:
            self._state = "half_open"
            self._half_success = 0

    def _trip(self) -> None:
        self._state = "open"
        self._opened_at = self._clock()
        self._results.clear()

    def _reset_closed(self) -> None:
        self._state = "closed"
        self._results.clear()
        self._half_success = 0


class TimeoutBudget:
    def __init__(self, *, soft_ms: float, hard_ms: float, clock=time.perf_counter) -> None:
        if hard_ms <= 0 or soft_ms <= 0 or soft_ms > hard_ms:
            raise ValueError("需要 0 < soft_ms <= hard_ms")
        self._started = clock()
        self._soft = soft_ms
        self._hard = hard_ms
        self._clock = clock

    def elapsed_ms(self) -> float:
        return (self._clock() - self._started) * 1000.0

    def remaining_ms(self) -> float:
        return self._hard - self.elapsed_ms()

    def over_soft(self) -> bool:
        return self.elapsed_ms() > self._soft

    def exhausted(self) -> bool:
        return self.remaining_ms() <= 0.0
```

- [ ] **Step 4: 跑绿** `python -m pytest tests/test_typesafe_v2_core.py -v`；全套件不新增失败。

---

### Task 2: 配置键 + 五档模式（含兼容）

**Files:** Modify `app/config.py`、`backend/.env.example`；Test `tests/test_typesafe_v2_core.py` 追加 `SettingsModeTests`

**Interfaces:**
- Produces（Settings 新字段，全部 `Field` 边界校验）：`typesafe_mode: Literal["off","shadow","selective","active","strict"] = "shadow"`、`typesafe_soft_timeout_ms:int=1200(500..30000)`、`typesafe_hard_timeout_ms:int=1800(1000..60000)`、`typesafe_min_candidates=3`、`typesafe_max_candidates=6`、`typesafe_compound_candidates=8`、`typesafe_low_confidence_candidates=12`、`typesafe_high_margin=0.25`、`typesafe_medium_margin=0.10`、`typesafe_confidence_floor=0.20`、`typesafe_dedup_cosine=0.97`、`typesafe_cache_enabled:bool=True`、`typesafe_cache_ttl_seconds=86400`、`typesafe_cache_max_entries=2048`、`typesafe_breaker_enabled:bool=True`、`typesafe_breaker_window=20`、`typesafe_breaker_failure_ratio=0.30`、`typesafe_breaker_open_seconds=60`、`typesafe_breaker_half_open_probes=3`；`typesafe_max_concurrency` 默认 4→6。
- Consumes: 现有键不动（`typesafe_enabled/timeout_seconds/candidates/compound_candidates` 保留：`candidates/compound_candidates` 继续作为 `active/shadow` 判定前的池尺寸默认，被动态 TopK 覆盖时以 Task 4 计算为准；`timeout_seconds` 成为单请求 client 上限）。

- [ ] **Step 1: 写失败测试**（模式合法性 + `enabled=false ⇒ off` 判定辅助函数）

```python
class SettingsModeTests(unittest.TestCase):
    def test_effective_mode_off_when_disabled(self):
        from app.config import Settings
        s = Settings(_env_file=None, typesafe_enabled=False, typesafe_mode="strict")
        self.assertEqual(s.effective_typesafe_mode, "off")

    def test_effective_mode_passthrough_when_enabled(self):
        from app.config import Settings
        s = Settings(_env_file=None, typesafe_enabled=True, typesafe_mode="selective")
        self.assertEqual(s.effective_typesafe_mode, "selective")

    def test_legacy_mode_values_still_valid(self):
        from app.config import Settings
        for legacy in ("shadow", "active"):
            self.assertEqual(
                Settings(_env_file=None, typesafe_mode=legacy).typesafe_mode, legacy)

    def test_invalid_mode_rejected(self):
        from app.config import Settings
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, typesafe_mode="yolo")
```

- [ ] **Step 2: 跑红**（`effective_typesafe_mode` 不存在 / Literal 拒绝新值）。
- [ ] **Step 3: 实现**：`typesafe_mode` 扩为五档 Literal；Settings 加方法：

```python
    @property
    def effective_typesafe_mode(self) -> str:
        if not self.typesafe_enabled:
            return "off"
        return self.typesafe_mode
```

其余 §8 键按 Interfaces 逐个加（Field 约束照 Feishu 块风格，注释中文一行）。`.env.example` TypeSafe 段追加新键示例（默认值注释，含 `TYPESAFE_MODE=selective` 生产建议与五档注释）。
- [ ] **Step 4: 跑绿 + 全套件**（`Settings()` 无参构造仍工作 = 默认值安全）。

---

### Task 3: 判定缓存 + store.fetch_vectors + 语义去重（纯函数与件）

**Files:** Modify `app/typesafe_judgments.py`（新增 `JudgmentCache` 与模块级 `judgment_cache`）、`app/store.py`；Test `tests/test_typesafe_v2_core.py` 追加

**Interfaces:**
- Produces: `cache_key(query: str, row: dict, model: str) -> str`（normalize：小写+折叠空白）；`JudgmentCache.get(key) -> PassageJudgment | None`、`put(key, judgment)`（LRU `typesafe_cache_max_entries` + TTL `typesafe_cache_ttl_seconds`，Lock，可注入 clock）；模块级 `judgment_cache = JudgmentCache()`；`VectorStore.fetch_vectors(point_ids: list[str]) -> dict[str, list[float]]`（`client.retrieve(with_vectors=True, with_payload=False)`）；`dedupe_by_similarity(rows, vectors, threshold) -> list[dict]`（纯函数，cosine≥threshold 合并保留入参序首位=高分块，无向量的行原样保留）。
- `PassageJudgment` 增加 `from_cache: bool = False` 字段（不进任何响应字段——行级 row_fields 白名单不变）。

- [ ] **Step 1: 写失败测试**

```python
class JudgmentCacheTests(unittest.TestCase):
    def make_judgment(self, evidence=0.9):
        from app.typesafe_judgments import PassageJudgment
        return PassageJudgment(point_id="p1", route="include", is_relevant=0.9,
                               contains_answer_evidence=evidence,
                               contradicts_query_premise=0.0,
                               contains_prompt_injection=0.0,
                               model="jev-test", latency_ms=100.0,
                               input_tokens=10, output_tokens=2)

    def test_key_stable_and_content_sensitive(self):
        from app.typesafe_judgments import cache_key
        row = {"id": "p1", "content": "保修两年"}
        self.assertEqual(cache_key("保修期", row, "m"), cache_key("  保修期 ", row, "m"))
        self.assertNotEqual(cache_key("保修期", row, "m"),
                            cache_key("保修期", {**row, "content": "保修三年"}, "m"))

    def test_hit_after_put_and_ttl_expiry(self):
        from app.typesafe_judgments import JudgmentCache
        clock = _FakeClock()
        cache = JudgmentCache(max_entries=2, ttl_seconds=100, clock=clock)
        key = "k1"
        cache.put(key, self.make_judgment())
        self.assertIsNotNone(cache.get(key))
        clock.advance(101)
        self.assertIsNone(cache.get(key))

    def test_lru_eviction(self):
        from app.typesafe_judgments import JudgmentCache
        cache = JudgmentCache(max_entries=2, ttl_seconds=100, clock=_FakeClock())
        cache.put("a", self.make_judgment()); cache.put("b", self.make_judgment())
        cache.get("a")                        # a 变最近使用
        cache.put("c", self.make_judgment())
        self.assertIsNotNone(cache.get("a")); self.assertIsNone(cache.get("b"))


class DedupeTests(unittest.TestCase):
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
```

- [ ] **Step 2: 跑红**。
- [ ] **Step 3: 实现**：`cache_key`（`sha256(f"{normalize(query)}|{row.get('id','')}|{sha256(normalize(content))}|{model}|{PROMPT_VERSION}")`，`PROMPT_VERSION="v1"` 模块常量）；`JudgmentCache` 用 `OrderedDict`（move_to_end + popitem(last=False)）+ `(judgment, expires_at)`；`dedupe_by_similarity`：对每个保留块与后续块算 cosine（纯 Python，≤12 块 O(n²) 可接受），≥threshold 丢弃后续。`store.fetch_vectors`：分片一次调用 `self.client.retrieve(collection_name=..., points=point_ids, with_payload=False, with_vectors=True)`，异常返回 `{}`（去重降级为不丢块，不炸主链路）。
- [ ] **Step 4: 跑绿 + 全套件**。

---

### Task 4: typesafe_router（should_judge + 动态 TopK）

**Files:** Create `app/typesafe_router.py`；Test `tests/test_typesafe_v2_core.py` 追加 `RouterTests`

**Interfaces:**
- Consumes: `app.typesafe_judgments.is_compound_query`；`settings`（margins）。
- Produces: `pick_candidate_count(query: str, rows: list[dict]) -> int`；`should_judge(query: str, rows: list[dict]) -> tuple[bool, list[str]]`（rows 已含 `rerank_score`，按降序）；`RISK_MARKERS: tuple[str, ...]`；`_QUERY_FACT_SIGNAL`（数字/时间/参数正则）。

规则（spec §3/§4 逐条）：
- 触发信号任一为真：compound；margin<medium；top1<floor；跨文档分散（top1 文档与 top2-4 全不同且 top1<0.6）；RISK_MARKERS 命中；`active` 跳过条件 = margin>high 且无风险信号且非 compound。
- TopK：compound→`typesafe_compound_candidates`；top1<floor→`typesafe_low_confidence_candidates`；margin>high→`typesafe_min_candidates`；margin>medium→4；否则 `typesafe_max_candidates`。

- [ ] **Step 1: 写失败测试**（信号矩阵 ≥8 例：高置信单一→selective 假/active 假；低 margin→真；floor 下→真且 topk=12；compound→真且 8；风险词→真；跨文档分散→真；`pick_candidate_count` 边界五例）

```python
class RouterTests(unittest.TestCase):
    def rows(self, top1, second_gap, docs=("a.md", "b.md", "c.md", "d.md")):
        base = top1
        out = []
        for i, doc in enumerate(docs):
            out.append({"id": str(i), "file_name": doc,
                        "rerank_score": max(0.0, base - i * second_gap)})
        return out

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
```

（若 `is_compound_query` 对样例不判复合，允许在测试内 monkeypatch，不改其判定器。）
- [ ] **Step 2: 跑红**。- [ ] **Step 3: 实现 `app/typesafe_router.py`**（纯函数、中文注释、`margin = rows[0]-rows[1]`；rows<2 时视为触发）。
- [ ] **Step 4: 跑绿 + 全套件**。

---

### Task 5: judge_candidates 接入（预算/熔断/缓存/mode 门）

**Files:** Modify `app/typesafe_judgments.py`；Test 追加 `JudgeWiringTests`（现有 `test_typesafe_judgments.py` 不动、必须仍绿）

**Interfaces:**
- Consumes: Task 1 breaker/budget、Task 3 cache、Task 2 settings。
- Produces: `TypeSafeJudgmentService.judge_candidates(query, rows, *, knowledge_base_ids, budget: TimeoutBudget | None = None) -> JudgmentBatch`；metrics 新键：`typesafe_cache_hit:int`、`typesafe_circuit_open:bool`、`typesafe_slow:bool`、`typesafe_skipped:str|None`("circuit_open"|"off"|"budget_exhausted")；模块级 `typesafe_breaker = CircuitBreaker(name="typesafe", ...按 settings)`；`typesafe_stats() -> dict`（滚动聚合，见下）与 `reset_typesafe_stats()`。
- 聚合（模块级 Lock+deque 滚动最近 200 请求）：`trigger_rate`、`skip_rate`、`cache_hit_ratio`、`requests_per_query_p50/p95`、`input_tokens_per_query_p50`、`timeout_rate`、`degraded_rate`、`breaker_state`、`latency_p50/p95`（判定内已算）。

行为：mode=off → 直接返回空批次 + `typesafe_skipped="off"`（不请求）；breaker `allow()` False → `typesafe_circuit_open=True, typesafe_skipped="circuit_open"`，**degraded 保持 False**；缓存命中不占 requests_attempted、不打断/记录 breaker；per-request timeout = `min(settings.typesafe_timeout_seconds*1000, budget.remaining_ms())/1000`；`budget.exhausted()` → 未开始的任务取消、批次 degraded=True + errors 追加 "budget_exhausted"；结束后 `breaker.record(ok=not degraded)`；`budget.over_soft()` → `typesafe_slow=True`。

- [ ] **Step 1: 写失败测试**（client_factory 注入假客户端计数请求：circuit open→零请求+not degraded+skip 标记；cache put 后二次同 query+row→request_count 0、cache_hits 1、judgments 仍完整；budget 预耗尽→degraded+budget_exhausted；stats 聚合数字断言 + `reset_typesafe_stats()` 隔离）。
- [ ] **Step 2: 跑红**。- [ ] **Step 3: 实现**（改动集中在 `judge_candidates`：缓存预筛 rows→eligible；judgment 成功后 `judgment_cache.put`；breaker 单例可被测试 `reset`；stats 在 finally 记录本请求计数）。
- [ ] **Step 4: 跑绿**：`tests/test_typesafe_judgments.py` 全量原测必须仍绿（签名向后兼容：budget 带默认）。全套件 0 新增失败。

---

### Task 6: retrieval.py 管道重排（核心整合）

**Files:** Modify `app/retrieval.py`（判定段 ~433-520 行区域）；Test 扩展 `tests/test_typesafe_retrieval.py`

**Interfaces:**
- Consumes: Task 4 router、Task 5 新签名、`store.fetch_vectors`、`settings.effective_typesafe_mode`。
- Produces: timings 新键（进 Task 7 白名单）：`typesafe_trigger`、`typesafe_skip`、`typesafe_cache_hit`、`typesafe_circuit_open`、`typesafe_slow`、`dedup_ms`、`rerank_stage_ms`（本地 CE 段）、`judge_input_count`（去重+TopK 后进判定的候选数）。

新流程（`rerank and rows and provider=typesafe and mode!=off`）：
1. **本地 CE 前置**：对 `rows[:retrieval_rerank_candidates]`（≥low_confidence 池 12 时取 max(…, typesafe_low_confidence_candidates)）跑 CE 打分排序（复用现 local 分支代码路径 → 抽 `_apply_cross_encoder(query, rows) -> (rows, ms)`）。
2. 向量批量取回（≤池大小一次 `fetch_vectors`）→ `dedupe_by_similarity`，记 `dedup_ms`。
3. `count = pick_candidate_count(query, rows)`；`judge_rows = rows[:count]`。
4. `need, reasons = should_judge(...)`：`selective` 且 not need → skip（本地 CE 序=最终候选序，走 diversity）；`active` 且满足跳过组合 → skip；`shadow/strict` → 恒 judge；budget(soft/hard) 构造传入。
5. judge 后：`not degraded and mode in {"active","strict","shadow-apply?"}` —— 仅 active/strict 应用 include/exclude/冲突排序（V1 代码逐段保留），shadow 维持 CE 本地序但产出观测 metrics。
6. 其后 diversify 与返回不变。`mode=off`/provider=local 走原路（不变式）。

- [ ] **Step 1: 写失败测试**（假 reranker + 假 judgment service 注入，断言：selective 高置信 → typesafe 服务零调用、`typesafe_skip` 出现、行序=CE 序；strict → 调用且应用；shadow → 调用不应用；dedup 合并非重复块；judge_input_count==动态 TopK 值；provider=local 全流程与现网逐字段一致——直接对拍现有 `test_typesafe_retrieval.py` 的 local 用例不变）。
- [ ] **Step 2: 跑红**。- [ ] **Step 3: 实现**（本任务禁止顺手重构无关段）。
- [ ] **Step 4: 跑绿 + 全套件 0 新增失败**（重点 `test_typesafe_retrieval.py`、`test_typesafe_api_runtime.py`、`test_retrieval_performance_contract.py`、`test_complex_accuracy_contract.py`）。

---

### Task 7: 观测面（白名单 + system/status + trace + 前端中文卡片）

**Files:** Modify `app/security.py`、`app/knowledge_os.py`（`/system/status`）、`app/agent_trace.py`（重排阶段事件）、`frontend/src/views/SystemView.tsx`、`TraceView.tsx`；Test：扩展 `test_typesafe_security_contract.py`、`test_ui_consistency_contract.py` 相关例

**Interfaces:**
- Consumes: Task 5 `typesafe_stats()`、Task 6 timings 新键。
- Produces: `PUBLIC_TYPESAFE_METRIC_KEYS` 追加（逐条枚举）：`typesafe_trigger typesafe_skip typesafe_cache_hit typesafe_circuit_open typesafe_slow typesafe_skipped judge_input_count`；`/system/status` 响应新增 `typesafe: {mode, breaker_state, trigger_rate, skip_rate, cache_hit_ratio, requests_per_query_p95, input_tokens_per_query_p50, timeout_rate, degraded_rate, latency_p50_ms, latency_p95_ms}`（全部数值/redact 处理）；前端 SystemView "判定层"区（Kicker `判定层观测`；卡片：触发率/跳过率/缓存命中/熔断状态，值百分比或 是/否，样式沿用 metrics 行；`typesafe_enabled=false` 时整块隐藏或显示 `未启用`）；TraceView 重排行 detail 追加 `触发/缓存/熔断` 中文子标签。
- 前端断言（中文文案按 glossary）：`system-status` 无 typesafe 块时前端不崩（可选字段）。

- [ ] **Step 1: 契约测试先行**：白名单外键（如 `typesafe_api_key`、`typesafe_mode_unknown`）不透传（沿用该文件既有模式）；status 块字段集合断言（admin via TestClient；viewer 403 语义不变）。
- [ ] **Step 2: 跑红** → **Step 3: 实现后端三件** → **Step 4: 前端两文件按 glossary 加卡片区**。
- [ ] **Step 5: `npm run build` PASS** + 定向后端测试绿 + 全套件 0 新增。

---

### Task 8: 验收脚本扩展 + 真实复跑 + 报告

**Files:** Modify `scripts/complex_accuracy.py`；Create `docs/TYPESAFE_V2_ACCEPTANCE_2026-09-23.md`（运行后填写实测数字）；Test：`test_complex_accuracy_contract.py` 更新 CLI 参数断言

**Interfaces:**
- Produces: CLI 新增 `--expect-typesafe-mode {off,shadow,selective,active,strict}`（多值语义=等于或按门禁）、`--max-avg-typesafe-requests-per-query FLOAT`、`--report-typesafe-rollup`（打印 `typesafe_stats()` 白名单聚合）；LLM-only 分支不变。
- 运行门禁（spec §9，真实 API 已获用户批准，两轮）：
  1. `strict` 复现 V1：59 题 Hit@1/3、MRR 100%±1%、Compound 5/5、RBAC 7/7、Citation+无答案 6/6、degraded=0、unauthorized=0；
  2. `selective` 生产：calls/query P50≤4/P95≤8、input tokens 对比 strict 轮 ↓≥30%、Hit@1≥98%、Hit@3=100%、判定段 P50≤700/P95≤1800ms；
  3. 故障注入：坏地址→200+degraded；连续失败→breaker open→零外呼仍 200；
  4. 全链路 SSE TTFT 采样 ≥5 次，对 6532ms 基线降幅 ≥30%（Ollama 状态如实记录，不达标不阻塞——按 TTFT 两段口径）；
  5. margin/floor 若需标定，在此任务记录终值到 spec"标定结果"节。
- 报告文件含：环境、命令、逐项门禁 PASS/FAIL、聚合数字、密钥扫描 0 命中、`python -m pytest tests -q` 与 `npm run build` 终态。

- [ ] **Step 1: 改脚本 + 契约测试（--help 断言新参数）** → [ ] **Step 2: 离线小样验证脚本逻辑**（`--limit 5 --no-llm` 若脚本支持，否则读码选择 dry 路径） → [ ] **Step 3: strict 全量真实跑** → [ ] **Step 4: selective 全量真实跑** → [ ] **Step 5: 故障注入两项** → [ ] **Step 6: SSE 采样** → [ ] **Step 7: 写验收报告文档**（中文，表格对齐 V1 报告格式）。

---

## 标定结果（Task 8 回填）

执行时点：2026-09-23 段D 收尾。全部门禁实测结论与证据见 `docs/TYPESAFE_V2_ACCEPTANCE_2026-09-23.md`；过程记录见 `.superpowers/sdd/TYPESAFE_V2_PRODUCTION_PLAN/task-8-report.md`（段A/B/B2/C/D）。

- **margin/floor 终值：`TYPESAFE_HIGH_MARGIN=0.25` / `TYPESAFE_MEDIUM_MARGIN=0.10` / `TYPESAFE_CONFIDENCE_FLOOR=0.20` —— 三个默认值全部保持，未调整。**
  - 理由：① 它们服务的门禁（selective 成本 ↓≥30%、calls/query P50≤4·P95≤8、accuracy 不退化）**已全部实测 PASS**，无调参动机；② 唯一未过的门禁是 §9.2 判定段延迟线，属**结构性问题而非阈值可解**——selective 免判 39 题落在 `{3:36, 4:3}`、判题 20 题落在 `{3:11, 6:7, 8:2}`，即 **6/8 多请求档 100% 被保留**，调 margin/floor 只改变"判几题"，不改变"被保留题有多慢"（strict 轮按档批次墙钟中位 3 档 938.7ms 已 > 700ms 线）。
  - 同批次一并定值：**`TYPESAFE_HARD_TIMEOUT_MS` 1800 → 3000（已入码**：`app/config.py` 类默认值 + `backend/.env.example`，段D 容器镜像复核生效）；`SOFT=1200` 不变。
  - reasons 分布证据（段B2 strict 轮 `typesafe_reasons`，覆盖 59/59 批次）：无信号 39 · `risk` 7 · `margin` 5 · `param` 3 · `margin/risk` 1 · `risk/param` 1 · `margin/param` 1 · `compound` 1 · `compound/param` 1；token 合计 `risk 9 · margin 7 · param 6 · compound 2 · floor 0 · dispersed 0`。交叉验证：**"无信号批次 = 39" 与段B selective 轮实测 `router_skipped_cases=39` 逐数相同**（同数据集）⇒ 免判集完全由该读数决定，段B 的"免判题 × 落档"代理可退役。`floor`/`dispersed` 与 12 档动态 TopK 在本数据集不可观测（0 命中），需扩低置信/跨文档分散题集后再标定。
- **strict vs selective 的 calls/query、tokens、P50/P95（同 59 题 + 5 compound 范围，均为真实外呼权威轮）**

  | 指标 | V1 active（基线） | V2 strict 复跑（段B2 权威轮） | V2 selective（段B 正式轮） | 门禁 |
  |---|---:|---:|---:|---|
  | requests | 426（366+60） | 251（211+40） | 131（91+40） | strict ≥150 **PASS**；selective ↓47.81% |
  | calls/query avg / P50 / P95（64 批次） | 6.203（rerank 均值）· — · 12 | 3.922 · 3 · **8** | 2.047 · **0**（仅判题 3）· **8**（恰线无余量） | P50≤4 / P95≤8 **PASS**（两口径） |
  | input tokens | 376,618 | 213,012 | **120,182** | ↓44.88%（vs 段B 同窗 strict 218,054）· ↓43.58%（vs 权威 strict）· ↓68.09%（vs V1）**PASS（≥30%）** |
  | output tokens / 估算 USD | 39,738 / $0.015818 | 22,752 / $0.008946 | 13,487 / **$0.005048** | 同上，↓43.44% vs V1 |
  | 单请求 P50 / P95（脚本 stage） | 882.94 / 2108.45ms | 634.5 / 2250.73ms | 794.96 / 2573.43ms | — |
  | 逐题批次墙钟 P50 / P95 / max | V1 未采集 | 996.96 / 3656.86 / 4707.86ms（非退化 51 批 938.74 / 1803.05 / **2073.51**） | **1102.02 / 2234.32 / 2577.2ms**（仅 20 真外呼题） | 700/1800 **两线 FAIL**（结构性；提案 P50≤1200 / P95≤2500 **待用户批准**） |
  | 判定段合计墙钟 | 91,666.7ms | 92,463.24ms | **32,950.54ms**（↓64.4% vs strict） | — |
  | degraded | 0 | 8/64 批次（12.5%）→ **CONDITIONAL PASS（上游瞬态）** | **0** → PASS | — |
  | Hit@1 / Hit@3 / MRR · Compound · RBAC · 越权 | 100% · 5/5 · 7/7 · 0 | 100%/100%/1.000 · 5/5 · 7/7 · 0 | 100%/100%/1.000 · 5/5 · 7/7 · 0 | **全 PASS** |
  | trigger / router_skip / cache_hit | 不可观测 | 64 / 0 / 0 | 25 / 39 / 0 | — |
  | `judge_input_count` 落档 | 固定池 6/12 | `{3:47,4:3,6:7,8:2}` + compound `{8:5}`（12 档 0 命中=不可观测） | 与 strict 逐题同档 | 动态 TopK 与模式无关，符合设计 |

- 计划内 8 个 Step 的终态：Step 1-7 全部完成（脚本扩展 + strict/selective 真实轮 + 故障注入两项 + SSE 采样 + 本报告）；Task 8 门禁 #19（LLM 边界 6/6）实测 **5/6**（唯一失败例=无答案题以英文作答 ⇒ 新发现缺陷 P2「拒答语言未锁定中文」，直接诱因为本机 9B 无法加载而换 `phi3:mini`）、门禁 #23（全链路 SSE TTFT ↓≥30%）实测 FAIL（TTFT 中位 38524.78ms，两段口径归因生成端：检索段中位 2375.92ms / 判定段中位 873.96ms）。回归终态 `403 passed`、`npm run build` PASS、密钥扫描 0 命中、容器形态已恢复（`rag-backend` Up、`/api/health` 200、`/api/system/status` 显示 `typesafe.mode`）。真实外呼累计 ≈$0.0351，超批准额度 ≈8-9%（全部来自 9B 显存不足导致的作废轮），段D 起零外呼。
