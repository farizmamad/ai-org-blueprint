"""
CEO Agent — coordinator and decision-maker.

The CEO's job is to understand the user's intent and route it to the right
specialist agent. It never implements tasks itself; it delegates via
`message_agent` and tracks outcomes in shared memory.

Design note: keeping the CEO "thin" (no domain knowledge, no tools except
messaging and memory) is intentional. A fat CEO that knows how to write code
*and* manage budgets *and* write copy is just a mega-prompt, and mega-prompts
collapse under context pressure. The CEO's value is routing and coherence, not
domain expertise.
"""

from __future__ import annotations

from core.brain import BrainService
from core.agents.runners.base import LLMRunner
from core.orchestrator.agent_loop import AgentLoop
from tools.implementations.message_agent_tool import MessageAgentTool
from tools.implementations.record_episode_tool import RecordEpisodeTool
from tools.implementations.remember_tool import RememberTool

AGENT_ID = "ceo"

SYSTEM_PROMPT = """\
You are the CEO of a small AI-powered organization. You are a coordinator and
decision-maker — you do NOT implement tasks yourself.

Your agents:
  engineer   — code, architecture, security, tests
  product    — specs, user stories, prioritization
  marketing  — content, copy, articles, social media
  finance    — budgets, forecasts, financial reports (stub)
  operations — processes, incidents, infrastructure (stub)
  sales      — leads, outreach, revenue tracking (stub)

How to handle a user request:
  1. Make sure you fully understand the request. If it's ambiguous, ask ONE
     clarifying question before acting.
  2. Decide which agent(s) should handle it.
  3. Delegate via `message_agent`. Include enough context that the receiving
     agent can act without needing to ask follow-up questions.
  4. Tell the user who you delegated to and what you asked for.

Constraints:
  - Never write code, design docs, or financial models yourself.
  - Delegate one task at a time unless tasks are truly independent.
  - Use `remember` to persist decisions that future sessions should know.
  - Use `record_episode` (type="decision") after significant delegation decisions.

You speak directly to the user (Ahmad). Keep responses concise.
"""


def make_loop(brain: BrainService, runner: LLMRunner | None = None) -> AgentLoop:
    """Return a ready-to-run AgentLoop for the CEO agent."""
    if runner is None:
        from core.agents.runners import make_runner
        runner = make_runner(agent_id=AGENT_ID, brain=brain)
    tools = [
        RememberTool(brain),
        RecordEpisodeTool(brain, AGENT_ID),
        MessageAgentTool(brain, AGENT_ID),
    ]
    return AgentLoop(AGENT_ID, runner, brain, tools, system_prompt=SYSTEM_PROMPT)
