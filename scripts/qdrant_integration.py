from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def fail(message: str) -> None:
    raise AssertionError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def wait_for_qdrant(url: str = "http://127.0.0.1:6333/healthz", timeout: int = 60) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 300:
                    print(f"[OK] Qdrant ready: {url}")
                    return
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Qdrant did not become ready within {timeout}s: {last_error}")


def _embed_one(text: str) -> np.ndarray:
    # Deterministic, tiny CI-only embedding. This validates Qdrant/API orchestration,
    # not semantic quality. Production continues to use the configured BGE model.
    vector = np.zeros(8, dtype=np.float32)
    for index, char in enumerate(str(text)):
        slot = (ord(char) + index * 17) % len(vector)
        vector[slot] += 1.0 + ((ord(char) % 7) / 10.0)
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector


class FakeSentenceTransformer:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def get_sentence_embedding_dimension(self) -> int:
        return 8

    def encode(self, values, **_kwargs):
        if isinstance(values, str):
            return _embed_one(values)
        rows = [_embed_one(str(value)) for value in values]
        return np.stack(rows) if rows else np.empty((0, 8), dtype=np.float32)


class FakeCrossEncoder:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def predict(self, pairs):
        scores = []
        for query, document in pairs:
            q = set(str(query))
            d = set(str(document))
            overlap = len(q & d) / max(1, len(q))
            scores.append(float(overlap))
        return np.asarray(scores, dtype=np.float32)


def install_ci_stubs() -> None:
    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = FakeSentenceTransformer
    sentence_transformers.CrossEncoder = FakeCrossEncoder
    sys.modules["sentence_transformers"] = sentence_transformers

    # Demo corpus is Markdown-only. These modules are imported by ingestion.py but
    # their PDF/DOCX code paths are intentionally outside this lightweight CI job.
    fitz = types.ModuleType("fitz")
    fitz.open = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("PDF parsing is not part of qdrant integration CI")
    )
    sys.modules["fitz"] = fitz

    docx = types.ModuleType("docx")
    docx.Document = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("DOCX parsing is not part of qdrant integration CI")
    )
    sys.modules["docx"] = docx

    ddgs = types.ModuleType("ddgs")

    class DisabledDDGS:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def text(self, *_args, **_kwargs):
            return []

    ddgs.DDGS = DisabledDDGS
    sys.modules["ddgs"] = ddgs


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client, username: str, password: str) -> tuple[str, dict]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    require(response.status_code == 200, f"login failed for {username}: {response.text}")
    data = response.json()
    return str(data["access_token"]), dict(data["user"])


def fake_ornith_chat(messages: list[dict], tools: list[dict]) -> dict:
    """CI-only Ornith boundary stub.

    It emits the same tool_calls shape expected from Ollama/Ornith, while every tool
    execution after that boundary remains the real yaoke implementation and real Qdrant.
    """
    if messages and messages[-1].get("role") == "tool":
        try:
            tool_result = json.loads(str(messages[-1].get("content") or "{}"))
        except json.JSONDecodeError:
            tool_result = {}
        if tool_result.get("status") == "DENIED":
            return {
                "role": "assistant",
                "content": "当前账号无权访问该知识库，因此不能基于未授权资料回答。",
            }
        evidence = tool_result.get("evidence") or []
        if evidence:
            citation = int(evidence[0].get("citation_index") or 1)
            return {
                "role": "assistant",
                "content": f"已根据授权企业资料完成回答。[{citation}]",
            }
        return {"role": "assistant", "content": "当前授权范围内没有足够证据。"}

    user_question = next(
        (str(item.get("content") or "") for item in reversed(messages) if item.get("role") == "user"),
        "",
    )
    if "X100" in user_question:
        arguments = {
            "query": "X100 产品整机保修期",
            "knowledge_base_id": "kb_product",
            "top_k": 3,
        }
    elif "调薪" in user_question:
        # Intentionally request an HR KB. The SALES test below must still be denied
        # by backend authorization, proving that model-generated tool arguments do
        # not become permissions.
        arguments = {
            "query": "公司年度调薪通常安排在几月",
            "knowledge_base_id": "kb_hr",
            "top_k": 3,
        }
    else:
        return {"role": "assistant", "content": "CI direct answer"}

    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "function": {
                    "name": "enterprise_search",
                    "arguments": arguments,
                }
            }
        ],
    }


def trace_tool_statuses(trace: dict, tool_name: str) -> list[str]:
    return [
        str(event.get("status"))
        for event in trace.get("events", [])
        if event.get("type") == "tool_end" and event.get("tool") == tool_name
    ]


