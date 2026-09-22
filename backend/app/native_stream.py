from __future__ import annotations

from typing import Any, Iterator

from app.config import settings
from app.llm_router import RouteContext, routed_stream_chat


def ollama_chat_stream(
    messages: list[dict[str, Any]],
    *,
    sensitivity: str = "public",
) -> Iterator[str]:
    """Compatibility wrapper around the enterprise streaming model router."""
    yield from routed_stream_chat(
        messages,
        temperature=0.2,
        max_tokens=int(settings.agent_num_predict_synthesis),
        think=bool(settings.agent_think_synthesis),
        context=RouteContext(
            sensitivity=sensitivity,
            requires_tools=False,
            requires_reasoning=bool(settings.agent_think_synthesis),
            mode="conversation",
        ),
    )
