"""
MockRunner — deterministic responses for offline demo and tests.

Why ship a mock as default? Two reasons:
  1. New readers can `make demo` without an Anthropic API key. They see
     architecture flow (intent → router → agent → memory) without LLM noise.
  2. Tests need to assert routing/memory behavior independent of LLM
     responses. The mock gives reproducible outputs.

Behaviour: keyword-match the incoming message → return a templated reply.
Realistic enough to demonstrate end-to-end flow; obvious enough not to be
mistaken for a real LLM.
"""

from __future__ import annotations

import hashlib
from typing import Any

from core.agents.runners.base import LLMRunner, RunnerResult


class MockRunner(LLMRunner):

    @property
    def name(self) -> str:
        return "mock"

    def run(
        self,
        message: str,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> RunnerResult:
        # Use the latest user-role content if full history is provided
        if messages is not None:
            for m in reversed(messages):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    message = m["content"]
                    break
        msg_lower = message.lower()

        # Keyword-match heuristic — make it obvious this is a stub
        if any(k in msg_lower for k in ("hello", "hi", "hey")):
            reply = "[mock] Hi. This is the mock LLM runner — set LLM_RUNNER=api in .env for real responses."
        elif "delegate" in msg_lower or "engineer" in msg_lower:
            reply = "[mock] If I were real, I'd delegate this to the Engineer agent via message_agent."
        elif "remember" in msg_lower or "memory" in msg_lower:
            reply = "[mock] Looks like a memory operation. Use brain.remember(namespace, key, value)."
        elif "goal" in msg_lower:
            reply = "[mock] Goal-related request. See agent_goals table semantics in core/brain/schema.sql."
        else:
            # Fall back to a deterministic-but-traceable echo
            digest = hashlib.sha256(message.encode()).hexdigest()[:8]
            reply = f"[mock-{digest}] Received {len(message)} chars. (Deterministic placeholder.)"

        return RunnerResult(
            response=reply,
            session_id=session_id or f"mock-session",
            usage={"input_tokens": len(message) // 4, "output_tokens": len(reply) // 4},
        )
