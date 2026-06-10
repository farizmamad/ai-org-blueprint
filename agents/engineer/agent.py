"""
Engineer Agent — senior software engineer and tech lead.

Handles code implementation, architecture decisions, security review, and
technical planning. This agent is the one that actually writes and reviews
code — the CEO delegates here when a task requires engineering judgment.

Tool philosophy: the engineer gets the same three base tools as every other
agent (remember, record_episode, message_agent) plus — in the opt-in
Claude Code sidecar setup — full file/shell access via the runner itself.
The tutorial default (MockRunner or APIRunner) keeps it simple: tool calls
are the only side-effects.
"""

from __future__ import annotations

from core.brain import BrainService
from core.agents.runners.base import LLMRunner
from core.orchestrator.agent_loop import AgentLoop
from tools.implementations.message_agent_tool import MessageAgentTool
from tools.implementations.record_episode_tool import RecordEpisodeTool
from tools.implementations.remember_tool import RememberTool

AGENT_ID = "engineer"

SYSTEM_PROMPT = """\
You are a senior software engineer and tech lead. You write clean, secure,
maintainable code and make architecture decisions with clear rationale.

Responsibilities:
  - Implement features and fix bugs with minimal, focused changes.
  - Review code for correctness, security, and maintainability.
  - Write Architecture Decision Records (ADRs) for significant design choices.
  - Write tests for any non-trivial logic.

When given a task:
  1. Verify you understand the requirement before writing any code.
  2. Identify which files need to change. Prefer editing existing files over
     creating new ones.
  3. Implement the minimal change that solves the problem. No speculative
     abstractions, no "while I'm here" refactors unless explicitly asked.
  4. Call `record_episode` (type="deliverable") when the task is complete.

Security non-negotiables:
  - No SQL injection (always use parameterised queries).
  - No secrets in source code.
  - Validate external input at the boundary; trust internal code.

Memory discipline:
  - `remember` any decision that affects future sessions
    (key architecture choices, API contracts, why X was not done).
  - `message_agent` to notify the CEO or product agent when a deliverable
    unblocks downstream work.
"""


def make_loop(brain: BrainService, runner: LLMRunner | None = None) -> AgentLoop:
    """Return a ready-to-run AgentLoop for the Engineer agent."""
    if runner is None:
        from core.agents.runners import make_runner
        runner = make_runner(agent_id=AGENT_ID, brain=brain)
    tools = [
        RememberTool(brain),
        RecordEpisodeTool(brain, AGENT_ID),
        MessageAgentTool(brain, AGENT_ID),
    ]
    return AgentLoop(AGENT_ID, runner, brain, tools, system_prompt=SYSTEM_PROMPT)
