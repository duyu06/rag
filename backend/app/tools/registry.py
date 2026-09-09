from __future__ import annotations

from typing import Any

from app.tools.base import AgentMode, ToolContext, ToolDefinition, ToolExecutionError
from app.tools.enterprise_search import execute_enterprise_search
from app.tools.web_search_tool import execute_web_search

ENTERPRISE_SEARCH = ToolDefinition(
    name="enterprise_search",
    description=(
        "Search authorized enterprise knowledge bases for internal policies, HR rules, product documentation, "
        "sales rules, after-sales SOPs, exact internal amounts, dates, parameters or procedures. "
        "Authorization is enforced by the backend; never infer access from the prompt."
    ),
    parameters={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "The enterprise knowledge query."},
            "knowledge_base_id": {
                "type": ["string", "null"],
                "description": "Optional KB id. Omit to search all KBs the current role may access.",
            },
            "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        },
        "additionalProperties": False,
    },
    executor=execute_enterprise_search,
    modes=frozenset({"local", "auto", "web"}),
)

WEB_SEARCH = ToolDefinition(
    name="web_search",
    description=(
        "Search the public internet for current or external information such as recent news, public releases, "
        "industry trends and facts that are not internal company policy. Do not use for confidential internal data."
    ),
    parameters={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "A public web search query without secrets."},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        },
        "additionalProperties": False,
    },
    executor=execute_web_search,
    modes=frozenset({"auto", "web"}),
)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools = {item.name: item for item in (ENTERPRISE_SEARCH, WEB_SEARCH)}

    def definitions(self, mode: AgentMode = "auto") -> list[ToolDefinition]:
        return [item for item in self._tools.values() if mode in item.modes]

    def schemas(self, mode: AgentMode = "auto") -> list[dict[str, Any]]:
        return [item.schema() for item in self.definitions(mode)]

    def describe(self, mode: AgentMode = "auto") -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "parameters": item.parameters,
                "modes": sorted(item.modes),
            }
            for item in self.definitions(mode)
        ]

    def execute(self, name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            raise ToolExecutionError(f"未知工具：{name}")
        if context.mode not in tool.modes:
            raise ToolExecutionError(f"{context.mode} 模式禁止调用 {name}", status="DENIED")
        return tool.executor(arguments, context)


tool_registry = ToolRegistry()
