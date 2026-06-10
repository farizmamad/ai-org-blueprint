"""
MessageAgentTool — delegate a task to another agent.

How cross-agent communication works in this architecture:
  1. The sender agent calls this tool with a target_agent + subject + body.
  2. The tool records a "task" episode under the *target* agent's ID.
  3. The target agent's proactive check (cron or poll) reads its episodic inbox
     and picks up pending tasks.

This is the simplest coordination pattern: shared memory as the message bus.
It has no delivery guarantees (fire-and-forget), but it's transparent — you
can inspect the inbox with `brain.get_episodes(agent_id="engineer", type="task")`.

In production (ai-angels), this is extended with:
  - Discord notifications to alert the target agent
  - A scheduler that dispatches the task to a live runner
  - Acknowledgement / status tracking via agent_goals
"""

from __future__ import annotations

from typing import Any

from core.brain.service import BrainService, Episode
from tools.base import BaseTool


class MessageAgentTool(BaseTool):

    def __init__(self, brain: BrainService, sender_id: str) -> None:
        self._brain = brain
        self._sender_id = sender_id

    @property
    def id(self) -> str:
        return "message_agent"

    @property
    def definition(self) -> dict[str, Any]:
        return {
            "name": "message_agent",
            "description": (
                "Delegate a task or share information with another agent. "
                "The message is recorded in the target agent's episodic inbox; "
                "they will pick it up on their next loop iteration."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_agent": {
                        "type": "string",
                        "description": "Agent ID of the recipient (e.g. 'engineer', 'product', 'ceo').",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Short task title (shown in the agent's dashboard).",
                    },
                    "body": {
                        "type": "string",
                        "description": "Full task description with context and expected output.",
                    },
                },
                "required": ["target_agent", "subject", "body"],
            },
        }

    def run(self, tool_input: dict[str, Any]) -> str:
        target = tool_input["target_agent"]
        subject = tool_input["subject"]
        body = tool_input["body"]

        episode = Episode(
            agent_id=target,
            type="task",
            title=f"[from:{self._sender_id}] {subject}",
            body=body,
        )
        ep_id = self._brain.record_episode(episode)
        return f"[ok] message delivered to {target!r} (episode #{ep_id})"
