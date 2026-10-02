"""Brute-force suite for FORMAT.md §6 active-event evaluation and folding."""

from __future__ import annotations

import itertools
import random

import pytest

from masora.fold import (
    Event,
    FoldCycleError,
    VersionContext,
    apply_precedence,
    fold_lineage,
    resolve_activity,
    sel,
)

KINDS = ("claim", "verify", "doubt", "undoubt", "refute", "unrefute")
ALLOWED_TARGET_KINDS = {
    "claim": frozenset(),
    "verify": frozenset({"claim"}),
    "doubt": frozenset({"verify"}),
    "undoubt": frozenset({"doubt"}),
    "refute": frozenset(KINDS),
    "unrefute": frozenset({"refute"}),
}
IDS = ["01J8Z3K000000000000000000" + c for c in "01234"]
EXHAUSTIVE_SIZES = (1, 2, 3, 4)
SAMPLED_SIZE = 5
SAMPLE_COUNT = 10000


def enumerate_graphs(n: int):
    for kinds in itertools.product(KINDS, repeat=n):
        choices = [
            [None] + [j for j in range(n) if kinds[j] in ALLOWED_TARGET_KINDS[kinds[i]]]
            for i in range(n)
        ]
        for combo in itertools.product(*choices):
            yield tuple(_event(kinds, combo, i) for i in range(n))


def sample_graphs(n: int, count: int, seed: int = 42):
    rng = random.Random(seed)
    seen = set()
    while len(seen) < count:
        kinds = tuple(rng.choice(KINDS) for _ in range(n))
        combo = [None] * n
        for i in range(n):
            compatible = [
                j for j in range(n) if j != i and kinds[j] in ALLOWED_TARGET_KINDS[kinds[i]]
            ]
            combo[i] = rng.choice([None] + compatible) if compatible else None
        key = (kinds, tuple(combo))
        if key in seen:
            continue
        events = tuple(_event(kinds, combo, i) for i in range(n))
        if has_cycle(list(events)):
            continue
        seen.add(key)
        yield events


def _event(kinds, combo, i) -> Event:
    target = combo[i]
    return Event(
        id=IDS[i],
        kind=kinds[i],
        lineage=IDS[0],
        targets=IDS[target] if target is not None else None,
        source="llm"
        if kinds[i] == "verify" and i % 2 == 0
        else ("human" if kinds[i] == "verify" else None),
    )


def has_cycle(events: list[Event]) -> bool:
    edges = {e.id: e.targets for e in events if e.targets is not None}
    for start in events:
        seen = set()
        node = start.id
        while node is not None:
            if node in seen:
                return True
            seen.add(node)
            node = edges.get(node)
    return False


def oracle_activity(events: list[Event]) -> dict[str, bool]:
    by_id = {e.id: e for e in events}
    ids = set(by_id)
    refuters: dict[str, list[str]] = {e.id: [] for e in events}
    unrefuters: dict[str, list[str]] = {e.id: [] for e in events}
    undoubters: dict[str, list[str]] = {e.id: [] for e in events}
    for e in events:
        if e.targets in ids:
            if e.kind == "refute":
                refuters[e.targets].append(e.id)
            elif e.kind == "unrefute":
                unrefuters[e.targets].append(e.id)
            elif e.kind == "undoubt":
                undoubters[e.targets].append(e.id)
    memo: dict[str, bool] = {}
    visiting: set[str] = set()

    def activity(event_id: str) -> bool:
        if event_id in memo:
            return memo[event_id]
        if event_id in visiting:
            raise AssertionError("oracle recursed into a cycle")
        visiting.add(event_id)
        event = by_id[event_id]
        if (
            event.targets is not None
            and event.targets not in ids
            or any(activity(r) for r in refuters[event_id])
            or event.kind == "refute"
            and any(activity(u) for u in unrefuters[event_id])
            or event.kind == "doubt"
            and any(activity(u) for u in undoubters[event_id])
        ):
            result = False
        else:
            result = True
        visiting.discard(event_id)
        memo[event_id] = result
        return result

    return {e.id: activity(e.id) for e in events}


ORDERS_FULL = ("desc", "asc", "shuffle-a", "shuffle-b")


