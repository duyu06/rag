from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "app" / "page.tsx"


class ChatPersistenceContractTests(unittest.TestCase):
    def test_chat_panel_stays_mounted_across_view_switches(self) -> None:
        text = PAGE.read_text(encoding="utf-8")
        self.assertIn('hidden={view !== "chat"}', text)
        self.assertIn('<ChatPanel selectedKb={selectedKb} bases={bases} />', text)
        self.assertNotIn('{view === "chat" && <ChatPanel', text)


if __name__ == "__main__":
    unittest.main()
