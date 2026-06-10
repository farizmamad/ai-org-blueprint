.PHONY: help setup demo demo-full demo-cron demo-namespaces test scrub-check mock-llm clean

# Default target: show help
help:
	@echo "ai-org-blueprint — available targets:"
	@echo ""
	@echo "  make setup        Install deps + copy .env.example to .env"
	@echo "  make demo         Run default demo (mock LLM, single-process)"
	@echo "  make demo-full    Run with Claude Code sidecar (Opsi A, opt-in)"
	@echo "  make demo-cron    Run proactive dispatch example"
	@echo "  make demo-namespaces  Run memory namespaces walkthrough (no LLM needed)"
	@echo "  make mock-llm     Start mock LLM HTTP server on :8080"
	@echo "  make test         Run pytest suite"
	@echo "  make scrub-check  Scan for accidental PII/secret leaks"
	@echo "  make clean        Remove containers, __pycache__, brain.db"
	@echo ""

# ─── Setup ───────────────────────────────────────────────────────────────
setup:
	@test -f .env || cp .env.example .env
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e .
	@echo ""
	@echo "✓ Setup complete. Edit .env if you want to switch LLM_RUNNER."

# ─── Demos ───────────────────────────────────────────────────────────────
demo:
	@echo "Starting default demo (mock LLM)..."
	docker-compose up --build --abort-on-container-exit

demo-full:
	@echo "Starting full demo (Claude Code sidecar — requires ANTHROPIC_API_KEY)..."
	docker-compose -f docker-compose.yml -f docker-compose.full.yml up --build --abort-on-container-exit

demo-cron:
	. .venv/bin/activate && python examples/cron-proactive-dispatch/run.py

demo-namespaces:
	. .venv/bin/activate && python examples/memory-namespaces/run.py

mock-llm:
	. .venv/bin/activate && python scripts/mock_llm_server.py

# ─── Quality checks ──────────────────────────────────────────────────────
test:
	. .venv/bin/activate && pytest tests/ -v

scrub-check:
	@echo "Scanning for accidental PII/secret patterns..."
	. .venv/bin/activate && python scripts/scrub_check.py

# ─── Cleanup ─────────────────────────────────────────────────────────────
clean:
	docker-compose down -v 2>/dev/null || true
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -f data/brain.db data/brain.db-*
	@echo "✓ Cleaned."
