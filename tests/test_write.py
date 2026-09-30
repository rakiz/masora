"""Tests for the shared write path's lineage directories (FORMAT.md §1 layout)."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

from helpers import (
    ULID_D1A,
    ULID_L1,
    ULID_V1A,
    make_claim,
    make_doubt,
    make_verify,
    write_event,
)

from masora.checker import check_base
from masora.write import lineage_slug, write_and_check

MONTH = datetime.now(UTC).strftime("%Y-%m")


def test_slug_is_deterministic():
    assert lineage_slug("One line summary") == "one-line-summary"
    assert lineage_slug("one line SUMMARY") == "one-line-summary"
    assert lineage_slug("  One   line  summary ") == "one-line-summary"


def test_slug_folds_unicode_to_ascii():
    assert lineage_slug("Résumé — ça va") == "resume-ca-va"


def test_slug_of_empty_or_punctuation_only_summary_is_empty():
    assert lineage_slug("") == ""
    assert lineage_slug("!!! — ??? ...") == ""


def test_slug_trims_long_summaries_at_word_boundaries():
    slug = lineage_slug("Resume token invalidated by a shard key change")
    assert slug == "resume-token-invalidated"
    assert len(slug) <= 24


def test_slug_hard_cuts_a_single_word_longer_than_the_budget():
    assert lineage_slug("a" * 40) == "a" * 24


def test_founder_write_creates_slug_named_directory_in_current_month(base):
    rel, _warnings = write_and_check(base, make_claim(ULID_L1))

    assert rel == f"{MONTH}/one-line-summary-{ULID_L1}/{ULID_L1}.claim.md"
    assert (base / rel).is_file()


def test_founder_with_slugless_summary_writes_bare_lineage_directory(base):
    rel, _warnings = write_and_check(base, make_claim(ULID_L1, summary="!!!"))

    assert rel == f"{MONTH}/{ULID_L1}/{ULID_L1}.claim.md"


def test_extension_joins_the_existing_lineage_directory(base):
    existing = f"2025-01/old-slug-{ULID_L1}"
    write_event(base, f"{existing}/{ULID_L1}.claim.md", make_claim(ULID_L1))

    rel, _warnings = write_and_check(base, make_verify(ULID_V1A, ULID_L1, ULID_L1))

    assert rel.startswith(f"{existing}/")
    assert rel.endswith(f"/{ULID_V1A}.verify.md")


def test_extension_without_existing_directory_writes_bare_lineage_directory(base):
    rel, _warnings = write_and_check(base, make_verify(ULID_V1A, ULID_L1, ULID_L1))

    assert rel == f"{MONTH}/{ULID_L1}/{ULID_V1A}.verify.md"


def test_legacy_split_tree_writes_into_the_deterministic_home(base):
    founder_home = f"2026-01/{ULID_L1}"
    write_event(base, f"{founder_home}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(
        base, f"2025-12/{ULID_L1}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1)
    )

    rel, _warnings = write_and_check(base, make_doubt(ULID_D1A, ULID_L1, ULID_V1A))

    assert rel.startswith(f"{founder_home}/")
    lineage_dirs = [path for path in base.rglob(ULID_L1) if path.is_dir()]
    assert len(lineage_dirs) == 2


def test_legacy_split_without_founder_picks_the_sorted_first_home(base):
    write_event(
        base, f"2026-02/{ULID_L1}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1)
    )

    rel, _warnings = write_and_check(base, make_doubt(ULID_D1A, ULID_L1, ULID_V1A))

    assert rel.startswith(f"2026-02/{ULID_L1}/")


def test_extension_never_creates_a_third_directory(base):
    write_event(base, f"2026-01/{ULID_L1}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(
        base, f"2025-12/{ULID_L1}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1)
    )

    write_and_check(base, make_doubt(ULID_D1A, ULID_L1, ULID_V1A))

    lineage_dirs = [path for path in base.rglob(f"*{ULID_L1}") if path.is_dir()]
    assert len(lineage_dirs) == 2


def test_checker_stays_path_indifferent_to_moved_lineage_directories(base):
    rel, _warnings = write_and_check(base, make_claim(ULID_L1))
    lineage_dir = (base / rel).parent
    moved = base / "handmade-home"
    shutil.move(str(lineage_dir), str(moved))

    result = check_base(base)

    assert result.errors == []
    assert (moved / f"{ULID_L1}.claim.md").is_file()
