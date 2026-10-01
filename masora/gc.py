"""`masora gc`: whole-lineage deletion with tombstones for published lineages
(FORMAT.md §1, §7.9-§7.10, SPEC.md Goals).

A lineage origin/main never saw (never published) is removed locally without
tombstone rows: the shared ledger records only what the shared repo knew.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .checker import CheckResult, check_base
from .diagnostics import (
    E_GC_CHECK,
    E_GC_ULID,
    E_GC_UNKNOWN,
    E_GIT,
    W_GC_ACTIVE,
    Diag,
)
from .sync import (
    MAIN_BRANCH,
    REMOTE,
    EventFile,
    SyncError,
    _render_tombstone,
    _scan_events,
    _tombstone_pairs,
    git_env,
)
from .ulid import is_ulid

PLAN_EXIT = 3


class GcError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


@dataclass
class LineagePlan:
    lineage: str
    events: list[EventFile]
    published: bool
    warnings: list[Diag] = field(default_factory=list)


@dataclass
class GcPlan:
    lineages: list[LineagePlan]
    already_deleted: list[str]
    pairs: set[tuple[str, str]]
    warnings: list[Diag]


def run(base_dir: Path, lineages: list[str], yes: bool = False) -> int:
    print(f"masora gc {base_dir}")
    if not base_dir.is_dir():
        print(f"masora gc: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    invalid = [value for value in lineages if not is_ulid(value)]
    if invalid:
        for value in invalid:
            diag = Diag(
                "error", E_GC_ULID, f"--lineage {value!r} is not a well-formed ULID (FORMAT.md §3)"
            )
            print(f"  {diag.render()}")
        print(f"FAILED: {len(invalid)} error(s)")
        return 1
    requested = _dedupe(lineages)

    pre = check_base(base_dir)
    print(f"pre-check: scanned {pre.file_count} event file(s), {pre.lineage_count} lineage(s)")
    for diag in pre.diags:
        print(f"  {diag.render()}")
    if pre.errors:
        print(f"FAILED: {len(pre.errors)} error(s) (pre-check) — gc blocked")
        return 1

    try:
        plan = _build_plan(base_dir, requested, pre)
    except GcError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1

    _print_plan(plan)
    if not plan.lineages:
        print("nothing to collect: every requested lineage is already tombstoned")
        return 0
    if not yes:
        print("plan only: nothing written — re-run with --yes to delete")
        return PLAN_EXIT

    # Only published lineages reach the ledger: an unpublished-only run
    # creates no deleted.toml at all.
    if plan.pairs:
        _append_tombstone(base_dir, plan.pairs)
    removed = 0
    for item in plan.lineages:
        for event in item.events:
            path = base_dir / event.path
            path.unlink()
            removed += 1
            _prune_empty_dirs(base_dir, path.parent)

    post = check_base(base_dir)
    print(f"post-check: scanned {post.file_count} event file(s), {post.lineage_count} lineage(s)")
    for diag in post.diags:
        print(f"  {diag.render()}")
    if post.errors:
        diag = Diag(
            "error",
            E_GC_CHECK,
            "the tree failed masora check after the deletion — restore with git restore",
        )
        print(f"  {diag.render()}")
        print(f"FAILED: {len(post.errors) + 1} error(s) (post-check)")
        return 1
    warnings = len(plan.warnings) + len(post.warnings)
    summary = f"collected: {len(plan.lineages)} lineage(s), {removed} event file(s) removed"
    unpublished = sum(1 for item in plan.lineages if not item.published)
    if unpublished:
        summary += f", {unpublished} unpublished (no tombstone)"
    print(summary)
    if warnings:
        print(f"collected with warnings: {warnings} warning(s)")
        return 2
    return 0


def _dedupe(lineages: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in lineages:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _build_plan(base_dir: Path, requested: list[str], pre: CheckResult) -> GcPlan:
    try:
        pairs_local = _tombstone_pairs(
            (base_dir / "deleted.toml").read_bytes()
            if (base_dir / "deleted.toml").exists()
            else None,
            "local",
        )
    except SyncError as exc:
        raise GcError(exc.diag) from exc
    tombstoned = {lineage for lineage, _ulid in pairs_local}
    events = _scan_events(base_dir)
    by_lineage: dict[str, list[EventFile]] = {}
    for event in events.values():
        if event.lineage:
            by_lineage.setdefault(event.lineage, []).append(event)
    origin_paths = _origin_tree_paths(base_dir)
    statuses = {envelope["lineage"]: envelope for envelope in pre.envelopes}
    plans: list[LineagePlan] = []
    already: list[str] = []
    warnings: list[Diag] = []
    for lineage in requested:
        events_of = sorted(by_lineage.get(lineage, []), key=lambda event: event.id)
        if not events_of:
            if lineage in tombstoned:
                already.append(lineage)
                continue
            raise GcError(
                Diag(
                    "error",
                    E_GC_UNKNOWN,
                    f"lineage {lineage} has no events in the base — gc never suggests lineages, check the ULID",
                )
            )
        warnings_of: list[Diag] = []
        versions = statuses.get(lineage, {}).get("versions", [])
        if any(not version["refuted"] for version in versions):
            warnings_of.append(
                Diag(
                    "warning",
                    W_GC_ACTIVE,
                    f"lineage {lineage} still has active (non-refuted) versions — deleting it discards live knowledge; refutations are usually the right correction",
                )
            )
        published = origin_paths is not None and any(
            event.path in origin_paths for event in events_of
        )
        plans.append(
            LineagePlan(
                lineage=lineage, events=events_of, published=published, warnings=warnings_of
            )
        )
        warnings.extend(warnings_of)
    pairs = {(item.lineage, event.id) for item in plans if item.published for event in item.events}
    return GcPlan(lineages=plans, already_deleted=already, pairs=pairs, warnings=warnings)


def _origin_tree_paths(base_dir: Path) -> set[str] | None:
    """The file paths of origin/main's tree — the published-ness oracle: a
    lineage is published iff one of its event files is in there. One read-only
    ls-tree, no fetch (the remote-tracking ref is as of the last one). None
    when origin/main does not resolve — no origin remote or no main branch
    means nothing was ever published. A git failure raises: published-ness is
    never guessed silently."""
    rev = subprocess.run(
        [
            "git",
            "-C",
            str(base_dir),
            "rev-parse",
            "--verify",
            f"refs/remotes/{REMOTE}/{MAIN_BRANCH}",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    if rev.returncode != 0:
        return None
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "ls-tree", "-r", "--name-only", rev.stdout.strip()],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    if proc.returncode != 0:
        raise GcError(
            Diag(
                "error",
                E_GIT,
                f"git ls-tree {REMOTE}/{MAIN_BRANCH} failed: {proc.stderr.strip()} — "
                "published-ness cannot be determined, gc blocked",
            )
        )
    return set(proc.stdout.splitlines())


def _print_plan(plan: GcPlan) -> None:
    for item in plan.lineages:
        print(f"lineage {item.lineage}: {len(item.events)} event file(s)")
        if not item.published:
            print("  unpublished — removed locally, no tombstone (origin/main never saw it)")
        for event in item.events:
            print(f"  delete {event.path} ({event.kind or 'event'})")
        for diag in item.warnings:
            print(f"  {diag.render()}")
    for lineage in plan.already_deleted:
        print(f"lineage {lineage}: already tombstoned, nothing to do")
    published = sum(1 for item in plan.lineages if item.published)
    if published:
        print(f"tombstone: append {published} [[deleted]] block(s) to deleted.toml")


def _append_tombstone(base_dir: Path, pairs: set[tuple[str, str]]) -> None:
    path = base_dir / "deleted.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    text += _render_tombstone(pairs)
    path.write_text(text, encoding="utf-8")


def _prune_empty_dirs(base_dir: Path, directory: Path) -> None:
    while directory != base_dir and directory.is_dir():
        try:
            directory.rmdir()
        except OSError:
            break
        directory = directory.parent
