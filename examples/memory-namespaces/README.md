# Example: Memory Namespaces

Demonstrates how `BrainService` namespaces keep agent memory separate — and
why that separation is the caller's responsibility, not the storage layer's.

## Architectural claim

> Shared memory beats shared context.

The context window is temporary, process-local, and expensive to expand.
A Brain namespace is durable, queryable, and accessible to any agent that has
the service's database path.

Each agent keeps sensitive state in `private:{id}` and publishes decisions to
`shared` — so the next agent can pick up where the last left off without
replaying an entire conversation transcript.

## Namespace conventions

| Namespace | Who reads/writes |
|-----------|-----------------|
| `private:{agent_id}` | That agent only (by convention) |
| `shared` | All agents |
| `cross:{a}:{b}` | Agents a and b (sorted alphabetically) |

**BrainService does NOT enforce these rules.** It is a pure read/write store.
Isolation is a routing-layer concern — the `AgentLoop` scopes tool calls to
the agent's own namespace. This keeps the service simple, testable, and easy
to inspect.

## What you'll see

```
────────────────────────────────────────────────────────────────
  1  Writing to separate namespaces
────────────────────────────────────────────────────────────────
  Wrote 5 facts across 3 namespaces:
    private:ceo      → strategy
    private:engineer → focus, open_prs
    shared           → org_mission, sprint

────────────────────────────────────────────────────────────────
  2  Simulating per-agent reads
────────────────────────────────────────────────────────────────
  CEO reads private:ceo/strategy      → 'Grow revenue 20% by Q3 via better delegation.'
  Eng reads private:engineer/focus    → 'Finish auth module security review.'
  Both read shared/sprint             → 'Sprint 4 — security + documentation'

  CEO reads private:engineer/focus    → 'Finish auth module security review.'
  ↑ BrainService returned this — isolation is NOT enforced here.
  → AgentLoop must scope tool calls to the agent's own namespace.

────────────────────────────────────────────────────────────────
  3  Listing a namespace
────────────────────────────────────────────────────────────────
  All facts in private:engineer (2 entries):
    focus                =  'Finish auth module security review.'
    open_prs             =  '3'

────────────────────────────────────────────────────────────────
  4  Cross-agent channel (pairwise)
────────────────────────────────────────────────────────────────
  cross:ceo:engineer/handoff_note → 'Auth review delegated 2026-06-09. Expect ADR by EOD.'
  Only CEO and Engineer are expected to read this channel.
  (Still not enforced by BrainService — convention only.)
```

## How to run

```bash
# No Brain service or LLM needed — runs entirely in-process:
make demo-namespaces

# Direct run:
python examples/memory-namespaces/run.py
```

This example has **no external dependencies** — no Docker, no API key, no
running services. It creates a temporary in-memory BrainService (or uses
`./data/brain.db` if `BRAIN_DB_PATH` is set).

## Key code locations

| What | Where |
|------|-------|
| Namespace read/write | `core/brain/service.py` → `remember`, `recall`, `recall_namespace` |
| Routing convention | `core/orchestrator/agent_loop.py` |
| Tool that enforces namespace | `tools/implementations/remember_tool.py` |
