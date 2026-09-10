from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "app" / "page.tsx"


class ChatPersistenceContractTests(unittest.TestCase):
    def test_conversation_chat_stays_mounted_across_view_switches(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        # The chat is hidden rather than conditionally unmounted so local UI state
        # survives navigation; durable history is additionally backed by SQLite.
        self.assertIn('hidden={view !== "chat"}', text)
        self.assertIn(
            '<ConversationChatPanel selectedKb={selectedKb} bases={bases} />',
            text,
        )
        self.assertNotIn('{view === "chat" && <ConversationChatPanel', text)
        self.assertNotIn("function ChatPanel(", text)


if __name__ == "__main__":
    unittest.main()
