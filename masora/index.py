"""SQLite index: full-rebuild persistence of §6.2 statuses + FTS5 (MASORA_DESIGN.md §6.2, §8).

The index is disposable: only a full rebuild (drop + recreate) is implemented
and the DB must be safe to delete at any time. Location is one index per base
× code repo: `<masora_home>/indexes/<base-slug>/<repo-slug>-<path-hash>.db`.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from . import config, resolve
from .checker import FILENAME_RE, check_base, discover_event_files
from .diagnostics import (
    E_IDX_CORRUPT,
    E_IDX_NOINDEX,
    E_IDX_QUERY,
    E_IDX_REPO,
    E_IDX_WRITE,
    E_YAML,
    W_IDX_CORRUPT,
    W_IDX_GRAPH,
    CheckFailure,
    Diag,
)
from .fold import Event
from .frontmatter import load_frontmatter
from .schema import EventRecord, validate_event
from .sync import SyncError, _tombstone_pairs, git_env
from .ulid import is_ulid

SCHEMA_VERSION = "4"

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE lineages (
    lineage TEXT PRIMARY KEY,
    displayed TEXT,
    resolution TEXT NOT NULL,
    verification TEXT NOT NULL,
    suspect INTEGER NOT NULL,
    doubted INTEGER NOT NULL,
    pending INTEGER NOT NULL,
    unknown INTEGER NOT NULL,
    unanchored INTEGER NOT NULL
);
CREATE TABLE versions (
    version TEXT PRIMARY KEY,
    lineage TEXT NOT NULL,
    refuted INTEGER NOT NULL,
    summary TEXT NOT NULL,
    statement TEXT NOT NULL,
    source TEXT NOT NULL,
    name TEXT,
    effort TEXT
);
CREATE INDEX versions_by_lineage ON versions (lineage);
CREATE TABLE anchors (
    version TEXT NOT NULL,
    provider TEXT NOT NULL,
    identity TEXT NOT NULL,
    fingerprint TEXT NOT NULL
);
CREATE INDEX anchors_by_version ON anchors (version);
CREATE VIRTUAL TABLE search USING fts5(
    summary,
    statement,
    lineage UNINDEXED,
    version UNINDEXED
);
CREATE VIRTUAL TABLE questions USING fts5(
    question,
    version UNINDEXED,
    question_ordinal UNINDEXED
);
CREATE VIRTUAL TABLE keywords USING fts5(
    keyword,
    version UNINDEXED,
    keyword_ordinal UNINDEXED
);
"""

SEARCH_SQL = """
SELECT search.lineage, search.version, search.summary, lineages.displayed,
       lineages.resolution, lineages.verification, lineages.suspect,
       lineages.doubted, lineages.pending, lineages.unknown, lineages.unanchored
FROM search JOIN lineages ON lineages.lineage = search.lineage
WHERE search MATCH ?
ORDER BY search.lineage, search.version
"""

QUESTIONS_SQL = """
SELECT version, question FROM questions WHERE questions MATCH ?
ORDER BY version, question_ordinal
"""

KEYWORDS_SQL = """
SELECT version, keyword FROM keywords WHERE keywords MATCH ?
ORDER BY version, keyword_ordinal
"""

CONTENT_BY_VERSION_SQL = """
SELECT search.lineage, search.version, search.summary, lineages.displayed,
       lineages.resolution, lineages.verification, lineages.suspect,
       lineages.doubted, lineages.pending, lineages.unknown, lineages.unanchored
FROM search JOIN lineages ON lineages.lineage = search.lineage
WHERE search.version = ?
"""


def _hit_from_row(
    row: tuple, matched_questions: tuple[str, ...], matched_keywords: tuple[str, ...] = ()
) -> SearchHit:
    return SearchHit(
        lineage=row[0],
        version=row[1],
        summary=row[2],
        displayed=row[3],
        resolution=row[4],
        verification=row[5],
        suspect=bool(row[6]),
        doubted=bool(row[7]),
        pending=bool(row[8]),
        unknown=bool(row[9]),
        unanchored=bool(row[10]),
        matched_questions=matched_questions,
        matched_keywords=matched_keywords,
    )


