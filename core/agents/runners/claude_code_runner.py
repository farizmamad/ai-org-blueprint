"""
ClaudeCodeRunner — runs agents through the Claude Code CLI sidecar.

This is the production pattern from the ai-angels/Faith implementation, adapted
for the tutorial repo. It adds a second container (claude-runner) that wraps
`claude -p` as an HTTP service, so the main Python container stays Python-only
while agents get full agentic capabilities: file edits, shell, MCP tools, etc.

Why a sidecar instead of subprocess?
  Calling `claude` as a subprocess from Python works, but it requires Node.js
  in the same container image and makes rebuilds slow. The sidecar pattern
  separates concerns: Python image builds are fast; the Node.js/claude image
  only rebuilds when Claude CLI versions change.

Session continuity (durable, Brain-backed):
  Each agent stores its Claude session ID in Brain under
  private:{agent_id}/_claude_session_id. On subsequent calls, the runner
  loads this ID and passes --resume so the agent's full context stays alive
  across container restarts. A TTL (_SESSION_MAX_AGE_SECS, default 10 min)
  prevents stale sessions from being resumed after a long idle period.

  When agent_id + brain are NOT provided (e.g. standalone tests), the runner
  falls back to an in-memory dict — functional but not restart-safe.

Memory context injection:
  When agent_id + brain are provided, the runner fetches the agent's recent
  long-term memory, episode history, and semantically relevant knowledge, then
  injects them into the prompt before dispatching to the sidecar. Claude Code
  therefore "remembers" decisions, ongoing tasks, and important facts without
  needing to search Brain manually on every invocation.

Prompt construction:
  The full prompt sent to claude -p is assembled in layers — identical to the
  Faith production pattern:
    1. System prompt (role, personality, responsibilities)
    2. Memory context (long-term facts, recent episodes, relevant knowledge)
    3. Reflection instructions (instruct the agent to verify before concluding)
    4. Workspace instructions (repo paths, working directory — caller-provided)
    5. Brain HTTP API instructions (how to curl Brain endpoints)
    6. HITL actions instructions (how to queue irreversible actions for approval)
    7. Task (the actual user message)

Token usage tracking:
  The sidecar returns token counts and cost_usd for each run. This runner
  captures, logs, and returns that data in RunnerResult.usage — identical
  to how Faith tracks per-agent API spend.

Fallback:
  If the sidecar is unavailable, the runner falls back to a secondary
  LLMRunner (e.g. APIRunner) if one was provided at construction time.
  This mirrors Faith's fallback from ClaudeCodeRunner → AgentLoop.

Tool access for agents:
  Unlike APIRunner, this runner does NOT pass `tools` to an Anthropic API
  endpoint — the Claude Code CLI handles tool dispatch internally. Agents
  get Claude Code's built-in tools (Bash, Read, Write, Grep, etc.) plus
  any MCP tools configured in the sidecar.

  If brain_url is set, the runner automatically passes the Brain MCP
  endpoint to the sidecar, so agents can call brain_remember, brain_recall,
  etc. directly as native tools — no manual curl needed.

Opt-in setup:
  Set LLM_RUNNER=claude_code in .env and run `make demo-full`.
  Requires ANTHROPIC_API_KEY and Docker (the sidecar container).

See docs/dual-runner-pattern.md for the full decision rationale.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from core.agents.runners.base import LLMRunner, RunnerResult
from core.observability.metrics import record_llm_call

if TYPE_CHECKING:
    from core.brain.service import BrainService

logger = logging.getLogger(__name__)

_DEFAULT_RUNNER_URL   = "http://claude-runner:8766"
_DEFAULT_BRAIN_URL    = "http://brain:8765"
_DEFAULT_TIMEOUT      = 300  # seconds — generous for long agentic tasks
_SESSION_KEY          = "_claude_session_id"
_SESSION_TS_KEY       = "_claude_session_ts"
_SESSION_MAX_AGE_SECS = int(os.getenv("CLAUDE_SESSION_MAX_AGE_SECS", str(10 * 60)))


# ── Prompt instruction blocks (same structure as Faith production) ─────────────

_REFLECTION_INSTRUCTIONS = """\
## Reflection Before Answering

For tasks that require deep analysis, do this review before finalising your answer:
1. Is there information you have not yet verified directly (file not read, output not checked)?
2. Are there tools or repos that are relevant but you have not used?
3. Is your conclusion consistent with the data available, not just assumptions?

Skip this for quick answers, status checks, or short confirmations.
You decide whether the task warrants reflection — the system does not."""


_BRAIN_API_INSTRUCTIONS = """\
## Brain HTTP API

You have access to the Brain HTTP API for persistent memory.
Use the Bash tool with curl to interact. Base URL: {brain_api_url}

