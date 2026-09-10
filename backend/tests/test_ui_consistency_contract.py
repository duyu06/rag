from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class UiConsistencyContractsTest(unittest.TestCase):
    def test_main_ui_matches_p17_streaming_and_p16_retrieval_baseline(self):
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        chat = (ROOT / "frontend/src/components/ConversationChatPanel.tsx").read_text(encoding="utf-8")
        demo_tools = (ROOT / "frontend/src/components/DemoTools.tsx").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        stale_ten_question_copy = "当前内置 " + "10 道"
        stale_demo_label = "P1." + "2 · 真实指标 + 审计"

        # The dashboard badge intentionally names the retrieval baseline. P1.7 is
        # the conversation transport/UX release layered on top of P1.6 retrieval.
        self.assertIn("yaoke / Enterprise RAG P1.6", page)
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

        self.assertIn("Local 模式支持原生流式", chat)
        self.assertIn("conversationApi.sendStream(", chat)
        self.assertIn("P1.7 / v0.7.0", demo_tools)
        self.assertIn("Real Streaming", demo_tools)
        self.assertIn("当前版本：**P1.7 / v0.7.0**", readme)
        self.assertIn("scripts/release_smoke.py --agent", readme)
        self.assertIn("docs/P1_7_STREAMING.md", readme)
        self.assertIn("docs/P1_6_RELEASE.md", readme)
        self.assertIn("docs/P1_5_CONVERSATIONS.md", readme)


if __name__ == "__main__":
    unittest.main()
