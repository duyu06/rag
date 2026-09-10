from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("QDRANT_URL", "http://127.0.0.1:6333")

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PayloadSchemaType, PointStruct, VectorParams
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from app.demo import DEMO_MANIFEST
from app.ingestion import chunk_markdown, chunk_text
from app.knowledge import get_base
from app.retrieval import build_dense_query, diversify_by_document, normalize, reciprocal_rank_fusion, tokenize
from app.retrieval_text import build_retrieval_text

MODEL = "BAAI/bge-small-zh-v1.5"
BASELINE_COLLECTION = "yaoke_p15_real_bge_ab"
P16_COLLECTION = "yaoke_p16_real_bge_ab"
DATASET = BACKEND / "eval_dataset.json"
DEMO_DATA = ROOT / "demo-data"
TOP_K = 3
P16_MAX_CHUNKS_PER_DOCUMENT = 2


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[index]


def build_rows() -> tuple[list[dict], list[dict]]:
    baseline: list[dict] = []
    p16: list[dict] = []
    for item in DEMO_MANIFEST:
        file_name = item["file_name"]
        kb_id = item["knowledge_base_id"]
        kb_name = str(get_base(kb_id)["name"])
        path = DEMO_DATA / file_name
        text = path.read_text(encoding="utf-8")

        for index, content in enumerate(chunk_text(text)):
            baseline.append(
                {
                    "id": str(uuid4()),
                    "content": content,
                    "file_name": file_name,
                    "knowledge_base_id": kb_id,
                    "chunk_index": index,
                }
            )

        for chunk in chunk_markdown(text):
            p16.append(
                {
                    "id": str(uuid4()),
                    **chunk,
                    "file_name": file_name,
                    "document_title": path.stem,
                    "knowledge_base_id": kb_id,
                    "knowledge_base_name": kb_name,
                }
            )
    return baseline, p16


def create_collection(client: QdrantClient, name: str, dimension: int, rows: list[dict], vectors) -> None:
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(name, vectors_config=VectorParams(size=dimension, distance=Distance.COSINE))
    client.create_payload_index(name, "knowledge_base_id", PayloadSchemaType.KEYWORD, wait=True)
    points = [
        PointStruct(id=row["id"], vector=vector.tolist(), payload=row)
        for row, vector in zip(rows, vectors)
    ]
    client.upsert(name, points=points, wait=True)


def kb_filter(kb_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="knowledge_base_id", match=MatchValue(value=kb_id))])


def make_bm25(rows: list[dict], p16: bool) -> dict[str, tuple[list[dict], BM25Okapi | None]]:
    result: dict[str, tuple[list[dict], BM25Okapi | None]] = {}
    for kb_id in sorted({str(row["knowledge_base_id"]) for row in rows}):
        scoped = [row for row in rows if row["knowledge_base_id"] == kb_id]
        corpus = [tokenize(build_retrieval_text(row) if p16 else str(row["content"])) for row in scoped]
        result[kb_id] = (scoped, BM25Okapi(corpus) if corpus else None)
    return result


def vector_rank(client: QdrantClient, collection: str, vector, kb_id: str, limit: int) -> list[tuple[str, float]]:
    response = client.query_points(
        collection_name=collection,
        query=vector.tolist(),
        query_filter=kb_filter(kb_id),
        limit=limit,
        with_payload=False,
    )
    return [(str(point.id), float(point.score)) for point in response.points]


def bm25_scores(query: str, scoped: list[dict], index: BM25Okapi | None) -> tuple[dict[str, float], list[str]]:
    if not scoped or index is None:
        return {}, []
    raw = [float(value) for value in index.get_scores(tokenize(query))]
    norm = {row["id"]: score for row, score in zip(scoped, normalize(raw))}
    ranked = [point_id for point_id in sorted(norm, key=norm.get, reverse=True) if norm[point_id] > 0]
    return norm, ranked


def baseline_hybrid(vector_rows: list[tuple[str, float]], bm25_norm: dict[str, float], bm25_ranked: list[str]) -> list[str]:
    candidate_k = 12
    vector_rows = vector_rows[:candidate_k]
    vector_ids = [point_id for point_id, _ in vector_rows]
    vector_norm_values = normalize([score for _, score in vector_rows])
    vector_norm = {point_id: score for point_id, score in zip(vector_ids, vector_norm_values)}
    candidate_ids = list(vector_ids)
    for point_id in bm25_ranked[:candidate_k]:
        if point_id not in candidate_ids:
            candidate_ids.append(point_id)
    scores = {
        point_id: 0.70 * vector_norm.get(point_id, 0.0) + 0.30 * bm25_norm.get(point_id, 0.0)
        for point_id in candidate_ids
    }
    return sorted(candidate_ids, key=scores.get, reverse=True)[:TOP_K]


