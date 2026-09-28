"""Docs/diagnostics sync — every exported diagnostic code must be documented.

The troubleshooting table (docs/TROUBLESHOOTING.md) is the human-facing
description of the error surface; these tests pin it to
masora/diagnostics.py in both directions so the two cannot diverge.
"""

from __future__ import annotations

import re
from pathlib import Path

from masora import diagnostics

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "docs" / "TROUBLESHOOTING.md"
README = ROOT / "README.md"

_CODE_RE = re.compile(r"`((?:E|W)-[A-Z0-9-]+)`")


def _exported_codes() -> set[str]:
    return {
        value
        for name, value in vars(diagnostics).items()
        if name.startswith(("E_", "W_")) and isinstance(value, str)
    }


def _documented_codes() -> set[str]:
    return set(_CODE_RE.findall(TABLE.read_text(encoding="utf-8")))


def test_every_exported_code_is_documented() -> None:
    missing = _exported_codes() - _documented_codes()
    assert not missing, f"diagnostic codes missing from docs/TROUBLESHOOTING.md: {sorted(missing)}"


def test_troubleshooting_table_has_no_phantom_code() -> None:
    phantom = _documented_codes() - _exported_codes()
    assert not phantom, (
        f"codes documented but not exported by masora/diagnostics.py: {sorted(phantom)}"
    )


def test_readme_links_the_troubleshooting_table() -> None:
    assert "docs/TROUBLESHOOTING.md" in README.read_text(encoding="utf-8")
