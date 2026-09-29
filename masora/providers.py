"""`code` anchor provider over a cppgraph graph store (FORMAT.md §4; MASORA_DESIGN.md §5.2, §5.4, §11, §12.4).

Reads the cppgraph SQLite index (`<repo>/.cppgraph/*.graph.db`, store schema v5:
`files`/`symbols`/`edges`/`meta`) read-only. The anchor identity is the SCIP
symbol string exactly as FORMAT.md records it (opaque-but-structured): matched
verbatim against `symbols.symbol`, never decomposed. Fingerprints per §5.2/§5.4:
definition = sha256 of the whitespace/comment-normalized source of the
definition range (`symbols.line`..`symbols.end_line` inclusive, 0-indexed; a
graph without body extents — stock binary, no `end_line` — hashes the single
definition line), edge set = sha256 of the sorted callee SCIP strings from
`calls` edges only. Neighbour snapshot per §12.4: 1-hop callers ∪ callees,
identity → that neighbour's edge-set hash.

Graph-behind-HEAD policy (§5.2 — the tool refuses fingerprints from a graph
behind HEAD): availability is decided once per index build in
`cppgraph_registry`, for ALL code anchors — the graph's recorded
`source_commit` must equal the `--repo` git HEAD. Not per-anchor, because the
registry contract has no per-anchor availability channel (a callable returning
None means `not_found`, which would guess `stale` instead of shadowing with
`unknown`) and §5.2 refuses a stale graph wholesale: re-index with cppgraph.
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .index import normalize_source
from .sync import git_env

SCHEMA_VERSION = 5


@dataclass(frozen=True)
class GraphHandle:
    """Read-only handle over one graph.db: provenance + provenance meta."""

    db: Path
    conn: sqlite3.Connection
    meta: dict[str, str]

    @property
    def source_commit(self) -> str | None:
        return self.meta.get("source_commit") or None


@dataclass(frozen=True)
class CppgraphRegistry:
    """The two `code` registry entries plus provenance (MASORA_DESIGN.md §5.2).

    `fingerprints`/`edges` are None when the provider is unavailable
    (`unknown` shadows, §6.2); `reason` states why — None when available or
    when the absence is deliberate/silent (no graph store, `no_cppgraph`).
    """

    fingerprints: Callable[[str, str], str | None] | None
    edges: Callable[[str, str], dict | None] | None
    db: Path | None
    graph_commit: str | None
    reason: str | None
    _handle: GraphHandle | None = None

    @property
    def available(self) -> bool:
        return self.fingerprints is not None

    def close(self) -> None:
        if self._handle is not None:
            self._handle.conn.close()


def discover_graph_db(repo: Path) -> Path | None:
    """Newest `*.graph.db` under `<repo>/.cppgraph/` (cppgraph's newest-wins rule).

    The repo directory itself is the anchor — never a parent walk — so a
    foreign graph cannot answer for this checkout.
    """
    cpg = repo / ".cppgraph"
    if not cpg.is_dir():
        return None
    graphs = sorted(cpg.glob("*.graph.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return graphs[0] if graphs else None


def repo_head(repo: Path) -> str | None:
    """`git rev-parse HEAD` over the sanitized git environment; None when not a checkout."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def open_graph(db: Path) -> GraphHandle | None:
    """Read-only handle, or None when the file is not a usable cppgraph store.

    Usable = readable as SQLite, carrying `symbols(symbol, file_id, line)`,
    `edges(kind, src_id, dst_id)` and `meta`; a store newer than
    SCHEMA_VERSION is refused (an old reader must not misread a new format,
    mirroring cppgraph's own `GraphStore._check_schema_compat`). `end_line`
    predates v3 and reads as NULL there (no body extent).
    """
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        conn.execute("SELECT symbol, file_id, line FROM symbols LIMIT 1").fetchone()
        conn.execute("SELECT kind, src_id, dst_id FROM edges LIMIT 1").fetchone()
    except sqlite3.Error:
        conn.close()
        return None
    raw = meta.get("schema_version")
    if raw is not None:
        try:
            version = int(raw)
        except ValueError:
            conn.close()
            return None
        if version > SCHEMA_VERSION:
            conn.close()
            return None
    return GraphHandle(db=db, conn=conn, meta=meta)


def cppgraph_registry(
    repo: Path, *, cppgraph: Path | None = None, no_cppgraph: bool = False
) -> CppgraphRegistry:
    """The default `code` entries for both provider registries (MASORA_DESIGN.md §5.2, §6.2).

    `cppgraph` points at an explicit graph.db (the CLI `--cppgraph` flag),
    None auto-discovers `<repo>/.cppgraph/*.graph.db`; `no_cppgraph` forces
    file-only. Unavailable with a stated `reason` when a found or explicitly
    given store is unusable or its indexed commit does not match the repo HEAD
    (§5.2: re-index first → `unknown` shadows); a missing store and
    `no_cppgraph` are silent (cppgraph is optional).
    """
    if no_cppgraph:
        return CppgraphRegistry(None, None, None, None, None)
    db = cppgraph if cppgraph is not None else discover_graph_db(repo)
    if db is None:
        return CppgraphRegistry(None, None, None, None, None)
    if not db.is_file():
        return CppgraphRegistry(None, None, None, None, f"--cppgraph path is not a file: {db}")
    handle = open_graph(db)
    if handle is None:
        return CppgraphRegistry(
            None,
            None,
            None,
            None,
            f"{db} is not a readable cppgraph store (unreadable, or built by a newer cppgraph)",
        )
    commit = handle.source_commit
    head = repo_head(repo)
    if commit is None or head is None:
        return CppgraphRegistry(
            None,
            None,
            db,
            commit,
            f"cannot verify {db} is current (indexed commit: {commit or 'none'},"
            f" HEAD: {head or 'none'}) — code anchors report unknown",
            handle,
        )
    if commit != head:
        return CppgraphRegistry(
            None,
            None,
            db,
            commit,
            f"{db} was indexed at {commit[:12]} but HEAD is {head[:12]}"
            " — re-index with cppgraph; code anchors report unknown (MASORA_DESIGN.md §5.2)",
            handle,
        )
    root = repo.resolve()

    def fingerprint(kind: str, identity: str) -> str | None:
        if kind != "code":
            return None
        return definition_fingerprint(handle, root, identity)

    def edge_snapshot(kind: str, identity: str) -> dict | None:
        if kind != "code":
            return None
        return edge_snapshot_of(handle, identity)

    return CppgraphRegistry(fingerprint, edge_snapshot, db, commit, None, handle)


def definition_fingerprint(handle: GraphHandle, root: Path, identity: str) -> str | None:
    """sha256 of the normalized definition-range source (MASORA_DESIGN.md §5.4).

    The range is `symbols.line`..`symbols.end_line` inclusive (0-indexed); a
    stock graph without body extents hashes the definition line alone. A symbol
    missing from the graph, or a definition whose file is missing/escaping the
    checkout, is None (`not_found` — fails to match, §6.2).
    """
    row = handle.conn.execute(
        "SELECT s.line, s.end_line, f.path"
        " FROM symbols s LEFT JOIN files f ON f.id = s.file_id"
        " WHERE s.symbol = ?",
        (identity,),
    ).fetchone()
    if row is None:
        return None
    line, end_line, rel = row
    if line is None or rel is None:
        return None
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    end = end_line if end_line is not None else line
    if line < 0 or line >= len(lines) or end < line or end >= len(lines):
        return None
    source = "\n".join(lines[line : end + 1])
    return hashlib.sha256(normalize_source(source).encode("utf-8")).hexdigest()


def edge_snapshot_of(handle: GraphHandle, identity: str) -> dict | None:
    """`{edges, neighbours}` per FORMAT.md §4 (suspect snapshot, MASORA_DESIGN.md §12.4).

    `edges` is the symbol's own edge-set hash; `neighbours` maps each 1-hop
    caller ∪ callee (calls edges) to its edge-set hash, self excluded.
    """
    row = handle.conn.execute("SELECT id FROM symbols WHERE symbol = ?", (identity,)).fetchone()
    if row is None:
        return None
    symbol_id = row[0]
    neighbours: dict[str, str] = {}
    for direction in ("src_id", "dst_id"):
        other = "dst_id" if direction == "src_id" else "src_id"
        for (nid,) in handle.conn.execute(
            f"SELECT DISTINCT {other} FROM edges WHERE kind = 'calls' AND {direction} = ?",
            (symbol_id,),
        ):
            if nid == symbol_id:
                continue
            symbol = handle.conn.execute(
                "SELECT symbol FROM symbols WHERE id = ?", (nid,)
            ).fetchone()
            if symbol is not None and symbol[0] not in neighbours:
                neighbours[symbol[0]] = _edge_set_hash(handle, nid)
    return {
        "edges": _edge_set_hash(handle, symbol_id),
        "neighbours": dict(sorted(neighbours.items())),
    }


def _edge_set_hash(handle: GraphHandle, symbol_id: int) -> str:
    """sha256 of the sorted distinct callee SCIP strings from `calls` edges (§5.4)."""
    rows = handle.conn.execute(
        "SELECT DISTINCT s.symbol FROM edges e JOIN symbols s ON s.id = e.dst_id"
        " WHERE e.kind = 'calls' AND e.src_id = ? ORDER BY s.symbol",
        (symbol_id,),
    ).fetchall()
    return hashlib.sha256("\n".join(r[0] for r in rows).encode("utf-8")).hexdigest()
