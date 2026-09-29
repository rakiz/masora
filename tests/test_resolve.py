"""§6.2 resolution matrix over pure lineage data (MASORA_DESIGN.md §6.2, §12.4)."""

from __future__ import annotations

import pytest
from helpers import (
    FP,
    FP2,
    IDENT_MAIN,
    IDENT_OTHER,
    ULID_D1A,
    ULID_L1,
    ULID_R1A,
    ULID_U1A,
    ULID_V1A,
    ULID_V2A,
)

from masora.fold import Event
from masora.resolve import AnchorData, VersionData, resolve_lineage

L = ULID_L1
F = ULID_L1
V2 = ULID_V2A
REF = ULID_R1A
DOUBT = ULID_D1A
UNDOUBT = ULID_U1A
VERIFY = ULID_V1A
IDENT_X = "scip-clang cxx . . example#zed()."
SNAP = {"edges": FP, "neighbours": {IDENT_OTHER: FP}}


def claim_event(uid: str) -> Event:
    return Event(id=uid, kind="claim", lineage=L)


def events_for(*uids: str) -> list[Event]:
    return [claim_event(uid) for uid in uids]


def vrow(
    uid: str,
    fingerprint: str = FP,
    snapshot: dict | None = None,
    unanchored: bool = False,
    provider: str = "code",
    identity: str = IDENT_MAIN,
) -> VersionData:
    anchors = () if unanchored else (AnchorData(provider, identity, fingerprint, snapshot),)
    return VersionData(uid, anchors, unanchored)


def registry(mode: str, fp_map: dict, edge_map: dict | None = None):
    if mode == "none":
        return {}
    fn = (lambda kind, identity: fp_map.get(identity)) if mode == "code" else None
    if edge_map is None:
        return {"code": fn}
    return {"code": fn}, {"code": lambda kind, identity: edge_map.get(identity)}


def resolve(versions, events, providers, pending_ids=frozenset()):
    fingerprints, edge_snapshots = providers if isinstance(providers, tuple) else (providers, {})
    return resolve_lineage(
        L, versions, events, fingerprints, edge_snapshots=edge_snapshots, pending_ids=pending_ids
    )