def search_index(db: Path, query: str) -> list[SearchHit]:
    """Run the FTS query over THREE tables — the content (summary + statement),
    the per-question and the per-keyword tables — and union the hits by
    version; raises IndexingError for missing/corrupt index or bad query
    syntax. Every hit carries the distinct matched questions and keywords
    (ordinal order); a question/keyword-only hit surfaces its version's
    content row."""
    if not query.strip():
        raise IndexingError(Diag("error", E_IDX_QUERY, "empty FTS query"))
    if not db.is_file():
        raise IndexingError(
            Diag("error", E_IDX_NOINDEX, f"no index at {db} — build it with masora index")
        )
    conn = _open_index(db)
    try:
        try:
            rows = conn.execute(SEARCH_SQL, (query,)).fetchall()
            question_rows = conn.execute(QUESTIONS_SQL, (query,)).fetchall()
            keyword_rows = conn.execute(KEYWORDS_SQL, (query,)).fetchall()
        except sqlite3.OperationalError as exc:
            raise IndexingError(Diag("error", E_IDX_QUERY, f"invalid FTS query: {exc}")) from exc
        except sqlite3.DatabaseError as exc:
            raise IndexingError(_corrupt_diag(db, str(exc))) from exc
        questions_by_version: dict[str, list[str]] = {}
        for version, question in question_rows:
            questions_by_version.setdefault(version, []).append(question)
        keywords_by_version: dict[str, list[str]] = {}
        for version, keyword in keyword_rows:
            keywords_by_version.setdefault(version, []).append(keyword)
        versions = set(questions_by_version) | set(keywords_by_version)
        hits: dict[str, SearchHit] = {}
        for r in rows:
            hits[r[1]] = _hit_from_row(
                r,
                tuple(questions_by_version.get(r[1], [])),
                tuple(keywords_by_version.get(r[1], [])),
            )
        for version in versions - set(hits):
            row = conn.execute(CONTENT_BY_VERSION_SQL, (version,)).fetchone()
            if row is not None:
                hits[version] = _hit_from_row(
                    row,
                    tuple(questions_by_version.get(version, [])),
                    tuple(keywords_by_version.get(version, [])),
                )
    finally:
        conn.close()
    return sorted(hits.values(), key=lambda h: (h.lineage, h.version))


class IndexingError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


@dataclass
class ParsedEvent:
    record: EventRecord
    anchors: tuple[resolve.AnchorData, ...]
    snapshots: dict | None
    statement: str
    questions: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass
class IndexResult:
    db_path: Path | None
    statuses: tuple[resolve.LineageStatus, ...] = ()
    version_count: int = 0
    diags: list[Diag] = field(default_factory=list)
    base_head: str | None = None
    graph_commit: str | None = None
    graph_db: Path | None = None

    @property
    def lineage_count(self) -> int:
        return len(self.statuses)

    @property
    def errors(self) -> list[Diag]:
        return [d for d in self.diags if d.severity == "error"]

    @property
    def warnings(self) -> list[Diag]:
        return [d for d in self.diags if d.severity == "warning"]

    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.warnings:
            return 2
        return 0


@dataclass(frozen=True)
class SearchHit:
    lineage: str
    version: str
    summary: str
    displayed: str | None
    resolution: str
    verification: str
    suspect: bool
    doubted: bool
    pending: bool
    unknown: bool
    unanchored: bool
    matched_questions: tuple[str, ...] = ()
    matched_keywords: tuple[str, ...] = ()

    @property
    def flags(self) -> str:
        names = [
            n
            for n, v in (
                ("suspect", self.suspect),
                ("doubted", self.doubted),
                ("pending", self.pending),
                ("unknown", self.unknown),
                ("unanchored", self.unanchored),
            )
            if v
        ]
        return ",".join(names) or "-"


def index_dir_for(base_dir: Path) -> Path:
    """The indexes directory of a base: `indexes/<base-dir-slug>/` — one source
    of truth shared by `index_db_path` and every reader of the layout."""
    return config.indexes_root() / (config.slug(base_dir.resolve().name) or "index")


