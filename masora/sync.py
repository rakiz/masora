"""`masora sync`: publication workflow (FORMAT.md §7.8-§7.10, MASORA_DESIGN.md §8)."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from .audit import REMEDY, audit_pending
from .checker import FILENAME_RE, check_base
from .diagnostics import (
    E_FOUNDER,
    E_GC_UNAVAILABLE,
    E_GIT,
    E_MERGE_BASE,
    E_NO_ORIGIN,
    E_REWRITE,
    E_SYNC_SELECT,
    E_SYNC_STACKED,
    E_TOMBSTONE_SHAPE,
    E_TOMBSTONE_SHRINK,
    W_SYNC_STACKED,
    CheckFailure,
    Diag,
)
from .frontmatter import split_frontmatter
from .ulid import is_ulid

PENDING_BRANCH_NS = "masora"
AUTHOR_SLUG_MAX = 24
REMOTE = "origin"
MAIN_BRANCH = "main"
PR_TITLE = "masora sync"
COMMIT_MESSAGE = "masora sync"
PLAN_EXIT = 3

# Subprocess timeouts (M4): a hung git/gh spawn must never block a sync or
# spend an MCP call's whole budget. Local operations get a short budget,
# network operations a longer one; the forge CLI is interactive-ish but
# non-essential (its failure is always just a note).
GIT_TIMEOUT_S = 60
FETCH_TIMEOUT_S = 300
NETWORK_TIMEOUT_S = 600
GH_TIMEOUT_S = 30

REPO_LOCATION_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def git_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return env (or os.environ) without repo-location GIT_* variables, with
    `GIT_TERMINAL_PROMPT=0` — a git spawn must fail fast when it would ask for
    credentials, never hang waiting for a terminal that is not there (M4)."""
    result = dict(os.environ if env is None else env)
    for name in REPO_LOCATION_ENV_VARS:
        result.pop(name, None)
    result["GIT_TERMINAL_PROMPT"] = "0"
    return result


