"""`masora facts`: the cppgraph injection contract as a read-only CLI (docs/CPPGRAPH_INTEGRATION.md).

Resolves the base from the user config for `--repo` (mappings on the
normalized `origin` remote, then `default_base` — MASORA_DESIGN.md §9), reads
the existing per-checkout index and prints ONE compact JSON document on
stdout. Strictly read-only: no index build, no git network access, nothing
written. `--symbol` filters to lineages whose effective version anchors on
that exact SCIP identity — the displayed version, or the NEWEST version when
the displayed one is null (`resolution: none`, FORMAT.md §6 folding); for
those lineages `anchors_matched` lists the matched identities, and facts are
empty-matched and skipped when they don't anchor the symbol. Hard failures
exit 1 with a diagnostic on stderr and nothing on stdout; the two warning
classes are in-band and never errors: `stale_warning` (index drift,
W-IDX-STALE semantics) and per-lineage `unknown` flags (W-IDX-GRAPH
semantics).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import providers
from .diagnostics import E_FACTS_NO_BASE, E_FACTS_NOINDEX, E_IDX_REPO, Diag
from .index import IndexingError, _open_index, index_db_path, index_stale
from .write import WriteError, auto_base

CONTRACT_VERSION = 1
_FLAG_NAMES = ("suspect", "doubted", "pending", "unknown", "unanchored")


class FactsError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


def run(repo: Path, symbol: str | None = None) -> int:
    try:
        document = _facts(repo, symbol)
    except FactsError as exc:
        print(f"  {exc.diag.render()}", file=sys.stderr)
        return 1
    print(json.dumps(document, separators=(",", ":"), ensure_ascii=False))
    return 0


def _flags(values: tuple[int, ...]) -> str:
    return ",".join(name for name, value in zip(_FLAG_NAMES, values) if value) or "-"


def _facts(repo: Path, symbol: str | None) -> dict:
    if not repo.is_dir():
        raise FactsError(
            Diag("error", E_IDX_REPO, f"--repo path is not an existing directory: {repo}")
        )
    try:
        base_dir = auto_base(repo)
    except WriteError as exc:
        raise FactsError(
            Diag("error", E_FACTS_NO_BASE, exc.diags[0].message, exc.diags[0].path)
        ) from exc
    if base_dir is None:
        raise FactsError(
            Diag(
                "error",
                E_FACTS_NO_BASE,
                f"no base resolved for {repo}: no [[mappings]] entry matches its origin remote and"
                " no default_base is configured — run masora setup --base <url> (MASORA_DESIGN.md §9)",
            )
        )
    db = index_db_path(base_dir, repo)
    if not db.is_file():
        raise FactsError(
            Diag(
                "error",
                E_FACTS_NOINDEX,
                f"no index at {db} — build it with masora index {base_dir} --repo {repo}"
                " (masora facts is read-only and never builds)",
            )
        )
    try:
        conn = _open_index(db)
    except IndexingError as exc:
        raise FactsError(exc.diag) from exc
    try:
        stale = index_stale(db, base_dir, repo)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        facts = []
        for row in conn.execute(
            "SELECT lineage, displayed, resolution, verification, suspect, doubted, pending,"
            " unknown, unanchored FROM lineages ORDER BY lineage"
        ).fetchall():
            lineage, displayed, resolution, verification, *flag_values = row
            effective = displayed
            if effective is None:
                newest = conn.execute(
                    "SELECT version FROM versions WHERE lineage = ? ORDER BY version DESC LIMIT 1",
                    (lineage,),
                ).fetchone()
                effective = newest[0] if newest else None
            matched: list[str] = []
            summary = ""
            if effective is not None:
                found = conn.execute(
                    "SELECT summary FROM versions WHERE version = ?", (effective,)
                ).fetchone()
                summary = (found[0] if found and found[0] else "")[:120]
                if symbol is not None:
                    matched = [
                        identity[0]
                        for identity in conn.execute(
                            "SELECT identity FROM anchors WHERE version = ? AND identity = ?",
                            (effective, symbol),
                        )
                    ]
            if symbol is not None and not matched:
                continue
            facts.append(
                {
                    "lineage": lineage,
                    "summary": summary,
                    "resolution": resolution,
                    "verification": verification,
                    "flags": _flags(tuple(flag_values)),
                    "anchors_matched": matched,
                }
            )
    finally:
        conn.close()
    return {
        "contract_version": CONTRACT_VERSION,
        "repo_head": providers.repo_head(repo),
        "graph_commit": meta.get("graph_commit") or None,
        "stale_warning": stale,
        "facts": facts,
    }