def main() -> int:
    wait_for_qdrant()

    os.environ["QDRANT_URL"] = "http://127.0.0.1:6333"
    os.environ["QDRANT_COLLECTION"] = "yaoke_ci"
    os.environ["DEMO_DATA_DIR"] = str((ROOT / "demo-data").resolve())
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:1"
    os.environ["OLLAMA_MODEL"] = "ornith-1.5:9b"
    os.environ["WEB_SEARCH_ENABLED"] = "false"
    os.environ["JWT_SECRET"] = "yaoke-ci-integration-secret-at-least-32-bytes"

    install_ci_stubs()
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))

    from fastapi.testclient import TestClient
    import app.agent as agent_module
    from app.config import settings
    from app.main_agent import app
    from app.store import vector_store

    with TestClient(app) as client:
        ready = client.get("/api/ready")
        require(ready.status_code == 200, f"/api/ready failed: {ready.text}")
        print("[OK] FastAPI ready endpoint reached real Qdrant")

        admin_token, admin_user = login(client, "admin", "admin123")
        sales_token, sales_user = login(client, "sales01", "sales123")
        hr_token, hr_user = login(client, "hr01", "hr123")
        require(admin_user["role"] == "ADMIN", "admin role mismatch")
        require(sales_user["role"] == "SALES", "sales role mismatch")
        require(hr_user["role"] == "HR", "hr role mismatch")
        print("[OK] Demo JWT authentication")

        init = client.post("/api/demo/initialize", headers=auth_headers(admin_token), json={})
        require(init.status_code == 200, f"Demo initialize failed: {init.text}")
        init_data = init.json()
        status = init_data.get("status", {})
        require(status.get("ready") is True, f"Demo not ready after initialize: {status}")
        require(status.get("ready_count") == 20 and status.get("total") == 20, f"Demo corpus mismatch: {status}")
        print("[OK] 20/20 Demo documents indexed into real Qdrant")

        stats = client.get("/api/stats", headers=auth_headers(admin_token))
        require(stats.status_code == 200, f"stats failed: {stats.text}")
        stats_data = stats.json()
        require(stats_data.get("total_documents") == 20, f"expected 20 documents: {stats_data}")
        require(int(stats_data.get("total_chunks") or 0) >= 20, f"expected chunks in Qdrant: {stats_data}")
        require(stats_data.get("embedding_dimension") == 8, f"CI embedding dimension mismatch: {stats_data}")

        info = vector_store.client.get_collection(settings.qdrant_collection)
        qdrant_points = int(info.points_count or 0)
        require(qdrant_points == int(stats_data["total_chunks"]), "Qdrant points_count != API total_chunks")
        print(f"[OK] Real Qdrant collection contains {qdrant_points} chunks")

        documents = client.get("/api/documents", headers=auth_headers(admin_token))
        require(documents.status_code == 200, f"documents failed: {documents.text}")
        require(documents.json().get("total_documents") == 20, "document listing does not contain all Demo files")

        sales_hr = client.get(
            "/api/documents?knowledge_base_id=kb_hr",
            headers=auth_headers(sales_token),
        )
        hr_sales = client.get(
            "/api/documents?knowledge_base_id=kb_sales",
            headers=auth_headers(hr_token),
        )
        require(sales_hr.status_code == 403, f"SALES -> HR should be 403, got {sales_hr.status_code}")
        require(hr_sales.status_code == 403, f"HR -> SALES should be 403, got {hr_sales.status_code}")
        print("[OK] API-level RBAC denies forbidden knowledge bases")

        source = client.get(
            "/api/source/kb_product/03-X100%E4%BA%A7%E5%93%81%E8%AF%B4%E6%98%8E%E4%B9%A6.md",
            headers=auth_headers(admin_token),
        )
        require(source.status_code == 200, f"authorized source open failed: {source.status_code} {source.text}")
        forbidden_source = client.get(
            "/api/source/kb_hr/05-HR%E5%91%98%E5%B7%A5%E6%89%8B%E5%86%8C.md",
            headers=auth_headers(sales_token),
        )
        require(forbidden_source.status_code == 403, "SALES opened an HR source file")
        print("[OK] Citation source endpoint re-checks ACL")

        retrieval_cases = [
            ("vector", False, "kb_product", "X100 产品整机保修期多久？"),
            ("bm25", False, "kb_hr", "公司年度调薪通常安排在几月？"),
            ("hybrid", False, "kb_sales", "普通报价单默认有效期多少天？"),
            ("hybrid", True, "kb_service", "P1客户投诉首次响应要求多久？"),
        ]
        for mode, rerank, kb_id, query in retrieval_cases:
            response = client.post(
                "/api/retrieval/debug",
                headers={**auth_headers(admin_token), "Content-Type": "application/json"},
                json={
                    "query": query,
                    "mode": mode,
                    "top_k": 5,
                    "rerank": rerank,
                    "knowledge_base_id": kb_id,
                },
            )
            require(response.status_code == 200, f"{mode}/rerank={rerank} failed: {response.text}")
            rows = response.json().get("results", [])
            require(bool(rows), f"{mode}/rerank={rerank} returned no rows")
            require(all(row.get("knowledge_base_id") == kb_id for row in rows), f"{mode} leaked outside {kb_id}: {rows}")
            if rerank:
                require(any(row.get("rerank_score") is not None for row in rows), "rerank path did not emit rerank_score")
        print("[OK] Vector / BM25 / Hybrid / Rerank API paths run against real Qdrant")

        evaluation = client.post(
            "/api/evaluation/run",
            headers={**auth_headers(admin_token), "Content-Type": "application/json"},
            json={
                "modes": ["vector", "bm25", "hybrid", "hybrid_rerank"],
                "top_k": 3,
            },
        )
        require(evaluation.status_code == 200, f"evaluation failed: {evaluation.text}")
        evaluation_data = evaluation.json()
        require(evaluation_data.get("dataset_size") == 30, f"evaluation dataset mismatch: {evaluation_data.get('dataset_size')}")
        report = evaluation_data.get("report", {})
        expected_modes = {"vector", "bm25", "hybrid", "hybrid_rerank"}
        require(set(report) == expected_modes, f"evaluation mode mismatch: {set(report)}")
        for mode in expected_modes:
            require(report[mode].get("total") == 30, f"{mode} total != 30")
            require(len(report[mode].get("cases", [])) == 30, f"{mode} cases != 30")
        print("[OK] 30-question four-mode evaluation endpoint completed")

        # The LLM boundary is stubbed, but the Agent loop, tool registry,
        # authorization, retrieval and Qdrant below are the real application code.
        original_ollama_chat = agent_module._ollama_chat
        agent_module._ollama_chat = fake_ornith_chat
        try:
            admin_agent = client.post(
                "/api/agent/query",
                headers={**auth_headers(admin_token), "Content-Type": "application/json"},
                json={
                    "question": "X100 的标准整机质保多久？请依据企业资料回答。",
                    "mode": "local",
                    "knowledge_base_id": None,
                    "top_k": 5,
                    "rerank": False,
                },
            )
            require(admin_agent.status_code == 200, f"Agent enterprise query failed: {admin_agent.text}")
            admin_data = admin_agent.json()
            admin_sources = admin_data.get("sources", [])
            require(bool(admin_sources), "Agent enterprise query returned no evidence")
            require(admin_sources[0].get("source_type") == "enterprise", f"unexpected source type: {admin_sources}")
            require(admin_sources[0].get("knowledge_base_id") == "kb_product", f"Agent used wrong KB: {admin_sources}")
            require(admin_sources[0].get("citation_index") == 1, f"Agent citation index mismatch: {admin_sources}")
            require("[1]" in str(admin_data.get("answer") or ""), f"Agent final answer lost citation: {admin_data}")

            admin_trace_id = str(admin_data.get("trace_id") or "")
            admin_trace = client.get(
                f"/api/agent/traces/{admin_trace_id}",
                headers=auth_headers(admin_token),
            )
            require(admin_trace.status_code == 200, f"Agent trace unavailable: {admin_trace.text}")
            require(
                "SUCCESS" in trace_tool_statuses(admin_trace.json(), "enterprise_search"),
                f"Agent enterprise_search did not succeed: {admin_trace.json()}",
            )
            print("[OK] Agent tool_call -> enterprise_search -> real Qdrant -> Citation -> final")

            sales_agent = client.post(
                "/api/agent/query",
                headers={**auth_headers(sales_token), "Content-Type": "application/json"},
                json={
                    "question": "公司年度调薪通常安排在几月？请查询内部制度。",
                    "mode": "local",
                    "knowledge_base_id": None,
                    "top_k": 5,
                    "rerank": False,
                },
            )
            require(sales_agent.status_code == 200, f"SALES denied Agent query failed unexpectedly: {sales_agent.text}")
            sales_data = sales_agent.json()
            require(not sales_data.get("sources"), f"SALES received HR evidence: {sales_data.get('sources')}")
            sales_trace_id = str(sales_data.get("trace_id") or "")
            sales_trace = client.get(
                f"/api/agent/traces/{sales_trace_id}",
                headers=auth_headers(sales_token),
            )
            require(sales_trace.status_code == 200, f"SALES Agent trace unavailable: {sales_trace.text}")
            require(
                "DENIED" in trace_tool_statuses(sales_trace.json(), "enterprise_search"),
                f"Model-requested kb_hr was not denied for SALES: {sales_trace.json()}",
            )
            print("[OK] Agent model-requested SALES -> kb_hr is DENIED before evidence reaches LLM")
        finally:
            agent_module._ollama_chat = original_ollama_chat

        reset = client.post("/api/demo/reset", headers=auth_headers(admin_token), json={})
        require(reset.status_code == 200, f"Demo reset failed: {reset.text}")
        reset_status = reset.json().get("status", {})
        require(reset_status.get("ready_count") == 20, f"Demo reset did not restore 20/20: {reset_status}")
        print("[OK] Demo reset deletes and re-indexes bundled corpus")

    print("\nQdrant integration smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
