# Architecture

This document covers the mental model behind `ai-org-blueprint` — how the
pieces fit together, why they were built this way, and where the seams are
if you want to adapt it.

For the formal decisions that shaped each piece, read
[`docs/adr/0001-architecture-overview.md`](adr/0001-architecture-overview.md).
For the runner design specifically, read
[`docs/dual-runner-pattern.md`](dual-runner-pattern.md).

---

## The four layers

```
┌─────────────────────────────────────────────────────────┐
│  Entrypoint  (CLI / Discord / HTTP)                      │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Orchestrator                                            │
│  ├── intent classifier  — message → agent(s)            │
│  └── router             — dispatch + merge              │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  AgentLoop                                               │
│  ├── tool-use loop (up to MAX_TURNS = 10)               │
│  ├── HITL gate (irreversible actions → pending_actions) │
│  └── LLMRunner (pluggable backend)                      │
│      ├── MockRunner     — deterministic, no API key     │
│      ├── APIRunner      — direct Anthropic API          │
│      └── ClaudeCodeRunner — sidecar CLI (opt-in)        │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Brain  (shared nervous system)                          │
│  ├── namespaced key-value memory  (private / shared)    │
│  ├── episodic event log                                  │
│  ├── semantic knowledge store (FTS)                      │
│  ├── agent_goals   — durable task queue                  │
│  └── pending_actions — HITL gate table                  │
│  Backend: SQLite + FastAPI (1 file, no infra)           │
└──────────────────────────────────────────────────────────┘
```

---

## Brain — the shared nervous system

Every agent reads and writes to a single Brain instance. This is the architectural
decision that makes multi-agent coordination possible without passing giant context
windows around.

### Memory namespaces

```
private:{agent_id}/key  →  only that agent reads/writes here
shared/key              →  all agents share this
```

The boundary is explicit and enforced by convention, not ACL. When an Engineer
agent writes a decision to `private:engineer/last_adr`, the CEO agent cannot
accidentally read it unless it uses the shared namespace.

See `core/brain/service.py::remember / recall / recall_namespace`.

### Episodic log

Every significant event — deliverables, errors, decisions — gets written here
via `record_episode`. Agents query their own recent episodes at the start of
each session so they "remember" what happened before without needing a shared
context window.

### Semantic knowledge store

Free-text knowledge indexed with SQLite FTS5. Agents store facts like market
research, architecture insights, user preferences. The ClaudeCodeRunner
automatically queries this before each call and injects the most relevant
entries into the prompt.

### agent_goals — durable task queue

Delegation via string-passing is fragile. This repo uses a typed table:

```sql
agent_goals(id, owner_agent, title, body, status, created_at, updated_at)
-- status: PENDING | IN_PROGRESS | COMPLETED | FAILED
```

The CEO writes a goal → Engineer claims it (`IN_PROGRESS`) → completes it →
marks `COMPLETED`. The full lifecycle is observable and atomic. The cron
dispatcher polls `PENDING` goals and dispatches them autonomously.

See `examples/ceo-engineer-delegation/run.py`.

### pending_actions — HITL gate

Irreversible tools (git push, file delete, API calls with side effects) don't
run immediately. AgentLoop calls `tool.is_irreversible()` before execution; if
it returns `True`, the action is queued in `pending_actions` and the LLM is
told to wait. The operator approves via CLI (`!approve N`) or Discord, then the
action executes.

---

## AgentLoop — how one agent thinks

`core/orchestrator/agent_loop.py`

```
run(message) →
  loop (max 10 turns):
    call runner.run(message, messages_history)
    if no tool_calls → return response
    for each tool_call:
      if tool.is_irreversible() → queue in pending_actions → tell LLM
      else → tool.run() → append result
    append results → continue loop
  → [error] max turns exceeded
```

Key design choices:
- **MAX_TURNS = 10** prevents infinite loops when a tool result confuses the agent.
- **Tool dispatch is synchronous** — no async fan-out, intentionally simple.
- **System prompt + tool list** is what differentiates agents, not subclass hierarchies.
- **Sessions** are keyed by `session_id` (a short UUID). ClaudeCodeRunner can
  resume a Claude Code CLI session across calls via `--resume`.

---

