from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

AgentMode = Literal["local", "auto", "web"]


@dataclass(frozen=True)
class ToolContext:
    username: str
    role: str
    mode: AgentMode
    trace_id: str
    selected_knowledge_base_id: str | None = None
    top_k: int = 5
    rerank: bool = False


class ToolExecutionError(RuntimeError):
    def __init__(self, message: str, *, status: str = "FAILED") -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    executor: Callable[[dict[str, Any], ToolContext], dict[str, Any]]
    modes: frozenset[AgentMode]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
