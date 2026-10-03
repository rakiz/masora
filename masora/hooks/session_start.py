#!/usr/bin/env python3
"""masora SessionStart freshness hook (MASORA_DESIGN.md §10.1).

Installed by `masora hook install`; registered as a Claude Code
SessionStart command (or spawned by an opencode plugin). Background and
best-effort: fetches + fast-forwards the configured base clones, rebuilds
stale indexes within the §10.1 wall-clock budget and prints at most ONE
line — the stale-lineage summary. Every failure is silent, exit 0 always;
the hook must never block or fail a session start.
"""

from masora.hook import session_start

if __name__ == "__main__":
    raise SystemExit(session_start())