MATRIX = [
    (
        "current",
        (vrow(F),),
        events_for(F),
        registry("code", {IDENT_MAIN: FP}),
        {},
        {
            "resolution": "current",
            "displayed": F,
            "suspect": False,
            "doubted": False,
            "pending": False,
            "unknown": False,
            "unanchored": False,
            "verification": "unverified",
        },
    ),
    (
        "stale-not-found",
        (vrow(F),),
        events_for(F),
        registry("code", {}),
        {},
        {"resolution": "stale", "displayed": F, "unknown": False},
    ),
    (
        "stale-mismatch",
        (vrow(F),),
        events_for(F),
        registry("code", {IDENT_MAIN: FP2}),
        {},
        {"resolution": "stale", "displayed": F},
    ),
    (
        "restored",
        (vrow(F), vrow(V2, FP2)),
        [*events_for(F, V2), Event(id=REF, kind="refute", lineage=L, targets=V2)],
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "restored", "displayed": F},
    ),
    (
        "none",
        (vrow(F),),
        [*events_for(F), Event(id=REF, kind="refute", lineage=L, targets=F)],
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "none", "displayed": None},
    ),
    (
        "refuted-newer-still-stale",
        (vrow(F), vrow(V2, FP2)),
        [*events_for(F, V2), Event(id=REF, kind="refute", lineage=L, targets=V2)],
        registry("code", {IDENT_MAIN: FP2}),
        {},
        {"resolution": "stale", "displayed": F},
    ),
    (
        "newest-match-wins",
        (vrow(F), vrow(V2, FP)),
        events_for(F, V2),
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "current", "displayed": V2},
    ),
    (
        "older-match-fallthrough",
        (vrow(F), vrow(V2, FP2)),
        events_for(F, V2),
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "current", "displayed": F},
    ),
    (
        "unknown-registry-missing",
        (vrow(F),),
        events_for(F),
        registry("none", {}),
        {},
        {"resolution": "unknown", "displayed": F, "unknown": True},
    ),
    (
        "unknown-registry-null-entry",
        (vrow(F),),
        events_for(F),
        registry("null", {}),
        {},
        {"resolution": "unknown", "displayed": F, "unknown": True},
    ),
    (
        "none-beats-unknown",
        (vrow(F),),
        [*events_for(F), Event(id=REF, kind="refute", lineage=L, targets=F)],
        registry("none", {}),
        {},
        {"resolution": "none", "displayed": None, "unknown": False},
    ),
    (
        "unanchored-current",
        (vrow(F, unanchored=True),),
        events_for(F),
        registry("none", {}),
        {},
        {"resolution": "current", "displayed": F, "unknown": False, "unanchored": True},
    ),
    (
        "founder-absent-excluded",
        (vrow(V2),),
        events_for(V2),
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "unknown", "displayed": None, "unknown": True},
    ),
    (
        "refute-then-unrefute",
        (vrow(F),),
        [
            *events_for(F),
            Event(id=REF, kind="refute", lineage=L, targets=F),
            Event(id=UNDOUBT, kind="unrefute", lineage=L, targets=REF),
        ],
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "current", "displayed": F},
    ),
    (
        "suspect-own-edges",
        (vrow(F, snapshot=SNAP),),
        events_for(F),
        registry(
            "code", {IDENT_MAIN: FP}, {IDENT_MAIN: {"edges": FP2, "neighbours": {IDENT_OTHER: FP}}}
        ),
        {},
        {"resolution": "current", "suspect": True},
    ),
    (
        "suspect-neighbour-changed",
        (vrow(F, snapshot=SNAP),),
        events_for(F),
        registry(
            "code", {IDENT_MAIN: FP}, {IDENT_MAIN: {"edges": FP, "neighbours": {IDENT_OTHER: FP2}}}
        ),
        {},
        {"resolution": "current", "suspect": True},
    ),
    (
        "suspect-neighbour-added",
        (vrow(F, snapshot=SNAP),),
        events_for(F),
        registry(
            "code",
            {IDENT_MAIN: FP},
            {IDENT_MAIN: {"edges": FP, "neighbours": {IDENT_OTHER: FP, IDENT_X: FP}}},
        ),
        {},
        {"resolution": "current", "suspect": True},
    ),
    (
        "suspect-neighbour-removed",
        (vrow(F, snapshot={"edges": FP, "neighbours": {IDENT_OTHER: FP, IDENT_X: FP}}),),
        events_for(F),
        registry(
            "code", {IDENT_MAIN: FP}, {IDENT_MAIN: {"edges": FP, "neighbours": {IDENT_OTHER: FP}}}
        ),
        {},
        {"resolution": "current", "suspect": True},
    ),
    (
        "no-suspect-unchanged",
        (vrow(F, snapshot=SNAP),),
        events_for(F),
        registry(
            "code", {IDENT_MAIN: FP}, {IDENT_MAIN: {"edges": FP, "neighbours": {IDENT_OTHER: FP}}}
        ),
        {},
        {"resolution": "current", "suspect": False},
    ),
    (
        "suspect-composes-with-stale",
        (vrow(F, snapshot=SNAP),),
        events_for(F),
        registry("code", {IDENT_MAIN: FP2}, {IDENT_MAIN: {"edges": FP2, "neighbours": {}}}),
        {},
        {"resolution": "stale", "suspect": True},
    ),
    (
        "doubted",
        (vrow(F),),
        [
            *events_for(F),
            Event(id=VERIFY, kind="verify", lineage=L, targets=F, source="llm"),
            Event(id=DOUBT, kind="doubt", lineage=L, targets=VERIFY),
        ],
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "current", "doubted": True, "verification": "verified(llm)"},
    ),
    (
        "doubt-on-refuted-verify",
        (vrow(F),),
        [
            *events_for(F),
            Event(id=VERIFY, kind="verify", lineage=L, targets=F, source="llm"),
            Event(id=DOUBT, kind="doubt", lineage=L, targets=VERIFY),
            Event(id=REF, kind="refute", lineage=L, targets=VERIFY),
        ],
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "current", "doubted": False, "verification": "unverified"},
    ),
    (
        "later-verify-keeps-doubt",
        (vrow(F),),
        [
            *events_for(F),
            Event(id=VERIFY, kind="verify", lineage=L, targets=F, source="llm"),
            Event(id=DOUBT, kind="doubt", lineage=L, targets=VERIFY),
            Event(id=UNDOUBT, kind="verify", lineage=L, targets=F, source="human"),
        ],
        registry("code", {IDENT_MAIN: FP}),
        {},
        {"resolution": "current", "doubted": True, "verification": "verified(human)"},
    ),
    (
        "pending",
        (vrow(F),),
        events_for(F),
        registry("code", {IDENT_MAIN: FP}),
        {F},
        {"resolution": "current", "pending": True},
    ),
    (
        "not-pending",
        (vrow(F),),
        events_for(F),
        registry("code", {IDENT_MAIN: FP}),
        {V2},
        {"resolution": "current", "pending": False},
    ),
]


