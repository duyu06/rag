from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser, require_permissions
from app.conversation_agent import run_conversation_agent
from app.conversation_routes import (
    ConversationMessageRequest,
    ConversationRetryRequest,
    _recent_completed_history,
    _retry_target,
    _load_conversation_for_user,
    _selected_kb,
    _success_payload,
    _validate_knowledge_base_scope,
)
from app.conversation_store import conversation_store
from app.llm.fallback import StreamInterrupted
from app.security import public_exception_detail, redact_secrets, redact_text

router = APIRouter(prefix="/api/conversations", tags=["conversation-stream"])


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(redact_secrets(payload), ensure_ascii=False)}\n\n"


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
        generating = False

        def token_sink(text: str) -> None:
            nonlocal generating
            if text:
                if not generating:
                    generating = True
                    events.put(("status", {"phase": "generating", "message": "正在生成回答"}))
                events.put(("token", {"text": text}))

        try:
            events.put(("status", {"phase": "retrieving", "message": "正在检索授权知识"}))
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
            detail = redact_text(exc)
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
        except StreamInterrupted as exc:
            # Model Router V2.3 D5（DESIGN §7）：**commit 之后** provider 断流时禁止换模型
            # ——用户已经看到了一段字，再跑一次另一个模型等于把两段接在一起。收口因此只用
            # **现行事件词汇表**里的 `error` + `done`，payload 上**只加两枚增量字段**：
            # `stream_committed: true`（「这次中断发生在交付之后」）与 `error_type`
            # （provider 侧的原始归类，机器码）。不新增事件类型、不改既有字段。
            # 顺序事实：账本行与 `model_route` trace 已在 `conversation_agent` 里落完，
            # 这里的 payload 是**给用户**的，不是给观测面的（`stream_committed` 属 SSE，
            # 刻意不进 trace——§8.1 第 4 条）。
            detail = f"Agent 服务不可用：{public_exception_detail(exc)}"
            assistant_message = conversation_store.replace_message(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                username=user.username,
                content=detail,
                status="failed",
                trace_id=None,
                latency_ms=(time.perf_counter() - started) * 1000,
                sources=[],
            )
            events.put(("error", {
                "detail": detail,
                "status": 503,
                "stream_committed": True,
                "error_type": exc.error_type,
            }))
            events.put(("done", {
                "message_id": assistant_message_id,
                "message": assistant_message,
                "status": "failed",
                "stream_committed": True,
                "error_type": exc.error_type,
            }))
        except Exception as exc:
            detail = f"Agent 服务不可用：{public_exception_detail(exc)}"
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
        yield _sse("status", {"phase": "authorizing", "message": "权限校验完成"})
        yield _sse("message", {"message_id": assistant_message_id, "status": "generating"})
        threading.Thread(target=worker, name=f"yaoke-stream-{assistant_message_id[:8]}", daemon=True).start()
        while True:
            try:
                item = events.get(timeout=10.0)
            except queue.Empty:
                yield _sse("heartbeat", {"phase": "working"})
                continue
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
    user: CurrentUser = Depends(
        require_permissions("conversation:write", "agent:run", "knowledge:query")
    ),
):
    conversation = _load_conversation_for_user(conversation_id, user)

    mode = request.mode or conversation.get("mode") or "auto"
    selected_kb = _selected_kb(request, conversation)
    _validate_knowledge_base_scope(user, selected_kb)
    history = _recent_completed_history(conversation)
    question = redact_text(request.content.strip())

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
    user: CurrentUser = Depends(
        require_permissions("conversation:write", "agent:run", "knowledge:query")
    ),
):
    conversation = _load_conversation_for_user(conversation_id, user)

    _target, question, history = _retry_target(conversation, message_id)
    mode = request.mode or conversation.get("mode") or "auto"
    selected_kb = _selected_kb(request, conversation)
    _validate_knowledge_base_scope(user, selected_kb)
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
