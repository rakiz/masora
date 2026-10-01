"""Tests for `masora skill` (packaged skill, detected agent homes, print)."""

from __future__ import annotations

from importlib import resources

from masora.cli import main
from masora.skill import _command_text, _skill_text
from masora.skill import run as skill_run


def packaged() -> str:
    return (resources.files("masora") / "skills/masora/SKILL.md").read_text(encoding="utf-8")


def packaged_command() -> str:
    return (resources.files("masora") / "skills/masora/COMMAND.md").read_text(encoding="utf-8")


def test_install_writes_both_detected_homes(tmp_path, capsys):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".config" / "opencode").mkdir(parents=True)

    code = skill_run("install", home=tmp_path)

    assert code == 0
    out = capsys.readouterr().out
    for target in (
        tmp_path / ".claude/skills/masora/SKILL.md",
        tmp_path / ".config/opencode/skills/masora/SKILL.md",
    ):
        assert target.is_file(), target
        assert target.read_text(encoding="utf-8") == packaged()
        assert f"installed: {target}" in out


def test_install_skips_absent_frameworks(tmp_path, capsys):
    (tmp_path / ".claude").mkdir()

    code = skill_run("install", home=tmp_path)

    assert code == 0
    out = capsys.readouterr().out
    assert (tmp_path / ".claude/skills/masora/SKILL.md").is_file()
    assert f"installed: {tmp_path / '.claude/skills/masora/SKILL.md'}" in out
    assert not (tmp_path / ".config").exists()
    assert out.count("installed:") == 1


def test_install_overwrites_on_rerun(tmp_path, capsys):
    (tmp_path / ".claude").mkdir()
    target = tmp_path / ".claude" / "skills" / "masora" / "SKILL.md"

    assert skill_run("install", home=tmp_path) == 0
    stale = "stale content"
    target.write_text(stale, encoding="utf-8")

    assert skill_run("install", home=tmp_path) == 0

    out = capsys.readouterr().out
    assert f"updated: {target}" in out
    assert target.read_text(encoding="utf-8") == packaged()


def test_install_without_frameworks_says_so_and_points_at_print(tmp_path, capsys):
    code = skill_run("install", home=tmp_path)

    assert code == 0
    out = capsys.readouterr().out
    assert "no agent-framework directory found" in out
    assert "masora skill print" in out
    assert not (tmp_path / ".claude").exists()


def test_install_writes_the_opencode_command_file(tmp_path, capsys):
    (tmp_path / ".config" / "opencode").mkdir(parents=True)

    code = skill_run("install", home=tmp_path)

    assert code == 0
    target = tmp_path / ".config/opencode/commands/masora.md"
    out = capsys.readouterr().out
    assert target.is_file(), target
    assert target.read_text(encoding="utf-8") == packaged_command()
    assert _command_text() == packaged_command()
    assert f"installed: {target}" in out


def test_install_writes_no_command_file_without_opencode(tmp_path, capsys):
    (tmp_path / ".claude").mkdir()

    code = skill_run("install", home=tmp_path)

    assert code == 0
    out = capsys.readouterr().out
    assert (tmp_path / ".claude/skills/masora/SKILL.md").is_file()
    assert not list((tmp_path / ".claude").rglob("masora.md"))
    assert "commands" not in out


def test_install_without_frameworks_writes_no_command_file(tmp_path, capsys):
    code = skill_run("install", home=tmp_path)

    assert code == 0
    out = capsys.readouterr().out
    assert "no agent-framework directory found" in out
    assert not (tmp_path / ".config").exists()


def test_print_outputs_the_packaged_content(tmp_path, capsys):
    code = skill_run("print", home=tmp_path)

    assert code == 0
    assert capsys.readouterr().out == packaged()


def test_cli_skill_print_and_install(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()

    assert main(["skill", "print"]) == 0
    printed = capsys.readouterr().out
    assert printed == packaged()
    assert main(["skill", "install"]) == 0
    assert (tmp_path / ".claude/skills/masora/SKILL.md").read_text(encoding="utf-8") == printed


def test_the_wheel_carries_the_skill_file():
    resource = resources.files("masora") / "skills/masora/SKILL.md"
    text = resource.read_text(encoding="utf-8")
    assert text.startswith("---\nname: masora\n")
    assert "## The ritual" in text
    assert _skill_text() == text
