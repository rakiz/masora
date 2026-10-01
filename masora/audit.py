"""Stacking audit for the `masora sync` publication gate (MASORA_DESIGN.md §12).

A multi-fact "block claim" note is tolerated locally — no command blocks on
writing one — but must not reach the shared base: it is all-or-nothing to
verify, to stale and to refute. The audit is a pure heuristic over parsed
pending claim events; `masora sync` owns the refusal and the override.
"""

from __future__ import annotations

# WHY conservative: the thresholds separate the known block claims from atomic
# notes on the real corpus (132 lineages, 7 known block claims) without
# false-flagging; calibration against the real base happens at the next sync.
# Tune them there, never silently here.
STATEMENT_MAX = 900
ANCHORS_MAX = 8
ANCHOR_FILES_MAX = 3

REMEDY = (
    "split into atomic notes: corrections are new events, never edits — "
    "or pass --allow-stacked to publish anyway"
)


def stacking_signals(claim: dict) -> list[str]:
    """Human-readable stacking signals for each fired threshold of a parsed
    claim event; exactly at a limit is never a signal."""
    signals: list[str] = []
    statement = claim.get("statement")
    if isinstance(statement, str) and len(statement) > STATEMENT_MAX:
        signals.append(f"statement is {len(statement)} chars (> {STATEMENT_MAX})")
    anchors = claim.get("anchors")
    anchors = [a for a in anchors if isinstance(a, dict)] if isinstance(anchors, list) else []
    if len(anchors) > ANCHORS_MAX:
        signals.append(f"{len(anchors)} anchors (> {ANCHORS_MAX})")
    files = {file for file in (_anchor_file(a) for a in anchors) if file is not None}
    if len(files) > ANCHOR_FILES_MAX:
        signals.append(f"anchors span {len(files)} distinct files (> {ANCHOR_FILES_MAX})")
    return signals


def audit_pending(events: list[tuple[str, dict]]) -> dict[str, list[str]]:
    """Fired signals per lineage id (or file path when the event carries no
    lineage), over CLAIM events only — verify/doubt/refute/undoubt events are
    structurally small and can never stack."""
    flagged: dict[str, list[str]] = {}
    for path, event in events:
        if not isinstance(event, dict) or event.get("kind") != "claim":
            continue
        signals = stacking_signals(event)
        if not signals:
            continue
        lineage = event.get("lineage")
        key = lineage if isinstance(lineage, str) and lineage else path
        existing = flagged.get(key, [])
        flagged[key] = existing + [signal for signal in signals if signal not in existing]
    return flagged


def _anchor_file(anchor: dict) -> str | None:
    """The definition file an anchor pins to, from the SCIP source-unit token
    of its identity — the one token the identity grammar can carry a path in
    ('.' when the identity records no file, the common namespace-only shape)."""
    identity = anchor.get("identity")
    if not isinstance(identity, str):
        return None
    tokens = identity.split(" ")
    if len(tokens) < 5 or tokens[0] != "scip-clang":
        return None
    source_unit = tokens[3]
    return None if source_unit == "." else source_unit
