from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.agent import run_agent
from app.auth import CurrentUser, require_user
from app.conversation_store import conversation_store

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
AgentMode = Literal["local", "auto", "web"]


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    mode: AgentMode = "auto"
    knowledge_base_id: str | None = None


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    mode: AgentMode | None = None
    knowledge_base_id: str | None = None
    update_knowledge_base: bool = False


class ConversationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    mode: AgentMode | None = None
    knowledge_base_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    rerank: bool = False


def _translate_store_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc).strip("'"))
    return HTTPException(status_code=500, detail=f"Conversation 存储失败：{type(exc).__name__}: {exc}")


@router.get("")
def list_conversations(
    limit: int = Query(default=100, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
):
    return {"conversations": conversation_store.list(user.username, limit=limit)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: ConversationCreateRequest,
    user: CurrentUser = Depends(require_user),
):
    return conversation_store.create(
        username=user.username,
        title=request.title or "新会话",
        mode=request.mode,
        knowledge_base_id=request.knowledge_base_id,
    )


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
):
    try:
        return conversation_store.get(conversation_id, username=user.username)
    except (PermissionError, KeyError) as exc:
        raise _translate_store_error(exc) from exc


@router.patch("/{conversation_id}")
def update_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
    user: CurrentUser = Depends(require_user),
):
    try:
        kwargs = {
            "username": user.username,
            "title": request.title,
            "mode": request.mode,
        }
        if request.update_knowledge_base:
            kwargs["knowledge_base_id"] = request.knowledge_base_id
        return conversation_store.update(conversation_id, **kwargs)
    except (PermissionError, KeyError) as exc:
        raise _translate_store_error(exc) from exc


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(require_user),
):
    try:
        conversation_store.delete(conversation_id, username=user.username)
    except (PermissionError, KeyError) as exc:
        raise _translate_store_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/messages")
def create_message(
    conversation_id: str,
    request: ConversationMessageRequest,
    user: CurrentUser = Depends(require_user),
):
    try:
        conversation = conversation_store.get(conversation_id, username=user.username)
    except (PermissionError, KeyError) as exc:
        raise _translate_store_error(exc) from exc

    mode = request.mode or conversation.get("mode") or "auto"
    selected_kb = request.knowledge_base_id
    if selected_kb is None:
        selected_kb = conversation.get("knowledge_base_id")

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

    started = time.perf_counter()
    try:
        result = run_agent(
            question=question,
            user=user,
            mode=mode,
            knowledge_base_id=selected_kb,
            top_k=request.top_k,
            rerank=request.rerank,
        )
    except ValueError as exc:
        conversation_store.add_message(
            conversation_id=conversation_id,
            username=user.username,
            role="assistant",
            content=str(exc),
            status="failed",
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        detail = f"Agent 服务不可用：{type(exc).__name__}: {exc}"
        conversation_store.add_message(
            conversation_id=conversation_id,
            username=user.username,
            role="assistant",
            content=detail,
            status="failed",
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        raise HTTPException(status_code=503, detail=detail) from exc

    assistant_message = conversation_store.add_message(
        conversation_id=conversation_id,
        username=user.username,
        role="assistant",
        content=str(result.get("answer") or ""),
        status="completed",
        trace_id=str(result.get("trace_id") or "") or None,
        latency_ms=(time.perf_counter() - started) * 1000,
        sources=list(result.get("sources") or []),
    )

    return {
        "conversation": conversation_store.get(conversation_id, username=user.username),
        "message": assistant_message,
        "trace_id": result.get("trace_id"),
        "model_used": result.get("model_used"),
    }
