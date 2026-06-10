#!/usr/bin/env python3
"""
mock_llm_server.py — deterministic HTTP mock of the Anthropic Messages API.

Runs a FastAPI server on PORT (default 8080) that responds to:
    POST /v1/messages

Responses mirror what MockRunner returns in-process, but over HTTP. This
lets you run `make demo` with docker-compose and have all containers use
the same mock without an Anthropic API key.

To route APIRunner here, set in .env:
    LLM_RUNNER=api
    ANTHROPIC_BASE_URL=http://localhost:8080   # or http://mock-llm:8080 in Docker

The Anthropic Python SDK respects ANTHROPIC_BASE_URL automatically.

Usage:
    python scripts/mock_llm_server.py          # port 8080
    PORT=9090 python scripts/mock_llm_server.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError:
    print("FastAPI / uvicorn not installed. Run `pip install fastapi uvicorn`.")
    sys.exit(1)

PORT = int(os.environ.get("PORT", "8080"))

app = FastAPI(title="mock-llm", docs_url=None, redoc_url=None)


def _extract_last_user_text(messages: list[dict]) -> str:
    """Pull the most recent user-role text content from a messages list."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
    return ""


def _mock_reply(message: str, has_tools: bool) -> str:
    msg_lower = message.lower()
    if any(k in msg_lower for k in ("hello", "hi", "hey")):
        return "[mock] Hi. This is the mock LLM — set ANTHROPIC_API_KEY and remove ANTHROPIC_BASE_URL for real responses."
    if "delegate" in msg_lower or "engineer" in msg_lower:
        return "[mock] If I were real, I'd delegate this to the Engineer agent via message_agent."
    if "remember" in msg_lower or "memory" in msg_lower:
        return "[mock] Looks like a memory operation. Use brain.remember(namespace, key, value)."
    if "goal" in msg_lower:
        return "[mock] Goal-related request. See agent_goals in core/brain/schema.sql."
    digest = hashlib.sha256(message.encode()).hexdigest()[:8]
    return f"[mock-{digest}] Received {len(message)} chars. (Deterministic placeholder.)"


@app.post("/v1/messages")
async def create_message(request: Request) -> JSONResponse:
    body = await request.json()
    messages: list[dict] = body.get("messages", [])
    tools: list[dict] = body.get("tools") or []

    last_user_text = _extract_last_user_text(messages)
    reply_text = _mock_reply(last_user_text, has_tools=bool(tools))

    response = {
        "id": f"msg_mock_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": reply_text}],
        "model": body.get("model", "mock-llm-1.0"),
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": sum(len(str(m)) // 4 for m in messages),
            "output_tokens": len(reply_text) // 4,
        },
    }
    return JSONResponse(content=response)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "ts": int(time.time())})


if __name__ == "__main__":
    print(f"mock-llm server starting on port {PORT}")
    print(f"  POST http://localhost:{PORT}/v1/messages")
    print(f"  Set ANTHROPIC_BASE_URL=http://localhost:{PORT} to route APIRunner here.\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
