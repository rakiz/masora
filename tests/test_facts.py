"""Tests for `masora facts` (the cppgraph injection contract, read-only CLI)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from helpers import ULID_L2, make_claim, make_doubt, make_verify, write_event

from masora.cli import main
from masora.config import bases_root
from masora.index import build_index, index_db_path
from masora.providers import cppgraph_registry
from masora.sync import git_env

SYM_A = "scip-clang cxx . . mongo/Engine#start()."
SYM_B = "scip-clang cxx . . mongo/Engine#stop()."
SOURCE = """namespace mongo {
void Engine::start() {
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


def anchors_for(repo: Path, identities: list[str]) -> list[dict]:
    registry = cppgraph_registry(repo)
    try:
        return [
            {
                "provider": "code",
                "identity": identity,
                "fingerprint": registry.fingerprints("code", identity),
                "snapshot": registry.edges("code", identity),
            }
            for identity in identities
        ]
    finally:
        registry.close()


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "mongo").mkdir(parents=True)
    (repo / "mongo" / "engine.cpp").write_text(SOURCE, encoding="utf-8")
    repo.joinpath(".cppgraph").mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "src")
    head = git(repo, "rev-parse", "HEAD")
    write_graph(repo, head)
    return repo, head


def write_graph(repo: Path, commit: str, **kwargs) -> Path:
    from helpers import write_graph_db

    symbols = kwargs.pop(
        "symbols",
        {
            SYM_A: ("mongo/engine.cpp", 1, 4),
            SYM_B: ("mongo/engine.cpp", 5, 6),
        },
    )
    return write_graph_db(
        repo / ".cppgraph" / "repo.graph.db", commit=commit, symbols=symbols, **kwargs
    )


def make_base(name: str = "base", git_init: bool = True) -> Path:
    base_dir = bases_root() / name
    base_dir.mkdir(parents=True)
    if git_init:
        git(base_dir, "init", "-b", "main")
        git(base_dir, "config", "user.name", "Masora Test")
        git(base_dir, "config", "user.email", "masora@example.invalid")
        (base_dir / "base.toml").write_text('name = "test-base"\n', encoding="utf-8")
        git(base_dir, "add", "-A")
        git(base_dir, "commit", "-m", "init")
    return base_dir


def claim_event(uid: str, repo: Path, head: str, identities: list[str], **overrides) -> dict:
    return make_claim(
        uid,
        anchors=anchors_for(repo, identities),
        recorded_at={"commit": head, "graph_commit": head},
        **overrides,
    )


def facts(capsys, repo: Path, symbol: str | None = None) -> tuple[int, dict | None, str]:
    argv = ["facts", "--repo", str(repo)]
    if symbol is not None:
        argv += ["--symbol", symbol]
    code = main(argv)
    captured = capsys.readouterr()
    document = json.loads(captured.out) if captured.out.strip() else None
    return code, document, captured.err


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MASORA_HOME", str(home))
    return home


@pytest.fixture
def base(home) -> Path:
    base_dir = make_base()
    (home / "config.toml").write_text(
        'default_base = "base"\n\n[bases.base]\nremote = "git@github.internal:org/base.git"\n',
        encoding="utf-8",
    )
    return base_dir


def test_facts_happy_path_with_symbol(tmp_path, base, capsys):
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    vid = "01J8Z3K0000000000000000001"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    write_event(
        base,
        f"2026-09/x/{vid}.verify.md",
        make_verify(
            vid,
            uid,
            uid,
            verified_at={"commit": head, "graph_commit": head},
            snapshots={a["identity"]: a["snapshot"] for a in anchors_for(repo, [SYM_A])},
        ),
    )
    assert build_index(base, repo).errors == []

    code, document, err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0 and err == ""
    assert document["contract_version"] == 1
    assert document["repo_head"] == head
    assert document["graph_commit"] == head
    assert document["stale_warning"] is False
    (fact,) = document["facts"]
    assert fact["lineage"] == uid
    assert fact["summary"] == "One line summary"
    assert fact["resolution"] == "current"
    assert fact["verification"] == "verified(llm)"
    assert fact["flags"] == "-"
    assert fact["source"] == "llm"
    assert fact["name"] is None
    assert fact["effort"] is None
    assert fact["anchors"] == [SYM_A]
    assert fact["anchors_matched"] == [SYM_A]
    assert capsys.readouterr().out == ""


def test_facts_v2_provenance_and_full_anchor_list(tmp_path, base, capsys):
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(
        base,
        f"2026-09/x/{uid}.claim.md",
        claim_event(uid, repo, head, [SYM_A, SYM_B], name="glm-5p3-flash", effort="high"),
    )
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbol=SYM_B)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["source"] == "llm"
    assert fact["name"] == "glm-5p3-flash"
    assert fact["effort"] == "high"
    assert fact["anchors"] == [SYM_A, SYM_B]
    assert fact["anchors_matched"] == [SYM_B]


def test_facts_v2_human_name_present(tmp_path, base, capsys):
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(
        base,
        f"2026-09/x/{uid}.claim.md",
        claim_event(uid, repo, head, [SYM_A], source="human", name="Sebastien"),
    )
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["source"] == "human"
    assert fact["name"] == "Sebastien"
    assert fact["effort"] is None


