from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterator
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


def stream_request(
    method: str,
    path: str,
    body: dict,
    token: str,
    timeout: int = 300,
) -> Iterator[tuple[str, dict, float]]:
    """Yield parsed SSE frames with elapsed seconds from request start."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Authorization": f"Bearer {token}",
    }
    req = Request(API + path, data=data, headers=headers, method=method)
    started = time.perf_counter()

    with urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise AssertionError(f"stream HTTP status={response.status}")

        event_name = ""
        data_lines: list[str] = []

        def emit() -> tuple[str, dict, float] | None:
            nonlocal event_name, data_lines
            if not event_name and not data_lines:
                return None
            raw = "\n".join(data_lines).strip()
            name = event_name or "message"
            event_name = ""
            data_lines = []
            if not raw:
                return None
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"invalid SSE JSON for event={name}: {raw[:200]}") from exc
            if not isinstance(payload, dict):
                raise AssertionError(f"SSE payload must be object: event={name}")
            return name, payload, time.perf_counter() - started

        while True:
            raw_line = response.readline()
            if not raw_line:
                pending = emit()
                if pending:
                    yield pending
                break

            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                frame = emit()
                if frame:
                    yield frame
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())


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


def verify_real_stream(
    *,
    conversation_id: str,
    token: str,
    min_token_events: int,
    max_ttft: float,
) -> None:
    message_id = ""
    trace_id = ""
    token_chunks: list[str] = []
    sources: list[dict] = []
    done_payload: dict | None = None
    first_token_seconds: float | None = None
    done_seconds: float | None = None

    for event, payload, elapsed in stream_request(
        "POST",
        f"/conversations/{conversation_id}/messages/stream",
        {
            "content": "X200 能在零下 20 度工作吗？",
            "mode": "local",
            "knowledge_base_id": "kb_product",
            "top_k": 5,
            "rerank": False,
        },
        token,
    ):
        if event == "message":
            message_id = str(payload.get("message_id") or "")
            require(payload.get("status") == "generating", f"unexpected initial message event: {payload}")
        elif event == "token":
            text = str(payload.get("text") or "")
            if text:
                if first_token_seconds is None:
                    first_token_seconds = elapsed
                token_chunks.append(text)
        elif event == "sources":
            sources = list(payload.get("sources") or [])
        elif event == "trace":
            trace_id = str(payload.get("trace_id") or "")
        elif event == "error":
            raise AssertionError(f"stream worker failed: {payload}")
        elif event == "done":
            done_payload = payload
            done_seconds = elapsed

    require(bool(message_id), "stream did not emit persisted assistant message id")
    require(first_token_seconds is not None, "stream emitted no visible token event")
    require(len(token_chunks) >= min_token_events, f"expected >= {min_token_events} token events, got {len(token_chunks)}")
    require(done_payload is not None and done_seconds is not None, "stream ended without done payload")
    require(first_token_seconds < done_seconds, "first token was not observed before stream completion")
    if max_ttft > 0:
        require(
            first_token_seconds <= max_ttft,
            f"TTFT {first_token_seconds:.2f}s exceeded configured limit {max_ttft:.2f}s",
        )

    message = dict(done_payload.get("message") or {})
    timings = dict(done_payload.get("timings") or {})
    require(message.get("id") == message_id, f"assistant id changed during stream: {message_id} -> {message.get('id')}")
    require(message.get("status") == "completed", f"assistant not completed: {message}")
    require(bool(message.get("trace_id")), f"trace_id missing: {message}")
    require(bool(message.get("sources")), f"Citation missing from completed message: {message}")
    require(bool(sources), "SSE sources event missing")
    require(timings.get("fast_path") is True, f"Local Fast Path missing: {timings}")
    require(timings.get("native_stream") is True, f"native_stream flag missing: {timings}")
    require(timings.get("llm_calls") == 1, f"expected one Ornith synthesis call: {timings}")

    streamed_text = "".join(token_chunks).strip()
    persisted_text = str(message.get("content") or "").strip()
    require(streamed_text == persisted_text, "streamed text differs from persisted assistant answer")

    if trace_id:
        require(trace_id == str(message.get("trace_id")), f"trace event/message mismatch: {trace_id} vs {message.get('trace_id')}")
    else:
        trace_id = str(message.get("trace_id"))

    status, restored = request("GET", f"/conversations/{conversation_id}", token=token)
    require(status == 200 and restored, f"conversation restore after stream failed: {status} {restored}")
    restored_message = next(
        (item for item in list(restored.get("messages") or []) if str(item.get("id")) == message_id),
        None,
    )
    require(restored_message is not None, "streamed assistant message missing after conversation reload")
    require(restored_message.get("status") == "completed", f"restored assistant not completed: {restored_message}")
    require(str(restored_message.get("content") or "").strip() == persisted_text, "restored content differs from streamed answer")
    require(bool(restored_message.get("sources")), "restored Citation rows missing")

    status, trace = request("GET", f"/agent/traces/{trace_id}", token=token)
    require(status == 200 and trace and trace.get("trace_id") == trace_id, f"Trace load failed: {trace}")
    trace_timings = dict(trace.get("timings") or {})
    require(trace_timings.get("native_stream") is True, f"Trace does not record native streaming: {trace_timings}")

    print(
        "[OK] P1.7 native SSE stream "
        f"tokens={len(token_chunks)} TTFT={first_token_seconds:.2f}s total={done_seconds:.2f}s "
        f"message_id={message_id[:8]}..."
    )
    print("[OK] streamed answer == persisted answer; Citation + Trace survive conversation reload")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="yaoke deployment smoke: API/Auth/RBAC/SQLite by default; --agent adds real Ornith QA; --stream verifies P1.7 native SSE",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="also run a real Local Fast Path conversation against Ornith/Qdrant",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="verify P1.7 local native streaming, Citation/Trace and post-stream persistence (implies --agent)",
    )
    parser.add_argument(
        "--min-token-events",
        type=int,
        default=2,
        help="minimum non-empty SSE token events required by --stream (default: 2)",
    )
    parser.add_argument(
        "--max-ttft",
        type=float,
        default=0.0,
        help="optional hard Time-To-First-Token limit in seconds; 0 disables the hardware SLA gate",
    )
    args = parser.parse_args()
    if args.stream:
        args.agent = True
    require(args.min_token_events >= 1, "--min-token-events must be >= 1")
    require(args.max_ttft >= 0, "--max-ttft must be >= 0")

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

            if args.stream:
                verify_real_stream(
                    conversation_id=temporary_conversation,
                    token=token,
                    min_token_events=args.min_token_events,
                    max_ttft=args.max_ttft,
                )
            else:
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
        elif not args.stream:
            print("Next: python scripts/release_smoke.py --stream")
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
