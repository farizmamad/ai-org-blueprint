# Observability

This document covers the metrics layer — what's measured, why each dimension
matters, and how to wire up Prometheus + Grafana for a local stack.

---

## What gets measured

Every LLM call emits four counter/histogram families, all labelled by `agent`:

| Metric | Type | Labels | Purpose |
|---|---|---|---|
| `ai_org_tokens_total` | Counter | `agent`, `token_type` | Token spend split by type |
| `ai_org_requests_total` | Counter | `agent`, `status` | Request outcomes |
| `ai_org_response_seconds` | Histogram | `agent` | End-to-end turn latency |
| `ai_org_cost_usd_total` | Counter | `agent` | Accumulated estimated cost |

`token_type` values: `input`, `output`, `cache_write`, `cache_read`.

`status` values: `success`, `rate_limited`, `error`.

---

## Why split tokens by type

Claude charges different rates for different token types:

| Type | What it is | Relative cost |
|---|---|---|
| `input` | Fresh tokens the model reads | 1× |
| `output` | Tokens the model generates | ~5–20× input |
| `cache_write` | Tokens written to the prompt cache | ~1.25× input |
| `cache_read` | Tokens read back from the cache | ~0.1× input |

System prompts and memory-injected content that repeats across calls gets cached.
A high `cache_read / input` ratio means your memory injection is paying off in
real cost reduction. A low ratio means the prompts aren't stable enough to cache —
worth investigating.

Without this split you can only see total token spend. With it, you can see:
- Which agents benefit most from caching
- Whether adding more memory context helps or just increases bill
- When cache hit rate drops (often signals a prompt structure change)

---

## Setup

### 1. Install prometheus-client

```bash
pip install prometheus-client
```

Metrics are silent no-ops without this package — nothing else changes.

### 2. Start the metrics server at startup

```python
from core.observability.metrics import start_metrics_server

start_metrics_server()   # exposes GET /metrics on METRICS_PORT (default 9101)
```

Call this once, early in your entrypoint.

### 3. Scrape with Prometheus or VictoriaMetrics

Minimal `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: ai-org
    static_configs:
      - targets: ["localhost:9101"]
    scrape_interval: 15s
```

Or with VictoriaMetrics in Docker Compose (what the Faith production stack uses):

```yaml
services:
  victoriametrics:
    image: victoriametrics/victoria-metrics:latest
    command: -promscrape.config=/etc/prometheus.yml
    volumes:
      - ./config/victoria-scrape.yml:/etc/prometheus.yml:ro
    ports:
      - "8428:8428"
```

### 4. Grafana

Add VictoriaMetrics as a Prometheus-compatible datasource
(`http://victoriametrics:8428`), then import the dashboard below.

---

## Useful Grafana queries

**Requests per agent per minute:**
```promql
rate(ai_org_requests_total[5m])
```

**Token spend — cache vs fresh input:**
```promql
rate(ai_org_tokens_total{token_type="cache_read"}[5m])
/
rate(ai_org_tokens_total{token_type="input"}[5m])
```
A ratio above ~0.3 means caching is meaningfully reducing costs.

**p95 latency by agent:**
```promql
histogram_quantile(0.95, rate(ai_org_response_seconds_bucket[5m]))
```

**Daily cost so far:**
```promql
increase(ai_org_cost_usd_total[24h])
```

**Rate-limit spike alert (Alertmanager rule):**
```yaml
groups:
  - name: ai-org
    rules:
      - alert: HighRateLimitRate
        expr: rate(ai_org_requests_total{status="rate_limited"}[5m]) > 0.1
        for: 2m
        annotations:
          summary: "Rate limit spike on {{ $labels.agent }}"
```

---

## How metrics are recorded

Both runners call `record_llm_call()` automatically after every invocation:

```
APIRunner.run()
  → calls Anthropic API
  → reads resp.usage (input_tokens, output_tokens, cache_* tokens)
  → estimates cost_usd via estimate_cost(model, usage)
  → calls record_llm_call(agent, usage, status, duration, cost_usd)

ClaudeCodeRunner.run()
  → calls claude-runner sidecar
  → sidecar returns usage dict (tokens + cost_usd already computed)
  → calls record_llm_call(agent, usage, status, duration_secs, cost_usd)
```

The agent and orchestrator layers never touch metrics directly — it's purely
a runner-level concern.

---

## Extending

To add a custom metric:

```python
from prometheus_client import Counter

MY_METRIC = Counter("ai_org_my_custom_total", "Description", ["agent"])

# then in your code:
MY_METRIC.labels(agent="engineer").inc()
```

Import from `core.observability.metrics` so it's registered on the same
default Prometheus registry and exported on the same `/metrics` endpoint.