@pytest.mark.parametrize(
    "name,versions,events,providers,pending,expected",
    MATRIX,
    ids=[row[0] for row in MATRIX],
)
def test_resolution_matrix(name, versions, events, providers, pending, expected):
    status = resolve(versions, events, providers, pending_ids=frozenset(pending))
    for key, value in expected.items():
        assert getattr(status, key) == value, key


def test_suspect_uses_newest_active_verify_snapshot():
    versions = (vrow(F, snapshot=SNAP),)
    events = [
        *events_for(F),
        Event(
            id=VERIFY,
            kind="verify",
            lineage=L,
            targets=F,
            source="llm",
            snapshots={IDENT_MAIN: {"edges": FP2, "neighbours": {}}},
        ),
    ]
    current = registry("code", {IDENT_MAIN: FP}, {IDENT_MAIN: {"edges": FP2, "neighbours": {}}})
    assert resolve(versions, events, current).suspect is False
    stale_edges = registry("code", {IDENT_MAIN: FP}, {IDENT_MAIN: {"edges": FP, "neighbours": {}}})
    assert resolve(versions, events, stale_edges).suspect is True


def test_refuted_verify_snapshot_unused():
    versions = (vrow(F, snapshot=SNAP),)
    events = [
        *events_for(F),
        Event(
            id=VERIFY,
            kind="verify",
            lineage=L,
            targets=F,
            source="llm",
            snapshots={IDENT_MAIN: {"edges": FP2, "neighbours": {}}},
        ),
        Event(id=REF, kind="refute", lineage=L, targets=VERIFY),
    ]
    providers = registry("code", {IDENT_MAIN: FP}, {IDENT_MAIN: {"edges": FP, "neighbours": {}}})
    status = resolve(versions, events, providers)
    assert status.suspect is True


def test_suspect_never_fires_without_edge_provider():
    versions = (vrow(F, snapshot=SNAP),)
    events = events_for(F)
    status = resolve(versions, events, registry("none", {}))
    assert status.resolution == "unknown"
    assert status.suspect is False


def test_suspect_fires_when_edge_provider_answers_symbol_gone():
    versions = (vrow(F, snapshot=SNAP),)
    events = events_for(F)
    providers = registry("code", {IDENT_MAIN: FP}, {IDENT_MAIN: None})
    status = resolve(versions, events, providers)
    assert status.suspect is True


def test_file_provider_registry_pin():
    versions = (vrow(F, provider="file", snapshot=SNAP),)
    events = events_for(F)
    providers = ({"file": lambda kind, identity: FP}, {})
    status = resolve(versions, events, providers)
    assert status.resolution == "current"
    assert status.suspect is False


def test_unavailable_provider_after_first_match_does_not_shadow():
    versions = (vrow(F, provider="file"), vrow(V2, provider="file", fingerprint=FP2))
    providers = ({"file": lambda kind, identity: FP}, {})
    status = resolve(versions, events_for(F, V2), providers)
    assert status.resolution == "current"
    assert status.displayed == F
    assert status.unknown is False


def test_unavailable_provider_before_first_match_shadows():
    versions = (vrow(F, provider="file"), vrow(V2, provider="code"))
    providers = ({"file": lambda kind, identity: FP}, {})
    status = resolve(versions, events_for(F, V2), providers)
    assert status.resolution == "unknown"
    assert status.unknown is True
