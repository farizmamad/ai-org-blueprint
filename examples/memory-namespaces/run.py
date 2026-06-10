#!/usr/bin/env python3
"""
Memory namespaces walkthrough — private vs shared memory boundaries.

What this demonstrates
──────────────────────
  BrainService uses namespaces to separate agent memory:

    private:{agent_id}   only that agent reads/writes (by convention)
    shared               all agents read/write freely
    cross:{a}:{b}        pairwise channel (a and b, sorted alphabetically)

  IMPORTANT: BrainService itself does NOT enforce isolation. It's a pure
  read/write store. The routing layer (AgentLoop + tool call site) is
  responsible for keeping each agent in its own namespace. This is a
  deliberate design choice — keeping the service dumb makes it easier to
  test, inspect, and debug.

Architectural claim this exercises
────────────────────────────────────
  "Shared memory beats shared context."
  Context window = temporary, process-local, expensive to expand.
  Brain namespace = durable, multi-agent, queryable.

  Each agent keeps its sensitive state in private:{id} and publishes
  decisions to shared — so the next agent can pick up where the last
  left off without re-reading a transcript.

Run
───
  python examples/memory-namespaces/run.py
"""
from __future__ import annotations

import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from dotenv import load_dotenv
load_dotenv()

from core.brain.service import BrainService

DIVIDER = "─" * 64


def section(title: str) -> None:
    print(f"\n{DIVIDER}\n  {title}\n{DIVIDER}")


def main() -> None:
    brain = BrainService()

    print(f"\nai-org-blueprint  ·  Memory namespaces demo")
    print(f"Brain: {brain._db_path}\n")

    # ── 1. Write to separate namespaces ──────────────────────────────────────
    section("1  Writing to separate namespaces")

    brain.remember("private:ceo",      "strategy",    "Grow revenue 20% by Q3 via better delegation.")
    brain.remember("private:engineer", "focus",       "Finish auth module security review.")
    brain.remember("private:engineer", "open_prs",    "3")
    brain.remember("shared",           "org_mission", "Ship a readable, runnable AI org blueprint.")
    brain.remember("shared",           "sprint",      "Sprint 4 — security + documentation")

    print("  Wrote 5 facts across 3 namespaces:")
    print("    private:ceo      → strategy")
    print("    private:engineer → focus, open_prs")
    print("    shared           → org_mission, sprint")

    # ── 2. Simulate per-agent reads ───────────────────────────────────────────
    section("2  Simulating per-agent reads")

    ceo_strategy  = brain.recall("private:ceo", "strategy")
    eng_focus     = brain.recall("private:engineer", "focus")
    shared_sprint = brain.recall("shared", "sprint")

    print(f"  CEO reads private:ceo/strategy      → '{ceo_strategy}'")
    print(f"  Eng reads private:engineer/focus    → '{eng_focus}'")
    print(f"  Both read shared/sprint             → '{shared_sprint}'")

    # Demonstrate that the service is permissive (no access control)
    ceo_reads_eng = brain.recall("private:engineer", "focus")
    print(f"\n  CEO reads private:engineer/focus    → '{ceo_reads_eng}'")
    print("  ↑ BrainService returned this — isolation is NOT enforced here.")
    print("  → AgentLoop must scope tool calls to the agent's own namespace.")

    # ── 3. Namespace listing ──────────────────────────────────────────────────
    section("3  Listing a namespace")

    eng_all = brain.recall_namespace("private:engineer")
    print(f"  All facts in private:engineer ({len(eng_all)} entries):")
    for m in eng_all:
        print(f"    {m.key:20}  =  {m.value!r}")

    # ── 4. Cross-agent channel ────────────────────────────────────────────────
    section("4  Cross-agent channel (pairwise)")

    brain.remember("cross:ceo:engineer", "handoff_note",
                   "Auth review delegated 2026-06-09. Expect ADR by EOD.")
    note = brain.recall("cross:ceo:engineer", "handoff_note")
    print(f"  cross:ceo:engineer/handoff_note → '{note}'")
    print("  Only CEO and Engineer are expected to read this channel.")
    print("  (Still not enforced by BrainService — convention only.)")

    # ── 5. Key takeaways ─────────────────────────────────────────────────────
    section("5  Key takeaways")

    takeaways = [
        "Namespaces are strings — any agent can technically read any namespace.",
        "Isolation is a routing-layer concern, not a storage-layer concern.",
        "private:{id} keeps an agent's internal state out of shared context.",
        "shared/ is the coordination surface — decisions, handoffs, north-star.",
        "cross:{a}:{b} is useful for explicit bilateral handoffs.",
    ]
    for i, t in enumerate(takeaways, 1):
        print(textwrap.fill(f"  {i}. {t}", 72, subsequent_indent="     "))

    print(f"\n{DIVIDER}\n")


if __name__ == "__main__":
    main()
