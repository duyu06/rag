from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client, username: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    require(response.status_code == 200, f"login failed for {username}: {response.text}")
    return str(response.json()["access_token"])


def main() -> int:
    # Reuse deterministic CI-only model boundaries from the Qdrant integration test.
    from qdrant_integration import fake_ornith_chat, install_ci_stubs, wait_for_qdrant

    wait_for_qdrant()
    db_path = ROOT / ".conversation-ci.db"
    db_path.unlink(missing_ok=True)

    os.environ["QDRANT_URL"] = "http://127.0.0.1:6333"
    os.environ["QDRANT_COLLECTION"] = "yaoke_ci"
    os.environ["DEMO_DATA_DIR"] = str((ROOT / "demo-data").resolve())
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:1"
    os.environ["OLLAMA_MODEL"] = "ornith-1.5:9b"
    os.environ["WEB_SEARCH_ENABLED"] = "false"
    os.environ["JWT_SECRET"] = "yaoke-ci-integration-secret-at-least-32-bytes"
    os.environ["CONVERSATION_DB_PATH"] = str(db_path)

    install_ci_stubs()
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))

    from fastapi.testclient import TestClient
    import app.agent as agent_module
    from app.main_agent import app

    with TestClient(app) as client:
        admin_token = login(client, "admin", "admin123")
        sales_token = login(client, "sales01", "sales123")

        status_response = client.get("/api/demo/status", headers=auth_headers(admin_token))
        require(status_response.status_code == 200, status_response.text)
        if not status_response.json().get("ready"):
            init = client.post("/api/demo/initialize", headers=auth_headers(admin_token), json={})
            require(init.status_code == 200, f"demo initialize failed: {init.text}")

        create = client.post(
            "/api/conversations",
            headers={**auth_headers(admin_token), "Content-Type": "application/json"},
            json={"mode": "local", "knowledge_base_id": "kb_product"},
        )
        require(create.status_code == 201, f"create conversation failed: {create.text}")
        conversation_id = str(create.json()["id"])
        require(create.json()["messages"] == [], "new conversation should be empty")
        print("[OK] Conversation created in SQLite")

        original_ollama_chat = agent_module._ollama_chat
        agent_module._ollama_chat = fake_ornith_chat
        try:
            send = client.post(
                f"/api/conversations/{conversation_id}/messages",
                headers={**auth_headers(admin_token), "Content-Type": "application/json"},
                json={
                    "content": "X100 的标准整机质保多久？",
                    "mode": "local",
                    "knowledge_base_id": "kb_product",
                    "top_k": 5,
                    "rerank": False,
                },
            )
        finally:
            agent_module._ollama_chat = original_ollama_chat

        require(send.status_code == 200, f"conversation message failed: {send.text}")
        detail = send.json()["conversation"]
        require(len(detail["messages"]) == 2, f"expected user+assistant messages: {detail}")
        require(detail["title"] != "新会话", "first question did not create a title")
        assistant = detail["messages"][1]
        require(assistant["role"] == "assistant", "second message is not assistant")
        require(assistant["status"] == "completed", "assistant message not completed")
        require(bool(assistant["trace_id"]), "assistant trace_id missing")
        require(bool(assistant["sources"]), "assistant citation sources missing")
        require(assistant["sources"][0]["knowledge_base_id"] == "kb_product", "wrong citation KB")
        require(assistant["sources"][0]["citation_index"] == 1, "citation index was not persisted")
        print("[OK] Agent -> real Qdrant -> Citation persisted with assistant message")

        # A fresh GET is the server-side equivalent of browser refresh/reopen.
        restored = client.get(
            f"/api/conversations/{conversation_id}",
            headers=auth_headers(admin_token),
        )
        require(restored.status_code == 200, restored.text)
        restored_data = restored.json()
        require(len(restored_data["messages"]) == 2, "persisted messages were not restored")
        require(bool(restored_data["messages"][1]["sources"]), "persisted sources were not restored")
        print("[OK] Conversation restored from SQLite after a fresh API request")

        listing = client.get("/api/conversations", headers=auth_headers(admin_token))
        require(listing.status_code == 200, listing.text)
        ids = {str(item["id"]) for item in listing.json().get("conversations", [])}
        require(conversation_id in ids, "conversation missing from history list")

        denied = client.get(
            f"/api/conversations/{conversation_id}",
            headers=auth_headers(sales_token),
        )
        require(denied.status_code == 403, f"SALES should not read ADMIN conversation: {denied.status_code}")
        print("[OK] Conversation ownership blocks cross-user reads")

        rename = client.patch(
            f"/api/conversations/{conversation_id}",
            headers={**auth_headers(admin_token), "Content-Type": "application/json"},
            json={"title": "X100 质保咨询"},
        )
        require(rename.status_code == 200 and rename.json()["title"] == "X100 质保咨询", "rename failed")

        delete = client.delete(
            f"/api/conversations/{conversation_id}",
            headers=auth_headers(admin_token),
        )
        require(delete.status_code == 204, f"delete failed: {delete.status_code} {delete.text}")
        missing = client.get(
            f"/api/conversations/{conversation_id}",
            headers=auth_headers(admin_token),
        )
        require(missing.status_code == 404, "deleted conversation still accessible")
        print("[OK] Rename/delete lifecycle")

    db_path.unlink(missing_ok=True)
    print("\nConversation integration smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
