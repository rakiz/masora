"""Tests for the shared write path's lineage directories (FORMAT.md §1 layout),
the tool-captured `lines` fork-point stamp (FORMAT.md §4, FIXED ref set), the
atomic event write and the credential guard."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime

import pytest
from helpers import (
    ULID_D1A,
    ULID_L1,
    ULID_L2,
    ULID_V1A,
    make_claim,
    make_doubt,
    make_verify,
    write_event,
)

from masora.checker import check_base
from masora.frontmatter import load_frontmatter
from masora.sync import git_env
from masora.write import (
    WriteError,
    capture_lines,
    scan_for_secrets,
    slugify_summary,
    write_and_check,
)

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


# --- the tool-captured `lines` fork-point stamp (FORMAT.md §4): FIXED set ----


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


@pytest.fixture
def remote_repo(code_repo):
    origin = code_repo.parent / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    git(code_repo, "remote", "add", "origin", str(origin))
    return origin


def commit_file(repo, name, content="change\n"):
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def merge_base(repo, a, ref):
    return git(repo, "merge-base", a, ref)


def test_capture_lines_captures_upstream_and_default_branch_deduped(code_repo, remote_repo):
    head = commit_file(code_repo, "a.txt")
    git(code_repo, "push", "-u", "origin", "main")
    git(code_repo, "remote", "set-head", "origin", "main")

    lines = capture_lines(code_repo, head)

    # Upstream and default branch are the same line: one entry.
    assert lines == {"origin/main": head}


def test_capture_lines_captures_both_refs_when_default_differs_from_upstream(
    code_repo, remote_repo
):
    first = commit_file(code_repo, "a.txt")
    git(code_repo, "push", "origin", "main:refs/heads/9.0")
    git(code_repo, "remote", "set-head", "origin", "9.0")
    head = commit_file(code_repo, "b.txt")
    git(code_repo, "push", "-u", "origin", "main")
    assert first

    lines = capture_lines(code_repo, head)

    assert set(lines) == {"origin/main", "origin/9.0"}
    assert lines["origin/main"] == head
    assert lines["origin/9.0"] == merge_base(code_repo, head, "refs/remotes/origin/9.0")


def test_capture_lines_without_upstream_keeps_the_default_branch(code_repo, remote_repo):
    head = commit_file(code_repo, "a.txt")
    git(code_repo, "push", "origin", "main")
    git(code_repo, "remote", "set-head", "origin", "main")
    git(code_repo, "checkout", "--detach", head)

    lines = capture_lines(code_repo, head)

    assert lines == {"origin/main": head}


def test_capture_lines_omits_a_failing_merge_base_silently(code_repo, remote_repo):
    head = commit_file(code_repo, "a.txt")
    git(code_repo, "push", "-u", "origin", "main")
    # A dangling default-branch pointer: symbolic-ref resolves the name, the
    # merge-base fails — the ref is omitted silently, the upstream stays.
    git(code_repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/ghost")

    lines = capture_lines(code_repo, head)

    assert lines == {"origin/main": head}


def test_capture_lines_none_without_any_ref(code_repo):
    head = commit_file(code_repo, "a.txt")
    assert capture_lines(code_repo, head) is None


def test_capture_lines_none_on_non_git_directory(tmp_path):
    assert capture_lines(tmp_path, "0" * 40) is None


def test_tool_write_stamps_lines_and_check_stays_green(code_repo, remote_repo, base):
    head = commit_file(code_repo, "a.txt")
    git(code_repo, "push", "-u", "origin", "main")
    git(code_repo, "remote", "set-head", "origin", "main")

    # The composition the MCP write tools perform (no agent-facing argument):
    # the establishing commit is the code checkout's HEAD at capture time.
    data = make_claim(ULID_L1)
    data["recorded_at"]["lines"] = capture_lines(code_repo, head)
    rel, _warnings = write_and_check(base, data)

    written = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    assert written["recorded_at"]["lines"] == {"origin/main": head}
    assert check_base(base).errors == []


# --- M10: the atomic event write ---------------------------------------------


def test_write_is_atomic_no_temp_files_remain(base):
    rel, _warnings = write_and_check(base, make_claim(ULID_L1))

    assert (base / rel).is_file()
    assert (base / rel).read_text(encoding="utf-8").startswith("---")
    assert not list(base.rglob("*.tmp"))
    assert check_base(base).errors == []


def test_failed_post_check_unlinks_the_event_and_leaves_no_temp(base):
    first_rel, _ = write_and_check(base, make_claim(ULID_L1))
    before = (base / first_rel).read_text(encoding="utf-8")

    # Schema-valid but rejected at check: a verify whose lineage disagrees
    # with its target's (E-LINEAGE).
    with pytest.raises(WriteError):
        write_and_check(base, make_verify(ULID_V1A, ULID_L2, ULID_L1))

    assert not list(base.rglob("*.tmp"))
    assert (base / first_rel).read_text(encoding="utf-8") == before
    assert check_base(base).errors == []


# --- M5: the credential guard's field coverage -------------------------------


def test_scan_covers_name_and_unanchored_reason():
    assert scan_for_secrets(make_claim(ULID_L1, name="token = " + "aB3$xY9#" * 4)) is not None
    assert (
        scan_for_secrets(
            make_claim(ULID_L1, unanchored=True, unanchored_reason="password = " + "aB3$xY9#" * 4)
        )
        is not None
    )


def test_scan_covers_proof_query_args_and_expect():
    query = {
        "tool": "cppgraph.calls",
        "args": {"symbol": "x", "filter": "ghp_" + "aB3xY9zK" * 4},
        "expect": {"op": "count", "value": 3},
        "provider_version": "1.0",
    }
    assert scan_for_secrets(make_claim(ULID_L1, proof_query=query)) is not None
    query["args"] = {"symbol": "x"}
    query["expect"] = {"op": "set-equality", "value": ["password = " + "aB3$xY9#" * 4]}
    assert scan_for_secrets(make_claim(ULID_L1, proof_query=query)) is not None


def test_scan_passes_a_clean_proof_query():
    query = {
        "tool": "cppgraph.calls",
        "args": {"symbol": "scip-clang cxx . . example#foo()."},
        "expect": {"op": "count", "value": 3},
        "provider_version": "1.0",
    }
    assert scan_for_secrets(make_claim(ULID_L1, proof_query=query)) is None


# --- Phase 4: M3 (one shared full-base pass per write), auto_base strictness,
# --- proof_query float round-trip --------------------------------------------


def test_write_and_check_runs_one_full_base_pass(base, monkeypatch):
    """M3: the post-write validation is incremental (touched lineage + the
    global invariants) — ONE full check_base parse per write, the guarantee
    (a returned write leaves a valid base) unchanged."""
    from masora import write as write_mod

    calls = {"n": 0}
    real = write_mod.check_base

    def counting(base_dir):
        calls["n"] += 1
        return real(base_dir)

    monkeypatch.setattr(write_mod, "check_base", counting)
    rel, _warnings = write_and_check(base, make_claim(ULID_L1))
    assert calls["n"] == 1
    assert (base / rel).is_file()
    assert real(base).errors == []


def test_write_and_check_reuses_the_callers_shared_pass(base, monkeypatch):
    """M3: the MCP write tools compute ONE `checked()` pass for target
    resolution AND the pre-check — `check_base` must not run again inside."""
    from masora import write as write_mod

    write_event(base, f"{MONTH}/x/{ULID_L1}.claim.md", make_claim(ULID_L1))
    calls = {"n": 0}
    real = write_mod.check_base

    def counting(base_dir):
        calls["n"] += 1
        return real(base_dir)

    monkeypatch.setattr(write_mod, "check_base", counting)
    shared = write_mod.checked(base)
    _rel, _warnings = write_and_check(base, make_verify(ULID_V1A, ULID_L1, ULID_L1), shared=shared)
    assert calls["n"] == 1
    assert real(base).errors == []


def test_post_check_refuses_a_tombstoned_lineage_and_unlinks(base):
    from masora.write import checked

    # A tombstone table with no events left behind is a VALID base.
    (base / "deleted.toml").write_text(
        f'[[deleted]]\nlineage = "{ULID_L1}"\nulids = ["{ULID_L1}"]\n', encoding="utf-8"
    )
    shared = checked(base)

    with pytest.raises(WriteError) as excinfo:
        write_and_check(base, make_claim(ULID_L1, summary="Second"), shared=shared)

    assert excinfo.value.diags[0].code == "E-TOMBSTONED"
    assert not list(base.rglob("*.tmp"))
    assert list(base.rglob(f"*{ULID_L1}*.claim.md")) == []


def test_auto_base_refuses_a_matched_mapping_without_bases(tmp_path, monkeypatch):
    """LOW: a mapping whose code_remote MATCHED but that names no base is an
    error — never a silent fall-through to default_base (wrong-base write)."""
    from masora.write import auto_base

    monkeypatch.setattr("masora.write.origin_remote", lambda repo: "git@github.com:org/proj.git")
    monkeypatch.setattr(
        "masora.write.load_user_config",
        lambda: {
            "default_base": "fallback",
            "mappings": [{"code_remote": "git@github.com:org/proj.git", "bases": []}],
        },
    )

    with pytest.raises(WriteError) as excinfo:
        auto_base(tmp_path)

    assert "names no base" in excinfo.value.diags[0].message


def test_proof_query_float_args_round_trip(base):
    """LOW: a float in proof_query.args is emitted as a YAML number and comes
    back as a float — never silently stringified."""
    query = {
        "tool": "cppgraph.calls",
        "args": {"threshold": 1.5, "symbol": "x"},
        "expect": {"op": "count", "value": 3},
        "provider_version": "1.0",
    }
    data = make_claim(ULID_L1, **{"class": "structural", "proof_query": query})
    rel, _warnings = write_and_check(base, data)

    written = load_frontmatter((base / rel).read_text(encoding="utf-8"), rel)
    args = written["proof_query"]["args"]
    assert args["threshold"] == 1.5
    assert isinstance(args["threshold"], float)
    assert "threshold: 1.5" in (base / rel).read_text(encoding="utf-8")
