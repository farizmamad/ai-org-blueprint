"""
Agent registry — maps agent_id strings to their make_loop factories.

Usage:
    from agents import AGENT_REGISTRY
    from core.brain import BrainService
    from core.agents.runners.mock_runner import MockRunner

    brain = BrainService()
    runner = MockRunner()

    loop = AGENT_REGISTRY["engineer"](brain, runner)
    response = loop.run("Review the auth module for SQL injection risks.")
"""

from __future__ import annotations

from typing import Callable

from core.brain import BrainService
from core.agents.runners.base import LLMRunner
from core.orchestrator.agent_loop import AgentLoop

import agents.ceo as ceo
import agents.engineer as engineer
import agents.product as product
import agents.marketing as marketing
import agents.finance as finance
import agents.operations as operations
import agents.sales as sales

# Maps agent_id → factory function (brain, runner) → AgentLoop
AgentFactory = Callable[[BrainService, LLMRunner], AgentLoop]

AGENT_REGISTRY: dict[str, AgentFactory] = {
    "ceo": ceo.make_loop,
    "engineer": engineer.make_loop,
    "product": product.make_loop,
    "marketing": marketing.make_loop,
    "finance": finance.make_loop,
    "operations": operations.make_loop,
    "sales": sales.make_loop,
}

DETAILED_AGENTS = {"ceo", "engineer", "product", "marketing"}
STUB_AGENTS = {"finance", "operations", "sales"}

__all__ = ["AGENT_REGISTRY", "DETAILED_AGENTS", "STUB_AGENTS"]
