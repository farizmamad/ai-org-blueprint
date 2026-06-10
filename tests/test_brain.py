"""
Smoke tests for BrainService.

These exercise every public method against a temp SQLite file. No mocks —
SQLite is fast enough that real I/O is fine for a test suite of this size.

Run:  pytest tests/test_brain.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.brain import BrainService, Episode, Goal, KnowledgeEntry, Memory, Turn


@pytest.fixture
def brain(tmp_path: Path) -> BrainService:
    return BrainService(db_path=str(tmp_path / "brain.db"))


# ── Long-term memory ─────────────────────────────────────────────────────────

def test_remember_and_recall(brain: BrainService) -> None:
    brain.remember("shared", "north_star", "ship the tutorial")
    assert brain.recall("shared", "north_star") == "ship the tutorial"


def test_remember_upserts(brain: BrainService) -> None:
    brain.remember("shared", "version", "0.1")
    brain.remember("shared", "version", "0.2")
    assert brain.recall("shared", "version") == "0.2"


def test_recall_missing_returns_none(brain: BrainService) -> None:
    assert brain.recall("shared", "nope") is None


def test_recall_namespace_lists_all(brain: BrainService) -> None:
    brain.remember("private:ceo", "k1", "v1")
    brain.remember("private:ceo", "k2", "v2")
    brain.remember("shared", "other", "v3")
    items = brain.recall_namespace("private:ceo")
    assert {m.key for m in items} == {"k1", "k2"}
    assert all(isinstance(m, Memory) for m in items)


def test_forget_removes_entry(brain: BrainService) -> None:
    brain.remember("shared", "tmp", "delete me")
    brain.forget("shared", "tmp")
    assert brain.recall("shared", "tmp") is None


# ── Episodic memory ──────────────────────────────────────────────────────────

def test_record_episode_returns_id(brain: BrainService) -> None:
    ep_id = brain.record_episode(Episode(
        agent_id="engineer",
        type="deliverable",
        title="shipped feature X",
        body="merged PR #42",
        tags=["feature", "merged"],
    ))
    assert ep_id > 0


def test_get_episodes_filters_by_agent_and_type(brain: BrainService) -> None:
    brain.record_episode(Episode("engineer", "deliverable", "A"))
    brain.record_episode(Episode("engineer", "error", "B"))
    brain.record_episode(Episode("ceo", "decision", "C"))

    eng_deliverables = brain.get_episodes(agent_id="engineer", type="deliverable")
    assert len(eng_deliverables) == 1
    assert eng_deliverables[0].title == "A"


def test_episode_metadata_and_tags_roundtrip(brain: BrainService) -> None:
    brain.record_episode(Episode(
        agent_id="engineer",
        type="event",
        title="meta test",
        metadata={"key": 1, "nested": {"a": "b"}},
        tags=["t1", "t2"],
    ))
    ep = brain.get_episodes(agent_id="engineer")[0]
    assert ep.metadata == {"key": 1, "nested": {"a": "b"}}
    assert ep.tags == ["t1", "t2"]


# ── Semantic knowledge (FTS5) ────────────────────────────────────────────────

def test_add_knowledge_and_search(brain: BrainService) -> None:
    brain.add_knowledge(KnowledgeEntry(
        namespace="shared",
        title="how to write an ADR",
        content="An architecture decision record captures context, decision, and consequences.",
    ))
    hits = brain.search_knowledge("decision")
    assert len(hits) == 1
    assert "ADR" in hits[0].title


def test_search_knowledge_respects_namespaces(brain: BrainService) -> None:
    brain.add_knowledge(KnowledgeEntry(namespace="public", title="public note", content="alpha"))
    brain.add_knowledge(KnowledgeEntry(namespace="private:x", title="private note", content="alpha"))
    public_hits = brain.search_knowledge("alpha", namespaces=["public"])
    assert {h.namespace for h in public_hits} == {"public"}


# ── Short-term memory ────────────────────────────────────────────────────────

def test_save_and_get_turns(brain: BrainService) -> None:
    brain.save_turn("engineer", "sess1", Turn(role="user", content="hello"))
    brain.save_turn("engineer", "sess1", Turn(role="assistant", content="hi"))
    turns = brain.get_turns("engineer", "sess1")
    assert [t.role for t in turns] == ["user", "assistant"]
    assert [t.content for t in turns] == ["hello", "hi"]


# ── Goals (durable task queue) ───────────────────────────────────────────────

def test_set_and_get_goals(brain: BrainService) -> None:
    gid = brain.set_goal(Goal(
        owner_agent="engineer",
        goal_text="implement feature X",
        complexity="complex",
    ))
    assert gid > 0
    goals = brain.get_goals(owner_agent="engineer", status="PENDING")
    assert len(goals) == 1
    assert goals[0]["goal_text"] == "implement feature X"
    assert goals[0]["complexity"] == "complex"


def test_update_goal_status_completed(brain: BrainService) -> None:
    gid = brain.set_goal(Goal(owner_agent="engineer", goal_text="ship X"))
    brain.update_goal(gid, status="COMPLETED")
    goals = brain.get_goals(owner_agent="engineer")
    assert goals[0]["status"] == "COMPLETED"
    assert goals[0]["last_reviewed_at"] is not None


def test_update_goal_current_value(brain: BrainService) -> None:
    gid = brain.set_goal(Goal(
        owner_agent="finance",
        goal_text="track monthly savings",
        goal_type="tracking",
        metric="savings_idr",
    ))
    brain.update_goal(gid, current_value="2500000")
    assert brain.get_goals(owner_agent="finance")[0]["current_value"] == "2500000"


# ── HITL pending actions ─────────────────────────────────────────────────────

def test_queue_action_and_list_pending(brain: BrainService) -> None:
    aid = brain.queue_action(
        agent_id="engineer",
        tool_name="commit_changes",
        tool_input={"files": ["x.py"], "message": "feat: x"},
        description="git commit 'feat: x'",
    )
    assert aid > 0
    pending = brain.get_pending_actions()
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "commit_changes"


def test_resolve_action_removes_from_pending(brain: BrainService) -> None:
    aid = brain.queue_action("engineer", "tool", {}, "desc")
    brain.resolve_action(aid, "approved", result="ok")
    assert brain.get_pending_actions() == []


def test_resolve_action_invalid_status_raises(brain: BrainService) -> None:
    aid = brain.queue_action("engineer", "tool", {}, "desc")
    with pytest.raises(ValueError):
        brain.resolve_action(aid, "maybe")


# ── Agent status board ───────────────────────────────────────────────────────

def test_update_and_get_status(brain: BrainService) -> None:
    brain.update_status("engineer", current_task="reviewing PR", weekly_focus="cashflow refactor")
    statuses = brain.get_status("engineer")
    assert len(statuses) == 1
    assert statuses[0]["current_task"] == "reviewing PR"
    assert statuses[0]["weekly_focus"] == "cashflow refactor"


def test_update_status_upserts(brain: BrainService) -> None:
    brain.update_status("engineer", current_task="t1")
    brain.update_status("engineer", current_task="t2")
    statuses = brain.get_status("engineer")
    assert statuses[0]["current_task"] == "t2"
