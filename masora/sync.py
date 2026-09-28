"""`masora sync`: publication workflow (FORMAT.md §7.8-§7.10, MASORA_DESIGN.md §8)."""

from __future__ import annotations

import io
import json
import os
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

from .checker import FILENAME_RE, check_base
from .diagnostics import (
    E_FOUNDER,
    E_GC_UNAVAILABLE,
    E_GIT,
    E_MERGE_BASE,
    E_NO_ORIGIN,
    E_REWRITE,
    E_TOMBSTONE_SHAPE,
    E_TOMBSTONE_SHRINK,
    CheckFailure,
    Diag,
)
from .frontmatter import split_frontmatter
from .ulid import is_ulid

PENDING_BRANCH = "masora/pending"
REMOTE = "origin"
MAIN_BRANCH = "main"
PR_TITLE = "masora sync"
COMMIT_MESSAGE = "masora sync"

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
    """Return env (or os.environ) without repo-location GIT_* variables."""
    result = dict(os.environ if env is None else env)
    for name in REPO_LOCATION_ENV_VARS:
        result.pop(name, None)
    return result


class SyncError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


@dataclass
class EventFile:
    id: str
    path: str
    content: bytes
    lineage: str | None = None
    kind: str | None = None
    summary: str | None = None


def run(base_dir: Path, drop: bool = False, push: bool = False) -> int:
    print(f"masora sync {base_dir}")
    if not base_dir.is_dir():
        print(f"masora sync: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    if drop:
        return _run_drop(base_dir)
    return _run_publish(base_dir, push)


def _run_publish(base_dir: Path, push: bool) -> int:
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
            deleted_ids = sorted(set(base_events) - set(local_events))
            print(
                f"diff vs {REMOTE}/{MAIN_BRANCH} ({origin_main[:12]}): "
                f"{len(added_ids)} added, {len(common_ids) - len(rewritten_ids)} unchanged, "
                f"{len(rewritten_ids)} rewritten, {len(deleted_ids)} deleted"
            )

            for event_id in rewritten_ids:
                errors.append(
                    Diag(
                        "error",
                        E_REWRITE,
                        f"event id {event_id} was rewritten: append-only history (FORMAT.md §7.9) — "
                        f"content differs from the recorded history ({origin_events[event_id].path if event_id in origin_events else base_events[event_id].path})",
                        local_events[event_id].path,
                    )
                )
            errors.extend(_deletion_diags(deleted_ids, base_events, origin_events))

            pairs_local = _tombstone_pairs(
                (base_dir / "deleted.toml").read_bytes()
                if (base_dir / "deleted.toml").exists()
                else None,
                "local",
            )
            pairs_base = _tombstone_pairs(
                _git_show_optional(base_dir, f"{merge_base}:deleted.toml"), "merge-base"
            )
            pairs_origin = _tombstone_pairs(
                (origin_dir / "deleted.toml").read_bytes()
                if (origin_dir / "deleted.toml").exists()
                else None,
                "origin/main",
            )
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

            for event_id in added_ids:
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
                _build_merged(origin_dir, base_dir, merged_dir, pairs_local, pairs_origin)
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

            has_pending = bool(added_ids) or bool(pairs_local - pairs_base)
            if not has_pending:
                print("no pending events: nothing to sync")
                if warnings:
                    print(f"synced with warnings: {len(warnings)} warning(s)")
                    return 2
                print("synced: 0 pending event(s)")
                return 0

            commit, tree = _commit_tree(base_dir, merged_dir, origin_main)
            if push:
                _git(base_dir, "push", REMOTE, f"{commit}:refs/heads/{MAIN_BRANCH}")
                _git(base_dir, "update-ref", f"refs/heads/{MAIN_BRANCH}", commit)
                if _head_branch(base_dir) == MAIN_BRANCH:
                    _git(base_dir, "reset", "--hard", commit)
                print(
                    f"pushed {commit[:12]} to {REMOTE}/{MAIN_BRANCH} (solo mode, direct push); local {MAIN_BRANCH} advanced"
                )
            else:
                current = _optional_rev(base_dir, f"refs/heads/{PENDING_BRANCH}")
                remote_tracking = _optional_rev(base_dir, f"refs/remotes/{REMOTE}/{PENDING_BRANCH}")
                up_to_date = (
                    current is not None
                    and remote_tracking == current
                    and _optional_rev(base_dir, f"{current}^") == origin_main
                    and _git(base_dir, "rev-parse", f"{current}^{{tree}}") == tree
                )
                if up_to_date:
                    print(
                        f"pending set unchanged: {PENDING_BRANCH} already carries it ({current[:12]})"
                    )
                else:
                    _git(base_dir, "update-ref", f"refs/heads/{PENDING_BRANCH}", commit)
                    _git(
                        base_dir,
                        "push",
                        "--force-with-lease",
                        REMOTE,
                        f"{PENDING_BRANCH}:{PENDING_BRANCH}",
                    )
                    print(f"pushed branch {PENDING_BRANCH} ({commit[:12]})")
                    _publish_pr(
                        base_dir, [local_events[event_id] for event_id in added_ids], warnings
                    )
    except SyncError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1

    if warnings:
        print(f"synced with warnings: {len(warnings)} warning(s)")
        return 2
    tombstone_note = " + tombstone additions" if pairs_local - pairs_base else ""
    print(f"synced: {len(added_ids)} pending event(s){tombstone_note}")
    return 0


def _run_drop(base_dir: Path) -> int:
    try:
        _git(base_dir, "rev-parse", "--git-dir")
        _remote_url(base_dir)
        _fetch(base_dir)
        origin_main = _origin_main(base_dir)
        local_pending = _optional_rev(base_dir, f"refs/heads/{PENDING_BRANCH}")
        remote_pending = _optional_rev(base_dir, f"refs/remotes/{REMOTE}/{PENDING_BRANCH}")
    except SyncError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    if local_pending is None and remote_pending is None:
        print(f"nothing to drop: no local or remote {PENDING_BRANCH}")
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
    print(f"dropped {len(dropped)} pending event(s)")
    _close_pr(base_dir)
    if remote_pending is not None:
        _git(base_dir, "push", REMOTE, "--delete", PENDING_BRANCH)
        print(f"deleted remote branch {PENDING_BRANCH}")
    _git(base_dir, "update-ref", "-d", f"refs/heads/{PENDING_BRANCH}")
    print(f"deleted local branch {PENDING_BRANCH}")
    print(
        "note: the local .md files of the dropped events were left in place; delete them or edit before the next sync"
    )
    return 0


def _deletion_diags(
    deleted_ids: list[str], base_events: dict[str, EventFile], origin_events: dict[str, EventFile]
) -> list[Diag]:
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
        if base_events[event_id].lineage in gc_lineages:
            continue
        diags.append(
            Diag(
                "error",
                E_REWRITE,
                f"event id {event_id} was deleted: append-only history (FORMAT.md §7.9) — still present in origin/main at {origin_events[event_id].path}",
                origin_events[event_id].path,
            )
        )
    for lineage in sorted(gc_lineages):
        if any(event_id in origin_events for event_id in lineage_ids[lineage]):
            diags.append(
                Diag(
                    "error",
                    E_GC_UNAVAILABLE,
                    f"lineage {lineage} is deleted entirely: whole-lineage deletion requires `masora gc`, which is not implemented yet (FORMAT.md §7.10)",
                )
            )
    return diags


def _tombstone_pairs(data: bytes | None, where: str) -> set[tuple[str, str]]:
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
    blocks = parsed.get("deleted", []) if isinstance(parsed, dict) else None
    if not isinstance(blocks, list) or any(not isinstance(block, dict) for block in blocks):
        raise SyncError(
            Diag(
                "error",
                E_TOMBSTONE_SHAPE,
                f"deleted.toml ({where}) must be a list of [[deleted]] tables",
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
                    f"deleted.toml ({where}) blocks must have {{lineage, ulids}} string values",
                    "deleted.toml",
                )
            )
        for ulid in ulids:
            pairs.add((lineage, ulid))
    return pairs


def _render_tombstone(pairs: set[tuple[str, str]]) -> str:
    by_lineage: dict[str, list[str]] = {}
    for lineage, ulid in pairs:
        by_lineage.setdefault(lineage, []).append(ulid)
    blocks = []
    for lineage in sorted(by_lineage):
        ulids = ", ".join(f'"{ulid}"' for ulid in sorted(by_lineage[lineage]))
        blocks.append(f'[[deleted]]\nlineage = "{lineage}"\nulids = [{ulids}]\n')
    return "\n".join(blocks)


def _build_merged(
    origin_dir: Path,
    base_dir: Path,
    merged_dir: Path,
    pairs_local: set[tuple[str, str]],
    pairs_origin: set[tuple[str, str]],
) -> None:
    shutil.copytree(origin_dir, merged_dir)
    for path in sorted(base_dir.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        rel = path.relative_to(base_dir)
        if not (FILENAME_RE.match(path.name) or rel in ("base.toml", "deleted.toml")):
            continue
        dest = merged_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    if (
        pairs_local
        or pairs_origin
        or (origin_dir / "deleted.toml").exists()
        or (base_dir / "deleted.toml").exists()
    ):
        (merged_dir / "deleted.toml").write_text(
            _render_tombstone(pairs_local | pairs_origin), encoding="utf-8"
        )


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
    except yaml.YAMLError:
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


def _pr_body(pending: list[EventFile], warnings: list[Diag]) -> str:
    lines = [PR_TITLE, "", f"Pending events ({len(pending)}):", ""]
    for event in pending:
        summary = (
            event.summary if isinstance(event.summary, str) and event.summary else "(no summary)"
        )
        lines.append(f"- `{event.id}` {event.kind or 'event'}: {summary}")
    if warnings:
        lines.extend(["", f"Warnings ({len(warnings)}):", ""])
        lines.extend(f"- {diag.render()}" for diag in warnings)
    return "\n".join(lines) + "\n"


def _publish_pr(base_dir: Path, pending: list[EventFile], warnings: list[Diag]) -> None:
    body = _pr_body(pending, warnings)
    url = _remote_url(base_dir)
    slug = _github_slug(url)
    gh = _gh_on_path()
    if gh is None or slug is None:
        print(
            f"forge CLI not available for this remote: open the pull request from {PENDING_BRANCH} to {MAIN_BRANCH} at {_compare_url(url, slug)}"
        )
        return
    existing = _gh_pr_list(gh, slug)
    if existing:
        number, pr_url = existing
        _gh_run(gh, ["pr", "edit", str(number), "--repo", slug, "--body-file", "-"], body)
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
                PENDING_BRANCH,
                "--base",
                MAIN_BRANCH,
                "--title",
                PR_TITLE,
                "--body-file",
                "-",
            ],
            body,
        )
        print(f"opened PR {pr_url or '(forge CLI returned no url)'}")


