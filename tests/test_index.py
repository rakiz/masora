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
    ULID_L1,
    ULID_V1A,
    ULID_V2A,
    make_claim,
    make_verify,
    write_event,
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
