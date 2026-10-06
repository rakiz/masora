"""`masora explain`: the complete story of ONE lineage, statuses included.

The rollout lesson: an agent wanting one lineage's full story improvised an
rg over the base's directories and read RAW event files — which carry NO
status, so a refuted/doubted claim looked valid. This is the canonical door:
the state is computed FRESH from the lineage's event files (never the index —
a stale index cannot lie here), and the render shows the status tuple, the
effective version's content and the full event chain with the active
verify's evidence.

With a code repo, the git context is re-derived LIVE with a fresh probe
budget (MASORA_DESIGN.md §6.2): the per-version relations drive the same
two-tier sel the index uses, and the render surfaces the context explicitly —
the lineage's `off-version` field, its `context_ordering` (`exact`/
`degraded`) and each claim version's `[established: <relation>]` in the event
chain. Without a repo nothing is provable: the anchors report `unknown` and
no context is rendered.
"""

from __future__ import annotations

from pathlib import Path

from . import gitctx, resolve
from .checker import _parse_event_file, check_base, discover_event_files
from .diagnostics import E_EXPLAIN_UNKNOWN, Diag
from .fold import Event, fold_lineage, resolve_activity
from .frontmatter import load_frontmatter
from .index import file_fingerprint_provider
from .providers import CppgraphRegistry, cppgraph_registry
from .resolve import AnchorData, VersionData, compose_outcomes, resolve_lineage
from .schema import EventRecord


class ExplainError(Exception):
    def __init__(self, *diags: Diag):
        super().__init__(diags[0].message if diags else "explain refused")
        self.diags = list(diags)


def explain_lineage(base_dir: Path, lineage_id: str, repo: Path | None = None) -> str:
    """The readable story of one lineage: the status tuple, the effective
    version's content, the anchors' current match state, the full event chain
    in ULID order and the active verify's evidence in full. With a repo the
    git context is re-derived live (fresh budget) and surfaced. Raises
    ExplainError (E-NOT-A-BASE, other base errors, E-EXPLAIN-UNKNOWN);
    nothing is ever written.

    An EVENT ULID (a non-lineage id) resolves to the lineage carrying it —
    the story is the lineage's, never an empty render. The graph registry's
    sqlite handle is closed when the story is built (M6).
    """
    pre = check_base(base_dir)
    if pre.errors:
        raise ExplainError(*pre.errors)
    records = _lineage_records(base_dir, lineage_id)
    if not records:
        raise ExplainError(
            Diag(
                "error",
                E_EXPLAIN_UNKNOWN,
                f"no event or lineage matches {lineage_id!r} in {base_dir} — the id is the"
                " lineage ULID (a claim whose id equals its lineage); masora check lists every"
                " lineage",
            )
        )
    # An event ULID (verify, doubt, refute, …) names its lineage: resolve it,
    # never render an empty story for a well-formed id that exists.
    if not any(record.kind == "claim" and record.id == lineage_id for record in records):
        lineage_id = records[0].lineage
        records = _lineage_records(base_dir, lineage_id)
    registry_repo: CppgraphRegistry | None = cppgraph_registry(repo) if repo is not None else None
    try:
        fingerprints, edge_snapshots = _registries(registry_repo, repo)
        # M2: one provider evaluation per anchor across the outcome
        # composition, the resolution and the render's anchor lines.
        fingerprints, edge_snapshots = resolve.memoized(fingerprints, edge_snapshots)
        return _explain(base_dir, lineage_id, records, repo, fingerprints, edge_snapshots)
    finally:
        if registry_repo is not None:
            registry_repo.close()