## Agents — role vs mechanism

```
agents/
├── ceo/         CEO agent — delegator pattern, single point of contact
├── engineer/    Technical agent — code review, ADRs, implementation
├── product/     Product agent — PRDs, user stories, prioritisation
├── marketing/   Content agent — copy, campaign planning
├── finance/     ← stub (see below for how to add a full agent)
├── operations/  ← stub
└── sales/       ← stub
```

Each agent is a plain dict/config passed to `AgentLoop`:

```python
AgentLoop(
    agent_id="engineer",
    runner=runner,          # LLMRunner instance
    brain=brain,            # BrainService instance
    tools=[...],            # list[BaseTool]
    system_prompt="...",    # role definition
)
```

No abstract base class hierarchy. The loop logic is the same for all agents;
only the inputs differ.

### Adding a new agent

1. Create `agents/yourname/agent.py` — define `SYSTEM_PROMPT` and `get_tools()`.
2. Register in the orchestrator's agent roster.
3. Optionally add a goal seed in `scripts/seed_demo.py`.

The stubs in `agents/finance/`, `agents/operations/`, `agents/sales/` show
the minimum skeleton.

---

## LLM runner abstraction

All three runners implement `LLMRunner.run()` → `RunnerResult`. The rest of the
system never knows which runner is active.

| Runner | When | Cost |
|---|---|---|
| `MockRunner` | CI, demos, offline | Free |
| `APIRunner` | Development, simple agents | API credits |
| `ClaudeCodeRunner` | Full agentic power, production | API credits + sidecar container |

Switch via `LLM_RUNNER` env var: `mock` (default), `api`, `claude_code`.

For a full explanation of why the sidecar exists and when you'd want it, see
[`docs/dual-runner-pattern.md`](dual-runner-pattern.md).

---

## Data flow — one delegation cycle

```
User: "Review the Q3 architecture decision"
  │
  ▼ Orchestrator classifies → engineer
  │
  ▼ CEO agent (if active):
    brain.set_goal(owner="engineer", title="Review Q3 ADR", ...)
  │
  ▼ Cron dispatcher polls PENDING goals →
    AgentLoop(agent_id="engineer").run("Review Q3 ADR")
  │
  ▼ Engineer runner calls LLM with:
      system_prompt + memory_context + task
  │
  ▼ LLM calls tools (Read, Grep, remember) → loop
  │
  ▼ Final response → brain.record_episode(type="deliverable")
    brain.update_goal(status="COMPLETED")
  │
  ▼ User sees result via Discord / CLI
```

---

## Observability

Every LLM call emits four Prometheus metrics via `core/observability/metrics.py`:

```
ai_org_tokens_total{agent, token_type}   — input / output / cache_write / cache_read
ai_org_requests_total{agent, status}     — success / rate_limited / error
ai_org_response_seconds{agent}           — histogram of end-to-end turn latency
ai_org_cost_usd_total{agent}             — accumulated estimated USD cost
```

The `token_type` split is the most important one. Claude caches repeated content
in system prompts and injected memory blocks. `cache_read` tokens cost 10× less
than fresh `input` tokens. Without this split you can't tell whether your memory
injection strategy is saving money or just making prompts bigger.

Both `APIRunner` and `ClaudeCodeRunner` call `record_llm_call()` automatically —
no changes needed in the agent or orchestrator layer. `prometheus_client` is
optional: if not installed, all calls are silent no-ops.

Expose metrics at startup:

```python
from core.observability.metrics import start_metrics_server
start_metrics_server()   # GET /metrics on :9101
```

Scrape with VictoriaMetrics (or any Prometheus-compatible scraper) and visualise
in Grafana. See [`docs/observability.md`](observability.md) for the full setup
and a Grafana dashboard starter.

---

## What this architecture does NOT have

- **Authentication / authorisation** — bring your own at the entrypoint layer.
- **Horizontal scale** — SQLite is single-writer. Swap to Postgres at the Brain
  layer if you need multiple writer processes.
- **Streaming** — AgentLoop blocks until done. WebSocket streaming is left as
  an exercise.
- **Parallel agent fan-out** — the router dispatches sequentially. Useful future
  work if you need simultaneous multi-agent responses.
