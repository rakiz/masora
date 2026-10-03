"""Tests for `masora explain` (the one-lineage story: fresh fold, statuses included)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from helpers import (
    ULID_L1,
    make_claim,
    make_doubt,
    make_verify,
    write_event,
    write_graph_db,
)

from masora.cli import main
from masora.providers import cppgraph_registry
from masora.sync import git_env

CLAIM_V1 = "2026-09/x/01J8Z3K0000000000000000000.claim.md"
VERIFY_A = "2026-09/x/01J8Z3K0000000000000000001.verify.md"
CLAIM_V2 = "2026-09/x/01J8Z3K0000000000000000005.claim.md"
VERIFY_B = "2026-09/x/01J8Z3K0000000000000000006.verify.md"
DOUBT_D = "2026-09/x/01J8Z3K0000000000000000007.doubt.md"
REFUTE_R = "2026-09/x/01J8Z3K0000000000000000008.refute.md"
V2 = "01J8Z3K0000000000000000005"
VB = "01J8Z3K0000000000000000006"

SYM_A = "scip-clang cxx . . mongo/Engine#start()."
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


@pytest.fixture
def story_base(tmp_path) -> Path:
    base = tmp_path / "base"
    base.mkdir()
    (base / "base.toml").write_text('name = "b"\ncode_remotes = []\n', encoding="utf-8")
    write_event(
        base,
        CLAIM_V1,
        make_claim(ULID_L1, questions=["Where does resume-token invalidation happen?"]),
    )
    write_event(
        base,
        VERIFY_A,
        make_verify(
            "01J8Z3K0000000000000000001",
            ULID_L1,
            ULID_L1,
            evidence=["replay: 3 edges", "tests: shard_key_change"],
        ),
    )
    write_event(
        base,
        CLAIM_V2,
        make_claim(
            V2,
            lineage=ULID_L1,
            reason="v2 after code change",
            questions=["Where does invalidation happen?"],
        ),
    )
    write_event(
        base,
        VERIFY_B,
        make_verify(VB, ULID_L1, V2, evidence=["replay: 5 edges, expected 5"]),
    )
    write_event(base, DOUBT_D, make_doubt("01J8Z3K0000000000000000007", ULID_L1, VB))
    write_event(
        base, REFUTE_R, make_doubt("01J8Z3K0000000000000000008", ULID_L1, ULID_L1, kind="refute")
    )
    return base


def test_explain_tells_the_whole_story(story_base, capsys):
    code = main(["explain", str(story_base), ULID_L1])

    assert code == 0
    out = capsys.readouterr().out
    assert f"lineage {ULID_L1}" in out
    assert "status: unknown verified(llm) flags: doubted, unknown" in out
    assert f"displayed version: {V2}" in out
    assert "summary: One line summary" in out
    assert "statement: Full statement." in out
    assert "- Where does invalidation happen?" in out
    assert "events (6, oldest first):" in out
    assert f"{ULID_L1} claim (llm) — founder: One line summary [refuted]" in out
    assert "01J8Z3K0000000000000000001 verify (llm) — verified: One line summary" in out
    assert f"{V2} claim (llm) — v2+: One line summary" in out
    assert "01J8Z3K0000000000000000007 doubt (human) — doubted: One line summary" in out
    assert "01J8Z3K0000000000000000008 refute (human) — refuted: One line summary" in out
    assert f"active verify evidence ({VB}):" in out
    assert "- replay: 5 edges, expected 5" in out
    assert "  anchors:" in out
    assert "— unknown" in out


def test_explain_unknown_lineage_is_a_clean_diagnostic(story_base, capsys):
    code = main(["explain", str(story_base), "01J8Z3K0000000000000000009"])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-EXPLAIN-UNKNOWN" in out
    assert "01J8Z3K0000000000000000009" in out
    assert not (story_base / "2026-10").exists()


def test_explain_on_a_non_base_refuses(tmp_path, capsys):
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    (stranger / "README.md").write_text("# not a base\n", encoding="utf-8")

    code = main(["explain", str(stranger), ULID_L1])

    assert code == 1
    assert "E-NOT-A-BASE" in capsys.readouterr().out


def test_explain_refuted_lineage_shows_the_not_state(story_base, capsys):
    refute_v2 = "2026-09/x/01J8Z3K0000000000000000009.refute.md"
    write_event(
        story_base,
        refute_v2,
        make_doubt("01J8Z3K0000000000000000009", ULID_L1, V2, kind="refute"),
    )

    code = main(["explain", str(story_base), ULID_L1])

    assert code == 0
    out = capsys.readouterr().out
    assert "status: none" in out
    assert "displayed version: none" in out
    assert f"{ULID_L1} claim (llm) — founder: One line summary [refuted]" in out
    assert f"{V2} claim (llm) — v2+: One line summary [refuted]" in out
    assert "active verify evidence" not in out


def test_explain_shows_the_off_version_field_without_a_repo(story_base, capsys):
    """off-version is its own labeled field, never folded into the flags;
    without a repo nothing is provable and no context ordering renders."""
    code = main(["explain", str(story_base), ULID_L1])

    assert code == 0
    out = capsys.readouterr().out
    assert "  off-version: no" in out
    assert "  context:" not in out


def _anchors_for(repo: Path, identities: list[str]) -> list[dict]:
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


def _graph_at(repo: Path, commit: str, symbols: dict) -> None:
    write_graph_db(repo / ".cppgraph" / "repo.graph.db", commit=commit, symbols=symbols)


def test_explain_surfaces_the_live_git_context(tmp_path, capsys):
    """With a repo the git context is re-derived live with a fresh budget:
    a claim established on a since-diverged feature line whose symbol is
    gone on main is the provably out_of_line fallback — off-version: yes,
    context exact, and the claim line carries the relation."""
    repo = tmp_path / "repo"
    (repo / "mongo").mkdir(parents=True)
    (repo / "mongo" / "engine.cpp").write_text(SOURCE, encoding="utf-8")
    repo.joinpath(".cppgraph").mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "src")
    base = tmp_path / "base"
    base.mkdir()
    (base / "base.toml").write_text('name = "b"\ncode_remotes = []\n', encoding="utf-8")
    # the claim is established on the feature line, with the graph at its HEAD
    git(repo, "checkout", "-b", "feature")
    (repo / "mongo" / "engine.cpp").write_text(
        SOURCE.replace("    stop();", "    halt();"), encoding="utf-8"
    )
    git(repo, "add", "mongo/engine.cpp")
    git(repo, "commit", "-m", "feature")
    established = git(repo, "rev-parse", "HEAD")
    _graph_at(repo, established, {SYM_A: ("mongo/engine.cpp", 1, 4)})
    write_event(
        base,
        CLAIM_V1,
        make_claim(
            ULID_L1,
            anchors=_anchors_for(repo, [SYM_A]),
            recorded_at={"commit": established, "graph_commit": established},
        ),
    )
    # main diverges AND drops the symbol: definitive absence + out_of_line
    git(repo, "checkout", "main")
    (repo / "mongo" / "engine.cpp").write_text(
        SOURCE.replace("void Engine::start() {\n    stop();\n    tick();\n}\n", ""),
        encoding="utf-8",
    )
    git(repo, "add", "mongo/engine.cpp")
    git(repo, "commit", "-m", "diverge")
    _graph_at(repo, git(repo, "rev-parse", "HEAD"), {})

    code = main(["explain", str(base), ULID_L1, "--repo", str(repo)])

    assert code == 0
    out = capsys.readouterr().out
    assert "status: stale unverified flags: suspect" in out
    assert "  off-version: yes" in out
    assert "  context: exact" in out
    assert f"{ULID_L1} claim (llm) — founder: One line summary [established: out_of_line]" in out


def test_explain_reports_degraded_ordering(tmp_path, capsys):
    """An unprovable v2 could outrank the in_line v1: the fresh context
    ordering is degraded and the displayed version's own relation surfaces."""
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
    _graph_at(repo, head, {SYM_A: ("mongo/engine.cpp", 1, 4)})
    base = tmp_path / "base"
    base.mkdir()
    (base / "base.toml").write_text('name = "b"\ncode_remotes = []\n', encoding="utf-8")
    write_event(
        base,
        CLAIM_V1,
        make_claim(
            ULID_L1,
            anchors=_anchors_for(repo, [SYM_A]),
            recorded_at={"commit": head, "graph_commit": head},
        ),
    )
    write_event(
        base,
        CLAIM_V2,
        make_claim(
            V2,
            lineage=ULID_L1,
            reason="v2",
            anchors=_anchors_for(repo, [SYM_A]),  # matching: it could win the line
        ),  # establishing commit unknown to the repo
    )

    code = main(["explain", str(base), ULID_L1, "--repo", str(repo)])

    assert code == 0
    out = capsys.readouterr().out
    assert "  context: degraded" in out
    assert "  off-version: no" in out
    assert f"displayed version: {ULID_L1}" in out
    assert f"{ULID_L1} claim (llm) — founder: One line summary [established: in_line]" in out


# --- Phase 4: an event ULID resolves to its lineage; the registry handle closes


def test_explain_on_an_event_ulid_tells_the_lineage_story(story_base, capsys):
    """LOW: a verify/doubt/refute ULID names its lineage — the story is the
    lineage's, never an empty render."""
    code = main(["explain", str(story_base), VB])

    assert code == 0
    out = capsys.readouterr().out
    assert f"lineage {ULID_L1}" in out
    assert f"displayed version: {V2}" in out
    assert "events (6, oldest first):" in out


def test_explain_closes_the_graph_registry_handle(story_base, monkeypatch):
    """M6: the cppgraph sqlite handle opened for the anchor render is closed
    when the story is built."""
    from masora import explain as explain_mod

    closed = {"n": 0}

    class SpyRegistry:
        available = True
        graph_commit = None
        fingerprints = None
        edges = None

        def close(self):
            closed["n"] += 1

    monkeypatch.setattr(explain_mod, "cppgraph_registry", lambda repo: SpyRegistry())
    story = explain_mod.explain_lineage(story_base, ULID_L1, repo=Path("."))
    assert "lineage " in story
    assert closed["n"] == 1
