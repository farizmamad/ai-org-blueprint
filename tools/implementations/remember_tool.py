"""
RememberTool — store a fact in long-term memory.

Why expose this as an agent tool?
  Agents need to persist information across sessions and share it with other
  agents. Rather than hard-coding persistence calls inside the runner, we let
  the LLM decide *what* to remember and *where* (namespace). That keeps the
  agent loop policy-free.

Namespace conventions (from BrainService docstring):
    private:{agent_id}  — only that agent reads/writes
    shared              — readable by all agents
    cross:{a}:{b}       — only agents a and b
"""

from __future__ import annotations

from typing import Any

from core.brain.service import BrainService
from tools.base import BaseTool


class RememberTool(BaseTool):

    def __init__(self, brain: BrainService) -> None:
        self._brain = brain

    @property
    def id(self) -> str:
        return "remember"

    @property
    def definition(self) -> dict[str, Any]:
        return {
            "name": "remember",
            "description": (
                "Persist a fact to long-term memory. "
                "Use this whenever you learn something that should survive past this session — "
                "a decision, a preference, a status update, etc."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": (
                            "Visibility scope. "
                            "'shared' = all agents. "
                            "'private:{your_agent_id}' = only you. "
                            "'cross:{a}:{b}' = two specific agents."
                        ),
                    },
                    "key": {
                        "type": "string",
                        "description": "Unique key within the namespace. Use snake_case.",
                    },
                    "value": {
                        "type": "string",
                        "description": "The fact to store. Plain text or JSON string.",
                    },
                },
                "required": ["namespace", "key", "value"],
            },
        }

    def run(self, tool_input: dict[str, Any]) -> str:
        namespace = tool_input["namespace"]
        key = tool_input["key"]
        value = tool_input["value"]
        self._brain.remember(namespace=namespace, key=key, value=value)
        return f"[ok] remembered {namespace}/{key}"
