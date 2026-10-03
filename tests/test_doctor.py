"""Tests for `masora doctor` (hermetic: MASORA_HOME sandbox, injected gh check
and base fetch — NO real network, NO real gh)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from helpers import ULID_L1, make_claim, write_event, write_graph_db

from masora import doctor
from masora.cli import main
from masora.index import build_index, index_db_path

REMOTE = "git@github.internal:org/knowledge.git"
CODE_REMOTE = "https://github.internal/org/proj.git"
CONFIG = (
    f'[bases.team]\nremote = "{REMOTE}"\n\n'
    "[[mappings]]\n"
    f'code_remote = "{CODE_REMOTE}"\n'
    'bases = ["team"]\n'
)
GITCONFIG = "[user]\n\tname = Masora Test\n\temail = masora@example.invalid\n"


def ok_gh():
    return True, True, "authenticated"


def ok_fetch(clone: Path) -> tuple[bool, str]:
    return True, ""


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "masora-home"
    path.mkdir()
    monkeypatch.setenv("MASORA_HOME", str(path))
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(GITCONFIG, encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    return path


@pytest.fixture
def clone(home) -> Path:
    path = home / "bases" / "team"
    path.mkdir(parents=True)
    (path / "base.toml").write_text('name = "test-base"\ncode_remotes = []\n', encoding="utf-8")
    import subprocess

    from masora.sync import git_env

    subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "remote", "add", "origin", REMOTE],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    return path


@pytest.fixture(autouse=True)
def fake_fetch(monkeypatch):
    """The doctor's one network operation is injected for every test that goes
    through the CLI — no test ever contacts a real remote."""
    monkeypatch.setattr(doctor, "_fetch_origin", lambda clone: (True, ""))


def configure(home: Path, text: str = CONFIG) -> None:
    (home / "config.toml").write_text(text, encoding="utf-8")


def run_doctor(gh=ok_gh, fetch=ok_fetch) -> tuple[int, str]:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = doctor.run(gh_checker=gh, fetcher=fetch)
    return code, buffer.getvalue()


def test_doctor_all_healthy(home, clone, capsys):
    configure(home)
    code = main(["doctor"])
    assert code == 0
    out = capsys.readouterr().out
    assert "OK: masora" in out
    assert "OK: config found and parsed" in out
    assert "OK: git user.name" in out and "OK: git user.email" in out
    assert f"OK: origin remote matches the configuration: {REMOTE}" in out
    assert "OK: git fetch origin succeeded" in out
    assert "OK: gh CLI: authenticated" in out
    assert "doctor: OK — 0 failing check(s)" in out


def test_doctor_no_config_is_a_warn_not_a_fail(home, capsys):
    code = main(["doctor"])
    assert code == 0
    out = capsys.readouterr().out
    assert "WARN: no masora config" in out
    assert "masora setup --base <url>" in out


def test_doctor_unparseable_config_fails(home, capsys):
    (home / "config.toml").write_text("not toml [", encoding="utf-8")
    code = main(["doctor"])
    assert code == 1
    assert "FAIL: the config at" in capsys.readouterr().out


def test_doctor_missing_git_identity_fails(home, monkeypatch, capsys):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    code = main(["doctor"])
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL: git user.name is not set" in out
    assert "FAIL: git user.email is not set" in out
    assert "git config --global" in out


def test_doctor_missing_clone_fails(home, capsys):
    configure(home)
    code = main(["doctor"])
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL: the base clone directory is missing" in out
    assert "masora setup --base <url>" in out


def test_doctor_origin_mismatch_fails(home, clone, capsys):
    configure(home, CONFIG.replace(REMOTE, "git@github.internal:org/other.git"))
    code = main(["doctor"])
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL: the clone's origin remote" in out
    assert "does not match the configured remote" in out


def test_doctor_unreadable_base_toml_fails(home, clone, capsys):
    configure(home)
    (clone / "base.toml").write_text("not toml [", encoding="utf-8")
    code = main(["doctor"])
    assert code == 1
    assert "FAIL: base.toml cannot be read" in capsys.readouterr().out


def test_doctor_fetch_failure_fails_with_the_exit_message(home, clone):
    configure(home)

    def failing(clone: Path) -> tuple[bool, str]:
        return False, "Could not resolve host"

    code, out = run_doctor(fetch=failing)
    assert code == 1
    assert "FAIL: git fetch origin failed: Could not resolve host" in out


def test_doctor_gh_missing_is_a_warn_not_a_fail(home, clone):
    configure(home)

    def missing():
        return False, False, "gh is not on PATH"

    code, out = run_doctor(gh=missing)
    assert code == 0
    assert "WARN: gh CLI is not available" in out
    assert "gh is optional" in out


def test_doctor_gh_unauthenticated_is_a_warn(home, clone):
    configure(home)

    def unauth():
        return True, False, "not logged in"

    code, out = run_doctor(gh=unauth)
    assert code == 0
    assert "WARN: gh is present but not authenticated" in out
    assert "gh auth login" in out


def test_doctor_missing_index_is_a_warn_with_the_build_remedy(home, clone, capsys):
    configure(home)
    repo = home / "code"
    repo.mkdir()
    code = main(["doctor"])
    assert code == 0
    out = capsys.readouterr().out
    assert f"WARN: index for {clone}: missing" in out
    assert "masora index <base-dir> --repo <code-checkout>" in out


def test_doctor_fresh_index_is_ok(home, clone, capsys):
    configure(home)
    repo = home / "code"
    repo.mkdir()
    build_index(clone, repo, no_cppgraph=True)
    code = main(["doctor"])
    assert code == 0
    assert "OK: index for" in capsys.readouterr().out


def test_doctor_stale_index_is_a_warn_with_the_axis_reason(home, clone, capsys):
    configure(home)
    repo = home / "code"
    repo.mkdir()
    db = index_db_path(clone, repo)
    build_index(clone, repo, no_cppgraph=True)
    write_event(clone, "2026-09/x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    connection = sqlite3.connect(db)
    connection.execute("UPDATE meta SET value = '2000-01-01T00:00:00+00:00' WHERE key = 'built_at'")
    connection.commit()
    connection.close()
    code = main(["doctor"])
    assert code == 0
    out = capsys.readouterr().out
    assert "WARN: index for" in out
    assert "events written since the index build" in out
    assert f"masora index {clone} --repo {repo}" in out


def test_doctor_graph_absent_is_a_warn(home, clone, capsys):
    configure(home)
    repo = home / "code"
    repo.mkdir()
    build_index(clone, repo, no_cppgraph=True)
    code = main(["doctor"])
    assert code == 0
    out = capsys.readouterr().out
    assert "WARN: no cppgraph graph store" in out
    assert "cppgraph is optional" in out


def test_doctor_graph_current_is_ok_and_behind_is_a_warn(home, clone, capsys):
    configure(home)
    repo = home / "code"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "a.cpp").write_text("int f() { return 1; }\n", encoding="utf-8")
    import subprocess

    from masora.sync import git_env

    subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True, check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t.invalid",
            "commit",
            "-m",
            "src",
        ],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    build_index(clone, repo, no_cppgraph=True)
    write_graph_db(
        repo / ".cppgraph" / "repo.graph.db",
        commit=head,
        symbols={"scip-clang cxx . . f": ("src/a.cpp", 1, 1)},
        calls=[],
    )
    code = main(["doctor"])
    assert code == 0
    out = capsys.readouterr().out
    assert "OK: cppgraph graph store" in out

    # a graph indexed at another commit warns (report-only — cppgraph is a
    # separate tool), never fails
    write_graph_db(
        repo / ".cppgraph" / "behind.graph.db",
        commit="0" * 40,
        symbols={"scip-clang cxx . . f": ("src/a.cpp", 1, 1)},
        calls=[],
    )
    (repo / ".cppgraph" / "behind.graph.db").touch()
    import os

    os.utime(repo / ".cppgraph" / "behind.graph.db", (2_000_000_000, 2_000_000_000))
    buffer_code = main(["doctor"])
    assert buffer_code == 0
    assert "WARN: the graph store" in capsys.readouterr().out


def test_doctor_mutates_nothing(home, clone):
    configure(home)
    repo = home / "code"
    repo.mkdir()
    write_event(clone, "2026-09/x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    build_index(clone, repo, no_cppgraph=True)

    def snapshot(root: Path) -> dict[str, bytes]:
        # sqlite's -shm/-wal sidecars are read side effects of the doctor's
        # read-only index opens, not doctor writes — excluded.
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.name.endswith(("-shm", "-wal"))
        }

    before_clone, before_home = snapshot(clone), snapshot(home)
    code, _out = run_doctor()
    assert code == 0
    assert snapshot(clone) == before_clone
    assert snapshot(home) == before_home
