-- ═══════════════════════════════════════════════════════════════
-- Brain — multi-layer memory schema
--
-- 4 storage layers covered here:
--   1. long_term_memory    — namespaced key-value facts (indefinite)
--   2. episodic_memory     — append-only event log (decisions, deliverables, errors)
--   3. semantic_memory     — FTS5-searchable knowledge base
--   4. short_term_memory   — conversation turns per session (rolling window)
--
-- 3 coordination tables:
--   5. agent_goals       — durable task queue (PENDING / IN_PROGRESS / COMPLETED)
--   6. pending_actions   — HITL queue for irreversible actions awaiting approval
--   7. agent_status      — current-task board shared across agents
-- ═══════════════════════════════════════════════════════════════

-- Layer 1: Long-term memory — persistent facts, key-value with namespace.
-- Namespace conventions:
--   private:{agent_id}  — only this agent reads/writes
--   shared              — all agents read/write (cross-agent facts)
--   cross:{a}:{b}       — only agents a and b (sorted alphabetically)
CREATE TABLE IF NOT EXISTS long_term_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace   TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    value       TEXT    NOT NULL,
    confidence  REAL    NOT NULL DEFAULT 1.0,
    source      TEXT,
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (namespace, key)
);

CREATE INDEX IF NOT EXISTS idx_ltm_namespace
    ON long_term_memory (namespace);

-- Layer 2: Episodic memory — append-only event log.
-- type: event | decision | deliverable | error | note
CREATE TABLE IF NOT EXISTS episodic_memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT    NOT NULL,
    type       TEXT    NOT NULL CHECK (type IN ('event', 'decision', 'deliverable', 'error', 'note')),
    title      TEXT    NOT NULL,
    body       TEXT,
    metadata   TEXT,
    tags       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_em_agent_type
    ON episodic_memory (agent_id, type, created_at);

CREATE INDEX IF NOT EXISTS idx_em_created_at
    ON episodic_memory (created_at);

-- Layer 3: Semantic memory — full-text-searchable knowledge base via SQLite FTS5.
CREATE VIRTUAL TABLE IF NOT EXISTS semantic_memory USING fts5 (
    namespace,
    title,
    content,
    source,
    created_at UNINDEXED,
    tokenize   = 'unicode61'
);

-- Layer 4: Short-term memory — conversation turns per agent/session.
-- Pruning policy is owned by service code (rolling window or TTL).
CREATE TABLE IF NOT EXISTS short_term_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT    NOT NULL,
    session_id  TEXT    NOT NULL,
    role        TEXT    NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content     TEXT    NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_stm_agent_session
    ON short_term_memory (agent_id, session_id, created_at);

-- ═══════════════════════════════════════════════════════════════
-- Coordination tables
-- ═══════════════════════════════════════════════════════════════

-- Goal registry — durable task queue for cross-agent delegation.
-- goal_type:
--   tracking — periodic review goal (e.g. monthly metric check, never "completed")
--   task     — one-shot execution (e.g. ship feature X), terminal at COMPLETED
-- review_schedule applies to tracking goals only.
-- status: PENDING -> IN_PROGRESS -> COMPLETED. Failed dispatches reset to PENDING.
-- complexity: routine = light agent loop | complex = full-capability runner
CREATE TABLE IF NOT EXISTS agent_goals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_agent      TEXT    NOT NULL,
    goal_text        TEXT    NOT NULL,
    goal_type        TEXT    NOT NULL DEFAULT 'task'
                             CHECK (goal_type IN ('tracking', 'task')),
    metric           TEXT,
    target_value     TEXT,
    current_value    TEXT,
    review_schedule  TEXT    NOT NULL DEFAULT 'weekly'
                             CHECK (review_schedule IN ('daily', 'weekly', 'monthly')),
    status           TEXT    NOT NULL DEFAULT 'PENDING'
                             CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED')),
    complexity       TEXT    NOT NULL DEFAULT 'routine'
                             CHECK (complexity IN ('routine', 'complex')),
    last_reviewed_at TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ag_owner_status
    ON agent_goals (owner_agent, status);

-- HITL pending actions — irreversible actions queued for owner approval.
-- status: pending -> approved (runs the tool) | rejected (discards).
CREATE TABLE IF NOT EXISTS pending_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT    NOT NULL,
    tool_name   TEXT    NOT NULL,
    tool_input  TEXT    NOT NULL,  -- JSON
    description TEXT    NOT NULL,  -- human-readable summary shown to approver
    status      TEXT    NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected')),
    result      TEXT,              -- tool output after approval+execution
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pa_status
    ON pending_actions (status, created_at);

-- Agent status board — current-task state visible to all agents.
-- Useful for cross-agent context (e.g. CEO reading what Engineer is currently doing).
CREATE TABLE IF NOT EXISTS agent_status (
    agent_id      TEXT NOT NULL PRIMARY KEY,
    current_task  TEXT,
    weekly_focus  TEXT,
    last_active   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
