"""Tests for `masora setup` (real git repos in tmp_path, MASORA_HOME sandbox, no network)."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest
from helpers import ULID_L1, make_claim, write_event

from masora.cli import main
from masora.config import bases_root, config_path, normalize_remote
from masora.setup import run as setup_run
from masora.sync import REPO_LOCATION_ENV_VARS, git_env

CLAIM_REL = "2026-09/x/01J8Z3K0000000000000000000.claim.md"
BASE_TOML = 'name = "Team Query"\ncode_remotes = ["https://GitHub.com/MongoDB/Mongo.git"]\n'


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


def make_origin(
    tmp_path: Path, name: str, subdir: str | None = None, base_toml: str = BASE_TOML
) -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    where = repo / subdir if subdir else repo
    where.mkdir(parents=True, exist_ok=True)
    (where / "base.toml").write_text(base_toml, encoding="utf-8")
    write_event(repo, (f"{subdir}/" if subdir else "") + CLAIM_REL, make_claim(ULID_L1))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "seed")
    return repo


@pytest.fixture
def masora_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "masora-home"
    home.mkdir()
    monkeypatch.setenv("MASORA_HOME", str(home))
    return home


@pytest.fixture
def origin(tmp_path) -> Path:
    return make_origin(tmp_path, "query-knowledge")


def test_setup_root_base(masora_home: Path, origin: Path) -> None:
    spec = f"file://{origin}"

    code = setup_run(spec)

    assert code == 0
    dest = masora_home / "bases" / "query-knowledge"
    assert (dest / ".git").is_dir()
    assert (dest / "base.toml").is_file()
    assert (dest / CLAIM_REL).is_file()
    assert (masora_home / "config.toml").read_text(encoding="utf-8") == (
        "[bases.query-knowledge]\n"
        f'remote = "file://{origin}"\n'
        'branch = "main"\n'
        "\n[[mappings]]\n"
        'code_remote = "github.com/MongoDB/Mongo"\n'
        'bases = ["query-knowledge"]\n'
    )


def test_setup_subdir_base_sparse_checkout(masora_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "employees"
    make_origin(
        tmp_path,
        "employees",
        subdir="rakiz/knowledge",
        base_toml='name = "Employees"\ncode_remotes = ["git@github.internal:org/query.git"]\n',
    )
    (repo / "other").mkdir()
    (repo / "other" / "notes.txt").write_text("distractor\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "distractor")
    spec = f"file://{repo}#rakiz/knowledge"

    code = setup_run(spec)

    assert code == 0
    dest = masora_home / "bases" / "employees"
    assert (dest / "rakiz" / "knowledge" / "base.toml").is_file()
    assert (dest / "rakiz" / "knowledge" / CLAIM_REL).is_file()
    assert not (dest / "other").exists()
    assert (masora_home / "config.toml").read_text(encoding="utf-8") == (
        "[bases.employees]\n"
        f'remote = "file://{repo}"\n'
        'path = "rakiz/knowledge"\n'
        'branch = "main"\n'
        "\n[[mappings]]\n"
        'code_remote = "github.internal/org/query"\n'
        'bases = ["employees"]\n'
    )


def test_setup_idempotent_rerun(masora_home: Path, origin: Path) -> None:
    spec = f"file://{origin}"
    assert setup_run(spec) == 0
    config_first = (masora_home / "config.toml").read_text(encoding="utf-8")
    dest = masora_home / "bases" / "query-knowledge"
    (dest / "marker.txt").write_text("sentinel\n", encoding="utf-8")

    assert setup_run(spec) == 0

    assert (dest / "marker.txt").is_file()
    assert (masora_home / "config.toml").read_text(encoding="utf-8") == config_first


def test_setup_preserves_existing_config(masora_home: Path, origin: Path) -> None:
    config = masora_home / "config.toml"
    config.write_text(
        'default_base = "perso"\n'
        "\n[bases.perso]\n"
        'remote = "git@github.internal:org/employees.git"\n'
        'branch = "main"\n'
        "\n[[mappings]]\n"
        'code_remote = "github.com/other/repo"\n'
        'bases = ["perso"]\n',
        encoding="utf-8",
    )

    assert setup_run(f"file://{origin}") == 0

    text = config.read_text(encoding="utf-8")
    assert 'default_base = "perso"' in text
    assert "[bases.perso]" in text
    assert 'remote = "git@github.internal:org/employees.git"' in text
    assert 'code_remote = "github.com/other/repo"' in text
    assert 'bases = ["perso"]' in text
    assert 'code_remote = "github.com/MongoDB/Mongo"' in text
    assert 'bases = ["query-knowledge"]' in text


def test_setup_merges_slug_into_existing_mapping(masora_home: Path, origin: Path) -> None:
    config = masora_home / "config.toml"
    config.write_text(
        '[[mappings]]\ncode_remote = "github.com/MongoDB/Mongo"\nbases = ["perso"]\n',
        encoding="utf-8",
    )

    assert setup_run(f"file://{origin}") == 0

    text = config.read_text(encoding="utf-8")
    assert 'bases = ["perso", "query-knowledge"]' in text
    assert text.count("[[mappings]]") == 1


def test_setup_refuses_duplicate_slug_different_remote(masora_home: Path, tmp_path: Path) -> None:
    first = make_origin(tmp_path / "one", "query-knowledge")
    second = make_origin(tmp_path / "two", "query-knowledge")
    config = masora_home / "config.toml"
    assert setup_run(f"file://{first}") == 0
    before = config.read_text(encoding="utf-8")

    code = setup_run(f"file://{second}")

    assert code == 1
    assert config.read_text(encoding="utf-8") == before


def test_setup_clone_failure(masora_home: Path, capsys) -> None:
    code = setup_run("file:///definitely/not/a/repo")

    assert code == 1
    assert "E-SETUP-CLONE" in capsys.readouterr().out
    assert not (masora_home / "config.toml").exists()


def test_setup_missing_base_toml(masora_home: Path, tmp_path: Path, capsys) -> None:
    repo = tmp_path / "not-a-base"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    git(repo, "commit", "--allow-empty", "-m", "seed")

    code = setup_run(f"file://{repo}")

    assert code == 1
    assert "E-SETUP-NO-TOML" in capsys.readouterr().out
    assert not (masora_home / "config.toml").exists()


def test_setup_invalid_base_toml(masora_home: Path, tmp_path: Path, capsys) -> None:
    garbage = make_origin(tmp_path, "garbage", base_toml="not [valid toml\n")
    wrong_schema = make_origin(
        tmp_path, "wrong-schema", base_toml='name = "X"\ncode_remote = ["github.com/o/r"]\n'
    )

    assert setup_run(f"file://{garbage}") == 1
    assert "E-SETUP-SCHEMA" in capsys.readouterr().out
    assert setup_run(f"file://{wrong_schema}") == 1
    assert "E-SETUP-SCHEMA" in capsys.readouterr().out
    assert not (masora_home / "config.toml").exists()


def test_setup_config_not_writable(masora_home: Path, origin: Path, capsys) -> None:
    (masora_home / "config.toml").mkdir(parents=True)

    code = setup_run(f"file://{origin}")

    assert code == 1
    assert "E-SETUP-WRITE" in capsys.readouterr().out


def test_setup_existing_config_invalid_toml(masora_home: Path, origin: Path, capsys) -> None:
    (masora_home / "config.toml").write_text("not [valid\n", encoding="utf-8")

    code = setup_run(f"file://{origin}")

    assert code == 1
    assert "E-SETUP-CONFIG" in capsys.readouterr().out


def test_setup_existing_config_unserializable_value(
    masora_home: Path, origin: Path, capsys
) -> None:
    (masora_home / "config.toml").write_text("remember = 2026-09-25\n", encoding="utf-8")

    code = setup_run(f"file://{origin}")

    assert code == 1
    assert "E-SETUP-CONFIG" in capsys.readouterr().out


def test_setup_argument_parsing(masora_home: Path, origin: Path, capsys) -> None:
    for spec in ("", f"file://{origin}#", "#rakiz/knowledge", f"file://{origin}#../outside"):
        assert setup_run(spec) == 1
        assert "E-SETUP-ARG" in capsys.readouterr().out
    assert not (masora_home / "bases").exists()
    assert not (masora_home / "config.toml").exists()


def test_setup_git_spawns_immune_to_inherited_git_env(
    masora_home: Path, origin: Path, tmp_path: Path, monkeypatch
) -> None:
    bogus = tmp_path / "bogus.index"
    for name in REPO_LOCATION_ENV_VARS:
        monkeypatch.setenv(name, str(bogus))

    assert setup_run(f"file://{origin}") == 0

    assert (masora_home / "bases" / "query-knowledge" / "base.toml").is_file()
    assert not bogus.exists()


def test_setup_cli_command(masora_home: Path, origin: Path, capsys) -> None:
    assert main(["setup", "--base", f"file://{origin}"]) == 0
    assert "config written" in capsys.readouterr().out
    with pytest.raises(SystemExit) as excinfo:
        main(["setup"])
    assert excinfo.value.code == 2


def test_setup_into_existing_empty_directory(masora_home: Path, origin: Path) -> None:
    dest = masora_home / "bases" / "query-knowledge"
    dest.mkdir(parents=True)

    assert setup_run(f"file://{origin}") == 0

    assert (dest / ".git").is_dir()
    assert (dest / "base.toml").is_file()
    assert (dest / CLAIM_REL).is_file()
    assert (masora_home / "config.toml").is_file()


def test_setup_roundtrips_non_bare_keys(masora_home: Path, origin: Path) -> None:
    config = masora_home / "config.toml"
    config.write_text(
        '["my base"]\n"code.remote" = "github.com/other/repo"\n',
        encoding="utf-8",
    )

    assert setup_run(f"file://{origin}") == 0

    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert data == {
        "my base": {"code.remote": "github.com/other/repo"},
        "bases": {"query-knowledge": {"remote": f"file://{origin}", "branch": "main"}},
        "mappings": [{"code_remote": "github.com/MongoDB/Mongo", "bases": ["query-knowledge"]}],
    }


def test_setup_dot_fragments_refused(masora_home: Path, origin: Path, capsys) -> None:
    for fragment in (".", "./"):
        assert setup_run(f"file://{origin}#{fragment}") == 1
        assert "E-SETUP-ARG" in capsys.readouterr().out
    assert not (masora_home / "bases").exists()
    assert not (masora_home / "config.toml").exists()


def test_setup_subdir_trailing_slash_normalized(masora_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "employees"
    make_origin(
        tmp_path,
        "employees",
        subdir="rakiz/knowledge",
        base_toml='name = "Employees"\ncode_remotes = ["git@github.internal:org/query.git"]\n',
    )

    assert setup_run(f"file://{repo}#rakiz/knowledge/") == 0

    assert (masora_home / "bases" / "employees" / "rakiz" / "knowledge" / "base.toml").is_file()
    assert (masora_home / "config.toml").read_text(encoding="utf-8") == (
        "[bases.employees]\n"
        f'remote = "file://{repo}"\n'
        'path = "rakiz/knowledge"\n'
        'branch = "main"\n'
        "\n[[mappings]]\n"
        'code_remote = "github.internal/org/query"\n'
        'bases = ["employees"]\n'
    )


def test_normalize_remote() -> None:
    cases = {
        "https://GitHub.com/Org/Repo.git/": "github.com/Org/Repo",
        "HTTPS://GitHub.com/Org/Repo.GIT": "github.com/Org/Repo",
        "git@github.internal:org/employees.git": "github.internal/org/employees",
        "git@host:repo.git": "host/repo",
        "ssh://git@Host:2222/org/repo.git": "host/2222/org/repo",
        "file:///Users/x/origin": "/Users/x/origin",
        "/Users/x/origin": "/Users/x/origin",
        "github.com/mongodb/mongo": "github.com/mongodb/mongo",
        "github.com/mongodb/mongo.git": "github.com/mongodb/mongo",
        "some/local/dir": "some/local/dir",
        "https://GitHub.com/Org/Repo": "github.com/Org/Repo",
    }
    for url, expected in cases.items():
        assert normalize_remote(url) == expected, url


def test_config_paths_default_and_env_override(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("MASORA_HOME", raising=False)
    assert config_path() == fake_home / ".config" / "masora" / "config.toml"
    assert bases_root() == fake_home / ".local" / "share" / "masora" / "bases"

    home = tmp_path / "masora-home"
    monkeypatch.setenv("MASORA_HOME", str(home))
    assert config_path() == home / "config.toml"
    assert bases_root() == home / "bases"


def test_setup_output_points_at_the_skill_and_writes_nothing_into_the_origin(
    masora_home: Path, origin: Path, capsys
) -> None:
    spec = f"file://{origin}"
    before = git(origin, "status", "--porcelain")

    code = setup_run(spec)

    assert code == 0
    out = capsys.readouterr().out
    assert "docs/skills/masora/SKILL.md" in out
    assert "masora never writes into your code repo" in out
    assert git(origin, "status", "--porcelain") == before
    assert not (origin / "docs").exists()
