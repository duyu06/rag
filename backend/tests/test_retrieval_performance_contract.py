from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RETRIEVAL = (ROOT / "backend" / "app" / "retrieval.py").read_text(encoding="utf-8")
RETRIEVAL_TEXT = (ROOT / "backend" / "app" / "retrieval_text.py").read_text(encoding="utf-8")
INGESTION = (ROOT / "backend" / "app" / "ingestion.py").read_text(encoding="utf-8")
STORE = (ROOT / "backend" / "app" / "store.py").read_text(encoding="utf-8")
DEMO = (ROOT / "backend" / "app" / "demo.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")
BENCH = (ROOT / "scripts" / "benchmark_retrieval.py").read_text(encoding="utf-8")


class RetrievalPerformanceContractTests(unittest.TestCase):
    def test_bm25_index_is_cached_by_scope(self):
        self.assertIn("_bm25_cache", RETRIEVAL)
        self.assertIn("_scope_key", RETRIEVAL)
        self.assertIn("bm25_cache_hit", RETRIEVAL)
        self.assertIn("BM25Okapi(corpus)", RETRIEVAL)

    def test_cache_invalidates_when_qdrant_data_changes(self):
        self.assertIn("data_revision", STORE)
        self.assertIn("_bump_data_revision()", STORE)
        self.assertIn("vector_store.data_revision", RETRIEVAL)

    def test_hybrid_runs_vector_and_bm25_in_parallel(self):
        self.assertIn("retrieval_parallel_hybrid", CONFIG)
        self.assertIn("ThreadPoolExecutor", RETRIEVAL)
        self.assertIn("vector_future", RETRIEVAL)
        self.assertIn("bm25_future", RETRIEVAL)

    def test_p16_uses_metadata_aware_dense_and_sparse_index_text(self):
        self.assertIn('parts.append(f"文档：{title}")', RETRIEVAL_TEXT)
        self.assertIn('parts.append(f"章节：{section}")', RETRIEVAL_TEXT)
        self.assertIn('parts.append(f"知识库：{kb_name}")', RETRIEVAL_TEXT)
        self.assertIn("build_retrieval_text(chunk)", STORE)
        self.assertIn("build_retrieval_text(row)", RETRIEVAL)
        self.assertIn("chunk_markdown", INGESTION)
        self.assertIn('"section_title": heading or None', INGESTION)

    def test_p16_uses_rrf_and_larger_independent_candidate_pools(self):
        self.assertIn("def reciprocal_rank_fusion", RETRIEVAL)
        self.assertIn("retrieval_rrf_k", CONFIG)
        self.assertIn("retrieval_vector_candidates", CONFIG)
        self.assertIn("retrieval_bm25_candidates", CONFIG)
        self.assertIn('"fusion": "rrf"', RETRIEVAL)
        self.assertNotIn("settings.vector_weight * vector_score", RETRIEVAL)

    def test_explicit_rerank_is_bounded(self):
        self.assertIn("retrieval_rerank_candidates", CONFIG)
        self.assertIn("rerank_pool_size", RETRIEVAL)
        self.assertIn("rows = rows[:rerank_pool_size]", RETRIEVAL)

    def test_qdrant_payload_filters_are_indexed(self):
        self.assertIn("PayloadSchemaType", STORE)
        self.assertIn('("knowledge_base_id", "file_name")', STORE)
        self.assertIn("create_payload_index", STORE)

    def test_demo_reindexes_when_retrieval_schema_changes(self):
        self.assertIn('retrieval_schema_version: str = "p16-metadata-rrf-v1"', CONFIG)
        self.assertIn('"retrieval_schema_version": settings.retrieval_schema_version', INGESTION)
        self.assertIn("_is_current_index", DEMO)
        self.assertIn("settings.retrieval_schema_version", DEMO)

    def test_benchmark_checks_warm_cache(self):
        self.assertIn("warm P50", BENCH)
        self.assertIn("warm P95", BENCH)
        self.assertIn("BM25 warm cache: PASS", BENCH)


if __name__ == "__main__":
    unittest.main()
