#!/usr/bin/env python3
"""
init_brain.py — initialise the Brain SQLite database.

Creates data/brain.db (or BRAIN_DB_PATH from .env) and runs the schema.
Safe to run multiple times — CREATE TABLE IF NOT EXISTS everywhere.

Usage:
    python scripts/init_brain.py
    BRAIN_DB_PATH=/tmp/test.db python scripts/init_brain.py
"""

from __future__ import annotations

import os
import sys

# Allow running from any directory inside the repo
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from core.brain.service import BrainService, DEFAULT_DB_PATH


def main() -> None:
    db_path = os.environ.get("BRAIN_DB_PATH", DEFAULT_DB_PATH)
    print(f"Initialising Brain at: {db_path}")

    brain = BrainService(db_path=db_path)

    # Verify the schema is live by doing a harmless read
    _ = brain.get_status()
    print("Schema OK.")

    # Stamp the version so seed scripts can check it
    brain.remember("shared", "brain_version", "1.0")
    print("Done. Brain is ready.")


if __name__ == "__main__":
    main()
