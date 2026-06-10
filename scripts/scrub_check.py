#!/usr/bin/env python3
"""
scrub_check.py — scan the repo for accidental PII and secret leaks.

Checks every tracked source file for patterns that should never appear in
a public repo: real API keys, hardcoded credentials, and email addresses.

Exit codes:
    0 — clean (safe to publish)
    1 — one or more violations found

Patterns checked:
    • Anthropic API keys  (sk-ant-...)
    • OpenAI API keys     (sk-proj-... / sk-...)
    • AWS access key IDs  (AKIA...)
    • Generic secrets     password= / secret= / token= with an inline value
    • Email addresses     (user@domain.tld) — skipped in test fixtures

Usage:
    python scripts/scrub_check.py
    python scripts/scrub_check.py --path /some/other/dir
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── Patterns ─────────────────────────────────────────────────────────────────

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Anthropic API key",  re.compile(r"sk-ant-[a-zA-Z0-9\-_]{20,}")),
    ("OpenAI API key",     re.compile(r"sk-proj-[a-zA-Z0-9\-_]{20,}|sk-[a-zA-Z0-9]{48}")),
    ("AWS access key ID",  re.compile(r"AKIA[A-Z0-9]{16}")),
    ("Hardcoded secret",   re.compile(
        r'(?i)(password|passwd|secret|api_key|token)\s*=\s*["\'][^"\']{8,}["\']'
    )),
    ("Email address",      re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    )),
]

# Files / directories to skip entirely
SKIP_PATHS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "data", "node_modules", ".eggs", "dist", "build",
}

# File extensions to scan
SCAN_EXTENSIONS = {
    ".py", ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg",
    ".env", ".sh", ".md",
}

# Lines containing these strings are allowed to match the email pattern
# (they're example/placeholder values, not real PII)
EMAIL_ALLOWLIST = [
    "example.com", "yourdomain.com", "your-email", "<your",
    "user@host", "user@domain",  # generic placeholders in docs/comments
    "noreply@", "test@", "foo@", "bar@",
]


def should_skip(path: Path) -> bool:
    return any(part in SKIP_PATHS for part in path.parts)


def check_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_number, pattern_name, matched_text)."""
    violations: list[tuple[int, str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return violations

    for lineno, line in enumerate(lines, start=1):
        for name, pattern in PATTERNS:
            match = pattern.search(line)
            if not match:
                continue

            # Apply email allowlist to reduce false positives
            if name == "Email address":
                if any(allowed in line for allowed in EMAIL_ALLOWLIST):
                    continue
                # Skip obvious test files
                if "test" in str(path).lower() or "fixture" in str(path).lower():
                    continue

            violations.append((lineno, name, match.group(0)))

    return violations


def main(root: Path) -> int:
    total_violations = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if should_skip(path.relative_to(root)):
            continue
        if path.suffix not in SCAN_EXTENSIONS:
            continue

        violations = check_file(path)
        if violations:
            for lineno, name, matched in violations:
                # Redact the match so the CI log itself doesn't leak
                redacted = matched[:6] + "***" if len(matched) > 6 else "***"
                print(f"  {path.relative_to(root)}:{lineno}  [{name}]  {redacted}")
            total_violations += len(violations)

    if total_violations:
        print(f"\nscrub-check FAILED — {total_violations} violation(s) found.")
        print("Fix before publishing. If a match is a false positive, add it to EMAIL_ALLOWLIST.")
        return 1

    print("scrub-check PASSED — no leaks detected.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan repo for accidental PII/secret leaks.")
    parser.add_argument("--path", default=".", help="Root directory to scan (default: .)")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    sys.exit(main(root))
