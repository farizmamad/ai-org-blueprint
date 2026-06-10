"""
BrainService — multi-layer memory for agentic AI organizations.

A single SQLite-backed Brain that all agents share. Four storage layers
(long-term kv, episodic log, semantic knowledge, short-term turns) plus three
coordination tables (goals, pending actions, agent status).

All methods are synchronous. SQLite handles concurrency via WAL mode + the
GIL — fine for a tutorial/single-VM deployment. For production multi-process
setups, swap the storage layer for Postgres.

Namespace conventions:
    private:{agent_id}  — only that agent reads/writes
    shared              — all agents read/write
    cross:{a}:{b}       — only agents a and b (sorted alphabetically)

The service does NOT enforce namespace permissions itself — call sites
(routing layer / agent loop) own that policy. Keeping the service pure
read/write makes it easier to test.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Generator


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Turn:
    role: str       # user | assistant | tool
    content: str
    token_count: int = 0


@dataclass
class Memory:
    namespace: str
    key: str
    value: str
    confidence: float = 1.0
    source: str | None = None


@dataclass
class Episode:
    agent_id: str
    type: str       # event | decision | deliverable | error | note
    title: str
    body: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class KnowledgeEntry:
    namespace: str
    title: str
    content: str
    source: str | None = None


@dataclass
class Goal:
    owner_agent: str
    goal_text: str
    goal_type: str = "task"            # task | tracking
    metric: str | None = None
    target_value: str | None = None
    current_value: str | None = None
    review_schedule: str = "weekly"    # daily | weekly | monthly
    status: str = "PENDING"            # PENDING | IN_PROGRESS | COMPLETED
    complexity: str = "routine"        # routine | complex


# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_DB_PATH = os.environ.get("BRAIN_DB_PATH", "./data/brain.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


# ── BrainService ─────────────────────────────────────────────────────────────

class BrainService:
    """Read/write API for the Brain. Synchronous, thread-safe via WAL."""

    SHORT_TERM_TTL_HOURS = 24

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        """Apply schema.sql idempotently."""
        if not SCHEMA_PATH.exists():
            raise RuntimeError(f"schema.sql not found at {SCHEMA_PATH}")
        with self._conn() as conn:
            conn.executescript(SCHEMA_PATH.read_text())

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Long-term memory ─────────────────────────────────────────────────────

    def remember(
        self,
        namespace: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> None:
        """Upsert a (namespace, key) fact."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO long_term_memory (namespace, key, value, confidence, source)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (namespace, key) DO UPDATE SET
                       value      = excluded.value,
                       confidence = excluded.confidence,
                       source     = excluded.source,
                       updated_at = datetime('now')""",
                (namespace, key, value, confidence, source),
            )

    def recall(self, namespace: str, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM long_term_memory WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
            return row["value"] if row else None

    def recall_namespace(self, namespace: str, limit: int = 50) -> list[Memory]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT namespace, key, value, confidence, source
                   FROM long_term_memory WHERE namespace=?
                   ORDER BY updated_at DESC LIMIT ?""",
                (namespace, limit),
            ).fetchall()
            return [Memory(**dict(r)) for r in rows]

    def forget(self, namespace: str, key: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM long_term_memory WHERE namespace=? AND key=?",
                (namespace, key),
            )

    # ── Episodic memory ──────────────────────────────────────────────────────

    def record_episode(self, episode: Episode) -> int:
        """Append an episode. Returns the new episode id."""
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO episodic_memory (agent_id, type, title, body, metadata, tags)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    episode.agent_id,
                    episode.type,
                    episode.title,
                    episode.body,
                    json.dumps(episode.metadata) if episode.metadata else None,
                    json.dumps(episode.tags) if episode.tags else None,
                ),
            )
            return cur.lastrowid or 0

    def get_episodes(
        self,
        agent_id: str | None = None,
        type: str | None = None,
        limit: int = 20,
    ) -> list[Episode]:
        clauses, params = [], []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if type:
            clauses.append("type = ?")
            params.append(type)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT agent_id, type, title, body, metadata, tags
                    FROM episodic_memory {where}
                    ORDER BY created_at DESC LIMIT ?""",
                params,
            ).fetchall()
            return [
                Episode(
                    agent_id=r["agent_id"],
                    type=r["type"],
                    title=r["title"],
                    body=r["body"],
                    metadata=json.loads(r["metadata"]) if r["metadata"] else {},
                    tags=json.loads(r["tags"]) if r["tags"] else [],
                )
                for r in rows
            ]

    # ── Semantic memory (FTS5) ───────────────────────────────────────────────

    def add_knowledge(self, entry: KnowledgeEntry) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO semantic_memory (namespace, title, content, source, created_at)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                (entry.namespace, entry.title, entry.content, entry.source),
            )

    def search_knowledge(
        self,
        query: str,
        namespaces: list[str] | None = None,
        limit: int = 10,
    ) -> list[KnowledgeEntry]:
        """Full-text search across knowledge. FTS5 MATCH semantics."""
        ns_filter = ""
        params: list[Any] = [query]
        if namespaces:
            placeholders = ",".join("?" * len(namespaces))
            ns_filter = f" AND namespace IN ({placeholders})"
            params.extend(namespaces)
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT namespace, title, content, source
                    FROM semantic_memory
                    WHERE semantic_memory MATCH ?{ns_filter}
                    ORDER BY rank LIMIT ?""",
                params,
            ).fetchall()
            return [KnowledgeEntry(**dict(r)) for r in rows]

    # ── Short-term memory ────────────────────────────────────────────────────

    def save_turn(self, agent_id: str, session_id: str, turn: Turn) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO short_term_memory (agent_id, session_id, role, content, token_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (agent_id, session_id, turn.role, turn.content, turn.token_count),
            )
            # Prune entries older than TTL
            conn.execute(
                f"""DELETE FROM short_term_memory
                    WHERE agent_id=? AND created_at <
                          datetime('now', '-{self.SHORT_TERM_TTL_HOURS} hours')""",
                (agent_id,),
            )

    def get_turns(self, agent_id: str, session_id: str, limit: int = 20) -> list[Turn]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT role, content, token_count FROM short_term_memory
                   WHERE agent_id=? AND session_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (agent_id, session_id, limit),
            ).fetchall()
            return [Turn(**dict(r)) for r in reversed(rows)]

    # ── Goals (durable task queue) ───────────────────────────────────────────

    def set_goal(self, goal: Goal) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO agent_goals (
                       owner_agent, goal_text, goal_type, metric,
                       target_value, current_value, review_schedule, status, complexity
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    goal.owner_agent, goal.goal_text, goal.goal_type, goal.metric,
                    goal.target_value, goal.current_value, goal.review_schedule,
                    goal.status, goal.complexity,
                ),
            )
            return cur.lastrowid or 0

    def get_goals(
        self,
        owner_agent: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if owner_agent:
            clauses.append("owner_agent = ?")
            params.append(owner_agent)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM agent_goals {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def update_goal(
        self,
        goal_id: int,
        status: str | None = None,
        current_value: str | None = None,
    ) -> None:
        sets, params = [], []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if current_value is not None:
            sets.append("current_value = ?")
            params.append(current_value)
        if status == "COMPLETED" or status == "IN_PROGRESS":
            sets.append("last_reviewed_at = datetime('now')")
        sets.append("updated_at = datetime('now')")
        params.append(goal_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE agent_goals SET {', '.join(sets)} WHERE id = ?",
                params,
            )

    # ── HITL pending actions ─────────────────────────────────────────────────

    def queue_action(
        self,
        agent_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        description: str,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO pending_actions (agent_id, tool_name, tool_input, description)
                   VALUES (?, ?, ?, ?)""",
                (agent_id, tool_name, json.dumps(tool_input), description),
            )
            return cur.lastrowid or 0

    def get_pending_actions(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_actions WHERE status='pending' ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_action(self, action_id: int, status: str, result: str | None = None) -> None:
        if status not in ("approved", "rejected"):
            raise ValueError(f"invalid resolution status: {status}")
        with self._conn() as conn:
            conn.execute(
                """UPDATE pending_actions
                   SET status=?, result=?, resolved_at=datetime('now')
                   WHERE id=?""",
                (status, result, action_id),
            )

    # ── Agent status board ───────────────────────────────────────────────────

    def update_status(
        self,
        agent_id: str,
        current_task: str | None = None,
        weekly_focus: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO agent_status (agent_id, current_task, weekly_focus)
                   VALUES (?, ?, ?)
                   ON CONFLICT (agent_id) DO UPDATE SET
                       current_task = COALESCE(excluded.current_task, current_task),
                       weekly_focus = COALESCE(excluded.weekly_focus, weekly_focus),
                       last_active  = datetime('now'),
                       updated_at   = datetime('now')""",
                (agent_id, current_task, weekly_focus),
            )

    def get_status(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM agent_status WHERE agent_id = ?", (agent_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_status ORDER BY last_active DESC"
                ).fetchall()
            return [dict(r) for r in rows]