def index_db_path(base_dir: Path, repo: Path) -> Path:
    repo_root = repo.resolve()
    digest = hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()[:12]
    repo_key = f"{config.slug(repo_root.name) or 'index'}-{digest}"
    return index_dir_for(base_dir) / f"{repo_key}.db"


def file_fingerprint_provider(repo: Path) -> resolve.FingerprintFn:
    """`file` anchors: sha256 of the whitespace/comment-normalized content (§5.2, §12.7).

    Identity is a repo-relative path, optionally `path#section` (the section is
    ignored in v1). A missing or escaping file is not_found.
    """
    root = repo.resolve()

    def fingerprint(kind: str, identity: str) -> str | None:
        if kind != "file":
            return None
        path = (root / identity.split("#", 1)[0]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        return hashlib.sha256(normalize_source(text).encode("utf-8")).hexdigest()

    return fingerprint


def normalize_source(text: str) -> str:
    """Whitespace/comment-normalized content (MASORA_DESIGN.md §5.2).

    Terminated `/* … */` block comments (inline or spanning lines) are removed,
    then blank lines and full-line `//`/`#` comments are dropped and whitespace
    runs collapsed; an unterminated `/*` is content, not a comment.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    lines = []
    for raw in without_blocks.splitlines():
        line = " ".join(raw.split())
        if not line or line.startswith(("//", "#")):
            continue
        lines.append(line)
    return "\n".join(lines)


def build_index(
    base_dir: Path,
    repo: Path,
    *,
    fingerprints: Mapping[str, resolve.FingerprintFn | None] | None = None,
    edge_snapshots: Mapping[str, resolve.EdgeSnapshotFn | None] | None = None,
    db_path: Path | None = None,
    cppgraph: Path | None = None,
    no_cppgraph: bool = False,
) -> IndexResult:
    """Full rebuild from the base tree; raises IndexingError on unusable inputs.

    Without injected registries the defaults ship the `file` provider plus the
    `code` provider from `masora/providers.py` (`cppgraph`: explicit graph.db
    or None = auto-discover `<repo>/.cppgraph/*.graph.db`; `no_cppgraph`
    forces file-only). The graph's indexed commit is exposed on the result and
    in the index meta (MASORA_DESIGN.md §5.2).
    """
    if not repo.is_dir():
        raise IndexingError(
            Diag("error", E_IDX_REPO, f"--repo path is not an existing directory: {repo}")
        )
    from .providers import repo_head

    db = db_path if db_path is not None else index_db_path(base_dir, repo)
    check = check_base(base_dir)
    diags = list(check.diags)
    if check.errors:
        return IndexResult(db_path=db, diags=diags)
    _report_corrupt(db, diags)
    parsed = _parse_events(base_dir, diags)
    tombstoned = _tombstone_ulids(base_dir)
    graph_commit: str | None = None
    graph_db: Path | None = None
    registry = None
    if fingerprints is None:
        from .providers import cppgraph_registry

        registry = cppgraph_registry(repo, cppgraph=cppgraph, no_cppgraph=no_cppgraph)
        if registry.available:
            graph_commit = registry.graph_commit
            graph_db = registry.db
        fingerprints = {"file": file_fingerprint_provider(repo), "code": registry.fingerprints}
        if edge_snapshots is None:
            edge_snapshots = {"code": registry.edges}
        if registry.reason is not None and _has_code_anchors(parsed):
            diags.append(Diag("warning", W_IDX_GRAPH, registry.reason))
    try:
        entries = _resolve_all(
            parsed, tombstoned, fingerprints, edge_snapshots or {}, _pending_ids(parsed, base_dir)
        )
    finally:
        if registry is not None:
            registry.close()
    version_count = sum(len(claims) for _, claims in entries)
    head = _base_head(base_dir)
    try:
        _write_db(db, entries, head, repo_head(repo), base_dir, repo, graph_commit, graph_db)
    except OSError as exc:
        raise IndexingError(
            Diag("error", E_IDX_WRITE, f"index location {db.parent} is not writable: {exc}")
        ) from exc
    return IndexResult(
        db_path=db,
        statuses=tuple(status for status, _ in entries),
        version_count=version_count,
        diags=diags,
        base_head=head,
        graph_commit=graph_commit,
        graph_db=graph_db,
    )


def _has_code_anchors(parsed: list[ParsedEvent]) -> bool:
    return any(
        pe.record.kind == "claim" and any(a.provider == "code" for a in pe.anchors) for pe in parsed
    )


def _open_index(db: Path) -> sqlite3.Connection:
    """Read-only connection with the meta/schema check; any failure there is corruption."""
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise IndexingError(_corrupt_diag(db, str(exc))) from exc
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as exc:
        conn.close()
        raise IndexingError(_corrupt_diag(db, str(exc))) from exc
    if row is None or row[0] != SCHEMA_VERSION:
        conn.close()
        raise IndexingError(_corrupt_diag(db, "schema version mismatch"))
    return conn


FRESHNESS_TOLERANCE_S = 2.0


def index_stale(db: Path, base_dir: Path, repo: Path | None = None) -> bool | None:
    """True when the base or code state moved since the build (rebuild trigger, TODO line 46).

    Four axes: the stored meta (`base_head`, `repo_head`, `graph_commit`)
    compared against the current base HEAD, the `--repo` HEAD and the
    discovered graph store's indexed commit, plus filesystem freshness — the
    newest mtime across the base tree's event files and `deleted.toml` against
    the build moment (`built_at`, tolerance `FRESHNESS_TOLERANCE_S`), which
    catches UNCOMMITTED writes that move no HEAD (the live-rollout freeze). A
    comparison with an unknown side (pre-built_at index row, no `--repo`, no
    git HEAD, no discovered graph, no event files) is skipped; None only when
    nothing is comparable.
    """
    return _stale_reason(db, base_dir, repo)[0]


def index_stale_reason(db: Path, base_dir: Path, repo: Path | None = None) -> str | None:
    """The staleness reason sentence, or None when clean or nothing is comparable.

    Same four axes as `index_stale`; the reason flows into the W-IDX-STALE
    message (`masora search`, MCP `search`) — `masora facts` keeps the bare
    `stale_warning` boolean (no contract shape change).
    """
    return _stale_reason(db, base_dir, repo)[1]


def _stale_reason(
    db: Path, base_dir: Path, repo: Path | None = None
) -> tuple[bool | None, str | None]:
    stored = _stored_meta(db)
    from .providers import discover_graph_db, open_graph, repo_head

    checks: list[tuple[bool, str]] = []
    current_base = _base_head(base_dir)
    if stored.get("base_head") and current_base:
        moved = stored["base_head"] != current_base
        checks.append((moved, "base or code state moved since the index build (base HEAD changed)"))
    if repo is not None:
        current_repo = repo_head(repo)
        if stored.get("repo_head") and current_repo:
            moved = stored["repo_head"] != current_repo
            checks.append(
                (moved, "base or code state moved since the index build (code HEAD changed)")
            )
        graph_db = discover_graph_db(repo)
        if graph_db is not None:
            handle = open_graph(graph_db)
            if handle is not None:
                current_graph = handle.source_commit
                handle.conn.close()
                if "graph_commit" in stored and current_graph:
                    moved = stored["graph_commit"] != current_graph
                    checks.append(
                        (
                            moved,
                            "base or code state moved since the index build (the graph store was re-indexed)",
                        )
                    )
    built = _built_at_epoch(stored)
    if built is not None:
        newest = _newest_event_mtime(base_dir)
        if newest is not None:
            fresh = newest > built + FRESHNESS_TOLERANCE_S
            checks.append(
                (
                    fresh,
                    "events written since the index build (uncommitted or unsynced writes move no git HEAD)",
                )
            )
    if not checks:
        return None, None
    stale = any(flag for flag, _ in checks)
    reason = next((why for flag, why in checks if flag), None)
    return stale, reason


def _built_at_epoch(stored: dict[str, str]) -> float | None:
    """The recorded build moment as an epoch float; None when absent/unparsable."""
    raw = stored.get("built_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def _newest_event_mtime(base_dir: Path) -> float | None:
    """Newest mtime across the base tree's event files (`*.md`) and `deleted.toml`.

    One walk, no caching — bases are small markdown trees; `.git` is skipped
    like the checker does. None when the tree holds no comparable file.
    """
    newest: float | None = None
    for path in base_dir.rglob("*.md"):
        if ".git" in path.parts:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        newest = mtime if newest is None else max(newest, mtime)
    tombstone = base_dir / "deleted.toml"
    if tombstone.is_file():
        try:
            mtime = tombstone.stat().st_mtime
        except OSError:
            pass
        else:
            newest = mtime if newest is None else max(newest, mtime)
    return newest


def _stored_meta(db: Path) -> dict[str, str]:
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
        try:
            return dict(conn.execute("SELECT key, value FROM meta").fetchall())
        finally:
            conn.close()
    except sqlite3.Error:
        return {}


def _report_corrupt(db: Path, diags: list[Diag]) -> None:
    if not db.is_file():
        return
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
        try:
            conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        diags.append(
            Diag(
                "warning",
                W_IDX_CORRUPT,
                f"existing index {db} is unreadable — discarded and rebuilt (the index is disposable)",
            )
        )


def _corrupt_diag(db: Path, why: str) -> Diag:
    return Diag(
        "error",
        E_IDX_CORRUPT,
        f"index {db} is unusable ({why}) — rebuild it with masora index",
    )


def _parse_events(base_dir: Path, diags: list[Diag]) -> list[ParsedEvent]:
    parsed: list[ParsedEvent] = []
    for path in discover_event_files(base_dir):
        rel = str(path.relative_to(base_dir))
        match = FILENAME_RE.match(path.name)
        if match is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            diags.append(Diag("error", E_YAML, f"file is not valid UTF-8: {exc}", rel))
            continue
        try:
            data = load_frontmatter(text, rel)
            record = validate_event(data, match.group("kind"), rel)
        except CheckFailure as exc:
            diags.append(exc.diag)
            continue
        anchors = (
            tuple(
                resolve.AnchorData(
                    provider=a["provider"],
                    identity=a["identity"],
                    fingerprint=a["fingerprint"],
                    snapshot=a.get("snapshot"),
                )
                for a in (data.get("anchors") or [])
            )
            if record.kind == "claim"
            else ()
        )
        parsed.append(
            ParsedEvent(
                record=record,
                anchors=anchors,
                snapshots=data.get("snapshots") if record.kind == "verify" else None,
                statement=data.get("statement") or "",
                questions=record.questions if record.kind == "claim" else (),
                keywords=record.keywords if record.kind == "claim" else (),
            )
        )
    return parsed


def _tombstone_ulids(base_dir: Path) -> set[str]:
    path = base_dir / "deleted.toml"
    if not path.exists():
        return set()
    try:
        pairs = _tombstone_pairs(path.read_bytes(), "index")
    except SyncError:
        return set()
    return {ulid for pair in pairs for ulid in pair}


def _pending_ids(parsed: list[ParsedEvent], base_dir: Path) -> frozenset[str]:
    published = _published_ids(base_dir)
    if published is None:
        return frozenset()
    return frozenset(pe.record.id for pe in parsed) - published


def _published_ids(base_dir: Path) -> set[str] | None:
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "ls-tree", "-r", "--name-only", "origin/main"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    if proc.returncode != 0:
        return None
    ids = set()
    for name in proc.stdout.splitlines():
        match = FILENAME_RE.match(name.rsplit("/", 1)[-1])
        if match and is_ulid(match.group("ulid")):
            ids.add(match.group("ulid"))
    return ids


def _base_head(base_dir: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(base_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _resolve_all(
    parsed: list[ParsedEvent],
    tombstoned: set[str],
    fingerprints: Mapping[str, resolve.FingerprintFn | None],
    edge_snapshots: Mapping[str, resolve.EdgeSnapshotFn | None],
    pending_ids: frozenset[str],
) -> tuple[tuple[resolve.LineageStatus, list[ParsedEvent]], ...]:
    by_lineage: dict[str, list[ParsedEvent]] = {}
    for pe in parsed:
        if pe.record.id in tombstoned or pe.record.lineage in tombstoned:
            continue
        by_lineage.setdefault(pe.record.lineage, []).append(pe)
    results = []
    for lineage in sorted(by_lineage):
        events = by_lineage[lineage]
        claims = [pe for pe in events if pe.record.kind == "claim"]
        if not claims:
            continue
        versions = tuple(
            resolve.VersionData(
                id=pe.record.id, anchors=pe.anchors, unanchored=pe.record.unanchored
            )
            for pe in claims
        )
        status = resolve.resolve_lineage(
            lineage,
            versions,
            [_fold_event(pe) for pe in events],
            fingerprints,
            edge_snapshots=edge_snapshots,
            pending_ids=pending_ids,
        )
        results.append((status, claims))
    return tuple(results)


def _fold_event(pe: ParsedEvent) -> Event:
    r = pe.record
    timestamp = {"commit": r.timestamp_commit, "graph_commit": r.timestamp_graph_commit}
    return Event(
        id=r.id,
        kind=r.kind,
        lineage=r.lineage,
        targets=r.targets,
        source=r.source,
        verified_at=timestamp if r.kind == "verify" else None,
        recorded_at=timestamp if r.kind != "verify" else None,
        snapshots=pe.snapshots,
    )


def _write_db(
    db: Path,
    entries: tuple[tuple[resolve.LineageStatus, list[ParsedEvent]], ...],
    head: str | None,
    repo_head: str | None,
    base_dir: Path,
    repo: Path,
    graph_commit: str | None = None,
    graph_db: Path | None = None,
) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_name(db.name + ".building")
    for suffix in ("", "-wal", "-shm"):
        Path(str(tmp) + suffix).unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(DDL)
        for status, claims in entries:
            conn.execute(
                "INSERT INTO lineages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    status.lineage,
                    status.displayed,
                    status.resolution,
                    status.verification,
                    int(status.suspect),
                    int(status.doubted),
                    int(status.pending),
                    int(status.unknown),
                    int(status.unanchored),
                ),
            )
            for claim in claims:
                refuted = claim.record.id in status.refuted
                conn.execute(
                    "INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        claim.record.id,
                        status.lineage,
                        int(refuted),
                        claim.record.summary or "",
                        claim.statement,
                        claim.record.source or "",
                        claim.record.name,
                        claim.record.effort,
                    ),
                )
                for a in claim.anchors:
                    conn.execute(
                        "INSERT INTO anchors VALUES (?, ?, ?, ?)",
                        (claim.record.id, a.provider, a.identity, a.fingerprint),
                    )
                conn.execute(
                    "INSERT INTO search (summary, statement, lineage, version) VALUES (?, ?, ?, ?)",
                    (claim.record.summary or "", claim.statement, status.lineage, claim.record.id),
                )
                for ordinal, question in enumerate(claim.questions):
                    conn.execute(
                        "INSERT INTO questions (question, version, question_ordinal) VALUES (?, ?, ?)",
                        (question, claim.record.id, ordinal),
                    )
                for ordinal, keyword in enumerate(claim.keywords):
                    conn.execute(
                        "INSERT INTO keywords (keyword, version, keyword_ordinal) VALUES (?, ?, ?)",
                        (keyword, claim.record.id, ordinal),
                    )
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("schema_version", SCHEMA_VERSION),
                ("base_path", str(base_dir.resolve())),
                ("repo_path", str(repo.resolve())),
                ("base_head", head or ""),
                ("repo_head", repo_head or ""),
                ("graph_commit", graph_commit or ""),
                ("graph_db", str(graph_db) if graph_db else ""),
                ("built_at", datetime.now(UTC).replace(microsecond=0).isoformat()),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    os.replace(tmp, db)