Available endpoints:
- POST /remember         — store a fact in long-term memory
- GET  /recall           — retrieve one fact
- POST /record_episode   — log an episode (decision, deliverable, error)
- POST /add_knowledge    — add an entry to semantic memory
- GET  /search_knowledge — search knowledge by query

Example usage:
```bash
# Store a fact
curl -s -X POST {brain_api_url}/remember \\
  -H 'Content-Type: application/json' \\
  -d '{{"namespace": "private:{agent_id}", "key": "key_name", "value": "value"}}'

# Recall a fact
curl -s "{brain_api_url}/recall?namespace=private:{agent_id}&key=key_name"

# Log an episode after completing a task
curl -s -X POST {brain_api_url}/record_episode \\
  -H 'Content-Type: application/json' \\
  -d '{{"agent_id": "{agent_id}", "type": "deliverable", "title": "Short title", "body": "Detail"}}'

# Search knowledge
curl -s "{brain_api_url}/search_knowledge?query=topic+to+search&namespaces=private:{agent_id},shared"
```"""


_HITL_ACTIONS_INSTRUCTIONS = """\
## HITL Actions (Irreversible Actions)

For actions that require human approval before execution, queue them here:

```bash
POST {brain_api_url}/actions/{{tool_id}}
Body: {{"agent_id": "{agent_id}", "tool_input": {{...}}}}
Response: {{"queued": true, "action_id": N, "description": "..."}}
```

Response is immediate — no need to wait. The operator approves via `!approve N`.

### Check pending actions

