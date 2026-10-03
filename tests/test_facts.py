"""Tests for `masora facts` (the cppgraph injection contract, read-only CLI)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from helpers import OMIT, ULID_L2, make_claim, make_doubt, make_verify, write_event

from masora.cli import main
from masora.config import bases_root
from masora.facts import PRESENCE_HINT, _anchor_leaf
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
    (base_dir / "base.toml").write_text('name = "test-base"\ncode_remotes = []\n', encoding="utf-8")
    if git_init:
        git(base_dir, "init", "-b", "main")
        git(base_dir, "config", "user.name", "Masora Test")
        git(base_dir, "config", "user.email", "masora@example.invalid")
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


def facts(
    capsys, repo: Path, symbol: str | None = None, symbols: list[str] | None = None
) -> tuple[int, dict | None, str]:
    argv = ["facts", "--repo", str(repo)]
    if symbol is not None:
        argv += ["--symbol", symbol]
    for s in symbols or []:
        argv += ["--symbol", s]
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
    assert document["contract_version"] == 3
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
    assert fact["anchor_leaf"] == "start"
    # v2 context stamps: a fact established at HEAD is in_line, exact, no
    # fallback — the quiet case cppgraph renders without a context label
    assert fact["established_relation"] == "in_line"
    assert fact["established_commit"] == head[:12]
    assert fact["off_version"] is False
    assert fact["context_ordering"] == "exact"
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
    # the stale lineage's displayed version is established at HEAD
    # (HEAD-equal counts as in_line) — it stays stale, never off-version
    assert by_lineage[stale_id]["established_relation"] == "in_line"
    assert by_lineage[stale_id]["established_commit"] == head[:12]
    assert by_lineage[stale_id]["off_version"] is False
    refuted = by_lineage[none_id]
    assert refuted["resolution"] == "none"
    assert refuted["summary"] == "Refuted claim"
    assert refuted["anchors_matched"] == [SYM_A]
    # nothing displays for a none lineage: the stamps are null even though
    # summary/anchors still come from the newest version
    assert refuted["established_relation"] is None
    assert refuted["established_commit"] is None
    assert refuted["off_version"] is False


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


def test_facts_not_a_git_checkout_names_the_checkout_remedy(tmp_path, home, capsys):
    plain = tmp_path / "workspace"
    plain.mkdir()

    code, _document, err = facts(capsys, plain)

    assert code == 1
    assert capsys.readouterr().out == ""
    assert "E-FACTS-NO-BASE" in err
    assert "--repo is not a Git checkout" in err
    assert "run masora setup" not in err


def test_facts_without_origin_names_the_origin_remedy(tmp_path, home, capsys):
    repo, _head = make_repo(tmp_path)

    code, _document, err = facts(capsys, repo)

    assert code == 1
    assert capsys.readouterr().out == ""
    assert "E-FACTS-NO-BASE" in err
    assert "the checkout has no readable origin, so mapping-based resolution is unavailable" in err
    assert "pass base explicitly" not in err


def test_facts_unmapped_origin_keeps_the_setup_remedy(tmp_path, home, capsys):
    repo, _head = make_repo(tmp_path)
    git(repo, "remote", "add", "origin", "git@github.internal:org/unmapped.git")

    code, _document, err = facts(capsys, repo)

    assert code == 1
    assert capsys.readouterr().out == ""
    assert "E-FACTS-NO-BASE" in err
    assert "run masora setup --base <url>" in err
    assert "not a Git checkout" not in err


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


def test_facts_stale_warning_true_after_uncommitted_note(tmp_path, base, capsys):
    """The live-rollout freeze: a note written after the build moves no git HEAD."""
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo)
    assert code == 0
    assert document["stale_warning"] is False

    # an uncommitted write: the base git HEAD does not move, the mtime does;
    # push it past built_at + tolerance (the real gap is seconds, the
    # wall-clock here is milliseconds)
    fresh_uid = "01J8Z3K0000000000000000002"
    write_event(
        base,
        f"2026-09/x/{fresh_uid}.claim.md",
        claim_event(fresh_uid, repo, head, [SYM_A], summary="Fresh note"),
    )
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(f"file:{index_db_path(base, repo)}?mode=ro", uri=True)
    try:
        (raw,) = conn.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    finally:
        conn.close()
    built = datetime.fromisoformat(raw).timestamp()
    os.utime(base / f"2026-09/x/{fresh_uid}.claim.md", (built + 5, built + 5))

    code, document, _err = facts(capsys, repo)

    assert code == 0
    assert document["stale_warning"] is True
    assert document["repo_head"] == head  # the git axes stayed quiet — freshness fired

    # the synthetic future mtime would out-date the NEXT build too — pull it
    # back onto the build moment (a real file is never in the future)
    os.utime(base / f"2026-09/x/{fresh_uid}.claim.md", (built, built))
    assert build_index(base, repo).errors == []
    code, document, _err = facts(capsys, repo)
    assert code == 0
    assert document["stale_warning"] is False


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


def test_facts_shape_is_untouched_when_questions_present(tmp_path, home, capsys):
    repo, head = make_repo(tmp_path)
    git(repo, "remote", "add", "origin", "git@github.internal:org/proj.git")
    base_dir = make_base(name="team")
    uid = "01J8Z3K0000000000000000000"
    write_event(
        base_dir,
        f"2026-09/x/{uid}.claim.md",
        claim_event(uid, repo, head, [SYM_A], questions=["Where does invalidation happen?"]),
    )
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
    plain_base = make_base(name="plain")
    write_event(plain_base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    assert build_index(plain_base, repo).errors == []
    (home / "config.toml").write_text(
        "[[mappings]]\n"
        'code_remote = "https://GitHub.internal/org/proj.git"\n'
        'bases = ["plain"]\n\n'
        "[bases.plain]\n"
        'remote = "git@github.internal:org/knowledge.git"\n',
        encoding="utf-8",
    )
    _plain_code, plain_document, _err = facts(capsys, repo, symbol=SYM_A)
    (plain_fact,) = plain_document["facts"]

    assert set(fact) == set(plain_fact)
    assert document["contract_version"] == 3
    assert "questions" not in json.dumps(document)


def test_facts_shape_untouched_when_keywords_present(tmp_path, home, capsys):
    repo, head = make_repo(tmp_path)
    git(repo, "remote", "add", "origin", "git@github.internal:org/proj.git")
    base_dir = make_base(name="team")
    uid = "01J8Z3K0000000000000000000"
    write_event(
        base_dir,
        f"2026-09/x/{uid}.claim.md",
        claim_event(uid, repo, head, [SYM_A], keywords=["CSFLE"]),
    )
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
    assert document["contract_version"] == 3
    (fact,) = document["facts"]
    assert fact["lineage"] == uid
    assert "keywords" not in json.dumps(document)


def test_facts_v2_off_version_fact_is_out_of_line(tmp_path, base, capsys):
    """The not-applicable-here shape: the fact was established on a
    since-diverged line and its symbol does not exist on this checkout —
    the no-match fallback carries the provable out_of_line relation and the
    off_version flag, and the stamps serve it to cppgraph."""
    repo, _head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    git(repo, "checkout", "-b", "feature")
    (repo / "mongo" / "engine.cpp").write_text(
        SOURCE.replace("    stop();", "    halt();"), encoding="utf-8"
    )
    # stage ONLY the source: the graph store stays untracked (a checkout must
    # not clobber or carry it)
    git(repo, "add", "mongo/engine.cpp")
    git(repo, "commit", "-m", "feature")
    established = git(repo, "rev-parse", "HEAD")
    write_graph(repo, established)
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, established, [SYM_A]))
    git(repo, "checkout", "main")
    # main diverges AND the symbol is gone there: the anchor resolves
    # not_found (definitive absence — not a mere fingerprint mismatch)
    (repo / "mongo" / "engine.cpp").write_text(
        SOURCE.replace("void Engine::start() {\n    stop();\n    tick();\n}\n", ""),
        encoding="utf-8",
    )
    git(repo, "add", "mongo/engine.cpp")
    git(repo, "commit", "-m", "diverge")
    write_graph(repo, git(repo, "rev-parse", "HEAD"), symbols={SYM_B: ("mongo/engine.cpp", 4, 5)})
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["resolution"] == "stale"
    assert fact["established_relation"] == "out_of_line"
    assert fact["established_commit"] == established[:12]
    assert fact["off_version"] is True
    assert fact["context_ordering"] == "exact"
    # off_version is its own field, not a flag — suspect fires because the
    # anchored symbol is gone (the edge provider answers None on it)
    assert fact["flags"] == "suspect"


def test_facts_v2_degraded_ordering_with_an_in_line_display(tmp_path, base, capsys):
    """Two matching versions, the newest's establishing commit missing from
    the repo: the in_line version displays, but the unprovable context could
    change the selection — context_ordering is degraded while the stamps of
    the DISPLAYED version stay exact."""
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    vid = "01J8Z3K0000000000000000005"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    write_event(
        base,
        f"2026-09/x/{vid}.claim.md",
        claim_event(
            vid,
            repo,
            "ffffffffffffffffffffffffffffffffffffffff",
            [SYM_A],
            lineage=uid,
            reason="Second version.",
        ),
    )
    result = build_index(base, repo)
    assert result.errors == []

    code, document, _err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["lineage"] == uid
    assert fact["resolution"] == "current"
    assert fact["established_relation"] == "in_line"
    assert fact["established_commit"] == head[:12]
    assert fact["off_version"] is False
    assert fact["context_ordering"] == "degraded"


def test_facts_v2_unprovable_context_leaves_the_relation_null(tmp_path, base, capsys):
    """Nothing was proven (the establishing commit is missing from the repo):
    established_relation is null — a distinct, renderable state that is never
    silently read as in_line."""
    repo, _head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    # unanchored so the version matches whatever the checkout holds (an
    # unanchored lineage matches no --symbol, so the query runs unfiltered)
    write_event(
        base,
        f"2026-09/x/{uid}.claim.md",
        make_claim(
            uid,
            anchors=OMIT,
            unanchored=True,
            unanchored_reason="unprovable context test",
            recorded_at={
                "commit": "ffffffffffffffffffffffffffffffffffffffff",
                "graph_commit": None,
            },
        ),
    )
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["resolution"] == "current"
    assert fact["flags"] == "unanchored"
    assert fact["established_relation"] is None
    assert fact["established_commit"] == "ffffffffffff"  # SHORT: 12 chars
    assert fact["off_version"] is False
    assert fact["context_ordering"] == "exact"


def test_facts_v2_maps_relation_unknown_to_the_contract_enum(tmp_path, base, capsys):
    """The adapter's `relation_unknown` (not-in_line proven, the ahead probe
    failed) reaches the contract as `unknown` — test_gitctx.py covers its
    production; the index row is set directly here to pin the mapping."""
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    assert build_index(base, repo).errors == []
    conn = sqlite3.connect(index_db_path(base, repo))
    try:
        conn.execute("UPDATE versions SET relation = 'relation_unknown' WHERE version = ?", (uid,))
        conn.commit()
    finally:
        conn.close()

    code, document, _err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["established_relation"] == "unknown"
    assert fact["established_commit"] == head[:12]


def test_facts_repeated_symbol_or_matches_across_lineages(tmp_path, base, capsys):
    """One spawn for several symbols: lineages anchoring on ANY passed
    identity are returned, each carrying only the identities it matched."""
    repo, head = make_repo(tmp_path)
    uid_a = "01J8Z3K0000000000000000000"
    uid_b = ULID_L2
    write_event(base, f"2026-09/x/{uid_a}.claim.md", claim_event(uid_a, repo, head, [SYM_A]))
    write_event(base, f"2026-09/x/{uid_b}.claim.md", claim_event(uid_b, repo, head, [SYM_B]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbols=[SYM_A, SYM_B])

    assert code == 0
    assert document["contract_version"] == 3
    by_lineage = {fact["lineage"]: fact for fact in document["facts"]}
    assert sorted(by_lineage) == sorted([uid_a, uid_b])
    assert by_lineage[uid_a]["anchors_matched"] == [SYM_A]
    assert by_lineage[uid_b]["anchors_matched"] == [SYM_B]


def test_facts_repeated_symbol_same_lineage_accumulates_anchors_matched(tmp_path, base, capsys):
    """Two passed symbols anchoring the SAME lineage: one fact, the
    anchors_matched list carries both identities in call order."""
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A, SYM_B]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbols=[SYM_B, SYM_A])

    assert code == 0
    (fact,) = document["facts"]
    assert fact["lineage"] == uid
    assert fact["anchors_matched"] == [SYM_B, SYM_A]


def test_facts_repeated_symbol_filters_non_matching_lineages(tmp_path, base, capsys):
    """A lineage anchoring NONE of the passed symbols is filtered out, even
    as another matches — and a repeated duplicate symbol dedupes."""
    repo, head = make_repo(tmp_path)
    uid_a = "01J8Z3K0000000000000000000"
    uid_b = ULID_L2
    write_event(base, f"2026-09/x/{uid_a}.claim.md", claim_event(uid_a, repo, head, [SYM_A]))
    write_event(base, f"2026-09/x/{uid_b}.claim.md", claim_event(uid_b, repo, head, [SYM_B]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbols=[SYM_A, SYM_A])

    assert code == 0
    (fact,) = document["facts"]
    assert fact["lineage"] == uid_a
    assert fact["anchors_matched"] == [SYM_A]


def test_facts_repeated_symbol_keeps_the_v2_document_shape(tmp_path, base, capsys):
    """The richer CLI input changes nothing on the output contract: the
    per-lineage key set and contract_version are those of a single-symbol
    query."""
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A, SYM_B]))
    assert build_index(base, repo).errors == []

    _code, single, _err = facts(capsys, repo, symbol=SYM_A)
    _code, multi, _err = facts(capsys, repo, symbols=[SYM_A, SYM_B])

    assert multi["contract_version"] == 3
    assert list(multi) == list(single)
    (multi_fact,) = multi["facts"]
    (single_fact,) = single["facts"]
    assert set(multi_fact) == set(single_fact)
    assert multi_fact["anchors_matched"] == [SYM_A, SYM_B]
    assert single_fact["anchors_matched"] == [SYM_A]


# ---------------------------------------------------------------------------
# Contract v3: anchor_leaf, the matching counters, the presence hint
# ---------------------------------------------------------------------------

SYM_NO_HASH = "scip-clang cxx . . mongo/Engine."
SYM_NO_PARENS = "scip-clang cxx . . mongo/Util#tick."


def test_facts_anchor_leaf_derivation_rules():
    """The leaf is the segment after the last `#` (or last `/` without one),
    up to but excluding the `(` hash, trailing `.` stripped."""
    assert _anchor_leaf("scip-clang cxx . . mongo/Engine#commitShard().") == "commitShard"
    assert _anchor_leaf(SYM_NO_HASH) == "Engine"
    assert _anchor_leaf(SYM_NO_PARENS) == "tick"
    assert _anchor_leaf("scip-clang cxx . . mongo/Util#tick") == "tick"


def test_facts_v3_anchor_leaf_without_hash_identity(tmp_path, base, capsys):
    """An identity without `#` derives its leaf from the last `/` segment."""
    repo, head = make_repo(tmp_path)
    write_graph(repo, head, symbols={SYM_NO_HASH: ("mongo/engine.cpp", 1, 2)})
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_NO_HASH]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbol=SYM_NO_HASH)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["anchors_matched"] == [SYM_NO_HASH]
    assert fact["anchor_leaf"] == "Engine"


def test_facts_v3_anchor_leaf_multiple_matched_anchors_first_in_call_order(tmp_path, base, capsys):
    """Several passed symbols anchor the same lineage: the leaf is the FIRST
    matched anchor's, in call order (not the anchors list's order)."""
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A, SYM_B]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbols=[SYM_B, SYM_A])

    assert code == 0
    (fact,) = document["facts"]
    assert fact["anchors_matched"] == [SYM_B, SYM_A]
    assert fact["anchor_leaf"] == "stop"


def test_facts_v3_anchor_leaf_null_without_symbol(tmp_path, base, capsys):
    """Full enumeration keeps the unbound shape: no leaf, even though the
    anchors carry every identity the derivation could consume."""
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo)

    assert code == 0
    (fact,) = document["facts"]
    assert fact["anchors"] == [SYM_A]
    assert fact["anchor_leaf"] is None


def test_facts_v3_counters_filtered_query_examined_exceeds_matched(tmp_path, base, capsys):
    """A filtered query walks the whole lineage table but matches only some —
    the counters expose the difference cppgraph's zero-fact rule needs."""
    repo, head = make_repo(tmp_path)
    uid_a = "01J8Z3K0000000000000000000"
    uid_b = ULID_L2
    write_event(base, f"2026-09/x/{uid_a}.claim.md", claim_event(uid_a, repo, head, [SYM_A]))
    write_event(base, f"2026-09/x/{uid_b}.claim.md", claim_event(uid_b, repo, head, [SYM_B]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0
    assert document["lineages_examined"] == 2
    assert document["lineages_matched"] == 1
    assert document["lineages_matched"] == len(document["facts"])


def test_facts_v3_counters_unfiltered_examined_equals_matched(tmp_path, base, capsys):
    repo, head = make_repo(tmp_path)
    uid_a = "01J8Z3K0000000000000000000"
    uid_b = ULID_L2
    write_event(base, f"2026-09/x/{uid_a}.claim.md", claim_event(uid_a, repo, head, [SYM_A]))
    write_event(base, f"2026-09/x/{uid_b}.claim.md", claim_event(uid_b, repo, head, [SYM_B]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo)

    assert code == 0
    assert document["lineages_examined"] == 2
    assert document["lineages_matched"] == 2


def test_facts_v3_counters_and_presence_hint_on_empty_base(tmp_path, home, capsys):
    """An empty base walks nothing: zero examined, and the document carries
    the exact capability hint cppgraph renders verbatim."""
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
    assert document["lineages_examined"] == 0
    assert document["lineages_matched"] == 0
    assert document["presence_hint"] == (
        "masora: present for this checkout — the masora search / explain /"
        " list_stale MCP tools recall recorded knowledge."
    )
    assert PRESENCE_HINT == document["presence_hint"]


def test_facts_v3_presence_hint_null_when_facts_exist(tmp_path, base, capsys):
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0
    assert document["facts"]
    assert document["presence_hint"] is None


def test_facts_v3_presence_hint_null_on_error_paths(tmp_path, base, capsys):
    """The error exits keep today's behavior: nothing on stdout — no
    document, no hint (E-FACTS-NOINDEX; the other exits share the path)."""
    repo, _head = make_repo(tmp_path)

    code, document, err = facts(capsys, repo)

    assert code == 1
    assert "E-FACTS-NOINDEX" in err
    assert document is None
    assert PRESENCE_HINT not in capsys.readouterr().out + err


def test_facts_v3_doc_shape_v2_fields_still_present(tmp_path, base, capsys):
    """v3 is v2 PLUS the new fields: every v2 fact key and document key is
    still there, and the new fields ride alongside."""
    repo, head = make_repo(tmp_path)
    uid = "01J8Z3K0000000000000000000"
    write_event(base, f"2026-09/x/{uid}.claim.md", claim_event(uid, repo, head, [SYM_A]))
    assert build_index(base, repo).errors == []

    code, document, _err = facts(capsys, repo, symbol=SYM_A)

    assert code == 0
    assert document["contract_version"] == 3
    assert set(document) >= {
        "contract_version",
        "repo_head",
        "graph_commit",
        "stale_warning",
        "facts",
        "lineages_examined",
        "lineages_matched",
        "presence_hint",
    }
    (fact,) = document["facts"]
    assert set(fact) >= {
        "lineage",
        "summary",
        "resolution",
        "verification",
        "flags",
        "source",
        "name",
        "effort",
        "anchors",
        "anchors_matched",
        "established_relation",
        "established_commit",
        "off_version",
        "context_ordering",
        "anchor_leaf",
    }
