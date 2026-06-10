from __future__ import annotations

import os
from typing import TYPE_CHECKING

from core.agents.runners.base import LLMRunner, RunnerResult
from core.agents.runners.api_runner import APIRunner
from core.agents.runners.mock_runner import MockRunner
from core.agents.runners.claude_code_runner import ClaudeCodeRunner

if TYPE_CHECKING:
    from core.brain.service import BrainService


def make_runner(
    runner_type: str | None = None,
    agent_id: str | None = None,
    brain: "BrainService | None" = None,
    **kwargs: object,
) -> LLMRunner:
    """
    Factory: read LLM_RUNNER from env (or pass runner_type explicitly).

    Values:
        mock         — deterministic, no API key needed (default)
        api          — Anthropic Messages API (requires ANTHROPIC_API_KEY)
        claude_code  — Claude Code sidecar (requires make demo-full)

    Pass agent_id + brain for ClaudeCodeRunner to enable Brain-backed session
    persistence and memory context injection (the Faith production pattern).
    Without them, the runner still works but sessions are in-memory only.

    Extra kwargs are forwarded to the runner constructor, e.g.:
        make_runner("api", model="claude-haiku-4-5-20251001")
    """
    t = runner_type or os.environ.get("LLM_RUNNER", "mock")
    if t == "mock":
        return MockRunner()
    if t == "api":
        return APIRunner(**kwargs)  # type: ignore[arg-type]
    if t == "claude_code":
        return ClaudeCodeRunner(agent_id=agent_id, brain=brain, **kwargs)  # type: ignore[arg-type]
    raise ValueError(
        f"Unknown LLM_RUNNER={t!r}. Valid values: mock | api | claude_code"
    )


__all__ = [
    "LLMRunner",
    "RunnerResult",
    "APIRunner",
    "MockRunner",
    "ClaudeCodeRunner",
    "make_runner",
]
