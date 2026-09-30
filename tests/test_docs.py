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


SKILL = ROOT / "docs" / "skills" / "masora" / "SKILL.md"
AGENT_INSTRUCTIONS = ROOT / "docs" / "AGENT_INSTRUCTIONS.md"

_HEADERS_RE = re.compile(r"^#{1,2} .+$", re.MULTILINE)


def test_skill_carries_every_agent_instructions_header() -> None:
    skill_text = SKILL.read_text(encoding="utf-8")
    canonical = AGENT_INSTRUCTIONS.read_text(encoding="utf-8")
    missing = [h for h in _HEADERS_RE.findall(canonical) if h not in skill_text]
    assert not missing, f"skill is missing the canonical headers: {missing}"


def test_skill_frontmatter_triggers_on_project_knowledge_only() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\nname: masora\n")
    assert (
        "repository-specific behavior, architecture, product semantics, past decisions,"
        " trade-offs, or non-obvious conventions" in text
    )
    assert "Not for general programming tasks" in text


def test_skill_ritual_is_conditional() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "MAY be served" in text
    assert "It is NOT evidence that this project has no knowledge" in text
    assert "Never inspect the checkout for Masora markers" in text
    assert "Never re-run `masora setup` on your own" in text
    assert "Continue normally" in text
    assert "This repository is served" not in text.split("## Tools")[0]


def test_agent_instructions_carry_the_graph_first_anchor_discipline() -> None:
    text = AGENT_INSTRUCTIONS.read_text(encoding="utf-8")
    assert "Locate symbols with the code graph (cppgraph `find`/`explain`), never by" in text
    assert "When delegating research to sub-agents, hand them the graph entry points" in text
    skill_text = SKILL.read_text(encoding="utf-8")
    assert "hand them the graph entry points" in skill_text


def test_agent_instructions_carry_the_atomic_claims_rule() -> None:
    rule = (
        'One claim = one fact. If you wrote "and" twice, that is several claims: split them;'
        " each fact gets its own anchors and its own verification — a block claim is"
        " all-or-nothing to verify, to stale and to refute."
    )

    def flat(text: str) -> str:
        return " ".join(text.split())

    assert rule in flat(AGENT_INSTRUCTIONS.read_text(encoding="utf-8"))
    assert rule in flat(SKILL.read_text(encoding="utf-8"))
