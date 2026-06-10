"""
Sales Agent — stub.

This agent is intentionally minimal. It ships with only the three base tools
(remember, record_episode, message_agent) and a placeholder system prompt.

To extend it, add domain-specific tools such as:
  - CRMTool         : read/write leads and deal stages from a CRM
  - OutreachTool    : draft and queue personalised outreach messages
  - PipelineTool    : summarise revenue pipeline by stage

See docs/adding-an-agent.md for the step-by-step walkthrough.
"""

from __future__ import annotations

from core.brain import BrainService
from core.agents.runners.base import LLMRunner
from core.orchestrator.agent_loop import AgentLoop
from tools.implementations.message_agent_tool import MessageAgentTool
from tools.implementations.record_episode_tool import RecordEpisodeTool
from tools.implementations.remember_tool import RememberTool

AGENT_ID = "sales"

SYSTEM_PROMPT = """\
You are the sales agent. You track leads, draft outreach, and monitor the
revenue pipeline.

This is a stub configuration — your domain-specific tools have not been
connected yet. Use `remember` to track key prospects and deal status, and
`record_episode` to log significant sales events (closed deals, lost deals,
key meetings). When you need marketing support (e.g. collateral), delegate via
`message_agent`.
"""


def make_loop(brain: BrainService, runner: LLMRunner | None = None) -> AgentLoop:
    """Return a ready-to-run AgentLoop for the Sales agent (stub)."""
    if runner is None:
        from core.agents.runners import make_runner
        runner = make_runner(agent_id=AGENT_ID, brain=brain)
    tools = [
        RememberTool(brain),
        RecordEpisodeTool(brain, AGENT_ID),
        MessageAgentTool(brain, AGENT_ID),
    ]
    return AgentLoop(AGENT_ID, runner, brain, tools, system_prompt=SYSTEM_PROMPT)