def diversify_ids(ids: list[str], row_map: dict[str, dict]) -> list[str]:
    rows = [{**row_map[point_id], "id": point_id} for point_id in ids]
    diversified = diversify_by_document(
        rows,
        top_k=TOP_K,
        max_per_document=P16_MAX_CHUNKS_PER_DOCUMENT,
    )
    return [str(row["id"]) for row in diversified]


def p16_hybrid(vector_rows: list[tuple[str, float]], bm25_ranked: list[str], row_map: dict[str, dict]) -> list[str]:
    vector_ids = [point_id for point_id, _ in vector_rows[:30]]
    scores = reciprocal_rank_fusion(vector_ids, bm25_ranked[:30], k=60)
    ranked = sorted(scores, key=scores.get, reverse=True)
    return diversify_ids(ranked, row_map)


def metrics(ranks: list[int | None], latencies: list[float]) -> dict[str, float]:
    total = len(ranks)
    hit1 = sum(rank == 1 for rank in ranks) / total
    hit3 = sum(rank is not None and rank <= 3 for rank in ranks) / total
    mrr = sum((1.0 / rank) if rank else 0.0 for rank in ranks) / total
    return {
        "hit@1": round(hit1, 4),
        "hit@3": round(hit3, 4),
        "mrr": round(mrr, 4),
        "latency_p50_ms": round(statistics.median(latencies), 2),
        "latency_p95_ms": round(percentile(latencies, 0.95), 2),
    }


def rank_for(ids: list[str], row_map: dict[str, dict], expected_file: str) -> int | None:
    for index, point_id in enumerate(ids, start=1):
        if row_map[point_id]["file_name"] == expected_file:
            return index
    return None


def describe_ids(ids: list[str], row_map: dict[str, dict]) -> list[str]:
    return [
        f"{row_map[point_id].get('file_name', '')} :: {row_map[point_id].get('section_title') or '(document)'}"
        for point_id in ids
    ]


