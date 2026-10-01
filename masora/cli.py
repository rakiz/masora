"""`masora` CLI — the Masora commands (each subparser below carries its contract in --help)."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .checker import check_base
from .compact import run as run_compact
from .diagnostics import E_IDX_QUERY, E_NOT_A_BASE, E_SEARCH_NO_BASE, W_IDX_STALE, Diag
from .explain import ExplainError, explain_lineage
from .facts import run as run_facts
from .gc import run as run_gc
from .index import (
    IndexingError,
    build_index,
    index_db_path,
    index_stale_reason,
    search_index,
)
from .init import run as run_init
from .mcp import PROTOCOL_VERSION
from .mcp import serve as run_mcp
from .setup import run as run_setup
from .skill import run as run_skill
from .status import installed_version
from .status import run as run_status
from .sync import run as run_sync
from .write import WriteError, auto_base, origin_state

BASE_COMMANDS = ("check", "gc", "compact", "index", "search", "explain")


def _configured_base_hint() -> Path | None:
    """The base configured for the current repo's origin remote, when resolvable."""
    try:
        return auto_base(Path.cwd())
    except (WriteError, OSError):
        return None


def _base_gate(base_dir: Path) -> bool:
    """Refuse a non-base root up front with E-NOT-A-BASE plus the configured-base
    remedy for this repo's remote; the commands never auto-correct."""
    if not base_dir.is_dir() or (base_dir / "base.toml").is_file():
        return True
    print(f"  {Diag('error', E_NOT_A_BASE, f'not a base: no base.toml at {base_dir}').render()}")
    hint = _configured_base_hint()
    if hint is not None:
        print(f"the base configured for this repo: {hint}")
    print("FAILED: 1 error(s)")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="masora",
        description="Masora: git-backed knowledge base of anchored claims. Phase 1 provides `check`, `sync`, `setup` and `gc`.",
    )
    parser.add_argument("--version", action="version", version=f"masora {installed_version()}")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser(
        "check",
        help="validate a base (whole-tree self-consistency per FORMAT.md §7)",
        description="Exit codes: 0 clean, 1 errors, 2 warnings only. Standalone mode: schema, uniqueness, tombstones and fold validity; no anchor provider, no append-only diff (that is `sync`).",
    )
    check.add_argument("base_dir", type=Path, help="path to the Masora base directory")
    sync = sub.add_parser(
        "sync",
        help="publish pending events as one branch and one PR (MASORA_DESIGN.md §8)",
        description="Exit codes: 0 synced, 1 errors, 2 synced with warnings. Runs the local check gate, the append-only content diff against origin/main (FORMAT.md §7.9-§7.10) and merged-result validation, then commits the pending set on masora/pending, pushes it and opens or updates the single PR. --push pushes the merged result directly to origin/main (solo base). --drop discards the pending set.",
    )
    sync.add_argument(
        "base_dir",
        type=Path,
        nargs="?",
        default=Path("."),
        help="path to the Masora base directory (default: current directory)",
    )
    sync.add_argument(
        "--drop",
        action="store_true",
        help="discard the pending set: reset masora/pending to origin/main and delete the remote branch",
    )
    sync.add_argument(
        "--push",
        action="store_true",
        help="solo-base mode: push the merged result directly to origin/main instead of a pending branch and PR",
    )
    sync.add_argument(
        "--allow-stacked",
        action="store_true",
        help="publish flagged block claims anyway, per-lineage warning",
    )
    init = sub.add_parser(
        "init",
        help="create a new Masora base locally (MASORA_DESIGN.md §9)",
        description="Exit codes: 0 created, 1 errors. Creates the directory, runs git init"
        " (branch main), writes base.toml (name + the code remotes it serves, stored"
        " normalized and deduplicated) and commits it ('masora init: base <name>'). A"
        " non-empty target directory is refused unless --force; a directory that already"
        " holds base.toml is always refused. The fresh tree must pass masora check before"
        " the commit. init works locally — publishing the base to a shared repo is your"
        " git work; masora setup --base <url> onboards contributors once pushed.",
    )
    init.add_argument(
        "base_dir",
        type=Path,
        nargs="?",
        default=None,
        help="path of the base directory to create (omit when using --here)",
    )
    init.add_argument(
        "--name",
        required=True,
        metavar="NAME",
        help="display name recorded in base.toml (non-empty)",
    )
    init.add_argument(
        "--code-remote",
        action="append",
        default=None,
        metavar="URL",
        help="git remote of a code repo this base will serve; repeatable, stored"
        " normalized and deduplicated (same normalization as the config [[mappings]])",
    )
    init.add_argument(
        "--here",
        action="store_true",
        help="create the base in the current directory instead of a named path",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="create the base inside a non-empty directory (base.toml present is still refused)",
    )
    setup = sub.add_parser(
        "setup",
        help="configure a base from its own base.toml (MASORA_DESIGN.md §9)",
        description="Clones the base into ~/.local/share/masora/bases/<name> (partial clone + sparse checkout at #<path>), reads its base.toml and writes or merges the local config.toml: a [bases.<name>] entry plus one [[mappings]] block per code remote it serves.",
    )
    setup.add_argument(
        "--base",
        required=True,
        metavar="URL[#PATH]",
        help="git URL of the base; '#<path>' selects a sub-directory of a shared repo (sparse checkout)",
    )
    gc = sub.add_parser(
        "gc",
        help="delete whole lineages on explicit, confirmed request (FORMAT.md §7.10)",
        description="Exit codes: 3 plan printed (nothing written), 0 deleted, 2 deleted with warnings, 1 errors. Runs masora check before and after the mutation, removes every event file of the requested lineage(s) and appends their tombstone to deleted.toml. gc never suggests lineages.",
    )
    gc.add_argument("base_dir", type=Path, help="path to the Masora base directory")
    gc.add_argument(
        "--lineage",
        action="append",
        required=True,
        metavar="ULID",
        help="lineage ULID to delete; repeatable to delete several lineages in one run",
    )
    gc.add_argument(
        "--yes",
        action="store_true",
        help="execute the deletion; without it gc prints the plan only and exits 3",
    )
    compact = sub.add_parser(
        "compact",
        help="compress every lineage to its minimal live witness set (FORMAT.md §6, §7.10)",
        description="Exit codes: 3 plan printed (nothing written), 0 compacted, 2 compacted"
        " with warnings, 1 errors. Per lineage, keeps only the event files still"
        " contributing to the current fold state (MASORA_DESIGN.md §6.2) and drops pure"
        " history; the per-lineage proof fold(witness) == fold(full lineage) refuses any"
        " diverging lineage fail-closed (E-COMPACT-DIVERGE). Surviving files keep their"
        " ULIDs and bytes. Dropped events known to the shared repo (present on"
        " origin/main or the sync merge-base) are tombstoned per-event in the"
        " [[deleted_events]] table of deleted.toml; unpublished events are dropped"
        " silently. Runs masora check before and after the mutation. --rehome"
        " additionally moves the surviving files into each lineage's canonical single"
        " home YYYY-MM/<slug>-<lineage> (FORMAT.md §1), merging split month buckets —"
        " a pure directory migration, no tombstones for moved files.",
    )
    compact.add_argument("base_dir", type=Path, help="path to the Masora base directory")
    compact.add_argument(
        "--yes",
        action="store_true",
        help="execute the compaction; without it compact prints the plan only and exits 3",
    )
    compact.add_argument(
        "--rehome",
        action="store_true",
        help="migrate the layout: move every surviving file into its lineage's canonical"
        " single home (the founder's month, <slug>-<lineage>), merging split month"
        " buckets; moved files keep their ULIDs and bytes",
    )
    index = sub.add_parser(
        "index",
        help="rebuild the SQLite index of a base for one code repo (MASORA_DESIGN.md §6.2, §8)",
        description="Exit codes: 0 built, 1 errors, 2 built with warnings. Full rebuild only — the index is disposable (drop + recreate), tombstoned lineages are excluded. The default registry ships the `file` anchor provider plus the `code` provider over a cppgraph graph store (auto-discovered at <repo>/.cppgraph, newest graph.db); `--cppgraph` points elsewhere, `--no-cppgraph` forces file-only (code anchors report unknown).",
    )
    index.add_argument("base_dir", type=Path, help="path to the Masora base directory")
    index.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="path to the code repo checkout the fingerprints are computed against (default: current directory)",
    )
    index.add_argument(
        "--cppgraph",
        type=Path,
        default=None,
        metavar="DB",
        help="explicit cppgraph graph.db to fingerprint code anchors against (default: newest <repo>/.cppgraph/*.graph.db)",
    )
    index.add_argument(
        "--no-cppgraph",
        action="store_true",
        help="force file-only indexing: code anchors report unknown even when a graph store exists",
    )
    search = sub.add_parser(
        "search",
        help="run the FTS query over a built index and render status tuples (MASORA_DESIGN.md §6.2)",
        description="Exit codes: 0 results or no match, 1 errors (no/unusable index), 2 invalid query syntax."
        " The `*` query enumerates every indexed lineage."
        " Prints W-IDX-STALE when the base or code state moved since the build, or events were written after it.",
    )
    search.add_argument(
        "base_dir",
        type=Path,
        nargs="?",
        default=None,
        help="path to the Masora base directory (omitted: resolved from the user config for"
        " --repo — mappings on the normalized origin remote, then default_base)",
    )
    search.add_argument(
        "query",
        help="FTS MATCH query over summaries and statements ('*' enumerates every indexed lineage)",
    )
    search.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="path to the code repo the index was built for (default: current directory)",
    )
    explain = sub.add_parser(
        "explain",
        help="the complete story of ONE lineage, statuses included (fresh fold, never the index)",
        description="Exit codes: 0 explained, 1 errors (unknown lineage E-EXPLAIN-UNKNOWN, a"
        " non-base root E-NOT-A-BASE, a broken base's own errors). Renders the fresh status"
        " tuple, the effective version's summary/statement/questions, the anchors with their"
        " current match state (unknown without --repo), the full event chain in ULID order and"
        " the active verify's evidence in full. Nothing is written, ever.",
    )
    explain.add_argument("base_dir", type=Path, help="path to the Masora base directory")
    explain.add_argument(
        "lineage_id", help="the lineage ULID (a claim whose id equals its lineage)"
    )
    explain.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="path to the code repo checkout the anchors are matched against (default: no"
        " provider — anchor states report unknown)",
    )
    sub.add_parser(
        "mcp",
        help="run the MCP stdio server (MASORA_DESIGN.md §10.4)",
        description="Hand-rolled minimal MCP server over stdio: newline-delimited JSON-RPC 2.0,"
        f" protocol version {PROTOCOL_VERSION} (negotiated: the result always carries it), tools only — note, verify,"
        " doubt, undoubt, refute, search, list_stale. Responses go to stdout; protocol anomalies"
        " to stderr (W-MCP-PROTO); the loop survives malformed input.",
    )
    facts = sub.add_parser(
        "facts",
        help="emit the cppgraph injection facts document (docs/CPPGRAPH_INTEGRATION.md)",
        description="Read-only: resolves the base from the user config for --repo (mappings on the"
        " normalized origin remote, then default_base) and prints ONE compact JSON document per"
        " docs/CPPGRAPH_INTEGRATION.md §3. Exit 0 with facts — possibly empty — the two warning"
        " classes in-band (stale_warning, per-lineage unknown flags); exit 1 on hard failure"
        " (diagnostic on stderr, nothing on stdout). Never builds the index, never touches the"
        " network.",
    )
    facts.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="path to the code repo checkout the facts are resolved for",
    )
    facts.add_argument(
        "--symbol",
        default=None,
        metavar="SCIP",
        help="exact SCIP symbol string; only lineages whose displayed version (or newest version"
        " for resolution none) anchors on it are returned",
    )
    status = sub.add_parser(
        "status",
        help="one readable screen: tool versions, configured bases, index drift, release check",
        description="Exit 0 — status never fails hard: an offline or failed release check is a"
        " one-line note, a missing clone or unreadable config is reported as-is. The release"
        " check hits the GitHub releases API (2 s timeout), is cached in"
        " MASORA_HOME/update-check.json for 24 hours and compares the semver triplet"
        " numerically; --force refetches now.",
    )
    status.add_argument(
        "--force",
        action="store_true",
        help="refetch the release check now, bypassing the 24 h cache",
    )
    skill = sub.add_parser(
        "skill",
        help="install or print the packaged masora agent skill",
        description="install: write the packaged SKILL.md into every detected agent-framework"
        " skills dir (~/.claude, ~/.config/opencode — other frameworks are skipped silently),"
        " creating the target dirs and overwriting on re-run (that is the update path);"
        " print: the packaged content to stdout for any other mechanism. Copy-install only —"
        " masora never writes into a code repo.",
    )
    skill.add_argument(
        "action",
        choices=["install", "print"],
        help="install: write into every detected agent-framework skills dir; print: the"
        " packaged content to stdout",
    )
    args = parser.parse_args(argv)

    if (
        args.command in BASE_COMMANDS
        and args.base_dir is not None
        and not _base_gate(args.base_dir)
    ):
        return 1

    if args.command == "check":
        return _run_check(args.base_dir)
    if args.command == "sync":
        if args.drop and args.push:
            sync.error("--drop and --push are mutually exclusive")
        return run_sync(
            args.base_dir, drop=args.drop, push=args.push, allow_stacked=args.allow_stacked
        )
    if args.command == "setup":
        return run_setup(args.base)
    if args.command == "init":
        return run_init(
            args.base_dir,
            args.name,
            code_remotes=args.code_remote,
            here=args.here,
            force=args.force,
        )
    if args.command == "gc":
        return run_gc(args.base_dir, args.lineage, yes=args.yes)
    if args.command == "compact":
        return run_compact(args.base_dir, yes=args.yes, rehome=args.rehome)
    if args.command == "index":
        return _run_index(args.base_dir, args.repo, args.cppgraph, args.no_cppgraph)
    if args.command == "search":
        return _run_search(args.base_dir, args.query, args.repo)
    if args.command == "explain":
        return _run_explain(args.base_dir, args.lineage_id, args.repo)
    if args.command == "mcp":
        return run_mcp()
    if args.command == "facts":
        return run_facts(args.repo, symbol=args.symbol)
    if args.command == "status":
        return run_status(force=args.force)
    if args.command == "skill":
        return run_skill(args.action)
    return 2


