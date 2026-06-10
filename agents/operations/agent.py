"""
Operations Agent — stub.

This agent is intentionally minimal. It ships with only the three base tools
(remember, record_episode, message_agent) and a placeholder system prompt.

To extend it, add domain-specific tools such as:
  - IncidentTool    : create and update incident records
  - InfraTool       : query service health or trigger restarts (HITL-gated)
  - RunbookTool     : search and return runbook steps for known failure modes

See docs/adding-an-agent.md for the step-by-step walkthrough.
"""

from __future__ import annotations

from core.brain import BrainService
from core.agents.runners.base import LLMRunner
from core.orchestrator.agent_loop import AgentLoop
from tools.implementations.message_agent_tool import MessageAgentTool
from tools.implementations.record_episode_tool import RecordEpisodeTool
from tools.implementations.remember_tool import RememberTool

AGENT_ID = "operations"

SYSTEM_PROMPT = """\
You are the operations agent. You manage processes, respond to incidents, and
keep the infrastructure healthy.

This is a stub configuration — your domain-specific tools have not been
connected yet. Use `remember` to capture runbook decisions and known failure
patterns, and `record_episode` (type="event") to log incidents. When a fix
requires code changes, delegate to the engineer via `message_agent`.
"""


def make_loop(brain: BrainService, runner: LLMRunner | None = None) -> AgentLoop:
    """Return a ready-to-run AgentLoop for the Operations agent (stub)."""
    if runner is None:
        from core.agents.runners import make_runner
        runner = make_runner(agent_id=AGENT_ID, brain=brain)
    tools = [
        RememberTool(brain),
        RecordEpisodeTool(brain, AGENT_ID),
        MessageAgentTool(brain, AGENT_ID),
    ]
    return AgentLoop(AGENT_ID, runner, brain, tools, system_prompt=SYSTEM_PROMPT)
