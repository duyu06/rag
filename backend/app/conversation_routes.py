from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, require_user
from app.config import settings
from app.conversation_agent import run_conversation_agent
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


class ConversationRetryRequest(BaseModel):
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


def _recent_completed_history(conversation: dict) -> list[dict]:
    limit = max(0, int(settings.agent_history_max_messages))
    if limit == 0:
        return []
    messages = [
        item
        for item in conversation.get("messages", [])
        if item.get("role") in {"user", "assistant"}
        and item.get("status") == "completed"
        and str(item.get("content") or "").strip()
    ]
    return messages[-limit:]


def _selected_kb(request: BaseModel, conversation: dict) -> str | None:
    # Explicit JSON null means "all authorized KBs". If the field is omitted,
    # preserve the conversation's previously selected KB for backward compatibility.
    if "knowledge_base_id" in request.model_fields_set:
        return getattr(request, "knowledge_base_id", None)
    return conversation.get("knowledge_base_id")


def _retry_target(conversation: dict, message_id: str) -> tuple[dict, str, list[dict]]:
    messages = list(conversation.get("messages") or [])
    target_index = next(
        (index for index, item in enumerate(messages) if item.get("id") == message_id),
        -1,
    )
    if target_index < 0:
        raise HTTPException(status_code=404, detail="Message 不存在")

    target = messages[target_index]
    if target.get("role") != "assistant":
        raise HTTPException(status_code=409, detail="只能重试 assistant 消息")
    if target.get("status") != "failed":
        raise HTTPException(status_code=409, detail="只能重试 failed 消息")

    user_index = next(
        (
            index
            for index in range(target_index - 1, -1, -1)
            if messages[index].get("role") == "user"
            and messages[index].get("status") == "completed"
            and str(messages[index].get("content") or "").strip()
        ),
        -1,
    )
    if user_index < 0:
        raise HTTPException(status_code=409, detail="找不到该失败回答对应的用户问题")

    question = str(messages[user_index].get("content") or "").strip()
    history = _recent_completed_history({"messages": messages[:user_index]})
    return target, question, history


def _replace_failed_message(
    *,
    conversation_id: str,
    message_id: str,
    user: CurrentUser,
    detail: str,
    started: float,
) -> None:
    conversation_store.replace_message(
        conversation_id=conversation_id,
        message_id=message_id,
        username=user.username,
        content=detail,
        status="failed",
        trace_id=None,
        latency_ms=(time.perf_counter() - started) * 1000,
        sources=[],
    )


def _success_payload(
    *,
    conversation_id: str,
    user: CurrentUser,
    assistant_message: dict,
    result: dict,
    history_size: int,
) -> dict:
    return {
        "conversation": conversation_store.get(conversation_id, username=user.username),
        "message": assistant_message,
        "trace_id": result.get("trace_id"),
        "model_used": result.get("model_used"),
        "context_messages": result.get("context_messages", history_size),
        "timings": result.get("timings"),
    }


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
    selected_kb = _selected_kb(request, conversation)

    # Capture history before storing the current user turn so the current question
    # remains a separate final user message in the model input.
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

    started = time.perf_counter()
    try:
        result = run_conversation_agent(
            question=question,
            user=user,
            mode=mode,
            knowledge_base_id=selected_kb,
            top_k=request.top_k,
            rerank=request.rerank,
            history=history,
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
    return _success_payload(
        conversation_id=conversation_id,
        user=user,
        assistant_message=assistant_message,
        result=result,
        history_size=len(history),
    )


@router.post("/{conversation_id}/messages/{message_id}/retry")
def retry_message(
    conversation_id: str,
    message_id: str,
    request: ConversationRetryRequest,
    user: CurrentUser = Depends(require_user),
):
    """Retry one failed assistant turn without duplicating the user message."""
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

    started = time.perf_counter()
    try:
        result = run_conversation_agent(
            question=question,
            user=user,
            mode=mode,
            knowledge_base_id=selected_kb,
            top_k=request.top_k,
            rerank=request.rerank,
            history=history,
        )
    except ValueError as exc:
        _replace_failed_message(
            conversation_id=conversation_id,
            message_id=message_id,
            user=user,
            detail=str(exc),
            started=started,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        detail = f"Agent 服务不可用：{type(exc).__name__}: {exc}"
        _replace_failed_message(
            conversation_id=conversation_id,
            message_id=message_id,
            user=user,
            detail=detail,
            started=started,
        )
        raise HTTPException(status_code=503, detail=detail) from exc

    assistant_message = conversation_store.replace_message(
        conversation_id=conversation_id,
        message_id=message_id,
        username=user.username,
        content=str(result.get("answer") or ""),
        status="completed",
        trace_id=str(result.get("trace_id") or "") or None,
        latency_ms=(time.perf_counter() - started) * 1000,
        sources=list(result.get("sources") or []),
    )
    return _success_payload(
        conversation_id=conversation_id,
        user=user,
        assistant_message=assistant_message,
        result=result,
        history_size=len(history),
    )
