# Dual-Runner Pattern

This repo ships three LLM runner implementations. Most readers need one; this
document explains all three so you can pick the right one — and understand why
the ClaudeCodeRunner sidecar exists at all.

---

## The three runners

| Runner | `LLM_RUNNER=` | Requires | Best for |
|---|---|---|---|
| `MockRunner` | `mock` (default) | Nothing | CI, offline demos |
| `APIRunner` | `api` | `ANTHROPIC_API_KEY` | Dev, simple agents |
| `ClaudeCodeRunner` | `claude_code` | API key + sidecar | Full agentic power |

All three implement the same interface (`LLMRunner.run()` → `RunnerResult`).
The rest of the system never knows which runner is active.

---

## Option A — MockRunner (default)

`core/agents/runners/mock_runner.py`

Returns deterministic placeholder text without making any network calls. The
mock LLM server (`scripts/mock_llm_server.py`) exposes an Anthropic-compatible
`POST /v1/messages` endpoint so you can also route `APIRunner` at it by setting
`ANTHROPIC_BASE_URL=http://mock-llm:8080`.

Use this when:
- You want to trace the architecture without an API key.
- Running CI tests.
- Developing tooling that wraps the agent loop.

```bash
# Default — mock runner, no key needed
make demo
```

---

## Option B — APIRunner

`core/agents/runners/api_runner.py`

Calls the Anthropic Messages API directly. Supports tool use via the standard
`tool_use` content blocks. Session continuity is not natively supported — each
`run()` call is stateless unless you pass the full `messages` history.

Use this when:
- You want real LLM responses.
- Your agents don't need file edits or shell access.
- You want the simplest possible production setup.

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
echo "LLM_RUNNER=api"              >> .env
make demo
```

Model and max tokens are configurable via env vars:

```bash
LLM_MODEL=claude-sonnet-4-6        # any current Anthropic model
LLM_MAX_TOKENS=2048
```

---

## Option C — ClaudeCodeRunner (opt-in)

`core/agents/runners/claude_code_runner.py`

This is the production pattern from the
[Faith / ai-angels implementation](https://github.com/your-org/ai-angels)
that the companion article describes. It adds a second container — the
`claude-runner` sidecar — that wraps `claude -p` as an HTTP service.

```bash
echo "LLM_RUNNER=claude_code"       >> .env
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
make demo-full
```

### Why a sidecar, not a subprocess?

Two reasons:

1. **Image separation.** The main Python container stays Python-only; the
   sidecar is Node.js + Claude CLI. Rebuilds are fast because the two rarely
   change at the same time.

2. **Agent capabilities.** When Claude runs inside Claude Code CLI, it gets
   `Bash`, `Read`, `Write`, `Grep`, and MCP tools natively — no explicit
   tool definitions needed in the Python layer. Agents can edit files, run
   shell commands, and call Brain endpoints as first-class operations.

### Session continuity

The Claude Code CLI maintains a conversation context per session. When you call
`claude --resume SESSION_ID`, the CLI picks up exactly where it left off — full
history, no reinjection needed.

ClaudeCodeRunner stores the Claude session ID in Brain:

```
private:{agent_id}/_claude_session_id   → the Claude session ID string
private:{agent_id}/_claude_session_ts   → ISO timestamp of last use
```

On the next call, the runner loads the ID and resumes. A TTL
(`CLAUDE_SESSION_MAX_AGE_SECS`, default 10 min) prevents stale sessions from
being resumed after a long idle period — the runner starts a fresh session
instead.

This is why agents "remember" what they were doing across container restarts:
the session ID persists in Brain even if the Python process dies.

### Memory context injection

Before every call, the runner fetches:

1. **Long-term facts** — `brain.recall_namespace(private:{agent_id})`
2. **Recent episodes** — last 5 episodes for this agent
3. **Relevant knowledge** — semantic FTS search against the task text

These are injected into the prompt *before* the task. The agent sees its
private facts and recent history without needing to call Brain manually.

### Prompt construction

The full prompt is assembled in layers — identical to the Faith production
pattern:

```
1. System prompt         (role, personality, responsibilities)
2. Memory context        (facts + episodes + relevant knowledge)
3. Reflection section    (instruct agent to verify before concluding)
4. Workspace section     (repo paths, working directory — caller-provided)
5. Brain HTTP API docs   (how to curl Brain endpoints)
6. HITL actions docs     (how to queue irreversible actions for approval)
7. Task                  (the actual user message)
```

### Token usage tracking

The sidecar returns `input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`, and `cost_usd` in its response. ClaudeCodeRunner
captures all of these, logs them, and returns them in `RunnerResult.usage`.

### Fallback

If the sidecar is unreachable, ClaudeCodeRunner falls back to a secondary
`LLMRunner` (e.g. `APIRunner`) if one was provided at construction time. This
mirrors Faith's own fallback logic — the agent degrades gracefully instead of
erroring.

---

## Choosing the right runner

```
                        ┌─────────────────┐
                        │  Need real LLM? │
                        └────────┬────────┘
                     No /        \ Yes
                        ▼         ▼
                   MockRunner   Need file edits
                                / shell / MCP?
                           No /     \ Yes
                              ▼      ▼
                          APIRunner  ClaudeCodeRunner
                                     (+ make demo-full)
```

Start with `MockRunner`. Move to `APIRunner` when you need real responses.
Move to `ClaudeCodeRunner` only when your agents need to act on the filesystem
or you want the exact production pattern from the article.

---

## Sidecar architecture (docker-compose.full.yml)

```
┌──────────────────────────┐     HTTP :8766    ┌──────────────────────────┐
│  demo container          │──────────────────▶│  claude-runner container │
│  (Python)                │                   │  (Node.js + Claude CLI)  │
│                          │◀──────────────────│                          │
│  ClaudeCodeRunner        │  RunnerResult JSON │  POST /run              │
│  ├── _build_prompt()     │                   │  → claude -p <prompt>   │
│  ├── _load_session()     │                   │  → returns result + sid  │
│  └── _save_session()     │                   │    + usage               │
└───────────┬──────────────┘                   └──────────────────────────┘
            │
            │ HTTP :8765
            ▼
┌──────────────────────────┐
│  brain container         │
│  (SQLite + FastAPI)      │
│  /remember /recall       │
│  /goals /actions         │
│  /mcp/ (MCP endpoint)    │
└──────────────────────────┘
```

The claude-runner sidecar also receives the Brain MCP URL so Claude Code can
call `brain_remember`, `brain_recall`, etc. as native MCP tools — no curl
required from inside the agent.

Source: `claude_runner/main.py`, `Dockerfile.claude-runner`.
