from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app.config import settings
from app.retrieval_text import build_retrieval_text
from app.store import vector_store
from app.typesafe_judgments import (
    dedupe_by_similarity,
    make_budget_from_settings,
    typesafe_judgment_service,
)
from app.typesafe_router import (
    is_high_confidence_single_fact,
    pick_candidate_count,
    should_judge,
)
from app.web_search import clean_question

SearchMode = Literal["vector", "bm25", "hybrid"]

# `typesafe_skipped` 的取值表：`off` / `circuit_open` / `budget_exhausted` 由判定层给出
# （Task 5），`router` 由检索层给出——selective/active 的"置信度路由免判"分支根本不会调用
# 判定服务（这正是 V2 的成本目标），因此没有批次 metrics 可并入，这几枚观测键只能自造
# （Task 5 交接第 3 条：由 Task 6 派生，不在判定模块加第 20 枚键）。
TYPESAFE_SKIPPED_BY_ROUTER = "router"

# 应用 include/exclude/冲突排序的档位集合 = 设计 §3 模式表的"应用路由"列（是=此三档）。
# off 从不调用、shadow 只观测，故都不在此列。
TYPESAFE_APPLY_MODES = frozenset({"selective", "active", "strict"})

BM25_QUERY_EXPANSIONS = {
    "酒店": ("住宿",),
}


def tokenize(text: str) -> list[str]:
    value = text.lower()
    latin = re.findall(r"[a-z0-9_.-]+", value)
    # Treat a signed measurement in a document (for example ``-20℃``) as an
    # exact match for the equivalent natural-language query token (``零下20度``).
    numeric_aliases = [
        token[1:]
        for token in latin
        if re.fullmatch(r"-\d+(?:\.\d+)?", token)
    ]
    chinese = re.findall(r"[\u4e00-\u9fff]", value)
    bigrams = ["".join(chinese[i : i + 2]) for i in range(max(0, len(chinese) - 1))]
    return latin + numeric_aliases + chinese + bigrams


def build_bm25_query_tokens(query: str) -> list[str]:
    """Add small, domain-neutral lexical aliases without changing the query text."""
    tokens = tokenize(query)
    for source, expansions in BM25_QUERY_EXPANSIONS.items():
        if source in query:
            for expansion in expansions:
                tokens.extend(tokenize(expansion))
    return tokens


def normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def rank_bm25_match_ids(
    rows: list[dict[str, Any]],
    corpus: list[list[str]],
    raw_scores: list[float],
    query: str,
) -> list[str]:
    """Rank only rows with lexical overlap, even when BM25 scores are non-positive."""
    query_tokens = set(build_bm25_query_tokens(query))
    if not query_tokens:
        return []
    matches = [
        (row["id"], raw_score)
        for row, tokens, raw_score in zip(rows, corpus, raw_scores)
        if query_tokens.intersection(tokens)
    ]
    matches.sort(key=lambda item: item[1], reverse=True)
    return [point_id for point_id, _ in matches]


def reciprocal_rank_fusion(
    vector_ids: list[str],
    bm25_ids: list[str],
    *,
    k: int,
) -> dict[str, float]:
    """Fuse independent rankings without assuming their raw scores are comparable."""
    scores: dict[str, float] = {}
    for ranking in (vector_ids, bm25_ids):
        for rank, point_id in enumerate(ranking, start=1):
            scores[point_id] = scores.get(point_id, 0.0) + 1.0 / (k + rank)
    return scores


def build_dense_query(query: str, *, use_instruction: bool) -> str:
    """Apply the BGE retrieval instruction only where it measured better.

    Pure dense retrieval benefits from the short-query instruction on the real-BGE
    evaluation set. Hybrid + RRF measured better with the raw query, so the hybrid
    vector branch intentionally remains unprefixed.
    """
    instruction = settings.retrieval_vector_query_instruction.strip()
    if use_instruction and instruction:
        return f"{instruction}{query}"
    return query