def evaluation_order(events: list[Event], order: str) -> list[str]:
    ids = [e.id for e in events]
    if order == "desc":
        return sorted(ids, reverse=True)
    if order == "asc":
        return sorted(ids)
    rng = random.Random(0 if order == "shuffle-a" else 1)
    shuffled = ids[:]
    rng.shuffle(shuffled)
    return shuffled


def assert_order_independent(events: list[Event], expected: dict[str, bool]):
    for order in ORDERS_FULL:
        assert resolve_activity(events, order=evaluation_order(events, order)) == expected, (
            events,
            order,
        )


@pytest.mark.parametrize("n", EXHAUSTIVE_SIZES)
def test_exhaustive_fixed_point_matches_oracle_and_is_order_independent(n):
    checked = 0
    for events in enumerate_graphs(n):
        if has_cycle(events):
            continue
        expected = resolve_activity(list(events))
        assert expected == oracle_activity(list(events)), list(events)
        assert_order_independent(list(events), expected)
        assert resolve_activity(list(events)) == expected
        checked += 1
    assert checked > 0


def test_sampled_five_event_graphs_match_oracle_and_are_order_independent():
    checked = 0
    for events in sample_graphs(SAMPLED_SIZE, SAMPLE_COUNT):
        expected = resolve_activity(list(events))
        assert expected == oracle_activity(list(events)), list(events)
        for order in ("desc", "asc", "shuffle-a"):
            assert (
                resolve_activity(list(events), order=evaluation_order(events, order)) == expected
            ), list(events)
        checked += 1
    assert checked == SAMPLE_COUNT


@pytest.mark.parametrize("n", (2, 3, 4))
def test_cyclic_graphs_terminate_without_undefined_crashes(n):
    for events in enumerate_graphs(n):
        if not has_cycle(events):
            continue
        try:
            first = resolve_activity(list(events))
        except FoldCycleError:
            continue
        assert resolve_activity(list(events)) == first


def test_format_example_refute_chain():
    c = Event(id="01J8Z3K0000000000000000000", kind="claim", lineage="01J8Z3K0000000000000000000")
    v = Event(id="01J8Z3K0000000000000000001", kind="verify", lineage=c.lineage, targets=c.id)
    r1 = Event(id="01J8Z3K0000000000000000002", kind="refute", lineage=c.lineage, targets=v.id)
    r2 = Event(id="01J8Z3K0000000000000000003", kind="refute", lineage=c.lineage, targets=r1.id)
    events = [c, v, r1, r2]
    assert resolve_activity(events) == {c.id: True, v.id: True, r1.id: False, r2.id: True}
    fold = fold_lineage(c.lineage, events, resolve_activity(events), [c.id])
    assert fold.displayed == c.id
    assert fold.verification_status == "verified"
    assert fold.verification_id == v.id


def test_refute_then_unrefute_restores_target():
    c = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    r = Event(id="01J8Z3K0000000000000000002", kind="refute", lineage=c.lineage, targets=c.id)
    u = Event(id="01J8Z3K0000000000000000003", kind="unrefute", lineage=c.lineage, targets=r.id)
    activity = resolve_activity([c, r, u])
    assert activity == {c.id: True, r.id: False, u.id: True}
    fold = fold_lineage(c.lineage, [c, r, u], activity, [c.id])
    assert fold.displayed == c.id
    assert fold.restored is False
    assert fold.verification_status == "unverified"


def test_refute_of_refute_is_equivalent_to_unrefute():
    c = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    v = Event(id="01J8Z3K0000000000000000002", kind="verify", lineage=c.lineage, targets=c.id)
    r1 = Event(id="01J8Z3K0000000000000000003", kind="refute", lineage=c.lineage, targets=v.id)
    r2 = Event(id="01J8Z3K0000000000000000004", kind="refute", lineage=c.lineage, targets=r1.id)
    u = Event(id="01J8Z3K0000000000000000005", kind="unrefute", lineage=c.lineage, targets=r1.id)
    via_unrefute = resolve_activity([c, v, r1, u])
    via_refute_of_refute = resolve_activity([c, v, r1, r2])
    assert via_unrefute == {c.id: True, v.id: True, r1.id: False, u.id: True}
    assert via_refute_of_refute == {c.id: True, v.id: True, r1.id: False, r2.id: True}


