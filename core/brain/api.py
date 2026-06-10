"""
Brain HTTP API — FastAPI wrapper around BrainService.

Why HTTP? When agents run as separate processes (or via the Claude Code
sidecar pattern), they need a stable interface to read/write Brain that
doesn't require sharing a SQLite file. HTTP + JSON is simpler than IPC
and gives you observability for free (curl, logs, dashboards).

Run locally:
    python -m uvicorn core.brain.api:app --reload

All endpoints return JSON. Errors use standard FastAPI HTTPException
(400 for bad input, 503 for uninitialized Brain).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from core.brain.service import (
    BrainService,
    Episode,
    Goal,
    KnowledgeEntry,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Brain API", version="0.1.0")

# Initialised lazily on first request, or eagerly via init().
_brain: BrainService | None = None


def init(brain: BrainService) -> None:
    """Inject a pre-built BrainService (useful for tests and shared instances)."""
    global _brain
    _brain = brain


def _get_brain() -> BrainService:
    global _brain
    if _brain is None:
        # Lazy init from env — convenient for `uvicorn` quickstart.
        _brain = BrainService(db_path=os.environ.get("BRAIN_DB_PATH", "./data/brain.db"))
    return _brain


# ── Request / response models ────────────────────────────────────────────────

class RememberRequest(BaseModel):
    namespace: str
    key: str
    value: str
    confidence: float = 1.0
    source: str | None = None


class RecordEpisodeRequest(BaseModel):
    agent_id: str
    type: str = Field(..., description="event | decision | deliverable | error | note")
    title: str
    body: str | None = None
    metadata: dict[str, Any] = {}
    tags: list[str] = []


class AddKnowledgeRequest(BaseModel):
    namespace: str
    title: str
    content: str
    source: str | None = None


class SetGoalRequest(BaseModel):
    owner_agent: str
    goal_text: str
    goal_type: str = "task"
    metric: str | None = None
    target_value: str | None = None
    current_value: str | None = None
    review_schedule: str = "weekly"
    complexity: str = "routine"


class UpdateGoalRequest(BaseModel):
    status: str | None = None
    current_value: str | None = None


class QueueActionRequest(BaseModel):
    agent_id: str
    tool_name: str
    tool_input: dict[str, Any]
    description: str


class ResolveActionRequest(BaseModel):
    status: str = Field(..., description="approved | rejected")
    result: str | None = None


class UpdateStatusRequest(BaseModel):
    agent_id: str
    current_task: str | None = None
    weekly_focus: str | None = None


# ── Long-term memory ─────────────────────────────────────────────────────────

@app.post("/remember")
def remember(req: RememberRequest) -> dict[str, str]:
    _get_brain().remember(
        req.namespace, req.key, req.value, req.confidence, req.source
    )
    return {"status": "ok"}


@app.get("/recall")
def recall(namespace: str, key: str) -> dict[str, Any]:
    return {
        "namespace": namespace,
        "key": key,
        "value": _get_brain().recall(namespace, key),
    }


@app.get("/recall_namespace")
def recall_namespace(namespace: str, limit: int = 50) -> dict[str, Any]:
    items = _get_brain().recall_namespace(namespace, limit)
    return {"namespace": namespace, "items": [vars(m) for m in items]}


@app.delete("/forget")
def forget(namespace: str, key: str) -> dict[str, str]:
    _get_brain().forget(namespace, key)
    return {"status": "ok"}


# ── Episodic memory ──────────────────────────────────────────────────────────

@app.post("/record_episode")
def record_episode(req: RecordEpisodeRequest) -> dict[str, Any]:
    episode_id = _get_brain().record_episode(Episode(**req.model_dump()))
    return {"status": "ok", "episode_id": episode_id}


@app.get("/episodes")
def get_episodes(
    agent_id: str | None = None,
    type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    eps = _get_brain().get_episodes(agent_id=agent_id, type=type, limit=limit)
    return {"count": len(eps), "episodes": [vars(e) for e in eps]}


# ── Semantic knowledge (FTS5) ────────────────────────────────────────────────

@app.post("/add_knowledge")
def add_knowledge(req: AddKnowledgeRequest) -> dict[str, str]:
    _get_brain().add_knowledge(KnowledgeEntry(**req.model_dump()))
    return {"status": "ok"}


@app.get("/search_knowledge")
def search_knowledge(
    query: str,
    namespaces: str | None = Query(default=None, description="Comma-separated namespace filter"),
    limit: int = 10,
) -> dict[str, Any]:
    ns_list = namespaces.split(",") if namespaces else None
    results = _get_brain().search_knowledge(query, namespaces=ns_list, limit=limit)
    return {"query": query, "count": len(results), "results": [vars(r) for r in results]}


# ── Goals (durable task queue) ───────────────────────────────────────────────

@app.post("/goals")
def set_goal(req: SetGoalRequest) -> dict[str, Any]:
    goal = Goal(**req.model_dump())
    goal_id = _get_brain().set_goal(goal)
    return {"status": "ok", "goal_id": goal_id}


@app.get("/goals")
def get_goals(
    owner_agent: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    goals = _get_brain().get_goals(owner_agent=owner_agent, status=status)
    return {"count": len(goals), "goals": goals}


@app.patch("/goals/{goal_id}")
def update_goal(goal_id: int, req: UpdateGoalRequest) -> dict[str, str]:
    _get_brain().update_goal(goal_id, status=req.status, current_value=req.current_value)
    return {"status": "ok"}


# ── HITL pending actions ─────────────────────────────────────────────────────

@app.post("/actions")
def queue_action(req: QueueActionRequest) -> dict[str, Any]:
    """Queue an irreversible action for human approval.

    Caller (the agent/tool layer) decides what's irreversible. This endpoint
    just persists the request and returns the queue id.
    """
    action_id = _get_brain().queue_action(
        agent_id=req.agent_id,
        tool_name=req.tool_name,
        tool_input=req.tool_input,
        description=req.description,
    )
    return {"queued": True, "action_id": action_id, "description": req.description}


@app.get("/actions/pending")
def list_pending_actions() -> dict[str, Any]:
    actions = _get_brain().get_pending_actions()
    return {"count": len(actions), "actions": actions}


@app.post("/actions/{action_id}/resolve")
def resolve_action(action_id: int, req: ResolveActionRequest) -> dict[str, str]:
    try:
        _get_brain().resolve_action(action_id, req.status, req.result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok"}


# ── Agent status board ───────────────────────────────────────────────────────

@app.post("/status")
def update_status(req: UpdateStatusRequest) -> dict[str, str]:
    _get_brain().update_status(
        agent_id=req.agent_id,
        current_task=req.current_task,
        weekly_focus=req.weekly_focus,
    )
    return {"status": "ok"}


@app.get("/status")
def get_status(agent_id: str | None = None) -> dict[str, Any]:
    rows = _get_brain().get_status(agent_id=agent_id)
    return {"count": len(rows), "statuses": rows}


# ── Meta ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    _get_brain()  # raises 503 indirectly if init fails
    return {"status": "ok"}
