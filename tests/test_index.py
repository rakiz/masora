"""Tests for the SQLite index, FTS search, the file provider and the index CLI surface."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from helpers import (
    FP,
    IDENT_MAIN,
    OMIT,
    SHA,
    ULID_L1,
    ULID_V1A,
    ULID_V2A,
    anchor,
    make_claim,
    make_verify,
    write_event,
    write_graph_db,
)

from masora.cli import main
from masora.config import indexes_root
from masora.diagnostics import E_IDX_CORRUPT
from masora.fold import Event
from masora.index import (
    IndexingError,
    build_index,
    file_fingerprint_provider,
    index_db_path,
    index_stale,
    search_index,
)
from masora.providers import cppgraph_registry
from masora.resolve import AnchorData, VersionData, resolve_lineage
from masora.sync import git_env

CLAIM_REL = "2026-09/x/01J8Z3K0000000000000000000.claim.md"
V2_REL = "2026-09/x/01J8Z3K0000000000000000005.claim.md"
VERIFY_REL = "2026-09/x/01J8Z3K0000000000000000001.verify.md"
TOKES = "shard key"


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


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MASORA_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    return path


@pytest.fixture
def git_base(tmp_path):
    base = tmp_path / "gitbase"
    base.mkdir()
    git(base, "init", "-b", "main")
    git(base, "config", "user.name", "Masora Test")
    git(base, "config", "user.email", "masora@example.invalid")
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    git(base, "remote", "add", "origin", str(origin))
    return base


def code_providers(fp_map: dict, edge_map: dict | None = None):
    registry = {"code": lambda kind, identity: fp_map.get(identity)}
    if edge_map is not None:
        return registry, {"code": lambda kind, identity: edge_map.get(identity)}
    return registry


def db_rows(db: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_default_registry_reports_unknown(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    result = build_index(base, repo)
    assert result.exit_code() == 0
    rows = db_rows(result.db_path, "SELECT resolution FROM lineages")
    assert rows == [("unknown",)]


def test_injected_provider_resolves_current(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    result = build_index(base, repo, fingerprints=code_providers({IDENT_MAIN: FP}))
    assert result.exit_code() == 0
    row = db_rows(result.db_path, "SELECT resolution, verification FROM lineages")[0]
    assert row == ("current", "verified(llm)")
    assert result.lineage_count == 1 and result.version_count == 1


def test_cli_index_summary_counts(base, repo, home, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    code = main(["index", str(base), "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 0
    assert "indexed: 1 lineage(s), 1 version(s)" in out
    assert "status counts: current=0 stale=0 restored=0 none=0 unknown=1" in out
    assert "flags: suspect=0 doubted=0 pending=0 unanchored=0" in out
    assert str(index_db_path(base, repo)) in out


def test_cli_index_bad_repo(base, tmp_path, home, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    code = main(["index", str(base), "--repo", str(tmp_path / "nope")])
    out = capsys.readouterr().out
    assert code == 1
    assert "E-IDX-REPO" in out
    assert not index_db_path(base, tmp_path / "nope").exists()


def test_cli_index_check_errors_block(base, repo, home, capsys):
    (base / "notes.md").write_text("stray file", encoding="utf-8")
    code = main(["index", str(base), "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 1
    assert "E-FILENAME" in out
    assert not index_db_path(base, repo).exists()


def test_search_renders_status_tuples(base, repo, home, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1, summary=f"The {TOKES} rotates"))
    main(["index", str(base), "--repo", str(repo)])
    code = main(["search", str(base), f"{TOKES}", "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 0
    assert "1 match(es) in 1 lineage(s)" in out
    assert f"{ULID_L1} [unknown unverified flags: unknown]" in out
    assert f"  {ULID_L1} The {TOKES} rotates" in out


def test_fts_match_and_case_insensitive(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1, summary=f"The {TOKES} rotates"))
    result = build_index(base, repo)
    assert [h.version for h in search_index(result.db_path, "shard")] == [ULID_L1]
    assert [h.version for h in search_index(result.db_path, "SHARD KEY")] == [ULID_L1]


def test_fts_accent_insensitive(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1, summary="Le café tourne"))
    result = build_index(base, repo)
    assert [h.lineage for h in search_index(result.db_path, "cafe")] == [ULID_L1]


def test_fts_statement_and_no_match(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1, statement="Only in the statement body"))
    result = build_index(base, repo)
    assert len(search_index(result.db_path, "statement body")) == 1
    assert search_index(result.db_path, "zzzunfindable") == []


def test_search_after_gc_tombstone_excludes_lineage(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1, summary=f"The {TOKES} rotates"))
    first = build_index(base, repo)
    assert len(search_index(first.db_path, "shard")) == 1
    (base / CLAIM_REL).unlink()
    (base / "2026-09/x").rmdir()
    (base / "deleted.toml").write_text(
        f'[[deleted]]\nlineage = "{ULID_L1}"\nulids = ["{ULID_L1}"]\n', encoding="utf-8"
    )
    result = build_index(base, repo)
    assert result.lineage_count == 0
    assert search_index(result.db_path, "shard") == []
    assert db_rows(result.db_path, "SELECT count(*) FROM lineages") == [(0,)]


def test_rebuild_idempotent(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1, summary=f"The {TOKES} rotates"))
    first = build_index(base, repo, fingerprints=code_providers({IDENT_MAIN: FP}))
    second = build_index(base, repo, fingerprints=code_providers({IDENT_MAIN: FP}))
    assert [h.__dict__ for h in search_index(first.db_path, "shard")] == [
        h.__dict__ for h in search_index(second.db_path, "shard")
    ]


def test_db_recreated_after_manual_deletion(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1, summary=f"The {TOKES} rotates"))
    result = build_index(base, repo)
    result.db_path.unlink()
    with pytest.raises(IndexingError) as exc:
        search_index(result.db_path, "shard")
    assert exc.value.diag.code == "E-IDX-NOINDEX"
    rebuilt = build_index(base, repo)
    assert [h.version for h in search_index(rebuilt.db_path, "shard")] == [ULID_L1]


def test_corrupt_db_search_refuses(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    db = index_db_path(base, repo)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"garbage" * 512)
    with pytest.raises(IndexingError) as exc:
        search_index(db, "shard")
    assert exc.value.diag.code == E_IDX_CORRUPT


def test_corrupt_db_rebuild_recovers(base, repo, home, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1, summary=f"The {TOKES} rotates"))
    db = index_db_path(base, repo)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"garbage" * 512)
    code = main(["index", str(base), "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 2
    assert "W-IDX-CORRUPT" in out
    assert [h.version for h in search_index(db, "shard")] == [ULID_L1]


def test_base_head_change_detected(git_base, repo, home, capsys):
    write_event(git_base, CLAIM_REL, make_claim(ULID_L1, summary=f"The {TOKES} rotates"))
    git(git_base, "add", "-A")
    git(git_base, "commit", "-m", "claim")
    git(git_base, "push", "origin", "main")
    db = index_db_path(git_base, repo)
    assert main(["index", str(git_base), "--repo", str(repo)]) == 0
    assert index_stale(db, git_base) is False
    write_event(
        git_base,
        V2_REL,
        make_claim(ULID_V2A, ULID_L1, reason="code changed", summary="Second version summary"),
    )
    git(git_base, "add", "-A")
    git(git_base, "commit", "-m", "v2")
    assert index_stale(db, git_base) is True
    code = main(["search", str(git_base), "shard", "--repo", str(repo)])
    assert code == 0
    assert "W-IDX-STALE" in capsys.readouterr().out
    assert main(["index", str(git_base), "--repo", str(repo)]) == 0
    assert index_stale(db, git_base) is False
    assert [h.version for h in search_index(db, "Second")] == [ULID_V2A]


def test_pending_flag_via_origin_diff(git_base, repo, home):
    write_event(git_base, CLAIM_REL, make_claim(ULID_L1))
    git(git_base, "add", "-A")
    git(git_base, "commit", "-m", "claim")
    git(git_base, "push", "origin", "main")
    result = build_index(git_base, repo)
    assert db_rows(result.db_path, "SELECT pending FROM lineages") == [(0,)]
    write_event(git_base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    result = build_index(git_base, repo)
    assert db_rows(result.db_path, "SELECT pending FROM lineages") == [(1,)]
    git(git_base, "add", "-A")
    git(git_base, "commit", "-m", "verify")
    git(git_base, "push", "origin", "main")
    result = build_index(git_base, repo)
    assert db_rows(result.db_path, "SELECT pending FROM lineages") == [(0,)]


def test_fts_query_syntax_error(base, repo, home, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    main(["index", str(base), "--repo", str(repo)])
    code = main(["search", str(base), "(unclosed", "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 2
    assert "E-IDX-QUERY" in out


def test_fts_query_syntax_error_without_fts_marker_in_message(base, repo, home, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    main(["index", str(base), "--repo", str(repo)])
    for query in ('"', "*", "NEAR(x y", "AND", "a OR"):
        code = main(["search", str(base), query, "--repo", str(repo)])
        out = capsys.readouterr().out
        assert code == 2, f"{query!r}: {out}"
        assert "E-IDX-QUERY" in out, f"{query!r}: {out}"
        assert "E-IDX-CORRUPT" not in out


def test_fts_query_syntax_error_without_fts_marker_direct(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    result = build_index(base, repo)
    for query in ('"', "*", "NEAR(x y", "AND", "a OR"):
        with pytest.raises(IndexingError) as exc:
            search_index(result.db_path, query)
        assert exc.value.diag.code == "E-IDX-QUERY"


def test_index_dir_not_writable(base, repo, tmp_path, monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("running as root: chmod does not block writes")
    monkeypatch.setenv("MASORA_HOME", str(tmp_path / "home"))
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    home_dir.chmod(0o555)
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    try:
        with pytest.raises(IndexingError) as exc:
            build_index(base, repo)
        assert exc.value.diag.code == "E-IDX-WRITE"
    finally:
        home_dir.chmod(0o755)


def test_file_reformat_does_not_stale(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text("def  f():   # the note\n    return 1\n")
    provider = file_fingerprint_provider(tmp_path)
    before = provider("file", "mod.py")
    target.write_text("def f():  # the note\n\n        return 1\n")
    assert provider("file", "mod.py") == before
    target.write_text("def g():   # the note\n    return 2\n")
    assert provider("file", "mod.py") != before


def test_file_comment_changes_do_not_change_fingerprint(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text("def f():\n    return 1\n")
    provider = file_fingerprint_provider(tmp_path)
    before = provider("file", "mod.py")
    target.write_text("def f():\n    // a full-line comment\n    return 1\n")
    assert provider("file", "mod.py") == before
    target.write_text("def f():\n    # a hash comment\n    return 1\n")
    assert provider("file", "mod.py") == before
    target.write_text("def f():\n/* a block comment\n   spanning lines */\n    return 1\n")
    assert provider("file", "mod.py") == before
    target.write_text("def f():\n    return 1\n\n/* trailing block\nadded later */\n")
    assert provider("file", "mod.py") == before
    target.write_text("def f():\n    return 1  /* inline */\n")
    assert provider("file", "mod.py") == before


def test_file_comment_only_change_between_builds_keeps_resolution(tmp_path):
    (tmp_path / "doc.py").write_text("def f():\n    return 1\n")
    provider = file_fingerprint_provider(tmp_path)
    fingerprint = provider("file", "doc.py")
    version = VersionData(ULID_L1, (AnchorData("file", "doc.py", fingerprint),))
    events = [Event(id=ULID_L1, kind="claim", lineage=ULID_L1)]
    first = resolve_lineage(ULID_L1, [version], events, {"file": provider})
    assert first.resolution == "current"
    assert first.suspect is False
    (tmp_path / "doc.py").write_text("def f():\n    // reformat added a comment\n    return 1\n")
    second = resolve_lineage(ULID_L1, [version], events, {"file": provider})
    assert second.resolution == "current"
    assert second.suspect is False
    (tmp_path / "doc.py").write_text("def f():\n/* block\ncomment */    return 2\n")
    third = resolve_lineage(ULID_L1, [version], events, {"file": provider})
    assert third.resolution == "stale"


def test_file_provider_escapes_and_missing_are_not_found(tmp_path, repo):
    (tmp_path / "keep.txt").write_text("x\n")
    provider = file_fingerprint_provider(tmp_path)
    assert provider("file", "../escaped.txt") is None
    assert provider("file", "missing.txt") is None
    assert provider("code", IDENT_MAIN) is None


def test_file_provider_resolution_roundtrip(tmp_path):
    (tmp_path / "doc.md").write_text("# Title\n\nThe resume token rotates.\n")
    provider = file_fingerprint_provider(tmp_path)
    fingerprint = provider("file", "doc.md")
    version = VersionData(ULID_L1, (AnchorData("file", "doc.md", fingerprint),))
    current = resolve_lineage(
        ULID_L1,
        [version],
        [Event(id=ULID_L1, kind="claim", lineage=ULID_L1)],
        {"file": file_fingerprint_provider(tmp_path)},
    )
    assert current.resolution == "current"
    (tmp_path / "doc.md").write_text("# Title\n\nThe resume token rotates NOW.\n")
    stale = resolve_lineage(
        ULID_L1,
        [version],
        [Event(id=ULID_L1, kind="claim", lineage=ULID_L1)],
        {"file": file_fingerprint_provider(tmp_path)},
    )
    assert stale.resolution == "stale"


def test_indexes_root_under_masora_home(home):
    assert indexes_root() == home / "indexes"


SYM_A = "scip-clang cxx . . mongo/Engine#start()."
SYM_B = "scip-clang cxx . . mongo/Engine#stop()."
SYM_C = "scip-clang cxx . . mongo/Util#tick()."

CPP_SOURCE_V1 = """namespace mongo {
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

CPP_SOURCE_V2 = """namespace mongo {
void Engine::start() {
    // bring-up order matters
    stop();
    tick();
}
void Engine::stop() {
    tick();
}
void Util::tick() {
}
}
"""

V1_SYMBOLS = {
    SYM_A: ("mongo/engine.cpp", 1, 4),
    SYM_B: ("mongo/engine.cpp", 5, 6),
    SYM_C: ("mongo/engine.cpp", 7, 8),
}
V2_SYMBOLS = {
    SYM_A: ("mongo/engine.cpp", 1, 4),
    SYM_B: ("mongo/engine.cpp", 6, 8),
    SYM_C: ("mongo/engine.cpp", 9, 10),
}


def cpp_repo(tmp_path, source=CPP_SOURCE_V1):
    repo = tmp_path / "cpprepo"
    (repo / "mongo").mkdir(parents=True)
    (repo / "mongo" / "engine.cpp").write_text(source, encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "src")
    return repo, git(repo, "rev-parse", "HEAD")


def write_cppgraph(repo, head, symbols, calls):
    return write_graph_db(
        repo / ".cppgraph" / f"{repo.name}.graph.db", commit=head, symbols=symbols, calls=calls
    )


def code_anchor(repo, identity=SYM_A):
    registry = cppgraph_registry(repo)
    result = anchor(
        identity=identity,
        fingerprint=registry.fingerprints("code", identity),
        snapshot=registry.edges("code", identity),
    )
    registry.close()
    return result


def test_code_graph_missing_is_silent_unknown(base, repo, home):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    result = build_index(base, repo)
    assert result.exit_code() == 0
    assert not result.warnings
    assert db_rows(result.db_path, "SELECT resolution FROM lineages") == [("unknown",)]


def test_code_anchor_resolves_current_with_graph_store(base, home, tmp_path):
    repo, head = cpp_repo(tmp_path)
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    snap = code_anchor(repo)
    write_event(base, CLAIM_REL, make_claim(ULID_L1, anchors=[snap]))
    write_event(
        base,
        VERIFY_REL,
        make_verify(ULID_V1A, ULID_L1, ULID_L1, snapshots={SYM_A: snap["snapshot"]}),
    )
    result = build_index(base, repo)
    assert result.exit_code() == 0
    assert result.graph_commit == head
    assert db_rows(result.db_path, "SELECT resolution, unknown, suspect FROM lineages") == [
        ("current", 0, 0)
    ]
    assert db_rows(result.db_path, "SELECT value FROM meta WHERE key = 'graph_commit'") == [(head,)]


def test_code_graph_behind_head_reports_unknown_with_warning(base, home, tmp_path):
    repo, head = cpp_repo(tmp_path)
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    snap = code_anchor(repo)
    write_event(base, CLAIM_REL, make_claim(ULID_L1, anchors=[snap]))
    write_event(
        base,
        VERIFY_REL,
        make_verify(ULID_V1A, ULID_L1, ULID_L1, snapshots={SYM_A: snap["snapshot"]}),
    )
    git(repo, "commit", "--allow-empty", "-m", "later")
    result = build_index(base, repo)
    assert result.exit_code() == 2
    assert [d.code for d in result.warnings] == ["W-IDX-GRAPH"]
    assert db_rows(result.db_path, "SELECT resolution, unknown FROM lineages") == [("unknown", 1)]


@pytest.mark.parametrize("seen", ["6", "4"])
def test_code_graph_schema_version_mismatch_unknown_with_warning(base, home, tmp_path, seen):
    repo, head = cpp_repo(tmp_path)
    db = write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    snap = code_anchor(repo)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (seen,))
    conn.commit()
    conn.close()
    write_event(base, CLAIM_REL, make_claim(ULID_L1, anchors=[snap]))
    result = build_index(base, repo)
    assert result.exit_code() == 2
    (warning,) = result.warnings
    assert warning.code == "W-IDX-GRAPH"
    assert f"schema_version {seen}" in warning.message
    assert db_rows(result.db_path, "SELECT resolution, unknown FROM lineages") == [("unknown", 1)]


