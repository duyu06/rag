from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import SecretStr


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.conversation_routes as conversation_routes
import app.conversation_stream_routes as stream_routes
import app.main as main_module
import app.retrieval as retrieval_module
from app.config import settings
from app.conversation_store import ConversationStore
from app.main_agent import app
from app.typesafe_judgments import judgment_cache, reset_typesafe_stats


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    normalized = raw.replace("\r\n", "\n")
    for frame in normalized.split("\n\n"):
        if not frame.strip():
            continue
        event = ""
        data = ""
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if event and data:
            events.append((event, json.loads(data)))
    return events


class TypeSafeApiRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        login = cls.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login.status_code == 200, login.text
        cls.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def setUp(self) -> None:
        # Task 5 起判定缓存是模块级共享态，而本文件有一条用例走**真实**判定服务
        # （缺 key 的配置级早退）⇒ 从空账开始，避免跨用例/跨文件读到陈旧命中。
        judgment_cache.clear()
        reset_typesafe_stats()

    def test_typesafe_off_keeps_legacy_query_and_debug_response_shapes(self) -> None:
        rows = [
            {
                "id": "point-1",
                "file_name": "policy.md",
                "page": 1,
                "content": "authorized content",
                "knowledge_base_id": "kb_public",
                "knowledge_base_name": "公共制度",
                "vector_score": 0.9,
                "bm25_score": 0.8,
                "hybrid_score": 1.0,
                "rerank_score": None,
            }
        ]
        off_timings = {
            "vector_ms": 1.0,
            "bm25_ms": 1.0,
            "fusion_ms": 1.0,
            "rerank_ms": 0.0,
            "total_ms": 3.0,
        }
        with (
            patch.object(
                main_module.retrieval_service,
                "search_with_timings",
                return_value=(rows, off_timings),
            ),
            patch.object(main_module, "generate_answer", return_value="answer [1]"),
            patch.object(main_module, "current_model_name", return_value="test-model"),
        ):
            query = self.client.post(
                "/api/query",
                headers=self.headers,
                json={
                    "question": "question",
                    "k": 3,
                    "use_hybrid_search": True,
                    "use_reranking": False,
                    "knowledge_base_id": "kb_public",
                },
            )
            debug = self.client.post(
                "/api/retrieval/debug",
                headers=self.headers,
                json={
                    "query": "question",
                    "mode": "hybrid",
                    "top_k": 3,
                    "rerank": False,
                    "knowledge_base_id": "kb_public",
                },
            )

        self.assertEqual(query.status_code, 200, query.text)
        self.assertEqual(
            set(query.json()),
            {"answer", "query", "sources", "num_sources", "model_used"},
        )
        self.assertNotIn("timings", query.json())
        self.assertEqual(debug.status_code, 200, debug.text)
        self.assertNotIn("typesafe", debug.json())

    def test_sse_tokens_sources_done_and_sqlite_are_consistent(self) -> None:
        secret = "never-stream-this-typesafe-key"
        source = {
            "citation_index": 1,
            "source_type": "enterprise",
            "title": "policy.md",
            "file_name": "policy.md",
            "page": 1,
            "content_preview": "authorized content",
            "relevance_score": 0.99,
            "knowledge_base_id": "kb_public",
            "knowledge_base_name": "公共制度",
            "url": None,
            "domain": None,
        }

        def fake_agent(**kwargs):
            kwargs["token_sink"]("第一段")
            kwargs["token_sink"]("第二段")
            return {
                "answer": "第一段第二段",
                "trace_id": "trace-typesafe-sse",
                "sources": [source],
                "model_used": "test-model",
                "context_messages": 0,
                "timings": {
                    "typesafe_degraded": False,
                    "typesafe_request_count": 2,
                    "typesafe_input_tokens": 200,
                    "typesafe_estimated_cost_usd": 0.0000084,
                    "typesafe_latency_p50_ms": 10.0,
                    "typesafe_latency_p95_ms": 12.0,
                    "ttft_ms": 25.0,
                },
            }

        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(str(Path(directory) / "conversation.db"))
            with (
                patch.object(conversation_routes, "conversation_store", store),
                patch.object(stream_routes, "conversation_store", store),
                patch.object(stream_routes, "run_conversation_agent", fake_agent),
            ):
                created = self.client.post(
                    "/api/conversations",
                    headers=self.headers,
                    json={"mode": "local", "knowledge_base_id": "kb_public"},
                )
                self.assertEqual(created.status_code, 201, created.text)
                conversation_id = created.json()["id"]

                with self.client.stream(
                    "POST",
                    f"/api/conversations/{conversation_id}/messages/stream",
                    headers=self.headers,
                    json={
                        "content": "question",
                        "mode": "local",
                        "knowledge_base_id": "kb_public",
                        "top_k": 3,
                        "rerank": True,
                    },
                ) as response:
                    self.assertEqual(response.status_code, 200)
                    raw = "".join(response.iter_text())

                events = parse_sse(raw)
                event_names = [event for event, _ in events]
                tokens = [payload["text"] for event, payload in events if event == "token"]
                sources_payload = next(payload for event, payload in events if event == "sources")
                done = next(payload for event, payload in events if event == "done")
                message_id = next(
                    payload["message_id"] for event, payload in events if event == "message"
                )

                self.assertEqual(tokens, ["第一段", "第二段"])
                self.assertLess(event_names.index("token"), event_names.index("sources"))
                self.assertLess(event_names.index("sources"), event_names.index("done"))
                self.assertEqual(sources_payload["sources"], [source])
                self.assertEqual(done["message"]["id"], message_id)
                self.assertEqual(done["message"]["content"], "第一段第二段")
                self.assertEqual(done["message"]["sources"], [source])
                self.assertEqual(done["timings"]["ttft_ms"], 25.0)
                self.assertEqual(done["timings"]["typesafe_request_count"], 2)
                self.assertNotIn(secret, raw)

                persisted = store.get(conversation_id, username="admin")
                assistant = [
                    item for item in persisted["messages"] if item["role"] == "assistant"
                ]
                self.assertEqual(len(assistant), 1)
                self.assertEqual(assistant[0]["id"], message_id)
                self.assertEqual(assistant[0]["status"], "completed")
                self.assertEqual(assistant[0]["content"], "第一段第二段")
                self.assertEqual(assistant[0]["sources"], [source])

    def test_missing_key_is_http_200_degraded_and_preserves_results(self) -> None:
        rows = [
            {
                "id": "a",
                "file_name": "a.md",
                "knowledge_base_id": "kb_public",
                "knowledge_base_name": "公共制度",
                "content": "first",
                "vector_raw_score": 0.9,
            },
            {
                "id": "b",
                "file_name": "b.md",
                "knowledge_base_id": "kb_public",
                "knowledge_base_name": "公共制度",
                "content": "second",
                "vector_raw_score": 0.8,
            },
        ]

        class StubReranker:
            """V2 判定段前置了本地 Cross-Encoder ⇒ 不注入就真去加载 bge-reranker。

            刻意给 **b > a**（与向量/融合序 a > b 反序）：缺 key 的降级退路交回的是"本地 CE
            序"，只有两序不同时这条断言才能区分"退 CE 序"和"压根没精排"（fix round 1 / M5）。
            """

            def predict(self, pairs):
                return [0.5 if "first" in str(pair[1]) else 1.0 for pair in pairs]

        with (
            patch("app.retrieval.vector_store.vector_search", return_value=rows),
            patch("app.retrieval.vector_store.fetch_vectors", return_value={}),
            patch.object(retrieval_module.retrieval_service, "_reranker", StubReranker()),
            patch.object(settings, "retrieval_vector_query_instruction", ""),
            patch.object(settings, "typesafe_enabled", True),
            # V2 的 active 会先被置信度路由免判（高置信单一事实 ⇒ 零外呼），要钉
            # "进了判定层之后缺 key 的降级退路"必须用 strict（§3：strict 恒调用）。
            patch.object(settings, "typesafe_mode", "strict"),
            patch.object(settings, "rerank_provider", "typesafe"),
            patch.object(settings, "typesafe_api_key", SecretStr("")),
        ):
            response = self.client.post(
                "/api/retrieval/debug",
                headers=self.headers,
                json={
                    "query": "question",
                    "mode": "vector",
                    "top_k": 2,
                    "rerank": True,
                    "knowledge_base_id": "kb_public",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # 可见序 = 本地 CE 序（b > a），不是融合序（a > b）：缺 key 的退路交回的是前者。
        self.assertEqual([item["file_name"] for item in body["results"]], ["b.md", "a.md"])
        self.assertTrue(body["typesafe"]["typesafe_degraded"])
        self.assertEqual(body["typesafe"]["typesafe_request_count"], 0)
        self.assertEqual(
            body["typesafe"]["typesafe_errors"],
            ["api_key_not_configured"],
        )


if __name__ == "__main__":
    unittest.main()