def main() -> int:
    print(f"Loading real embedding model: {MODEL}")
    model = SentenceTransformer(MODEL)
    dimension = int(model.get_sentence_embedding_dimension())
    client = QdrantClient(url=os.environ["QDRANT_URL"], timeout=30)

    baseline_rows, p16_rows = build_rows()
    print(f"Indexing baseline chunks={len(baseline_rows)}; P1.6 chunks={len(p16_rows)}")
    baseline_vectors = model.encode(
        [row["content"] for row in baseline_rows],
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    p16_vectors = model.encode(
        [build_retrieval_text(row) for row in p16_rows],
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    create_collection(client, BASELINE_COLLECTION, dimension, baseline_rows, baseline_vectors)
    create_collection(client, P16_COLLECTION, dimension, p16_rows, p16_vectors)

    baseline_map = {row["id"]: row for row in baseline_rows}
    p16_map = {row["id"]: row for row in p16_rows}
    baseline_bm25 = make_bm25(baseline_rows, False)
    p16_bm25 = make_bm25(p16_rows, True)
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))

    results = {
        "p15_vector": ([], []),
        "p15_bm25": ([], []),
        "p15_hybrid": ([], []),
        "p16_vector": ([], []),
        "p16_bm25": ([], []),
        "p16_hybrid": ([], []),
    }
    vector_query_embedding_latencies: list[float] = []
    vector_debug: list[dict[str, object]] = []

    for item in dataset:
        question = item["question"]
        kb_id = item["knowledge_base_id"]
        expected = item["expected_file"]

        # P1.5 and P1.6 Hybrid both use the raw query. P1.6 pure Vector uses the
        # production mode-aware BGE instruction because that measured better for
        # dense Top-3 recall; passages are identical regardless of query mode.
        raw_query_vector = model.encode(
            build_dense_query(question, use_instruction=False),
            normalize_embeddings=True,
        )
        started = time.perf_counter()
        p16_vector_query_vector = model.encode(
            build_dense_query(question, use_instruction=True),
            normalize_embeddings=True,
        )
        vector_query_embedding_latencies.append((time.perf_counter() - started) * 1000)

        # P1.5 baseline.
        started = time.perf_counter()
        b_vector = vector_rank(client, BASELINE_COLLECTION, raw_query_vector, kb_id, 12)
        elapsed = (time.perf_counter() - started) * 1000
        b_vector_ids = [point_id for point_id, _ in b_vector[:TOP_K]]
        results["p15_vector"][0].append(rank_for(b_vector_ids, baseline_map, expected))
        results["p15_vector"][1].append(elapsed)

        b_scoped, b_index = baseline_bm25[kb_id]
        started = time.perf_counter()
        b_norm, b_ranked = bm25_scores(question, b_scoped, b_index)
        elapsed = (time.perf_counter() - started) * 1000
        results["p15_bm25"][0].append(rank_for(b_ranked[:TOP_K], baseline_map, expected))
        results["p15_bm25"][1].append(elapsed)

        started = time.perf_counter()
        b_hybrid = baseline_hybrid(b_vector, b_norm, b_ranked)
        elapsed = (time.perf_counter() - started) * 1000
        results["p15_hybrid"][0].append(rank_for(b_hybrid, baseline_map, expected))
        results["p15_hybrid"][1].append(elapsed)

        # P1.6 pure Vector uses the instructed query.
        started = time.perf_counter()
        n_vector = vector_rank(client, P16_COLLECTION, p16_vector_query_vector, kb_id, 30)
        n_vector_ids = diversify_ids([point_id for point_id, _ in n_vector], p16_map)
        elapsed = (time.perf_counter() - started) * 1000
        results["p16_vector"][0].append(rank_for(n_vector_ids, p16_map, expected))
        results["p16_vector"][1].append(elapsed)
        vector_debug.append(
            {
                "question": question,
                "expected": expected,
                "p15_ids": b_vector_ids,
                "p16_ids": n_vector_ids,
            }
        )

        n_scoped, n_index = p16_bm25[kb_id]
        started = time.perf_counter()
        _n_norm, n_ranked = bm25_scores(question, n_scoped, n_index)
        n_bm25_ids = diversify_ids(n_ranked, p16_map)
        elapsed = (time.perf_counter() - started) * 1000
        results["p16_bm25"][0].append(rank_for(n_bm25_ids, p16_map, expected))
        results["p16_bm25"][1].append(elapsed)

        # P1.6 Hybrid intentionally keeps the raw dense query: real-BGE A/B showed
        # raw query + RRF has higher Hit@1/MRR than globally applying the instruction.
        n_hybrid_vector = vector_rank(client, P16_COLLECTION, raw_query_vector, kb_id, 30)
        started = time.perf_counter()
        n_hybrid = p16_hybrid(n_hybrid_vector, n_ranked, p16_map)
        elapsed = (time.perf_counter() - started) * 1000
        results["p16_hybrid"][0].append(rank_for(n_hybrid, p16_map, expected))
        results["p16_hybrid"][1].append(elapsed)

    report = {name: metrics(ranks, latencies) for name, (ranks, latencies) in results.items()}
    report["vector_query_embedding"] = {
        "latency_p50_ms": round(statistics.median(vector_query_embedding_latencies), 2),
        "latency_p95_ms": round(percentile(vector_query_embedding_latencies, 0.95), 2),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    for index, item in enumerate(dataset):
        p15_rank = results["p15_hybrid"][0][index]
        p16_rank = results["p16_hybrid"][0][index]
        old = p15_rank if p15_rank is not None else 99
        new = p16_rank if p16_rank is not None else 99
        if new > old:
            print(
                f"[DIAG] Hybrid rank regression: {item['question']} "
                f"expected={item['expected_file']} P1.5={p15_rank} P1.6={p16_rank}"
            )

        p15_vector_rank = results["p15_vector"][0][index]
        p16_vector_rank = results["p16_vector"][0][index]
        old_vector = p15_vector_rank if p15_vector_rank is not None else 99
        new_vector = p16_vector_rank if p16_vector_rank is not None else 99
        if new_vector > old_vector:
            debug = vector_debug[index]
            print(
                f"[DIAG] Vector rank regression: {debug['question']} "
                f"expected={debug['expected']} P1.5={p15_vector_rank} P1.6={p16_vector_rank}"
            )
            print(f"[DIAG] P1.5 Vector Top3: {describe_ids(debug['p15_ids'], baseline_map)}")
            print(f"[DIAG] P1.6 Vector Top3: {describe_ids(debug['p16_ids'], p16_map)}")

    baseline_h = report["p15_hybrid"]
    candidate_h = report["p16_hybrid"]
    if candidate_h["hit@3"] < baseline_h["hit@3"]:
        raise AssertionError(f"P1.6 Hybrid Hit@3 regressed: {baseline_h} -> {candidate_h}")
    if candidate_h["mrr"] + 0.02 < baseline_h["mrr"]:
        raise AssertionError(f"P1.6 Hybrid MRR regressed by >0.02: {baseline_h} -> {candidate_h}")
    if report["p16_vector"]["hit@3"] < report["p15_vector"]["hit@3"]:
        raise AssertionError(f"P1.6 Vector Hit@3 regressed: {report['p15_vector']} -> {report['p16_vector']}")

    print("[PASS] Real-BGE P1.6 recall quality gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