def test_redundant_unrefutes_are_idempotent():
    c = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    v = Event(id="01J8Z3K0000000000000000002", kind="verify", lineage=c.lineage, targets=c.id)
    r = Event(id="01J8Z3K0000000000000000003", kind="refute", lineage=c.lineage, targets=v.id)
    u1 = Event(id="01J8Z3K0000000000000000004", kind="unrefute", lineage=c.lineage, targets=r.id)
    u2 = Event(id="01J8Z3K0000000000000000005", kind="unrefute", lineage=c.lineage, targets=r.id)
    one = resolve_activity([c, v, r, u1])
    two = resolve_activity([c, v, r, u1, u2])
    assert all(one[key] == two[key] for key in one)
    assert two[u2.id] is True
    assert one[r.id] is False and two[r.id] is False
    assert one[v.id] is True and two[v.id] is True


def test_doubt_and_undoubt_flag():
    c = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    v = Event(
        id="01J8Z3K0000000000000000002",
        kind="verify",
        lineage=c.lineage,
        targets=c.id,
        source="llm",
    )
    d = Event(id="01J8Z3K0000000000000000003", kind="doubt", lineage=c.lineage, targets=v.id)
    u = Event(id="01J8Z3K0000000000000000004", kind="undoubt", lineage=c.lineage, targets=d.id)
    activity = resolve_activity([c, v, d])
    fold = fold_lineage(c.lineage, [c, v, d], activity, [c.id])
    assert fold.doubted is True
    assert fold.verification_status == "verified"
    assert fold.sources == ("llm",)
    activity = resolve_activity([c, v, d, u])
    fold = fold_lineage(c.lineage, [c, v, d, u], activity, [c.id])
    assert fold.doubted is False
    assert fold.verification_status == "verified"


def test_doubt_of_refuted_verify_does_not_flag():
    c = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    v = Event(
        id="01J8Z3K0000000000000000002",
        kind="verify",
        lineage=c.lineage,
        targets=c.id,
        source="llm",
    )
    r = Event(id="01J8Z3K0000000000000000003", kind="refute", lineage=c.lineage, targets=v.id)
    d = Event(id="01J8Z3K0000000000000000004", kind="doubt", lineage=c.lineage, targets=v.id)
    fold = fold_lineage(c.lineage, [c, v, r, d], resolve_activity([c, v, r, d]), [c.id])
    assert fold.doubted is False
    assert fold.verification_status == "unverified"


def test_dangling_events_are_inactive():
    c = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    r = Event(
        id="01J8Z3K0000000000000000002",
        kind="refute",
        lineage=c.lineage,
        targets="01J8Z3K0000000000000000009",
    )
    activity = resolve_activity([c, r])
    assert activity == {c.id: True, r.id: False}


def test_skewed_refuter_below_target_still_deactivates():
    r = Event(
        id="01J8Z3K0000000000000000001",
        kind="refute",
        lineage="01J8Z3K0000000000000000001",
        targets="01J8Z3K0000000000000000002",
    )
    c = Event(id="01J8Z3K0000000000000000002", kind="claim", lineage=r.lineage)
    expected = {r.id: True, c.id: False}
    assert resolve_activity([r, c]) == expected
    assert resolve_activity([r, c], order=[c.id, r.id]) == expected


def test_newest_active_verify_wins_and_sources_accumulate():
    c = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    v1 = Event(
        id="01J8Z3K0000000000000000002",
        kind="verify",
        lineage=c.lineage,
        targets=c.id,
        source="human",
    )
    v2 = Event(
        id="01J8Z3K0000000000000000003",
        kind="verify",
        lineage=c.lineage,
        targets=c.id,
        source="llm",
    )
    fold = fold_lineage(c.lineage, [c, v1, v2], resolve_activity([c, v1, v2]), [c.id])
    assert fold.verification_id == v2.id
    assert fold.verification_source == "llm"
    assert fold.sources == ("human", "llm")