def _explain(
    base_dir: Path,
    lineage_id: str,
    records,
    repo: Path | None,
    fingerprints: dict,
    edge_snapshots: dict,
) -> str:
    by_id = {record.id: record for record in records}
    fold_events = [_fold_event(record) for record in records]
    claims = [record for record in records if record.kind == "claim"]
    founder_present = any(record.id == lineage_id for record in claims)
    eligible = [record.id for record in claims if record.id == lineage_id or founder_present]
    version_data = tuple(
        VersionData(
            id=record.id,
            anchors=_record_anchors(base_dir, record),
            unanchored=record.unanchored,
        )
        for record in claims
    )
    activity = resolve_activity(fold_events)
    # The same composed outcomes the status used, so the fold's displayed
    # version (the known match under an unknown shadow, else the fallback)
    # always agrees with the status tuple above.
    outcomes = compose_outcomes(version_data, fingerprints)
    contexts: dict[str, gitctx.VersionContext] = {}
    ordering: str | None = None
    if repo is not None:
        # Fresh budget per explain (§6.2): explain's own ordering is
        # authoritative for its output — the index is never consulted.
        prober = gitctx.RelationProber(repo, gitctx.asking_line(repo))
        contexts = prober.lineage_contexts(
            {record.id: record.timestamp_commit for record in claims}
        )
        ordering = gitctx.context_ordering(
            lineage_id, fold_events, activity, eligible, outcomes, contexts
        )
    status = resolve_lineage(
        lineage_id,
        version_data,
        fold_events,
        fingerprints,
        edge_snapshots=edge_snapshots,
        contexts=contexts,
    )
    fold = fold_lineage(
        lineage_id, fold_events, activity, eligible, outcomes=outcomes, contexts=contexts
    )
    relations = {version: ctx.relation for version, ctx in contexts.items()}
    return _render(
        base_dir, records, by_id, activity, fold, status, fingerprints, relations, ordering
    )


def _lineage_records(base_dir: Path, lineage_id: str) -> list[EventRecord]:
    records = []
    for path in discover_event_files(base_dir):
        rel = str(path.relative_to(base_dir))
        record = _parse_event_file(path, rel, [])
        if record is not None and (record.lineage == lineage_id or record.id == lineage_id):
            records.append(record)
    return sorted(records, key=lambda record: record.id)


def _fold_event(record: EventRecord) -> Event:
    timestamp = {
        "commit": record.timestamp_commit,
        "graph_commit": record.timestamp_graph_commit,
    }
    return Event(
        id=record.id,
        kind=record.kind,
        lineage=record.lineage,
        targets=record.targets,
        source=record.source,
        contradicts=record.contradicts,
        verified_at=timestamp if record.kind == "verify" else None,
        recorded_at=timestamp if record.kind != "verify" else None,
    )


def _frontmatter(base_dir: Path, record: EventRecord) -> dict:
    return load_frontmatter((base_dir / record.path).read_text(encoding="utf-8"), record.path)


def _record_anchors(base_dir: Path, record: EventRecord) -> tuple[AnchorData, ...]:
    if record.kind != "claim" or record.unanchored:
        return ()
    return tuple(
        AnchorData(
            provider=a["provider"],
            identity=a["identity"],
            fingerprint=a["fingerprint"],
            snapshot=a.get("snapshot"),
        )
        for a in (_frontmatter(base_dir, record).get("anchors") or [])
    )


def _registries(registry, repo: Path | None) -> tuple[dict, dict]:
    """The fingerprint/edge mappings; the registry handle (with its sqlite
    connection) is owned and closed by `explain_lineage` (M6)."""
    if repo is None:
        return {}, {}
    return (
        {"file": file_fingerprint_provider(repo), "code": registry.fingerprints},
        {"file": None, "code": registry.edges},
    )


def _claim_summary(record: EventRecord, by_id: dict[str, EventRecord]) -> str:
    """The claim summary an event is about, following the targets chain."""
    current = record
    seen: set[str] = set()
    while current is not None and current.kind != "claim" and current.id not in seen:
        seen.add(current.id)
        current = by_id.get(current.targets) if current.targets else None
    if current is None:
        return record.targets or "?"
    return current.summary or current.id


def _writer(record: EventRecord) -> str:
    if record.source is None:
        return ""
    return f" ({record.source}: {record.name})" if record.name else f" ({record.source})"