def test_facts_stale_and_refuted_none_match_newest_version(tmp_path, base, capsys):
    repo, head = make_repo(tmp_path)
    stale_id = "01J8Z3K0000000000000000000"
    none_id = ULID_L2
    write_event(
        base,
        f"2026-09/x/{stale_id}.claim.md",
        claim_event(stale_id, repo, head, [SYM_A], summary="Stale claim"),
    )
    write_event(
        base,
        f"2026-09/x/{none_id}.claim.md",
        claim_event(none_id, repo, head, [SYM_A], summary="Refuted claim"),
    )
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000002.refute.md",
        make_doubt(
            "01J8Z3K0000000000000000002",
            none_id,
            none_id,
            kind="refute",
            source="human",
            reason="Provably wrong.",
        ),
    )
    (repo / "mongo" / "engine.cpp").write_text(
        SOURCE.replace("    stop();", "    halt();"), encoding="utf-8"
    )
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0
    by_lineage = {fact["lineage"]: fact for fact in document["facts"]}
    assert by_lineage[stale_id]["resolution"] == "stale"
    refuted = by_lineage[none_id]
    assert refuted["resolution"] == "none"
    assert refuted["summary"] == "Refuted claim"
    assert refuted["anchors_matched"] == [SYM_A]


def test_facts_without_symbol_returns_all_lineages(tmp_path, base, capsys):
    repo, head = make_repo(tmp_path)
    uid_a = "01J8Z3K0000000000000000000"
    uid_b = ULID_L2
    write_event(base, f"2026-09/x/{uid_a}.claim.md", claim_event(uid_a, repo, head, [SYM_A]))
    write_event(base, f"2026-09/x/{uid_b}.claim.md", claim_event(uid_b, repo, head, [SYM_B]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo)

    assert code == 0
    assert [fact["lineage"] for fact in document["facts"]] == sorted([uid_a, uid_b])
    assert all(fact["anchors_matched"] == [] for fact in document["facts"])
    assert all(fact["resolution"] == "current" for fact in document["facts"])


def test_facts_empty_base_exit_zero_and_uncomparable_stale_warning(tmp_path, home, capsys):
    plain_repo = tmp_path / "plain"
    plain_repo.mkdir()
    bare_base = make_base(git_init=False)
    (home / "config.toml").write_text(
        'default_base = "base"\n\n[bases.base]\nremote = "git@github.internal:org/base.git"\n',
        encoding="utf-8",
    )
    assert build_index(bare_base, plain_repo).errors == []

    code, document, _err = facts(capsys, plain_repo)

    assert code == 0
    assert document["facts"] == []
    assert document["repo_head"] is None
    assert document["stale_warning"] is None


def test_facts_missing_index_exit_one(tmp_path, base, capsys):
    repo, _head = make_repo(tmp_path)

    code, document, err = facts(capsys, repo)

    assert code == 1
    assert document is None and capsys.readouterr().out == ""
    assert "E-FACTS-NOINDEX" in err
    assert "masora index" in err


def test_facts_no_base_resolved_exit_one(tmp_path, home, capsys):
    repo, _head = make_repo(tmp_path)

    code, _document, err = facts(capsys, repo)

    assert code == 1
    assert capsys.readouterr().out == ""
    assert "E-FACTS-NO-BASE" in err


def test_facts_broken_mapping_exit_one(tmp_path, home, capsys):
    repo, _head = make_repo(tmp_path)
    git(repo, "remote", "add", "origin", "git@github.internal:org/proj.git")
    (home / "config.toml").write_text(
        '[[mappings]]\ncode_remote = "https://github.internal/org/proj.git"\nbases = ["team"]\n',
        encoding="utf-8",
    )

    code, _document, err = facts(capsys, repo)

    assert code == 1
    assert capsys.readouterr().out == ""
    assert "E-FACTS-NO-BASE" in err and "team" in err


def test_facts_mapping_resolves_base(tmp_path, home, capsys):
    repo, head = make_repo(tmp_path)
    git(repo, "remote", "add", "origin", "git@github.internal:org/proj.git")
    base_dir = make_base(name="team")
    uid = "01J8Z3K0000000000000000000"
    write_event(base_dir, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    assert build_index(base_dir, repo).errors == []
    (home / "config.toml").write_text(
        "[[mappings]]\n"
        'code_remote = "https://GitHub.internal/org/proj.git"\n'
        'bases = ["team"]\n\n'
        "[bases.team]\n"
        'remote = "git@github.internal:org/knowledge.git"\n',
        encoding="utf-8",
    )

    code, document, _err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["lineage"] == uid and fact["anchors_matched"] == [SYM_A]


def test_facts_stale_warning_true_after_repo_head_move(tmp_path, base, capsys):
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    assert build_index(base, repo).errors == []
    (repo / "mongo" / "extra.cpp").write_text("void extra() {}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "move head")

    code, document, _err = facts(capsys, repo)

    assert code == 0
    assert document["stale_warning"] is True
    assert document["repo_head"] != head


def test_facts_corrupt_index_exit_one(tmp_path, base, capsys):
    repo, _head = make_repo(tmp_path)
    db = index_db_path(base, repo)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"not sqlite" * 64)

    code, _document, err = facts(capsys, repo)

    assert code == 1
    assert capsys.readouterr().out == ""
    assert "E-IDX-CORRUPT" in err


def test_facts_repo_not_a_directory_exit_one(tmp_path, home, capsys):
    code, _document, err = facts(capsys, tmp_path / "missing")

    assert code == 1
    assert capsys.readouterr().out == ""
    assert "E-IDX-REPO" in err
