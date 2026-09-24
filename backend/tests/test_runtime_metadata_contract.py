from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RuntimeMetadataContractsTest(unittest.TestCase):
    def test_p18_runtime_metadata_is_consistent(self):
        entry = (ROOT / "backend/app/main_agent.py").read_text(encoding="utf-8")
        self.assertIn('app.title = "yaoke API"', entry)
        self.assertIn('app.version = "0.8.0"', entry)
        self.assertIn('"version": "0.8.0"', entry)
        self.assertIn('"phase": "P1.8"', entry)

    def test_p18_health_reports_model_and_readiness_capabilities(self):
        entry = (ROOT / "backend/app/main_agent.py").read_text(encoding="utf-8")
        rag = (ROOT / "backend/app/rag.py").read_text(encoding="utf-8")
        # Model Router V2.3 Task 2（D6）：probe 的定义随迁入 app/llm/health.py，
        # HTTP 出口收编进 app/llm/provider.py。断言强度不降——只是换了文件读，
        # 并额外钉住 rag.py 里不再留第二份定义（那等于第二条出口）。
        health = (ROOT / "backend/app/llm/health.py").read_text(encoding="utf-8")

        self.assertIn('path in {"/", "/api/health"}', entry)
        self.assertIn("agent_ok, agent_detail = probe_ollama()", entry)
        self.assertIn('"status": "healthy" if (qdrant_ok and agent_ok) else "degraded"', entry)
        self.assertIn('"version": "0.8.0"', entry)
        self.assertIn('"phase": "P1.8"', entry)
        self.assertIn('"native_streaming": True', entry)
        self.assertIn('"llm_connected": agent_ok', entry)
        self.assertIn('"llm_provider": "ollama"', entry)
        self.assertIn('"llm_model": settings.ollama_model', entry)
        self.assertIn('"legacy_rag_connected": legacy_ok', entry)
        self.assertIn('"legacy_rag_provider": legacy_provider', entry)
        self.assertIn("def probe_ollama", health)
        self.assertIn("def probe_llm", health)
        self.assertNotIn("def probe_ollama", rag)
        self.assertNotIn("def probe_llm", rag)
        self.assertNotIn("import httpx", health)  # probe 只经 provider 出口发请求


if __name__ == "__main__":
    unittest.main()
