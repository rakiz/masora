"""`masora doctor`: report-only health checks for the tool and its environment.

Every check prints one OK / WARN / FAIL line with a concrete remedy and
NOTHING is ever mutated (the CLI is the fix, never the doctor). Exit 0 when
no FAIL, 1 when any FAIL fires; WARNs never fail. The only network access is
the read-only `git fetch origin` of each configured base — every spawn goes
through `sync.run_git`/`sync.git_env` with the M4 timeouts. The gh auth check
and the base fetch are injectable module-level callables so tests stay
hermetic (the same seam idiom as `status.fetch_latest_release`).
"""

from __future__ import annotations

import shutil
import sqlite3
import tomllib
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from . import config, providers
from .index import (
    SCHEMA_VERSION,
    _stored_meta,
    index_db_path,
    index_dir_for,
    index_stale_reason,
)
from .schema import SUPPORTED_FORMAT_VERSION
from .status import installed_version
from .sync import (
    FETCH_TIMEOUT_S,
    GH_TIMEOUT_S,
    REMOTE,
    git_env,
    run_git,
)

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

GhCheck = Callable[[], tuple[bool, bool, str]]
BaseFetch = Callable[[Path], tuple[bool, str]]


def _gh_status() -> tuple[bool, bool, str]:
    """(present, authenticated, detail) from `gh auth status` — report-only."""
    gh = shutil.which("gh")
    if gh is None:
        return False, False, "gh is not on PATH"
    proc = run_git(
        [gh, "auth", "status"],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_S,
        env=git_env(),
    )
    if proc is None:
        return True, False, "gh auth status timed out"
    if proc.returncode != 0:
        return True, False, proc.stderr.strip() or "gh is not authenticated"
    return True, True, "authenticated"


def _fetch_origin(clone: Path) -> tuple[bool, str]:
    """The read-only `git fetch origin` of one base clone — the doctor's only
    network operation; (ok, stderr) so a failure can FAIL with the exit message."""
    proc = run_git(
        ["git", "-C", str(clone), "fetch", REMOTE, "--prune"],
        capture_output=True,
        text=True,
        timeout=FETCH_TIMEOUT_S,
        env=git_env(),
    )
    if proc is None or proc.returncode != 0:
        reason = "timed out" if proc is None else proc.stderr.strip()
        return False, reason
    return True, ""


def run(gh_checker: GhCheck | None = None, fetcher: BaseFetch | None = None) -> int:
    gh_check = _gh_status if gh_checker is None else gh_checker
    fetch = _fetch_origin if fetcher is None else fetcher
    failed = 0
    failed += _check_tool()
    failed += _check_git_identity()
    failed += _check_gh(gh_check)
    data, config_failed = _load_config()
    failed += config_failed
    bases = _configured_bases(data)
    for name, entry, base_dir in bases:
        failed += _check_base(name, entry, base_dir, fetch)
        failed += _check_base_indexes(base_dir)
    repos = _known_repos(bases)
    for base_dir, repo in repos:
        failed += _check_indexes(base_dir, repo)
        failed += _check_graph(repo)
    if not bases:
        print("bases: none configured — masora setup --base <url> (nothing to check)")
    print(f"doctor: {'FAIL' if failed else 'OK'} — {failed} failing check(s)")
    return 1 if failed else 0


def _report(state: str, message: str, remedy: str | None = None) -> int:
    print(f"{state}: {message}")
    if remedy is not None:
        print(f"  remedy: {remedy}")
    return 1 if state == FAIL else 0


def _check_tool() -> int:
    version = installed_version()
    print("masora doctor")
    _report(
        OK,
        f"masora {version} (format_version {SUPPORTED_FORMAT_VERSION},"
        f" index schema_version {SCHEMA_VERSION})",
    )
    return 0


