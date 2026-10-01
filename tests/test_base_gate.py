"""Tests for the base gate: every base-dir-taking command refuses a non-base root."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from helpers import ULID_L1, make_claim, write_event

from masora.cli import main
from masora.sync import git_env


@pytest.fixture
def masora_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "masora-home"
    home.mkdir()
    monkeypatch.setenv("MASORA_HOME", str(home))
    return home


@pytest.fixture
def checkout_root(tmp_path, monkeypatch) -> Path:
    """The exact rollout shape: a git repo root with stray .md files, no base.toml."""
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "README.md").write_text("# some code repo\n", encoding="utf-8")
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Masora Test")
    git(root, "config", "user.email", "masora@example.invalid")
    monkeypatch.chdir(root)
    return root


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


def tree_bytes(base: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(base)): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


def write_mapping_config(masora_home: Path, name: str, code_remote: str) -> Path:
    """A minimal valid base under the masora home, registered for `code_remote` by
    a [[mappings]] entry (the shape `masora setup` writes)."""
    base = masora_home / "bases" / name / "masora_mdb"
    base.mkdir(parents=True)
    (base / "base.toml").write_text(f'name = "{name}"\ncode_remotes = []\n', encoding="utf-8")
    (masora_home / "config.toml").write_text(
        "[[mappings]]\n"
        f'code_remote = "{code_remote}"\n'
        f'bases = ["{name}"]\n\n'
        f"[bases.{name}]\n"
        'remote = "git@github.internal:org/checkout.git"\n'
        'path = "masora_mdb"\n',
        encoding="utf-8",
    )
    return base


def test_check_refuses_a_git_repo_root_without_base_toml(checkout_root, capsys):
    code = main(["check", str(checkout_root)])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-NOT-A-BASE" in out
    assert f"not a base: no base.toml at {checkout_root}" in out


def test_gc_refuses_and_writes_nothing(checkout_root, capsys):
    before = tree_bytes(checkout_root)

    code = main(["gc", str(checkout_root), "--lineage", "01J8Z3K0000000000000000000", "--yes"])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-NOT-A-BASE" in out
    assert not (checkout_root / "deleted.toml").exists()
    assert tree_bytes(checkout_root) == before


def test_compact_refuses_and_writes_nothing(checkout_root, capsys):
    before = tree_bytes(checkout_root)

    code = main(["compact", str(checkout_root), "--yes"])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-NOT-A-BASE" in out
    assert not (checkout_root / "deleted.toml").exists()
    assert tree_bytes(checkout_root) == before


def test_index_refuses_and_builds_nothing(checkout_root, masora_home, capsys):
    code = main(["index", str(checkout_root), "--repo", str(checkout_root)])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-NOT-A-BASE" in out
    assert not (masora_home / "indexes").exists()


def test_search_refuses(checkout_root, capsys):
    code = main(["search", str(checkout_root), "anything"])

    assert code == 1
    assert "E-NOT-A-BASE" in capsys.readouterr().out


def test_remedy_names_the_base_configured_for_this_repo(checkout_root, masora_home, capsys):
    base = masora_home / "bases" / "employees"
    (base / "masora_mdb").mkdir(parents=True)
    (base / "base.toml").write_text('name = "Employees"\ncode_remotes = []\n', encoding="utf-8")
    (masora_home / "config.toml").write_text(
        "[[mappings]]\n"
        'code_remote = "github.internal/org/checkout.git"\n'
        'bases = ["employees"]\n\n'
        "[bases.employees]\n"
        'remote = "git@github.internal:org/checkout.git"\n'
        'path = "masora_mdb"\n',
        encoding="utf-8",
    )
    git(checkout_root, "remote", "add", "origin", "git@github.internal:org/checkout.git")

    code = main(["check", str(checkout_root)])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-NOT-A-BASE" in out
    assert f"the base configured for this repo: {base / 'masora_mdb'}" in out


def test_remedy_absent_when_no_mapping_resolves(checkout_root, capsys):
    code = main(["check", str(checkout_root)])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-NOT-A-BASE" in out
    assert "the base configured for this repo" not in out


def test_omitted_base_dir_resolves_the_configured_base(checkout_root, masora_home, capsys):
    """The friction: a base-taking command run with no path resolves the base from
    the checkout's masora configuration and runs against it."""
    git(checkout_root, "remote", "add", "origin", "git@github.internal:org/checkout.git")
    base = write_mapping_config(masora_home, "employees", "github.internal/org/checkout.git")

    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert f"masora check {base}" in out
    assert "clean: no errors, no warnings" in out


def test_omitted_base_dir_resolves_default_base(checkout_root, masora_home, capsys):
    """An origin-less checkout still resolves through `default_base` — the same
    semantics as the MCP write tools' resolution."""
    base = masora_home / "bases" / "solo" / "masora_mdb"
    base.mkdir(parents=True)
    (base / "base.toml").write_text('name = "solo"\ncode_remotes = []\n', encoding="utf-8")
    (masora_home / "config.toml").write_text(
        'default_base = "solo"\n\n'
        "[bases.solo]\n"
        'remote = "git@github.internal:org/checkout.git"\n'
        'path = "masora_mdb"\n',
        encoding="utf-8",
    )

    assert main(["check"]) == 0
    assert f"masora check {base}" in capsys.readouterr().out