def test_code_graph_missing_schema_version_row_unknown_with_warning(base, home, tmp_path):
    repo, head = cpp_repo(tmp_path)
    db = write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    snap = code_anchor(repo)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM meta WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    write_event(base, CLAIM_REL, make_claim(ULID_L1, anchors=[snap]))
    result = build_index(base, repo)
    (warning,) = result.warnings
    assert warning.code == "W-IDX-GRAPH"
    assert "no schema_version meta row" in warning.message
    assert db_rows(result.db_path, "SELECT resolution, unknown FROM lineages") == [("unknown", 1)]


def test_code_graph_warning_suppressed_without_code_anchors(base, home, tmp_path):
    repo, _head = cpp_repo(tmp_path)
    write_cppgraph(repo, SHA, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    write_event(
        base,
        CLAIM_REL,
        make_claim(ULID_L1, anchors=OMIT, unanchored=True, unanchored_reason="No symbol applies"),
    )
    result = build_index(base, repo)
    assert result.exit_code() == 0
    assert result.warnings == []
    (repo / ".cppgraph" / "garbage.graph.db").write_bytes(b"not sqlite" * 64)
    result = build_index(base, repo)
    assert result.exit_code() == 0
    assert result.warnings == []
    assert db_rows(result.db_path, "SELECT resolution FROM lineages") == [("current",)]


def test_suspect_fires_on_neighbour_drift(base, home, tmp_path):
    repo, head = cpp_repo(tmp_path)
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    snap = code_anchor(repo)
    write_event(base, CLAIM_REL, make_claim(ULID_L1, anchors=[snap]))
    write_event(
        base,
        VERIFY_REL,
        make_verify(ULID_V1A, ULID_L1, ULID_L1, snapshots={SYM_A: snap["snapshot"]}),
    )
    first = build_index(base, repo)
    assert first.statuses[0].suspect is False
    (repo / "mongo" / "engine.cpp").write_text(CPP_SOURCE_V2, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "stop() now calls tick()")
    write_cppgraph(
        repo,
        git(repo, "rev-parse", "HEAD"),
        V2_SYMBOLS,
        [(SYM_A, SYM_B), (SYM_A, SYM_C), (SYM_B, SYM_C)],
    )
    result = build_index(base, repo)
    status = result.statuses[0]
    assert status.resolution == "current"
    assert status.suspect is True


def test_suspect_fires_on_own_edge_drift(base, home, tmp_path):
    repo, head = cpp_repo(tmp_path)
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    write_event(base, CLAIM_REL, make_claim(ULID_L1, anchors=[code_anchor(repo)]))
    assert build_index(base, repo).statuses[0].suspect is False
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B)])
    result = build_index(base, repo)
    assert result.statuses[0].resolution == "current"
    assert result.statuses[0].suspect is True


