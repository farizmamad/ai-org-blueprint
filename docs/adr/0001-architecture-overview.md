# ADR-0001: Architecture Overview

**Status:** Accepted
**Date:** 2026-06-09

## Context

This repository accompanies an article on building a multi-agent AI
organization. The architecture aims to answer one question: *what does it take
for multiple LLM agents to coordinate reliably without all the context collapse
problems of a single mega-prompt?*

The constraints for this repo specifically:

- **Tutorial-grade, not production.** Code should be readable in one sitting.
- **Runnable in 5 minutes** with no API key. Demo mode uses a mock LLM.
- **Honest about tradeoffs.** Where the architecture is opinionated, the ADR
  explains why and what we gave up.

## Decision

Four pillars, layered:

```
┌─────────────────────────────────────────────────────┐
│  Discord / CLI / HTTP — entrypoint (any chat UI)    │
└─────────────────┬───────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  Orchestrator                                        │
│  ├── intent.py    — classify message → agent(s)     │
│  └── router.py    — dispatch + merge responses      │
└─────────────────┬───────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  Agents                                              │
│  ├── base/loop.py     — agentic tool-use loop       │
│  └── runners/         — pluggable LLM backend       │
│      ├── api_runner.py        (Anthropic API)       │
│      ├── mock_runner.py       (deterministic)       │
│      └── claude_code_runner.py (sidecar HTTP)       │
└─────────────────┬───────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────┐
│  Brain (shared nervous system)                       │
│  ├── namespaced key-value memory (private / shared) │
│  ├── episodic event log                              │
│  ├── semantic knowledge store                        │
│  ├── agent_goals (durable task queue)                │
│  └── pending_actions (HITL gate)                     │
│  Backend: SQLite (1 file, no external deps)         │
└──────────────────────────────────────────────────────┘
```

## Three claims this architecture makes

### 1. Shared memory beats shared context

Single-prompt agents collapse under long histories. A shared *structured*
memory layer (Brain) lets each agent run with a focused prompt while still
reading and writing to a common state. Each agent has private and shared
namespaces — boundary is explicit.

See: `core/brain/`, example `examples/memory-namespaces/`.

### 2. Delegation requires durable state

A "boss" agent that delegates by passing strings to another agent via a single
function call is fragile. We use `agent_goals` — a typed table with status
(`PENDING|IN_PROGRESS|COMPLETED`) and ownership. Delegation becomes
"write a goal," execution becomes "claim and complete it," tracking becomes
"read the table." Atomic, observable, idempotent.

See: `core/brain/agent_goals.py`, example `examples/ceo-engineer-delegation/`.

### 3. Multi-agent is only worth it if it's autonomous

If a human has to manually trigger each agent, multi-agent is just more typing
than single-agent. The proactive dispatch cron periodically scans
`agent_goals` for `PENDING` tasks and dispatches them. Agents that finish call
back to mark `COMPLETED`. The human stays in the loop only at irreversible
decision points (`pending_actions`).

See: `core/agents/cron.py`, example `examples/cron-proactive-dispatch/`.

## Tradeoffs we accepted

| Choice | What we gave up |
|---|---|
| **SQLite for everything** | Horizontal scale; multi-process write contention |
| **Single mock runner by default** | Demo doesn't show real LLM personality differences |
| **No abstract Agent base class** | Less polymorphism; each agent config is a plain dict |
| **One synchronous router** | No parallel multi-agent fan-out; future work |
| **No observability stack** | You'll need your own logs/metrics for anything serious |

## Alternatives considered

- **LangChain / LangGraph** — fully featured, lots of magic. Great for fast
  prototypes; harder to audit when things go wrong.
- **AutoGen** — Microsoft's framework. Conversation-centric; we wanted task-centric.
- **Build-your-own from scratch** — what this repo demonstrates. Choose this
  when you want to understand every line.

## When this architecture isn't right

- Your problem is genuinely single-domain (then a single agent with good
  prompts is simpler).
- You need >10 agents — coordination cost will dominate.
- You can't pay the SQLite scaling tax (then swap to Postgres at the Brain
  layer; everything else stays).

## References

- Liu et al. (2023), [Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/) — long-context degradation
- Simon (1947), *Administrative Behavior* — organizational role theory
- Park et al. (2023), [Generative Agents](https://arxiv.org/abs/2304.03442) — multi-agent simulation
