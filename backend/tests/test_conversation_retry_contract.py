from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ConversationRetryContractTests(unittest.TestCase):
    def test_retry_endpoint_reuses_existing_assistant_message(self):
        routes = (ROOT / "backend/app/conversation_routes.py").read_text(encoding="utf-8")
        store = (ROOT / "backend/app/conversation_store.py").read_text(encoding="utf-8")
        self.assertIn('@router.post("/{conversation_id}/messages/{message_id}/retry")', routes)
        self.assertIn("只能重试 failed 消息", routes)
        self.assertIn("conversation_store.replace_message(", routes)
        self.assertIn("def replace_message(", store)
        self.assertIn("DELETE FROM message_sources WHERE message_id = ?", store)

    def test_frontend_exposes_retry_without_resending_user_turn(self):
        client = (ROOT / "frontend/src/lib/conversations.ts").read_text(encoding="utf-8")
        panel = (ROOT / "frontend/src/components/ConversationChatPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("async retry(", client)
        self.assertIn("/retry`", client)
        self.assertIn("const retryMessage = async", panel)
        self.assertIn("void retryMessage(message)", panel)

    def test_local_fast_path_exposes_retrieval_breakdown(self):
        retrieval = (ROOT / "backend/app/retrieval.py").read_text(encoding="utf-8")
        agent = (ROOT / "backend/app/conversation_agent.py").read_text(encoding="utf-8")
        self.assertIn("def search_with_timings(", retrieval)
        for key in ("vector_ms", "bm25_ms", "fusion_ms", "rerank_ms"):
            self.assertIn(f'"{key}"', retrieval)
            self.assertIn(f'"{key}"', agent)
        self.assertIn('"retrieval_total_ms"', agent)
        self.assertIn('"bm25_cache_hit"', agent)
        self.assertIn('"parallel_hybrid"', agent)


if __name__ == "__main__":
    unittest.main()