def diversify_by_document(
    rows: list[dict[str, Any]],
    *,
    top_k: int,
    max_per_document: int,
) -> list[dict[str, Any]]:
    """Prefer broad document coverage before taking extra chunks from one file.

    Heading-aware indexing creates several useful chunks per file. The first pass takes
    only the best-ranked chunk from each document; later passes may take a second (or
    further configured) chunk. If there are not enough distinct documents/chunks, the
    remaining rows are filled in original rank order so single-document workspaces still
    return the requested number of evidence chunks.
    """
    if top_k <= 0:
        return []

    cap = max(1, int(max_per_document))
    selected: list[dict[str, Any]] = []
    selected_indexes: set[int] = set()
    counts: dict[tuple[str, str], int] = {}

    def document_key(row: dict[str, Any], index: int) -> tuple[str, str]:
        file_name = str(row.get("file_name") or "").strip()
        kb_id = str(row.get("knowledge_base_id") or "").strip()
        if file_name:
            return kb_id, file_name
        return "__point__", str(row.get("id") or index)

    # Pass 1 maximizes source coverage; later passes admit additional chunks per file.
    for pass_number in range(1, cap + 1):
        for index, row in enumerate(rows):
            if index in selected_indexes:
                continue
            key = document_key(row, index)
            if counts.get(key, 0) >= pass_number:
                continue
            selected.append(row)
            selected_indexes.add(index)
            counts[key] = counts.get(key, 0) + 1
            if len(selected) >= top_k:
                return selected[:top_k]

    # Preserve result count even when the scope has fewer documents than top_k.
    for index, row in enumerate(rows):
        if index in selected_indexes:
            continue
        selected.append(row)
        if len(selected) >= top_k:
            break
    return selected[:top_k]


@dataclass(slots=True)
class _BM25CacheEntry:
    revision: int
    expires_at: float
    rows: list[dict[str, Any]]
    row_map: dict[str, dict[str, Any]]
    corpus: list[list[str]]
    index: BM25Okapi | None


