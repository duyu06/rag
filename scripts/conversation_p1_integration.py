from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def main() -> int:
    from qdrant_integration import install_ci_stubs, wait_for_qdrant

    wait_for_qdrant()
    db_path = ROOT / ".conversation-p1-ci.db"
    db_path.unlink(missing_ok=True)
    os.environ.update(
        QDRANT_URL="http://127.0.0.1:6333",
        QDRANT_COLLECTION="yaoke_ci",
        DEMO_DATA_DIR=str((ROOT / "demo-data").resolve()),
        OLLAMA_BASE_URL="http://127.0.0.1:1",
        OLLAMA_MODEL="ornith-1.5:9b",
        WEB_SEARCH_ENABLED="false",
        JWT_SECRET="yaoke-ci-integration-secret-at-least-32-bytes",
        CONVERSATION_DB_PATH=str(db_path),
        AGENT_HISTORY_MAX_MESSAGES="8",
        AGENT_LOCAL_FAST_PATH="true",
    )
    install_ci_stubs()
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))

    from fastapi.testclient import TestClient
    import app.agent as agent_module
    from app.main_agent import app

    def fake_chat(messages: list[dict], tools: list[dict]) -> dict:
        if not tools and any(
            "AUTHORIZED_ENTERPRISE_EVIDENCE=" in str(m.get("content") or "")
            for m in messages
            if m.get("role") == "system"
        ):
            return {"role": "assistant", "content": "已根据授权企业资料回答。[1]"}
        return {"role": "assistant", "content": "CI direct answer"}

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        require(login.status_code == 200, login.text)
        token = str(login.json()["access_token"])

        status = client.get("/api/demo/status", headers=headers(token))
        require(status.status_code == 200, status.text)
        if not status.json().get("ready"):
            init = client.post("/api/demo/initialize", headers=headers(token), json={})
            require(init.status_code == 200, init.text)

        created = client.post(
            "/api/conversations",
            headers=headers(token),
            json={"mode": "local", "knowledge_base_id": "kb_product"},
        )
        require(created.status_code == 201, created.text)
        conversation_id = str(created.json()["id"])

        original = agent_module._ollama_chat
        agent_module._ollama_chat = fake_chat
        try:
            first = client.post(
                f"/api/conversations/{conversation_id}/messages",
                headers=headers(token),
                json={"content": "X100 的标准整机质保多久？", "mode": "local", "knowledge_base_id": "kb_product"},
            )
            require(first.status_code == 200, first.text)
            first_data = first.json()
            require(first_data.get("context_messages") == 0, str(first_data))
            timings = first_data.get("timings") or {}
            require(timings.get("fast_path") is True, str(timings))
            require(timings.get("llm_calls") == 1, str(timings))
            require("[1]" in str(first_data["message"].get("content") or ""), str(first_data))

            second = client.post(
                f"/api/conversations/{conversation_id}/messages",
                headers=headers(token),
                json={"content": "那 X200 呢？", "mode": "local", "knowledge_base_id": "kb_product"},
            )
            require(second.status_code == 200, second.text)
            second_data = second.json()
            require(second_data.get("context_messages") == 2, str(second_data))
            require((second_data.get("timings") or {}).get("llm_calls") == 1, str(second_data))
        finally:
            agent_module._ollama_chat = original

        trace_id = str(second_data.get("trace_id") or "")
        trace = client.get(f"/api/agent/traces/{trace_id}", headers=headers(token))
        require(trace.status_code == 200, trace.text)
        trace_data = trace.json()
        fast_events = [e for e in trace_data.get("events", []) if e.get("type") == "fast_path"]
        require(bool(fast_events), str(trace_data))
        require(fast_events[0].get("contextual_retrieval_query") is True, str(fast_events))
        require((trace_data.get("timings") or {}).get("llm_calls") == 1, str(trace_data))
        require(len(second_data["conversation"]["messages"]) == 4, str(second_data))

        print("[OK] local fast path uses one LLM synthesis call")
        print("[OK] second turn receives prior user+assistant context")
        print("[OK] short follow-up retrieval is contextualized without another LLM")
        print("[OK] fast-path timings are present in Agent Trace")

    db_path.unlink(missing_ok=True)
    print("Conversation P1 integration: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