def _load_config() -> tuple[dict, int]:
    path = config.config_path()
    if not path.is_file():
        return {}, _report(
            WARN,
            f"no masora config at {path}",
            "run masora setup --base <url> in a code checkout to create it",
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        return {}, _report(
            FAIL, f"the config at {path} cannot be parsed: {exc}", f"fix or remove {path}"
        )
    _report(OK, f"config found and parsed: {path}")
    return data if isinstance(data, dict) else {}, 0


def _configured_bases(data: dict) -> list[tuple[str, dict, Path]]:
    bases = data.get("bases")
    if not isinstance(bases, dict):
        return []
    entries = []
    for name in sorted(bases):
        entry = bases[name]
        if not isinstance(entry, dict):
            continue
        base_dir = config.bases_root() / config.slug(name)
        sub = entry.get("path")
        if isinstance(sub, str) and sub:
            base_dir = base_dir / sub
        entries.append((name, entry, base_dir))
    return entries


def _check_git_identity() -> int:
    failed = 0
    for key in ("user.name", "user.email"):
        proc = run_git(
            ["git", "config", "--get", key],
            capture_output=True,
            text=True,
            env=git_env(),
        )
        value = proc.stdout.strip() if proc is not None else ""
        if value:
            _report(OK, f"git {key}: {value}")
        else:
            failed += _report(
                FAIL,
                f"git {key} is not set — masora init and sync commits need it",
                f"git config --global {key} '<your value>'",
            )
    return failed


def _check_base(name: str, entry: dict, base_dir: Path, fetch: BaseFetch) -> int:
    failed = 0
    print(f"base {name}: {base_dir}")
    if not base_dir.is_dir():
        return _report(
            FAIL,
            "the base clone directory is missing",
            "run masora setup --base <url> to (re)clone it",
        )
    base_toml = base_dir / "base.toml"
    try:
        tomllib.loads(base_toml.read_text(encoding="utf-8"))
        _report(OK, "base.toml found and parsed")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        failed += _report(FAIL, f"base.toml cannot be read: {exc}", f"fix or restore {base_toml}")
    proc = run_git(
        ["git", "-C", str(base_dir), "remote", "get-url", REMOTE],
        capture_output=True,
        text=True,
        env=git_env(),
    )
    origin = proc.stdout.strip() if proc is not None and proc.returncode == 0 else ""
    wanted = entry.get("remote")
    if not origin:
        failed += _report(
            FAIL,
            f"no '{REMOTE}' remote in the clone",
            f"git -C {base_dir} remote add {REMOTE} <url>",
        )
    elif isinstance(wanted, str) and config.normalize_remote(origin) != config.normalize_remote(
        wanted
    ):
        failed += _report(
            FAIL,
            f"the clone's {REMOTE} remote {origin!r} does not match the configured remote"
            f" {wanted!r}",
            "re-run masora setup --base <url> or fix the remote in config.toml",
        )
    else:
        _report(OK, f"{REMOTE} remote matches the configuration: {origin}")
    ok, detail = fetch(base_dir)
    if ok:
        _report(OK, f"git fetch {REMOTE} succeeded")
    else:
        failed += _report(
            FAIL,
            f"git fetch {REMOTE} failed: {detail}",
            "fix the network/credentials and re-run masora doctor",
        )
    return failed


def _check_gh(gh_check: GhCheck) -> int:
    present, authenticated, detail = gh_check()
    if not present:
        return _report(
            WARN,
            f"gh CLI is not available ({detail}) — gh is optional: PR publication falls"
            " back to the compare URL",
            "install the GitHub CLI (https://cli.github.com) if you want automatic PRs",
        )
    if not authenticated:
        return _report(WARN, f"gh is present but not authenticated ({detail})", "run gh auth login")
    return _report(OK, f"gh CLI: {detail}")


def _known_repos(bases: list[tuple[str, dict, Path]]) -> list[tuple[Path, Path]]:
    """The distinct (base_dir, code repo) pairs known to the config or an index."""
    pairs: list[tuple[Path, Path]] = []
    seen: set[tuple[str, str]] = set()
    for _name, _entry, base_dir in bases:
        if not base_dir.is_dir():
            continue
        repos: list[Path] = []
        index_dir = index_dir_for(base_dir)
        if index_dir.is_dir():
            for db in sorted(index_dir.glob("*.db")):
                meta = _stored_meta(db)
                repo_path = meta.get("repo_path") or ""
                if repo_path:
                    repos.append(Path(repo_path))
        for repo in repos:
            key = (str(base_dir.resolve()), str(repo))
            if key not in seen:
                seen.add(key)
                pairs.append((base_dir, repo))
    return pairs


def _check_base_indexes(base_dir: Path) -> int:
    """The base-level index overview: a base with NO index at all is a WARN
    (the index is a disposable cache, never an error) — the per (base, repo)
    checks below only run for repos a stored index meta knows."""
    if not base_dir.is_dir():
        return 0
    index_dir = index_dir_for(base_dir)
    if index_dir.is_dir() and any(index_dir.glob("*.db")):
        return 0
    return _report(
        WARN,
        f"index for {base_dir}: missing",
        "masora index <base-dir> --repo <code-checkout>",
    )


def _check_indexes(base_dir: Path, repo: Path) -> int:
    db = index_db_path(base_dir, repo)
    label = f"index for {base_dir} x {repo}"
    if not db.is_file():
        return _report(
            WARN,
            f"{label}: missing",
            f"masora index {base_dir} --repo {repo}",
        )
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM meta")
        conn.close()
    except sqlite3.Error as exc:
        return _report(
            WARN,
            f"{label}: unreadable ({exc}) — the index is disposable",
            f"masora index {base_dir} --repo {repo}",
        )
    reason = index_stale_reason(db, base_dir, repo)
    if reason is None:
        return _report(OK, f"{label}: fresh")
    return _report(
        WARN,
        f"{label}: {reason}",
        f"masora index {base_dir} --repo {repo}",
    )


def _check_graph(repo: Path) -> int:
    graph_dir = repo / ".cppgraph"
    if not graph_dir.is_dir():
        return _report(
            WARN,
            f"no cppgraph graph store at {graph_dir} — code anchors report unknown"
            " (cppgraph is optional)",
            "re-index the code repo with cppgraph",
        )
    head = providers.repo_head(repo)
    graph_db = providers.discover_graph_db(repo)
    if graph_db is None:
        return _report(
            WARN,
            f"no graph.db under {graph_dir} — code anchors report unknown",
            "re-index the code repo with cppgraph",
        )
    handle = providers.open_graph(graph_db)
    if handle is None:
        return _report(
            WARN,
            f"the graph store {graph_db} is unreadable — code anchors report unknown",
            "re-index the code repo with cppgraph",
        )
    source_commit = handle.source_commit
    handle.conn.close()
    if head is not None and source_commit and source_commit != head:
        return _report(
            WARN,
            f"the graph store {graph_db} is indexed at {source_commit[:12]} but the repo"
            f" HEAD is {head[:12]} — code anchors report unknown",
            "re-index the code repo with cppgraph",
        )
    return _report(OK, f"cppgraph graph store {graph_db} is current with HEAD")
