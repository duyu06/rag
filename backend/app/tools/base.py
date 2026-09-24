from __future__ import annotations

from dataclasses import dataclass, field
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
    # 知识范围白名单：由调用方（agent 入口）解析一次后注入，工具层不再自行按 role 判库。
    # **必填**：忘传就是 TypeError，而不是静默退化成"按本地 role 放行"（那对提权是漏放、
    # 对收窄是漏收）。语义与 app.knowledge.effective_allowed_from_grant 一致：
    # `None` = 本请求没有有效授予（显式声明走本地 role）；`[]` = 零可见，检索必须命中零行。
    # kw_only 保证它只能按关键字写出，同时不打扰既有字段的位置参数顺序。
    allowed_knowledge_base_ids: list[str] | None = field(kw_only=True)


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
