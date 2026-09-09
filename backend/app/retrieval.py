from __future__ import annotations

import re
from threading import Lock
from typing import Any, Literal

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app.config import settings
from app.store import vector_store

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


class RetrievalService:
    def __init__(self) -> None:
        self._reranker: CrossEncoder | None = None
        self._reranker_lock = Lock()

    @property
    def reranker(self) -> CrossEncoder:
        if self._reranker is None:
            with self._reranker_lock:
                if self._reranker is None:
                    self._reranker = CrossEncoder(settings.rerank_model)
        return self._reranker

    def search(
        self,
        query: str,
        top_k: int | None = None,
        mode: SearchMode = "hybrid",
        rerank: bool = False,
        knowledge_base_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        top_k = top_k or settings.top_k
        candidate_k = max(top_k * 4, 12)

        vector_rows = vector_store.vector_search(
            query,
            candidate_k,
            knowledge_base_ids=knowledge_base_ids,
        )
        vector_map = {row["id"]: row for row in vector_rows}
        raw_vector = [float(row.get("vector_raw_score", 0.0)) for row in vector_rows]
        vector_norm = {
            row["id"]: score
            for row, score in zip(vector_rows, normalize(raw_vector))
        }

        all_rows = vector_store.all_chunks(knowledge_base_ids=knowledge_base_ids)
        all_map = {row["id"]: row for row in all_rows}
        bm25_norm: dict[str, float] = {}
        if all_rows:
            corpus = [tokenize(str(row.get("content", ""))) for row in all_rows]
            bm25 = BM25Okapi(corpus)
            raw_bm25 = [float(value) for value in bm25.get_scores(tokenize(query))]
            bm25_norm = {
                row["id"]: score
                for row, score in zip(all_rows, normalize(raw_bm25))
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
