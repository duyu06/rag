from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.conversation_store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def test_persists_messages_sources_and_enforces_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conversations.db"
            store = ConversationStore(str(path))
            conversation = store.create(username="admin", mode="local")
            conversation_id = conversation["id"]

            store.add_message(
                conversation_id=conversation_id,
                username="admin",
                role="user",
                content="X100 的标准整机质保多久？",
            )
            store.maybe_title_from_first_question(
                conversation_id,
                username="admin",
                question="X100 的标准整机质保多久？",
            )
            assistant = store.add_message(
                conversation_id=conversation_id,
                username="admin",
                role="assistant",
                content="整机质保 24 个月。[1]",
                trace_id="trace-test",
                latency_ms=12.5,
                sources=[
                    {
                        "citation_index": 1,
                        "source_type": "enterprise",
                        "title": "03-X100产品说明书.md",
                        "file_name": "03-X100产品说明书.md",
                        "knowledge_base_id": "kb_product",
                        "knowledge_base_name": "产品知识库",
                        "page": None,
                        "content_preview": "标准整机质保 24 个月",
                        "relevance_score": 0.9,
                    }
                ],
            )
            self.assertEqual(assistant["sources"][0]["citation_index"], 1)

            # Re-open using a new store instance to prove data is persisted on disk,
            # rather than surviving only in an in-memory object.
            reopened = ConversationStore(str(path))
            detail = reopened.get(conversation_id, username="admin")
            self.assertEqual(len(detail["messages"]), 2)
            self.assertNotEqual(detail["title"], "新会话")
            self.assertEqual(detail["messages"][1]["trace_id"], "trace-test")
            self.assertEqual(
                detail["messages"][1]["sources"][0]["knowledge_base_id"],
                "kb_product",
            )

            with self.assertRaises(PermissionError):
                reopened.get(conversation_id, username="sales01")

            reopened.delete(conversation_id, username="admin")
            with self.assertRaises(KeyError):
                reopened.get(conversation_id, username="admin")

    def test_lists_only_current_users_conversations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(str(Path(directory) / "conversations.db"))
            store.create(username="admin", title="Admin chat")
            store.create(username="sales01", title="Sales chat")
            self.assertEqual([row["title"] for row in store.list("admin")], ["Admin chat"])
            self.assertEqual([row["title"] for row in store.list("sales01")], ["Sales chat"])


if __name__ == "__main__":
    unittest.main()
