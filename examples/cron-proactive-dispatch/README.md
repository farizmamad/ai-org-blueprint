# Example: Proactive Cron Dispatch

Demonstrates the gap between a **reactive** and an **autonomous** AI org:

| Mode | When does the agent run? |
|------|--------------------------|
| Reactive | Only when a human sends a message |
| Autonomous | A scheduler polls the goal queue and starts agents proactively |

This example seeds one `PENDING` goal for the Engineer, starts an
[APScheduler](https://apscheduler.readthedocs.io/) loop that polls every 3
seconds, dispatches the goal when found, then exits cleanly. No human message
is required after the initial seed.

## Architectural claim

> Multi-agent only beats single-agent if it's autonomous.

The scheduler is the bridge from reactive to autonomous. Without it,
`agent_goals` is a write-only table — tasks pile up and nobody runs them.

## What you'll see

```
────────────────────────────────────────────────────────────────
  ai-org-blueprint  ·  Proactive dispatch demo
  Runner: mock  ·  Brain: ./data/brain.db
────────────────────────────────────────────────────────────────

  [setup] Seeded 1 PENDING goal for Engineer.

  Starting scheduler (poll interval: 3s, max cycles: 5)...
  Ctrl-C to stop early.

  [tick 1] Found goal #1: Write a brief security note about SQL injection ...
  [cron] Marking IN_PROGRESS and dispatching to Engineer.

  Engineer reply:
    I'll write a concise security note on SQL injection risks in the
    auth module, covering parameterised queries and ORM usage.
    The key risk is string interpolation in raw queries — using
    `cursor.execute(f"SELECT ... WHERE id={id}")` instead of
    `cursor.execute("... WHERE id=?", (id,))`.

  [cron] Goal marked COMPLETED. Exiting.

Done.
```

## How to run

```bash
# Make target (uses local venv):
make demo-cron

# Direct run:
python scripts/init_brain.py
python examples/cron-proactive-dispatch/run.py
```

The demo is self-contained — if no `PENDING` goals exist for the Engineer, it
seeds one automatically before starting the scheduler.

## Key code locations

| What | Where |
|------|-------|
| Scheduler loop | `examples/cron-proactive-dispatch/run.py` |
| Goal storage | `core/brain/service.py` → `set_goal`, `update_goal` |
| Engineer agent | `agents/engineer/agent.py` |

## Extending this pattern

In a production deployment, this scheduler would run as a separate container or
cron job alongside the Brain API. It polls `agent_goals` for `PENDING` tasks,
dispatches them to the appropriate agent, and marks them `COMPLETED` (or
`FAILED` with a retry count).

See `docker-compose.yml` and `ADR-003` for how the runner pattern connects here.
