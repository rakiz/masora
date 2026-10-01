"""Docs/diagnostics sync — every exported diagnostic code must be documented.

The troubleshooting table (docs/TROUBLESHOOTING.md) is the human-facing
description of the error surface; these tests pin it to
masora/diagnostics.py in both directions so the two cannot diverge.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from masora import diagnostics

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "docs" / "TROUBLESHOOTING.md"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"

_CODE_RE = re.compile(r"`((?:E|W)-[A-Z0-9-]+)`")
_HEADERS_RE = re.compile(r"^#{1,2} .+$", re.MULTILINE)


def _changelog_headers() -> list[tuple[str, int]]:
    """The `## ` section headers of CHANGELOG.md as (header, 1-based line number).

    HTML comments are stripped first — the entry template at the bottom lives
    inside one and must not trip the guards; line numbers are preserved by
    replacing each comment with the newlines it held.
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    without_comments = re.sub(
        r"(?s)<!--.*?-->", lambda match: "\n" * match.group(0).count("\n"), text
    )
    return [
        (line.strip(), number)
        for number, line in enumerate(without_comments.splitlines(), start=1)
        if line.startswith("## ")
    ]


def _version_triplet(header: str) -> tuple[int, int, int] | None:
    match = re.match(r"## v?(\d+)\.(\d+)\.(\d+)", header)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


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


SKILL_PATH = "skills/masora/SKILL.md"
AGENT_INSTRUCTIONS = ROOT / "docs" / "AGENT_INSTRUCTIONS.md"


def skill_text() -> str:
    """The packaged skill (one canonical copy inside the masora package)."""
    return (resources.files("masora") / SKILL_PATH).read_text(encoding="utf-8")


def test_skill_carries_every_agent_instructions_header() -> None:
    packaged = skill_text()
    canonical = AGENT_INSTRUCTIONS.read_text(encoding="utf-8")
    missing = [h for h in _HEADERS_RE.findall(canonical) if h not in packaged]
    assert not missing, f"skill is missing the canonical headers: {missing}"


def test_skill_frontmatter_triggers_on_project_knowledge_only() -> None:
    text = skill_text()
    assert text.startswith("---\nname: masora\n")
    assert (
        'repository-specific behavior — including "what happens when X" questions —'
        " architecture, product semantics, past decisions, trade-offs, or non-obvious"
        " conventions" in text
    )
    assert "Not for general programming tasks" in text


def test_skill_ritual_is_conditional() -> None:
    text = skill_text()
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
    assert "hand them the graph entry points" in skill_text()


def test_agent_instructions_carry_the_atomic_claims_rule() -> None:
    rule = (
        'One claim = one fact. If you wrote "and" twice, that is several claims: split them;'
        " each fact gets its own anchors and its own verification — a block claim is"
        " all-or-nothing to verify, to stale and to refute."
    )

    def flat(text: str) -> str:
        return " ".join(text.split())

    assert rule in flat(AGENT_INSTRUCTIONS.read_text(encoding="utf-8"))
    assert rule in flat(skill_text())


def test_completeness_check_closing_line_in_both_docs() -> None:
    closing = "A note missing an authoring-side item is not done — finish it or split it."

    def flat(text: str) -> str:
        return " ".join(text.split())

    assert closing in flat(AGENT_INSTRUCTIONS.read_text(encoding="utf-8"))
    assert closing in flat(skill_text())
    assert "## Completeness check" in AGENT_INSTRUCTIONS.read_text(encoding="utf-8")
    assert "## Completeness check" in skill_text()


def test_standing_orders_before_memory_and_before_compacting_in_both_docs() -> None:
    def flat(text: str) -> str:
        return " ".join(text.split())

    standing_orders = (
        "These are STANDING ORDERS, not suggestions: when a trigger fires, you note —"
        " without being asked and without asking permission."
    )
    before_memory = (
        "Before answering a product-semantics, architecture or decision question from memory"
        " or from external docs, `search` the base first: it may already hold the answer —"
        " or contradict it. Web and doc confirmation remain the fallback, not the default."
    )
    triage = (
        'A "what happens when X" question is a knowledge question, not a code-navigation'
        " task: search the base before answering, even when code pointers are requested —"
        " the recorded claims carry verified consequences (ordering guarantees, edge cases)"
        " that a fresh code read under-weights."
    )
    before_compacting = (
        "FIRST write a terminal verify per lineage whose evidence is self-contained (report"
        " the replayable bullets) — compact keeps the live state, not the archives."
    )

    canonical = flat(AGENT_INSTRUCTIONS.read_text(encoding="utf-8"))
    skill = flat(skill_text())
    for fragment in (standing_orders, before_memory, triage, before_compacting):
        assert fragment in canonical
        assert fragment in skill


def test_retrieval_budget_names_the_match_all_sentinel() -> None:
    fragment = (
        "`search '*'` lists every indexed lineage with its status tuple — the way"
        " to audit or check for an existing claim before writing."
    )

    def flat(text: str) -> str:
        return " ".join(text.split())

    assert fragment in flat(AGENT_INSTRUCTIONS.read_text(encoding="utf-8"))
    assert fragment in flat(skill_text())


def test_retrieval_budget_forbids_grepping_the_base() -> None:
    fragment = (
        "Never read or grep the base's raw event files (`*.md` under the base"
        " directory) — they carry no status: a refuted/doubted claim read raw"
        " looks valid. Audit through search/explain only."
    )

    def flat(text: str) -> str:
        return " ".join(text.split())

    assert fragment in flat(AGENT_INSTRUCTIONS.read_text(encoding="utf-8"))
    assert fragment in flat(skill_text())


def test_changelog_version_headers_are_unique() -> None:
    seen: dict[str, int] = {}
    duplicates = []
    for header, number in _changelog_headers():
        if header in seen:
            duplicates.append(f"line {number}: {header!r} (first at line {seen[header]})")
        seen[header] = number
    assert not duplicates, "duplicated CHANGELOG section headers: " + "; ".join(duplicates)


def test_changelog_has_at_most_one_unreleased() -> None:
    unreleased = [
        (header, number)
        for header, number in _changelog_headers()
        if header.startswith("## [Unreleased]")
    ]
    assert len(unreleased) <= 1, "stacked [Unreleased] headers: " + "; ".join(
        f"line {n}: {h}" for h, n in unreleased
    )


def test_changelog_versions_sort_newest_first() -> None:
    previous: tuple[int, int, int] | None = None
    failures = []
    for header, number in _changelog_headers():
        if header.startswith("## [Unreleased]"):
            continue
        version = _version_triplet(header)
        if version is None:
            failures.append(f"line {number}: {header!r} is not a version header")
            continue
        if previous is not None and version > previous:
            failures.append(f"line {number}: {header} sorts AFTER an older section above it")
        previous = version
    assert not failures, "CHANGELOG is not newest-first: " + "; ".join(failures)
