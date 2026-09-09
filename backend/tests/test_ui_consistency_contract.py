from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class UiConsistencyContractsTest(unittest.TestCase):
    def test_main_ui_matches_p14_evaluation_capabilities(self):
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        tools = (ROOT / "frontend/src/components/DemoTools.tsx").read_text(encoding="utf-8")

        self.assertIn("yaoke / Enterprise RAG P1.4", page)
        self.assertIn("30 题 · 四路 RAG 检索评测", page)
        self.assertIn('report?.bm25', page)
        self.assertIn('report?.hybrid_rerank', page)
        self.assertIn('title="BM25 Search"', page)
        self.assertIn('title="Hybrid + Rerank"', page)
        self.assertNotIn("当前内置 10 道", page)
        self.assertIn("P1.4 / v0.4.0", tools)
        self.assertNotIn("P1.2 · 真实指标 + 审计", tools)


if __name__ == "__main__":
    unittest.main()