class RetrievalService:
    def __init__(self) -> None:
        self._reranker: CrossEncoder | None = None
        self._reranker_lock = Lock()
        self._bm25_cache: dict[tuple[str, ...], _BM25CacheEntry] = {}
        self._bm25_cache_lock = Lock()

    @property
    def reranker(self) -> CrossEncoder:
        if self._reranker is None:
            with self._reranker_lock:
                if self._reranker is None:
                    self._reranker = CrossEncoder(settings.rerank_model)
        return self._reranker

    @staticmethod
    def _scope_key(knowledge_base_ids: list[str] | None) -> tuple[str, ...]:
        # `None`（无范围概念）才是全库键；`[]`（零可见）必须是独立键，
        # 否则无权限用户会和全库用户共用同一份 BM25 索引缓存。
        if knowledge_base_ids is None:
            return ("*",)
        return tuple(sorted(set(knowledge_base_ids)))

    def clear_bm25_cache(self) -> None:
        with self._bm25_cache_lock:
            self._bm25_cache.clear()

    def _get_bm25_entry(
        self,
        knowledge_base_ids: list[str] | None,
    ) -> tuple[_BM25CacheEntry, bool]:
        """Return a cached BM25 index for the current authorized KB scope."""
        key = self._scope_key(knowledge_base_ids)
        revision = vector_store.data_revision
        now = time.monotonic()
        ttl = max(0, int(settings.bm25_cache_ttl_seconds))

        if ttl > 0:
            with self._bm25_cache_lock:
                cached = self._bm25_cache.get(key)
                if (
                    cached is not None
                    and cached.revision == revision
                    and cached.expires_at > now
                ):
                    return cached, True

        rows = vector_store.all_chunks(knowledge_base_ids=knowledge_base_ids)
        row_map = {row["id"]: row for row in rows}
        corpus = [tokenize(build_retrieval_text(row)) for row in rows]
        index = BM25Okapi(corpus) if corpus else None
        entry = _BM25CacheEntry(
            revision=revision,
            expires_at=now + ttl,
            rows=rows,
            row_map=row_map,
            corpus=corpus,
            index=index,
        )

        if ttl > 0 and vector_store.data_revision == revision:
            with self._bm25_cache_lock:
                stale = [
                    cache_key
                    for cache_key, value in self._bm25_cache.items()
                    if value.revision != revision or value.expires_at <= now
                ]
                for cache_key in stale:
                    self._bm25_cache.pop(cache_key, None)
                self._bm25_cache[key] = entry

        return entry, False

    def _bm25_search(
        self,
        query: str,
        knowledge_base_ids: list[str] | None,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, float],
        list[str],
        bool,
    ]:
        entry, cache_hit = self._get_bm25_entry(knowledge_base_ids)
        if not entry.rows or entry.index is None:
            return entry.rows, entry.row_map, {}, [], cache_hit

        raw_bm25 = [
            float(value)
            for value in entry.index.get_scores(build_bm25_query_tokens(query))
        ]
        bm25_norm = {
            row["id"]: score
            for row, score in zip(entry.rows, normalize(raw_bm25))
        }
        bm25_match_ids = rank_bm25_match_ids(entry.rows, entry.corpus, raw_bm25, query)
        return entry.rows, entry.row_map, bm25_norm, bm25_match_ids, cache_hit

    def _timed_vector_search(
        self,
        query: str,
        candidate_k: int,
        knowledge_base_ids: list[str] | None,
    ) -> tuple[list[dict[str, Any]], float]:
        started = time.perf_counter()
        rows = vector_store.vector_search(
            query,
            candidate_k,
            knowledge_base_ids=knowledge_base_ids,
        )
        return rows, (time.perf_counter() - started) * 1000

    def _timed_bm25_search(
        self,
        query: str,
        knowledge_base_ids: list[str] | None,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, float],
        list[str],
        bool,
        float,
    ]:
        started = time.perf_counter()
        rows, row_map, scores, match_ids, cache_hit = self._bm25_search(query, knowledge_base_ids)
        return rows, row_map, scores, match_ids, cache_hit, (time.perf_counter() - started) * 1000

    def _apply_cross_encoder(
        self,
        query: str,
        rows: list[dict[str, Any]],
        *,
        pool_size: int,
    ) -> tuple[list[dict[str, Any]], float]:
        """本地 Cross-Encoder 精排：V1 local 分支逐字抽出，行为不变（设计 §2 第一步）。

        返回 `(重排后的行, 打分耗时 ms)`。池尺寸由调用方给：

        - `provider=local` / `mode=off`：`max(top_k, retrieval_rerank_candidates)`（V1 口径）。
        - `provider=typesafe`：再并入 `typesafe_low_confidence_candidates`（§4 动态 TopK 的
          最宽档），否则 12 档永远拿不满输入。

        打分写回 `rerank_score`（归一化 + 保留 6 位），并按分数降序重排。
        """
        rerank_pool_size = max(1, int(pool_size))
        rows = rows[:rerank_pool_size]
        started = time.perf_counter()
        pairs = [[query, str(row.get("content", ""))] for row in rows]
        raw_scores = [float(value) for value in self.reranker.predict(pairs)]
        for row, score in zip(rows, normalize(raw_scores)):
            row["rerank_score"] = round(score, 6)
        rows.sort(key=lambda item: item["rerank_score"] or 0.0, reverse=True)
        return rows, (time.perf_counter() - started) * 1000

    def _router_skip_metrics(self, mode: str) -> dict[str, Any]:
        """路由免判时的 metrics 替身：零外呼 ⇒ 判定层没跑，观测键由检索层自造。"""
        return {
            "typesafe_enabled": True,
            "typesafe_mode": mode,
            "typesafe_trigger": False,
            "typesafe_skipped": TYPESAFE_SKIPPED_BY_ROUTER,
            "typesafe_cache_hit": 0,
            "typesafe_circuit_open": False,
            "typesafe_slow": False,
        }

    def _should_judge_by_mode(
        self, mode: str, query: str, judge_rows: list[dict[str, Any]]
    ) -> tuple[bool, list[str]]:
        """§3 模式表"调用条件"列：strict/shadow 恒判；selective 看信号；active 只跳高置信单一事实。

        返回 `(need, reasons)`（段B2 缺陷2）。`reasons` 是 §3 六信号（`REASON_TOKENS`）在
        **本次输入**上的读数：旧代码把 `should_judge` 的第二返回值写成 `_reasons` 丢弃，于是
        selective 的触发率标定只看得到"判/没判"、看不到"为什么"（段B 只能用"免判题 × 落档"
        做代理推断）。这里改为**四档一律取信号**、只有 selective 用它当调用门：

        - selective：`need = bool(reasons)`，即 `should_judge` 本义，行为逐字不变；
        - strict/shadow/active：`need` 仍按各自模式表算，`reasons` 只作观测随请求上报
          ——一轮 strict 因此自带"selective 反事实"读数（哪些题会被免判、因为哪个信号），
          这正是 §9 margin/floor 标定要的素材，且判定前的一次纯函数计算成本可忽略。

        四档**逐一点名**、未知 mode 直接抛（Fix round 1 / M7）：写成" else 走 active"的话，
        Task 2 若加第六档，这里会**静默按 active 免判**——一个该花钱的档位被悄悄变成省钱的档位，
        既不报错也没有观测面。off 不会到这里（已并入 `use_local_reranker` 支路）。
        """
        _, reasons = should_judge(query, judge_rows)
        if mode in {"strict", "shadow"}:
            return True, reasons
        if mode == "selective":
            return bool(reasons), reasons
        if mode == "active":
            return not is_high_confidence_single_fact(query, judge_rows), reasons
        raise ValueError("未知 TypeSafe 模式")

    def _search_impl(
        self,
        query: str,
        top_k: int | None = None,
        mode: SearchMode = "hybrid",
        rerank: bool = False,
        knowledge_base_ids: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if mode not in {"vector", "bm25", "hybrid"}:
            raise ValueError("无效检索模式")

        total_started = time.perf_counter()
        query = clean_question(query)
        top_k = top_k or settings.top_k
        vector_candidate_k = max(top_k, int(settings.retrieval_vector_candidates))
        bm25_candidate_k = max(top_k, int(settings.retrieval_bm25_candidates))
        vector_instruction_enabled = bool(
            mode == "vector" and settings.retrieval_vector_query_instruction.strip()
        )
        vector_query = build_dense_query(
            query,
            use_instruction=vector_instruction_enabled,
        )

        vector_rows: list[dict[str, Any]] = []
        all_rows: list[dict[str, Any]] = []
        all_map: dict[str, dict[str, Any]] = {}
        bm25_norm: dict[str, float] = {}
        bm25_match_ids: list[str] = []
        bm25_cache_hit = False
        vector_ms = 0.0
        bm25_ms = 0.0

        if mode == "hybrid" and settings.retrieval_parallel_hybrid:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="yaoke-retrieval") as executor:
                vector_future = executor.submit(
                    self._timed_vector_search,
                    vector_query,
                    vector_candidate_k,
                    knowledge_base_ids,
                )
                bm25_future = executor.submit(
                    self._timed_bm25_search,
                    query,
                    knowledge_base_ids,
                )
                vector_rows, vector_ms = vector_future.result()
                all_rows, all_map, bm25_norm, bm25_match_ids, bm25_cache_hit, bm25_ms = (
                    bm25_future.result()
                )
        else:
            if mode in {"vector", "hybrid"}:
                vector_rows, vector_ms = self._timed_vector_search(
                    vector_query,
                    vector_candidate_k,
                    knowledge_base_ids,
                )
            if mode in {"bm25", "hybrid"}:
                all_rows, all_map, bm25_norm, bm25_match_ids, bm25_cache_hit, bm25_ms = (
                    self._timed_bm25_search(
                        query,
                        knowledge_base_ids,
                    )
                )

        fusion_started = time.perf_counter()
        vector_map = {row["id"]: row for row in vector_rows}
        vector_ids = [row["id"] for row in vector_rows[:vector_candidate_k]]
        raw_vector = [float(row.get("vector_raw_score", 0.0)) for row in vector_rows]
        vector_norm = {
            row["id"]: score
            for row, score in zip(vector_rows, normalize(raw_vector))
        }

        bm25_ids = [
            point_id
            for point_id in sorted(bm25_norm, key=bm25_norm.get, reverse=True)
            if bm25_norm.get(point_id, 0.0) > 0
        ][:bm25_candidate_k]
        if len(bm25_ids) < bm25_candidate_k:
            selected_bm25 = set(bm25_ids)
            bm25_ids.extend(
                [
                    point_id
                    for point_id in bm25_match_ids
                    if point_id not in selected_bm25
                ][: bm25_candidate_k - len(bm25_ids)]
            )

        rrf_raw: dict[str, float] = {}
        rrf_norm: dict[str, float] = {}
        if mode == "vector":
            candidate_ids = vector_ids
        elif mode == "bm25":
            candidate_ids = bm25_ids
        else:
            rrf_raw = reciprocal_rank_fusion(
                vector_ids,
                bm25_ids,
                k=int(settings.retrieval_rrf_k),
            )
            candidate_ids = sorted(rrf_raw, key=rrf_raw.get, reverse=True)
            normalized_rrf = normalize([rrf_raw[point_id] for point_id in candidate_ids])
            rrf_norm = {
                point_id: score
                for point_id, score in zip(candidate_ids, normalized_rrf)
            }

        rows: list[dict[str, Any]] = []
        for point_id in candidate_ids:
            source = vector_map.get(point_id) or all_map.get(point_id) or {}
            vector_score = vector_norm.get(point_id, 0.0)
            bm25_score = bm25_norm.get(point_id, 0.0)
            if mode == "vector":
                final_score = vector_score
            elif mode == "bm25":
                final_score = bm25_score
            else:
                final_score = rrf_norm.get(point_id, 0.0)

            rows.append(
                {
                    **source,
                    "vector_score": round(vector_score, 6),
                    "bm25_score": round(bm25_score, 6),
                    "rrf_score": round(rrf_raw.get(point_id, 0.0), 8) if mode == "hybrid" else None,
                    "hybrid_score": round(final_score, 6),
                    "rerank_score": None,
                    "bm25_cache_hit": bm25_cache_hit if mode in {"bm25", "hybrid"} else None,
                }
            )

        rows.sort(key=lambda item: item["hybrid_score"], reverse=True)
        fusion_ms = (time.perf_counter() - fusion_started) * 1000

        rerank_ms = 0.0
        rerank_candidate_count = 0
        typesafe_metrics: dict[str, Any] = {}
        stage_timings: dict[str, Any] = {}
        # `mode=off`（含 `typesafe_enabled=false`）并入本地 CE 路：判定层关掉时精排不能跟着消失
        # （Task 5 交接硬前置第 3 条）。`provider=local` 走的也是这条不变式通路。
        use_local_reranker = bool(
            rerank
            and rows
            and (
                settings.rerank_provider == "local"
                or settings.effective_typesafe_mode == "off"
            )
        )
        if use_local_reranker:
            rows, rerank_ms = self._apply_cross_encoder(
                query,
                rows,
                pool_size=max(top_k, int(settings.retrieval_rerank_candidates)),
            )
            rerank_candidate_count = len(rows)
        elif rerank and rows and settings.rerank_provider == "typesafe":
            # ============ TypeSafe V2 判定段（设计 §2）============
            # 本地 CE 精排 → 语义去重 → 动态 TopK → 置信度/风险路由 → 判定 → 路由应用。
            # mode=off 与 provider=local 都已在上面并路，故此处恒为其余四档之一。
            typesafe_mode = settings.effective_typesafe_mode
            rows, ce_ms = self._apply_cross_encoder(
                query,
                rows,
                pool_size=max(
                    top_k,
                    int(settings.retrieval_rerank_candidates),
                    int(settings.typesafe_low_confidence_candidates),
                ),
            )
            rerank_candidate_count = len(rows)

            # 语义去重（§6）：一次批量取向量（≤池大小），cosine 达阈值即合并并保留高分块。
            # `fetch_vectors` 的契约是"存储失败一律返回 {}"，所以失败时退化成"不合并"（不丢块）。
            dedup_started = time.perf_counter()
            vectors = vector_store.fetch_vectors(
                [str(row.get("id") or "") for row in rows]
            )
            rows = dedupe_by_similarity(rows, vectors, settings.typesafe_dedup_cosine)
            dedup_ms = (time.perf_counter() - dedup_started) * 1000

            # 动态 TopK（§4）：判定输入 = CE 归一化分 + 去重后的**头部**行。
            # `pick_candidate_count` 给的是池宽上限，rows 未必有那么多，故再夹一次长度。
            count = pick_candidate_count(query, rows)
            judge_input_count = min(count, len(rows))
            judge_rows = rows[:judge_input_count]
            # 尾部保留（Task 6 fix round 1 / 主控裁决）：**判定集与返回集解耦**。§4 的 min 档
            # （默认 3）可以小于 top_k（默认 5），于是池里天然有一批"没进判定"的尾行。V1 没有
            # 这个概念（V1 的池 == 判定输入），照搬"只交付已判行"就会凭空丢行：exclude 越多
            # 结果越短，全判 exclude 时甚至返回空结果。尾行不参与 include/exclude/证据排序，
            # 但按 CE 序留在结果尾部（下面应用段结束时拼回），因此应用支路的返回条数
            # ≥ min(top_k, 池) 成立。`judge_input_count` 仍是动态 TopK 的实值，语义不动。
            tail = rows[judge_input_count:]

            typesafe_total_ms = 0.0
            judge_should, typesafe_reasons = self._should_judge_by_mode(
                typesafe_mode, query, judge_rows
            )
            if judge_should:
                # 预算用 Task 5 的工厂造（off→None、坏配置不抛），并且在判定段入口造。
                # 段B2 核因（spec §5「批次以 `typesafe_hard_timeout_ms` 包预算」）：这条预算的
                # **语义对象就是本批次**——`make_budget_from_settings()` 就这一次调用点，
                # `TimeoutBudget` 以构造时刻为零点 ⇒ 每判定批次一条新预算，批次之间不共享、
                # 也不跨阶段累计（一次 HTTP 检索 = 一段 = 一预算）。批次内 N 条逐判定请求共
                # 用它是规格本义（per-request timeout = min(剩余预算, 全局上限)）。
                batch = typesafe_judgment_service.judge_candidates(
                    query,
                    judge_rows,
                    knowledge_base_ids=knowledge_base_ids,
                    budget=make_budget_from_settings(),
                )
                typesafe_metrics = dict(batch.metrics)
                typesafe_total_ms = float(typesafe_metrics.get("typesafe_total_ms") or 0.0)

                # 应用门（Task 5 交接硬前置）：判定"不全"的三种形态——degraded（超时/失败/
                # 预算耗尽）、circuit_open（主动避险，判定层只交付缓存命中）、skipped（批次
                # 自己跳过）——一律不许应用。V1 只看 degraded，而 V2 的熔断路径刻意保持
                # degraded=False，沿用旧门就会把熔断期的结果集打成空/半空（下面那段循环
                # 对"没有判定的行"是丢弃）。
                if (
                    not typesafe_metrics.get("typesafe_degraded")
                    and not typesafe_metrics.get("typesafe_circuit_open")
                    and typesafe_metrics.get("typesafe_skipped") is None
                    and typesafe_mode in TYPESAFE_APPLY_MODES
                ):
                    annotated: list[dict[str, Any]] = []
                    for row in judge_rows:
                        judgment = batch.judgments.get(str(row.get("id") or ""))
                        if judgment is None:
                            continue
                        annotated.append({**row, **judgment.row_fields()})

                    annotated = [
                        row
                        for row in annotated
                        if row.get("typesafe_route") != "exclude"
                    ]
                    annotated.sort(
                        key=lambda item: max(
                            float(item.get("typesafe_contains_answer_evidence") or 0.0),
                            float(item.get("typesafe_contradicts_query_premise") or 0.0),
                        ),
                        reverse=True,
                    )
                    # 尾行接在已判行之后（Task 6 fix round 1）：它们没有判定 ⇒ 证据分按 0 计，
                    # 稳定排序后天然落在"证据分 0 的已判行"之后、并保持彼此间的 CE 序。
                    rows = annotated + tail
                # else：shadow（只观测）与三条故障退路都不重排、不剔除，用户可见序即上面的
                # 本地 CE 序。与 V1 的差别（V2 定案，spec §2）：V1 的退路是
                # `rows = original_rows`（融合序、且含整条候选链），V2 的退路是"CE 精排 +
                # 去重后的池"——因为 V2 把本地 CE 提成了判定段的前置阶段，shadow 的观测对象
                # 也跟着换成这条新管道；shadow 依旧"不影响用户可见序"，只是"序"的定义变成 CE 序。
            else:
                # 路由免判：判定服务一次都不问（V2 的成本目标本体），所以没有批次 metrics 可并入；
                # 观测键由检索层自造。用户可见序同上，仍是本地 CE 序（继续走 diversify）。
                typesafe_metrics = self._router_skip_metrics(typesafe_mode)

            # `rerank_ms` = 判定段总时长 = 本地 CE 段（`rerank_stage_ms`）+ TypeSafe 段：
            # `rerank_ms = ce_ms + typesafe_total_ms`。路由免判时后者为 0，
            # 于是 rerank_ms == rerank_stage_ms（需求 7 的口径定义）。
            rerank_ms = ce_ms + typesafe_total_ms
            typesafe_metrics["typesafe_skip"] = (
                typesafe_metrics.get("typesafe_skipped") is not None
            )
            # 段B2（观测缺陷修复）：§3 六信号读数随请求上报，判与免判两条路都带该键。
            # 值域 = `app.typesafe_router.REASON_TOKENS` 的子集（compound/margin/floor/risk/
            # dispersed/param 六枚 token，由发射器构造保证），不回传任何提交文本 ⇒ 白名单
            # 放开它没有泄密面。旧实现 `_reasons` 丢弃 ⇒ selective 标定只能看"判/没判"。
            typesafe_metrics["typesafe_reasons"] = list(typesafe_reasons)
            stage_timings = {
                "rerank_stage_ms": round(ce_ms, 2),
                "dedup_ms": round(dedup_ms, 2),
                "judge_input_count": judge_input_count,
            }

        diversity_started = time.perf_counter()
        final_rows = diversify_by_document(
            rows,
            top_k=top_k,
            max_per_document=int(settings.retrieval_max_chunks_per_document),
        )
        diversity_ms = (time.perf_counter() - diversity_started) * 1000
        total_ms = (time.perf_counter() - total_started) * 1000
        timings = {
            "vector_ms": round(vector_ms, 2),
            "bm25_ms": round(bm25_ms, 2),
            "fusion_ms": round(fusion_ms, 2),
            "rerank_ms": round(rerank_ms, 2),
            "diversity_ms": round(diversity_ms, 2),
            "total_ms": round(total_ms, 2),
            "bm25_cache_hit": bm25_cache_hit if mode in {"bm25", "hybrid"} else None,
            "parallel_hybrid": bool(mode == "hybrid" and settings.retrieval_parallel_hybrid),
            "fusion": "rrf" if mode == "hybrid" else mode,
            "vector_query_instruction": vector_instruction_enabled,
            "vector_candidates": len(vector_ids) if mode in {"vector", "hybrid"} else 0,
            "bm25_candidates": len(bm25_ids) if mode in {"bm25", "hybrid"} else 0,
            "rerank_candidates": rerank_candidate_count,
            "max_chunks_per_document": int(settings.retrieval_max_chunks_per_document),
            "returned_documents": len(
                {
                    (str(row.get("knowledge_base_id") or ""), str(row.get("file_name") or ""))
                    for row in final_rows
                    if row.get("file_name")
                }
            ),
            # V2 判定段的本地计时：只在 provider=typesafe 且 mode!=off 时出现，
            # 因此 provider=local / mode=off 两条路的键集合与现网（V1）逐字相同。
            **stage_timings,
            **typesafe_metrics,
        }
        return final_rows, timings

    def search(
        self,
        query: str,
        top_k: int | None = None,
        mode: SearchMode = "hybrid",
        rerank: bool = False,
        knowledge_base_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows, _ = self._search_impl(
            query,
            top_k=top_k,
            mode=mode,
            rerank=rerank,
            knowledge_base_ids=knowledge_base_ids,
        )
        return rows

    def search_with_timings(
        self,
        query: str,
        top_k: int | None = None,
        mode: SearchMode = "hybrid",
        rerank: bool = False,
        knowledge_base_ids: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return self._search_impl(
            query,
            top_k=top_k,
            mode=mode,
            rerank=rerank,
            knowledge_base_ids=knowledge_base_ids,
        )


retrieval_service = RetrievalService()
