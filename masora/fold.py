"""Active-event evaluation, selection and status folding (FORMAT.md §6, MASORA_DESIGN.md §6.2).

`Event.contradicts` rides the record for witness closure in `masora/compact.py`;
the fold itself never reads it. The git context B(v) is injected at recall
(`VersionContext`); the fold stays pure — `check` and the format know nothing
of git or providers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

MAX_ACTIVITY_PASSES_FACTOR = 2

# Tier 1 of sel: the relations that prove a version sits on the asking line
# (MASORA_DESIGN.md §6.2). Everything else — including an unprovable context —
# ranks in tier 2 on ULID alone.
TIER1_RELATIONS = frozenset({"in_line", "ahead"})


class FoldCycleError(ValueError):
    pass


@dataclass
class Event:
    id: str
    kind: str
    lineage: str
    targets: str | None = None
    source: str | None = None
    verified_at: dict | None = None
    recorded_at: dict | None = None
    snapshots: dict | None = None
    contradicts: str | None = None


@dataclass
class LineageFold:
    lineage: str
    eligible_versions: tuple[str, ...]
    active_versions: tuple[str, ...]
    refuted_versions: tuple[str, ...]
    displayed: str | None
    restored: bool
    resolution: str | None
    verification_status: str
    verification_id: str | None
    verification_source: str | None
    verification_time: dict | None
    sources: tuple[str, ...] = field(default_factory=tuple)
    doubted: bool = False
    verification_snapshots: dict | None = None
    off_version: bool = False


@dataclass(frozen=True)
class VersionContext:
    """The per-version git context B(v) injected at recall (MASORA_DESIGN.md §6.2).

    `relation` describes the version's establishing commit against the asking
    HEAD: `in_line` (provable ancestor-or-equal), `ahead` (provable proper
    descendant that is also an ancestor-or-equal of the asking branch's
    upstream ref), `out_of_line` (provable, neither), `relation_unknown`
    (probe answered "unknown") — or `None` when the context is unprovable
    (missing object, shallow clone, probe budget exhausted). `ancestors`
    lists the version ULIDs whose establishing commits this version properly
    descends from — the ancestry-maxima input of tier 1.
    """

    version: str
    relation: str | None = None
    ancestors: frozenset[str] = frozenset()


def _relation(contexts: Mapping[str, VersionContext], version: str) -> str | None:
    context = contexts.get(version)
    return context.relation if context is not None else None


def _ancestors(contexts: Mapping[str, VersionContext], version: str) -> frozenset[str]:
    context = contexts.get(version)
    return context.ancestors if context is not None else frozenset()


def sel(versions: Iterable[str], contexts: Mapping[str, VersionContext]) -> str | None:
    """The selection function sel(S, B) (MASORA_DESIGN.md §6.2): the single
    best version of S under the per-version context B, or None for an empty S.

    Tier 1 gathers the versions provably on the asking line (`in_line` or
    `ahead`); `ahead` outranks `in_line`, within one relation kind a proper
    descendant beats its ancestors (maxima under proper ancestry over that
    relation kind alone) and the remaining ties break by descending ULID.
    Tier 2 — everything else, unprovable contexts included — ranks by
    descending ULID alone. With every context unprovable the function
    therefore reduces to descending-ULID order. Deterministic and
    order-independent; no pairwise order is claimed between the returned
    version and the rest."""
    candidates = set(versions)
    if not candidates:
        return None
    tier1 = [v for v in candidates if _relation(contexts, v) in TIER1_RELATIONS]
    if not tier1:
        return max(candidates)
    group = [v for v in tier1 if _relation(contexts, v) == "ahead"] or tier1
    # Maxima under proper ancestry: a version dominated by a proper
    # descendant in the same relation kind loses to it; the survivors are
    # mutually incomparable and tie-break by descending ULID.
    maxima = [v for v in group if not any(v in _ancestors(contexts, w) for w in group if w != v)]
    # Ancestry is injected data; a malformed (cyclic) injection falls back to
    # the ULID order instead of losing totality.
    return max(maxima or group)


def resolve_activity(events: list[Event], *, order: str | list[str] = "desc") -> dict[str, bool]:
    """Fixed-point evaluation of event activity; converges on the acyclic
    reference graph that `check` enforces (FORMAT.md §3), raises
    FoldCycleError when the update never settles (mutual refutation cycles)."""
    events = sorted(events, key=lambda e: e.id)
    if len({e.id for e in events}) != len(events):
        raise ValueError("duplicate event ids in fold input")
    ids = {e.id for e in events}
    dangling = {e.id for e in events if e.targets is not None and e.targets not in ids}
    refuters: dict[str, list[str]] = {}
    unrefuters: dict[str, list[str]] = {}
    undoubters: dict[str, list[str]] = {}
    for e in events:
        if e.targets is None or e.targets not in ids:
            continue
        if e.kind == "refute":
            refuters.setdefault(e.targets, []).append(e.id)
        elif e.kind == "unrefute":
            unrefuters.setdefault(e.targets, []).append(e.id)
        elif e.kind == "undoubt":
            undoubters.setdefault(e.targets, []).append(e.id)
    activity = {e.id: e.id not in dangling for e in events}
    if isinstance(order, list):
        passes = [next(e for e in events if e.id == i) for i in order]
    else:
        passes = sorted(events, key=lambda e: e.id, reverse=order == "desc")
    max_passes = MAX_ACTIVITY_PASSES_FACTOR * len(events) + 4
    for _ in range(max_passes):
        changed = False
        for e in passes:
            new = _is_active(e, activity, refuters, unrefuters, undoubters, dangling)
            if new != activity[e.id]:
                activity[e.id] = new
                changed = True
        if not changed:
            return activity
    raise FoldCycleError(
        f"active-event evaluation did not converge ({len(events)} events); the reference graph is cyclic"
    )


def _is_active(
    event: Event,
    activity: dict[str, bool],
    refuters: dict[str, list[str]],
    unrefuters: dict[str, list[str]],
    undoubters: dict[str, list[str]],
    dangling: set[str],
) -> bool:
    if event.id in dangling:
        return False
    if any(activity[r] for r in refuters.get(event.id, ())):
        return False
    if event.kind == "refute" and any(activity[u] for u in unrefuters.get(event.id, ())):
        return False
    return not (event.kind == "doubt" and any(activity[u] for u in undoubters.get(event.id, ())))


def fold_lineage(
    lineage: str,
    events: list[Event],
    activity: dict[str, bool],
    eligible_versions: list[str],
    *,
    outcomes: Mapping[str, str] | None = None,
    contexts: Mapping[str, VersionContext] | None = None,
) -> LineageFold:
    """Fold one lineage into its status data (MASORA_DESIGN.md §6.2 rules 3–8).

    `outcomes` maps version ULID to the composed anchor outcome (`match` /
    `mismatch` / `not_found` / `unavailable`, composed by
    `masora.resolve.compose_outcomes`) and `contexts` maps version ULID to
    its injected `VersionContext`; an omitted context is unprovable.
    Omitting `outcomes` entirely is the no-provider posture (standalone
    check, compact): every version is unevaluable, the unknown shadow covers
    the lineage and the fallback displays the newest active version.
    """
    versions = sorted(set(eligible_versions), reverse=True)
    active_versions = [v for v in versions if activity.get(v, False)]
    refuted_versions = [v for v in versions if not activity.get(v, False)]
    supplied = outcomes or {}
    # A version without a supplied outcome is unevaluable: it can never
    # silently match, and it shadows when it would win sel.
    outcome = {v: supplied.get(v, "unavailable") for v in versions}
    ctx = contexts or {}
    match_set = {v for v in active_versions if outcome[v] == "match"}
    # Rules 3 and 5 use the SAME sel: the matches display, and the no-match
    # fallback is sel over all active versions — this line's drift can never
    # be masked by a younger off-version, and a non-match can never hide a
    # match.
    displayed = sel(match_set, ctx) if match_set else sel(active_versions, ctx)
    # Rule 6 (counterfactual shadow): an active unavailable version sets the
    # unknown flag iff it would win sel over the matches; with no matches any
    # active unavailable version trivially does — the self-unavailable
    # displayed/fallback version included (rule 7: never a bare
    # current/stale).
    shadow = any(
        sel(match_set | {u}, ctx) == u for u in active_versions if outcome[u] == "unavailable"
    )
    # Rule 4 (counterfactual restored): only a displayed match can be
    # restored; a refuted R counts iff it would win sel over the matches,
    # whatever R's own composed outcome.
    restored = bool(match_set) and any(sel(match_set | {r}, ctx) == r for r in refuted_versions)
    if not versions:
        resolution = None
    elif not active_versions:
        resolution = "none"
    elif shadow:
        # The unknown shadow: callers map a None resolution through the
        # status precedence (none > unknown > current/restored > stale).
        resolution = None
    else:
        resolution = ("restored" if restored else "current") if match_set else "stale"
    # Rules 5 and 8: off-version needs the FALLBACK (never a displayed match)
    # to be definitively absent AND provably foreign; the shadow suppresses
    # the flag — the lineage is not provably inapplicable while an
    # unevaluable version might match.
    fallback = None if match_set else displayed
    fallback_context = ctx.get(fallback) if fallback is not None else None
    off_version = bool(
        fallback is not None
        and not shadow
        and outcome[fallback] == "not_found"
        and fallback_context is not None
        and fallback_context.relation == "out_of_line"
    )
    verifies = [
        e for e in events if e.kind == "verify" and e.targets == displayed and activity[e.id]
    ]
    verifies.sort(key=lambda e: e.id)
    shown = verifies[-1] if verifies else None
    sources = sorted({e.source for e in verifies if e.source is not None})
    verify_ids = {e.id for e in verifies}
    doubts = [e for e in events if e.kind == "doubt" and e.targets in verify_ids and activity[e.id]]
    return LineageFold(
        lineage=lineage,
        eligible_versions=tuple(versions),
        active_versions=tuple(active_versions),
        refuted_versions=tuple(refuted_versions),
        displayed=displayed,
        restored=restored,
        resolution=resolution,
        verification_status="verified" if shown is not None else "unverified",
        verification_id=shown.id if shown else None,
        verification_source=shown.source if shown else None,
        verification_time=shown.verified_at if shown else None,
        sources=tuple(sources),
        doubted=bool(doubts),
        verification_snapshots=shown.snapshots if shown is not None else None,
        off_version=off_version,
    )


def apply_precedence(resolution: str | None, unknown: bool) -> str | None:
    """Status precedence none > unknown > current/restored > stale (MASORA_DESIGN.md §6.2)."""
    if resolution == "none":
        return "none"
    if unknown:
        return "unknown"
    return resolution
