"""Tests for the stacking audit (masora/audit.py) — pure functions, no I/O."""

from __future__ import annotations

from helpers import ULID_L1, ULID_L2, anchor, make_claim, make_verify

from masora.audit import (
    ANCHOR_FILES_MAX,
    ANCHORS_MAX,
    STATEMENT_MAX,
    audit_pending,
    stacking_signals,
)

FILE_IDENTITY = "scip-clang cxx . src/engine.cpp . mongo/Engine#commitShard()."


def test_atomic_claim_fires_no_signals():
    assert stacking_signals(make_claim(ULID_L1)) == []


def test_long_statement_fires_statement_signal():
    claim = make_claim(ULID_L1, statement="x" * (STATEMENT_MAX + 1))

    signals = stacking_signals(claim)

    assert len(signals) == 1
    assert str(STATEMENT_MAX + 1) in signals[0]
    assert "statement" in signals[0]


def test_many_anchors_fire_anchor_count_signal():
    claim = make_claim(
        ULID_L1,
        anchors=[
            anchor(identity=f"scip-clang cxx . . sym{i}#f().") for i in range(ANCHORS_MAX + 1)
        ],
    )

    signals = stacking_signals(claim)

    assert len(signals) == 1
    assert str(ANCHORS_MAX + 1) in signals[0]
    assert "anchors" in signals[0]


def test_multifile_anchors_fire_span_signal():
    claim = make_claim(
        ULID_L1,
        anchors=[
            anchor(identity=f"scip-clang cxx . src/file{i}.cpp . sym{i}#f().")
            for i in range(ANCHOR_FILES_MAX + 1)
        ],
    )

    signals = stacking_signals(claim)

    assert len(signals) == 1
    assert str(ANCHOR_FILES_MAX + 1) in signals[0]
    assert "files" in signals[0]


def test_all_three_signals_fire_together():
    claim = make_claim(
        ULID_L1,
        statement="x" * (STATEMENT_MAX + 1),
        anchors=[
            anchor(identity=f"scip-clang cxx . src/f{i}.cpp . s{i}#f().")
            for i in range(ANCHORS_MAX + 1)
        ],
    )

    assert len(stacking_signals(claim)) == 3


def test_threshold_boundaries_are_quiet():
    # 8 anchors (exactly ANCHORS_MAX) spanning exactly 3 distinct files
    # (exactly ANCHOR_FILES_MAX), with a statement of exactly STATEMENT_MAX.
    claim = make_claim(
        ULID_L1,
        statement="x" * STATEMENT_MAX,
        anchors=[
            anchor(identity=f"scip-clang cxx . src/f{i % ANCHOR_FILES_MAX}.cpp . s{i}#f().")
            for i in range(ANCHORS_MAX)
        ],
    )

    assert stacking_signals(claim) == []


def test_verify_event_is_ignored_even_when_over_every_threshold():
    event = make_verify(ULID_L1, ULID_L1, ULID_L1) | {"statement": "x" * (STATEMENT_MAX + 1)}

    assert audit_pending([("2026-09/x/claim.md", event)]) == {}


def test_audit_pending_keys_flagged_claims_by_lineage():
    claim = make_claim(ULID_L1, statement="x" * (STATEMENT_MAX + 1))

    flagged = audit_pending([("2026-09/x/claim.md", claim)])

    assert flagged == {ULID_L1: [f"statement is {STATEMENT_MAX + 1} chars (> {STATEMENT_MAX})"]}


def test_audit_pending_keys_by_file_path_when_no_lineage():
    claim = make_claim(ULID_L1, statement="x" * (STATEMENT_MAX + 1))
    del claim["lineage"]

    flagged = audit_pending([("2026-09/x/claim.md", claim)])

    assert list(flagged) == ["2026-09/x/claim.md"]


def test_audit_pending_merges_signals_across_claims_of_a_lineage():
    # Two pending claim versions of ONE lineage, each firing a different
    # threshold: the lineage is flagged once, carrying both signals.
    statement_claim = make_claim(ULID_L1, statement="x" * (STATEMENT_MAX + 1))
    anchors_claim = make_claim(
        ULID_L2,
        lineage=ULID_L1,
        anchors=[
            anchor(identity=f"scip-clang cxx . . sym{i}#f().") for i in range(ANCHORS_MAX + 1)
        ],
    )

    flagged = audit_pending([("a.md", statement_claim), ("b.md", anchors_claim)])

    assert flagged == {
        ULID_L1: [
            f"statement is {STATEMENT_MAX + 1} chars (> {STATEMENT_MAX})",
            f"{ANCHORS_MAX + 1} anchors (> {ANCHORS_MAX})",
        ]
    }


def test_audit_pending_passes_clean_claims_and_keeps_first_lineage_order():
    clean = make_claim(ULID_L1)
    stacked = make_claim("01J8Z3K0000000000000000006", statement="x" * (STATEMENT_MAX + 1))

    flagged = audit_pending(
        [("a.md", clean), ("b.md", stacked), ("c.md", make_verify(ULID_L1, ULID_L1, ULID_L1))]
    )

    assert list(flagged) == ["01J8Z3K0000000000000000006"]
