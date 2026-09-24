from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[2]


def ndjson(*rows: object) -> bytes:
    """Ollama 的 NDJSON 响应体（一行一个 JSON 对象）。"""
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")


def response_of(body: bytes):
    class _Response:
        def iter_bytes(self):
            yield body

    return _Response()


class P17StreamingContractsTest(unittest.TestCase):
    # 迁移说明（Task 7）：本类原来用「读源码 + assertIn 字面量」钉 Ollama 原生流式，
    # 那份实现现在住在 `app/llm/`（行解析 = normalize，HTTP 出口 = provider），
    # 所以断言**逐条换了落点、没有一条降低强度**：
    #   * 「发 `stream: true`」「空 tools 仍带键」「只读 `message.content`」「未收到
    #     `done: true` 不算成功」四件从 grep 升级成**行为断言**（直接调
    #     `ollama_payload` / `ollama_stream_lines`），比字符串更难被重写绕过；
    #   * 「不许把已成答案切片再吐」从「不含 `range(0, len(answer), 14)`」升级成
    #     「正向逐字相等 + CoT 一个字都不出现」。
    def test_native_stream_module_is_retired_and_its_semantics_live_in_llm(self):
        from app.llm import normalize
        from app.llm.models import LLMRequest

        self.assertFalse((ROOT / "backend/app/native_stream.py").exists(),
                         "Task 7 退役的模块又回来了 ⇒ 出现第二条流式出口（D6）")
        payload = normalize.ollama_payload(
            LLMRequest(messages=[{"role": "user", "content": "问题"}], tools=[]),
            "ornith-1.5:9b-text", stream=True)
        self.assertTrue(payload["stream"])                      # 原：'"stream": True'
        self.assertEqual([], payload["tools"])                   # 原：'"tools": []'
        self.assertEqual("ornith-1.5:9b-text", payload["model"])
        self.assertNotIn("temperature", payload)                 # 温度只在 options 里

    def test_partial_ndjson_stream_is_never_accepted_as_a_finished_answer(self):
        """原钉：`finished = False` + `chunk.get("done") is True` + `if not finished:` +
        「Ollama 流式响应提前结束」。同一件事现在由 `normalize.ollama_stream_lines` 负责，
        这里按**行为**钉：没有 `done: true` 的流必须抛，不能被当成一次成功答案。
        """
        from app.llm import normalize
        from app.llm.errors import LLMError

        body = ndjson({"message": {"content": "中"}})
        with self.assertRaises(LLMError) as caught:
            list(normalize.ollama_stream_lines(response_of(body)))
        self.assertIn("Ollama 流式响应提前结束", str(caught.exception))

    def test_ollama_stream_yields_message_content_verbatim_without_slicing(self):
        from app.llm import normalize

        # `reasoning` 里放一段可识别的文本：原钉「只读 message.content」，迁移后同一件
        # 事钉成「CoT 一个字都不许出现在 chunk 里」（D3 永不存 reasoning）。
        body = ndjson(
            {"message": {"content": "第一段"}, "reasoning": "HIDDEN-COT"},
            {"message": {"content": "第二段"}},
            {"message": {"content": ""}, "done": True, "eval_count": 3},
        )
        texts = [chunk.text for chunk in normalize.ollama_stream_lines(response_of(body))]
        # 末位那枚空文本 chunk 是 `done: true` 行的 usage 载体（`StreamSession` 刻意不在
        # 提交后扣住它）；除此之外一个字都不许多。
        self.assertEqual(["第一段", "第二段", ""], texts)           # 逐字，不切片、不合并
        self.assertNotIn("HIDDEN-COT", "".join(texts))
        self.assertNotIn("range(0, len(answer), 14)",
                         (ROOT / "backend/app/llm/normalize.py").read_text(encoding="utf-8"))

    def test_local_fast_path_forwards_real_tokens_without_changing_retrieval(self):
        agent = (ROOT / "backend/app/conversation_agent.py").read_text(encoding="utf-8")
        self.assertIn("token_sink: Callable[[str], None] | None = None", agent)
        # 原钉：`for text in ollama_chat_stream(messages):`（模块级 import 的那条流）。
        # 现钉：流式腿从 `llm.stream(...)` 拿会话，并消费 `session.chunks()`。
        self.assertIn("session = llm.stream(", agent)
        self.assertIn("for chunk in session.chunks():", agent)
        self.assertIn("token_sink(text)", agent)
        self.assertIn('"native_stream": native_stream', agent)
        self.assertIn('tool_registry.execute(\n            "enterprise_search"', agent)

    def test_redaction_happens_per_chunk_before_the_token_is_forwarded(self):
        """Task 7 的硬义务：脱敏点不许挪到 commit 之后或收尾之后。

        原来这里没有独立钉（`redact_text` 就写在 for 循环里）；迁移后「先吐再洗」在语法
        上完全合法，所以把它做成**顺序断言**：源码里 `redact_text(chunk.text)` 必须
        出现在 `token_sink(text)` 之前，且两者都在同一个 chunk 循环体内。
        """
        agent = (ROOT / "backend/app/conversation_agent.py").read_text(encoding="utf-8")
        loop = agent.index("for chunk in session.chunks():")
        body = agent[loop:agent.index("finally:", loop)]
        self.assertLess(body.index("redact_text(chunk.text)"), body.index("token_sink(text)"),
                        "脱敏必须发生在把这段文本推给客户端之前")
        self.assertIn("chunks.append(text)", body)

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
