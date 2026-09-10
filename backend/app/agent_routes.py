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
from app.auth import CurrentUser, require_user
from app.conversation_agent import run_conversation_agent
from app.knowledge import allowed_ids
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
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/tools")
def list_tools(
    mode: AgentMode = Query(default="auto"),
    user: CurrentUser = Depends(require_user),
):
    return {
        "mode": mode,
        "tools": tool_registry.describe(mode),
        "allowed_knowledge_base_ids": allowed_ids(user.role),
    }


@router.post("/agent/query")
def agent_query(request: AgentQueryRequest, user: CurrentUser = Depends(require_user)):
    try:
        return run_agent(
            question=request.question,
            user=user,
            mode=request.mode,
            knowledge_base_id=request.knowledge_base_id,
            top_k=request.top_k,
            rerank=request.rerank,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent 服务不可用：{type(exc).__name__}: {exc}") from exc


@router.post("/agent/query/stream")
def agent_query_stream(request: AgentQueryRequest, user: CurrentUser = Depends(require_user)):
    events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

    def token_sink(text: str) -> None:
        if text:
            events.put(("token", {"text": text}))

    def worker() -> None:
        try:
            result = run_conversation_agent(
                question=request.question,
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
                        "timings": result.get("timings"),
                    },
                )
            )
        except ValueError as exc:
            events.put(("error", {"detail": str(exc), "status": 400}))
        except Exception as exc:
            events.put(
                (
                    "error",
                    {
                        "detail": f"Agent 服务不可用：{type(exc).__name__}: {exc}",
                        "status": 503,
                    },
                )
            )
        finally:
            events.put(None)

    def event_stream():
        yield _sse("start", {"mode": request.mode})
        threading.Thread(target=worker, name="yaoke-agent-stream", daemon=True).start()
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


@router.get("/agent/traces/{trace_id}")
def agent_trace(trace_id: str, user: CurrentUser = Depends(require_user)):
    trace = get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace 不存在")
    if trace.get("username") != user.username and user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="无权查看该 Trace")
    return trace