def run_git(cmd: list[str], *, timeout: int = GIT_TIMEOUT_S, error=None, **kwargs):
    """A `subprocess.run` for git/gh spawns with a mandatory timeout (M4).

    `subprocess.TimeoutExpired` and `FileNotFoundError` (missing binary) are
    mapped through `error` — a callable `str -> Exception` carrying the
    site's E-GIT-family diagnostic — when given, and the process returns None
    when it is not (sites whose contract already treats a git failure as
    "unavailable"). kwargs must not set `timeout` or `check`.
    """
    try:
        return subprocess.run(cmd, timeout=timeout, check=False, **kwargs)
    except subprocess.TimeoutExpired as exc:
        if error is None:
            return None
        raise error(f"{cmd[0]} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        if error is None:
            return None
        raise error(f"{cmd[0]} is not available on PATH — install it and retry") from exc


class SyncError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


IDENTITY_REMEDY = (
    "sync publishes commits and needs a commit identity — set it with:"
    " git config --global user.name '<your name>' and git config --global user.email '<you@example.org>'"
)


def _author_slugify(name: str) -> str:
    """The per-author branch slug: lowercase ASCII `[a-z0-9-]`, spaces and dots
    become `-`, every other character (accents, punctuation) is dropped, runs
    collapse to one `-`, trimmed to 24 characters. Deterministic; an empty
    result means the identity is unusable."""
    out: list[str] = []
    for char in name.lower():
        if char in " .":
            out.append("-")
        elif ("a" <= char <= "z") or ("0" <= char <= "9") or char == "-":
            out.append(char)
    collapsed = re.sub("-+", "-", "".join(out)).strip("-")
    return collapsed[:AUTHOR_SLUG_MAX].rstrip("-")


def author_slug(base_dir: Path) -> str:
    """The pending-branch author slug from the base clone's git `user.name`.

    A missing or unusable identity is an E-GIT refusal (with the identity
    remedy): sync needs a commit identity anyway, so inventing a branch name
    here would only defer the failure to the first commit.
    """
    proc = run_git(
        ["git", "-C", str(base_dir), "config", "--get", "user.name"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    raw = proc.stdout.strip() if proc is not None and proc.returncode == 0 else ""
    slug = _author_slugify(raw)
    if not slug:
        raise SyncError(
            Diag(
                "error",
                E_GIT,
                f"no usable git user.name in {base_dir} — the per-author pending branch"
                f" masora/<author> derives from it; {IDENTITY_REMEDY}",
            )
        )
    return slug


def pending_branch(base_dir: Path) -> str:
    """The per-author pending branch: `masora/<author-slug>` — two writers never
    collide on one shared branch (each pushes and opens its own PR)."""
    return f"{PENDING_BRANCH_NS}/{author_slug(base_dir)}"


@dataclass
class EventFile:
    id: str
    path: str
    content: bytes
    lineage: str | None = None
    kind: str | None = None
    summary: str | None = None
    targets: str | None = None
    source: str | None = None
    name: str | None = None
    reason: str | None = None
    evidence_count: int = 0


def run(
    base_dir: Path,
    drop: bool = False,
    push: bool = False,
    allow_stacked: bool = False,
    yes: bool = False,
    only: list[str] | None = None,
    exclude: list[str] | None = None,
) -> int:
    print(f"masora sync {base_dir}")
    if not base_dir.is_dir():
        print(f"masora sync: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    if only is not None and exclude is not None:
        print(
            f"  {Diag('error', E_SYNC_SELECT, '--only and --exclude are mutually exclusive').render()}"
        )
        return 1
    if drop:
        return _run_drop(base_dir, yes)
    return _run_publish(base_dir, push, allow_stacked, yes, only=only, exclude=exclude)


def _run_publish(
    base_dir: Path,
    push: bool,
    allow_stacked: bool = False,
    yes: bool = False,
    only: list[str] | None = None,
    exclude: list[str] | None = None,
) -> int:
    local = check_base(base_dir)
    print(
        f"local check: scanned {local.file_count} event file(s), {local.lineage_count} lineage(s)"
    )
    for diag in local.diags:
        print(f"  {diag.render()}")
    if local.errors:
        print(f"FAILED: {len(local.errors)} error(s) (local check) — sync blocked")
        return 1

    try:
        _git(base_dir, "rev-parse", "--git-dir")
        _require_repo_root(base_dir)
        _remote_url(base_dir)
        _fetch(base_dir)
        origin_main = _origin_main(base_dir)
        merge_base = _merge_base(base_dir)
        branch = pending_branch(base_dir)
    except SyncError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1

    errors: list[Diag] = []
    warnings: list[Diag] = list(local.warnings)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            origin_dir = tmp_root / "origin"
            merged_dir = tmp_root / "merged"
            base_snapshot_dir = tmp_root / "base-snapshot"
            _materialize(base_dir, origin_main, origin_dir)
            _materialize(base_dir, merge_base, base_snapshot_dir)
            local_events = _scan_events(base_dir)
            origin_events = _scan_events(origin_dir)
            base_events = _scan_events(base_snapshot_dir)

            added_ids = sorted(set(local_events) - set(origin_events))
            common_ids = set(local_events) & set(origin_events)
            rewritten_ids = sorted(
                event_id
                for event_id in set(local_events) & (set(base_events) | set(origin_events))
                if (
                    event_id in base_events
                    and local_events[event_id].content != base_events[event_id].content
                )
                or (
                    event_id in origin_events
                    and local_events[event_id].content != origin_events[event_id].content
                )
            )
            # Deletion detection (the refusal scan): merge-base-relative — an
            # event this history KNEW and no longer has. The deletions another
            # writer already PUBLISHED are detected separately, against
            # origin/main's post-fetch tombstone table (origin_dead_ids below):
            # a stale local main must not hide them, nor resurrect them.
            deleted_ids = sorted(set(base_events) - set(local_events))
            print(
                f"diff vs {REMOTE}/{MAIN_BRANCH} ({origin_main[:12]}): "
                f"{len(added_ids)} added, {len(common_ids) - len(rewritten_ids)} unchanged, "
                f"{len(rewritten_ids)} rewritten, {len(deleted_ids)} deleted"
            )

            selected_added = added_ids
            excluded_ids: set[str] = set()
            if only is not None or exclude is not None:
                try:
                    selected_added = _select_pending(added_ids, only, exclude)
                except SyncError as exc:
                    print(f"  {exc.diag.render()}")
                    print("FAILED: 1 error(s)")
                    return 1
                excluded_ids = set(added_ids) - set(selected_added)
                if exclude is not None:
                    print(
                        f"--exclude selection: {len(excluded_ids)} of {len(added_ids)} pending"
                        " event(s) excluded from this sync (they stay pending locally):"
                    )
                    for event_id in sorted(excluded_ids):
                        print(f"  excluded: {event_id}")
                else:
                    print(
                        f"--only selection: {len(selected_added)} of {len(added_ids)} pending"
                        " event(s) will be published"
                    )

            stacked = _stacked_pending(local_events, selected_added)
            if stacked:
                _report_stacked(stacked, local_events, allow_stacked, warnings)
                if not allow_stacked:
                    print(REMEDY)
                    print(f"FAILED: {len(stacked)} error(s)")
                    return 1

            pairs_local = _tombstone_pairs(
                (base_dir / "deleted.toml").read_bytes()
                if (base_dir / "deleted.toml").exists()
                else None,
                "local",
            )
            de_local = _deleted_event_pairs(
                (base_dir / "deleted.toml").read_bytes()
                if (base_dir / "deleted.toml").exists()
                else None,
                "local",
            )
            tombstoned = {value for pair in pairs_local for value in pair}

            for event_id in rewritten_ids:
                errors.append(
                    Diag(
                        "error",
                        E_REWRITE,
                        f"event id {event_id} was rewritten: append-only history (FORMAT.md §7.9) — "
                        f"content differs from the recorded history ({origin_events[event_id].path if event_id in origin_events else base_events[event_id].path});"
                        " if the remote history was rewritten out-of-band, see docs/REFOUNDATION.md",
                        local_events[event_id].path,
                    )
                )
            errors.extend(
                _deletion_diags(deleted_ids, base_events, origin_events, tombstoned, de_local)
            )

            pairs_base = _tombstone_pairs(
                _git_show_optional(base_dir, f"{merge_base}:deleted.toml"), "merge-base"
            )
            de_base = _deleted_event_pairs(
                _git_show_optional(base_dir, f"{merge_base}:deleted.toml"), "merge-base"
            )
            pairs_origin = _tombstone_pairs(
                (origin_dir / "deleted.toml").read_bytes()
                if (origin_dir / "deleted.toml").exists()
                else None,
                "origin/main",
            )
            de_origin = _deleted_event_pairs(
                (origin_dir / "deleted.toml").read_bytes()
                if (origin_dir / "deleted.toml").exists()
                else None,
                "origin/main",
            )
            # Deletions ALREADY PUBLISHED by another writer (origin/main's
            # post-fetch tombstone table): events whose id the shared ledger
            # has collected. A stale local main still carries their files; the
            # merged tree must drop them, not resurrect them (and not brick on
            # E-TOMBSTONED at the merged check). Events whose id is NOT
            # tombstoned on origin but whose lineage is (a new doubt on a
            # collected lineage) are still copied — the merged check refuses
            # them, surfacing the gc race.
            origin_dead_ids = {ulid for _lineage, ulid in pairs_origin | de_origin}
            dead_paths = {
                event.path for event in local_events.values() if event.id in origin_dead_ids
            }
            missing = sorted(pairs_base - pairs_local)
            if missing:
                listing = ", ".join(f"({lineage}, {ulid})" for lineage, ulid in missing)
                errors.append(
                    Diag(
                        "error",
                        E_TOMBSTONE_SHRINK,
                        f"deleted.toml lost tombstone entries present at the merge-base: {listing} — tombstones are append-only by content (FORMAT.md §7.10)",
                        "deleted.toml",
                    )
                )
            de_missing = sorted(de_base - de_local)
            if de_missing:
                listing = ", ".join(f"({lineage}, {ulid})" for lineage, ulid in de_missing)
                errors.append(
                    Diag(
                        "error",
                        E_TOMBSTONE_SHRINK,
                        f"deleted.toml lost deleted_events entries present at the merge-base: {listing} — tombstones are append-only by content (FORMAT.md §7.10)",
                        "deleted.toml",
                    )
                )

            for event_id in selected_added:
                event = local_events[event_id]
                if (
                    event.kind == "claim"
                    and event.id != event.lineage
                    and not (
                        _is_founder(origin_events.get(event.lineage))
                        or _is_founder(local_events.get(event.lineage))
                    )
                ):
                    errors.append(
                        Diag(
                            "error",
                            E_FOUNDER,
                            f"claim version {event_id} (lineage {event.lineage}) has no founding claim in origin/main or in the pending diff "
                            "(self-contained lineages, FORMAT.md §7.8)",
                            event.path,
                        )
                    )

            for diag in errors:
                print(f"  {diag.render()}")

            if errors:
                print("merged-result check skipped: diff errors above")
            else:
                _build_merged(
                    origin_dir,
                    base_dir,
                    merged_dir,
                    pairs_local,
                    pairs_origin,
                    de_local,
                    de_origin,
                    deleted_ids,
                    origin_events,
                    skip_paths={local_events[event_id].path for event_id in excluded_ids},
                    dead_paths=dead_paths,
                )
                merged = check_base(merged_dir)
                print(
                    f"merged-result check (origin/main + pending): scanned {merged.file_count} event file(s), {merged.lineage_count} lineage(s)"
                )
                for diag in merged.diags:
                    print(f"  {diag.render()}")
                errors.extend(merged.errors)
                warnings.extend(merged.warnings)

            if errors:
                print(f"FAILED: {len(errors)} error(s)")
                return 1

            # Events the shared ledger already tombstoned but this (possibly
            # stale) clone still carries: applying them counts as pending work,
            # so sync proceeds and the push/reset lands the pruned state.
            applied_upstream = sorted(
                event_id for event_id in local_events if event_id in origin_dead_ids
            )
            has_pending = (
                bool(selected_added)
                or bool(pairs_local - pairs_base)
                or bool(de_local - de_base)
                or bool(applied_upstream)
            )
            if not has_pending:
                print("no pending events: nothing to sync")
                if warnings:
                    print(f"synced with warnings: {len(warnings)} warning(s)")
                    return 2
                print("synced: 0 pending event(s)")
                return 0

            pending = [local_events[event_id] for event_id in selected_added]
            removed = len(pairs_local - pairs_base) + len(de_local - de_base)
            if not yes:
                print(_pr_body(pending, warnings, local_events, removed), end="")
                action = "push to origin/main" if push else "publish (one branch and one PR)"
                print(f"plan only: nothing written — re-run with --yes to {action}")
                return PLAN_EXIT

            commit, tree = _commit_tree(base_dir, merged_dir, origin_main)
            if push:
                _git(base_dir, "push", REMOTE, f"{commit}:refs/heads/{MAIN_BRANCH}")
                local_main = _preserve_committed_excluded(
                    base_dir, commit, origin_main, excluded_ids, local_events
                )
                _git(base_dir, "update-ref", f"refs/heads/{MAIN_BRANCH}", local_main)
                if _head_branch(base_dir) == MAIN_BRANCH:
                    _git(base_dir, "reset", "--hard", local_main)
                preserved_note = (
                    " (excluded committed event(s) preserved on local main)"
                    if local_main != commit
                    else ""
                )
                print(
                    f"pushed {commit[:12]} to {REMOTE}/{MAIN_BRANCH} (solo mode, direct push);"
                    f" local {MAIN_BRANCH} advanced{preserved_note}"
                )
            else:
                current = _optional_rev(base_dir, f"refs/heads/{branch}")
                remote_tracking = _optional_rev(base_dir, f"refs/remotes/{REMOTE}/{branch}")
                up_to_date = (
                    current is not None
                    and remote_tracking == current
                    and _optional_rev(base_dir, f"{current}^") == origin_main
                    and _git(base_dir, "rev-parse", f"{current}^{{tree}}") == tree
                )
                if up_to_date:
                    print(f"pending set unchanged: {branch} already carries it ({current[:12]})")
                else:
                    _git(base_dir, "update-ref", f"refs/heads/{branch}", commit)
                    _git(
                        base_dir,
                        "push",
                        "--force-with-lease",
                        REMOTE,
                        f"{branch}:{branch}",
                    )
                    print(f"pushed branch {branch} ({commit[:12]})")
                    _publish_pr(base_dir, branch, pending, warnings, local_events, removed)
    except SyncError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1

    if warnings:
        print(f"synced with warnings: {len(warnings)} warning(s)")
        return 2
    tombstone_note = (
        " + tombstone additions" if (pairs_local - pairs_base) or (de_local - de_base) else ""
    )
    if applied_upstream:
        tombstone_note += f" + {len(applied_upstream)} upstream-published deletion(s) applied"
    print(f"synced: {len(selected_added)} pending event(s){tombstone_note}")
    return 0


def _run_drop(base_dir: Path, yes: bool = False) -> int:
    try:
        _git(base_dir, "rev-parse", "--git-dir")
        _remote_url(base_dir)
        _fetch(base_dir)
        origin_main = _origin_main(base_dir)
        branch = pending_branch(base_dir)
        local_pending = _optional_rev(base_dir, f"refs/heads/{branch}")
        remote_pending = _optional_rev(base_dir, f"refs/remotes/{REMOTE}/{branch}")
    except SyncError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    if local_pending is None and remote_pending is None:
        print(f"nothing to drop: no local or remote {branch}")
        return 0
    dropped: list[EventFile] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        main_dir = tmp_root / "main"
        pending_dir = tmp_root / "pending"
        _materialize(base_dir, origin_main, main_dir)
        main_events = _scan_events(main_dir)
        _materialize(base_dir, local_pending or remote_pending, pending_dir)
        pending_events = _scan_events(pending_dir)
        dropped = [
            pending_events[event_id] for event_id in sorted(set(pending_events) - set(main_events))
        ]
    for event in dropped:
        summary = event.summary if isinstance(event.summary, str) and event.summary else event.path
        print(f"  dropped: {event.id} {event.kind or 'event'}: {summary}")
    if not yes:
        # Plan mode: the discard is destructive, so it waits for --yes like
        # publish does — the listing above is the plan, nothing is touched.
        print(f"would discard {len(dropped)} pending event(s)")
        print("plan only: nothing written — re-run with --yes to discard")
        return PLAN_EXIT
    print(f"dropped {len(dropped)} pending event(s)")
    _close_pr(base_dir, branch)
    if remote_pending is not None:
        _git(base_dir, "push", REMOTE, "--delete", branch)
        print(f"deleted remote branch {branch}")
    _git(base_dir, "update-ref", "-d", f"refs/heads/{branch}")
    print(f"deleted local branch {branch}")
    print(
        "note: the local .md files of the dropped events were left in place; delete them or edit before the next sync"
    )
    return 0


def _select_pending(
    added_ids: list[str], only: list[str] | None, exclude: list[str] | None
) -> list[str]:
    """Resolve the --only/--exclude selectors against the pending EVENT
    ADDITIONS and return the selected event ids (sorted).

    A selector matches by full ULID or by unique prefix (git-short-sha style);
    an exact match wins over prefix ambiguity. A selector matching nothing, or
    a prefix matching several pending ids, is a refusal — a typo must neither
    silently publish everything nor silently exclude nothing. The two flags
    are mutually exclusive (checked at the entry point too). Deletions decided
    by gc are not filterable and are not part of this selection.
    """
    if only is not None and exclude is not None:
        raise SyncError(Diag("error", E_SYNC_SELECT, "--only and --exclude are mutually exclusive"))
    selectors = only if only is not None else exclude
    mode = "--only" if only is not None else "--exclude"
    pending = sorted(added_ids)
    selected: list[str] = []
    problems: list[str] = []
    for selector in selectors:
        if selector in pending:
            selected.append(selector)
            continue
        matches = [event_id for event_id in pending if event_id.startswith(selector)]
        if not matches:
            problems.append(
                f"no pending event matches {mode} selector '{selector}' — "
                "select from the pending additions only (deletions are not filterable)"
            )
        elif len(matches) > 1:
            candidates = ", ".join(matches)
            problems.append(f"{mode} selector '{selector}' is ambiguous — matches: {candidates}")
        else:
            selected.append(matches[0])
    if problems:
        raise SyncError(Diag("error", E_SYNC_SELECT, "; ".join(problems)))
    matched = set(selected)
    if exclude is not None:
        return sorted(set(pending) - matched)
    return sorted(matched)


def _stacked_pending(
    local_events: dict[str, EventFile], added_ids: list[str]
) -> dict[str, list[str]]:
    """The stacking audit over the pending CLAIM events; the parsed claim
    events come from sync's own lenient frontmatter read (already past the
    local check gate, so every pending file parses)."""
    pairs = []
    for event_id in added_ids:
        event = local_events[event_id]
        if event.kind != "claim":
            continue
        data = _lenient_frontmatter(event.content, Path(event.path).name)
        if data is not None:
            pairs.append((event.path, data))
    return audit_pending(pairs)


def _report_stacked(
    stacked: dict[str, list[str]],
    local_events: dict[str, EventFile],
    allow_stacked: bool,
    warnings: list[Diag],
) -> None:
    """One line per flagged lineage with its fired signals: a refusal when the
    override is absent, a W-SYNC-STACKED warning riding the plan with it."""
    print(
        f"stacked block claims in the pending set: {_plural(len(stacked), 'lineage', 'lineages')}"
    )
    for key, signals in sorted(stacked.items()):
        label, path = _stacked_label_path(key, local_events)
        message = f"{label}: {'; '.join(signals)}"
        if allow_stacked:
            diag = Diag(
                "warning",
                W_SYNC_STACKED,
                f"{message} — published with --allow-stacked",
                path,
            )
            print(f"  {diag.render()}")
            warnings.append(diag)
        else:
            print(f"  {Diag('error', E_SYNC_STACKED, message, path).render()}")


def _stacked_label_path(key: str, events: dict[str, EventFile]) -> tuple[str, str | None]:
    """Display label and file path of a flagged lineage id — the founder's
    slug when the lineage resolves, else the key itself (a pathless file)."""
    founder = events.get(key)
    if founder is not None and founder.lineage == key:
        return _lineage_label(founder, events), founder.path
    return key, key if key.endswith(".md") else None


def _deletion_diags(
    deleted_ids: list[str],
    base_events: dict[str, EventFile],
    origin_events: dict[str, EventFile],
    tombstoned: set[str],
    event_tombstones: set[tuple[str, str]],
) -> list[Diag]:
    """Refusals for local deletions the shared repo still knows: the diff
    baseline is the merge-base (an event this history knew and no longer
    has), and each refusal additionally requires the event to still exist on
    origin/main — a published deletion is never re-refused here. A deletion
    survives only when the lineage was gc'd (whole-lineage) or the event id
    is tombstoned."""
    if not deleted_ids:
        return []
    lineage_ids: dict[str, set[str]] = {}
    for event in base_events.values():
        if event.lineage:
            lineage_ids.setdefault(event.lineage, set()).add(event.id)
    gc_lineages = {lineage for lineage, ids in lineage_ids.items() if ids <= set(deleted_ids)}
    diags: list[Diag] = []
    for event_id in deleted_ids:
        if event_id not in origin_events:
            continue
        lineage = base_events[event_id].lineage
        if lineage in gc_lineages:
            continue
        if (lineage, event_id) in event_tombstones:
            continue
        diags.append(
            Diag(
                "error",
                E_REWRITE,
                f"event id {event_id} was deleted: append-only history (FORMAT.md §7.9) — still present in origin/main at {origin_events[event_id].path};"
                " if the remote history was rewritten out-of-band, see docs/REFOUNDATION.md",
                origin_events[event_id].path,
            )
        )
    for lineage in sorted(gc_lineages):
        if any(event_id in origin_events for event_id in lineage_ids[lineage]):
            if lineage in tombstoned:
                continue
            tombstoned_events = {ulid for lin, ulid in event_tombstones if lin == lineage}
            if lineage_ids[lineage] <= tombstoned_events:
                continue
            diags.append(
                Diag(
                    "error",
                    E_GC_UNAVAILABLE,
                    f"lineage {lineage} is deleted entirely without a tombstone in deleted.toml: whole-lineage deletion is tampering (FORMAT.md §7.9) — use `masora gc --lineage`, which tombstones the lineage (§7.10)",
                )
            )
    return diags


def _tombstone_pairs(data: bytes | None, where: str) -> set[tuple[str, str]]:
    return _table_pairs(data, where, "deleted")


def _deleted_event_pairs(data: bytes | None, where: str) -> set[tuple[str, str]]:
    return _table_pairs(data, where, "deleted_events")


def _table_pairs(data: bytes | None, where: str, table: str) -> set[tuple[str, str]]:
    if data is None:
        return set()
    try:
        parsed = tomllib.loads(data.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise SyncError(
            Diag(
                "error",
                E_TOMBSTONE_SHAPE,
                f"deleted.toml ({where}) is not valid TOML: {exc}",
                "deleted.toml",
            )
        ) from exc
    blocks = parsed.get(table, []) if isinstance(parsed, dict) else None
    if not isinstance(blocks, list) or any(not isinstance(block, dict) for block in blocks):
        raise SyncError(
            Diag(
                "error",
                E_TOMBSTONE_SHAPE,
                f"deleted.toml ({where}) {table} must be a list of [[{table}]] tables",
                "deleted.toml",
            )
        )
    pairs: set[tuple[str, str]] = set()
    for block in blocks:
        lineage = block.get("lineage")
        ulids = block.get("ulids")
        if (
            not isinstance(lineage, str)
            or not isinstance(ulids, list)
            or any(not isinstance(ulid, str) for ulid in ulids)
        ):
            raise SyncError(
                Diag(
                    "error",
                    E_TOMBSTONE_SHAPE,
                    f"deleted.toml ({where}) {table} blocks must have {{lineage, ulids}} string values",
                    "deleted.toml",
                )
            )
        for ulid in ulids:
            pairs.add((lineage, ulid))
    return pairs


def _render_blocks(pairs: set[tuple[str, str]], table: str) -> str:
    by_lineage: dict[str, list[str]] = {}
    for lineage, ulid in pairs:
        by_lineage.setdefault(lineage, []).append(ulid)
    blocks = []
    for lineage in sorted(by_lineage):
        ulids = ", ".join(f'"{ulid}"' for ulid in sorted(by_lineage[lineage]))
        blocks.append(f'[[{table}]]\nlineage = "{lineage}"\nulids = [{ulids}]\n')
    return "\n".join(blocks)


def _render_tombstone(pairs: set[tuple[str, str]]) -> str:
    return _render_blocks(pairs, "deleted")


def _render_deleted_events(pairs: set[tuple[str, str]]) -> str:
    return _render_blocks(pairs, "deleted_events")


def _preserve_committed_excluded(
    base_dir: Path,
    pushed_commit: str,
    origin_main: str,
    excluded_ids: set[str],
    local_events: dict[str, EventFile],
) -> str:
    """The commit local main must point at after a solo `--push`.

    The pushed commit's tree is origin/main + the selected events only. When
    the selection EXCLUDED events that are already COMMITTED on local main,
    advancing main to the pushed commit (then `reset --hard`) would drop them
    from the branch and the work tree (reflog-only recovery) — breaking the
    --exclude promise for committed events. Instead this builds a preservation
    commit ON TOP of the pushed commit: the pushed tree plus the excluded
    event files taken verbatim from the work tree. Local main and the work
    tree keep the excluded events; origin/main never sees them (their commits
    are superseded by one local preservation commit). Without committed
    excluded events, the pushed commit is returned unchanged.
    """
    head = _optional_rev(base_dir, f"refs/heads/{MAIN_BRANCH}")
    if head is None or head == pushed_commit:
        return pushed_commit
    paths = [
        local_events[event_id].path for event_id in sorted(excluded_ids) if event_id in local_events
    ]
    committed = [rel for rel in paths if _tree_has_path(base_dir, head, rel)]
    if not committed:
        return pushed_commit
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "preserved"
        _materialize(base_dir, pushed_commit, work)
        for rel in committed:
            src = base_dir / rel
            dst = work / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return _commit_tree(base_dir, work, pushed_commit, "masora sync: preserve excluded events")[
            0
        ]


def _tree_has_path(base_dir: Path, commit: str, rel: str) -> bool:
    proc = run_git(
        ["git", "-C", str(base_dir), "ls-tree", "--", commit, rel],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    return proc is not None and proc.returncode == 0 and bool(proc.stdout.strip())


def _build_merged(
    origin_dir: Path,
    base_dir: Path,
    merged_dir: Path,
    pairs_local: set[tuple[str, str]],
    pairs_origin: set[tuple[str, str]],
    de_local: set[tuple[str, str]],
    de_origin: set[tuple[str, str]],
    deleted_ids: list[str],
    origin_events: dict[str, EventFile],
    skip_paths: set[str] | None = None,
    dead_paths: set[str] | None = None,
) -> None:
    shutil.copytree(origin_dir, merged_dir)
    dropped_paths = skip_paths or set()
    dead_paths = dead_paths or set()
    for path in sorted(base_dir.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        rel = path.relative_to(base_dir)
        if not (FILENAME_RE.match(path.name) or rel in ("base.toml", "deleted.toml")):
            continue
        if str(rel) in dropped_paths:
            # An --only/--exclude selection: the excluded pending events stay
            # out of the published tree so the merged result is validated —
            # and published — without them.
            continue
        if str(rel) in dead_paths:
            # Already tombstoned on origin/main (another writer's published
            # deletion): never resurrect it from a stale clone.
            continue
        dest = merged_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    for event_id in deleted_ids:
        event = origin_events.get(event_id)
        if event is not None:
            (merged_dir / event.path).unlink(missing_ok=True)
    merged_tombstone = _render_tombstone(pairs_local | pairs_origin)
    merged_events = _render_deleted_events(de_local | de_origin)
    if (
        pairs_local
        or pairs_origin
        or de_local
        or de_origin
        or (origin_dir / "deleted.toml").exists()
        or (base_dir / "deleted.toml").exists()
    ):
        (merged_dir / "deleted.toml").write_text(merged_tombstone + merged_events, encoding="utf-8")


def _scan_events(root: Path) -> dict[str, EventFile]:
    events: dict[str, EventFile] = {}
    for path in sorted(root.rglob("*.md")):
        if ".git" in path.parts:
            continue
        rel = str(path.relative_to(root))
        content = path.read_bytes()
        data = _lenient_frontmatter(content, path.name)
        event_id = _identity(data, path)
        if event_id is None or event_id in events:
            continue
        events[event_id] = EventFile(
            id=event_id,
            path=rel,
            content=content,
            lineage=_string(data, "lineage"),
            kind=_string(data, "kind"),
            summary=_string(data, "summary"),
            targets=_string(data, "targets"),
            source=_string(data, "source"),
            name=_string(data, "name"),
            reason=_string(data, "reason"),
            evidence_count=(
                len(evidence) if isinstance(evidence := data.get("evidence"), list) else 0
            ),
        )
    return events


def _lenient_frontmatter(content: bytes, name: str) -> dict | None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        raw = split_frontmatter(text, name)
    except CheckFailure:
        return None
    try:
        data = yaml.safe_load(raw)
    except (yaml.YAMLError, RecursionError):
        # RecursionError: deeply nested YAML — the lenient scan treats it as
        # unparsable (M7's E-YAML fires on the validating paths).
        return None
    return data if isinstance(data, dict) else None


def _identity(data: dict | None, path: Path) -> str | None:
    if data:
        value = data.get("id")
        if isinstance(value, str) and is_ulid(value):
            return value
    match = FILENAME_RE.match(path.name)
    if match and is_ulid(match.group("ulid")):
        return match.group("ulid")
    return None


def _string(data: dict | None, key: str) -> str | None:
    if data:
        value = data.get(key)
        if isinstance(value, str):
            return value
    return None


def _is_founder(event: EventFile | None) -> bool:
    return event is not None and event.kind == "claim" and event.id == event.lineage


_KIND_LABELS = {
    "claim": ("claim", "claims"),
    "verify": ("verification", "verifications"),
    "doubt": ("doubt", "doubts"),
    "refute": ("refutation", "refutations"),
    "undoubt": ("undoubt", "undoubts"),
    "unrefute": ("unrefute", "unrefutes"),
}
_KIND_VERBS = {
    "doubt": "doubted",
    "refute": "refuted",
    "undoubt": "undoubted",
    "unrefute": "unrefuted",
}
_KIND_ORDER = ("claim", "verify", "doubt", "refute", "undoubt", "unrefute", "event")


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {plural or singular + 's'}"


def _writer(event: EventFile) -> str:
    if isinstance(event.name, str) and event.name:
        return event.name
    return event.source or "unknown"


def _target_summary(event: EventFile, events: dict[str, EventFile]) -> str:
    node = event.targets
    seen = {event.id}
    while node and node in events and node not in seen and len(seen) <= 4:
        seen.add(node)
        target = events[node]
        if target.summary:
            return target.summary
        node = target.targets
    return event.targets or "unknown target"


def _reason_text(event: EventFile) -> str:
    text = " ".join((event.reason or "").split())
    return text if len(text) <= 80 else f"{text[:80]}…"


def _lineage_label(event: EventFile, events: dict[str, EventFile]) -> str:
    founder = events.get(event.lineage or "")
    if founder is not None and founder.id == founder.lineage and founder.summary:
        from .write import slugify_summary

        slug = slugify_summary(founder.summary)
        if slug:
            return slug
    return event.lineage or event.id


def _event_line(event: EventFile, events: dict[str, EventFile]) -> str:
    if event.kind == "claim":
        summary = event.summary or "(summary unavailable)"
        return f'- {_lineage_label(event, events)}: "{summary}" — {_writer(event)}'
    if event.kind == "verify":
        summary = _target_summary(event, events)
        return (
            f'- verified "{summary}" — by {_writer(event)}'
            f" — {_plural(event.evidence_count, 'evidence item')}"
        )
    verb = _KIND_VERBS.get(event.kind or "", event.kind or "event")
    summary = _target_summary(event, events)
    return f'- {verb} "{summary}" — {_reason_text(event)} — by {_writer(event)}'


def _pr_title(pending: list[EventFile], removed: int) -> str:
    counts: dict[str, int] = {}
    for event in pending:
        kind = event.kind or "event"
        counts[kind] = counts.get(kind, 0) + 1
    segments = [
        _plural(counts[kind], *_KIND_LABELS.get(kind, ("event", "events")))
        for kind in _KIND_ORDER
        if counts.get(kind)
    ]
    if removed:
        segments.append(f"{removed} tombstoned")
    if not segments:
        return PR_TITLE
    return f"{PR_TITLE}: {', '.join(segments)}"


def _pr_body(
    pending: list[EventFile],
    warnings: list[Diag],
    events: dict[str, EventFile] | None = None,
    removed: int = 0,
) -> str:
    known = events if events is not None else {}
    lines = [_pr_title(pending, removed), ""]
    lines.extend(_event_line(event, known) for event in pending)
    if removed:
        lines.append(f"- {_plural(removed, 'event')} removed by compact/gc")
    if warnings:
        lines.extend(["", f"Warnings ({len(warnings)}):", ""])
        lines.extend(f"- {diag.render()}" for diag in warnings)
    return "\n".join(lines) + "\n"


def _publish_pr(
    base_dir: Path,
    branch: str,
    pending: list[EventFile],
    warnings: list[Diag],
    events: dict[str, EventFile] | None = None,
    removed: int = 0,
) -> None:
    title = _pr_title(pending, removed)
    body = _pr_body(pending, warnings, events, removed)
    url = _remote_url(base_dir)
    slug = _github_slug(url)
    gh = _gh_on_path()
    if gh is None or slug is None:
        print(
            f"forge CLI not available for this remote: open the pull request from {branch} to {MAIN_BRANCH} at {_compare_url(url, slug, branch)}"
        )
        return
    existing = _gh_pr_list(gh, slug, branch)
    if existing:
        number, pr_url = existing
        _gh_run(
            gh,
            ["pr", "edit", str(number), "--repo", slug, "--title", title, "--body-file", "-"],
            body,
        )
        print(f"updated PR {pr_url}")
    else:
        pr_url = _gh_run(
            gh,
            [
                "pr",
                "create",
                "--repo",
                slug,
                "--head",
                branch,
                "--base",
                MAIN_BRANCH,
                "--title",
                title,
                "--body-file",
                "-",
            ],
            body,
        )
        print(f"opened PR {pr_url or '(forge CLI returned no url)'}")


def _close_pr(base_dir: Path, branch: str) -> None:
    gh = _gh_on_path()
    if gh is None:
        print(
            f"note: forge CLI (gh) not available; an open pull request from {branch} could not be looked up or closed"
        )
        return
    try:
        slug = _github_slug(_remote_url(base_dir))
    except SyncError:
        slug = None
    if slug is None:
        print(
            f"note: remote is not GitHub; an open pull request from {branch} could not be looked up or closed"
        )
        return
    existing = _gh_pr_list(gh, slug, branch)
    if existing is None:
        return
    if existing:
        number, pr_url = existing
        proc = run_git(
            [gh, "pr", "close", str(number), "--repo", slug],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_S,
            env=git_env(),
        )
        if proc is None:
            print(f"note: could not close PR {pr_url} (gh unavailable or timed out)")
        elif proc.returncode == 0:
            print(f"closed PR {pr_url}")
        else:
            print(f"note: could not close PR {pr_url}: {proc.stderr.strip()}")


def _gh_pr_list(gh: str, slug: str, branch: str) -> tuple[int, str] | None:
    proc = run_git(
        [
            gh,
            "pr",
            "list",
            "--repo",
            slug,
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number,url",
        ],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_S,
        env=git_env(),
    )
    if proc is None or proc.returncode != 0:
        reason = "timed out" if proc is None else proc.stderr.strip()
        print(f"note: could not list open pull requests ({reason})")
        return None
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        # Malformed forge output is a note, never a traceback (LOW sweep).
        print(f"note: could not parse the forge CLI's pull-request list: {exc}")
        return None
    if not isinstance(items, list):
        print("note: could not parse the forge CLI's pull-request list (not a JSON array)")
        return None
    return (items[0]["number"], items[0]["url"]) if items else None


def _gh_run(gh: str, args: list[str], body: str) -> str:
    proc = run_git(
        [gh, *args],
        input=body,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_S,
        env=git_env(),
    )
    if proc is None:
        print(f"note: gh {' '.join(args[:2])} timed out or is unavailable")
        return ""
    if proc.returncode != 0:
        print(f"note: gh {' '.join(args[:2])} failed: {proc.stderr.strip()}")
        return ""
    return proc.stdout.strip()


def _gh_on_path() -> str | None:
    return shutil.which("gh")


def _compare_url(url: str, slug: str | None, branch: str) -> str:
    if slug:
        return f"https://github.com/{slug}/compare/{MAIN_BRANCH}...{branch}?expand=1"
    return url


def _github_slug(url: str) -> str | None:
    text = url.strip()
    for prefix in (
        "https://github.com/",
        "http://github.com/",
        "git@github.com:",
        "ssh://git@github.com/",
        "git://github.com/",
    ):
        if text.startswith(prefix):
            rest = text[len(prefix) :].removesuffix(".git").strip("/")
            parts = rest.split("/")
            if len(parts) == 2 and all(parts):
                return f"{parts[0]}/{parts[1]}"
    return None


def _remote_url(base_dir: Path) -> str:
    proc = run_git(
        ["git", "-C", str(base_dir), "remote", "get-url", REMOTE],
        capture_output=True,
        text=True,
        env=git_env(),
        error=lambda msg: SyncError(Diag("error", E_GIT, f"git remote get-url {REMOTE}: {msg}")),
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SyncError(
            Diag(
                "error",
                E_NO_ORIGIN,
                f"no git remote '{REMOTE}' in {base_dir} (sync compares against and publishes to {REMOTE}/{MAIN_BRANCH})",
            )
        )
    return proc.stdout.strip()


def _fetch(base_dir: Path) -> None:
    proc = run_git(
        ["git", "-C", str(base_dir), "fetch", REMOTE, "--prune"],
        capture_output=True,
        text=True,
        timeout=FETCH_TIMEOUT_S,
        env=git_env(),
        error=lambda msg: SyncError(Diag("error", E_GIT, f"git fetch {REMOTE} failed: {msg}")),
    )
    if proc.returncode != 0:
        raise SyncError(Diag("error", E_GIT, f"git fetch {REMOTE} failed: {proc.stderr.strip()}"))


def _origin_main(base_dir: Path) -> str:
    proc = run_git(
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
        env=git_env(),
        error=lambda msg: SyncError(
            Diag("error", E_GIT, f"git rev-parse {REMOTE}/{MAIN_BRANCH}: {msg}")
        ),
    )
    if proc.returncode != 0:
        raise SyncError(
            Diag(
                "error",
                E_NO_ORIGIN,
                f"{REMOTE}/{MAIN_BRANCH} not found after fetch — the remote repository has no '{MAIN_BRANCH}' branch",
            )
        )
    return proc.stdout.strip()


def _merge_base(base_dir: Path) -> str:
    proc = run_git(
        ["git", "-C", str(base_dir), "merge-base", "HEAD", f"refs/remotes/{REMOTE}/{MAIN_BRANCH}"],
        capture_output=True,
        text=True,
        env=git_env(),
        error=lambda msg: SyncError(Diag("error", E_GIT, f"git merge-base: {msg}")),
    )
    if proc.returncode != 0:
        raise SyncError(
            Diag(
                "error",
                E_MERGE_BASE,
                f"cannot compute the merge-base between HEAD and {REMOTE}/{MAIN_BRANCH} (empty or unrelated history)",
            )
        )
    return proc.stdout.strip()


def _optional_rev(base_dir: Path, rev: str) -> str | None:
    proc = run_git(
        ["git", "-C", str(base_dir), "rev-parse", "--verify", rev],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    return proc.stdout.strip() if proc is not None and proc.returncode == 0 else None


def _head_branch(base_dir: Path) -> str | None:
    proc = run_git(
        ["git", "-C", str(base_dir), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    return proc.stdout.strip() if proc is not None and proc.returncode == 0 else None


def _git(base_dir: Path, *args: str) -> str:
    proc = run_git(
        ["git", "-C", str(base_dir), *args],
        capture_output=True,
        text=True,
        env=git_env(),
        error=lambda msg: SyncError(Diag("error", E_GIT, f"git {' '.join(args)} failed: {msg}")),
    )
    if proc.returncode != 0:
        raise SyncError(Diag("error", E_GIT, f"git {' '.join(args)} failed: {proc.stderr.strip()}"))
    return proc.stdout.strip()


def _require_repo_root(base_dir: Path) -> None:
    toplevel = Path(_git(base_dir, "rev-parse", "--show-toplevel")).resolve()
    if toplevel != base_dir.resolve():
        raise SyncError(
            Diag(
                "error",
                E_GIT,
                f"sync requires the base directory to be the repository root; root is {toplevel}",
            )
        )


def _git_show_optional(base_dir: Path, rev: str) -> bytes | None:
    proc = run_git(
        ["git", "-C", str(base_dir), "show", rev],
        capture_output=True,
        env=git_env(),
    )
    return proc.stdout if proc is not None and proc.returncode == 0 else None


def _materialize(base_dir: Path, commit: str, dest: Path) -> None:
    proc = run_git(
        ["git", "-C", str(base_dir), "archive", "--format=tar", commit],
        capture_output=True,
        env=git_env(),
        error=lambda msg: SyncError(
            Diag("error", E_GIT, f"git archive {commit[:12]} failed: {msg}")
        ),
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise SyncError(Diag("error", E_GIT, f"git archive {commit[:12]} failed: {stderr}"))
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        tar.extractall(dest, filter="data")


def _commit_tree(
    base_dir: Path, work_tree: Path, parent: str, message: str = COMMIT_MESSAGE
) -> tuple[str, str]:
    git_dir = _git(base_dir, "rev-parse", "--absolute-git-dir")
    with tempfile.TemporaryDirectory() as tmp:
        env = git_env() | {
            "GIT_DIR": git_dir,
            "GIT_WORK_TREE": str(work_tree),
            "GIT_INDEX_FILE": str(Path(tmp) / "index"),
        }

        def _plumb(*args: str) -> str:
            proc = run_git(
                ["git", *args],
                cwd=work_tree,
                env=env,
                capture_output=True,
                text=True,
                error=lambda msg: SyncError(
                    Diag("error", E_GIT, f"git {' '.join(args)} failed: {msg}")
                ),
            )
            if proc.returncode != 0:
                raise SyncError(
                    Diag("error", E_GIT, f"git {' '.join(args)} failed: {proc.stderr.strip()}")
                )
            return proc.stdout.strip()

        _plumb("read-tree", "--empty")
        _plumb("add", "-A")
        tree = _plumb("write-tree")
        return _plumb("commit-tree", tree, "-p", parent, "-m", message), tree
