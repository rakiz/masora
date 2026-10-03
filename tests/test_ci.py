"""Tests for `masora ci` (packaged reusable CI check workflow template)."""

from __future__ import annotations

from importlib import resources

from masora.ci import run as ci_run
from masora.ci import template_text
from masora.cli import main


def test_the_wheel_carries_the_template():
    resource = resources.files("masora") / "templates/masora-check.yml"
    text = resource.read_text(encoding="utf-8")
    assert template_text() == text
    assert "workflow_call" in text
    assert "masora check" in text


def test_ci_print_outputs_the_packaged_template(capsys):
    assert ci_run("print") == 0
    assert capsys.readouterr().out == template_text()


def test_ci_template_documents_the_union_rescue_and_read_only_ci():
    text = template_text()
    assert "masora union" in text
    assert "CI stays" in text or "CI is" in text or "read-only" in text


def test_cli_ci_print(capsys):
    assert main(["ci", "print"]) == 0
    assert capsys.readouterr().out == template_text()
