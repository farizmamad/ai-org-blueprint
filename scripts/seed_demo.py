#!/usr/bin/env python3
"""
seed_demo.py — pre-load brain.db with data the demo examples expect.

Run after init_brain.py. All writes are idempotent: remember() upserts,
and goals are only created if none exist for that owner+title combo.

What gets seeded:
  - Shared fact: the organisation's north star
  - CEO memory: a pending task to delegate
  - Engineer memory: current weekly focus
  - A PENDING goal for the engineer (picked up by the delegation example)
  - An initial agent_status row for CEO + Engineer

Usage:
    python scripts/seed_demo.py
    BRAIN_DB_PATH=/tmp/test.db python scripts/seed_demo.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from core.brain.service import BrainService, Episode, Goal, DEFAULT_DB_PATH


def main() -> None:
    db_path = os.environ.get("BRAIN_DB_PATH", DEFAULT_DB_PATH)
    brain = BrainService(db_path=db_path)

    print("Seeding shared facts...")
    brain.remember("shared", "north_star", "Ship a readable, runnable reference architecture for agentic AI organizations.")
    brain.remember("shared", "org_name", "DemoOrg")
    brain.remember("shared", "runner_mode", os.environ.get("LLM_RUNNER", "mock"))

    print("Seeding CEO memory...")
    brain.remember(
        "private:ceo",
        "pending_delegation",
        "Review the auth module for SQL injection risks — needs to go to engineer.",
    )

    print("Seeding Engineer memory...")
    brain.remember(
        "private:engineer",
        "weekly_focus",
        "Reviewing auth module and writing ADRs for the tutorial repo.",
    )

    print("Seeding agent statuses...")
    brain.update_status("ceo", current_task="Waiting for engineer to complete auth review", weekly_focus="Delegation demo")
    brain.update_status("engineer", current_task="Idle — polling for pending goals", weekly_focus="Security review")

    print("Seeding demo goal for engineer...")
    existing = brain.get_goals(owner_agent="engineer", status="PENDING")
    if not any(g["goal_text"].startswith("Review the auth module") for g in existing):
        brain.set_goal(Goal(
            owner_agent="engineer",
            goal_text="Review the auth module for SQL injection risks and write a brief ADR.",
            goal_type="task",
            complexity="routine",
        ))
        print("  → goal created.")
    else:
        print("  → goal already exists, skipping.")

    print("Seeding episode history...")
    brain.record_episode(Episode(
        agent_id="ceo",
        type="decision",
        title="Decided to delegate auth review to engineer",
        body=(
            "User asked for a security review of the auth module. "
            "Delegated to engineer via message_agent with context about SQL injection risks. "
            "Expected output: ADR + inline code comments."
        ),
        tags=["delegation", "security", "demo"],
    ))

    print(f"\nSeed complete. Brain at: {db_path}")
    print("Run `make demo` to start the delegation walkthrough.")


if __name__ == "__main__":
    main()
