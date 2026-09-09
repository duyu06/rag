from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import run_agent
from app.agent_trace import get_trace
from app.auth import CurrentUser, require_user
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
    try:
        result = run_agent(
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

    def event_stream():
        yield "event: trace\ndata: " + json.dumps({"trace_id": result["trace_id"], "mode": result["mode"]}, ensure_ascii=False) + "\n\n"
        yield "event: sources\ndata: " + json.dumps({"sources": result["sources"]}, ensure_ascii=False) + "\n\n"
        answer = str(result["answer"])
        for start in range(0, len(answer), 14):
            payload = json.dumps({"text": answer[start : start + 14]}, ensure_ascii=False)
            yield f"event: token\ndata: {payload}\n\n"
        yield "event: done\ndata: " + json.dumps({"finish_reason": "stop", "trace_id": result["trace_id"]}) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/agent/traces/{trace_id}")
def agent_trace(trace_id: str, user: CurrentUser = Depends(require_user)):
    trace = get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace 不存在")
    if trace.get("username") != user.username and user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="无权查看该 Trace")
    return trace
