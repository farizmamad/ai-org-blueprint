"""
Claude Runner Sidecar — HTTP wrapper around the Claude Code CLI.

Runs as a separate container so the main Python image stays Python-only.
Faith calls this via ClaudeCodeRunner → POST /run.

Why a separate container?
  The Claude Code CLI is a Node.js binary. Keeping it out of the Python image
  means faster Python rebuilds and a clean separation: change the Python
  business logic without touching the Node.js layer, or upgrade the Claude CLI
  without touching Python dependencies.

Endpoints:
  POST /run    — run `claude -p <prompt>`, return result + session_id
  GET  /health — health check for docker-compose depends_on

Session continuity:
  Pass resume_id (a claude session_id from a previous /run call) to pick up
  where the last turn left off. Claude Code's --resume flag reloads the full
  conversation history from its local cache.

MCP tools (Brain integration):
  Pass mcp_config_url to have the sidecar write a temp MCP config file and
  pass --mcp-config to claude. This gives the agent access to Brain tools
  (brain_remember, brain_recall, etc.) as first-class MCP calls rather than
  requiring manual curl commands.

  The Brain service must expose an MCP-compatible endpoint at mcp_config_url.
  See core/brain/api.py for the /mcp/ endpoint.

Usage (inside docker-compose):
  The claude-runner service is defined in docker-compose.full.yml and started
  via `make demo-full`. It is opt-in — the default `make demo` uses MockRunner
  or APIRunner without this container.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

from fastapi import FastAPI
from pydantic import BaseModel, computed_field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("claude-runner")

app = FastAPI(title="claude-runner", version="1.0", docs_url=None, redoc_url=None)

_CLAUDE_BIN   = os.getenv("CLAUDE_BIN", "claude")
_TIMEOUT_SECS = int(os.getenv("CLAUDE_CODE_TIMEOUT", "300"))


# ── Request / Response models ─────────────────────────────────────────────────

class RunRequest(BaseModel):
    prompt:         str
    resume_id:      str | None = None
    mcp_config_url: str | None = None


class TokenUsage(BaseModel):
    input_tokens:                   int = 0
    output_tokens:                  int = 0
    cache_creation_input_tokens:    int = 0
    cache_read_input_tokens:        int = 0

    @computed_field  # type: ignore[misc]
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @computed_field  # type: ignore[misc]
    @property
    def cost_usd(self) -> float:
        # claude-sonnet-4-6 pricing (June 2026)
        return (
            self.input_tokens                   * 3.00  / 1_000_000
            + self.output_tokens                * 15.00 / 1_000_000
            + self.cache_creation_input_tokens  * 3.75  / 1_000_000
            + self.cache_read_input_tokens      * 0.30  / 1_000_000
        )


class RunResponse(BaseModel):
    success:    bool
    result:     str           = ""
    session_id: str | None    = None
    error:      str | None    = None
    usage:      TokenUsage    = TokenUsage()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/run", response_model=RunResponse)
def run(req: RunRequest) -> RunResponse:
    args = [
        _CLAUDE_BIN, "-p", req.prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions",
    ]
    if req.resume_id:
        args += ["--resume", req.resume_id]

    mcp_config_file = None
    if req.mcp_config_url:
        mcp_config = {
            "mcpServers": {
                "brain": {"type": "http", "url": req.mcp_config_url},
            }
        }
        mcp_config_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="mcp-cfg-"
        )
        json.dump(mcp_config, mcp_config_file)
        mcp_config_file.flush()
        args += ["--mcp-config", mcp_config_file.name]

    logger.info(
        "run resume=%s mcp=%s prompt_len=%d",
        req.resume_id, bool(req.mcp_config_url), len(req.prompt),
    )

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECS,
        )
    except FileNotFoundError:
        logger.error("binary %r not found — is claude CLI installed?", _CLAUDE_BIN)
        return RunResponse(success=False, error=f"binary {_CLAUDE_BIN!r} not found")
    except subprocess.TimeoutExpired:
        logger.error("timeout after %ds", _TIMEOUT_SECS)
        return RunResponse(success=False, error=f"timeout after {_TIMEOUT_SECS}s")
    finally:
        if mcp_config_file:
            try:
                os.unlink(mcp_config_file.name)
            except OSError:
                pass

    if proc.returncode != 0:
        logger.error("exit=%d stderr=%s", proc.returncode, proc.stderr[:300])
        return RunResponse(success=False, error=proc.stderr[:500] or proc.stdout[:500])

    try:
        data       = json.loads(proc.stdout)
        result     = data.get("result", "").strip()
        session_id = data.get("session_id")
        raw_usage  = data.get("usage") or {}
        usage      = TokenUsage(
            input_tokens=raw_usage.get("input_tokens", 0),
            output_tokens=raw_usage.get("output_tokens", 0),
            cache_creation_input_tokens=raw_usage.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=raw_usage.get("cache_read_input_tokens", 0),
        )
    except (json.JSONDecodeError, AttributeError):
        # claude didn't return JSON — use raw stdout as result
        result     = proc.stdout.strip()
        session_id = None
        usage      = TokenUsage()

    logger.info(
        "done session=%s chars=%d | in=%d out=%d cache_w=%d cache_r=%d total=%d cost=$%.4f",
        session_id, len(result),
        usage.input_tokens, usage.output_tokens,
        usage.cache_creation_input_tokens, usage.cache_read_input_tokens,
        usage.total_tokens, usage.cost_usd,
    )
    return RunResponse(success=True, result=result, session_id=session_id, usage=usage)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
