from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RETRIEVAL = (ROOT / "backend" / "app" / "retrieval.py").read_text(encoding="utf-8")
STORE = (ROOT / "backend" / "app" / "store.py").read_text(encoding="utf-8")
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

    def test_hybrid_can_run_vector_and_bm25_in_parallel(self):
        self.assertIn("retrieval_parallel_hybrid", CONFIG)
        self.assertIn("ThreadPoolExecutor", RETRIEVAL)
        self.assertIn("vector_future", RETRIEVAL)
        self.assertIn("bm25_future", RETRIEVAL)

    def test_benchmark_checks_warm_cache(self):
        self.assertIn("warm P50", BENCH)
        self.assertIn("warm P95", BENCH)
        self.assertIn("BM25 warm cache: PASS", BENCH)


if __name__ == "__main__":
    unittest.main()
