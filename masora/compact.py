"""`masora compact`: per-lineage compression to the minimal live witness set
(FORMAT.md §6, §7.10, MASORA_DESIGN.md §6.2) plus `--rehome` layout migration
(FORMAT.md §1).

Every lineage is reduced to the event files still contributing to its current
§6 fold state; surviving files keep their ULIDs and bytes. The plan carries a
per-lineage proof — the witness fold must equal the full fold — and any
diverging lineage refuses the whole run fail-closed (`E-COMPACT-DIVERGE`).
Dropped events known to the shared repo (present on `origin/main` or the sync
merge-base) are tombstoned per-event in the `[[deleted_events]]` table of
`deleted.toml`; unpublished events are dropped silently. `--rehome` moves the
surviving files of every lineage into its canonical single home
`YYYY-MM/<slug>-<lineage>` (the founder's month) and merges split month
buckets, renaming directories only — nothing is deleted by rehoming.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .checker import (
    FILENAME_RE,
    CheckResult,
    _parse_event_file,
    check_base,
    discover_event_files,
)
from .diagnostics import E_COMPACT_CHECK, E_COMPACT_DIVERGE, Diag
from .fold import Event, LineageFold, fold_lineage, resolve_activity
from .gc import _prune_empty_dirs
from .schema import EventRecord
from .sync import _optional_rev, _render_deleted_events, git_env
from .ulid import is_ulid
from .write import slugify_summary

PLAN_EXIT = 3
ACTIVITY_KINDS = frozenset({"refute", "unrefute", "undoubt"})


@dataclass
class LineagePlan:
    lineage: str
    kept: list[EventRecord]
    dropped: list[EventRecord]
    dropped_unpublished: int
    warnings: list[Diag] = field(default_factory=list)


@dataclass
class RehomePlan:
    lineage: str
    target: str
    moves: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class CompactPlan:
    lineages: list[LineagePlan]
    tombstone_pairs: set[tuple[str, str]]
    files_before: int
    files_after: int
    diverged: list[Diag]
    warnings: list[Diag]
    rehomes: list[RehomePlan] = field(default_factory=list)


def run(base_dir: Path, yes: bool = False, rehome: bool = False) -> int:
    print(f"masora compact {base_dir}" + (" --rehome" if rehome else ""))
    if not base_dir.is_dir():
        print(f"masora compact: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1

    pre = check_base(base_dir)
    print(f"pre-check: scanned {pre.file_count} event file(s), {pre.lineage_count} lineage(s)")
    for diag in pre.diags:
        print(f"  {diag.render()}")
    if pre.errors:
        print(f"FAILED: {len(pre.errors)} error(s) (pre-check) — compact blocked")
        return 1

    plan = _build_plan(base_dir, _known_ids(base_dir), rehome)

    _print_plan(plan, rehome)
    for diag in plan.diverged:
        print(f"  {diag.render()}")
    if plan.diverged:
        print(f"FAILED: {len(plan.diverged)} error(s) — nothing written")
        return 1
    drops = sum(len(item.dropped) for item in plan.lineages)
    moves = sum(len(names) for item in plan.rehomes for _src, names in item.moves)
    if not drops and not moves:
        if rehome:
            print(
                "nothing to rehome: every lineage is at its minimal witness set "
                "in its canonical home"
            )
        else:
            print("nothing to compact: every lineage is already at its minimal witness set")
        return 0
    if not yes:
        print("plan only: nothing written — re-run with --yes to compact")
        return PLAN_EXIT

    if plan.tombstone_pairs:
        _append_deleted_events(base_dir, plan.tombstone_pairs)
    removed = 0
    compacted = 0
    for item in plan.lineages:
        if not item.dropped:
            continue
        compacted += 1
        for record in item.dropped:
            path = base_dir / record.path
            path.unlink()
            removed += 1
            _prune_empty_dirs(base_dir, path.parent)
    moved = _execute_rehome(base_dir, plan.rehomes) if rehome else 0

    post = check_base(base_dir)
    print(f"post-check: scanned {post.file_count} event file(s), {post.lineage_count} lineage(s)")
    for diag in post.diags:
        print(f"  {diag.render()}")
    tree_diverged = _tree_divergence(pre, post)
    for diag in tree_diverged:
        print(f"  {diag.render()}")
    if post.errors or tree_diverged:
        why = (
            "the tree failed masora check after compaction"
            if post.errors
            else "a lineage status changed after compaction"
        )
        code = E_COMPACT_CHECK if post.errors else E_COMPACT_DIVERGE
        print(f"  {Diag('error', code, f'{why} — restore with git restore').render()}")
        print("FAILED: 1 error(s) (post-check)")
        return 1
    warnings = len(plan.warnings) + len(post.warnings)
    if drops:
        print(
            f"compacted: {removed} event file(s) removed across {compacted} lineage(s), "
            f"{len(plan.tombstone_pairs)} tombstoned, {moved} file(s) moved, "
            f"{plan.files_before} -> {plan.files_after} files"
        )
    else:
        print(f"rehomed: {moved} event file(s) moved into canonical home(s)")
    if warnings:
        print(f"compacted with warnings: {warnings} warning(s)")
        return 2
    return 0


def select_witness(
    lineage: str, events: list[Event], eligible: list[str], activity: dict[str, bool]
) -> set[str]:
    """The minimal live witness set of one lineage (FORMAT.md §6, MASORA_DESIGN.md §6.2).

    Returns the event ids whose files still contribute to the lineage's
    current fold state: the founding claim (every eligible version's
    resolution hangs on it), the effective version — the newest active
    eligible version, the newest eligible version when every version is
    refuted (`resolution: none`), the newest existing version when the
    lineage is founderless —, every active verify of the effective version
    (their sources feed the envelope; with no displayed version the fold
    counts active verifies with no target, kept as well), every active doubt
    on a kept verify, every active refute of a version when `resolution:
    none`, and the newest version (whose active refutations sustain
    `restored`) when restored. The
    set is closed over `targets`/`contradicts` (a kept event's references
    must resolve) and over the active refute/unrefute/undoubt events
    targeting kept events (a kept event's activity must not flip). Everything
    else is pure history.
    """
    claim_ids = {e.id for e in events if e.kind == "claim"}
    versions = sorted(claim_ids, reverse=True)
    eligible_desc = sorted(set(eligible), reverse=True)
    active_versions = [v for v in eligible_desc if activity.get(v, False)]
    refuted_versions = [v for v in eligible_desc if not activity.get(v, False)]
    displayed = active_versions[0] if active_versions else None
    restored = displayed is not None and any(v > displayed for v in refuted_versions)
    founder = next((e.id for e in events if e.kind == "claim" and e.id == lineage), None)
    kept: set[str] = set()
    effective: str | None = None
    if eligible_desc:
        if founder is not None:
            kept.add(founder)
        if not active_versions:
            for e in events:
                if e.kind == "refute" and activity[e.id] and e.targets in claim_ids:
                    kept.add(e.id)
        else:
            effective = displayed
            kept.add(displayed)
            for e in events:
                if e.kind == "verify" and e.targets == displayed and activity[e.id]:
                    kept.add(e.id)
            if restored:
                kept.add(versions[0])
    elif versions:
        kept.add(versions[0])
    for e in events:
        if e.kind == "verify" and e.targets == effective and activity[e.id]:
            kept.add(e.id)
    changed = True
    while changed:
        changed = False
        referenced = set()
        for e in events:
            if e.id in kept:
                if e.targets is not None:
                    referenced.add(e.targets)
                if e.contradicts is not None:
                    referenced.add(e.contradicts)
        for e in events:
            if e.id in kept:
                continue
            if (
                e.id in referenced
                or (e.kind in ACTIVITY_KINDS and e.targets in kept and activity[e.id])
                or (e.kind == "doubt" and e.targets in kept and activity[e.id])
            ):
                kept.add(e.id)
                changed = True
    return kept


def observable_state(fold: LineageFold, activity: dict[str, bool], versions: list[str]) -> tuple:
    """The fold-derived state a compaction must preserve (MASORA_DESIGN.md §6.2)."""
    return (
        fold.displayed,
        fold.restored,
        fold.resolution,
        fold.verification_status,
        fold.verification_id,
        fold.verification_source,
        fold.verification_time,
        fold.verification_snapshots,
        fold.sources,
        fold.doubted,
        tuple(sorted((v, activity.get(v, False)) for v in versions)),
    )


def _build_plan(base_dir: Path, known: set[str] | None, rehome: bool = False) -> CompactPlan:
    records: list[EventRecord] = []
    for path in discover_event_files(base_dir):
        rel = str(path.relative_to(base_dir))
        record = _parse_event_file(path, rel, [])
        if record is not None:
            records.append(record)
    by_lineage: dict[str, list[EventRecord]] = {}
    for record in records:
        by_lineage.setdefault(record.lineage, []).append(record)
    plans: list[LineagePlan] = []
    diverged: list[Diag] = []
    warnings: list[Diag] = []
    tombstone_pairs: set[tuple[str, str]] = set()
    rehomes: list[RehomePlan] = []
    for lineage in sorted(by_lineage):
        item, diverge = _plan_lineage(lineage, by_lineage[lineage], known)
        plans.append(item)
        diverged.extend(diverge)
        warnings.extend(item.warnings)
        for record in item.dropped:
            if known is not None and record.id in known:
                tombstone_pairs.add((lineage, record.id))
        if rehome:
            rehome_plan = _rehome_plan(item.lineage, item.kept)
            if rehome_plan is not None:
                rehomes.append(rehome_plan)
    files_before = len(records)
    files_after = files_before - sum(len(item.dropped) for item in plans)
    return CompactPlan(
        lineages=plans,
        tombstone_pairs=tombstone_pairs,
        files_before=files_before,
        files_after=files_after,
        diverged=diverged,
        warnings=warnings,
        rehomes=rehomes,
    )


def _plan_lineage(
    lineage: str, records: list[EventRecord], known: set[str] | None
) -> tuple[LineagePlan, list[Diag]]:
    events = [_to_event(record) for record in records]
    by_id = {record.id: record for record in records}
    claims = sorted((record for record in records if record.kind == "claim"), key=lambda r: r.id)
    founder = by_id.get(lineage)
    has_founder = founder is not None and founder.kind == "claim"
    eligible = [record.id for record in claims if record.id == lineage or has_founder]
    activity = resolve_activity(events)
    fold_full = fold_lineage(lineage, events, activity, eligible)
    kept = select_witness(lineage, events, eligible, activity)
    witness = [e for e in events if e.id in kept]
    wit_activity = resolve_activity(witness)
    wit_eligible = [v for v in eligible if v in kept]
    fold_wit = fold_lineage(lineage, witness, wit_activity, wit_eligible)
    kept_versions = [v for v in eligible if v in kept]
    diverged = []
    if observable_state(fold_full, activity, kept_versions) != observable_state(
        fold_wit, wit_activity, kept_versions
    ):
        diverged.append(
            Diag(
                "error",
                E_COMPACT_DIVERGE,
                f"lineage {lineage}: the witness fold would diverge from the full fold "
                "— compaction is refused (fail-closed), nothing written",
            )
        )
    kept_records = sorted((record for record in records if record.id in kept), key=lambda r: r.id)
    dropped_records = sorted(
        (record for record in records if record.id not in kept), key=lambda r: r.id
    )
    unpublished = sum(1 for record in dropped_records if known is None or record.id not in known)
    return (
        LineagePlan(
            lineage=lineage,
            kept=kept_records,
            dropped=dropped_records,
            dropped_unpublished=unpublished,
        ),
        diverged,
    )


def _rehome_plan(lineage: str, survivors: list[EventRecord]) -> RehomePlan | None:
    """The canonical-home migration of one lineage's surviving files (FORMAT.md §1).

    The canonical home sits where the founder file lives, renamed
    `<slug>-<lineage>` when the directory is the bare `<lineage>` form (the
    slug is the founder summary's deterministic form, skipped when it yields
    nothing); a directory that already carries a slug keeps it verbatim. Every
    surviving file outside that home moves into it. A founderless lineage has
    no canonical home to derive — it is left untouched.
    """
    founder = next(
        (record for record in survivors if record.kind == "claim" and record.id == lineage),
        None,
    )
    if founder is None:
        return None
    home = Path(founder.path).parent
    slug = slugify_summary(founder.summary or "")
    name = f"{slug}-{lineage}" if home.name == lineage and slug else home.name
    target = home.with_name(name)
    by_dir: dict[str, list[str]] = {}
    for record in survivors:
        parent = Path(record.path).parent
        if parent == target:
            continue
        by_dir.setdefault(parent.as_posix(), []).append(Path(record.path).name)
    if not by_dir:
        return None
    return RehomePlan(
        lineage=lineage,
        target=target.as_posix(),
        moves=sorted(by_dir.items()),
    )


def _execute_rehome(base_dir: Path, rehomes: list[RehomePlan]) -> int:
    moved = 0
    for item in rehomes:
        target = base_dir / item.target
        target.mkdir(parents=True, exist_ok=True)
        for src, names in item.moves:
            source = base_dir / src
            for name in names:
                (source / name).rename(target / name)
                moved += 1
            _prune_empty_dirs(base_dir, source)
    return moved


def _to_event(record: EventRecord) -> Event:
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


def _known_ids(base_dir: Path) -> set[str] | None:
    """Event ULIDs the shared repo knows: present on `origin/main` plus, when
    it resolves, the sync merge-base; None when no `origin/main` resolves — no
    tombstones at all (no fetch: the remote-tracking ref is as of the last one)."""
    origin_main = _optional_rev(base_dir, "refs/remotes/origin/main")
    if origin_main is None:
        return None
    known = _tree_ulids(base_dir, origin_main)
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "merge-base", "HEAD", origin_main],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    if proc.returncode == 0:
        known |= _tree_ulids(base_dir, proc.stdout.strip())
    return known


def _tree_ulids(base_dir: Path, commit: str) -> set[str]:
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "ls-tree", "-r", "--name-only", commit],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    ids: set[str] = set()
    if proc.returncode != 0:
        return ids
    for name in proc.stdout.splitlines():
        match = FILENAME_RE.match(name.rsplit("/", 1)[-1])
        if match and is_ulid(match.group("ulid")):
            ids.add(match.group("ulid"))
    return ids


def _append_deleted_events(base_dir: Path, pairs: set[tuple[str, str]]) -> None:
    path = base_dir / "deleted.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    text += _render_deleted_events(pairs)
    path.write_text(text, encoding="utf-8")


def _print_plan(plan: CompactPlan, rehome: bool = False) -> None:
    for item in plan.lineages:
        if not item.dropped:
            continue
        print(
            f"lineage {item.lineage}: keep {len(item.kept)} of "
            f"{len(item.kept) + len(item.dropped)} "
            f"event file(s), drop {len(item.dropped)} ({item.dropped_unpublished} unpublished)"
        )
        for record in item.dropped:
            print(f"  drop {record.path} ({record.kind})")
    if rehome:
        for item in plan.rehomes:
            print(f"lineage {item.lineage}: home {item.target}")
            for src, names in item.moves:
                print(f"  move {len(names)} file(s): {src} -> {item.target}")
    if plan.tombstone_pairs:
        print(
            f"tombstone: append {len(plan.tombstone_pairs)} deleted_events ulid(s) to deleted.toml"
        )
    print(f"total: {plan.files_before} file(s) before, {plan.files_after} after")


def _tree_divergence(pre: CheckResult, post: CheckResult) -> list[Diag]:
    before = {env["lineage"]: _status_tuple(env) for env in pre.envelopes}
    diverged = []
    for env in post.envelopes:
        lineage = env["lineage"]
        if lineage in before and _status_tuple(env) != before[lineage]:
            diverged.append(
                Diag(
                    "error",
                    E_COMPACT_DIVERGE,
                    f"lineage {lineage}: status changed after compaction",
                )
            )
    return diverged


def _status_tuple(envelope: dict) -> tuple:
    verification = envelope["verification"]
    return (
        envelope["status"],
        envelope["displayed"],
        envelope["restored"],
        envelope["doubted"],
        verification["status"],
        verification["id"],
        verification["source"],
        verification["verified_at"],
        tuple(envelope["sources"]),
    )
