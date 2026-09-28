"""§6.2 resolution: the full status tuple over folded lineage data (MASORA_DESIGN.md §6.2, §12.4).

Pure functions: lineage data is parsed/validated upstream, providers are
injected. A provider registry maps anchor kind -> callable or None; a missing
or None entry means the provider is unavailable (the `unknown` flag), while a
callable returning None means the anchor is not_found (it simply fails to
match).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from . import fold
from .fold import Event, apply_precedence

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
    verification_actor: str | None
    active: tuple[str, ...]
    refuted: tuple[str, ...]
    suspect: bool
    doubted: bool
    pending: bool
    unknown: bool
    unanchored: bool

    @property
    def verification(self) -> str:
        if self.verification_status == "verified":
            return f"verified({self.verification_actor})"
        return "unverified"


def resolve_lineage(
    lineage: str,
    versions: Sequence[VersionData],
    events: Sequence[Event],
    fingerprints: Mapping[str, FingerprintFn | None],
    *,
    edge_snapshots: Mapping[str, EdgeSnapshotFn | None] | None = None,
    pending_ids: Collection[str] = (),
) -> LineageStatus:
    """Compute the status tuple of one lineage (MASORA_DESIGN.md §6.2).

    Founder-absent exclusion is applied to build the eligible set; activity
    fixed point, folding and precedence are delegated to fold.py; only the
    fingerprint walk, `suspect` (§12.4) and `pending` (§8) live here.
    """
    edge_snapshots = edge_snapshots or {}
    by_id = {v.id: v for v in versions}
    founder = any(v.id == lineage for v in versions)
    eligible = [v.id for v in versions if v.id == lineage or founder]
    activity = fold.resolve_activity(list(events))
    unknown = _unavailable_on_walk(by_id, activity, eligible, fingerprints)
    status = fold.fold_lineage(
        lineage,
        list(events),
        activity,
        eligible,
        fingerprint_matcher=_matcher(by_id, fingerprints),
        provider_available=not unknown,
    )
    displayed = by_id.get(status.displayed) if status.displayed else None
    resolution = apply_precedence(status.resolution, unknown=unknown)
    if resolution is None:
        resolution = "unknown"
        unknown = True
    return LineageStatus(
        lineage=lineage,
        displayed=status.displayed,
        resolution=resolution,
        verification_status=status.verification_status,
        verification_actor=status.verification_actor,
        active=status.active_versions,
        refuted=status.refuted_versions,
        suspect=_suspect(displayed, status, edge_snapshots) if displayed else False,
        doubted=status.doubted,
        pending=any(e.id in pending_ids for e in events),
        unknown=unknown,
        unanchored=displayed.unanchored if displayed else False,
    )


def _matcher(
    by_id: Mapping[str, VersionData], fingerprints: Mapping[str, FingerprintFn | None]
) -> Callable[[str], bool]:
    def match(version_id: str) -> bool:
        version = by_id[version_id]
        if version.unanchored:
            return True
        for a in version.anchors:
            fn = fingerprints.get(a.provider)
            if fn is None or fn(a.provider, a.identity) != a.fingerprint:
                return False
        return True

    return match


def _unavailable_on_walk(
    by_id: Mapping[str, VersionData],
    activity: Mapping[str, bool],
    eligible: Sequence[str],
    fingerprints: Mapping[str, FingerprintFn | None],
) -> bool:
    """True when the newest-first walk (§6.2 steps 1–4) hits an unevaluable version.

    The walk stops at the first match, so only unavailability *before* that
    point shadows the resolution; an anchor not_found (callable returns None)
    simply fails to match and the walk continues.
    """
    for version_id in sorted(eligible, reverse=True):
        if not activity.get(version_id, False):
            continue
        version = by_id[version_id]
        if version.unanchored:
            return False
        if any(fingerprints.get(a.provider) is None for a in version.anchors):
            return True
        if all(
            fingerprints[a.provider](a.provider, a.identity) == a.fingerprint
            for a in version.anchors
        ):
            return False
    return False


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
