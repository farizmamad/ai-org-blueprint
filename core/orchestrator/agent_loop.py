"""
AgentLoop — the beating heart of every agent.

The loop is straightforward:
  1. Receive a task (string).
  2. Send to the LLM runner with the current messages history.
  3. If the response contains tool calls → dispatch each tool → append results
     to the messages list → go to 2.
  4. If no tool calls → the agent is done; return the text response.

A MAX_TURNS guard prevents infinite loops (a common failure mode when an
agent misunderstands its own tool results).

Why keep this class small?
  - Agents differ in *system prompt* and *tool list*, not in loop logic.
  - A single AgentLoop implementation means a single place to fix bugs.
  - Tests can inject any runner (including MockRunner) without touching
    the orchestration code.

HITL (human-in-the-loop):
  Tools can declare themselves irreversible via `is_irreversible()`. When that
  returns True, the loop queues the action in brain.pending_actions and tells
  the LLM the action needs approval — it does NOT execute the tool immediately.
  The human approves via the CLI/Discord bot; a separate process then runs
  the tool and resumes the agent if needed.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from core.agents.runners.base import LLMRunner
from core.brain.service import BrainService, Turn
from tools.base import BaseTool

logger = logging.getLogger(__name__)

MAX_TURNS = 10  # module-level constant so tests can read it


class AgentLoop:
    """Orchestrates one agent's reasoning-and-action loop."""

    def __init__(
        self,
        agent_id: str,
        runner: LLMRunner,
        brain: BrainService,
        tools: list[BaseTool],
        system_prompt: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self._runner = runner
        self._brain = brain
        self._system_prompt = system_prompt
        self._tool_map: dict[str, BaseTool] = {t.id: t for t in tools}

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, message: str, session_id: str | None = None) -> str:
        """Run the agent loop for one task. Blocks until done. Returns final text."""
        session_id = session_id or uuid.uuid4().hex[:8]
        messages: list[dict[str, Any]] = [{"role": "user", "content": message}]
        self._brain.save_turn(self.agent_id, session_id, Turn(role="user", content=message))
        self._brain.update_status(self.agent_id, current_task=message[:80])

        tool_defs = [t.definition for t in self._tool_map.values()] or None

        for turn_num in range(MAX_TURNS):
            result = self._runner.run(
                message=message,
                session_id=session_id,
                system_prompt=self._system_prompt,
                tools=tool_defs,
                messages=messages,
            )

            if result.error:
                logger.error("[AgentLoop:%s] runner error on turn %d: %s", self.agent_id, turn_num, result.error)
                return f"[error] {result.error}"

            if not result.tool_calls:
                # No more tools to call — agent is done.
                final = result.response
                self._brain.save_turn(self.agent_id, session_id, Turn(role="assistant", content=final))
                return final

            # ── Append assistant turn (text + tool_use blocks) ────────────────
            assistant_content: list[dict[str, Any]] = []
            if result.response:
                assistant_content.append({"type": "text", "text": result.response})
            for tc in result.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # ── Dispatch each tool ────────────────────────────────────────────
            tool_results: list[dict[str, Any]] = []
            for tc in result.tool_calls:
                tool_result_text = self._dispatch(tc)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": tool_result_text,
                })
                logger.debug("[AgentLoop:%s] tool=%s result=%s", self.agent_id, tc["name"], tool_result_text[:80])

            messages.append({"role": "user", "content": tool_results})

        logger.warning("[AgentLoop:%s] hit MAX_TURNS (%d)", self.agent_id, MAX_TURNS)
        return "[error] max turns exceeded — agent loop did not converge"

    # ── Internals ─────────────────────────────────────────────────────────────

    def _dispatch(self, tool_call: dict[str, Any]) -> str:
        """Execute one tool call. Returns the result string for the LLM."""
        tool_name = tool_call["name"]
        tool_input = tool_call.get("input", {})

        tool = self._tool_map.get(tool_name)
        if tool is None:
            return f"[error] unknown tool: {tool_name!r}. Available: {list(self._tool_map)}"

        needs_approval, description = tool.is_irreversible(tool_input)
        if needs_approval:
            action_id = self._brain.queue_action(
                agent_id=self.agent_id,
                tool_name=tool_name,
                tool_input=tool_input,
                description=description,
            )
            return (
                f"[hitl] Action queued for human approval (action_id={action_id}). "
                f"Description: {description}. "
                "The tool will execute after approval — do not retry it."
            )

        try:
            return tool.run(tool_input)
        except Exception as exc:
            logger.exception("[AgentLoop:%s] tool %s raised", self.agent_id, tool_name)
            return f"[error] {tool_name} failed: {exc}"
