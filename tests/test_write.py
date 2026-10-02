"""Tests for the shared write path's lineage directories (FORMAT.md §1 layout)
and the tool-captured `lines` fork-point stamp (FORMAT.md §4)."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime

import pytest
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
from masora.frontmatter import load_frontmatter
from masora.sync import git_env
from masora.write import LINES_CAP, capture_lines, slugify_summary, write_and_check

MONTH = datetime.now(UTC).strftime("%Y-%m")


def test_slug_is_deterministic():
    assert slugify_summary("One line summary") == "one-line-summary"
    assert slugify_summary("one line SUMMARY") == "one-line-summary"
    assert slugify_summary("  One   line  summary ") == "one-line-summary"


def test_slug_splits_camel_case():
    assert slugify_summary("$changeStreamSplitLargeEvent") == "change-stream-split-large"
    assert slugify_summary("changeStreamSplitLargeEvent").startswith("change-stream-split")


def test_slug_splits_acronym_runs():
    assert slugify_summary("XMLParser") == "xml-parser"
    assert slugify_summary("honorMaxTimeMSDuringBatch") == "honor-max-time-ms-during-batch"


def test_slug_strips_the_leading_article():
    assert slugify_summary("The resume token test") == "resume-token-test"
    assert slugify_summary("A resume token") == "resume-token"
    assert slugify_summary("An unanchored claim") == "unanchored-claim"


def test_slug_trims_long_summaries_at_word_boundaries():
    slug = slugify_summary("Resume token invalidated by a shard key change")
    assert slug == "resume-token-invalidated-by-a"
    assert len(slug) <= 30


def test_slug_hard_cuts_a_single_word_longer_than_the_budget():
    assert slugify_summary("a" * 40) == "a" * 30
    assert len(slugify_summary("a" * 40)) <= 30


def test_slug_of_no_alphanumeric_summary_falls_back_to_lineage():
    assert slugify_summary("!!! — ??? ...") == "lineage"
    assert slugify_summary("") == "lineage"


def test_slug_keeps_digits():
    assert slugify_summary("0x82 and 16MiB limits") == "0x82-and-16-mi-b-limits"


def test_slug_of_already_conformant_string_is_unchanged():
    assert slugify_summary("resume-token-invalidated") == "resume-token-invalidated"
    assert slugify_summary("one-line-summary") == "one-line-summary"


def test_founder_write_creates_slug_named_directory_in_current_month(base):
    rel, _warnings = write_and_check(base, make_claim(ULID_L1))

    assert rel == f"{MONTH}/one-line-summary-{ULID_L1}/{ULID_L1}.claim.md"
    assert (base / rel).is_file()


def test_founder_with_slugless_summary_derives_the_lineage_fallback_directory(base):
    rel, _warnings = write_and_check(base, make_claim(ULID_L1, summary="!!!"))

    assert rel == f"{MONTH}/lineage-{ULID_L1}/{ULID_L1}.claim.md"


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


# --- the tool-captured `lines` fork-point stamp (FORMAT.md §4) ---------------


def git(repo, *args):
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


@pytest.fixture
def code_repo(tmp_path):
    repo = tmp_path / "code"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Masora Test")
    git(repo, "config", "user.email", "masora@example.invalid")
    return repo


def commit_file(repo, name, content="change\n"):
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def merge_base(repo, a, ref):
    return git(repo, "merge-base", a, ref)


def test_capture_lines_returns_sorted_merge_bases(code_repo):
    first = commit_file(code_repo, "a.txt")
    git(code_repo, "branch", "8.0", first)
    second = commit_file(code_repo, "b.txt")
    git(code_repo, "branch", "master", second)
    head = commit_file(code_repo, "c.txt")

    lines = capture_lines(code_repo, head)

    assert list(lines) == ["8.0", "main", "master"]
    assert lines["8.0"] == merge_base(code_repo, head, "8.0") == first
    assert lines["master"] == second
    assert lines["main"] == head


def test_capture_lines_includes_remote_tracking_refs_and_skips_symbolic_head(code_repo):
    head = commit_file(code_repo, "a.txt")
    git(code_repo, "update-ref", "refs/remotes/origin/9.0", head)
    git(code_repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/9.0")

    lines = capture_lines(code_repo, head)

    assert lines == {"main": head, "origin/9.0": head}


def test_capture_lines_omits_unrelated_history(code_repo):
    head = commit_file(code_repo, "a.txt")
    git(code_repo, "checkout", "--orphan", "isolated")
    commit_file(code_repo, "b.txt")
    git(code_repo, "checkout", "main")

    lines = capture_lines(code_repo, head)

    # The orphan branch has no merge-base with HEAD — omitted silently.
    proc = subprocess.run(
        ["git", "-C", str(code_repo), "merge-base", head, "isolated"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    assert proc.returncode != 0
    assert lines == {"main": head}


def test_capture_lines_capped_at_lines_cap(code_repo):
    head = commit_file(code_repo, "a.txt")
    for i in range(LINES_CAP + 3):
        git(code_repo, "branch", f"train-{i:02d}", head)

    lines = capture_lines(code_repo, head)

    assert len(lines) == LINES_CAP
    assert (
        list(lines)
        == sorted(["main", *(f"train-{i:02d}" for i in range(LINES_CAP + 3))])[:LINES_CAP]
    )
    assert set(lines.values()) == {head}


def test_capture_lines_all_failures_omit_the_stamp(code_repo):
    """A detached HEAD on an unrelated root commit with no other prober ref →
    no successful merge-base at all → None (the caller omits `lines`)."""
    commit_file(code_repo, "a.txt")
    git(code_repo, "checkout", "--orphan", "isolated")
    orphan = commit_file(code_repo, "b.txt")
    git(code_repo, "checkout", "--detach", orphan)
    git(code_repo, "branch", "-D", "isolated")

    assert capture_lines(code_repo, orphan) is None


def test_capture_lines_none_on_non_git_directory(tmp_path):
    assert capture_lines(tmp_path, "0" * 40) is None


def test_tool_write_stamps_lines_and_check_stays_green(code_repo, base):
    head = commit_file(code_repo, "a.txt")
    git(code_repo, "branch", "8.0", head)
    commit_file(code_repo, "b.txt")

    # The composition the MCP write tools perform (no agent-facing argument):
    # the establishing commit is the code checkout's HEAD at capture time.
    data = make_claim(ULID_L1)
    data["recorded_at"]["lines"] = capture_lines(code_repo, head)
    rel, _warnings = write_and_check(base, data)

    written = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert written["recorded_at"]["lines"] == {"8.0": head, "main": head}
    raw = (base / rel).read_text(encoding="utf-8")
    assert raw.index('"8.0":') < raw.index('"main":')
    assert check_base(base).errors == []
