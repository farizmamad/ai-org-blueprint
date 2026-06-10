# ADR-0003: Pluggable Runner Pattern

**Status:** Accepted
**Date:** 2026-06-10

## Context

The tutorial repo needs to be runnable with no API key (for CI, offline demos,
and readers who just want to trace the architecture). At the same time, the
article it accompanies describes a production system — Faith / ai-angels — where
agents use Claude Code CLI to get native file, shell, and MCP tool access.

A single hardcoded LLM backend would force a choice: either the repo requires
an API key (bad for tutorials) or it doesn't show the real production pattern
(misleading for readers who want to build something real).

We also observed that moving from "LLM that can generate text" to "LLM that can
act on the filesystem" changes the architecture meaningfully — it's not a config
flag, it's a second container. The design should make that boundary explicit, not
hide it behind a single env var.

## Decision

Abstract all LLM invocations behind a single `LLMRunner` interface:

```python
class LLMRunner(ABC):
    def run(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[BaseTool],
        session_id: str | None = None,
    ) -> RunnerResult:
        ...
```

`RunnerResult` carries `response`, `tool_calls`, `usage`, and optionally a new
`session_id` for backends that support session continuity.

Ship three concrete implementations, selected by `LLM_RUNNER` env var:

### MockRunner (`mock`, default)

Returns deterministic placeholder text without network calls. The companion
`scripts/mock_llm_server.py` exposes an Anthropic-compatible
`POST /v1/messages` endpoint so that `APIRunner` can also be pointed at it for
integration testing without real API credits.

### APIRunner (`api`)

Calls the Anthropic Messages API directly. Stateless per call — session
continuity requires passing the full `messages` history. Supports tool use via
standard `tool_use` content blocks. Requires `ANTHROPIC_API_KEY`.

### ClaudeCodeRunner (`claude_code`)

The opt-in production runner. Delegates LLM calls to a sidecar container
running `claude -p` (Claude Code CLI) over HTTP. Requires a second container
(`Dockerfile.claude-runner`); enabled via `docker-compose.full.yml`.

The sidecar gives agents native access to `Bash`, `Read`, `Write`, `Grep`, and
MCP tools — capabilities that would require explicit tool definitions in the
Python layer with `APIRunner`. It also provides session continuity: the CLI
maintains conversation context per session, and `ClaudeCodeRunner` stores the
session ID in Brain so it can `--resume` across restarts.

This runner mirrors the exact pattern used in the Faith production system
described in the companion article.

## Why the sidecar, not a subprocess?

Running `claude -p` as a subprocess from Python would work. Two reasons to use
a sidecar instead:

1. **Image isolation.** The Python container stays Python-only (lean, fast
   builds). The sidecar is Node.js + Claude CLI. The two rarely change at the
   same time — separate layers means separate rebuild cycles.

2. **Portability.** Other services (future webhook handler, cron dispatcher)
   can call the same sidecar HTTP endpoint. A subprocess is owned by one process;
   an HTTP service is owned by the network.

## Consequences

**Good:**
- The tutorial is runnable with `make demo` and zero API keys.
- The production pattern (ClaudeCodeRunner + sidecar) is available as opt-in,
  not a rewrite.
- The runner boundary is explicit: the rest of the system never imports
  `anthropic` or `subprocess` directly. All LLM coupling is in one directory.
- Adding a new runner (Gemini, local Ollama, etc.) requires one new file that
  implements `LLMRunner.run()`.

**Bad:**
- Three runners is three code paths to maintain. `MockRunner` in particular can
  diverge from real LLM behaviour and produce tests that pass but don't catch
  real failure modes. Mitigation: integration tests that run against
  `mock_llm_server.py` (same HTTP protocol as APIRunner).
- `ClaudeCodeRunner` couples the architecture to Claude Code CLI. If Anthropic
  changes the CLI interface, the sidecar needs updating. Mitigation: the sidecar
  (`claude_runner/main.py`) is isolated; only it needs to change.
- Session continuity via Brain-stored IDs means the Brain is load-bearing for
  agent conversational state. If Brain data is lost, agents lose their session
  context. Mitigation: Brain SQLite file should be on a mounted volume.

## Graduated adoption path

```
MockRunner  →  APIRunner  →  ClaudeCodeRunner
(no key)       (one key)      (key + sidecar)

make demo     make demo      make demo-full
```

The recommendation: start with `MockRunner`, upgrade to `APIRunner` when you
need real LLM responses, upgrade to `ClaudeCodeRunner` only when agents need
to act on the filesystem or you want the exact production pattern.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Single APIRunner, skip Mock** | Breaks offline/CI use case; costs money to run the tutorial |
| **Single ClaudeCodeRunner** | Requires Node.js + sidecar for even the simplest demo |
| **LangChain LLM abstraction** | External dependency; black-box error messages; harder to trace |
| **Subprocess `claude -p` from Python** | Less portable; owned by one process; harder to test |
| **OpenAI-compatible proxy** | Adds another infra piece; complexity not justified for tutorial |

## References

- `core/agents/runners/` — all three runner implementations
- `claude_runner/main.py` — sidecar HTTP server
- `Dockerfile.claude-runner` — sidecar image
- `docker-compose.full.yml` — opt-in overlay for ClaudeCodeRunner
- `docs/dual-runner-pattern.md` — narrative guide with decision tree
- `scripts/mock_llm_server.py` — Anthropic-compatible mock endpoint
