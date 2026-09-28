"""Active-event evaluation and status folding (FORMAT.md §6, MASORA_DESIGN.md §6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_ACTIVITY_PASSES_FACTOR = 2


class FoldCycleError(ValueError):
    pass


@dataclass
class Event:
    id: str
    kind: str
    lineage: str
    targets: str | None = None
    actor: str | None = None
    verified_at: dict | None = None
    recorded_at: dict | None = None


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
    verification_actor: str | None
    verification_time: dict | None
    actors: tuple[str, ...] = field(default_factory=tuple)
    doubted: bool = False


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
    raise FoldCycleError(f"active-event evaluation did not converge ({len(events)} events); the reference graph is cyclic")


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
    if event.kind == "doubt" and any(activity[u] for u in undoubters.get(event.id, ())):
        return False
    return True


def fold_lineage(
    lineage: str,
    events: list[Event],
    activity: dict[str, bool],
    eligible_versions: list[str],
    *,
    fingerprint_matcher=None,
    provider_available: bool = True,
) -> LineageFold:
    versions = sorted(set(eligible_versions), reverse=True)
    active_versions = [v for v in versions if activity.get(v, False)]
    refuted_versions = [v for v in versions if not activity.get(v, False)]
    matched = [v for v in active_versions if fingerprint_matcher is not None and provider_available and fingerprint_matcher(v)]
    if matched:
        displayed = matched[0]
    elif active_versions:
        displayed = active_versions[0]
    else:
        displayed = None
    restored = displayed is not None and any(v > displayed for v in refuted_versions)
    if not versions:
        resolution = None
    elif not active_versions:
        resolution = "none"
    elif not provider_available or fingerprint_matcher is None:
        resolution = None
    else:
        resolution = ("restored" if restored else "current") if matched else "stale"
    verifies = [e for e in events if e.kind == "verify" and e.targets == displayed and activity[e.id]]
    verifies.sort(key=lambda e: e.id)
    shown = verifies[-1] if verifies else None
    actors = sorted({e.actor for e in verifies if e.actor is not None})
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
        verification_actor=shown.actor if shown else None,
        verification_time=shown.verified_at if shown else None,
        actors=tuple(actors),
        doubted=bool(doubts),
    )


def apply_precedence(resolution: str | None, unknown: bool) -> str | None:
    """Status precedence none > unknown > current/restored > stale (MASORA_DESIGN.md §6.2)."""
    if resolution == "none":
        return "none"
    if unknown:
        return "unknown"
    return resolution
