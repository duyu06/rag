from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from app.config import settings


def ollama_chat_stream(messages: list[dict[str, Any]]) -> Iterator[str]:
    """Yield visible synthesis text from Ollama's native NDJSON stream.

    This helper is intentionally used only for final synthesis turns where tools
    are disabled. Tool-routing turns remain buffered so partial tool-call JSON is
    never exposed to the client. A stream is successful only after Ollama emits
    `done: true`; otherwise the caller must persist the turn as failed rather than
    accepting a truncated answer.
    """
    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "stream": True,
        "think": bool(settings.agent_think_synthesis),
        "keep_alive": settings.ollama_keep_alive,
        "messages": messages,
        "tools": [],
        "options": {
            "temperature": 0.2,
            "num_predict": int(settings.agent_num_predict_synthesis),
        },
    }

    finished = False
    with httpx.stream(
        "POST",
        settings.ollama_base_url.rstrip("/") + "/api/chat",
        json=payload,
        timeout=settings.agent_llm_timeout_seconds,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Ollama 流式响应不是合法 JSON") from exc

            if chunk.get("error"):
                raise RuntimeError(f"Ollama 流式生成失败：{chunk['error']}")

            message = chunk.get("message")
            if isinstance(message, dict):
                text = str(message.get("content") or "")
                if text:
                    yield text

            if chunk.get("done") is True:
                finished = True
                break

    if not finished:
        raise RuntimeError("Ollama 流式响应提前结束，未收到 done=true")