def _run_check(base_dir: Path) -> int:
    if not base_dir.is_dir():
        print(f"masora check: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    result = check_base(base_dir)
    print(f"masora check {base_dir}")
    print(f"scanned {result.file_count} event file(s), {result.lineage_count} lineage(s)")
    print(
        "standalone mode: no anchor provider wired — fingerprint resolution is unknown; proof queries are validated, not replayed"
    )
    for diag in result.diags:
        print(f"  {diag.render()}")
    if not result.envelopes:
        print("no claim lineages found")
    for envelope in result.envelopes:
        _print_envelope(envelope)
    code = result.exit_code()
    if code == 0:
        print("clean: no errors, no warnings")
    elif code == 1:
        print(f"FAILED: {len(result.errors)} error(s)")
    else:
        print(f"PASSED WITH WARNINGS: {len(result.warnings)} warning(s)")
    return code


def _print_envelope(envelope: dict) -> None:
    print(f"claim {envelope['lineage']}")
    print(f"  displayed version: {envelope['displayed'] or 'none'}")
    print(
        f"  status: {envelope['status']}"
        + (" (restored: a newer version is refuted)" if envelope["restored"] else "")
    )
    for version in envelope["versions"]:
        state = "refuted" if version["refuted"] else "active"
        print(f"  version {version['id']}: {state}")
    verification = envelope["verification"]
    if verification["status"] == "verified":
        print(
            f"  verification: verified by {verification['id']} (source: {verification['source']})"
        )
    else:
        print("  verification: unverified")
    print(f"  sources: {', '.join(envelope['sources']) or 'none'}")
    print(f"  doubted: {'yes' if envelope['doubted'] else 'no'}")
    if envelope["proof_replay"]:
        print(f"  proof replay: {envelope['proof_replay']} (provider not wired)")


def _run_index(base_dir: Path, repo: Path, cppgraph: Path | None, no_cppgraph: bool) -> int:
    print(f"masora index {base_dir}")
    if not base_dir.is_dir():
        print(f"masora index: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    try:
        result = build_index(base_dir, repo, cppgraph=cppgraph, no_cppgraph=no_cppgraph)
    except IndexingError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    print(f"repo: {repo}")
    if result.graph_db is not None:
        print(f"graph: {result.graph_db} (commit {result.graph_commit[:12]})")
    else:
        print("graph: none — code anchors report unknown")
    print(f"index: {result.db_path}")
    print(f"base HEAD: {result.base_head or 'unknown'}")
    for diag in result.diags:
        print(f"  {diag.render()}")
    if result.errors:
        print(f"FAILED: {len(result.errors)} error(s)")
        return 1
    print(f"indexed: {result.lineage_count} lineage(s), {result.version_count} version(s)")
    counts = Counter(status.resolution for status in result.statuses)
    print(
        "status counts: "
        + " ".join(
            f"{key}={counts.get(key, 0)}"
            for key in ("current", "stale", "restored", "none", "unknown")
        )
    )
    print(
        "flags: "
        + " ".join(
            f"{flag}={sum(getattr(status, flag) for status in result.statuses)}"
            for flag in ("suspect", "doubted", "pending", "unanchored")
        )
    )
    return 2 if result.warnings else 0


def _no_base_message(repo: Path) -> str:
    """The cause-specific no-base refusal for `masora search` (same detection as `masora facts`;
    the remedies may also point at search's own explicit base_dir)."""
    kind, _remote = origin_state(repo)
    if kind == "not_git_worktree":
        return (
            f"no base resolved for {repo}: --repo is not a Git checkout — pass the code"
            " checkout itself (not its workspace parent), or pass the base directory"
            " explicitly"
        )
    if kind == "git_without_origin":
        return (
            f"no base resolved for {repo}: the checkout has no readable origin, so"
            " mapping-based resolution is unavailable — configure origin or configure"
            " default_base, or pass the base directory explicitly"
        )
    return (
        f"no base resolved for {repo}: no [[mappings]] entry matches its origin remote and"
        " no default_base is configured — run masora setup --base <url> in this checkout, or"
        " pass the base directory explicitly"
    )


def _run_search(base_dir: Path | None, query: str, repo: Path) -> int:
    if base_dir is None:
        try:
            base_dir = auto_base(repo)
        except WriteError as exc:
            diag = exc.diags[0]
            print(
                f"  {Diag('error', E_SEARCH_NO_BASE, diag.message, diag.path).render()}",
                file=sys.stderr,
            )
            return 1
        if base_dir is None:
            print(
                f"  {Diag('error', E_SEARCH_NO_BASE, _no_base_message(repo)).render()}",
                file=sys.stderr,
            )
            return 1
    print(f"masora search {base_dir}")
    if not base_dir.is_dir():
        print(f"masora search: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    db = index_db_path(base_dir, repo)
    try:
        hits = search_index(db, query)
    except IndexingError as exc:
        print(f"  {exc.diag.render()}")
        return 2 if exc.diag.code == E_IDX_QUERY else 1
    stale_reason = index_stale_reason(db, base_dir, repo)
    if stale_reason is not None:
        stale = Diag("warning", W_IDX_STALE, f"{stale_reason} — rerun masora index")
        print(f"  {stale.render()}")
    if not hits:
        print("no results")
        return 0
    grouped: dict[str, list] = {}
    for hit in hits:
        grouped.setdefault(hit.lineage, []).append(hit)
    print(f"{len(hits)} match(es) in {len(grouped)} lineage(s)")
    for lineage, group in grouped.items():
        first = group[0]
        print(f"{lineage} [{first.resolution} {first.verification} flags: {first.flags}]")
        for hit in group:
            print(f"  {hit.version} {hit.summary}")
            for question in hit.matched_questions:
                print(f"    matched question: {question}")
            for keyword in hit.matched_keywords:
                print(f"    matched keyword: {keyword}")
        print(f"details: masora explain {lineage}")
    return 0


def _run_explain(base_dir: Path, lineage_id: str, repo: Path | None) -> int:
    print(f"masora explain {base_dir} {lineage_id}")
    if not base_dir.is_dir():
        print(f"masora explain: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    try:
        block = explain_lineage(base_dir, lineage_id, repo)
    except ExplainError as exc:
        for diag in exc.diags:
            print(f"  {diag.render()}")
        print(f"FAILED: {len(exc.diags)} error(s)")
        return 1
    print(block)
    return 0
