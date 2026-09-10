from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from app.config import settings


class VectorStore:
    def __init__(self) -> None:
        self._client: QdrantClient | None = None
        self._embedder: SentenceTransformer | None = None
        self._model_lock = Lock()

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            kwargs: dict[str, Any] = {"url": settings.qdrant_url, "timeout": 30.0}
            if settings.qdrant_api_key:
                kwargs["api_key"] = settings.qdrant_api_key
            self._client = QdrantClient(**kwargs)
        return self._client

    @property
    def embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            with self._model_lock:
                if self._embedder is None:
                    self._embedder = SentenceTransformer(settings.embedding_model)
        return self._embedder

    @property
    def dimension(self) -> int:
        return int(self.embedder.get_sentence_embedding_dimension())

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def collection_exists(self) -> bool:
        return bool(
            self.client.collection_exists(collection_name=settings.qdrant_collection)
        )

    def ensure_collection(self) -> None:
        if self.collection_exists():
            return
        self.client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=self.dimension, distance=Distance.COSINE),
        )

    @staticmethod
    def _dimension_from_collection(info: Any) -> int | None:
        params = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(params, "vectors", None)
        size = getattr(vectors, "size", None)
        if size is not None:
            return int(size)
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            size = getattr(first, "size", None)
            if size is not None:
                return int(size)
        return None

    @staticmethod
    def _kb_filter(knowledge_base_ids: list[str] | None) -> Filter | None:
        if not knowledge_base_ids:
            return None
        return Filter(
            must=[
                FieldCondition(
                    key="knowledge_base_id",
                    match=MatchAny(any=knowledge_base_ids),
                )
            ]
        )

    def add_chunks(self, chunks: list[dict[str, Any]]) -> int:
        if not chunks:
            return 0
        self.ensure_collection()
        vectors = self.embedder.encode(
            [str(chunk["content"]) for chunk in chunks],
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        )
        uploaded_at = datetime.now(timezone.utc).isoformat()
        points: list[PointStruct] = []
        for chunk, vector in zip(chunks, vectors):
            payload = dict(chunk)
            payload["uploaded_at"] = uploaded_at
            points.append(PointStruct(id=str(uuid4()), vector=vector.tolist(), payload=payload))
        self.client.upsert(
            collection_name=settings.qdrant_collection,
            points=points,
            wait=True,
        )
        return len(points)

    def vector_search(
        self,
        query: str,
        limit: int = 12,
        knowledge_base_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        # A read against a brand-new workspace should be cheap. Collection creation
        # and model loading happen only when data is actually ingested.
        if not self.collection_exists():
            return []
        vector = self.embedder.encode(query, normalize_embeddings=True).tolist()
        response = self.client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            query_filter=self._kb_filter(knowledge_base_ids),
            limit=limit,
            with_payload=True,
        )
        rows: list[dict[str, Any]] = []
        for point in response.points:
            rows.append(
                {
                    "id": str(point.id),
                    "vector_raw_score": float(point.score),
                    **dict(point.payload or {}),
                }
            )
        return rows

    def all_chunks(
        self,
        limit: int = 10000,
        knowledge_base_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.collection_exists():
            return []
        points, _ = self.client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=self._kb_filter(knowledge_base_ids),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [{"id": str(point.id), **dict(point.payload or {})} for point in points]

    def stats(self, knowledge_base_ids: list[str] | None = None) -> dict[str, Any]:
        if not self.collection_exists():
            cached_dimension = (
                int(self._embedder.get_sentence_embedding_dimension())
                if self._embedder is not None
                else None
            )
            return {
                "total_chunks": 0,
                "collection_name": settings.qdrant_collection,
                "embedding_model": settings.embedding_model,
                "embedding_dimension": cached_dimension,
            }

        info = self.client.get_collection(settings.qdrant_collection)
        if knowledge_base_ids:
            chunks = self.all_chunks(knowledge_base_ids=knowledge_base_ids)
            count = len(chunks)
        else:
            count = int(info.points_count or 0)

        dimension = self._dimension_from_collection(info)
        if dimension is None and self._embedder is not None:
            dimension = int(self._embedder.get_sentence_embedding_dimension())

        return {
            "total_chunks": count,
            "collection_name": settings.qdrant_collection,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": dimension,
        }

    def delete_file(self, file_name: str, knowledge_base_id: str | None = None) -> None:
        if not self.collection_exists():
            return
        must = [
            FieldCondition(
                key="file_name",
                match=MatchValue(value=file_name),
            )
        ]
        if knowledge_base_id:
            must.append(
                FieldCondition(
                    key="knowledge_base_id",
                    match=MatchValue(value=knowledge_base_id),
                )
            )
        self.client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=FilterSelector(filter=Filter(must=must)),
            wait=True,
        )


vector_store = VectorStore()
