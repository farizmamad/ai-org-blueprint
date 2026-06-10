"""
Observability — Prometheus metrics for the AI organization.

Metrics exported, all with an `agent` label:

  ai_org_tokens_total{agent, token_type}   — token counts split by type:
                                             input, output, cache_write, cache_read
  ai_org_requests_total{agent, status}     — request outcomes: success, rate_limited, error
  ai_org_response_seconds{agent}           — histogram of end-to-end turn latency
  ai_org_cost_usd_total{agent}             — accumulated estimated API cost in USD

Why four separate dimensions?

  Tokens split by type lets you see whether prompt caching is actually reducing
  your bill. Claude charges 10× less for cache_read tokens than for fresh input
  tokens. Without this split you can't tell whether your memory injection
  strategy is helping or just adding to prompt size.

  Requests split by status lets you detect rate-limit spikes before they show
  up as user-facing errors.

  Latency as a histogram gives you p50/p95/p99 per agent — so you know which
  agent is the bottleneck without reading logs.

  Cost as a counter accumulates over time. You can alert when daily spend
  crosses a threshold instead of checking your bill at month end.

prometheus_client is optional. If not installed, all recording calls are
silent no-ops — the rest of the system works without any changes.

Quick start:

    pip install prometheus-client

    from core.observability.metrics import start_metrics_server, record_llm_call

    start_metrics_server()   # GET /metrics on METRICS_PORT (default 9101)

    with timed_llm_call("engineer") as ctx:
        result = runner.run(message)
        ctx["usage"]    = result.usage
        ctx["status"]   = "success" if not result.error else "error"
        ctx["cost_usd"] = result.usage.get("cost_usd", 0.0)

See docs/observability.md for Grafana dashboard and VictoriaMetrics setup.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

# ── Prometheus setup (optional) ────────────────────────────────────────────────

try:
    from prometheus_client import Counter, Histogram
    from prometheus_client import start_http_server as _start_http

    TOKENS = Counter(
        "ai_org_tokens_total",
        "Total tokens consumed by agents",
        ["agent", "token_type"],
    )

    REQUESTS = Counter(
        "ai_org_requests_total",
        "Total LLM API requests made by agents",
        ["agent", "status"],
    )

    LATENCY = Histogram(
        "ai_org_response_seconds",
        "End-to-end agent response latency in seconds",
        ["agent"],
        buckets=[1, 2, 5, 10, 30, 60, 120, 300],
    )

    COST = Counter(
        "ai_org_cost_usd_total",
        "Estimated USD cost of LLM calls by agent",
        ["agent"],
    )

    _AVAILABLE = True

except ImportError:
    logger.debug(
        "prometheus_client not installed — metrics disabled "
        "(run `pip install prometheus-client` to enable)"
    )
    _AVAILABLE = False

    class _Noop:
        def labels(self, **_): return self
        def inc(self, _=1):    pass
        def observe(self, _):  pass

    TOKENS   = _Noop()  # type: ignore[assignment]
    REQUESTS = _Noop()  # type: ignore[assignment]
    LATENCY  = _Noop()  # type: ignore[assignment]
    COST     = _Noop()  # type: ignore[assignment]


# ── Cost estimation ────────────────────────────────────────────────────────────

# USD per million tokens — keep in sync with Anthropic pricing page.
# cache_write is charged at input rate; cache_read at 0.1× input rate.
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001":  {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":          {"input": 3.00,  "output": 15.00},
    "claude-opus-4-8":            {"input": 15.00, "output": 75.00},
}
_FALLBACK_PRICING = {"input": 1.00, "output": 5.00}


def estimate_cost(model: str, usage: dict) -> float:
    """
    Estimate USD cost from a token usage dict.

    Handles cache tokens:
      - cache_creation_input_tokens  → billed at input rate
      - cache_read_input_tokens      → billed at 0.1× input rate

    Returns 0.0 if usage is empty.
    """
    pricing = _MODEL_PRICING.get(model, _FALLBACK_PRICING)
    input_rate  = pricing["input"]
    output_rate = pricing["output"]

    fresh_input   = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_write   = usage.get("cache_creation_input_tokens", 0)
    cache_read    = usage.get("cache_read_input_tokens", 0)

    cost = (
        fresh_input   * input_rate  / 1_000_000
        + output_tokens * output_rate / 1_000_000
        + cache_write   * input_rate  / 1_000_000
        + cache_read    * input_rate  * 0.1 / 1_000_000
    )
    return round(cost, 6)


# ── Public API ─────────────────────────────────────────────────────────────────

def start_metrics_server() -> None:
    """
    Expose Prometheus metrics on GET /metrics.

    Port is read from METRICS_PORT env (default 9101). Call once at startup.
    Does nothing if prometheus_client is not installed.
    """
    if not _AVAILABLE:
        return
    port = int(os.getenv("METRICS_PORT", "9101"))
    _start_http(port)
    logger.info("Prometheus metrics available at :%d/metrics", port)


def record_llm_call(
    agent:    str,
    usage:    dict,
    status:   str   = "success",
    duration: float = 0.0,
    cost_usd: float = 0.0,
) -> None:
    """
    Record one completed LLM call into all four metric dimensions.

    Args:
        agent:    Agent identifier, e.g. "ceo" or "engineer".
        usage:    Token usage dict. Recognised keys:
                    input_tokens, output_tokens,
                    cache_creation_input_tokens, cache_read_input_tokens.
        status:   "success", "rate_limited", or "error".
        duration: Wall-clock seconds for the full turn. Skipped if 0.
        cost_usd: Estimated USD cost. Skipped if 0.
    """
    REQUESTS.labels(agent=agent, status=status).inc()

    token_map = {
        "input":       usage.get("input_tokens", 0),
        "output":      usage.get("output_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "cache_read":  usage.get("cache_read_input_tokens", 0),
    }
    for token_type, count in token_map.items():
        if count:
            TOKENS.labels(agent=agent, token_type=token_type).inc(count)

    if duration > 0:
        LATENCY.labels(agent=agent).observe(duration)

    if cost_usd > 0:
        COST.labels(agent=agent).inc(cost_usd)


@contextmanager
def timed_llm_call(agent: str) -> Generator[dict, None, None]:
    """
    Context manager that measures wall-clock time and records all metrics.

    Usage::

        with timed_llm_call("engineer") as ctx:
            result = runner.run(message)
            ctx["usage"]    = result.usage
            ctx["status"]   = "success" if not result.error else "error"
            ctx["cost_usd"] = result.usage.get("cost_usd", 0.0)

    The caller populates ctx inside the block.
    Metrics are recorded on exit — including on exceptions (status="error").
    """
    ctx: dict = {"usage": {}, "status": "success", "cost_usd": 0.0}
    start = time.monotonic()
    try:
        yield ctx
    except Exception:
        ctx["status"] = "error"
        raise
    finally:
        duration = time.monotonic() - start
        record_llm_call(
            agent    = agent,
            usage    = ctx.get("usage", {}),
            status   = ctx.get("status", "success"),
            duration = duration,
            cost_usd = ctx.get("cost_usd", 0.0),
        )
