"""`masora explain`: the complete story of ONE lineage, statuses included.

The rollout lesson: an agent wanting one lineage's full story improvised an
rg over the base's directories and read RAW event files — which carry NO
status, so a refuted/doubted claim looked valid. This is the canonical door:
the state is computed FRESH from the lineage's event files (never the index —
a stale index cannot lie here), and the render shows the status tuple, the
effective version's content and the full event chain with the active
verify's evidence.
"""

from __future__ import annotations

from pathlib import Path

from .checker import _parse_event_file, check_base, discover_event_files
from .diagnostics import E_EXPLAIN_UNKNOWN, Diag
from .fold import Event, fold_lineage, resolve_activity
from .frontmatter import load_frontmatter
from .index import file_fingerprint_provider
from .providers import cppgraph_registry
from .resolve import AnchorData, VersionData, _matcher, resolve_lineage
from .schema import EventRecord


class ExplainError(Exception):
    def __init__(self, *diags: Diag):
        super().__init__(diags[0].message if diags else "explain refused")
        self.diags = list(diags)


def explain_lineage(base_dir: Path, lineage_id: str, repo: Path | None = None) -> str:
    """The readable story of one lineage: the status tuple, the effective
    version's content, the anchors' current match state, the full event chain
    in ULID order and the active verify's evidence in full. Raises
    ExplainError (E-NOT-A-BASE, other base errors, E-EXPLAIN-UNKNOWN);
    nothing is ever written."""
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
    fingerprints, edge_snapshots = _registries(repo)
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
    status = resolve_lineage(
        lineage_id, version_data, fold_events, fingerprints, edge_snapshots=edge_snapshots
    )
    activity = resolve_activity(fold_events)
    fold = fold_lineage(
        lineage_id,
        fold_events,
        activity,
        eligible,
        fingerprint_matcher=_matcher({v.id: v for v in version_data}, fingerprints),
        provider_available=not status.unknown,
    )
    return _render(base_dir, records, by_id, activity, fold, status, fingerprints)


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


def _registries(repo: Path | None) -> tuple[dict, dict]:
    if repo is None:
        return {}, {}
    registry = cppgraph_registry(repo)
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
    fold,
) -> list[str]:
    kind = record.kind
    what = _claim_summary(record, by_id)
    if kind == "claim":
        label = "founder" if record.id == record.lineage else "v2+"
        line = f"    {record.id} claim{_writer(record)} — {label}: {record.summary or ''}"
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
    lines.extend(_anchor_lines(base_dir, fold.displayed, by_id, fingerprints))
    lines.append(f"  events ({len(records)}, oldest first):")
    for record in records:
        lines.extend(_event_lines(record, by_id, activity, fold))
    if fold.verification_id is not None:
        evidence = _frontmatter(base_dir, by_id[fold.verification_id]).get("evidence") or []
        evidence = [item for item in evidence if isinstance(item, str)]
        if evidence:
            lines.append(f"  active verify evidence ({fold.verification_id}):")
            lines.extend(f"    - {item}" for item in evidence)
    return "\n".join(lines)
