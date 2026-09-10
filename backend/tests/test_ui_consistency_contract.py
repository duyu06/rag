from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class UiConsistencyContractsTest(unittest.TestCase):
    def test_main_ui_matches_p15_conversation_and_evaluation_capabilities(self):
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        demo_tools = (ROOT / "frontend/src/components/DemoTools.tsx").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        stale_ten_question_copy = "当前内置 " + "10 道"
        stale_demo_label = "P1." + "2 · 真实指标 + 审计"

        self.assertIn("yaoke / Enterprise RAG P1.5", page)
        self.assertIn(
            '<ConversationChatPanel selectedKb={selectedKb} bases={bases} />',
            page,
        )
        self.assertIn("30 题 · 四路 RAG 检索评测", page)
        self.assertIn('report?.bm25', page)
        self.assertIn('report?.hybrid_rerank', page)
        self.assertIn('title="BM25 Search"', page)
        self.assertIn('title="Hybrid + Rerank"', page)
        self.assertNotIn(stale_ten_question_copy, page)
        self.assertNotIn(stale_demo_label, page)
        self.assertNotIn("function ChatPanel(", page)

        self.assertIn("P1.5 / v0.5.0", demo_tools)
        self.assertIn("Conversation + Agent", demo_tools)
        self.assertIn("当前版本：**P1.5 / v0.5.0**", readme)
        self.assertIn("scripts/release_smoke.py --agent", readme)
        self.assertIn("docs/P1_5_CONVERSATIONS.md", readme)


if __name__ == "__main__":
    unittest.main()
