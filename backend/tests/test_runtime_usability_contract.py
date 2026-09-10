from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class RuntimeUsabilityContractsTest(unittest.TestCase):
    def test_read_only_store_paths_do_not_create_collection_or_load_model(self):
        store = (ROOT / "backend/app/store.py").read_text(encoding="utf-8")
        vector_search = section(store, "    def vector_search(", "    def all_chunks(")
        all_chunks = section(store, "    def all_chunks(", "    def stats(")
        stats = section(store, "    def stats(", "    def delete_file(")

        self.assertIn("def collection_exists(self) -> bool", store)
        self.assertIn("if not self.collection_exists():", vector_search)
        self.assertNotIn("self.ensure_collection()", vector_search)
        self.assertIn("if not self.collection_exists():", all_chunks)
        self.assertNotIn("self.ensure_collection()", all_chunks)
        self.assertIn("if not self.collection_exists():", stats)
        self.assertNotIn("self.ensure_collection()", stats)
        self.assertIn("embedding_dimension", stats)

    def test_vector_and_bm25_paths_are_actually_isolated(self):
        retrieval = (ROOT / "backend/app/retrieval.py").read_text(encoding="utf-8")
        self.assertIn('if mode in {"vector", "hybrid"}:', retrieval)
        self.assertIn('if mode in {"bm25", "hybrid"}:', retrieval)
        self.assertIn('raise ValueError("无效检索模式")', retrieval)

    def test_ollama_probe_checks_configured_tag(self):
        rag = (ROOT / "backend/app/rag.py").read_text(encoding="utf-8")
        self.assertIn("def _ollama_model_installed", rag)
        self.assertIn('if ":" in wanted:', rag)
        self.assertIn("return wanted in installed_names", rag)

    def test_agent_stream_releases_busy_state_on_eof(self):
        api = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        self.assertIn("let doneSignaled = false;", api)
        self.assertIn("const consumeFrame = (frame: string)", api)
        self.assertIn("finally {", api)
        self.assertIn("if (!doneSignaled) handlers.onDone();", api)


if __name__ == "__main__":
    unittest.main()
