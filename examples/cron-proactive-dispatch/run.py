#!/usr/bin/env python3
"""
Proactive dispatch example — cron checks agent_goals and dispatches pending tasks.

What this demonstrates
──────────────────────
  The gap between a REACTIVE and an AUTONOMOUS AI org:

  Reactive:  agent only runs when a human sends a message.
  Autonomous: a scheduler polls the goal queue and starts agents proactively.

  This example seeds one PENDING goal for the Engineer, starts an
  APScheduler loop that polls every 3 seconds, dispatches the goal when
  found, then exits cleanly. No human message needed.

Architectural claim this exercises
────────────────────────────────────
  "Multi-agent only beats single-agent if it's autonomous."
  The scheduler is the bridge from reactive to autonomous. Without it,
  agent_goals is just a write-only table — tasks pile up and nobody runs them.

Run
───
  # Prerequisites:
  python scripts/init_brain.py

  # Direct run:
  python examples/cron-proactive-dispatch/run.py

  # Via make:
  make demo-cron
"""
from __future__ import annotations

import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.blocking import BlockingScheduler

from core.brain.service import BrainService, Goal
from core.agents.runners import make_runner
from agents.engineer.agent import make_loop as make_engineer_loop

# ── Module-level state shared with the scheduler callback ────────────────────
_brain: BrainService | None = None
_runner = None
_cycle_count = 0
_MAX_CYCLES = 5  # give up after N empty polls so demo doesn't hang forever


def _dispatch_pending() -> None:
    """Scheduler callback — runs every tick. Dispatches one PENDING goal if found."""
    global _cycle_count

    _cycle_count += 1
    goals = _brain.get_goals(owner_agent="engineer", status="PENDING")  # type: ignore[union-attr]

    if not goals:
        print(f"  [tick {_cycle_count}] No PENDING goals — waiting...")
        if _cycle_count >= _MAX_CYCLES:
            print("  [cron] Max cycles reached with no work. Exiting.")
            raise SystemExit(0)
        return

    goal = goals[0]
    print(f"\n  [tick {_cycle_count}] Found goal #{goal['id']}: {goal['goal_text'][:60]}...")
    print("  [cron] Marking IN_PROGRESS and dispatching to Engineer.\n")

    _brain.update_goal(goal["id"], status="IN_PROGRESS")  # type: ignore[union-attr]

    engineer = make_engineer_loop(_brain, _runner)  # type: ignore[arg-type]
    reply = engineer.run(
        f"You have a task from the goal queue:\n\n{goal['goal_text']}\n\n"
        "Acknowledge the task and write a 2-3 sentence response describing "
        "how you would approach it."
    )

    print(f"  Engineer reply:")
    print(textwrap.fill(reply, 72, initial_indent="    ", subsequent_indent="    "))

    _brain.update_goal(goal["id"], status="COMPLETED")  # type: ignore[union-attr]
    print("\n  [cron] Goal marked COMPLETED. Exiting.\n")
    raise SystemExit(0)


def main() -> None:
    global _brain, _runner
    _brain = BrainService()
    _runner = make_runner()

    DIVIDER = "─" * 64
    print(f"\n{DIVIDER}")
    print("  ai-org-blueprint  ·  Proactive dispatch demo")
    print(f"  Runner: {_runner.name}  ·  Brain: {_brain._db_path}")
    print(f"{DIVIDER}\n")

    # Seed a demo goal if none exist so the demo is self-contained
    existing = _brain.get_goals(owner_agent="engineer", status="PENDING")
    if not existing:
        _brain.set_goal(Goal(
            owner_agent="engineer",
            goal_text=(
                "Write a brief security note about SQL injection risks in the auth module. "
                "Focus on parameterised queries and ORM usage."
            ),
            goal_type="task",
            complexity="routine",
        ))
        print("  [setup] Seeded 1 PENDING goal for Engineer.\n")
    else:
        print(f"  [setup] Found {len(existing)} existing PENDING goal(s) — using those.\n")

    print(f"  Starting scheduler (poll interval: 3s, max cycles: {_MAX_CYCLES})...")
    print("  Ctrl-C to stop early.\n")

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(_dispatch_pending, "interval", seconds=3, max_instances=1)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)

    print("Done.\n")


if __name__ == "__main__":
    main()
