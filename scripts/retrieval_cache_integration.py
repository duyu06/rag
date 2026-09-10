from __future__ import annotations

import os
import sys
from pathlib import Path

from qdrant_integration import BACKEND, ROOT, install_ci_stubs, require, wait_for_qdrant


def main() -> int:
    wait_for_qdrant()
    os.environ["QDRANT_URL"] = "http://127.0.0.1:6333"
    os.environ["QDRANT_COLLECTION"] = "yaoke_ci"
    os.environ["DEMO_DATA_DIR"] = str((ROOT / "demo-data").resolve())
    os.environ["WEB_SEARCH_ENABLED"] = "false"
    os.environ["JWT_SECRET"] = "yaoke-ci-integration-secret-at-least-32-bytes"
    os.environ["BM25_CACHE_TTL_SECONDS"] = "300"
    os.environ["RETRIEVAL_PARALLEL_HYBRID"] = "true"

    install_ci_stubs()
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))

    from app.retrieval import retrieval_service

    retrieval_service.clear_bm25_cache()
    query = "X100 产品整机保修期多久？"
    scope = ["kb_product"]

    cold = retrieval_service.search(
        query,
        top_k=5,
        mode="hybrid",
        rerank=False,
        knowledge_base_ids=scope,
    )
    require(bool(cold), "cold hybrid query returned no results")
    require(
        cold[0].get("bm25_cache_hit") is False,
        f"cold hybrid query unexpectedly reported cache hit: {cold[0].get('bm25_cache_hit')}",
    )

    warm = retrieval_service.search(
        query,
        top_k=5,
        mode="hybrid",
        rerank=False,
        knowledge_base_ids=scope,
    )
    require(bool(warm), "warm hybrid query returned no results")
    require(
        warm[0].get("bm25_cache_hit") is True,
        f"warm hybrid query did not hit BM25 cache: {warm[0].get('bm25_cache_hit')}",
    )
    require(
        all(row.get("knowledge_base_id") == "kb_product" for row in warm),
        f"warm cache leaked outside authorized KB: {warm}",
    )

    print("[OK] cold hybrid query built BM25 index")
    print("[OK] warm hybrid query reused BM25 index from real-Qdrant scope")
    print("Retrieval cache integration: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
