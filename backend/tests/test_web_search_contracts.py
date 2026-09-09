from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class WebSearchContractsTest(unittest.TestCase):
    def test_web_search_is_explicit_and_controlled(self):
        rag = (ROOT / "backend/app/rag.py").read_text(encoding="utf-8")
        web = (ROOT / "backend/app/web_search.py").read_text(encoding="utf-8")
        self.assertIn("[[NEXUS_WEB_SEARCH]]", web)
        self.assertIn("wants_web_search(question)", rag)
        self.assertIn("企业知识库证据优先", rag)
        self.assertIn("http", web)
        self.assertIn("https", web)

    def test_retrieval_strips_control_marker(self):
        retrieval = (ROOT / "backend/app/retrieval.py").read_text(encoding="utf-8")
        self.assertIn("query = clean_question(query)", retrieval)

    def test_ddgs_dependency_and_env_exist(self):
        requirements = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8")
        env = (ROOT / "backend/.env.example").read_text(encoding="utf-8")
        self.assertIn("ddgs", requirements)
        self.assertIn("WEB_SEARCH_ENABLED=true", env)
        self.assertIn("WEB_SEARCH_MAX_RESULTS=5", env)


if __name__ == "__main__":
    unittest.main()
