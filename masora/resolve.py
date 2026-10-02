"""§6.2 resolution: the full status tuple over folded lineage data (MASORA_DESIGN.md §6.2, §12.4).

Pure functions: lineage data is parsed/validated upstream, providers are
injected. The provider registry maps anchor kind -> callable or None; per
anchor, a missing or None registry entry is `unavailable`, a callable
returning None is `not_found`, a fingerprint equality is `match` and
anything else is `mismatch` — composed per version by `compose_outcomes`
(§6.2 step 1)."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from . import fold
from .fold import Event

FingerprintFn = Callable[[str, str], str | None]
EdgeSnapshotFn = Callable[[str, str], dict | None]


@dataclass(frozen=True)
class AnchorData:
    provider: str
    identity: str
    fingerprint: str
    snapshot: dict | None = None


@dataclass(frozen=True)
class VersionData:
    id: str
    anchors: tuple[AnchorData, ...] = ()
    unanchored: bool = False


@dataclass(frozen=True)
class LineageStatus:
    lineage: str
    displayed: str | None
    resolution: str
    verification_status: str
    verification_source: str | None
    active: tuple[str, ...]
    refuted: tuple[str, ...]
    suspect: bool
    doubted: bool
    pending: bool
    unknown: bool
    unanchored: bool
    off_version: bool = False

    @property
    def verification(self) -> str:
        if self.verification_status == "verified":
            return f"verified({self.verification_source})"
        return "unverified"


def resolve_lineage(
    lineage: str,
    versions: Sequence[VersionData],
    events: Sequence[Event],
    fingerprints: Mapping[str, FingerprintFn | None],
    *,
    edge_snapshots: Mapping[str, EdgeSnapshotFn | None] | None = None,
    pending_ids: Collection[str] = (),
    contexts: Mapping[str, fold.VersionContext] | None = None,
) -> LineageStatus:
    """Compute the status tuple of one lineage (MASORA_DESIGN.md §6.2).

    Founder-absent exclusion is applied to build the eligible set; activity
    fixed point, selection, folding and precedence are delegated to fold.py;
    only the composed anchor outcomes, `suspect` (§12.4) and `pending` (§8)
    live here. `contexts` injects the per-version git relation B(v) at
    recall (`fold.VersionContext`); an omitted mapping leaves every context
    unprovable and the selection ranks by descending ULID alone.
    """
    edge_snapshots = edge_snapshots or {}
    by_id = {v.id: v for v in versions}
    founder = any(v.id == lineage for v in versions)
    eligible = [v.id for v in versions if v.id == lineage or founder]
    activity = fold.resolve_activity(list(events))
    outcomes = compose_outcomes([by_id[v] for v in eligible], fingerprints)
    status = fold.fold_lineage(
        lineage, list(events), activity, eligible, outcomes=outcomes, contexts=contexts
    )
    displayed = by_id.get(status.displayed) if status.displayed else None
    resolution = status.resolution
    unknown = False
    if resolution is None:
        # A None fold resolution is the unknown shadow over live candidates —
        # or no eligible version at all; precedence keeps `none` above it.
        resolution = "unknown"
        unknown = True
    return LineageStatus(
        lineage=lineage,
        displayed=status.displayed,
        resolution=resolution,
        verification_status=status.verification_status,
        verification_source=status.verification_source,
        active=status.active_versions,
        refuted=status.refuted_versions,
        suspect=_suspect(displayed, status, edge_snapshots) if displayed else False,
        doubted=status.doubted,
        pending=any(e.id in pending_ids for e in events),
        unknown=unknown,
        unanchored=displayed.unanchored if displayed else False,
        off_version=status.off_version,
    )


def compose_outcomes(
    versions: Sequence[VersionData], fingerprints: Mapping[str, FingerprintFn | None]
) -> dict[str, str]:
    """Composed per-version anchor outcome (§6.2 step 1): `unavailable` when
    any anchor cannot be evaluated, else `not_found` when any anchor is
    definitively absent, else `mismatch` when any fingerprint differs, else
    `match`. Unanchored versions always match. Every anchor is considered —
    no provider call is skipped on the way to a verdict."""
    return {v.id: _version_outcome(v, fingerprints) for v in versions}


def _version_outcome(version: VersionData, fingerprints: Mapping[str, FingerprintFn | None]) -> str:
    if version.unanchored:
        return "match"
    unavailable = False
    not_found = False
    mismatch = False
    for a in version.anchors:
        fn = fingerprints.get(a.provider)
        if fn is None:
            unavailable = True
            continue
        observed = fn(a.provider, a.identity)
        if observed is None:
            not_found = True
        elif observed != a.fingerprint:
            mismatch = True
    if unavailable:
        return "unavailable"
    if not_found:
        return "not_found"
    if mismatch:
        return "mismatch"
    return "match"


def _suspect(
    displayed: VersionData,
    status: fold.LineageFold,
    edge_snapshots: Mapping[str, EdgeSnapshotFn | None],
) -> bool:
    """§12.4: edge-set drift on the displayed version's anchors or their 1-hop neighbours.

    Compared against the newest observation (the displayed verify's snapshot,
    else the claim's write-time one) over the union of recorded and current
    neighbours. A kind with no edge provider is skipped — with only e.g. the
    `file` provider registered, suspect never fires.
    """
    snapshots = status.verification_snapshots or {
        a.identity: a.snapshot for a in displayed.anchors if a.snapshot is not None
    }
    kinds = {a.identity: a.provider for a in displayed.anchors}
    for identity, snapshot in snapshots.items():
        kind = kinds.get(identity)
        fn = edge_snapshots.get(kind) if kind is not None else None
        if fn is None:
            continue
        current = fn(kind, identity)
        if current is None:
            return True
        if current.get("edges") != snapshot.get("edges"):
            return True
        recorded_n = snapshot.get("neighbours") or {}
        current_n = current.get("neighbours") or {}
        if any(recorded_n.get(n) != current_n.get(n) for n in recorded_n.keys() | current_n.keys()):
            return True
    return False
