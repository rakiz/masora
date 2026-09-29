"""Brute-force suite for FORMAT.md §6 active-event evaluation and folding."""

from __future__ import annotations

import itertools
import random

import pytest

from masora.fold import Event, FoldCycleError, apply_precedence, fold_lineage, resolve_activity

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


def test_resolution_with_fingerprint_matcher_current_stale_restored():
    c1 = Event(id="01J8Z3K0000000000000000001", kind="claim", lineage="01J8Z3K0000000000000000001")
    c2 = Event(id="01J8Z3K0000000000000000002", kind="claim", lineage=c1.lineage)
    activity = resolve_activity([c1, c2])
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], fingerprint_matcher=lambda v: False
    )
    assert fold.displayed == c2.id
    assert fold.resolution == "stale"
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], fingerprint_matcher=lambda v: v == c1.id
    )
    assert fold.displayed == c1.id
    assert fold.resolution == "current"
    fold = fold_lineage(
        c1.lineage, [c1, c2], activity, [c1.id, c2.id], fingerprint_matcher=lambda v: v == c2.id
    )
    assert fold.displayed == c2.id
    assert fold.resolution == "current"
    r2 = Event(id="01J8Z3K0000000000000000004", kind="refute", lineage=c1.lineage, targets=c2.id)
    activity = resolve_activity([c1, c2, r2])
    fold = fold_lineage(
        c1.lineage, [c1, c2, r2], activity, [c1.id, c2.id], fingerprint_matcher=lambda v: v == c1.id
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
        fingerprint_matcher=lambda v: v == c1.id,
    )
    assert fold.displayed is None
    assert fold.resolution == "none"


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
