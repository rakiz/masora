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
)

from masora.cli import main
from masora.sync import git_env

CLAIM_V1 = "2026-09/x/01J8Z3K0000000000000000000.claim.md"
VERIFY_A = "2026-09/x/01J8Z3K0000000000000000001.verify.md"
CLAIM_V2 = "2026-09/x/01J8Z3K0000000000000000005.claim.md"
VERIFY_B = "2026-09/x/01J8Z3K0000000000000000006.verify.md"
DOUBT_D = "2026-09/x/01J8Z3K0000000000000000007.doubt.md"
REFUTE_R = "2026-09/x/01J8Z3K0000000000000000008.refute.md"
V2 = "01J8Z3K0000000000000000005"
VB = "01J8Z3K0000000000000000006"


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