def _close_pr(base_dir: Path) -> None:
    gh = _gh_on_path()
    if gh is None:
        print(
            f"note: forge CLI (gh) not available; an open pull request from {PENDING_BRANCH} could not be looked up or closed"
        )
        return
    try:
        slug = _github_slug(_remote_url(base_dir))
    except SyncError:
        slug = None
    if slug is None:
        print(
            f"note: remote is not GitHub; an open pull request from {PENDING_BRANCH} could not be looked up or closed"
        )
        return
    existing = _gh_pr_list(gh, slug)
    if existing is None:
        return
    if existing:
        number, pr_url = existing
        proc = subprocess.run(
            [gh, "pr", "close", str(number), "--repo", slug],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            print(f"closed PR {pr_url}")
        else:
            print(f"note: could not close PR {pr_url}: {proc.stderr.strip()}")


def _gh_pr_list(gh: str, slug: str) -> tuple[int, str] | None:
    proc = subprocess.run(
        [
            gh,
            "pr",
            "list",
            "--repo",
            slug,
            "--head",
            PENDING_BRANCH,
            "--state",
            "open",
            "--json",
            "number,url",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"note: could not list open pull requests ({proc.stderr.strip()})")
        return None
    items = json.loads(proc.stdout or "[]")
    return (items[0]["number"], items[0]["url"]) if items else None


def _gh_run(gh: str, args: list[str], body: str) -> str:
    proc = subprocess.run([gh, *args], input=body, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"note: gh {' '.join(args[:2])} failed: {proc.stderr.strip()}")
        return ""
    return proc.stdout.strip()


def _gh_on_path() -> str | None:
    return shutil.which("gh")


def _compare_url(url: str, slug: str | None) -> str:
    if slug:
        return f"https://github.com/{slug}/compare/{MAIN_BRANCH}...{PENDING_BRANCH}?expand=1"
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
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "remote", "get-url", REMOTE],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
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
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "fetch", REMOTE, "--prune"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    if proc.returncode != 0:
        raise SyncError(Diag("error", E_GIT, f"git fetch {REMOTE} failed: {proc.stderr.strip()}"))


def _origin_main(base_dir: Path) -> str:
    proc = subprocess.run(
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
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "merge-base", "HEAD", f"refs/remotes/{REMOTE}/{MAIN_BRANCH}"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
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
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "rev-parse", "--verify", rev],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _head_branch(base_dir: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _git(base_dir: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(base_dir), *args],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
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
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "show", rev],
        capture_output=True,
        check=False,
        env=git_env(),
    )
    return proc.stdout if proc.returncode == 0 else None


