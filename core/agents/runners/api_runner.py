"""
APIRunner — calls the Anthropic API directly.

Use this when you want real LLM responses but don't need the full Claude
Code CLI environment (file edits, shell, etc). Light, single-process,
fine for most agent loops.

Activate via .env:
    LLM_RUNNER=api
    ANTHROPIC_API_KEY=sk-ant-...
    LLM_MODEL=claude-haiku-4-5-20251001   # or any current model

For long-running agents that need file/shell tools, use ClaudeCodeRunner
(opt-in, see docker-compose.full.yml).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from core.agents.runners.base import LLMRunner, RunnerResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")
DEFAULT_MAX_TOKENS = 1024


class APIRunner(LLMRunner):

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        # Import here so the module is importable even without anthropic installed
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed. Run `pip install anthropic` "
                "or use LLM_RUNNER=mock for offline demos."
            ) from e

        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY missing. Set it in .env or pass api_key=."
            )

        from anthropic import Anthropic
        self._client = Anthropic(api_key=self._api_key)
        self._model = model
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return "api"

    def run(
        self,
        message: str,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> RunnerResult:
        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": self._max_tokens,
                "messages": messages if messages is not None else [{"role": "user", "content": message}],
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            if tools:
                kwargs["tools"] = tools

            resp = self._client.messages.create(**kwargs)

            # Extract text + any tool calls
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in resp.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            usage = {}
            if hasattr(resp, "usage") and resp.usage is not None:
                usage = {
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                }

            return RunnerResult(
                response="\n".join(text_parts),
                session_id=session_id,
                tool_calls=tool_calls,
                usage=usage,
            )

        except Exception as e:
            logger.exception("[APIRunner] inference failed")
            return RunnerResult(response="", error=str(e))
