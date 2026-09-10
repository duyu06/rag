from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ConversationUIP1CContractTests(unittest.TestCase):
    def test_chat_is_rendered_directly_without_portal_adapter(self):
        layout = (ROOT / "frontend/src/app/layout.tsx").read_text(encoding="utf-8")
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        adapter = ROOT / "frontend/src/components/ConversationExperience.tsx"
        self.assertNotIn("ConversationExperience", layout)
        self.assertFalse(adapter.exists())
        self.assertIn('import ConversationChatPanel from "@/components/ConversationChatPanel"', page)
        self.assertIn("<ConversationChatPanel selectedKb={selectedKb} bases={bases} />", page)
        self.assertNotIn("function ChatPanel(", page)

    def test_conversation_layout_has_responsive_classes(self):
        panel = (ROOT / "frontend/src/components/ConversationChatPanel.tsx").read_text(encoding="utf-8")
        css = (ROOT / "frontend/src/app/globals.css").read_text(encoding="utf-8")
        for class_name in (
            "conversation-shell",
            "conversation-history",
            "conversation-chat-main",
            "conversation-sources",
        ):
            self.assertIn(class_name, panel)
            self.assertIn(f".{class_name}", css)
        self.assertIn("@media (max-width: 850px)", css)
        self.assertIn("@media (max-width: 560px)", css)

    def test_agent_debugger_surfaces_p1b_timings(self):
        debugger = (ROOT / "frontend/src/app/admin/agent/page.tsx").read_text(encoding="utf-8")
        self.assertIn("性能分解", debugger)
        for key in (
            "vector_ms",
            "bm25_ms",
            "fusion_ms",
            "rerank_ms",
            "retrieval_total_ms",
            "llm_ms",
            "total_ms",
        ):
            self.assertIn(key, debugger)
        self.assertIn("hidden reasoning / chain-of-thought", debugger)

    def test_release_smoke_has_safe_and_real_agent_modes(self):
        smoke = (ROOT / "scripts/release_smoke.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument(\n        "--agent"', smoke)
        self.assertIn("SQLite conversation create + restore", smoke)
        self.assertIn("real Ornith Local Fast Path -> Qdrant -> Citation -> timings", smoke)
        self.assertIn("conversation cleanup", smoke)


if __name__ == "__main__":
    unittest.main()
