from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

# Reuse the same deterministic model boundary used by the existing real-Qdrant CI.
from qdrant_integration import install_ci_stubs, wait_for_qdrant


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    wait_for_qdrant()
    os.environ["QDRANT_URL"] = "http://127.0.0.1:6333"
    os.environ["QDRANT_COLLECTION"] = "yaoke_p16_ci"
    os.environ["DEMO_DATA_DIR"] = str((ROOT / "demo-data").resolve())
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:1"
    os.environ["OLLAMA_MODEL"] = "ornith-1.5:9b"
    os.environ["WEB_SEARCH_ENABLED"] = "false"
    os.environ["JWT_SECRET"] = "yaoke-p16-integration-secret-at-least-32-bytes"

    install_ci_stubs()
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))

    from fastapi.testclient import TestClient
    import app.agent as agent_module
    from app.config import settings
    from app.conversation_agent import _contextual_retrieval_query
    from app.main_agent import app
    from app.retrieval import retrieval_service
    from app.retrieval_text import build_retrieval_text
    from app.store import vector_store

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        require(login.status_code == 200, f"admin login failed: {login.text}")
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        init = client.post("/api/demo/initialize", headers=headers, json={})
        require(init.status_code == 200, f"Demo initialize failed: {init.text}")
        status = init.json().get("status") or {}
        require(status.get("ready") is True, f"Demo not ready: {status}")
        require(
            status.get("retrieval_schema_version") == settings.retrieval_schema_version,
            f"schema version mismatch: {status}",
        )
        print(f"[OK] Demo index schema: {settings.retrieval_schema_version}")

        rows = vector_store.all_chunks()
        require(bool(rows), "Qdrant has no chunks")
        require(
            all(row.get("retrieval_schema_version") == settings.retrieval_schema_version for row in rows),
            "legacy retrieval schema rows remain after Demo initialization",
        )
        require(all(row.get("document_title") for row in rows), "document_title missing from chunks")
        require(any(row.get("section_title") for row in rows), "Markdown section_title metadata was not persisted")
        sample = next(row for row in rows if row.get("section_title"))
        retrieval_text = build_retrieval_text(sample)
        require("文档：" in retrieval_text, f"document metadata missing from retrieval text: {retrieval_text}")
        require("章节：" in retrieval_text, f"section metadata missing from retrieval text: {retrieval_text}")
        require("知识库：" in retrieval_text, f"KB metadata missing from retrieval text: {retrieval_text}")
        print("[OK] Metadata-aware chunks are persisted and used to build retrieval text")

        info = vector_store.client.get_collection(settings.qdrant_collection)
        payload_schema = getattr(info, "payload_schema", None) or {}
        require("knowledge_base_id" in payload_schema, f"knowledge_base_id payload index missing: {payload_schema}")
        require("file_name" in payload_schema, f"file_name payload index missing: {payload_schema}")
        print("[OK] Qdrant payload indexes: knowledge_base_id + file_name")

        hybrid_rows, timings = retrieval_service.search_with_timings(
            "X200 整机质保期限是多少？",
            top_k=5,
            mode="hybrid",
            rerank=False,
            knowledge_base_ids=["kb_product"],
        )
        require(bool(hybrid_rows), "Hybrid RRF returned no results")
        require(timings.get("fusion") == "rrf", f"Hybrid did not report RRF: {timings}")
        require(int(timings.get("vector_candidates") or 0) >= 5, f"vector candidate pool too small: {timings}")
        require(int(timings.get("bm25_candidates") or 0) >= 1, f"BM25 candidate pool empty: {timings}")
        require(any(row.get("rrf_score") is not None for row in hybrid_rows), "RRF score missing from Hybrid rows")
        print(
            "[OK] Hybrid uses RRF; "
            f"vector_candidates={timings.get('vector_candidates')} "
            f"bm25_candidates={timings.get('bm25_candidates')}"
        )

        enriched, contextualized = _contextual_retrieval_query(
            "那 X200 呢？",
            [{"role": "user", "content": "X100 的整机质保多久？", "status": "completed"}],
        )
        require(contextualized is True, "short follow-up was not contextualized")
        require("X200" in enriched, f"current entity missing from enriched query: {enriched}")
        require("X100" not in enriched, f"stale entity leaked into enriched query: {enriched}")
        require("质保" in enriched, f"previous topic was not inherited: {enriched}")
        print(f"[OK] Follow-up query enrichment: {enriched.replace(chr(10), ' | ')}")

        captured: list[dict] = []
        original_post = agent_module.httpx.post

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"message": {"role": "assistant", "content": "ok"}}

        def fake_post(_url, *, json, timeout):
            captured.append(dict(json))
            return FakeResponse()

        agent_module.httpx.post = fake_post
        try:
            agent_module._ollama_chat([{"role": "user", "content": "answer"}], [])
            agent_module._ollama_chat(
                [{"role": "user", "content": "route"}],
                [{"type": "function", "function": {"name": "enterprise_search"}}],
            )
        finally:
            agent_module.httpx.post = original_post

        synthesis, routing = captured
        require(synthesis.get("think") is False, f"synthesis should disable think: {synthesis}")
        require(synthesis.get("keep_alive") == settings.ollama_keep_alive, f"keep_alive missing: {synthesis}")
        require(
            synthesis.get("options", {}).get("num_predict") == settings.agent_num_predict_synthesis,
            f"synthesis num_predict mismatch: {synthesis}",
        )
        require(routing.get("think") is True, f"tool-routing reasoning should remain enabled: {routing}")
        require(
            routing.get("options", {}).get("num_predict") == settings.agent_num_predict_tool_routing,
            f"routing num_predict mismatch: {routing}",
        )
        print("[OK] Ollama latency policy: synthesis think=false, routing think=true, keep_alive enabled")

        evaluation = client.post(
            "/api/evaluation/run",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "modes": ["vector", "bm25", "hybrid", "hybrid_rerank"],
                "top_k": 3,
            },
        )
        require(evaluation.status_code == 200, f"evaluation failed: {evaluation.text}")
        report = evaluation.json().get("report") or {}
        require(set(report) == {"vector", "bm25", "hybrid", "hybrid_rerank"}, f"evaluation modes missing: {report}")
        for mode in ("vector", "bm25", "hybrid", "hybrid_rerank"):
            metrics = report[mode]
            print(
                f"[METRIC] {mode}: "
                f"Hit@1={metrics.get('hit_at_1')} "
                f"Hit@3={metrics.get('hit_at_3')} "
                f"MRR={metrics.get('mrr')} "
                f"elapsed_ms={metrics.get('elapsed_ms')}"
            )

    print("\nP1.6 retrieval integration: PASS")
    print("Note: semantic quality still requires a user-machine run with the real BGE model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
