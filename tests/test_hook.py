"""Tests for `masora hook` (SessionStart freshness hook: install + behavior)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import ULID_L1, make_claim, write_event

from masora.cli import main
from masora.hook import run as hook_run
from masora.hook import script_text, session_start
from masora.index import build_index, index_stale


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """EVERY test here runs against a throwaway MASORA_HOME — the hook must
    never touch the real ~/.local/share/masora or the real config."""
    home = tmp_path / "home-root" / "home"
    home.mkdir(parents=True)
    monkeypatch.setenv("MASORA_HOME", str(home))
    yield home
    monkeypatch.delenv("MASORA_HOME", raising=False)


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def make_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    return home


def write_config(home: Path, **bases: dict) -> None:
    lines = []
    for name, entry in bases.items():
        lines.append(f"[bases.{name}]")
        for key, value in entry.items():
            lines.append(f'{key} = "{value}"')
    (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_base(home: Path, origin: Path, name: str = "test") -> Path:
    base = home / "bases" / name
    subprocess.run(["git", "clone", str(origin), str(base)], capture_output=True, check=True)
    git(base, "config", "user.name", "Masora Test")
    git(base, "config", "user.email", "masora@example.invalid")
    return base


def make_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True)
    return origin


def push_seed(base: Path, message: str = "seed") -> None:
    git(base, "add", "-A")
    git(base, "commit", "-m", message)
    git(base, "push", "origin", "main")


# --- install ---


def test_install_writes_script_and_claude_settings(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()

    assert hook_run(None, home=home) == 0

    script = home / ".claude/hooks/masora_session_start.py"
    assert script.is_file()
    assert script.read_text(encoding="utf-8") == script_text()
    settings = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["SessionStart"]
    assert len(entries) == 1
    assert "masora_session_start.py" in entries[0]["hooks"][0]["command"]


def test_install_is_idempotent(tmp_path, capsys):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()

    assert hook_run(None, home=home) == 0
    assert hook_run(None, home=home) == 0

    out = capsys.readouterr().out
    assert out.count("installed: ") == 2  # script + settings, first run
    assert out.count("updated: ") == 2  # second run: same count, no duplicate
    settings = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
    assert len(settings["hooks"]["SessionStart"]) == 1


def test_install_preserves_foreign_settings_keys(tmp_path):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()
    settings = home / ".claude/settings.json"
    settings.write_text(json.dumps({"model": "opus", "hooks": {}}), encoding="utf-8")

    assert hook_run("claude", home=home) == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "opus"
    assert len(data["hooks"]["SessionStart"]) == 1


def test_install_unwritable_settings_prints_snippet(tmp_path, capsys):
    home = make_home(tmp_path)
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text("not json at all", encoding="utf-8")

    assert hook_run("claude", home=home) == 0

    out = capsys.readouterr().out
    # The script is installed, the registration degrades to the snippet —
    # never a traceback, never a broken settings file.
    assert (home / ".claude/hooks/masora_session_start.py").is_file()
    assert "manual snippet" in out
    assert "SessionStart" in out
    assert "not json at all" == (home / ".claude/settings.json").read_text(encoding="utf-8")


def test_install_opencode_prints_the_manual_snippet(tmp_path, capsys):
    home = make_home(tmp_path)
    (home / ".config" / "opencode").mkdir(parents=True)

    assert hook_run(None, home=home) == 0

    out = capsys.readouterr().out
    assert (home / ".config/opencode/hooks/masora_session_start.py").is_file()
    assert (home / ".config/opencode/hooks/masora_session_start.py").read_text(
        encoding="utf-8"
    ) == script_text()
    assert "manual step" in out
    assert "SessionStart" in out


def test_install_without_homes_says_so(tmp_path, capsys):
    home = make_home(tmp_path)

    assert hook_run(None, home=home) == 0

    out = capsys.readouterr().out
    assert "no agent-framework directory found" in out
    assert not (home / ".claude").exists()


def test_install_explicit_target_creates_it(tmp_path, capsys):
    home = make_home(tmp_path)

    assert hook_run("claude", home=home) == 0

    assert (home / ".claude/hooks/masora_session_start.py").is_file()


def test_cli_hook_unknown_target_is_refused(capsys):
    try:
        main(["hook", "install", "--target", "carrier"])
    except SystemExit as exc:
        assert exc.code != 0
    assert "masora_session_start" not in capsys.readouterr().out


# --- behavior (the shipped script's session_start) ---


def base_scenario(tmp_path: Path):
    """A configured home (the autouse fixture's MASORA_HOME) with one base
    clone + one code repo, the base pushed to its origin with one
    file-anchored claim, and a built index."""
    home = Path(os.environ["MASORA_HOME"])
    origin = make_origin(tmp_path)
    code = tmp_path / "code"
    code.mkdir()
    git(code, "init", "-b", "main")
    git(code, "config", "user.name", "Dev")
    git(code, "config", "user.email", "dev@example.invalid")
    (code / "a.txt").write_text("one\n", encoding="utf-8")
    git(code, "add", "-A")
    git(code, "commit", "-m", "one")
    (code / ".cppgraph").mkdir()

    base = make_base(home, origin)
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000000.claim.md",
        make_claim(ULID_L1),
    )
    push_seed(base)
    (base / "base.toml").write_text('name = "test"\n', encoding="utf-8")
    push_seed(base, "base.toml")

    write_config(home, test={"remote": str(origin)})
    build_index(base, code)
    return home, origin, base, code


def test_hook_fast_forwards_the_base(tmp_path):
    _home, origin, base, _code = base_scenario(tmp_path)
    # A second writer publishes a commit; the clone is behind.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(origin), str(other)], capture_output=True, check=True)
    (other / "base.toml").write_text('name = "test"\n# touched\n', encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-m", "upstream")
    git(other, "push", "origin", "main")
    behind = git(base, "rev-parse", "HEAD")

    assert session_start() == 0

    assert git(base, "rev-parse", "HEAD") != behind
    assert git(base, "rev-parse", "HEAD") == git(origin, "rev-parse", "refs/heads/main")


def test_hook_skips_a_diverged_base_silently(tmp_path, capsys):
    _home, _origin, base, _code = base_scenario(tmp_path)
    # Diverge the clone: a local commit origin never saw (a fetch + ff-only
    # merge cannot land it — and must never force or rebase).
    (base / "base.toml").write_text('name = "test"\n# local\n', encoding="utf-8")
    git(base, "add", "-A")
    git(base, "commit", "-m", "local")
    diverged = git(base, "rev-parse", "HEAD")

    assert session_start() == 0

    # The pull is skipped silently (no force, no rebase) — but the hook still
    # reports/rebuilds the clone's index staleness, in at most ONE line.
    assert git(base, "rev-parse", "HEAD") == diverged
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) <= 1
    for line in lines:
        assert line.startswith("masora: ")


def test_hook_rebuilds_a_stale_index_and_prints_one_summary_line(tmp_path, capsys):
    _home, _origin, base, code = base_scenario(tmp_path)
    # Move the CODE repo: the index's code-HEAD axis goes stale, and the
    # anchored file changed, so the rebuilt index reports the lineage stale.
    (code / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    git(code, "add", "-A")
    git(code, "commit", "-m", "two")
    assert index_stale(index_db(base, code), base, code) is True

    assert session_start() == 0

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line]
    assert len(lines) == 1
    assert lines[0].startswith("masora: ")
    assert "stale lineage(s)" in lines[0]
    assert index_stale(index_db(base, code), base, code) is False


def index_db(base: Path, code: Path) -> Path:
    from masora.index import index_db_path

    return index_db_path(base, code)


def test_hook_prints_nothing_when_fresh(tmp_path, capsys):
    base_scenario(tmp_path)

    assert session_start() == 0
    assert capsys.readouterr().out == ""


def test_hook_silent_failure_garbage_config(tmp_path, capsys):
    home = make_home(tmp_path)
    (home / "config.toml").write_text("not [valid toml", encoding="utf-8")

    assert session_start() == 0
    assert capsys.readouterr().out == ""


def test_hook_exception_in_one_base_never_fails_the_run(tmp_path, capsys, monkeypatch):
    import masora.hook as hook_mod

    base_scenario(tmp_path)
    # The FIRST base explodes; the hook still completes and exits 0.
    monkeypatch.setattr(
        hook_mod, "_fast_forward", lambda base_dir: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert session_start() == 0
    assert "boom" not in capsys.readouterr().out


def test_shipped_script_runs_standalone(tmp_path, capsys):
    """End-to-end: the INSTALLED script, executed by a bare python, behaves —
    here against an empty home (nothing configured): exit 0, no output."""
    home = make_home(tmp_path)
    script = tmp_path / "installed.py"
    script.write_text(script_text(), encoding="utf-8")
    import os

    env = dict(os.environ, MASORA_HOME=str(home))
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, env=env, check=False
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_shipped_script_carries_the_section_10_1_caps_pointer():
    text = script_text()
    assert "§10.1" in text


def test_hook_module_carries_the_named_caps():
    import masora.hook as hook_mod

    assert hook_mod.REBUILD_BUDGET_S > 0
    assert hook_mod.HOOK_GIT_TIMEOUT_S > 0
    source = Path(hook_mod.__file__).read_text(encoding="utf-8")
    assert "§10.1" in source
