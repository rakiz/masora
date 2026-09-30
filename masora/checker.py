"""Whole-tree validation for `masora check` (FORMAT.md §7, standalone mode)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .diagnostics import (
    E_ANCHOR,
    E_CYCLE,
    E_DUP_ID,
    E_FILENAME,
    E_LINEAGE,
    E_TARGET_KIND,
    E_TOMBSTONE_SHAPE,
    E_TOMBSTONED,
    E_ULID,
    E_YAML,
    W_DANGLING,
    W_FOUNDER,
    W_REPLAY,
    W_SKEW,
    Diag,
)
from .fold import Event, apply_precedence, fold_lineage, resolve_activity
from .frontmatter import load_frontmatter
from .schema import KINDS, EventRecord, validate_event
from .ulid import validate_ulid

FILENAME_RE = re.compile(
    r"^(?P<ulid>[0-9A-Z]+)\.(?P<kind>claim|verify|doubt|undoubt|refute|unrefute)\.md$"
)
ALLOWED_TARGET_KINDS = {
    "verify": frozenset({"claim"}),
    "doubt": frozenset({"verify"}),
    "undoubt": frozenset({"doubt"}),
    "refute": frozenset(KINDS),
    "unrefute": frozenset({"refute"}),
}


@dataclass
class CheckResult:
    diags: list[Diag]
    envelopes: list[dict]
    file_count: int
    lineage_count: int

    @property
    def errors(self) -> list[Diag]:
        return [d for d in self.diags if d.severity == "error"]

    @property
    def warnings(self) -> list[Diag]:
        return [d for d in self.diags if d.severity == "warning"]

    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.warnings:
            return 2
        return 0


def check_base(base_dir: Path) -> CheckResult:
    diags: list[Diag] = []
    records: list[EventRecord] = []
    files = discover_event_files(base_dir)
    seen_ids: dict[str, str] = {}
    for path in files:
        rel = str(path.relative_to(base_dir))
        record = _parse_event_file(path, rel, diags)
        if record is None:
            continue
        if record.id in seen_ids:
            diags.append(
                Diag(
                    "error",
                    E_DUP_ID,
                    f"event id {record.id} already defined by {seen_ids[record.id]}",
                    rel,
                )
            )
            continue
        seen_ids[record.id] = rel
        records.append(record)

    tombstoned, event_tombstoned = _load_tombstone_tables(base_dir / "deleted.toml", diags)
    for record in records:
        if record.id in tombstoned or record.lineage in tombstoned or record.id in event_tombstoned:
            diags.append(
                Diag(
                    "error",
                    E_TOMBSTONED,
                    f"event id or lineage appears in deleted.toml: {record.id}",
                    record.path,
                )
            )

    valid = [
        r
        for r in records
        if r.id not in tombstoned and r.lineage not in tombstoned and r.id not in event_tombstoned
    ]
    by_id = {r.id: r for r in valid}

    for record in valid:
        _check_references(record, by_id, diags)
    _check_cycles(valid, diags)

    structural_count = sum(1 for r in valid if r.kind == "claim" and r.claim_class == "structural")
    if structural_count:
        diags.append(
            Diag(
                "warning",
                W_REPLAY,
                f"proof replay not wired in standalone check: {structural_count} structural claim(s) not replayed, outcome unknown",
            )
        )

    envelopes: list[dict] = []
    if not any(d.code == E_CYCLE for d in diags):
        activity = resolve_activity([_to_fold_event(r) for r in valid])
        lineages = sorted({r.lineage for r in valid})
        for lineage in lineages:
            lineage_events = [_to_fold_event(r) for r in valid if r.lineage == lineage]
            versions = sorted(
                (r for r in valid if r.kind == "claim" and r.lineage == lineage),
                key=lambda r: r.id,
                reverse=True,
            )
            eligible = [r.id for r in versions if r.id == lineage or _has_founder(r, by_id)]
            for r in versions:
                if r.id not in eligible:
                    diags.append(
                        Diag(
                            "warning",
                            W_FOUNDER,
                            f"version {r.id} has no founding claim (id == lineage {lineage}); excluded from resolution",
                            r.path,
                        )
                    )
            fold = fold_lineage(
                lineage, lineage_events, activity, eligible, provider_available=False
            )
            envelopes.append(_envelope(fold, versions))
    diags.sort(key=lambda d: (d.severity != "error", d.code, d.path or "", d.message))
    return CheckResult(
        diags=diags,
        envelopes=envelopes,
        file_count=len(files),
        lineage_count=len({r.lineage for r in valid}),
    )


def discover_event_files(base_dir: Path) -> list[Path]:
    return sorted(p for p in base_dir.rglob("*.md") if ".git" not in p.parts)


def _parse_event_file(path: Path, rel: str, diags: list[Diag]) -> EventRecord | None:
    match = FILENAME_RE.match(path.name)
    if not match:
        diags.append(
            Diag(
                "error",
                E_FILENAME,
                f"filename does not parse as <ULID>.<kind>.md with kind in {sorted(KINDS)}",
                rel,
            )
        )
        return None
    try:
        filename_ulid = validate_ulid(match.group("ulid"), what="filename ULID")
    except ValueError as exc:
        diags.append(Diag("error", E_ULID, str(exc), rel))
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        diags.append(Diag("error", E_YAML, f"file is not valid UTF-8: {exc}", rel))
        return None
    try:
        data = load_frontmatter(text, rel)
        record = validate_event(data, match.group("kind"), rel)
    except Exception as exc:
        if hasattr(exc, "diag"):
            diags.append(exc.diag)
            return None
        raise
    if record.id != filename_ulid:
        diags.append(
            Diag(
                "error",
                E_FILENAME,
                f"frontmatter id {record.id} does not equal filename ULID {filename_ulid}",
                rel,
            )
        )
        return None
    return record


def _load_tombstone_tables(path: Path, diags: list[Diag]) -> tuple[set[str], set[str]]:
    """Parse deleted.toml (FORMAT.md §7.10): `[[deleted]]` blocks tombstone a
    whole lineage (its lineage ULID and every event ULID), `[[deleted_events]]`
    blocks tombstone individual event ids while the lineage lives on."""
    dead: set[str] = set()
    dead_events: set[str] = set()
    if not path.exists():
        return dead, dead_events
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        diags.append(
            Diag("error", E_TOMBSTONE_SHAPE, f"deleted.toml is not valid TOML: {exc}", path.name)
        )
        return dead, dead_events
    if set(data) - {"deleted", "deleted_events"}:
        diags.append(
            Diag(
                "error",
                E_TOMBSTONE_SHAPE,
                f"deleted.toml has unknown top-level fields {sorted(set(data) - {'deleted', 'deleted_events'})}",
                path.name,
            )
        )
        return dead, dead_events
    tables: list[tuple[str, set[str], bool]] = []
    for name, whole in (("deleted", True), ("deleted_events", False)):
        blocks = data.get(name, [])
        if not isinstance(blocks, list) or any(not isinstance(block, dict) for block in blocks):
            diags.append(
                Diag(
                    "error",
                    E_TOMBSTONE_SHAPE,
                    f"deleted.toml {name} must be a list of [[{name}]] tables",
                    path.name,
                )
            )
            return dead, dead_events
        tables.append((name, dead if whole else dead_events, whole))
    for name, target, whole in tables:
        blocks = data.get(name, [])
        for i, block in enumerate(blocks):
            if set(block) != {"lineage", "ulids"}:
                diags.append(
                    Diag(
                        "error",
                        E_TOMBSTONE_SHAPE,
                        f"deleted.toml {name} block {i} must have exactly {{lineage, ulids}}",
                        path.name,
                    )
                )
                return dead, dead_events
            ulids = block["ulids"]
            if not isinstance(ulids, list):
                diags.append(
                    Diag(
                        "error",
                        E_TOMBSTONE_SHAPE,
                        f"deleted.toml {name} block {i} ulids must be a list of strings",
                        path.name,
                    )
                )
                return dead, dead_events
            try:
                lineage = validate_ulid(
                    block["lineage"], what=f"deleted.toml {name} block {i} lineage"
                )
                validated = [
                    validate_ulid(ulid, what=f"deleted.toml {name} block {i} ulid")
                    for ulid in ulids
                ]
            except (ValueError, TypeError) as exc:
                diags.append(Diag("error", E_TOMBSTONE_SHAPE, str(exc), path.name))
                return dead, dead_events
            if whole:
                dead.add(lineage)
            target.update(validated)
    return dead, dead_events


def _check_references(
    record: EventRecord, by_id: dict[str, EventRecord], diags: list[Diag]
) -> None:
    if record.targets is not None:
        target = by_id.get(record.targets)
        if target is None:
            diags.append(
                Diag(
                    "warning",
                    W_DANGLING,
                    f"targets ULID {record.targets} does not resolve to a valid event",
                    record.path,
                )
            )
        else:
            if target.kind not in ALLOWED_TARGET_KINDS[record.kind]:
                diags.append(
                    Diag(
                        "error",
                        E_TARGET_KIND,
                        f"{record.kind} must target {sorted(ALLOWED_TARGET_KINDS[record.kind])}, got {target.kind}",
                        record.path,
                    )
                )
            if target.lineage != record.lineage:
                diags.append(
                    Diag(
                        "error",
                        E_LINEAGE,
                        f"lineage mismatch: targets {target.id} in lineage {target.lineage}, event in lineage {record.lineage}",
                        record.path,
                    )
                )
            if (
                record.kind == "verify"
                and target.kind == "claim"
                and set(record.snapshot_keys) != set(target.anchor_identities)
            ):
                diags.append(
                    Diag(
                        "error",
                        E_ANCHOR,
                        f"snapshots keys must equal the target's anchor-identity set: expected {sorted(target.anchor_identities)}, got {sorted(record.snapshot_keys)}",
                        record.path,
                    )
                )
        if record.targets > record.id:
            diags.append(
                Diag(
                    "warning",
                    W_SKEW,
                    f"targets ULID {record.targets} is lexically greater than event id {record.id} (clock skew tolerated)",
                    record.path,
                )
            )
    if record.contradicts is not None:
        target = by_id.get(record.contradicts)
        if target is None:
            diags.append(
                Diag(
                    "warning",
                    W_DANGLING,
                    f"contradicts ULID {record.contradicts} does not resolve to a valid event",
                    record.path,
                )
            )
        else:
            if target.kind != "claim":
                diags.append(
                    Diag(
                        "error",
                        E_TARGET_KIND,
                        f"contradicts must resolve to a claim version, got {target.kind}",
                        record.path,
                    )
                )
            if target.lineage != record.lineage:
                diags.append(
                    Diag(
                        "error",
                        E_LINEAGE,
                        f"contradicts must resolve to a claim version in the same lineage {record.lineage}, got {target.lineage}",
                        record.path,
                    )
                )


def _check_cycles(records: list[EventRecord], diags: list[Diag]) -> None:
    by_id = {r.id: r for r in records}
    edges = {r.id: r.targets for r in records if r.targets is not None and r.targets in by_id}
    indegree = {r.id: 0 for r in records}
    for target in edges.values():
        indegree[target] += 1
    queue = sorted(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        target = edges.get(node)
        if target is not None:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
                queue.sort(reverse=True)
    if visited != len(records):
        remaining = sorted(node for node, degree in indegree.items() if degree > 0)
        cycle_path = _trace_cycle(remaining, edges)
        diags.append(
            Diag(
                "error",
                E_CYCLE,
                f"reference graph contains a cycle: {' -> '.join(cycle_path)}",
                by_id[cycle_path[0]].path,
            )
        )


def _trace_cycle(remaining: list[str], edges: dict[str, str]) -> list[str]:
    start = remaining[0]
    path = [start]
    seen = {start}
    node = edges[start]
    while node not in seen:
        path.append(node)
        seen.add(node)
        node = edges[node]
    return path[path.index(node) :] + [node]


def _has_founder(record: EventRecord, by_id: dict[str, EventRecord]) -> bool:
    founder = by_id.get(record.lineage)
    return founder is not None and founder.kind == "claim"


def _to_fold_event(record: EventRecord) -> Event:
    return Event(
        id=record.id,
        kind=record.kind,
        lineage=record.lineage,
        targets=record.targets,
        source=record.source,
        verified_at={
            "commit": record.timestamp_commit,
            "graph_commit": record.timestamp_graph_commit,
        }
        if record.kind == "verify"
        else None,
        recorded_at={
            "commit": record.timestamp_commit,
            "graph_commit": record.timestamp_graph_commit,
        }
        if record.kind != "verify"
        else None,
    )


def _envelope(fold, versions: list[EventRecord]) -> dict:
    version_states = [{"id": r.id, "refuted": r.id in fold.refuted_versions} for r in versions]
    displayed_record = next((r for r in versions if r.id == fold.displayed), None)
    return {
        "lineage": fold.lineage,
        "displayed": fold.displayed,
        "status": apply_precedence(fold.resolution, unknown=True),
        "restored": fold.restored,
        "versions": version_states,
        "verification": {
            "status": fold.verification_status,
            "source": fold.verification_source,
            "id": fold.verification_id,
            "verified_at": fold.verification_time,
        },
        "sources": list(fold.sources),
        "doubted": fold.doubted,
        "recorded_at": {
            "commit": displayed_record.timestamp_commit,
            "graph_commit": displayed_record.timestamp_graph_commit,
        }
        if displayed_record
        else None,
        "proof_replay": "unknown" if any(r.claim_class == "structural" for r in versions) else None,
    }
