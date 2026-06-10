"""
ToolRegistry — maps tool names to BaseTool instances.

Usage:
    registry = ToolRegistry()
    registry.register(RememberTool(brain)).register(RecordEpisodeTool(brain, agent_id))

    # Pass definitions to the runner
    runner.run(..., tools=registry.definitions())

    # Dispatch after tool_use response
    tool = registry.get("remember")
    result = tool.run(tool_input)

The registry is optional — AgentLoop accepts a plain list[BaseTool] and builds
its own dict internally. The registry is useful when you want to share a set of
tools across multiple loops or build the list dynamically.
"""

from __future__ import annotations

from tools.base import BaseTool


class ToolRegistry:
    """Lightweight container for BaseTool instances."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> "ToolRegistry":
        """Register a tool. Returns self for chaining."""
        self._tools[tool.id] = tool
        return self

    def get(self, tool_id: str) -> BaseTool | None:
        return self._tools.get(tool_id)

    def definitions(self) -> list[dict]:
        """Return Anthropic tool-use schemas for all registered tools."""
        return [t.definition for t in self._tools.values()]

    def all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def __repr__(self) -> str:
        return f"ToolRegistry({list(self._tools)})"
