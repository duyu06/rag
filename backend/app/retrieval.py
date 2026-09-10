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
from app.store import vector_store
from app.web_search import clean_question

SearchMode = Literal["vector", "bm25", "hybrid"]


def tokenize(text: str) -> list[str]:
    value = text.lower()
    latin = re.findall(r"[a-z0-9_.-]+", value)
    chinese = re.findall(r"[\u4e00-\u9fff]", value)
    bigrams = ["".join(chinese[i : i + 2]) for i in range(max(0, len(chinese) - 1))]
    return latin + chinese + bigrams


def normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


@dataclass(slots=True)
class _BM25CacheEntry:
    revision: int
    expires_at: float
    rows: list[dict[str, Any]]
    row_map: dict[str, dict[str, Any]]
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
        if not knowledge_base_ids:
            return ("*",)
        return tuple(sorted(set(knowledge_base_ids)))

    def clear_bm25_cache(self) -> None:
        with self._bm25_cache_lock:
            self._bm25_cache.clear()

    def _get_bm25_entry(
        self,
        knowledge_base_ids: list[str] | None,
    ) -> tuple[_BM25CacheEntry, bool]:
        """Return a cached BM25 index for the current authorized KB scope.

        Cache is invalidated immediately for writes performed by this backend process
        through vector_store.data_revision, and also expires by TTL to avoid stale data
        when another process mutates the same Qdrant collection.
        """
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
        corpus = [tokenize(str(row.get("content", ""))) for row in rows]
        index = BM25Okapi(corpus) if corpus else None
        entry = _BM25CacheEntry(
            revision=revision,
            expires_at=now + ttl,
            rows=rows,
            row_map=row_map,
            index=index,
        )

        if ttl > 0 and vector_store.data_revision == revision:
            with self._bm25_cache_lock:
                # Drop entries from previous data revisions while keeping distinct
                # authorization scopes for the active revision.
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
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, float], bool]:
        entry, cache_hit = self._get_bm25_entry(knowledge_base_ids)
        if not entry.rows or entry.index is None:
            return entry.rows, entry.row_map, {}, cache_hit

        raw_bm25 = [float(value) for value in entry.index.get_scores(tokenize(query))]
        bm25_norm = {
            row["id"]: score
            for row, score in zip(entry.rows, normalize(raw_bm25))
        }
        return entry.rows, entry.row_map, bm25_norm, cache_hit

    def search(
        self,
        query: str,
        top_k: int | None = None,
        mode: SearchMode = "hybrid",
        rerank: bool = False,
        knowledge_base_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if mode not in {"vector", "bm25", "hybrid"}:
            raise ValueError("无效检索模式")

        query = clean_question(query)
        top_k = top_k or settings.top_k
        candidate_k = max(top_k * 4, 12)

        vector_rows: list[dict[str, Any]] = []
        all_rows: list[dict[str, Any]] = []
        all_map: dict[str, dict[str, Any]] = {}
        bm25_norm: dict[str, float] = {}
        bm25_cache_hit = False

        if mode == "hybrid" and settings.retrieval_parallel_hybrid:
            # Vector embedding/Qdrant query and BM25 scoring are independent. Running
            # them concurrently reduces wall-clock latency, especially on the first
            # query for a KB scope when its BM25 index is being built.
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="yaoke-retrieval") as executor:
                vector_future = executor.submit(
                    vector_store.vector_search,
                    query,
                    candidate_k,
                    knowledge_base_ids,
                )
                bm25_future = executor.submit(
                    self._bm25_search,
                    query,
                    knowledge_base_ids,
                )
                vector_rows = vector_future.result()
                all_rows, all_map, bm25_norm, bm25_cache_hit = bm25_future.result()
        else:
            if mode in {"vector", "hybrid"}:
                vector_rows = vector_store.vector_search(
                    query,
                    candidate_k,
                    knowledge_base_ids=knowledge_base_ids,
                )
            if mode in {"bm25", "hybrid"}:
                all_rows, all_map, bm25_norm, bm25_cache_hit = self._bm25_search(
                    query,
                    knowledge_base_ids,
                )

        vector_map = {row["id"]: row for row in vector_rows}
        raw_vector = [float(row.get("vector_raw_score", 0.0)) for row in vector_rows]
        vector_norm = {
            row["id"]: score
            for row, score in zip(vector_rows, normalize(raw_vector))
        }

        if mode == "vector":
            candidate_ids = list(vector_map.keys())
        elif mode == "bm25":
            candidate_ids = sorted(bm25_norm, key=bm25_norm.get, reverse=True)[:candidate_k]
        else:
            candidate_ids = list(vector_map.keys())
            for point_id in sorted(bm25_norm, key=bm25_norm.get, reverse=True)[:candidate_k]:
                if point_id not in candidate_ids:
                    candidate_ids.append(point_id)

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
                final_score = (
                    settings.vector_weight * vector_score
                    + (1 - settings.vector_weight) * bm25_score
                )

            rows.append(
                {
                    **source,
                    "vector_score": round(vector_score, 6),
                    "bm25_score": round(bm25_score, 6),
                    "hybrid_score": round(final_score, 6),
                    "rerank_score": None,
                    "bm25_cache_hit": bm25_cache_hit if mode in {"bm25", "hybrid"} else None,
                }
            )

        rows.sort(key=lambda item: item["hybrid_score"], reverse=True)
        rows = rows[:candidate_k]

        if rerank and rows:
            pairs = [[query, str(row.get("content", ""))] for row in rows]
            raw_scores = [float(value) for value in self.reranker.predict(pairs)]
            for row, score in zip(rows, normalize(raw_scores)):
                row["rerank_score"] = round(score, 6)
            rows.sort(key=lambda item: item["rerank_score"] or 0.0, reverse=True)

        return rows[:top_k]


retrieval_service = RetrievalService()
