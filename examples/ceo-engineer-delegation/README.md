# Example: CEO → Engineer Delegation

Demonstrates the most fundamental pattern in an AI org: **one agent delegating
a task to another via durable shared memory**, not via direct function calls or
shared in-process context.

## Architectural claim

> Shared memory beats shared context.

CEO and Engineer are two separate `AgentLoop` instances. They share no Python
objects, no conversation history, no in-process state. Coordination happens
entirely through `BrainService` — a single SQLite file both processes read and
write.

If either agent crashed mid-task and restarted, the goal would still be in the
`agent_goals` table and the other agent would pick it up on the next poll.

## What you'll see

```
──────────────────────────────────────────────────────────────────
  Step 1  CEO receives task from user
──────────────────────────────────────────────────────────────────
  User → CEO: I need the engineer to review the auth module for SQL
              injection risks. Please delegate this and tell me who
              you sent it to.

  CEO:
    I've delegated the SQL injection review of the auth module to
    the Engineer. They've been assigned the task and will focus on
    parameterised queries and ORM usage.

──────────────────────────────────────────────────────────────────
  Step 2  Engineer checks pending goals
──────────────────────────────────────────────────────────────────
  Engineer sees goal #1: Review auth module for SQL injection risks

  Engineer:
    Understood. I'll review the auth module for SQL injection risks,
    focusing on: (1) raw query construction, (2) parameterised
    queries and ORM usage, (3) input validation at boundaries.
    Marking this IN_PROGRESS now.

──────────────────────────────────────────────────────────────────
  Step 3  Shared memory state after delegation
──────────────────────────────────────────────────────────────────
  Agent status board:
    ceo           Delegating auth review to Engineer
    engineer      Review auth module for SQL injection...

  Last 2 episode(s):
    [deliverable ] engineer: Auth review acknowledged
    [event       ] ceo: Delegated task to engineer
```

## How to run

```bash
# Quickest path — Docker handles Brain + seed data automatically:
make demo

# Direct run (needs brain.db seeded first):
python scripts/init_brain.py
python scripts/seed_demo.py
python examples/ceo-engineer-delegation/run.py
```

## Key code locations

| What | Where |
|------|-------|
| CEO agent definition | `agents/ceo/agent.py` |
| Engineer agent definition | `agents/engineer/agent.py` |
| AgentLoop (shared loop logic) | `core/orchestrator/agent_loop.py` |
| BrainService (shared memory) | `core/brain/service.py` |
| Demo seed data | `scripts/seed_demo.py` |

## What changes if you use a real LLM

Set `LLM_RUNNER=api` and `ANTHROPIC_API_KEY=sk-ant-...` in `.env`.
The loop logic and memory patterns are identical — only the runner changes.
