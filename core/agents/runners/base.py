"""
LLMRunner — abstract interface for "give me a response from an LLM".

Three implementations ship with this repo:
  - MockRunner  : deterministic placeholders, no API call (default)
  - APIRunner   : direct Anthropic SDK calls
  - ClaudeCodeRunner : opt-in, talks to the Claude Code sidecar via HTTP

Why an abstract interface? Two practical reasons:
  1. Tests should not hit a real LLM. MockRunner makes that free.
  2. The article's full setup uses Claude Code CLI in a sidecar. Most readers
     don't need that complexity for "look how the architecture works." Default
     is single-process; sidecar is opt-in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunnerResult:
    """What every runner returns. Same shape regardless of implementation."""

    response: str                   # the model's text response
    session_id: str | None = None   # if the runner supports session continuity
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)  # token counts, optional
    error: str | None = None        # populated on failure instead of raising


class LLMRunner(ABC):
    """Abstract runner. Implementations must be safe to call from sync code."""

    @abstractmethod
    def run(
        self,
        message: str,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> RunnerResult:
        """Run one inference call.

        `messages` is the full conversation history in Anthropic messages format.
        When provided by the AgentLoop (multi-turn), implementations should use
        it instead of building `[{"role": "user", "content": message}]`.
        `message` is kept as the original user prompt for backwards compatibility
        and for runners that don't need full history (e.g. MockRunner).
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier — used in logs and the runner factory."""
        ...