```bash
curl -s {brain_api_url}/actions/pending
```"""


# ── Runner ─────────────────────────────────────────────────────────────────────

class ClaudeCodeRunner(LLMRunner):
    """
    LLMRunner implementation that delegates to the claude-runner sidecar.

    Matches the Faith production pattern:
      - Brain-backed session persistence (survives container restarts)
      - Memory context injection (long-term facts + episodes + relevant knowledge)
      - Full prompt construction (system + memory + instructions + task)
      - Token usage tracking and cost logging from sidecar response
      - Fallback to a secondary LLMRunner when the sidecar is unavailable

    Without agent_id/brain the runner still works, but sessions are
    in-memory only and no context is injected — suitable for tests and
    standalone use, but not for production multi-agent deployments.
    """

    def __init__(
        self,
        runner_url:             str | None            = None,
        brain_url:              str | None            = None,
        timeout:                int                   = _DEFAULT_TIMEOUT,
        agent_id:               str | None            = None,
        brain:                  "BrainService | None" = None,
        fallback_runner:        "LLMRunner | None"    = None,
        workspace_instructions: str | None            = None,
    ) -> None:
        """
        Args:
            runner_url:             URL of the claude-runner sidecar (default: CLAUDE_RUNNER_URL env).
            brain_url:              URL of the Brain API (default: BRAIN_API_URL env).
            timeout:                Seconds to wait for the sidecar per call.
            agent_id:               Agent identifier — enables Brain-backed sessions and memory injection.
            brain:                  BrainService instance — enables full memory context features.
            fallback_runner:        Secondary LLMRunner to use if the sidecar is unavailable.
                                    Mirrors Faith's fallback from ClaudeCodeRunner → AgentLoop.
            workspace_instructions: Instructions describing the agent's working directory and repos.
                                    Injected into every prompt between reflection and Brain API sections.
                                    Example: "## Workspace\\n- /app/src — main source, writable\\n..."
        """
        try:
            import httpx  # noqa: F401
        except ImportError as e:
            raise RuntimeError("httpx not installed. Run `pip install httpx`.") from e

        self._runner_url             = runner_url or os.environ.get("CLAUDE_RUNNER_URL", _DEFAULT_RUNNER_URL)
        self._brain_url              = brain_url  or os.environ.get("BRAIN_API_URL",     _DEFAULT_BRAIN_URL)
        self._timeout                = timeout
        self._agent_id               = agent_id
        self._brain                  = brain
        self._fallback_runner        = fallback_runner
        self._workspace_instructions = workspace_instructions

        # In-memory session map — only used when brain is not provided.
        # Lost on restart — always prefer brain + agent_id in production.
        self._session_map: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "claude_code"

    def run(
        self,
        message:       str,
        session_id:    str | None                  = None,
        system_prompt: str | None                  = None,
        tools:         list[dict[str, Any]] | None = None,
        messages:      list[dict[str, Any]] | None = None,
    ) -> RunnerResult:
        # NOTE: `tools` is intentionally ignored here. Claude Code dispatches
        # tools internally (Bash, Read, Write, MCP) — the agent does not go
        # through the Anthropic tool_use API when this runner is active.

        prompt    = self._build_prompt(message, system_prompt)
        resume_id = self._load_session(session_id)
        mcp_url   = f"{self._brain_url}/mcp/" if self._brain_url else None

        result, new_claude_sid, usage = self._invoke(prompt, resume_id, mcp_url)

        if result is None and resume_id:
            logger.warning(
                "[ClaudeCodeRunner] resume %s failed — retrying with fresh session",
                resume_id,
            )
            result, new_claude_sid, usage = self._invoke(prompt, resume_id=None, mcp_url=mcp_url)

        if result is None:
            return self._fallback(message, session_id, system_prompt, tools, messages)

        if session_id and new_claude_sid:
            self._save_session(session_id, new_claude_sid)

        if self._brain and self._agent_id:
            self._record_episode(message, result)

        cost_usd = usage.get("cost_usd", 0.0)
        logger.info(
            "[ClaudeCodeRunner] done agent=%s chars=%d session=%s | "
            "in=%d out=%d cache_w=%d cache_r=%d total=%d cost=$%.4f",
            self._agent_id, len(result), new_claude_sid or resume_id,
            usage.get("input_tokens", 0), usage.get("output_tokens", 0),
            usage.get("cache_creation_input_tokens", 0), usage.get("cache_read_input_tokens", 0),
            usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            cost_usd,
        )

        record_llm_call(
            agent    = self._agent_id or "unknown",
            usage    = usage,
            status   = "success",
            duration = usage.get("duration_secs", 0.0),
            cost_usd = cost_usd,
        )

        return RunnerResult(
            response=result.strip(),
            session_id=session_id,
            usage=usage,
        )

    # ── Session management ────────────────────────────────────────────────────

    def _load_session(self, session_id: str | None) -> str | None:
        """Load Claude session ID. Brain-backed if available, else in-memory."""
        if not session_id:
            return None
        if self._brain and self._agent_id:
            return self._load_brain_session()
        return self._session_map.get(session_id)

    def _save_session(self, session_id: str, claude_sid: str) -> None:
        """Persist Claude session ID. Brain-backed if available, else in-memory."""
        if self._brain and self._agent_id:
            self._save_brain_session(claude_sid)
        else:
            self._session_map[session_id] = claude_sid

    def _load_brain_session(self) -> str | None:
        try:
            ns         = f"private:{self._agent_id}"
            claude_sid = self._brain.recall(ns, _SESSION_KEY)  # type: ignore[union-attr]
            if not claude_sid:
                return None
            ts_str = self._brain.recall(ns, _SESSION_TS_KEY)  # type: ignore[union-attr]
            if ts_str:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts_str)).total_seconds()
                if age > _SESSION_MAX_AGE_SECS:
                    logger.info(
                        "[ClaudeCodeRunner] agent=%s session expired (age=%.0fm > max=%.0fm)",
                        self._agent_id, age / 60, _SESSION_MAX_AGE_SECS / 60,
                    )
                    return None
            return claude_sid
        except Exception:
            return None

    def _save_brain_session(self, claude_sid: str) -> None:
        try:
            ns = f"private:{self._agent_id}"
            self._brain.remember(ns, _SESSION_KEY, claude_sid, source="claude_code_runner")  # type: ignore[union-attr]
            self._brain.remember(  # type: ignore[union-attr]
                ns, _SESSION_TS_KEY,
                datetime.now(timezone.utc).isoformat(),
                source="claude_code_runner",
            )
        except Exception as e:
            logger.warning("[ClaudeCodeRunner] failed to save session to Brain: %s", e)

    # ── Prompt construction ───────────────────────────────────────────────────

    def _build_prompt(self, message: str, system_prompt: str | None) -> str:
        """
        Assemble the full prompt for `claude -p`.

        Layer order matches the Faith production pattern:
          system prompt → memory context → reflection → workspace → brain API → HITL → task
        """
        parts: list[str] = []

        if system_prompt:
            parts.append(system_prompt)

        ctx = self._build_context(message) if (self._brain and self._agent_id) else ""
        if ctx:
            parts.append(f"# Memory Context\n\n{ctx}")

        parts.append(_REFLECTION_INSTRUCTIONS)

        if self._workspace_instructions:
            parts.append(self._workspace_instructions)

        if self._brain_url and self._agent_id:
            parts.append(
                _BRAIN_API_INSTRUCTIONS.format(
                    brain_api_url=self._brain_url,
                    agent_id=self._agent_id,
                )
            )
            parts.append(
                _HITL_ACTIONS_INSTRUCTIONS.format(
                    brain_api_url=self._brain_url,
                    agent_id=self._agent_id,
                )
            )

        parts.append(f"# Task\n\n{message}")
        return "\n\n---\n\n".join(parts)

    def _build_context(self, query: str = "") -> str:
        """
        Fetch and format Brain state for this agent.

        Mirrors Faith's prepare_context() output structure:
          - Long-term facts (private namespace, excluding internal session keys)
          - Recent episodes
          - Relevant knowledge (semantic FTS search when query is provided)

        Injecting this context is what makes the agent "remember" across sessions
        without relying on a shared context window. The agent sees its private facts,
        recent episode history, and task-relevant knowledge before every call.
        """
        lines: list[str] = []

        try:
            facts   = self._brain.recall_namespace(f"private:{self._agent_id}", limit=10)  # type: ignore[union-attr]
            visible = [m for m in facts if not m.key.startswith("_")]
            if visible:
                lines.append("## Long-term Memory")
                for m in visible:
                    lines.append(f"- [{m.namespace}] {m.key}: {m.value[:200]}")
        except Exception:
            pass

        try:
            episodes = self._brain.get_episodes(agent_id=self._agent_id, limit=5)  # type: ignore[union-attr]
            if episodes:
                lines.append("## Recent Episodes")
                for ep in episodes:
                    lines.append(f"- [{ep.type}] {ep.title}")
        except Exception:
            pass

        if query:
            try:
                namespaces = [f"private:{self._agent_id}", "shared"]
                results    = self._brain.search_knowledge(query, namespaces=namespaces, limit=5)  # type: ignore[union-attr]
                if results:
                    lines.append("## Relevant Knowledge")
                    for k in results:
                        lines.append(f"- {k.title}: {k.content[:200]}")
            except Exception:
                pass

        return "\n".join(lines)

    # ── Episode recording ─────────────────────────────────────────────────────

    def _record_episode(self, message: str, result: str) -> None:
        try:
            from core.brain.service import Episode
            self._brain.record_episode(Episode(  # type: ignore[union-attr]
                agent_id=self._agent_id,  # type: ignore[arg-type]
                type="deliverable",
                title=f"[claude_code] {message[:80]}",
                body=result[:1000] if result else None,
                tags=["claude-code"],
            ))
        except Exception as e:
            logger.warning("[ClaudeCodeRunner] failed to record episode: %s", e)

    # ── HTTP invocation ───────────────────────────────────────────────────────

    def _invoke(
        self,
        prompt:    str,
        resume_id: str | None,
        mcp_url:   str | None,
    ) -> tuple[str | None, str | None, dict]:
        """
        POST to the claude-runner sidecar.
        Returns (result_text, claude_session_id, usage_dict) or (None, None, {}) on failure.
        """
        import httpx

        payload: dict[str, Any] = {"prompt": prompt, "resume_id": resume_id}
        if mcp_url:
            payload["mcp_config_url"] = mcp_url

        try:
            resp = httpx.post(
                f"{self._runner_url}/run",
                json=payload,
                timeout=self._timeout + 10,
            )
            data = resp.json()
        except httpx.ConnectError:
            logger.warning("[ClaudeCodeRunner] sidecar not reachable at %s", self._runner_url)
            return None, None, {}
        except Exception as exc:
            logger.error("[ClaudeCodeRunner] unexpected error: %s", exc)
            return None, None, {}

        if not data.get("success"):
            logger.error("[ClaudeCodeRunner] sidecar returned error: %s", data.get("error"))
            return None, None, {}

        return data.get("result", ""), data.get("session_id"), data.get("usage") or {}

    # ── Fallback ──────────────────────────────────────────────────────────────

    def _fallback(
        self,
        message:       str,
        session_id:    str | None,
        system_prompt: str | None,
        tools:         list[dict[str, Any]] | None,
        messages:      list[dict[str, Any]] | None,
    ) -> RunnerResult:
        """
        Called when the sidecar is unreachable after both the resume attempt and
        a fresh-session retry. Delegates to fallback_runner if configured —
        mirrors Faith's fallback from ClaudeCodeRunner → AgentLoop.
        """
        if self._fallback_runner is None:
            logger.error(
                "[ClaudeCodeRunner] sidecar unavailable and no fallback_runner configured"
            )
            return RunnerResult(
                response="",
                error=(
                    f"claude-runner sidecar at {self._runner_url} is unavailable and no "
                    "fallback_runner was provided. Is `make demo-full` running? "
                    "See docs/dual-runner-pattern.md."
                ),
            )
        logger.info(
            "[ClaudeCodeRunner] sidecar unavailable — falling back to %s for agent=%s",
            self._fallback_runner.name, self._agent_id,
        )
        return self._fallback_runner.run(
            message=message,
            session_id=session_id,
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
        )

    # ── Health check ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Health-check the sidecar. Useful in startup scripts and tests."""
        import httpx
        try:
            resp = httpx.get(f"{self._runner_url}/health", timeout=5)
            return resp.json().get("status") == "ok"
        except Exception:
            return False
