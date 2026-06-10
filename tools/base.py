"""
BaseTool — the contract every tool implements.

A "tool" is something an agent can invoke during its loop. Examples in
this repo: `remember`, `record_episode`, `message_agent`. The base class
keeps the interface tiny so adding a new tool is mostly just writing the
`run()` body.

Design notes:
  - `definition()` returns the Anthropic tool schema. That's the format
    the API uses; if you swap LLM providers, adapt this layer.
  - `is_irreversible()` decides whether the tool needs HITL approval before
    running. Default: False. Override for git commits, deploys, etc.
  - `run()` does the work and returns a string. Stringly-typed by design —
    LLMs work in text, so even if your tool returns structured data, it
    gets JSON-serialised here.

The tool layer is intentionally agnostic of agent identity. If a tool
needs to know who's calling, it should accept `agent_id` as input.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Abstract base for agent tools."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Stable identifier — used in the tool registry and in tool_calls."""
        ...

    @property
    @abstractmethod
    def definition(self) -> dict[str, Any]:
        """Anthropic tool-use schema. See:
        https://docs.anthropic.com/en/docs/tool-use
        Minimum keys: name, description, input_schema."""
        ...

    @abstractmethod
    def run(self, tool_input: dict[str, Any]) -> str:
        """Execute the tool and return a stringified result.

        Raise on bad input. Wrap recoverable failures in the response string
        (e.g. "[error] description") so the agent can see and react.
        """
        ...

    def is_irreversible(self, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """Override if this tool needs HITL approval before execution.

        Returns:
            (needs_approval: bool, human_readable_description: str)
        """
        return False, ""