def _materialize(base_dir: Path, commit: str, dest: Path) -> None:
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "archive", "--format=tar", commit],
        capture_output=True,
        check=False,
        env=git_env(),
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise SyncError(Diag("error", E_GIT, f"git archive {commit[:12]} failed: {stderr}"))
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        tar.extractall(dest, filter="data")


def _commit_tree(base_dir: Path, work_tree: Path, parent: str) -> tuple[str, str]:
    git_dir = _git(base_dir, "rev-parse", "--absolute-git-dir")
    with tempfile.TemporaryDirectory() as tmp:
        env = git_env() | {
            "GIT_DIR": git_dir,
            "GIT_WORK_TREE": str(work_tree),
            "GIT_INDEX_FILE": str(Path(tmp) / "index"),
        }

        def _plumb(*args: str) -> str:
            proc = subprocess.run(
                ["git", *args], cwd=work_tree, env=env, capture_output=True, text=True, check=False
            )
            if proc.returncode != 0:
                raise SyncError(
                    Diag("error", E_GIT, f"git {' '.join(args)} failed: {proc.stderr.strip()}")
                )
            return proc.stdout.strip()

        _plumb("read-tree", "--empty")
        _plumb("add", "-A")
        tree = _plumb("write-tree")
        return _plumb("commit-tree", tree, "-p", parent, "-m", COMMIT_MESSAGE), tree
