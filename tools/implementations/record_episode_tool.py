"""
RecordEpisodeTool — log a significant event to episodic memory.

Why episodic memory?
  Long-term memory (remember/recall) stores *facts*. Episodic memory stores
  *what happened*: decisions made, deliverables shipped, errors encountered.
  The distinction matters for retrieval: you search episodes by agent + type
  to reconstruct history, not to look up a specific fact.

Practical use:
  At the end of a task, agents call this tool to leave a paper trail.
  Other agents (or the human) can query `brain.get_episodes(agent_id="engineer")`
  to see what was done without reading every memory key.
"""

from __future__ import annotations

from typing import Any

from core.brain.service import BrainService, Episode
from tools.base import BaseTool

VALID_TYPES = {"event", "decision", "deliverable", "error", "note"}


class RecordEpisodeTool(BaseTool):

    def __init__(self, brain: BrainService, agent_id: str) -> None:
        self._brain = brain
        self._agent_id = agent_id

    @property
    def id(self) -> str:
        return "record_episode"

    @property
    def definition(self) -> dict[str, Any]:
        return {
            "name": "record_episode",
            "description": (
                "Log a significant event, decision, or deliverable to episodic memory. "
                "Call this at the end of a task or whenever something notable happens. "
                "Other agents and the human can query this history later."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": sorted(VALID_TYPES),
                        "description": (
                            "event — something that happened; "
                            "decision — a choice made; "
                            "deliverable — work shipped; "
                            "error — something went wrong; "
                            "note — miscellaneous observation."
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": "Short one-line summary (shown in dashboards).",
                    },
                    "body": {
                        "type": "string",
                        "description": "Full detail. Optional but recommended for decisions and deliverables.",
                    },
                },
                "required": ["type", "title"],
            },
        }

    def run(self, tool_input: dict[str, Any]) -> str:
        ep_type = tool_input["type"]
        if ep_type not in VALID_TYPES:
            return f"[error] invalid type {ep_type!r}. Must be one of: {sorted(VALID_TYPES)}"

        episode = Episode(
            agent_id=self._agent_id,
            type=ep_type,
            title=tool_input["title"],
            body=tool_input.get("body"),
        )
        ep_id = self._brain.record_episode(episode)
        return f"[ok] episode #{ep_id} recorded ({ep_type}: {tool_input['title'][:60]})"