def test_all_refuted_resolves_none_and_restored_flag():
    c1 = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    c2 = Event(id="01J8Z3K0000000000000000002", kind="claim", lineage=c1.lineage)
    r1 = Event(id="01J8Z3K0000000000000000003", kind="refute", lineage=c1.lineage, targets=c1.id)
    fold = fold_lineage(c1.lineage, [c1, c2, r1], resolve_activity([c1, c2, r1]), [c1.id, c2.id])
    assert fold.displayed == c2.id
    assert fold.restored is False
    assert fold.resolution is None
    r2 = Event(id="01J8Z3K0000000000000000004", kind="refute", lineage=c1.lineage, targets=c2.id)
    fold = fold_lineage(
        c1.lineage, [c1, c2, r1, r2], resolve_activity([c1, c2, r1, r2]), [c1.id, c2.id]
    )
    assert fold.displayed is None
    assert fold.resolution == "none"


def test_resolution_with_structured_outcomes_current_stale_restored():
    c1 = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    c2 = Event(id="01J8Z3K0000000000000000002", kind="claim", lineage=c1.lineage)
    activity = resolve_activity([c1, c2])
    fold = fold_lineage(
        c1.lineage,
        [c1, c2],
        activity,
        [c1.id, c2.id],
        outcomes={c1.id: "mismatch", c2.id: "mismatch"},
    )
    assert fold.displayed == c2.id
    assert fold.resolution == "stale"
    assert fold.off_version is False
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], outcomes={c1.id: "match", c2.id: "mismatch"}
    )
    assert fold.displayed == c1.id
    assert fold.resolution == "current"
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], outcomes={c1.id: "mismatch", c2.id: "match"}
    )
    assert fold.displayed == c2.id
    assert fold.resolution == "current"
    r2 = Event(id="01J8Z3K0000000000000000004", kind="refute", lineage=c1.lineage, targets=c2.id)
    activity = resolve_activity([c1, c2, r2])
    fold = fold_lineage(
        c1.lineage,
        [c1, c2, r2],
        activity,
        [c1.id, c2.id],
        outcomes={c1.id: "match", c2.id: "mismatch"},
    )
    assert fold.displayed == c1.id
    assert fold.resolution == "restored"
    r1 = Event(id="01J8Z3K0000000000000000003", kind="refute", lineage=c1.lineage, targets=c1.id)
    activity = resolve_activity([c1, c2, r1, r2])
    fold = fold_lineage(
        c1.lineage,
        [c1, c2, r1, r2],
        activity,
        [c1.id, c2.id],
        outcomes={c1.id: "match", c2.id: "mismatch"},
    )
    assert fold.displayed is None
    assert fold.resolution == "none"


def test_not_found_fallback_with_provable_out_of_line_flags_off_version():
    c1 = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    c2 = Event(id="01J8Z3K0000000000000000002", kind="claim", lineage=c1.lineage)
    activity = resolve_activity([c1, c2])
    outcomes = {c1.id: "mismatch", c2.id: "not_found"}
    # An unprovable relation never grants the flag, whatever the outcome; the
    # fallback is the sel-winner c2 (higher ULID).
    for relation in ("in_line", "ahead", "out_of_line", "relation_unknown", None):
        contexts = {v: VersionContext(v, relation) for v in (c1.id, c2.id)}
        fold = fold_lineage(
            c1.lineage, [c1, c2], activity, [c1.id, c2.id], outcomes=outcomes, contexts=contexts
        )
        assert fold.displayed == c2.id
        assert fold.resolution == "stale"
        assert fold.off_version is (relation == "out_of_line")
    # A match in play suppresses the flag entirely: it belongs to the
    # no-match fallback only.
    matched = {c1.id: "match", c2.id: "not_found"}
    contexts = {v: VersionContext(v, "out_of_line") for v in (c1.id, c2.id)}
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], outcomes=matched, contexts=contexts
    )
    assert fold.displayed == c1.id
    assert fold.resolution == "current"
    assert fold.off_version is False
    # An unavailable rival shadows the would-be off-version fallback: the
    # lineage is not provably inapplicable while it might match.
    shadowed = {c1.id: "unavailable", c2.id: "not_found"}
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], outcomes=shadowed, contexts=contexts
    )
    assert fold.resolution is None
    assert fold.off_version is False


