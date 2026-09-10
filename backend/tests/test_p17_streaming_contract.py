from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class P17StreamingContractsTest(unittest.TestCase):
    def test_ollama_synthesis_uses_native_streaming(self):
        native = (ROOT / "backend/app/native_stream.py").read_text(encoding="utf-8")
        self.assertIn('"stream": True', native)
        self.assertIn("with httpx.stream(", native)
        self.assertIn('"tools": []', native)
        self.assertIn('message.get("content")', native)
        self.assertNotIn("range(0, len(answer), 14)", native)

    def test_local_fast_path_forwards_real_tokens_without_changing_retrieval(self):
        agent = (ROOT / "backend/app/conversation_agent.py").read_text(encoding="utf-8")
        self.assertIn("token_sink: Callable[[str], None] | None = None", agent)
        self.assertIn("for text in ollama_chat_stream(messages):", agent)
        self.assertIn("token_sink(text)", agent)
        self.assertIn('"native_stream": native_stream', agent)
        self.assertIn('tool_registry.execute(\n            "enterprise_search"', agent)

    def test_conversation_sse_persists_one_assistant_message(self):
        routes = (ROOT / "backend/app/conversation_stream_routes.py").read_text(encoding="utf-8")
        entry = (ROOT / "backend/app/main_agent.py").read_text(encoding="utf-8")
        self.assertIn('@router.post("/{conversation_id}/messages/stream")', routes)
        self.assertIn('@router.post("/{conversation_id}/messages/{message_id}/retry/stream")', routes)
        self.assertIn('status="generating"', routes)
        self.assertIn("assistant_message_id=assistant_message[\"id\"]", routes)
        self.assertIn("message_id=assistant_message_id", routes)
        self.assertIn('status="completed"', routes)
        self.assertIn('status="failed"', routes)
        self.assertIn("StreamingResponse(", routes)
        self.assertIn("app.include_router(conversation_stream_router)", entry)

    def test_legacy_agent_stream_no_longer_slices_completed_answer(self):
        routes = (ROOT / "backend/app/agent_routes.py").read_text(encoding="utf-8")
        self.assertNotIn("range(0, len(answer), 14)", routes)
        self.assertIn("run_conversation_agent(", routes)
        self.assertIn("token_sink=token_sink", routes)

    def test_conversation_ui_consumes_sse_incrementally(self):
        api = (ROOT / "frontend/src/lib/conversations.ts").read_text(encoding="utf-8")
        panel = (ROOT / "frontend/src/components/ConversationChatPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("async sendStream(", api)
        self.assertIn("async retryStream(", api)
        self.assertIn('event === "token"', api)
        self.assertIn("conversationApi.sendStream(", panel)
        self.assertIn("conversationApi.retryStream(", panel)
        self.assertIn("item.content + text", panel)
        self.assertIn('message.content || <span className="typing">', panel)


if __name__ == "__main__":
    unittest.main()
