"""Tests for `masora init` (hermetic: MASORA_HOME sandbox, spawned git via git_env, no network)."""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from masora.cli import main
from masora.sync import REPO_LOCATION_ENV_VARS, git_env


@pytest.fixture
def masora_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "masora-home"
    home.mkdir()
    monkeypatch.setenv("MASORA_HOME", str(home))
    return home


@pytest.fixture
def git_identity(tmp_path, monkeypatch) -> Path:
    config = tmp_path / "gitconfig"
    config.write_text(
        "[user]\n    name = Masora Test\n    email = masora@example.invalid\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    return config


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


def test_init_happy_path(masora_home: Path, git_identity: Path, tmp_path: Path, capsys) -> None:
    dest = tmp_path / "team-query"

    assert main(["init", str(dest), "--name", "Team Query"]) == 0

    assert (dest / "base.toml").is_file()
    assert (dest / ".git").is_dir()
    data = tomllib.loads((dest / "base.toml").read_text(encoding="utf-8"))
    assert data == {"name": "Team Query", "code_remotes": []}
    assert f"masora setup --base {dest}" in capsys.readouterr().out
    assert not (masora_home / "config.toml").exists()

    assert main(["check", str(dest)]) == 0


def test_init_here_uses_the_current_directory(
    masora_home: Path, git_identity: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    cwd = tmp_path / "somewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    assert main(["init", "--here", "--name", "Solo"]) == 0

    assert (cwd / "base.toml").is_file()
    assert (cwd / ".git").is_dir()
    assert f"masora setup --base {cwd}" in capsys.readouterr().out


def test_init_refuses_non_empty_directory(
    masora_home: Path, git_identity: Path, tmp_path: Path, capsys
) -> None:
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "notes.txt").write_text("keep\n", encoding="utf-8")

    assert main(["init", str(dest), "--name", "X"]) == 1

    assert "E-INIT-TARGET" in capsys.readouterr().out
    assert not (dest / "base.toml").exists()
    assert not (dest / ".git").exists()
    assert (dest / "notes.txt").is_file()


def test_init_force_allows_a_non_empty_directory(
    masora_home: Path, git_identity: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "notes.txt").write_text("keep\n", encoding="utf-8")

    assert main(["init", str(dest), "--name", "X", "--force"]) == 0

    assert (dest / "base.toml").is_file()
    assert (dest / "notes.txt").is_file()
    assert git(dest, "log", "--format=%s") == "masora init: base X"


def test_init_refuses_an_existing_base_even_with_force(
    masora_home: Path, git_identity: Path, tmp_path: Path, capsys
) -> None:
    dest = tmp_path / "already"
    assert main(["init", str(dest), "--name", "First"]) == 0
    before = (dest / "base.toml").read_text(encoding="utf-8")

    assert main(["init", str(dest), "--name", "Second"]) == 1
    assert main(["init", str(dest), "--name", "Second", "--force"]) == 1

    assert "E-INIT-TARGET" in capsys.readouterr().out
    assert (dest / "base.toml").read_text(encoding="utf-8") == before
    assert git(dest, "rev-list", "--count", "HEAD") == "1"


def test_init_normalizes_and_deduplicates_code_remotes(
    masora_home: Path, git_identity: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "served"

    assert (
        main(
            [
                "init",
                str(dest),
                "--name",
                "Served",
                "--code-remote",
                "https://GitHub.com/Org/Repo.git/",
                "--code-remote",
                "https://GitHub.com/Org/Repo",
                "--code-remote",
                "git@github.internal:org/other.git",
            ]
        )
        == 0
    )

    data = tomllib.loads((dest / "base.toml").read_text(encoding="utf-8"))
    assert data["code_remotes"] == ["github.com/Org/Repo", "github.internal/org/other"]


def test_init_commits_base_toml_on_main(
    masora_home: Path, git_identity: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "committed"

    assert main(["init", str(dest), "--name", "Team Query"]) == 0

    assert git(dest, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(dest, "log", "--format=%s") == "masora init: base Team Query"
    assert git(dest, "ls-files") == "base.toml"


def test_init_git_failure_is_a_clean_error(
    masora_home: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    empty = tmp_path / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    dest = tmp_path / "no-identity"

    assert main(["init", str(dest), "--name", "X"]) == 1

    assert "E-INIT-GIT" in capsys.readouterr().out
    assert (dest / "base.toml").is_file()
    assert (dest / ".git").is_dir()


def test_init_argument_refusals(
    masora_home: Path, git_identity: Path, tmp_path: Path, capsys
) -> None:
    dest = tmp_path / "args"
    for argv in (
        ["init", str(dest), "--name", "   "],
        ["init", str(dest), "--name", "X", "--code-remote", "https://"],
        ["init", "--name", "X"],
        ["init", str(dest), "--name", "X", "--here"],
    ):
        assert main(argv) == 1
        assert "E-INIT-ARG" in capsys.readouterr().out
    assert not dest.exists()


def test_init_requires_a_name(masora_home: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["init", str(tmp_path / "x")])
    assert excinfo.value.code == 2


def test_init_git_spawns_immune_to_inherited_git_env(
    masora_home: Path, git_identity: Path, tmp_path: Path, monkeypatch
) -> None:
    bogus = tmp_path / "bogus.index"
    for name in REPO_LOCATION_ENV_VARS:
        monkeypatch.setenv(name, str(bogus))
    dest = tmp_path / "immune"

    assert main(["init", str(dest), "--name", "X"]) == 0

    assert (dest / "base.toml").is_file()
    assert not bogus.exists()


def test_init_output_points_at_the_skill(
    masora_home: Path, git_identity: Path, tmp_path: Path, capsys
) -> None:
    dest = tmp_path / "skill-hint"

    assert main(["init", str(dest), "--name", "Team Query"]) == 0

    out = capsys.readouterr().out
    assert "docs/skills/masora/SKILL.md" in out
    assert not (dest / "docs").exists()
