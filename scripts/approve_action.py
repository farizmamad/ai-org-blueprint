#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
approve_action.py - CLI for reviewing and resolving HITL pending actions.

Equivalent to the Discord !approve / !reject commands for setups without Discord.

Usage:
    python scripts/approve_action.py list
    python scripts/approve_action.py approve <id>
    python scripts/approve_action.py reject <id>
    python scripts/approve_action.py approve <id> --reason "looks good"
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.brain.service import BrainService

_DEFAULT_DB = os.environ.get("BRAIN_DB_PATH", "data/brain.db")


def _brain() -> BrainService:
    if not os.path.exists(_DEFAULT_DB):
        print(f"Error: database not found at {_DEFAULT_DB}", file=sys.stderr)
        print("Run 'python scripts/init_brain.py' first, or set BRAIN_DB_PATH.", file=sys.stderr)
        sys.exit(1)
    return BrainService(_DEFAULT_DB)


def cmd_list(_args: argparse.Namespace) -> None:
    actions = _brain().get_pending_actions()
    if not actions:
        print("No pending actions.")
        return
    for a in actions:
        print(f"[{a['id']}] {a['agent_id']} -> {a['tool_name']}")
        print(f"      {a['description']}")
        print(f"      created: {a['created_at']}")
        print()


def cmd_approve(args: argparse.Namespace) -> None:
    _brain().resolve_action(args.id, "approved", args.reason)
    print(f"Action {args.id} approved.")


def cmd_reject(args: argparse.Namespace) -> None:
    _brain().resolve_action(args.id, "rejected", args.reason)
    print(f"Action {args.id} rejected.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage HITL pending actions")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Show all pending actions")

    ap = sub.add_parser("approve", help="Approve a pending action")
    ap.add_argument("id", type=int)
    ap.add_argument("--reason", default=None, help="Optional note stored in result field")

    rp = sub.add_parser("reject", help="Reject a pending action")
    rp.add_argument("id", type=int)
    rp.add_argument("--reason", default=None, help="Optional note stored in result field")

    args = parser.parse_args()
    {"list": cmd_list, "approve": cmd_approve, "reject": cmd_reject}[args.command](args)


if __name__ == "__main__":
    main()
