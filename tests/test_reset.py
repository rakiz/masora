"""Tests for `masora reset --from-origin` (plan/confirm flow per test_gc idioms:
real local git, a bare origin, no network)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from helpers import ULID_L1, make_claim, write_event

from masora.checker import check_base
from masora.cli import main
from masora.reset import run as reset_run
from masora.sync import git_env

CLAIM_REL = "2026-09/x/01J8Z3K0000000000000000000.claim.md"


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


def seed(base: Path, message: str = "seed") -> None:
    git(base, "add", "-A")
    git(base, "commit", "--allow-empty", "-m", message)
    git(base, "push", "origin", "main")


def tree_bytes(base: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(base)): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


@pytest.fixture
def repo(tmp_path) -> tuple[Path, Path]:
    tmp = tmp_path
    base = tmp / "base"
    base.mkdir()
    git(base, "init", "-b", "main")
    git(base, "config", "user.name", "Masora Test")
    git(base, "config", "user.email", "masora@example.invalid")
    origin = tmp / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    git(base, "remote", "add", "origin", str(origin))
    (base / "base.toml").write_text('name = "test-base"\n', encoding="utf-8")
    seed(base, "init")
    return base, origin


def test_reset_plan_prints_discards_and_exits_3(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    seed(base, "with events")
    git(base, "add", "-A")
    git(base, "commit", "--allow-empty", "-m", "local only 1")
    git(base, "commit", "--allow-empty", "-m", "local only 2")
    before = tree_bytes(base)

    code = reset_run(base)

    assert code == 3
    out = capsys.readouterr().out
    assert "local-only commit(s) will be discarded" in out
    assert "discard" in out and "local only 1" in out and "local only 2" in out
    assert "refoundation or an attack" in out
    assert "plan only: nothing written" in out
    assert tree_bytes(base) == before


def test_reset_refuses_a_dirty_working_tree(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))  # uncommitted
    before = tree_bytes(base)

    code = reset_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-RESET-DIRTY" in out
    assert "commit or discard" in out
    assert tree_bytes(base) == before


def test_reset_refuses_missing_origin_main(repo, capsys):
    base, origin = repo
    # an origin whose history was replaced by an empty (branchless) repo
    fresh = origin.parent / "fresh-origin.git"
    subprocess.run(["git", "init", "--bare", str(fresh)], capture_output=True, check=True)
    git(base, "remote", "set-url", "origin", str(fresh))

    code = reset_run(base)

    assert code == 1
    assert "E-RESET-NO-MAIN" in capsys.readouterr().out


def test_reset_yes_resets_main_to_origin(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    seed(base, "with events")
    git(base, "commit", "--allow-empty", "-m", "local only")

    code = reset_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "reset: local 'main' is now at" in out
    assert "masora index" in out and "masora check" in out
    assert git(base, "rev-parse", "HEAD") == git(base, "rev-parse", "origin/main")
    assert check_base(base).errors == []


def test_reset_yes_drops_local_only_commits_from_main(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    seed(base, "with events")
    git(base, "commit", "--allow-empty", "-m", "local divergence 2")

    code = reset_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "discard" in out and "local divergence 2" in out
    assert git(base, "rev-parse", "HEAD") == git(base, "rev-parse", "origin/main")
    assert "local divergence 2" not in git(base, "log", "--oneline", "main")


def test_reset_cli_wiring_plan_then_yes(repo, capsys):
    base, _origin = repo
    git(base, "commit", "--allow-empty", "-m", "local only")

    assert main(["reset", str(base), "--from-origin"]) == 3
    assert main(["reset", str(base), "--from-origin", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "plan only: nothing written" in out
    assert "reset: local 'main' is now at" in out


def test_reset_fetch_failure_is_a_fail(repo, capsys, monkeypatch):
    base, _origin = repo
    import masora.reset as reset_module

    class Boom:
        returncode = 128
        stderr = "fatal: could not reach origin"
        stdout = ""

    monkeypatch.setattr(reset_module, "run_git", lambda *a, **k: Boom())

    code = reset_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-RESET-FETCH" in out
    assert "could not reach origin" in out