def test_unavailable_version_shadows_only_when_it_would_win_sel():
    c1 = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    c2 = Event(id="01J8Z3K0000000000000000002", kind="claim", lineage=c1.lineage)
    activity = resolve_activity([c1, c2])
    outcomes = {c1.id: "match", c2.id: "unavailable"}
    # c2 outranks c1 by ULID (tier 2, unprovable contexts): it would win sel,
    # so it shadows — and the displayed version stays the known match. At the
    # fold level the shadow is a None resolution; precedence maps it to
    # `unknown` upstream.
    fold = fold_lineage(c1.lineage, [c1, c2], activity, [c1.id, c2.id], outcomes=outcomes)
    assert fold.resolution is None
    assert fold.displayed == c1.id
    # With c2 provably ahead it still wins tier 1 and still shadows.
    contexts = {
        c1.id: VersionContext(c1.id, "in_line"),
        c2.id: VersionContext(c2.id, "ahead"),
    }
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], outcomes=outcomes, contexts=contexts
    )
    assert fold.resolution is None
    assert fold.displayed == c1.id
    # With c1 ahead of c2, the unavailable c2 can no longer win sel: no
    # shadow, plain current.
    contexts = {
        c1.id: VersionContext(c1.id, "ahead"),
        c2.id: VersionContext(c2.id, "in_line"),
    }
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], outcomes=outcomes, contexts=contexts
    )
    assert fold.resolution == "current"
    assert fold.displayed == c1.id


def test_restored_is_counterfactual_over_sel_whatever_the_refuted_outcome():
    c1 = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    c2 = Event(id="01J8Z3K0000000000000000002", kind="claim", lineage=c1.lineage)
    r2 = Event(id="01J8Z3K0000000000000000004", kind="refute", lineage=c1.lineage, targets=c2.id)
    activity = resolve_activity([c1, c2, r2])
    contexts = {
        c1.id: VersionContext(c1.id, "in_line"),
        c2.id: VersionContext(c2.id, "ahead"),
    }
    # The refuted c2 would win sel (tier 1 ahead over in_line) even though
    # its own anchors are unevaluable: restored fires on the uncertainty of
    # its rank, not its fingerprints.
    fold = fold_lineage(
        c1.lineage,
        [c1, c2, r2],
        activity,
        [c1.id, c2.id],
        outcomes={c1.id: "match", c2.id: "unavailable"},
        contexts=contexts,
    )
    assert fold.restored is True
    # A refutation that never outranks the displayed match triggers nothing.
    contexts = {
        c1.id: VersionContext(c1.id, "ahead"),
        c2.id: VersionContext(c2.id, "in_line"),
    }
    fold = fold_lineage(
        c1.lineage,
        [c1, c2, r2],
        activity,
        [c1.id, c2.id],
        outcomes={c1.id: "match", c2.id: "mismatch"},
        contexts=contexts,
    )
    assert fold.restored is False
    assert fold.resolution == "current"


def test_exhaustive_envelope_invariants():
    for events in enumerate_graphs(4):
        if has_cycle(list(events)):
            continue
        activity = resolve_activity(list(events))
        claims = [e.id for e in events if e.kind == "claim"]
        fold = fold_lineage(IDS[0], list(events), activity, claims)
        assert fold.displayed is None or fold.displayed in fold.active_versions
        assert set(fold.active_versions) | set(fold.refuted_versions) == set(claims)
        assert not (set(fold.active_versions) & set(fold.refuted_versions))
        if fold.verification_status == "verified":
            assert any(
                e.kind == "verify" and e.targets == fold.displayed and activity[e.id]
                for e in events
            )
            assert fold.verification_source in fold.sources
        else:
            assert not any(
                e.kind == "verify" and e.targets == fold.displayed and activity[e.id]
                for e in events
            )
        if fold.doubted:
            verify_ids = {
                e.id
                for e in events
                if e.kind == "verify" and e.targets == fold.displayed and activity[e.id]
            }
            assert any(
                e.kind == "doubt" and e.targets in verify_ids and activity[e.id] for e in events
            )
        if fold.resolution == "none":
            assert fold.active_versions == ()
        if fold.restored:
            assert fold.displayed is not None
            assert any(v > fold.displayed for v in fold.refuted_versions)


