from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RuntimeMetadataContractsTest(unittest.TestCase):
    def test_p15_runtime_metadata_is_consistent(self):
        entry = (ROOT / "backend/app/main_agent.py").read_text(encoding="utf-8")
        self.assertIn('app.title = "yaoke API"', entry)
        self.assertIn('app.version = "0.5.0"', entry)
        self.assertIn('"version": "0.5.0"', entry)
        self.assertIn('"phase": "P1.5"', entry)

    def test_p15_health_reports_the_model_agent_actually_uses(self):
        entry = (ROOT / "backend/app/main_agent.py").read_text(encoding="utf-8")
        rag = (ROOT / "backend/app/rag.py").read_text(encoding="utf-8")

        self.assertIn('path in {"/", "/api/health"}', entry)
        self.assertIn("agent_ok, agent_detail = probe_ollama()", entry)
        self.assertIn('"status": "healthy" if (qdrant_ok and agent_ok) else "degraded"', entry)
        self.assertIn('"llm_connected": agent_ok', entry)
        self.assertIn('"llm_provider": "ollama"', entry)
        self.assertIn('"llm_model": settings.ollama_model', entry)
        self.assertIn('"legacy_rag_connected": legacy_ok', entry)
        self.assertIn('"legacy_rag_provider": legacy_provider', entry)
        self.assertIn("def probe_ollama", rag)
        self.assertIn("def probe_llm", rag)


if __name__ == "__main__":
    unittest.main()
