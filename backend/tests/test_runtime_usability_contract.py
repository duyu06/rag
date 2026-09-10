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

    def test_host_and_docker_ollama_addresses_are_not_conflated(self):
        env_example = (ROOT / "backend/.env.example").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("OLLAMA_BASE_URL=http://localhost:11434", env_example)
        self.assertIn("OLLAMA_BASE_URL: http://host.docker.internal:11434", compose)
        self.assertIn('"host.docker.internal:host-gateway"', compose)
        self.assertIn("cd backend\nuvicorn app.main_agent:app", readme)

    def test_model_backed_smokes_require_real_demo_data_and_evidence(self):
        demo_smoke = (ROOT / "scripts/demo_smoke.py").read_text(encoding="utf-8")
        agent_smoke = (ROOT / "scripts/agent_smoke.py").read_text(encoding="utf-8")

        self.assertIn("if args.retrieval:", demo_smoke)
        self.assertIn("if not ready:", demo_smoke)
        self.assertIn("nonempty = bool(rows)", demo_smoke)
        self.assertIn("passed = nonempty and not leaked", demo_smoke)

        self.assertIn("if args.agent:", agent_smoke)
        self.assertIn("if not demo_ready(demo):", agent_smoke)
        self.assertIn('item.get("knowledge_base_id") == "kb_product"', agent_smoke)
        self.assertIn("citation_indexes_are_contiguous", agent_smoke)
        self.assertIn('trace_has_tool_status(sales_trace, "enterprise_search", "DENIED")', agent_smoke)
        self.assertIn('trace_has_tool_status(hr_trace, "enterprise_search", "DENIED")', agent_smoke)


if __name__ == "__main__":
    unittest.main()
