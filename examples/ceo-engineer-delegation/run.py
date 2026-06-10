#!/usr/bin/env python3
"""
CEO → Engineer delegation walkthrough.

What this demonstrates
──────────────────────
  1. CEO reads its own private memory (pending delegation task)
  2. CEO delegates to Engineer via `message_agent` tool
  3. Engineer retrieves its goal from the durable task queue (agent_goals)
  4. Engineer acknowledges and plans the task
  5. We inspect shared memory state after the cycle

Architectural claims this exercises
────────────────────────────────────
  - Shared memory beats shared context: CEO and Engineer use separate
    BrainService instances pointed at the same SQLite file — no shared
    in-process state, no context-passing between loops.
  - Delegation requires durable state: the goal written by seed_demo.py
    persists across process boundaries. If the Engineer container restarted
    mid-task, the goal would still be there.

Run
───
  # Prerequisites (docker-compose handles this for you):
  python scripts/init_brain.py
  python scripts/seed_demo.py

  # Direct run:
  python examples/ceo-engineer-delegation/run.py

  # Via make:
  make demo
"""
from __future__ import annotations

import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from dotenv import load_dotenv
load_dotenv()

from core.brain.service import BrainService
from core.agents.runners import make_runner
from agents.ceo.agent import make_loop as make_ceo_loop
from agents.engineer.agent import make_loop as make_engineer_loop

DIVIDER = "─" * 64


def heading(text: str) -> None:
    print(f"\n{DIVIDER}\n  {text}\n{DIVIDER}")


def wrap(text: str, width: int = 72, indent: int = 4) -> str:
    return textwrap.fill(text, width, initial_indent=" " * indent, subsequent_indent=" " * indent)


def main() -> None:
    brain = BrainService()
    runner = make_runner()

    print(f"\nai-org-blueprint  ·  CEO → Engineer delegation demo")
    print(f"Runner: {runner.name}  ·  Brain: {brain._db_path}")

    pending = brain.recall("private:ceo", "pending_delegation") or "(nothing seeded)"
    print(f"CEO pending task: {pending}")

    # ── Step 1: CEO receives the delegation request ───────────────────────────
    heading("Step 1  CEO receives task from user")

    user_prompt = (
        "I need the engineer to review the auth module for SQL injection risks. "
        "Please delegate this and tell me who you sent it to."
    )
    print(f"  User → CEO: {user_prompt}\n")

    ceo = make_ceo_loop(brain, runner)
    ceo_reply = ceo.run(user_prompt)
    print(f"  CEO:\n{wrap(ceo_reply)}")

    # ── Step 2: Engineer picks up the pending goal ────────────────────────────
    heading("Step 2  Engineer checks pending goals")

    goals = brain.get_goals(owner_agent="engineer", status="PENDING")
    if not goals:
        print("  (No PENDING goals — did you run scripts/seed_demo.py?)")
        print("  Hint: `make demo` runs seed_demo.py automatically.\n")
        return

    goal = goals[0]
    print(f"  Engineer sees goal #{goal['id']}: {goal['goal_text']}\n")

    engineer = make_engineer_loop(brain, runner)
    eng_prompt = (
        f"You have a pending task: {goal['goal_text']}\n\n"
        "Acknowledge the task, outline your approach in 3 bullets, "
        "and update the goal status to IN_PROGRESS."
    )
    eng_reply = engineer.run(eng_prompt)
    print(f"  Engineer:\n{wrap(eng_reply)}")

    # ── Step 3: Memory state after the cycle ─────────────────────────────────
    heading("Step 3  Shared memory state after delegation")

    statuses = brain.get_status()
    print("  Agent status board:")
    for s in statuses:
        task = (s.get("current_task") or "—")[:50]
        print(f"    {s['agent_id']:12}  {task}")

    episodes = brain.get_episodes(limit=3)
    print(f"\n  Last {len(episodes)} episode(s):")
    for ep in episodes:
        print(f"    [{ep.type:12}] {ep.agent_id}: {ep.title}")

    print(f"\n{DIVIDER}")
    print("  Done. Key takeaways:")
    print("    - CEO and Engineer shared state via Brain (SQLite), not in-process context.")
    print("    - The goal survived across two separate AgentLoop instantiations.")
    print("    - Neither agent knew about the other's internal state directly.")
    print(f"{DIVIDER}\n")


if __name__ == "__main__":
    main()
