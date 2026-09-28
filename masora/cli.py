"""`masora` CLI — Phase 1 implements the `check` and `sync` commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checker import check_base
from .sync import run as run_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="masora",
        description="Masora: git-backed knowledge base of anchored claims. Phase 1 provides `check` and `sync`.",
    )
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
    args = parser.parse_args(argv)

    if args.command == "check":
        return _run_check(args.base_dir)
    if args.command == "sync":
        if args.drop and args.push:
            sync.error("--drop and --push are mutually exclusive")
        return run_sync(args.base_dir, drop=args.drop, push=args.push)
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
        print(f"  verification: verified by {verification['id']} (actor: {verification['actor']})")
    else:
        print("  verification: unverified")
    print(f"  actors: {', '.join(envelope['actors']) or 'none'}")
    print(f"  doubted: {'yes' if envelope['doubted'] else 'no'}")
    if envelope["proof_replay"]:
        print(f"  proof replay: {envelope['proof_replay']} (provider not wired)")
