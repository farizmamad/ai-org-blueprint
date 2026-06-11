# ai-org-blueprint

> A reference architecture for building **agentic AI organizations** — multiple
> LLM agents coordinated through shared memory, durable task queues, and
> human-in-the-loop checkpoints. Companion code to the article
> [_I Built an AI Organization to Manage My Life_](#) (Medium, 2026).

This is a **tutorial repo**, not a framework. Read the code, fork it, gut it,
adapt it. The goal is to show one workable pattern — not the only pattern.

---

## What's inside

```
core/
├── brain/          SQLite memory layer (namespaces, episodic log, knowledge)
├── orchestrator/   Intent classifier + agent router
└── agents/         Base AgentLoop + LLM runner abstraction

agents/
├── ceo/            Delegator pattern (single point of contact)
├── engineer/       Technical agent (code review, ADRs)
├── product/        PRD-style agent
├── marketing/      Content agent
├── finance/        ← stub (see docs/adding-an-agent.md)
├── operations/     ← stub
└── sales/          ← stub

examples/
├── ceo-engineer-delegation/    delegation pattern walkthrough
├── cron-proactive-dispatch/    autonomous goal dispatch
└── memory-namespaces/          private vs shared memory boundaries
```

---

## Quickstart (5 minutes)

**Requires:** Docker + Docker Compose. No API key needed for the default demo.

```bash
git clone https://github.com/<your-fork>/ai-org-blueprint.git
cd ai-org-blueprint
cp .env.example .env
make demo
```

That runs the **default mode**: a mock LLM responds with deterministic
placeholders, so you can trace the architecture end-to-end without an
Anthropic API key. `make demo` boots the Brain, spins up the CEO + Engineer
agents, and walks through one delegation cycle. Logs to stdout.

To use real Claude API responses instead:

```bash
echo "ANTHROPIC_API_KEY=sk-..." >> .env
echo "LLM_RUNNER=api"            >> .env
make demo
```

---

## Advanced: Claude Code sidecar (opt-in)

The article's actual implementation runs each agent through the
[Claude Code CLI](https://github.com/anthropics/claude-code) in a separate
container, so agents get full agentic capabilities (file edits, shell, etc).
That setup is heavier — Node.js + Claude CLI + an HTTP sidecar — so it's
**opt-in**.

```bash
echo "LLM_RUNNER=claude_code" >> .env
make demo-full
```

See [`docs/dual-runner-pattern.md`](docs/dual-runner-pattern.md) for why this
matters and when you'd want it.

---

## What this repo demonstrates

The article makes three architectural claims. This repo has runnable code for
each:

| Claim | Read this code | Run this example |
|---|---|---|
| Shared memory beats shared context | `core/brain/` | `examples/memory-namespaces/` |
| Delegation requires durable state | `core/orchestrator/`, `agents/ceo/` | `examples/ceo-engineer-delegation/` |
| Multi-agent only beats single-agent if it's autonomous | `core/orchestrator/agent_loop.py` | `examples/cron-proactive-dispatch/` |

See [`docs/architecture.md`](docs/architecture.md) for the full mental model,
[`docs/dual-runner-pattern.md`](docs/dual-runner-pattern.md) for the runner
design, [`docs/observability.md`](docs/observability.md) for Prometheus metrics
setup, and [`docs/adr/`](docs/adr/) for the decisions that shaped each piece.

---

## What this repo is NOT

- Not a framework — there's no plugin system, no abstract base class hierarchy.
  Copy what's useful, throw out what isn't.
- Not production-ready — no auth, no rate limiting. Observability is included
  (`core/observability/`) but wiring up Grafana is left to you.
- Not the only way — multi-agent design space is wide. The README links to
  alternative approaches at the bottom.

---

## License

[MIT](LICENSE). Use freely, attribute if you find it useful, no warranty.
