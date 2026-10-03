"""`masora reset --from-origin`: the refoundation acceptance move.

INVARIANT (AUDIT.md operational risk 3): this command NEVER runs
automatically — nothing in `sync`, `index`, the MCP server or any hook may
call it; it exists only as an explicit, human-confirmed acceptance of an
out-of-band remote history rewrite. The command does NOT judge whether the
remote rewrite was a refoundation or an attack — tamper evidence stays
intact: it prints exactly what will be discarded (the local-only commits)
and refuses to act without `--yes`. The runbook is docs/REFOUNDATION.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .diagnostics import E_RESET_DIRTY, E_RESET_FETCH, E_RESET_NO_MAIN, Diag
from .sync import (
    FETCH_TIMEOUT_S,
    MAIN_BRANCH,
    REMOTE,
    git_env,
    run_git,
)

PLAN_EXIT = 3


def run(base_dir: Path, yes: bool = False) -> int:
    print(f"masora reset {base_dir} --from-origin")
    if not base_dir.is_dir():
        print(f"masora reset: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    if _dirty(base_dir):
        diag = Diag(
            "error",
            E_RESET_DIRTY,
            "the working tree is dirty — commit or discard the local changes first"
            " (a hard reset would silently destroy them)",
        )
        print(f"  {diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    proc = run_git(
        ["git", "-C", str(base_dir), "fetch", REMOTE, "--prune"],
        capture_output=True,
        text=True,
        timeout=FETCH_TIMEOUT_S,
        env=git_env(),
    )
    if proc is None or proc.returncode != 0:
        reason = "git timed out" if proc is None else proc.stderr.strip()
        diag = Diag("error", E_RESET_FETCH, f"git fetch {REMOTE} failed: {reason}")
        print(f"  {diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    origin_main = _rev(base_dir, f"refs/remotes/{REMOTE}/{MAIN_BRANCH}")
    if origin_main is None:
        diag = Diag(
            "error",
            E_RESET_NO_MAIN,
            f"{REMOTE}/{MAIN_BRANCH} does not exist after the fetch — there is nothing"
            " to reset to (the remote repository has no 'main' branch)",
        )
        print(f"  {diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    discarded = _local_only_commits(base_dir, origin_main)
    print(f"target: {REMOTE}/{MAIN_BRANCH} at {origin_main[:12]}")
    print(
        f"would reset the local '{MAIN_BRANCH}' branch to it (hard reset);"
        f" {len(discarded)} local-only commit(s) will be discarded:"
    )
    for sha, subject in discarded:
        print(f"  discard {sha[:12]} {subject}")
    if not discarded:
        print("  (no local-only commits — only the work tree and unpushed merges move)")
    print(
        "note: masora does not judge whether the remote history rewrite was a"
        " refoundation or an attack — verify that out-of-band before confirming"
        " (docs/REFOUNDATION.md)"
    )
    if not yes:
        print("plan only: nothing written — re-run with --yes to reset")
        return PLAN_EXIT
    if _current_branch(base_dir) == MAIN_BRANCH:
        reset = run_git(
            ["git", "-C", str(base_dir), "reset", "--hard", f"{REMOTE}/{MAIN_BRANCH}"],
            capture_output=True,
            text=True,
            env=git_env(),
        )
    else:
        # Detached HEAD or another branch checked out: move the main ref only
        # — the confirmation is about main's history, never the work tree.
        reset = run_git(
            ["git", "-C", str(base_dir), "update-ref", f"refs/heads/{MAIN_BRANCH}", origin_main],
            capture_output=True,
            text=True,
            env=git_env(),
        )
    if reset is None or reset.returncode != 0:
        reason = "git timed out" if reset is None else reset.stderr.strip()
        diag = Diag(
            "error",
            E_RESET_FETCH,
            f"git reset --hard {REMOTE}/{MAIN_BRANCH} failed: {reason}",
        )
        print(f"  {diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    print(f"reset: local '{MAIN_BRANCH}' is now at {origin_main[:12]}")
    print("next: rebuild the indexes (masora index) and re-run masora check")
    return 0


def _current_branch(base_dir: Path) -> str | None:
    proc = run_git(
        ["git", "-C", str(base_dir), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _dirty(base_dir: Path) -> bool:
    proc = run_git(
        ["git", "-C", str(base_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    if proc is None:
        return True
    return bool(proc.stdout.strip())


def _rev(base_dir: Path, rev: str) -> str | None:
    proc = run_git(
        ["git", "-C", str(base_dir), "rev-parse", "--verify", rev],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _local_only_commits(base_dir: Path, origin_main: str) -> list[tuple[str, str]]:
    """(sha, subject) of the commits on local main that origin/main lacks —
    the informed part of the confirmation."""
    proc = run_git(
        [
            "git",
            "-C",
            str(base_dir),
            "rev-list",
            "--oneline",
            f"{origin_main}..{MAIN_BRANCH}",
        ],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    if proc is None or proc.returncode != 0:
        return []
    entries = []
    for line in proc.stdout.splitlines():
        sha, _, subject = line.partition(" ")
        if sha:
            entries.append((sha, subject))
    return entries
