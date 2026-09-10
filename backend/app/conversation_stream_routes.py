from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser, require_user
from app.conversation_agent import run_conversation_agent
from app.conversation_routes import (
    ConversationMessageRequest,
    ConversationRetryRequest,
    _recent_completed_history,
    _retry_target,
    _selected_kb,
    _success_payload,
    _translate_store_error,
)
from app.conversation_store import conversation_store

router = APIRouter(prefix="/api/conversations", tags=["conversation-stream"])


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_response(
    *,
    conversation_id: str,
    assistant_message_id: str,
    question: str,
    history: list[dict[str, Any]],
    mode: str,
    knowledge_base_id: str | None,
    top_k: int,
    rerank: bool,
    user: CurrentUser,
) -> StreamingResponse:
    events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

    def worker() -> None:
        started = time.perf_counter()

        def token_sink(text: str) -> None:
            if text:
                events.put(("token", {"text": text}))

        try:
            result = run_conversation_agent(
                question=question,
                user=user,
                mode=mode,
                knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                rerank=rerank,
                history=history,
                token_sink=token_sink,
            )
            assistant_message = conversation_store.replace_message(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                username=user.username,
                content=str(result.get("answer") or ""),
                status="completed",
                trace_id=str(result.get("trace_id") or "") or None,
                latency_ms=(time.perf_counter() - started) * 1000,
                sources=list(result.get("sources") or []),
            )
            if result.get("trace_id"):
                events.put(("trace", {"trace_id": str(result["trace_id"])}))
            events.put(("sources", {"sources": list(result.get("sources") or [])}))
            events.put(
                (
                    "done",
                    _success_payload(
                        conversation_id=conversation_id,
                        user=user,
                        assistant_message=assistant_message,
                        result=result,
                        history_size=len(history),
                    ),
                )
            )
        except ValueError as exc:
            detail = str(exc)
            conversation_store.replace_message(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                username=user.username,
                content=detail,
                status="failed",
                trace_id=None,
                latency_ms=(time.perf_counter() - started) * 1000,
                sources=[],
            )
            events.put(("error", {"detail": detail, "status": 400}))
        except Exception as exc:
            detail = f"Agent 服务不可用：{type(exc).__name__}: {exc}"
            conversation_store.replace_message(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                username=user.username,
                content=detail,
                status="failed",
                trace_id=None,
                latency_ms=(time.perf_counter() - started) * 1000,
                sources=[],
            )
            events.put(("error", {"detail": detail, "status": 503}))
        finally:
            events.put(None)

    def event_stream():
        yield _sse("message", {"message_id": assistant_message_id, "status": "generating"})
        threading.Thread(target=worker, name=f"yaoke-stream-{assistant_message_id[:8]}", daemon=True).start()
        while True:
            item = events.get()
            if item is None:
                break
            event, payload = item
            yield _sse(event, payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{conversation_id}/messages/stream")
def create_message_stream(
    conversation_id: str,
    request: ConversationMessageRequest,
    user: CurrentUser = Depends(require_user),
):
    try:
        conversation = conversation_store.get(conversation_id, username=user.username)
    except (PermissionError, KeyError) as exc:
        raise _translate_store_error(exc) from exc

    mode = request.mode or conversation.get("mode") or "auto"
    selected_kb = _selected_kb(request, conversation)
    history = _recent_completed_history(conversation)
    question = request.content.strip()

    conversation_store.add_message(
        conversation_id=conversation_id,
        username=user.username,
        role="user",
        content=question,
        status="completed",
    )
    conversation_store.maybe_title_from_first_question(
        conversation_id,
        username=user.username,
        question=question,
    )
    conversation_store.update(
        conversation_id,
        username=user.username,
        mode=mode,
        knowledge_base_id=selected_kb,
    )
    assistant_message = conversation_store.add_message(
        conversation_id=conversation_id,
        username=user.username,
        role="assistant",
        content="",
        status="generating",
        sources=[],
    )

    return _stream_response(
        conversation_id=conversation_id,
        assistant_message_id=assistant_message["id"],
        question=question,
        history=history,
        mode=mode,
        knowledge_base_id=selected_kb,
        top_k=request.top_k,
        rerank=request.rerank,
        user=user,
    )


@router.post("/{conversation_id}/messages/{message_id}/retry/stream")
def retry_message_stream(
    conversation_id: str,
    message_id: str,
    request: ConversationRetryRequest,
    user: CurrentUser = Depends(require_user),
):
    try:
        conversation = conversation_store.get(conversation_id, username=user.username)
    except (PermissionError, KeyError) as exc:
        raise _translate_store_error(exc) from exc

    _target, question, history = _retry_target(conversation, message_id)
    mode = request.mode or conversation.get("mode") or "auto"
    selected_kb = _selected_kb(request, conversation)
    conversation_store.update(
        conversation_id,
        username=user.username,
        mode=mode,
        knowledge_base_id=selected_kb,
    )
    conversation_store.replace_message(
        conversation_id=conversation_id,
        message_id=message_id,
        username=user.username,
        content="",
        status="generating",
        trace_id=None,
        latency_ms=None,
        sources=[],
    )

    return _stream_response(
        conversation_id=conversation_id,
        assistant_message_id=message_id,
        question=question,
        history=history,
        mode=mode,
        knowledge_base_id=selected_kb,
        top_k=request.top_k,
        rerank=request.rerank,
        user=user,
    )
