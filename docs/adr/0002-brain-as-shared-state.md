# ADR-0002: Brain as Shared State

**Status:** Accepted
**Date:** 2026-06-10

## Context

Multi-agent systems fail in two common ways:

1. **Context collapse.** Pass the full conversation history to every agent on
   every call. Works up to ~20k tokens, then latency spikes, cost multiplies,
   and the model starts ignoring the middle.

2. **Shared mutable chaos.** Give every agent direct database access. Works
   until two agents write conflicting facts with no record of why.

We needed a third path: structured shared state with clean read/write semantics
and no giant context window.

Additional constraints:
- Zero external infrastructure for the tutorial case (no Redis, no Postgres,
  no vector DB, no message queue).
- Each agent must be able to "wake up" after a container restart and know what
  it was doing.
- Irreversible actions (git push, file delete) must not auto-execute; a human
  approval step is required.

## Decision

Introduce a single **Brain** service (`core/brain/`) backed by SQLite. All
agents share one Brain instance; no agent talks directly to the database. The
API is intentionally narrow: agents read and write through typed endpoints, not
raw SQL.

Brain exposes five subsystems:

### 1. Namespaced key-value memory

```
private:{agent_id}/key  →  only that agent reads/writes
shared/key              →  all agents share
```

Private namespaces prevent accidental cross-contamination. Shared namespaces
are used for facts that multiple agents need (current user, project context,
active deadlines). The boundary is convention, not ACL — appropriate for a
tutorial; a production system might enforce it.

### 2. Episodic log

Every significant event — deliverable, decision, error, handoff — is appended
via `record_episode(agent_id, type, title, body)`. Agents query their own
recent episodes at session start. This is how an agent "remembers" across
container restarts without loading the full conversation history.

### 3. Semantic knowledge store

Free-text facts indexed with SQLite FTS5. Agents add knowledge; runners query
it at call time and inject the top-K results into the prompt. No vector
embeddings, no external service — FTS5 is good enough for tutorial-scale
knowledge bases (< 50k entries).

### 4. agent_goals — durable task queue

```sql
agent_goals(id, owner_agent, title, body, status, created_at, updated_at)
-- status: PENDING | IN_PROGRESS | COMPLETED | FAILED
```

Delegation by string-passing (calling a function with `task="do X"`) is
fragile: if the process dies mid-task, the task is lost. Goals persist through
restarts. The cron dispatcher polls `PENDING` goals and claims them atomically.
Completed goals are observable — the CEO can see what the Engineer finished
without asking.

### 5. pending_actions — HITL gate

```sql
pending_actions(id, agent_id, tool_id, tool_input, status, created_at)
-- status: PENDING | APPROVED | REJECTED
```

Before executing any irreversible tool, the AgentLoop checks
`tool.is_irreversible()`. If true, the action is written here and the LLM is
told to wait. The operator approves or rejects via CLI or Discord. Execution
only happens after `APPROVED`. This prevents runaway automation from taking
actions that can't be undone.

## Consequences

**Good:**
- Agents are stateless containers. The Brain holds all durable state; an agent
  can crash, restart, and resume without data loss.
- Observable by design. You can inspect the entire system state with
  `SELECT * FROM ...` — no black-box internal state.
- No infrastructure dependencies for the tutorial case. One SQLite file per
  environment.
- The narrow API makes it straightforward to swap the backend. The Brain
  service is the only layer that knows SQLite is underneath.

**Bad:**
- SQLite is single-writer. If you run multiple Python workers (e.g. in
  production), they'll contend on writes. Mitigation: WAL mode + write
  serialisation, or swap to Postgres at the Brain layer.
- FTS5 semantic search is keyword-based, not semantic. For real semantic
  similarity, replace the `knowledge` table with a vector store (pgvector,
  Chroma, etc.) and keep the same API surface.
- The HITL gate adds latency. Irreversible actions block until a human approves.
  For fully automated pipelines this is undesirable; remove `is_irreversible()`
  from the relevant tools in that case.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Pass full history to each agent** | Context collapse at scale; cost multiplies with every agent |
| **Shared Postgres + raw SQL** | External infra dependency; too heavy for a tutorial |
| **Redis for key-value, Postgres for goals** | Two infra dependencies; operational overhead not justified |
| **Agent-local SQLite files (no sharing)** | Agents can't read each other's state; coordination impossible |
| **LangChain memory** | Opaque implementation; harder to audit and extend |

## References

- `core/brain/service.py` — Brain service implementation
- `core/brain/agent_goals.py` — goals table and status transitions
- `docs/architecture.md#brain` — narrative walkthrough
- `examples/ceo-engineer-delegation/run.py` — goals-based delegation example
- `examples/memory-namespaces/run.py` — namespace isolation example