def _anchor_lines(
    base_dir: Path,
    fold_displayed: str | None,
    by_id: dict[str, EventRecord],
    fingerprints: dict,
) -> list[str]:
    if fold_displayed is None:
        return []
    record = by_id.get(fold_displayed)
    anchors = _record_anchors(base_dir, record) if record else ()
    if not anchors:
        return []
    lines = ["  anchors:"]
    for anchor in anchors:
        fn = fingerprints.get(anchor.provider) if fingerprints else None
        if fn is None:
            state = "unknown"
        else:
            current = fn(anchor.provider, anchor.identity)
            if current is None:
                state = "not_found"
            elif current == anchor.fingerprint:
                state = "matched"
            else:
                state = "changed"
        lines.append(f"    {anchor.provider} {anchor.identity} — {state}")
    return lines


def _event_lines(
    record: EventRecord,
    by_id: dict[str, EventRecord],
    activity: dict[str, bool],
    relations: dict[str, str | None],
) -> list[str]:
    kind = record.kind
    what = _claim_summary(record, by_id)
    if kind == "claim":
        label = "founder" if record.id == record.lineage else "v2+"
        line = f"    {record.id} claim{_writer(record)} — {label}: {record.summary or ''}"
        # The version's OWN context, never another version's (§6.2); a
        # version with no proven relation renders no suffix — the lineage's
        # `context:` field carries the degraded visibility.
        if relations.get(record.id):
            line += f" [established: {relations[record.id]}]"
        if not activity.get(record.id, False):
            line += " [refuted]"
        return [line]
    verb = {
        "verify": "verified",
        "doubt": "doubted",
        "undoubt": "undoubted",
        "refute": "refuted",
        "unrefute": "un-refuted",
    }[kind]
    line = f"    {record.id} {kind}{_writer(record)} — {verb}: {what}"
    if not activity.get(record.id, False):
        line += " [inactive]"
    return [line]


def _render(
    base_dir: Path,
    records: list[EventRecord],
    by_id: dict[str, EventRecord],
    activity: dict[str, bool],
    fold,
    status,
    fingerprints: dict,
    relations: dict[str, str | None],
    ordering: str | None,
) -> str:
    flags = ", ".join(
        name
        for name, value in (
            ("suspect", status.suspect),
            ("doubted", status.doubted),
            ("pending", status.pending),
            ("unknown", status.unknown),
            ("unanchored", status.unanchored),
        )
        if value
    )
    lines = [f"lineage {fold.lineage}"]
    lines.append(f"  status: {status.resolution} {status.verification} flags: {flags or '-'}")
    # off-version is its own labeled field, never folded into the flags list
    # (the flag is a context statement — the knowledge lives on another
    # version line — not a drift signal).
    lines.append(f"  off-version: {'yes' if status.off_version else 'no'}")
    if ordering is not None:
        lines.append(f"  context: {ordering}")
    lines.append(f"  displayed version: {fold.displayed or 'none'}")
    effective = by_id.get(fold.displayed) if fold.displayed else None
    if effective is not None:
        data = _frontmatter(base_dir, effective)
        lines.append(f"  summary: {effective.summary or ''}")
        statement_lines = (data.get("statement") or "").splitlines() or [""]
        lines.append(f"  statement: {statement_lines[0]}")
        lines.extend(f"    {rest}" for rest in statement_lines[1:])
        questions = effective.questions
        if questions:
            lines.append("  questions:")
            lines.extend(f"    - {question}" for question in questions)
        # The keywords nudge is an explain-only backfill hint (owner decision):
        # a claim whose effective version carries no keywords — the field is
        # optional — sees the one factual line; claims with keywords and
        # non-claim fields render nothing.
        if effective.kind == "claim" and not effective.keywords:
            lines.append(
                "  keywords: none (optional — add alternate vocabulary via a new"
                " claim version if this claim would benefit from it)"
            )
    lines.extend(_anchor_lines(base_dir, fold.displayed, by_id, fingerprints))
    lines.append(f"  events ({len(records)}, oldest first):")
    for record in records:
        lines.extend(_event_lines(record, by_id, activity, relations))
    if fold.verification_id is not None:
        evidence = _frontmatter(base_dir, by_id[fold.verification_id]).get("evidence") or []
        evidence = [item for item in evidence if isinstance(item, str)]
        if evidence:
            lines.append(f"  active verify evidence ({fold.verification_id}):")
            lines.extend(f"    - {item}" for item in evidence)
    return "\n".join(lines)
