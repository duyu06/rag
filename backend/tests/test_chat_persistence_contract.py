from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "app" / "page.tsx"
ASK = ROOT / "frontend" / "src" / "views" / "AskView.tsx"
NAV = ROOT / "frontend" / "src" / "lib" / "nav.ts"


class ChatPersistenceContractTests(unittest.TestCase):
    def test_conversation_chat_stays_mounted_across_view_switches(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        ask = ASK.read_text(encoding="utf-8")
        nav = NAV.read_text(encoding="utf-8")
        # 视图层重构后问答由 AskView（02 问答）承载：切走再回来时靠持久化的
        # activeConversationPreference 恢复同一会话，历史本身仍由 SQLite 支撑。
        self.assertIn('{view === "ask" && <AskView {...sharedProps} />}', page)
        self.assertIn("selectedKb,", page)
        self.assertIn("activeConversationPreference.get()", ask)
        self.assertIn("activeConversationPreference.set(detail.id);", ask)
        self.assertIn("activeConversationPreference.set(created.id);", ask)
        self.assertIn("conversationApi.create(selectedKb)", ask)
        self.assertIn("conversationApi.list()", ask)
        # 写入/智能体权限仍决定问答可用，问答视图本身按 conversation:read 曝光。
        self.assertIn(
            'const canAsk = hasPermission(user, "conversation:write")'
            ' && hasPermission(user, "agent:run")'
            ' && hasPermission(user, "knowledge:query");',
            ask,
        )
        self.assertIn('{ key: "ask", idx: "02", zh: "问答", perms: ["conversation:read"] },', nav)
        self.assertNotIn('{view === "chat" && <ConversationChatPanel', page)
        self.assertNotIn("function ChatPanel(", page)


if __name__ == "__main__":
    unittest.main()