def test_precedence_none_over_unknown_over_current_restored_over_stale():
    assert apply_precedence("none", unknown=True) == "none"
    assert apply_precedence("none", unknown=False) == "none"
    assert apply_precedence(None, unknown=True) == "unknown"
    assert apply_precedence("current", unknown=True) == "unknown"
    assert apply_precedence("restored", unknown=True) == "unknown"
    assert apply_precedence("stale", unknown=True) == "unknown"
    assert apply_precedence("current", unknown=False) == "current"
    assert apply_precedence("restored", unknown=False) == "restored"
    assert apply_precedence("stale", unknown=False) == "stale"
    assert apply_precedence(None, unknown=False) is None


# --- §6.2 structured outcomes: sel and the counterfactual rules ------------
#
# The oracle below re-derives the §6.2 contract from the design text,
# independently of masora/fold.py: the two-tier selection sel(S, B) and the
# display / restored / no-match / shadow / off-version rules over composed
# per-version outcomes. Every case asserts the implementation agrees with
# the oracle and that the structural invariants hold.

RELATION_VALUES = ("in_line", "ahead", "out_of_line", "relation_unknown", None)
OUTCOME_VALUES = ("match", "mismatch", "not_found", "unavailable")
# Lexicographic ULID order deliberately differs from index order.
VERSION_IDS = (
    "01J8Z3K0000000000000000M0",
    "01J8Z3K0000000000000000A1",
    "01J8Z3K0000000000000000Z2",
    "01J8Z3K0000000000000000B3",
)


def oracle_sel(candidates, contexts):
    """sel(S, B) from the §6.2 text: tier 1 = provably on the asking line
    (`ahead` outranks `in_line`; within one relation kind, maxima under
    proper ancestry, then descending ULID); tier 2 = everything else,
    descending ULID; empty S selects nothing."""
    if not candidates:
        return None
    tier1 = [v for v in candidates if contexts[v].relation in ("in_line", "ahead")]
    if not tier1:
        return max(candidates)
    group = [v for v in tier1 if contexts[v].relation == "ahead"] or tier1
    maxima = [v for v in group if not any(v in contexts[w].ancestors for w in group if w != v)]
    return max(maxima or group)


def oracle_fold(versions, activity, outcomes, contexts):
    """§6.2 rules 3–8 re-derived over structured outcomes."""
    versions = sorted(set(versions), reverse=True)
    active = [v for v in versions if activity.get(v, False)]
    refuted = [v for v in versions if not activity.get(v, False)]
    matches = {v for v in active if outcomes[v] == "match"}
    displayed = oracle_sel(matches, contexts) if matches else oracle_sel(active, contexts)
    shadow = any(
        oracle_sel(matches | {u}, contexts) == u for u in active if outcomes[u] == "unavailable"
    )
    restored = bool(matches) and any(oracle_sel(matches | {r}, contexts) == r for r in refuted)
    if not versions:
        resolution = None
    elif not active:
        resolution = "none"
    elif shadow:
        resolution = None
    else:
        resolution = ("restored" if restored else "current") if matches else "stale"
    fallback = None if matches else displayed
    off_version = bool(
        fallback is not None
        and not shadow
        and outcomes[fallback] == "not_found"
        and contexts[fallback].relation == "out_of_line"
    )
    return displayed, restored, resolution, off_version


def assert_fold_matches_oracle(events, activity, versions, outcomes, contexts):
    fold = fold_lineage(
        IDS[0], list(events), activity, list(versions), outcomes=outcomes, contexts=contexts
    )
    displayed, restored, resolution, off_version = oracle_fold(
        versions, activity, outcomes, contexts
    )
    assert (fold.displayed, fold.restored, fold.resolution, fold.off_version) == (
        displayed,
        restored,
        resolution,
        off_version,
    ), (outcomes, contexts)
    # Exactly one answer, and it is a live version or nothing.
    assert fold.displayed is None or activity.get(fold.displayed)
    matches = {v for v in versions if activity.get(v, False) and outcomes[v] == "match"}
    # A non-match can never display over a match: the fallback only fires
    # when the match set is empty.
    if matches:
        assert fold.displayed in matches
    # restored / shadow / off-version are well-defined on every input.
    if fold.restored:
        assert matches
        assert any(
            oracle_sel(matches | {v}, contexts) == v for v in versions if not activity.get(v, False)
        )
        assert fold.resolution in ("restored", None)
    if fold.resolution == "unknown" and fold.active_versions:
        assert any(
            oracle_sel(matches | {u}, contexts) == u
            for u in fold.active_versions
            if outcomes[u] == "unavailable"
        )
    if fold.off_version:
        assert fold.resolution == "stale"
        assert outcomes[fold.displayed] == "not_found"
        assert contexts[fold.displayed].relation == "out_of_line"
    # Determinism: folding the same input again gives the same answer.
    again = fold_lineage(
        IDS[0], list(events), activity, list(versions), outcomes=outcomes, contexts=contexts
    )
    assert again == fold
    return fold


