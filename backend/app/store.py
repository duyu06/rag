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

    def ensure_collection(self) -> None:
        try:
            self.client.get_collection(settings.qdrant_collection)
        except Exception:
            self.client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(size=self.dimension, distance=Distance.COSINE),
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

    def vector_search(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        self.ensure_collection()
        vector = self.embedder.encode(query, normalize_embeddings=True).tolist()
        response = self.client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
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

    def all_chunks(self, limit: int = 10000) -> list[dict[str, Any]]:
        self.ensure_collection()
        points, _ = self.client.scroll(
            collection_name=settings.qdrant_collection,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [{"id": str(point.id), **dict(point.payload or {})} for point in points]

    def stats(self) -> dict[str, Any]:
        self.ensure_collection()
        info = self.client.get_collection(settings.qdrant_collection)
        return {
            "total_chunks": int(info.points_count or 0),
            "collection_name": settings.qdrant_collection,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": self.dimension,
        }

    def delete_file(self, file_name: str) -> None:
        self.ensure_collection()
        self.client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="file_name",
                            match=MatchValue(value=file_name),
                        )
                    ]
                )
            ),
            wait=True,
        )


vector_store = VectorStore()
