from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = os.environ.get("YAOKE_API", "http://localhost:8001/api").rstrip("/")


def request(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> tuple[int, dict | None]:
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(API + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def login() -> str:
    status, payload = request(
        "POST",
        "/auth/login",
        {"username": "admin", "password": "admin123"},
    )
    require(status == 200 and isinstance(payload, dict), f"admin login failed: {status} {payload}")
    return str(payload["access_token"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="yaoke deployment smoke: API/Auth/RBAC/SQLite by default; --agent adds real Ornith + Qdrant QA",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="also run a real Local Fast Path conversation against Ornith/Qdrant",
    )
    args = parser.parse_args()

    temporary_conversation = ""
    token = ""
    try:
        status, health = request("GET", "/health")
        require(status == 200 and isinstance(health, dict), f"health failed: {status} {health}")
        require(bool(health.get("vector_db_connected")), f"Qdrant not connected: {health}")
        print(f"[OK] API reachable; Qdrant connected; health={health.get('status')}")
        if not health.get("llm_connected"):
            print(f"[WARN] Ornith runtime is not ready: {health.get('llm_detail')}")

        token = login()
        status, me = request("GET", "/auth/me", token=token)
        require(status == 200 and me and me.get("role") == "ADMIN", f"auth/me failed: {status} {me}")
        print("[OK] JWT login + /auth/me")

        status, bases = request("GET", "/knowledge-bases", token=token)
        visible = list((bases or {}).get("knowledge_bases") or [])
        require(status == 200 and len(visible) >= 5, f"knowledge bases incomplete: {status} {bases}")
        print(f"[OK] ADMIN knowledge scope: {len(visible)} KBs")

        for mode, expected in {
            "local": {"enterprise_search"},
            "auto": {"enterprise_search", "web_search"},
            "web": {"enterprise_search", "web_search"},
        }.items():
            status, payload = request("GET", f"/tools?mode={mode}", token=token)
            names = {str(item.get("name")) for item in (payload or {}).get("tools", [])}
            require(status == 200 and names == expected, f"{mode} tools mismatch: {names}")
        print("[OK] Tool Registry modes")

        status, created = request(
            "POST",
            "/conversations",
            {"title": "release-smoke-temp", "mode": "local", "knowledge_base_id": "kb_product"},
            token=token,
        )
        require(status == 201 and created and created.get("id"), f"conversation create failed: {status} {created}")
        temporary_conversation = str(created["id"])

        status, restored = request("GET", f"/conversations/{temporary_conversation}", token=token)
        require(status == 200 and restored and restored.get("id") == temporary_conversation, "conversation restore failed")
        print("[OK] SQLite conversation create + restore")

        if args.agent:
            status, demo = request("GET", "/demo/status", token=token)
            require(status == 200 and demo and demo.get("ready"), f"Demo corpus not ready: {demo}")
            require(
                int(demo.get("ready_count", 0) or 0) == int(demo.get("total", 0) or 0) > 0,
                f"Demo corpus incomplete: {demo}",
            )
            print(f"[OK] Demo corpus ready: {demo.get('ready_count')}/{demo.get('total')}")

            status, answer = request(
                "POST",
                f"/conversations/{temporary_conversation}/messages",
                {
                    "content": "X100 的标准整机质保多久？",
                    "mode": "local",
                    "knowledge_base_id": "kb_product",
                    "top_k": 5,
                    "rerank": False,
                },
                token=token,
                timeout=240,
            )
            require(status == 200 and answer, f"real Agent conversation failed: {status} {answer}")
            message = dict(answer.get("message") or {})
            timings = dict(answer.get("timings") or {})
            require(message.get("status") == "completed", f"assistant not completed: {message}")
            require(bool(message.get("trace_id")), f"trace_id missing: {message}")
            require(bool(message.get("sources")), f"Citation missing: {message}")
            require(timings.get("fast_path") is True, f"Local Fast Path missing: {timings}")
            require(timings.get("llm_calls") == 1, f"expected one Ornith synthesis call: {timings}")
            require("vector_ms" in timings and "bm25_ms" in timings and "llm_ms" in timings, f"timings incomplete: {timings}")
            print("[OK] real Ornith Local Fast Path -> Qdrant -> Citation -> timings")

            trace_id = str(message["trace_id"])
            status, trace = request("GET", f"/agent/traces/{trace_id}", token=token)
            require(status == 200 and trace and trace.get("trace_id") == trace_id, f"Trace load failed: {trace}")
            require(bool(trace.get("timings")), f"Trace timings missing: {trace}")
            print("[OK] Agent Trace persisted with performance breakdown")

        status, _ = request("DELETE", f"/conversations/{temporary_conversation}", token=token)
        require(status == 204, f"conversation cleanup failed: {status}")
        temporary_conversation = ""
        print("[OK] SQLite conversation cleanup")

        print("\nyaoke release smoke: PASS")
        if not args.agent:
            print("Next: python scripts/release_smoke.py --agent")
        return 0
    except (AssertionError, URLError, TimeoutError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    finally:
        if token and temporary_conversation:
            try:
                request("DELETE", f"/conversations/{temporary_conversation}", token=token)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
