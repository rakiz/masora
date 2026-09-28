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
    CheckFailure,
    Diag,
)
from .fold import Event
from .frontmatter import load_frontmatter
from .schema import EventRecord, validate_event
from .sync import SyncError, _tombstone_pairs, git_env
from .ulid import is_ulid

SCHEMA_VERSION = "1"

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
    statement TEXT NOT NULL
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
"""

SEARCH_SQL = """
SELECT search.lineage, search.version, search.summary, lineages.displayed,
       lineages.resolution, lineages.verification, lineages.suspect,
       lineages.doubted, lineages.pending, lineages.unknown, lineages.unanchored
FROM search JOIN lineages ON lineages.lineage = search.lineage
WHERE search MATCH ?
ORDER BY search.lineage, search.version
"""


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


@dataclass
class IndexResult:
    db_path: Path | None
    statuses: tuple[resolve.LineageStatus, ...] = ()
    version_count: int = 0
    diags: list[Diag] = field(default_factory=list)
    base_head: str | None = None

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


def index_db_path(base_dir: Path, repo: Path) -> Path:
    base_slug = config.slug(base_dir.resolve().name) or "index"
    repo_root = repo.resolve()
    digest = hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()[:12]
    repo_key = f"{config.slug(repo_root.name) or 'index'}-{digest}"
    return config.indexes_root() / base_slug / f"{repo_key}.db"


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
) -> IndexResult:
    """Full rebuild from the base tree; raises IndexingError on unusable inputs."""
    if not repo.is_dir():
        raise IndexingError(
            Diag("error", E_IDX_REPO, f"--repo path is not an existing directory: {repo}")
        )
    if fingerprints is None:
        fingerprints = {"file": file_fingerprint_provider(repo)}
    db = db_path if db_path is not None else index_db_path(base_dir, repo)
    check = check_base(base_dir)
    diags = list(check.diags)
    if check.errors:
        return IndexResult(db_path=db, diags=diags)
    _report_corrupt(db, diags)
    parsed = _parse_events(base_dir, diags)
    tombstoned = _tombstone_ulids(base_dir)
    entries = _resolve_all(
        parsed, tombstoned, fingerprints, edge_snapshots or {}, _pending_ids(parsed, base_dir)
    )
    version_count = sum(len(claims) for _, claims in entries)
    head = _base_head(base_dir)
    try:
        _write_db(db, entries, head, base_dir, repo)
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
    )


def search_index(db: Path, query: str) -> list[SearchHit]:
    """Run the FTS query; raises IndexingError for missing/corrupt index or bad query syntax."""
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
        except sqlite3.OperationalError as exc:
            raise IndexingError(Diag("error", E_IDX_QUERY, f"invalid FTS query: {exc}")) from exc
        except sqlite3.DatabaseError as exc:
            raise IndexingError(_corrupt_diag(db, str(exc))) from exc
    finally:
        conn.close()
    return [
        SearchHit(
            lineage=r[0],
            version=r[1],
            summary=r[2],
            displayed=r[3],
            resolution=r[4],
            verification=r[5],
            suspect=bool(r[6]),
            doubted=bool(r[7]),
            pending=bool(r[8]),
            unknown=bool(r[9]),
            unanchored=bool(r[10]),
        )
        for r in rows
    ]


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


def index_stale(db: Path, base_dir: Path) -> bool | None:
    """True when the stored base HEAD differs from the current one (rebuild trigger, TODO line 46)."""
    stored = _stored_base_head(db)
    current = _base_head(base_dir)
    if stored is None or current is None:
        return None
    return stored != current


def _stored_base_head(db: Path) -> str | None:
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'base_head'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] or None if row else None


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
        actor=r.actor,
        verified_at=timestamp if r.kind == "verify" else None,
        recorded_at=timestamp if r.kind != "verify" else None,
        snapshots=pe.snapshots,
    )


def _write_db(
    db: Path,
    entries: tuple[tuple[resolve.LineageStatus, list[ParsedEvent]], ...],
    head: str | None,
    base_dir: Path,
    repo: Path,
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
                    "INSERT INTO versions VALUES (?, ?, ?, ?, ?)",
                    (
                        claim.record.id,
                        status.lineage,
                        int(refuted),
                        claim.record.summary or "",
                        claim.statement,
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
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("schema_version", SCHEMA_VERSION),
                ("base_path", str(base_dir.resolve())),
                ("repo_path", str(repo.resolve())),
                ("base_head", head or ""),
                ("built_at", datetime.now(UTC).replace(microsecond=0).isoformat()),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    os.replace(tmp, db)