def _ancestry_configurations(ids):
    """Every ancestry assignment over `ids` (including cyclic ones — the fold
    must stay total on injected data)."""
    pairs = [(v, w) for v in ids for w in ids if w != v]
    for bits in itertools.product((False, True), repeat=len(pairs)):
        ancestors = {v: frozenset(w for (v, w), keep in zip(pairs, bits) if keep) for v in ids}
        yield {v: VersionContext(v, None, ancestors[v]) for v in ids}


def test_sel_unit_tier_semantics():
    a, b, c = VERSION_IDS[0], VERSION_IDS[1], VERSION_IDS[2]
    assert sel([], {}) is None
    assert sel({a}, {}) == a
    # Tier 2 (all unprovable): descending ULID.
    assert sel([a, b, c], {}) == c  # ...Z2 sorts last
    # Tier 1 beats tier 2 regardless of ULID; ahead beats in_line.
    contexts = {
        a: VersionContext(a, "in_line"),
        b: VersionContext(b, "ahead"),
        c: VersionContext(c, None),
    }
    assert sel([a, b, c], contexts) == b
    contexts = {
        a: VersionContext(a, "in_line"),
        b: VersionContext(b, "relation_unknown"),
        c: VersionContext(c, "out_of_line"),
    }
    assert sel([a, b, c], contexts) == a
    # Within one relation kind, a proper descendant beats its ancestors —
    # even an ancestor with a higher ULID; incomparable maxima tie-break by
    # descending ULID.
    mid, low, high = VERSION_IDS[0], VERSION_IDS[1], VERSION_IDS[2]
    contexts = {
        mid: VersionContext(mid, "in_line", frozenset({high})),  # mid descends from high
        high: VersionContext(high, "in_line"),
        low: VersionContext(low, "in_line"),
    }
    assert sel([mid, high, low], contexts) == mid
    contexts = {
        mid: VersionContext(mid, "in_line"),
        high: VersionContext(high, "in_line"),
        low: VersionContext(low, "in_line"),
    }
    assert sel([mid, high, low], contexts) == high


def test_sel_is_order_independent_and_total():
    rng = random.Random(1234)
    checked = 0
    for _ in range(5000):
        k = rng.randint(0, len(VERSION_IDS))
        ids = rng.sample(VERSION_IDS, k)
        # Ancestors only from earlier in a random permutation: acyclic by
        # construction, not necessarily transitive.
        order = ids[:]
        rng.shuffle(order)
        contexts = {
            v: VersionContext(
                v,
                rng.choice(RELATION_VALUES),
                frozenset(w for w in order[:i] if rng.random() < 0.4),
            )
            for i, v in enumerate(order)
        }
        expected = oracle_sel(set(ids), contexts)
        assert expected is None or expected in set(ids)
        for _round in range(3):
            shuffled = ids[:]
            rng.shuffle(shuffled)
            assert sel(shuffled, contexts) == expected
        checked += 1
    assert checked == 5000


