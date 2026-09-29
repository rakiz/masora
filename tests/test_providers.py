"""Tests for the `code` anchor provider over a cppgraph graph store (masora/providers.py)."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from helpers import SHA, write_graph_db

from masora.index import normalize_source
from masora.providers import (
    cppgraph_registry,
    discover_graph_db,
    open_graph,
    repo_head,
)
from masora.sync import git_env

SYM_A = "scip-clang cxx . . mongo/Engine#start()."
SYM_B = "scip-clang cxx . . mongo/Engine#stop()."
SYM_C = "scip-clang cxx . . mongo/Util#tick()."
SOURCE = """namespace mongo {
void Engine::start() {
    // bring-up order matters
    stop();
    tick();
}
void Engine::stop() {
}
void Util::tick() {
}
}
"""


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def write_source(repo: Path, text: str = SOURCE) -> None:
    (repo / "mongo").mkdir(parents=True, exist_ok=True)
    (repo / "mongo" / "engine.cpp").write_text(text, encoding="utf-8")


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    write_source(repo)
    repo.joinpath(".cppgraph").mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "src")
    return repo, git(repo, "rev-parse", "HEAD")


def write_current_graph(repo: Path, head: str, **kwargs) -> Path:
    symbols = kwargs.pop(
        "symbols",
        {
            SYM_A: ("mongo/engine.cpp", 1, 4),
            SYM_B: ("mongo/engine.cpp", 5, 6),
            SYM_C: ("mongo/engine.cpp", 7, 8),
        },
    )
    return write_graph_db(
        repo / ".cppgraph" / f"{repo.name}.graph.db", commit=head, symbols=symbols, **kwargs
    )


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_definition_fingerprint_hashes_normalized_definition_range(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head)
    registry = cppgraph_registry(repo)
    expected = digest(normalize_source("\n".join(SOURCE.splitlines()[1:5])))
    assert registry.fingerprints("code", SYM_A) == expected


def test_definition_fingerprint_ignores_comments_and_whitespace(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head)
    registry = cppgraph_registry(repo)
    before = registry.fingerprints("code", SYM_A)
    write_source(
        repo,
        """namespace mongo {
void  Engine::start()  {
    // a different full-line comment
    stop();
        tick();
}
void Engine::stop() {
}
void Util::tick() {
}
}
""",
    )
    assert registry.fingerprints("code", SYM_A) == before


def test_definition_fingerprint_changes_with_body(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head)
    registry = cppgraph_registry(repo)
    before = registry.fingerprints("code", SYM_A)
    write_source(repo, SOURCE.replace("    stop();", "    halt();"))
    assert registry.fingerprints("code", SYM_A) != before


def test_definition_fingerprint_stable_across_graph_rebuilds(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head)
    first = cppgraph_registry(repo).fingerprints("code", SYM_A)
    write_current_graph(repo, head)
    second = cppgraph_registry(repo).fingerprints("code", SYM_A)
    assert first == second
    assert first is not None


def test_definition_fingerprint_single_line_without_body_extent(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(
        repo,
        head,
        symbols={SYM_A: ("mongo/engine.cpp", 1, None), SYM_B: ("mongo/engine.cpp", 5, 6)},
        calls=[(SYM_A, SYM_B)],
    )
    registry = cppgraph_registry(repo)
    expected = digest(normalize_source("void Engine::start() {"))
    assert registry.fingerprints("code", SYM_A) == expected


def test_edge_set_fingerprint_changes_when_callee_added(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head, calls=[(SYM_A, SYM_B)])
    registry = cppgraph_registry(repo)
    edges_before, snap_before = registry.edges("code", SYM_A)["edges"], None
    assert edges_before == digest(SYM_B)
    write_current_graph(repo, head, calls=[(SYM_A, SYM_B), (SYM_A, SYM_C)])
    snap_before = cppgraph_registry(repo).edges("code", SYM_A)["edges"]
    assert snap_before == digest("\n".join(sorted([SYM_B, SYM_C])))
    assert snap_before != edges_before


def test_neighbours_snapshot_shape(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head, calls=[(SYM_A, SYM_B), (SYM_A, SYM_C), (SYM_B, SYM_C)])
    registry = cppgraph_registry(repo)
    snapshot = registry.edges("code", SYM_A)
    assert snapshot == {
        "edges": digest("\n".join(sorted([SYM_B, SYM_C]))),
        "neighbours": {
            SYM_B: digest(SYM_C),
            SYM_C: digest(""),
        },
    }
    caller_snapshot = registry.edges("code", SYM_B)
    assert caller_snapshot["neighbours"] == {
        SYM_A: digest("\n".join(sorted([SYM_B, SYM_C]))),
        SYM_C: digest(""),
    }


def test_unknown_symbol_and_missing_source_are_not_found(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head)
    registry = cppgraph_registry(repo)
    assert registry.fingerprints("code", "scip-clang cxx . . mongo/Nope#f().") is None
    (repo / "mongo" / "engine.cpp").unlink()
    assert registry.fingerprints("code", SYM_A) is None


def test_definition_fingerprint_refuses_escaping_path(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head, symbols={SYM_A: ("../outside.cpp", 0, 1)})
    (tmp_path / "outside.cpp").write_text("void f();\n", encoding="utf-8")
    registry = cppgraph_registry(repo)
    assert registry.fingerprints("code", SYM_A) is None


def test_registry_behind_head_unavailable(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, SHA)
    registry = cppgraph_registry(repo)
    assert registry.fingerprints is None
    assert registry.edges is None
    assert registry.graph_commit == SHA
    assert registry.reason is not None and "re-index" in registry.reason
    assert repo_head(repo) == head


def test_registry_without_commit_or_head_unavailable(tmp_path):
    repo, _head = make_repo(tmp_path)
    write_current_graph(repo, None)
    registry = cppgraph_registry(repo)
    assert registry.fingerprints is None
    assert "cannot verify" in registry.reason
    plain = tmp_path / "plain"
    plain.mkdir()
    write_graph_db(plain / ".cppgraph" / "plain.graph.db", commit=SHA, symbols={}, calls=[])
    assert cppgraph_registry(plain).reason is not None


def test_registry_matching_head_is_available(tmp_path):
    repo, head = make_repo(tmp_path)
    write_current_graph(repo, head)
    registry = cppgraph_registry(repo)
    assert registry.available
    assert registry.graph_commit == head
    assert registry.reason is None


def test_registry_missing_graph_is_silent(tmp_path):
    repo, _head = make_repo(tmp_path)
    registry = cppgraph_registry(repo)
    assert registry.fingerprints is None
    assert registry.reason is None
    assert discover_graph_db(repo) is None


def test_registry_auto_discovery_picks_newest(tmp_path):
    repo, head = make_repo(tmp_path)
    db = write_current_graph(repo, head)
    older = repo / ".cppgraph" / "older.graph.db"
    write_graph_db(older, commit=SHA, symbols={}, calls=[])
    os.utime(db, (2000000000, 2000000000))
    os.utime(older, (1000000000, 1000000000))
    assert discover_graph_db(repo) == db
    assert cppgraph_registry(repo).graph_commit == head


def test_registry_explicit_db_and_no_cppgraph(tmp_path):
    repo, head = make_repo(tmp_path)
    explicit = write_graph_db(tmp_path / "elsewhere.db", commit=head, symbols={}, calls=[])
    registry = cppgraph_registry(repo, cppgraph=explicit)
    assert registry.available
    assert registry.graph_commit == head
    off = cppgraph_registry(repo, no_cppgraph=True)
    assert off.fingerprints is None and off.reason is None


def test_corrupt_or_newer_graph_db_unavailable(tmp_path):
    repo, head = make_repo(tmp_path)
    garbage = repo / ".cppgraph" / "garbage.graph.db"
    garbage.write_bytes(b"not sqlite" * 64)
    assert cppgraph_registry(repo).reason is not None
    write_current_graph(repo, head)
    import sqlite3

    conn = sqlite3.connect(repo / ".cppgraph" / f"{repo.name}.graph.db")
    conn.execute("UPDATE meta SET value = '6' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    registry = cppgraph_registry(repo)
    assert registry.fingerprints is None
    assert "newer cppgraph" in registry.reason


def test_open_graph_refuses_store_without_symbols_table(tmp_path):
    repo, head = make_repo(tmp_path)
    db = write_current_graph(repo, head)
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE symbols")
    conn.commit()
    conn.close()
    assert open_graph(db) is None
    assert cppgraph_registry(repo).reason is not None


def test_open_graph_refuses_non_integer_schema_version(tmp_path):
    repo, head = make_repo(tmp_path)
    db = write_current_graph(repo, head)
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("UPDATE meta SET value = 'five' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    assert open_graph(db) is None
    registry = cppgraph_registry(repo)
    assert registry.reason is not None
    assert "unparsable schema_version 'five'" in registry.reason


def _set_schema_version(db: Path, value: str | None) -> None:
    import sqlite3

    conn = sqlite3.connect(db)
    if value is None:
        conn.execute("DELETE FROM meta WHERE key = 'schema_version'")
    else:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (value,))
    conn.commit()
    conn.close()


def test_open_graph_refuses_newer_schema_version_naming_it(tmp_path):
    repo, head = make_repo(tmp_path)
    db = write_current_graph(repo, head)
    _set_schema_version(db, "6")
    assert open_graph(db) is None
    registry = cppgraph_registry(repo)
    assert registry.fingerprints is None and registry.edges is None
    assert registry.reason is not None
    assert "schema_version 6" in registry.reason
    assert "newer" in registry.reason
    assert "5" in registry.reason
    assert registry.graph_commit is None


def test_open_graph_refuses_older_schema_version_naming_it(tmp_path):
    repo, head = make_repo(tmp_path)
    db = write_current_graph(repo, head)
    _set_schema_version(db, "4")
    assert open_graph(db) is None
    registry = cppgraph_registry(repo)
    assert registry.fingerprints is None
    assert registry.reason is not None
    assert "schema_version 4" in registry.reason
    assert "older" in registry.reason


def test_open_graph_refuses_missing_schema_version_row(tmp_path):
    repo, head = make_repo(tmp_path)
    db = write_current_graph(repo, head)
    _set_schema_version(db, None)
    assert open_graph(db) is None
    registry = cppgraph_registry(repo)
    assert registry.fingerprints is None
    assert registry.reason is not None
    assert "no schema_version meta row" in registry.reason


def test_open_graph_accepts_exact_learned_schema_version(tmp_path):
    repo, head = make_repo(tmp_path)
    db = write_current_graph(repo, head)
    handle = open_graph(db)
    assert handle is not None
    assert handle.source_commit == head
    handle.conn.close()
    registry = cppgraph_registry(repo)
    assert registry.available and registry.reason is None


def test_open_graph_reads_provenance(tmp_path):
    repo, head = make_repo(tmp_path)
    db = write_current_graph(repo, head)
    handle = open_graph(db)
    assert handle is not None
    assert handle.source_commit == head
    handle.conn.close()