def test_cli_index_graph_line_and_flags(base, home, tmp_path, capsys):
    repo, head = cpp_repo(tmp_path)
    graph_db = write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    write_event(base, CLAIM_REL, make_claim(ULID_L1, anchors=[code_anchor(repo)]))
    assert main(["index", str(base), "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert f"graph: {graph_db} (commit {head[:12]})" in out
    assert "status counts: current=1" in out
    assert main(["index", str(base), "--repo", str(repo), "--no-cppgraph"]) == 0
    out = capsys.readouterr().out
    assert "graph: none — code anchors report unknown" in out
    assert "status counts: current=0 stale=0 restored=0 none=0 unknown=1" in out
    explicit = tmp_path / "elsewhere"
    explicit.mkdir()
    explicit_db = write_graph_db(
        explicit / "explicit.graph.db", commit=head, symbols=V1_SYMBOLS, calls=[(SYM_A, SYM_B)]
    )
    assert main(["index", str(base), "--repo", str(repo), "--cppgraph", str(explicit_db)]) == 0
    assert str(explicit_db) in capsys.readouterr().out


def test_cli_index_graph_behind_head_warns(base, home, tmp_path, capsys):
    repo, head = cpp_repo(tmp_path)
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    write_event(base, CLAIM_REL, make_claim(ULID_L1, anchors=[code_anchor(repo)]))
    git(repo, "commit", "--allow-empty", "-m", "later")
    code = main(["index", str(base), "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 2
    assert "W-IDX-GRAPH" in out
    assert "re-index with cppgraph" in out


def test_repo_head_drift_warns_on_search(base, home, tmp_path, capsys):
    repo, head = cpp_repo(tmp_path)
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    write_event(
        base,
        CLAIM_REL,
        make_claim(ULID_L1, summary="One line summary", anchors=[code_anchor(repo)]),
    )
    assert build_index(base, repo).exit_code() == 0
    git(repo, "commit", "--allow-empty", "-m", "later")
    code = main(["search", str(base), "summary", "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 0
    assert "W-IDX-STALE" in out
    assert "base or code state moved" in out


def test_graph_reindex_drift_warns_on_search(base, home, tmp_path, capsys):
    repo, head = cpp_repo(tmp_path)
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    write_event(
        base,
        CLAIM_REL,
        make_claim(ULID_L1, summary="One line summary", anchors=[code_anchor(repo)]),
    )
    assert build_index(base, repo).exit_code() == 0
    write_cppgraph(repo, SHA, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    code = main(["search", str(base), "summary", "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 0
    assert "W-IDX-STALE" in out


def test_fresh_search_warning_free(base, home, tmp_path, capsys):
    repo, head = cpp_repo(tmp_path)
    write_cppgraph(repo, head, V1_SYMBOLS, [(SYM_A, SYM_B), (SYM_A, SYM_C)])
    write_event(
        base,
        CLAIM_REL,
        make_claim(ULID_L1, summary="One line summary", anchors=[code_anchor(repo)]),
    )
    assert build_index(base, repo).exit_code() == 0
    code = main(["search", str(base), "summary", "--repo", str(repo)])
    out = capsys.readouterr().out
    assert code == 0
    assert "W-IDX-STALE" not in out
    assert "W-IDX-GRAPH" not in out


def test_index_stale_without_repo_checks_base_only(git_base, repo, home):
    write_event(git_base, CLAIM_REL, make_claim(ULID_L1))
    git(git_base, "add", "-A")
    git(git_base, "commit", "-m", "claim")
    git(git_base, "push", "origin", "main")
    db = index_db_path(git_base, repo)
    result = build_index(git_base, repo)
    assert index_stale(result.db_path, git_base, repo=None) is False
    write_event(
        git_base,
        V2_REL,
        make_claim(ULID_V2A, ULID_L1, reason="code changed", summary="Second version summary"),
    )
    git(git_base, "add", "-A")
    git(git_base, "commit", "-m", "v2")
    assert index_stale(db, git_base, repo=None) is True
    assert db.is_file()