def test_exhaustive_two_version_structured_fold_matches_oracle():
    ids = VERSION_IDS[:2]
    checked = 0
    for activity_bits in itertools.product((True, False), repeat=len(ids)):
        activity = dict(zip(ids, activity_bits))
        for outcomes_tuple in itertools.product(OUTCOME_VALUES, repeat=len(ids)):
            outcomes = dict(zip(ids, outcomes_tuple))
            for relations in itertools.product(RELATION_VALUES, repeat=len(ids)):
                for contexts in _ancestry_configurations(ids):
                    for v, relation in zip(ids, relations):
                        contexts[v] = VersionContext(v, relation, contexts[v].ancestors)
                    assert_fold_matches_oracle((), activity, ids, outcomes, contexts)
                    checked += 1
    assert checked == 2**2 * 4**2 * 5**2 * 2**2


def test_random_structured_folds_match_oracle():
    rng = random.Random(77)
    checked = 0
    for _ in range(20000):
        k = rng.randint(1, len(VERSION_IDS))
        ids = list(VERSION_IDS[:k])
        activity = {v: rng.random() < 0.6 for v in ids}
        outcomes = {v: rng.choice(OUTCOME_VALUES) for v in ids}
        order = ids[:]
        rng.shuffle(order)
        contexts = {
            v: VersionContext(
                v,
                rng.choice(RELATION_VALUES),
                frozenset(w for w in order[:i] if rng.random() < 0.3),
            )
            for i, v in enumerate(order)
        }
        assert_fold_matches_oracle((), activity, ids, outcomes, contexts)
        checked += 1
    assert checked == 20000


def test_structured_fold_over_event_graphs_matches_oracle():
    """Ties the structured-outcome fold to REAL event DAGs: refuted and
    active versions mixed by the activity fixed point, not by hand."""
    rng = random.Random(99)
    checked = 0
    for events in enumerate_graphs(3):
        if has_cycle(list(events)):
            continue
        activity = resolve_activity(list(events))
        claims = [e.id for e in events if e.kind == "claim"]
        if not claims:
            continue
        for _ in range(3):
            order = claims[:]
            rng.shuffle(order)
            outcomes = {v: rng.choice(OUTCOME_VALUES) for v in claims}
            contexts = {
                v: VersionContext(
                    v,
                    rng.choice(RELATION_VALUES),
                    frozenset(w for w in order[:i] if rng.random() < 0.3),
                )
                for i, v in enumerate(order)
            }
            assert_fold_matches_oracle(events, activity, claims, outcomes, contexts)
            checked += 1
    assert checked > 700


@pytest.mark.parametrize("n", EXHAUSTIVE_SIZES)
def test_unprovable_contexts_reduce_to_the_legacy_walk(n):
    """The regression guarantee: with every version's context unprovable, sel
    ranks by descending ULID and the fold reproduces the legacy walk exactly
    (first match in descending-ULID order displays; a refuted version newer
    than the displayed one flagged restored)."""
    checked = 0
    for events in enumerate_graphs(n):
        if has_cycle(list(events)):
            continue
        activity = resolve_activity(list(events))
        claims = [e.id for e in events if e.kind == "claim"]
        if not claims:
            continue
        for bits in itertools.product((True, False), repeat=len(claims)):
            matcher = dict(zip(claims, bits))
            outcomes = {v: ("match" if m else "mismatch") for v, m in matcher.items()}
            new = fold_lineage(
                IDS[0], list(events), activity, claims, outcomes=outcomes, contexts={}
            )
            versions = sorted(set(claims), reverse=True)
            active = [v for v in versions if activity.get(v, False)]
            refuted = [v for v in versions if not activity.get(v, False)]
            matched = [v for v in active if matcher[v]]
            legacy_displayed = matched[0] if matched else (active[0] if active else None)
            legacy_restored = legacy_displayed is not None and any(
                v > legacy_displayed for v in refuted
            )
            if not versions:
                legacy_resolution = None
            elif not active:
                legacy_resolution = "none"
            elif not matched:
                legacy_resolution = "stale"
            else:
                legacy_resolution = "restored" if legacy_restored else "current"
            assert new.displayed == legacy_displayed, (events, matcher)
            assert new.resolution == legacy_resolution, (events, matcher)
            if matched:
                # On the matched path the counterfactual reduces to the
                # legacy ULID comparison exactly; on the no-match path the
                # design retires the flag (§6.2 rule 4 — only a displayed
                # match can be restored).
                assert new.restored == legacy_restored, (events, matcher)
            else:
                assert new.restored is False
            checked += 1
    assert checked > 0
