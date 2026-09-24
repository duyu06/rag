from __future__ import annotations

import json
import queue
import threading
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import run_agent
from app.agent_trace import get_trace
from app.auth import CurrentUser, has_permission, require_permission, require_permissions
from app.conversation_agent import run_conversation_agent
from app.conversation_routes import _validate_knowledge_base_scope
from app.knowledge import allowed_for
from app.llm.fallback import StreamInterrupted  # D5：post-commit 中断在 SSE 出口上的专用分支（见 `agent_query_stream`）
from app.security import public_exception_detail, public_timings, redact_secrets, redact_text
from app.tools.registry import tool_registry

router = APIRouter(prefix="/api", tags=["agent"])
AgentMode = Literal["local", "auto", "web"]


class AgentQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    mode: AgentMode = "auto"
    knowledge_base_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    rerank: bool = False


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(redact_secrets(payload), ensure_ascii=False)}\n\n"


@router.get("/tools")
def list_tools(
    mode: AgentMode = Query(default="auto"),
    user: CurrentUser = Depends(require_permission("agent:run")),
):
    return {
        "mode": mode,
        "tools": tool_registry.describe(mode),
        "allowed_knowledge_base_ids": allowed_for(user),
    }


@router.post("/agent/query")
def agent_query(
    request: AgentQueryRequest,
    user: CurrentUser = Depends(require_permissions("agent:run", "knowledge:query")),
):
    _validate_knowledge_base_scope(user, request.knowledge_base_id)
    try:
        return run_agent(
            question=redact_text(request.question),
            user=user,
            mode=request.mode,
            knowledge_base_id=request.knowledge_base_id,
            top_k=request.top_k,
            rerank=request.rerank,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_text(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent 服务不可用：{public_exception_detail(exc)}") from exc


@router.post("/agent/query/stream")
def agent_query_stream(
    request: AgentQueryRequest,
    user: CurrentUser = Depends(require_permissions("agent:run", "knowledge:query")),
):
    _validate_knowledge_base_scope(user, request.knowledge_base_id)
    events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
    generating = False

    def token_sink(text: str) -> None:
        nonlocal generating
        if text:
            if not generating:
                generating = True
                events.put(("status", {"phase": "generating", "message": "正在生成回答"}))
            events.put(("token", {"text": text}))

    def worker() -> None:
        try:
            events.put(("status", {"phase": "retrieving", "message": "正在检索授权知识"}))
            result = run_conversation_agent(
                question=redact_text(request.question),
                user=user,
                mode=request.mode,
                knowledge_base_id=request.knowledge_base_id,
                top_k=request.top_k,
                rerank=request.rerank,
                history=None,
                token_sink=token_sink,
            )
            if result.get("trace_id"):
                events.put(("trace", {"trace_id": str(result["trace_id"]), "mode": result.get("mode")}))
            events.put(("sources", {"sources": list(result.get("sources") or [])}))
            events.put(
                (
                    "done",
                    {
                        "finish_reason": "stop",
                        "trace_id": result.get("trace_id"),
                        "timings": public_timings(result.get("timings")),
                    },
                )
            )
        except ValueError as exc:
            events.put(("error", {"detail": redact_text(exc), "status": 400}))
        except StreamInterrupted as exc:
            # Model Router V2.3 D5（DESIGN §7 / Task 7 独立评审 I-4）：这一支与
            # `conversation_stream_routes.py` 的同名分支**同形**——commit 之后 provider 断流
            # 时禁止换模型，收口只用**现行事件词汇表**里的 `error` + `done`，payload 上只加
            # 两枚增量字段 `stream_committed` / `error_type`：不新增事件类型、不改前端契约
            # （`frontend/src/lib/api.ts::queryStream` 只读事件名与 `error.detail`）。
            # 为什么这一支在这里也必须存在：本路由同样传了 `token_sink`（见下方 worker）⇒
            # 同一条流式腿、同一种 post-commit 中断；少了它这条出口就退化成「error-only、
            # 无 `done`、无 `stream_committed`」，D5 的 payload 增量只落在一支 SSE 上。
            events.put(("error", {
                "detail": f"Agent 服务不可用：{public_exception_detail(exc)}",
                "status": 503,
                "stream_committed": True,
                "error_type": exc.error_type,
            }))
            events.put(("done", {
                # 会话面字段（`message_id` / `message`）在本端点不存在：它不落会话库。
                "status": "failed",
                "stream_committed": True,
                "error_type": exc.error_type,
            }))
        except Exception as exc:
            events.put(
                (
                    "error",
                    {
                        "detail": f"Agent 服务不可用：{public_exception_detail(exc)}",
                        "status": 503,
                    },
                )
            )
        finally:
            events.put(None)

    def event_stream():
        yield _sse("start", {"mode": request.mode})
        yield _sse("status", {"phase": "authorizing", "message": "权限校验完成"})
        threading.Thread(target=worker, name="yaoke-agent-stream", daemon=True).start()
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


@router.get("/agent/traces/{trace_id}")
def agent_trace(
    trace_id: str,
    user: CurrentUser = Depends(require_permission("trace:read")),
):
    trace = get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace 不存在")
    if trace.get("username") != user.username and not has_permission(user, "trace:read:any"):
        raise HTTPException(status_code=403, detail="无权查看该 Trace")
    return trace
