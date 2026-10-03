"""`masora facts`: the cppgraph injection contract as a read-only CLI (docs/CPPGRAPH_INTEGRATION.md).

Resolves the base from the user config for `--repo` (mappings on the
normalized `origin` remote, then `default_base` — MASORA_DESIGN.md §9), reads
the existing per-checkout index and prints ONE compact JSON document on
stdout. Strictly read-only: no index build, no git network access, nothing
written. `--symbol` (repeatable) filters to lineages whose effective version
anchors on ANY of the passed SCIP identities — matched verbatim, the same
rule Masora's provider uses — the displayed version, or the NEWEST version
when the displayed one is null (`resolution: none`, FORMAT.md §6 folding);
for those lineages `anchors_matched` lists the matched identities, and facts
are empty-matched and skipped when they don't anchor any passed symbol. Each
fact also carries the effective version's provenance (`source`, `name`,
`effort`) and its FULL anchor-identity list (`anchors`).

Contract v2 stamps each fact with the git context Masora evaluated at index
build time (MASORA_DESIGN.md §6.2): `established_relation` (the DISPLAYED
version's relation — the contract enum `in_line | ahead | out_of_line |
unknown`, with the index's `relation_unknown` reported as `unknown`; null
when nothing displays or the context was unprovable), `established_commit`
(the displayed version's establishing commit, SHORT — presentation-only,
never a validity input), `off_version` (the lineage's fallback flag) and
`context_ordering` (`exact | degraded`). cppgraph RENDERS this context
(docs/CPPGRAPH_INTEGRATION.md §6) — it never computes ancestry and never
treats the stamps as validity.

Contract v3 adds, ADDITIVELY (shape change = version bump — no in-place
enrichment), the multi-symbol rendering inputs: each fact carries
`anchor_leaf` (the SHORT leaf of the first matched anchor identity — a
rendering input cppgraph's §6 multi-symbol rule consumes, derived by masora
because masora owns the identity format), and the document carries the
matching counters `lineages_examined` / `lineages_matched` plus the
`presence_hint` capability line (masora owns its wording so tool renames
never drift cppgraph's literals — docs/CPPGRAPH_INTEGRATION.md §6).

Hard failures exit 1 with a diagnostic on stderr and nothing on stdout; the
two warning classes are in-band and never errors: `stale_warning` (index
drift on four axes — base HEAD, code HEAD, graph indexed commit, and
filesystem freshness: events written after the build move no git HEAD —
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
from .write import WriteError, auto_base, origin_state

CONTRACT_VERSION = 3
# Rendered VERBATIM by cppgraph when zero facts render and zero lineages
# were examined (docs/CPPGRAPH_INTEGRATION.md §6): masora owns the wording so
# tool renames never drift cppgraph's literals.
PRESENCE_HINT = (
    "masora: present for this checkout — the masora search / explain /"
    " list_stale MCP tools recall recorded knowledge."
)
_FLAG_NAMES = ("suspect", "doubted", "pending", "unknown", "unanchored")
# The index's stored per-version relation (masora/index.py, §6.2) mapped onto
# the v2 contract enum: `relation_unknown` is reported as `unknown`; a NULL
# relation (unprovable context) stays null — both fire the rendering rule.
_RELATION_ENUM = {
    "in_line": "in_line",
    "ahead": "ahead",
    "out_of_line": "out_of_line",
    "relation_unknown": "unknown",
}


class FactsError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


def run(repo: Path, symbols: list[str] | None = None) -> int:
    try:
        document = _facts(repo, symbols)
    except FactsError as exc:
        print(f"  {exc.diag.render()}", file=sys.stderr)
        return 1
    print(json.dumps(document, separators=(",", ":"), ensure_ascii=False))
    return 0


def _flags(values: tuple[int, ...]) -> str:
    return ",".join(name for name, value in zip(_FLAG_NAMES, values) if value) or "-"


def _anchor_leaf(identity: str) -> str:
    # The SHORT leaf of an anchor identity: after the last `#` (the
    # disambiguation separator) or, when the identity has none, after the
    # last `/`; up to but excluding the `(` hash; a trailing `.` stripped.
    # Deterministic and masora-owned: masora owns the identity format
    # (docs/CPPGRAPH_INTEGRATION.md, the symbol identity section).
    head = identity.rsplit("#", 1)[1] if "#" in identity else identity.rsplit("/", 1)[-1]
    head = head.split("(", 1)[0]
    return head.removesuffix(".")


def _facts(repo: Path, symbols: list[str] | None) -> dict:
    # OR-matching over the repeatable --symbol: a lineage is included when
    # its effective version anchors on ANY passed identity; the matched
    # identities accumulate in anchors_matched (deduped, in call order).
    symbol_set = set(symbols) if symbols else None
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
        kind, _remote = origin_state(repo)
        if kind == "not_git_worktree":
            message = (
                f"no base resolved for {repo}: --repo is not a Git checkout — pass the code"
                " checkout itself (not its workspace parent)"
            )
        elif kind == "git_without_origin":
            message = (
                f"no base resolved for {repo}: the checkout has no readable origin, so"
                " mapping-based resolution is unavailable — configure origin or configure"
                " default_base"
            )
        else:
            message = (
                f"no base resolved for {repo}: no [[mappings]] entry matches its origin remote and"
                " no default_base is configured — run masora setup --base <url> (MASORA_DESIGN.md §9)"
            )
        raise FactsError(Diag("error", E_FACTS_NO_BASE, message))
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
        lineages_examined = 0
        for row in conn.execute(
            "SELECT lineage, displayed, resolution, verification, off_version,"
            " context_ordering, suspect, doubted, pending, unknown, unanchored"
            " FROM lineages ORDER BY lineage"
        ).fetchall():
            (
                lineage,
                displayed,
                resolution,
                verification,
                off_version,
                ordering,
                *flag_values,
            ) = row
            lineages_examined += 1
            effective = displayed
            if effective is None:
                newest = conn.execute(
                    "SELECT version FROM versions WHERE lineage = ? ORDER BY version DESC LIMIT 1",
                    (lineage,),
                ).fetchone()
                effective = newest[0] if newest else None
            matched: list[str] = []
            summary = ""
            source: str | None = None
            name: str | None = None
            effort: str | None = None
            anchor_identities: list[str] = []
            # The context stamps belong to the DISPLAYED version: a lineage
            # with nothing displayed (every version refuted) carries null
            # stamps even though its summary/anchors come from the newest
            # version (the effective-version rule above).
            established_relation: str | None = None
            established_commit: str | None = None
            if displayed is not None:
                stamped = conn.execute(
                    "SELECT relation, established_commit FROM versions WHERE version = ?",
                    (displayed,),
                ).fetchone()
                if stamped is not None:
                    established_relation = (
                        _RELATION_ENUM.get(stamped[0]) if stamped[0] is not None else None
                    )
                    # SHORT, presentation-only: cppgraph shows a pointer, it
                    # never re-derives ancestry from 12 hex chars.
                    established_commit = stamped[1][:12] if stamped[1] else None
            if effective is not None:
                found = conn.execute(
                    "SELECT summary, source, name, effort FROM versions WHERE version = ?",
                    (effective,),
                ).fetchone()
                if found is not None:
                    summary = (found[0] if found[0] else "")[:120]
                    source = found[1] or None
                    name = found[2]
                    effort = found[3]
                anchor_identities = [
                    identity[0]
                    for identity in conn.execute(
                        "SELECT identity FROM anchors WHERE version = ?", (effective,)
                    )
                ]
                if symbol_set is not None:
                    matched = list(dict.fromkeys(s for s in symbols if s in anchor_identities))
            if symbol_set is not None and not matched:
                continue
            # The leaf of the FIRST matched anchor (call order) — a rendering
            # input for cppgraph's multi-symbol responses; null when no
            # symbols were passed (the document is then symbol-unbound).
            anchor_leaf = _anchor_leaf(matched[0]) if matched else None
            facts.append(
                {
                    "lineage": lineage,
                    "summary": summary,
                    "resolution": resolution,
                    "verification": verification,
                    "flags": _flags(tuple(flag_values)),
                    "source": source,
                    "name": name,
                    "effort": effort,
                    "anchors": anchor_identities,
                    "anchors_matched": matched,
                    "anchor_leaf": anchor_leaf,
                    "established_relation": established_relation,
                    "established_commit": established_commit,
                    "off_version": bool(off_version),
                    "context_ordering": ordering,
                }
            )
    finally:
        conn.close()
    # The hint carries only the empty-and-unexamined case: with facts present
    # the response is already knowledge, and with examined-but-unmatched
    # lineages cppgraph derives its own staleness line from the counters
    # (docs/CPPGRAPH_INTEGRATION.md §6).
    presence_hint = PRESENCE_HINT if not facts and lineages_examined == 0 else None
    return {
        "contract_version": CONTRACT_VERSION,
        "repo_head": providers.repo_head(repo),
        "graph_commit": meta.get("graph_commit") or None,
        "stale_warning": stale,
        "lineages_examined": lineages_examined,
        "lineages_matched": len(facts),
        "presence_hint": presence_hint,
        "facts": facts,
    }