def test_omitted_base_dir_refuses_when_nothing_resolves(checkout_root, masora_home, capsys):
    git(checkout_root, "remote", "add", "origin", "git@github.internal:org/checkout.git")

    code = main(["check"])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-NOT-A-BASE" in out
    assert "no [[mappings]] entry matches its origin remote" in out
    assert (
        "run masora setup --base <url> in this checkout, or pass the base directory explicitly"
        in out
    )
    assert "FAILED: 1 error(s)" in out


def test_explicit_base_dir_wins_over_the_configuration(checkout_root, masora_home, capsys):
    git(checkout_root, "remote", "add", "origin", "git@github.internal:org/checkout.git")
    configured = write_mapping_config(masora_home, "employees", "github.internal/org/checkout.git")
    explicit = checkout_root / "local-base"
    explicit.mkdir()
    (explicit / "base.toml").write_text('name = "local"\ncode_remotes = []\n', encoding="utf-8")

    assert main(["check", str(explicit)]) == 0
    out = capsys.readouterr().out
    assert f"masora check {explicit}" in out
    assert str(configured) not in out


def test_check_from_inside_a_base_directory_runs_it(
    checkout_root, masora_home, monkeypatch, capsys
):
    """Run from inside a base directory with no positional and no configured
    mapping: the command runs that base."""
    base = checkout_root / "the-base"
    base.mkdir()
    (base / "base.toml").write_text('name = "B"\ncode_remotes = []\n', encoding="utf-8")
    monkeypatch.chdir(base)

    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert f"masora check {base}" in out
    assert "E-NOT-A-BASE" not in out


def test_sync_from_inside_a_base_directory_runs_it(checkout_root, masora_home, monkeypatch, capsys):
    """Same default for sync: the gate resolves the hinted (cwd) base and sync
    is dispatched with it — the sync machinery never sees a refusal."""
    base = checkout_root / "the-base"
    base.mkdir()
    (base / "base.toml").write_text('name = "B"\ncode_remotes = []\n', encoding="utf-8")
    monkeypatch.chdir(base)
    captured: dict = {}

    def fake_sync(base_dir, **kwargs):
        captured["base"] = base_dir
        return 0

    monkeypatch.setattr("masora.cli.run_sync", fake_sync)

    assert main(["sync"]) == 0
    assert captured["base"] == base
    assert "E-NOT-A-BASE" not in capsys.readouterr().out


def test_the_hinted_base_beats_the_configuration(checkout_root, masora_home, monkeypatch, capsys):
    """Order: explicit positional > the hinted directory IS a base > the
    configuration chain — a base.toml in the hint dir wins over a mapping."""
    git(checkout_root, "remote", "add", "origin", "git@github.internal:org/checkout.git")
    configured = write_mapping_config(masora_home, "employees", "github.internal/org/checkout.git")
    here = checkout_root / "here-base"
    here.mkdir()
    (here / "base.toml").write_text('name = "here"\ncode_remotes = []\n', encoding="utf-8")
    monkeypatch.chdir(here)

    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert f"masora check {here}" in out
    assert str(configured) not in out


def test_omitted_base_dir_resolves_for_gc_compact_and_index(checkout_root, masora_home, capsys):
    """The shared gate resolution feeds every base-taking command: each runs
    against the resolved base (its header names it) instead of refusing."""
    git(checkout_root, "remote", "add", "origin", "git@github.internal:org/checkout.git")
    base = write_mapping_config(masora_home, "employees", "github.internal/org/checkout.git")
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000000.claim.md",
        make_claim(ULID_L1),
    )

    # An unknown-but-well-formed lineage proves gc ran on the resolved base
    # (the gate passed; the refusal would be E-NOT-A-BASE instead).
    assert main(["gc", "--lineage", "01J8Z3K0000000000000000001"]) == 1
    out = capsys.readouterr().out
    assert f"masora gc {base}" in out
    assert "E-GC-UNKNOWN" in out

    capsys.readouterr()
    assert main(["compact"]) == 0
    out = capsys.readouterr().out
    assert f"masora compact {base}" in out

    capsys.readouterr()
    assert main(["index", "--repo", str(checkout_root)]) == 0
    out = capsys.readouterr().out
    assert f"masora index {base}" in out


def test_a_freshly_inited_base_passes_the_gate(tmp_path, capsys):
    target = tmp_path / "fresh"

    assert main(["init", str(target), "--name", "Fresh"]) == 0
    capsys.readouterr()
    assert main(["check", str(target)]) == 0
    assert "E-NOT-A-BASE" not in capsys.readouterr().out


def test_the_write_path_precheck_refuses_a_non_base(tmp_path):
    from masora.write import WriteError, write_and_check

    stranger = tmp_path / "stranger"
    stranger.mkdir()
    with pytest.raises(WriteError) as exc:
        write_and_check(stranger, make_claim("01J8Z3K0000000000000000000"))
    assert exc.value.code == "E-NOT-A-BASE"


def test_a_valid_base_with_events_stays_green(checkout_root, capsys):
    base = checkout_root / "the-base"
    base.mkdir()
    (base / "base.toml").write_text('name = "B"\ncode_remotes = []\n', encoding="utf-8")
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000000.claim.md",
        make_claim("01J8Z3K0000000000000000000"),
    )

    assert main(["check", str(base)]) == 0
    assert "E-NOT-A-BASE" not in capsys.readouterr().out
