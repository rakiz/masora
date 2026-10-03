"""Tests for `masora sync` (real git repos in tmp_path, fake gh, no network)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from helpers import (
    OMIT,
    ULID_D1A,
    ULID_L1,
    ULID_L2,
    ULID_R1A,
    ULID_V1A,
    ULID_V2A,
    ULID_V3A,
    make_claim,
    make_doubt,
    make_verify,
    write_event,
)

from masora.audit import STATEMENT_MAX
from masora.cli import main
from masora.sync import REPO_LOCATION_ENV_VARS, _git, _remote_url, git_env
from masora.sync import run as sync_run

CLAIM_REL = "2026-09/x/01J8Z3K0000000000000000000.claim.md"
VERIFY_REL = "2026-09/x/01J8Z3K0000000000000000001.verify.md"
DANGLING = "01J7ZZZZZZZZZZZZZZZZZZZZZZ"

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
entry = {"args": sys.argv[1:], "stdin": sys.stdin.read() or None}
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry) + "\\n")
args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    print(os.environ.get("FAKE_GH_LIST", "[]"))
elif args[:2] == ["pr", "create"]:
    print("https://github.com/acme/base/pull/42")
"""


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


def rev_ok(repo: Path, rev: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", rev],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    return proc.returncode == 0


def gh_calls(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def seed(base: Path, message: str = "seed") -> None:
    git(base, "add", "-A")
    git(base, "commit", "-m", message)
    git(base, "push", "origin", "main")


def tombstone(lineage: str, ulids: list[str]) -> str:
    ulids_text = ", ".join(f'"{ulid}"' for ulid in ulids)
    return f'[[deleted]]\nlineage = "{lineage}"\nulids = [{ulids_text}]\n'


@pytest.fixture
def repo(tmp_path: tuple) -> tuple[Path, Path]:
    tmp = tmp_path
    base = tmp / "base"
    base.mkdir()
    (base / "base.toml").write_text('name = "test-base"\ncode_remotes = []\n', encoding="utf-8")
    git(base, "init", "-b", "main")
    git(base, "config", "user.name", "Masora Test")
    git(base, "config", "user.email", "masora@example.invalid")
    origin = tmp / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    git(base, "remote", "add", "origin", str(origin))
    (base / "base.toml").write_text('name = "test-base"\n', encoding="utf-8")
    seed(base, "init")
    return base, origin


@pytest.fixture
def fake_gh(tmp_path, monkeypatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(FAKE_GH, encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("FAKE_GH_LOG", str(tmp_path / "gh.log"))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return tmp_path / "gh.log"


@pytest.fixture
def github_remote(monkeypatch):
    monkeypatch.setattr(
        "masora.sync._remote_url", lambda base_dir: "https://github.com/acme/base.git"
    )


def test_sync_clean_add_pushes_pending_branch_and_opens_pr(repo, fake_gh, github_remote, capsys):
    base, origin = repo
    main_before = git(origin, "rev-parse", "refs/heads/main")
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "2 added, 0 unchanged, 0 rewritten, 0 deleted" in out
    assert git(origin, "rev-parse", "refs/heads/main") == main_before
    pending = git(base, "rev-parse", "refs/heads/masora/masora-test")
    assert pending == git(origin, "rev-parse", "refs/heads/masora/masora-test")
    assert git(base, "rev-parse", "masora/masora-test^") == main_before
    assert "2026-09/x/01J8Z3K0000000000000000000.claim.md" in git(
        origin, "ls-tree", "-r", "--name-only", "masora/masora-test"
    )
    calls = gh_calls(fake_gh)
    assert [call["args"][:2] for call in calls] == [["pr", "list"], ["pr", "create"]]
    create = calls[1]
    assert "--head" in create["args"] and "masora/masora-test" in create["args"]
    assert "--base" in create["args"] and "main" in create["args"]
    assert create["args"][create["args"].index("--title") + 1] == (
        "masora sync: 1 claim, 1 verification"
    )
    assert '- one-line-summary: "One line summary" — llm' in create["stdin"]
    assert '- verified "One line summary" — by llm — 1 evidence item' in create["stdin"]
    assert "(no summary)" not in create["stdin"]
    assert "opened PR https://github.com/acme/base/pull/42" in out
    assert "synced: 2 pending event(s)" in out


def test_sync_updates_existing_pr(repo, fake_gh, github_remote, monkeypatch, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    monkeypatch.setenv(
        "FAKE_GH_LIST", '[{"number": 42, "url": "https://github.com/acme/base/pull/42"}]'
    )

    code = sync_run(base, yes=True)

    assert code == 0
    calls = gh_calls(fake_gh)
    assert [call["args"][:2] for call in calls] == [["pr", "list"], ["pr", "edit"]]
    assert "42" in calls[1]["args"]
    assert "One line summary" in calls[1]["stdin"]
    assert "updated PR https://github.com/acme/base/pull/42" in capsys.readouterr().out


def test_sync_idempotent_second_run(repo, fake_gh, github_remote, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base, yes=True) == 0
    capsys.readouterr()
    calls_after_first = gh_calls(fake_gh)

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "pending set unchanged: masora/masora-test already carries it" in out
    assert gh_calls(fake_gh) == calls_after_first


def test_sync_squash_merged_content_is_not_tampering(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    assert sync_run(base, yes=True) == 0
    capsys.readouterr()
    main_before = git(origin, "rev-parse", "refs/heads/main")
    pending_tree = git(base, "rev-parse", "refs/heads/masora/masora-test^{tree}")
    squash = git(base, "commit-tree", pending_tree, "-p", main_before, "-m", "masora sync (squash)")
    git(base, "push", "origin", f"{squash}:refs/heads/main")

    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-REWRITE" not in out
    assert "no pending events: nothing to sync" in out


def test_sync_rewrite_is_rejected(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    seed(base)
    write_event(base, CLAIM_REL, make_claim(ULID_L1, summary="Tampered summary"))

    code = sync_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-REWRITE" in out
    assert "FAILED: 1 error(s)" in out
    assert not rev_ok(origin, "refs/heads/masora/masora-test")


def test_sync_partial_lineage_deletion_is_rejected(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    seed(base)
    (base / VERIFY_REL).unlink()

    code = sync_run(base)

    assert code == 1
    assert "E-REWRITE" in capsys.readouterr().out


def test_sync_whole_lineage_deletion_reports_gc_unavailable(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    other_rel = "2026-09/y/01J8Z3K0000000000000000006.claim.md"
    write_event(base, other_rel, make_claim(ULID_L2))
    seed(base)
    (base / CLAIM_REL).unlink()
    (base / VERIFY_REL).unlink()

    code = sync_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-GC-UNAVAILABLE" in out
    assert "masora gc" in out
    assert "E-REWRITE" not in out


def test_sync_tombstone_shrink_is_rejected(repo, capsys):
    base, _origin = repo
    (base / "deleted.toml").write_text(tombstone(ULID_L1, [ULID_L1]), encoding="utf-8")
    seed(base)
    (base / "deleted.toml").unlink()

    code = sync_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-TOMBSTONE-SHRINK" in out
    assert ULID_L1 in out


def test_sync_v2_claim_without_founder_is_rejected(repo, capsys):
    base, _origin = repo
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000005.claim.md",
        make_claim(ULID_V2A, lineage=ULID_L1, reason="why"),
    )

    code = sync_run(base)

    assert code == 1
    assert "E-FOUNDER" in capsys.readouterr().out


def test_sync_v2_claim_with_pending_founder_is_accepted(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000005.claim.md",
        make_claim(ULID_V2A, lineage=ULID_L1, reason="why"),
    )

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-FOUNDER" not in out
    assert "synced: 2 pending event(s)" in out


def test_sync_gc_race_surfaces_at_merged_result(repo, tmp_path, capsys):
    base, origin = repo
    claim_rel = "2026-09/x/01J8Z3K0000000000000000006.claim.md"
    verify_rel = "2026-09/x/01J8Z3K0000000000000000008.verify.md"
    write_event(
        base,
        claim_rel,
        make_claim(ULID_L2, unanchored=True, anchors=OMIT, unanchored_reason="no anchors"),
    )
    write_event(base, verify_rel, make_verify(ULID_V3A, ULID_L2, ULID_L2, snapshots={}))
    seed(base)

    worker = tmp_path / "worker"
    subprocess.run(
        ["git", "clone", str(origin), str(worker)], capture_output=True, check=True, env=git_env()
    )
    git(worker, "config", "user.name", "Other Author")
    git(worker, "config", "user.email", "other@example.invalid")
    (worker / claim_rel).unlink()
    (worker / verify_rel).unlink()
    (worker / "deleted.toml").write_text(tombstone(ULID_L2, [ULID_L2, ULID_V3A]), encoding="utf-8")
    seed(worker, "gc lineage")

    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000002.doubt.md",
        make_doubt(ULID_D1A, ULID_L2, ULID_V3A),
    )

    code = sync_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-TOMBSTONED" in out
    assert "merged-result check" in out


def test_sync_drop_deletes_local_branch_closes_pr_and_deletes_remote(
    repo, fake_gh, github_remote, monkeypatch, capsys
):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base, yes=True) == 0
    capsys.readouterr()
    monkeypatch.setenv(
        "FAKE_GH_LIST", '[{"number": 42, "url": "https://github.com/acme/base/pull/42"}]'
    )

    code = sync_run(base, drop=True, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert f"dropped: {ULID_L1} claim: One line summary" in out
    assert "dropped 1 pending event(s)" in out
    calls = gh_calls(fake_gh)
    assert any(call["args"][:2] == ["pr", "close"] and "42" in call["args"] for call in calls)
    assert not rev_ok(origin, "refs/heads/masora/masora-test")
    assert not rev_ok(base, "refs/heads/masora/masora-test")


def test_sync_drop_without_forge_cli_still_deletes_remote_branch(repo, monkeypatch, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base, yes=True) == 0
    capsys.readouterr()
    monkeypatch.setattr("masora.sync._gh_on_path", lambda: None)

    code = sync_run(base, drop=True, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "forge CLI (gh) not available" in out
    assert not rev_ok(origin, "refs/heads/masora/masora-test")
    assert not rev_ok(base, "refs/heads/masora/masora-test")


def test_sync_drop_without_any_pending(repo, capsys):
    base, _origin = repo
    code = sync_run(base, drop=True)
    assert code == 0
    assert "nothing to drop" in capsys.readouterr().out


def test_sync_push_solo_pushes_main(repo, capsys):
    base, origin = repo
    main_before = git(origin, "rev-parse", "refs/heads/main")
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))

    code = sync_run(base, push=True, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "solo mode" in out
    assert not rev_ok(base, "refs/heads/masora/masora-test")
    assert not rev_ok(origin, "refs/heads/masora/masora-test")
    main_after = git(origin, "rev-parse", "refs/heads/main")
    assert main_after != main_before
    assert git(base, "rev-parse", f"{main_after}^") == main_before
    tree = git(origin, "ls-tree", "-r", "--name-only", "refs/heads/main")
    assert CLAIM_REL in tree and VERIFY_REL in tree
    assert git(base, "rev-parse", "refs/heads/main") == main_after
    status = subprocess.run(
        ["git", "-C", str(base), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        env=git_env(),
    )
    assert status.returncode == 0 and status.stdout == ""


def test_sync_dangling_target_is_warning_only(repo, capsys):
    base, origin = repo
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000002.doubt.md",
        make_doubt(ULID_D1A, ULID_L1, DANGLING),
    )

    code = sync_run(base, yes=True)

    assert code == 2
    out = capsys.readouterr().out
    assert "W-DANGLING" in out
    assert "synced with warnings: 2 warning(s)" in out
    assert rev_ok(origin, "refs/heads/masora/masora-test")


def test_sync_pr_body_unresolvable_target_falls_back_to_ulid(repo, fake_gh, github_remote):
    base, _origin = repo
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000002.doubt.md",
        make_doubt(ULID_D1A, ULID_L1, DANGLING),
    )

    code = sync_run(base, yes=True)

    assert code == 2
    calls = gh_calls(fake_gh)
    create = calls[1]
    assert f'- doubted "{DANGLING}" — A reason. — by human' in create["stdin"]


def test_sync_local_check_errors_block_before_any_git_action(repo, capsys):
    base, origin = repo
    event = base / CLAIM_REL
    event.parent.mkdir(parents=True)
    event.write_text("---\n^ invalid: [\n---\n", encoding="utf-8")

    code = sync_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert not rev_ok(origin, "refs/heads/masora/masora-test")


def test_sync_requires_origin(tmp_path, capsys):
    base = tmp_path / "lonely"
    base.mkdir()
    (base / "base.toml").write_text('name = "test-base"\ncode_remotes = []\n', encoding="utf-8")
    git(base, "init", "-b", "main")
    git(base, "config", "user.name", "Masora Test")
    git(base, "config", "user.email", "masora@example.invalid")

    code = sync_run(base)

    assert code == 1
    assert "E-NO-ORIGIN" in capsys.readouterr().out


def test_sync_compare_url_fallback_without_gh(repo, monkeypatch, capsys):
    base, origin = repo
    monkeypatch.setattr(
        "masora.sync._remote_url", lambda base_dir: "https://github.com/acme/base.git"
    )
    monkeypatch.setattr("masora.sync._gh_on_path", lambda: None)
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "https://github.com/acme/base/compare/main...masora/masora-test?expand=1" in out
    assert rev_ok(origin, "refs/heads/masora/masora-test")


def test_sync_non_github_remote_prints_manual_instruction(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "open the pull request from masora/masora-test to main" in out
    assert str(origin) in out
    assert rev_ok(origin, "refs/heads/masora/masora-test")


def test_sync_collaborator_event_on_origin_is_not_tampering(repo, tmp_path, capsys):
    base, origin = repo
    collab_rel = "2026-09/y/01J8Z3K0000000000000000006.claim.md"
    worker = tmp_path / "worker"
    subprocess.run(
        ["git", "clone", str(origin), str(worker)], capture_output=True, check=True, env=git_env()
    )
    git(worker, "config", "user.name", "Other Author")
    git(worker, "config", "user.email", "other@example.invalid")
    write_event(worker, collab_rel, make_claim(ULID_L2))
    seed(worker, "collaborator claim")

    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-REWRITE" not in out
    assert "E-GC-UNAVAILABLE" not in out
    assert "1 added" in out
    pending_files = git(
        base, "ls-tree", "-r", "--name-only", "refs/heads/masora/masora-test"
    ).splitlines()
    assert collab_rel in pending_files and CLAIM_REL in pending_files


def test_sync_up_to_date_requires_matching_remote_tracking_ref(
    repo, fake_gh, github_remote, capsys
):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base, yes=True) == 0
    capsys.readouterr()
    calls_after_first = gh_calls(fake_gh)
    main_sha = git(origin, "rev-parse", "refs/heads/main")
    git(base, "push", "origin", f"{main_sha}:refs/heads/masora/masora-test", "--force")

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "pending set unchanged" not in out
    assert "pushed branch masora/masora-test" in out
    assert len(gh_calls(fake_gh)) == len(calls_after_first) + 2
    pending = git(base, "rev-parse", "refs/heads/masora/masora-test")
    assert pending == git(origin, "rev-parse", "refs/heads/masora/masora-test")


def test_sync_drop_is_idempotent(repo, fake_gh, github_remote, monkeypatch, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base, yes=True) == 0
    capsys.readouterr()
    monkeypatch.setenv(
        "FAKE_GH_LIST", '[{"number": 42, "url": "https://github.com/acme/base/pull/42"}]'
    )
    assert sync_run(base, drop=True, yes=True) == 0
    calls_after_drop = gh_calls(fake_gh)
    assert any(call["args"][:2] == ["pr", "close"] for call in calls_after_drop)

    code = sync_run(base, drop=True, yes=True)

    assert code == 0
    assert "nothing to drop" in capsys.readouterr().out
    assert gh_calls(fake_gh) == calls_after_drop
    assert not rev_ok(base, "refs/heads/masora/masora-test")
    assert not rev_ok(origin, "refs/heads/masora/masora-test")


def test_sync_pending_commit_excludes_stray_files(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    (base / "caches").mkdir()
    (base / "caches/data.bin").write_text("junk\n", encoding="utf-8")
    (base / ".venv").mkdir()
    (base / ".venv/lib.py").write_text("junk\n", encoding="utf-8")
    (base / "base.toml").write_text('name = "edited"\n', encoding="utf-8")

    code = sync_run(base, yes=True)

    assert code == 0
    files = git(base, "ls-tree", "-r", "--name-only", "refs/heads/masora/masora-test").splitlines()
    assert CLAIM_REL in files and "base.toml" in files
    assert "caches/data.bin" not in files
    assert ".venv/lib.py" not in files


def test_sync_unrelated_history_reports_merge_base(repo, tmp_path, capsys):
    base, origin = repo
    rogue = tmp_path / "rogue"
    rogue.mkdir()
    git(rogue, "init", "-b", "main")
    git(rogue, "config", "user.name", "Rogue")
    git(rogue, "config", "user.email", "rogue@example.invalid")
    (rogue / "other.txt").write_text("divergent\n", encoding="utf-8")
    git(rogue, "add", "-A")
    git(rogue, "commit", "-m", "orphan")
    git(rogue, "push", "-f", str(origin), "main")

    code = sync_run(base)

    assert code == 1
    assert "E-MERGE-BASE" in capsys.readouterr().out


def test_sync_corrupted_merge_base_tombstone_is_rejected(repo, capsys):
    base, _origin = repo
    (base / "deleted.toml").write_text("deleted = [not valid toml\n", encoding="utf-8")
    seed(base)
    (base / "deleted.toml").unlink()

    code = sync_run(base)

    assert code == 1
    assert "E-TOMBSTONE-SHAPE" in capsys.readouterr().out


def test_sync_corrupted_local_tombstone_blocks_at_gate(repo, capsys):
    base, _origin = repo
    (base / "deleted.toml").write_text("deleted = [not valid toml\n", encoding="utf-8")

    code = sync_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-TOMBSTONE-SHAPE" in out
    assert "(local check)" in out


def test_sync_git_spawns_immune_to_inherited_git_env(repo, tmp_path, monkeypatch):
    base, origin = repo
    bogus = tmp_path / "bogus.index"
    for name in REPO_LOCATION_ENV_VARS:
        monkeypatch.setenv(name, str(bogus))

    assert _git(base, "rev-parse", "--git-dir") == ".git"
    assert _remote_url(base) == str(origin)
    git(base, "add", "-A")
    assert (base / ".git" / "index").exists()
    assert "base.toml" in git(base, "ls-files")
    assert not bogus.exists()


def test_sync_pr_title_mirrors_pending_counts(repo, fake_gh, github_remote):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000002.doubt.md",
        make_doubt(ULID_D1A, ULID_L1, ULID_V1A),
    )
    write_event(base, "2026-09/y/01J8Z3K0000000000000000006.claim.md", make_claim(ULID_L2))

    assert sync_run(base, yes=True) == 0

    calls = gh_calls(fake_gh)
    create = calls[1]
    assert create["args"][create["args"].index("--title") + 1] == (
        "masora sync: 2 claims, 1 verification, 1 doubt"
    )


def test_sync_pr_body_lines_read_as_changelog(repo, fake_gh, github_remote):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000002.doubt.md",
        make_doubt(ULID_D1A, ULID_L1, ULID_V1A, reason="I ran the case X=0 and it held."),
    )
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000004.refute.md",
        make_doubt(ULID_R1A, ULID_L1, ULID_L1, kind="refute", reason="Replay says otherwise."),
    )
    write_event(
        base,
        "2026-09/y/01J8Z3K0000000000000000006.claim.md",
        make_claim(ULID_L2, summary="Second claim about locking"),
    )

    assert sync_run(base, yes=True) == 0

    create = gh_calls(fake_gh)[1]
    body = create["stdin"]
    assert '- one-line-summary: "One line summary" — llm' in body
    assert '- second-claim-about-locking: "Second claim about locking" — llm' in body
    assert '- verified "One line summary" — by llm — 1 evidence item' in body
    assert '- doubted "One line summary" — I ran the case X=0 and it held. — by human' in body
    assert '- refuted "One line summary" — Replay says otherwise. — by human' in body
    assert "(no summary)" not in body


def test_sync_pr_body_tombstone_additions_line(repo, fake_gh, github_remote):
    base, _origin = repo
    (base / "deleted.toml").write_text(
        tombstone(ULID_L1, [ULID_L1, ULID_V1A]) + tombstone(ULID_L2, [ULID_L2]),
        encoding="utf-8",
    )

    assert sync_run(base, yes=True) == 0

    create = gh_calls(fake_gh)[1]
    assert create["args"][create["args"].index("--title") + 1] == "masora sync: 3 tombstoned"
    assert "- 3 events removed by compact/gc" in create["stdin"]


def test_pr_body_truncates_long_reason_at_eighty_chars():
    from masora.sync import EventFile, _pr_body

    event = EventFile(
        id=ULID_D1A,
        path="2026-09/x/doubt.md",
        content=b"",
        lineage=ULID_L1,
        kind="doubt",
        targets=ULID_V1A,
        source="human",
        reason="word " * 40,
    )

    body = _pr_body([event], [], {})

    assert "word " * 16 + "…" in body
    assert "word " * 17 not in body


STACKED_STATEMENT = "x" * (STATEMENT_MAX + 1)


def test_sync_stacked_claim_refuses_publication(repo, capsys):
    # Plan mode (no --yes): the stacked refusal still fires at the audit gate —
    # the preview reflects what publish would do, exit 1, nothing mutated.
    base, origin = repo
    main_before = git(origin, "rev-parse", "refs/heads/main")
    write_event(base, CLAIM_REL, make_claim(ULID_L1, statement=STACKED_STATEMENT))

    code = sync_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-SYNC-STACKED" in out
    assert "one-line-summary" in out
    assert f"statement is {STATEMENT_MAX + 1} chars" in out
    assert "split into one atomic note per fact" in out
    assert "remove the unpublished block claim with `masora gc --lineage <id>`" in out
    assert "never published — no tombstone" in out
    assert "re-run sync" in out
    assert not rev_ok(origin, "refs/heads/masora/masora-test")
    assert git(origin, "rev-parse", "refs/heads/main") == main_before


def test_sync_allow_stacked_warns_and_publishes(repo, fake_gh, github_remote, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1, statement=STACKED_STATEMENT))

    code = sync_run(base, allow_stacked=True, yes=True)

    assert code == 2
    out = capsys.readouterr().out
    assert "W-SYNC-STACKED" in out
    assert "one-line-summary" in out
    assert f"statement is {STATEMENT_MAX + 1} chars" in out
    assert "synced with warnings: 1 warning(s)" in out
    assert rev_ok(origin, "refs/heads/masora/masora-test")
    create = gh_calls(fake_gh)[1]
    assert "W-SYNC-STACKED" in create["stdin"]
    assert "one-line-summary" in create["stdin"]


def test_sync_clean_claim_passes_the_stacking_audit(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-SYNC-STACKED" not in out
    assert "W-SYNC-STACKED" not in out


def test_sync_stacking_audit_covers_only_added_claims(repo, capsys):
    # A block claim already on origin/main is tolerated: the gate audits the
    # pending set — what has not reached the shared base yet.
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1, statement=STACKED_STATEMENT))
    seed(base)
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-SYNC-STACKED" not in out
    assert "W-SYNC-STACKED" not in out
    assert "synced: 1 pending event(s)" in out


def test_sync_without_base_dir_resolves_the_configured_base(tmp_path, monkeypatch, capsys):
    """Omitted base_dir: the pre-flight gate resolves the base from the checkout's
    masora configuration before sync runs — the header names the resolved base."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MASORA_HOME", str(home))
    base = home / "bases" / "team" / "masora_mdb"
    base.mkdir(parents=True)
    (base / "base.toml").write_text('name = "test-base"\n', encoding="utf-8")
    git(base, "init", "-b", "main")
    git(base, "config", "user.name", "Masora Test")
    git(base, "config", "user.email", "masora@example.invalid")
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    git(base, "remote", "add", "origin", str(origin))
    seed(base, "init")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git(checkout, "init", "-b", "main")
    git(checkout, "config", "user.name", "Masora Test")
    git(checkout, "config", "user.email", "masora@example.invalid")
    git(checkout, "remote", "add", "origin", "git@github.internal:org/checkout.git")
    (home / "config.toml").write_text(
        "[[mappings]]\n"
        'code_remote = "github.internal/org/checkout.git"\n'
        'bases = ["team"]\n\n'
        "[bases.team]\n"
        'remote = "git@github.internal:org/knowledge.git"\n'
        'path = "masora_mdb"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(checkout)

    code = main(["sync"])

    assert code == 0
    out = capsys.readouterr().out
    assert f"masora sync {base}" in out
    assert "no pending events: nothing to sync" in out


def test_sync_without_base_dir_refuses_and_mutates_nothing(tmp_path, monkeypatch, capsys):
    """Omitted base_dir with nothing resolvable: the pre-flight gate refuses before
    sync is dispatched — the sync machinery (its git plumbing included) never runs
    and the checkout stays untouched."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MASORA_HOME", str(home))
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git(checkout, "init", "-b", "main")
    git(checkout, "config", "user.name", "Masora Test")
    git(checkout, "config", "user.email", "masora@example.invalid")
    git(checkout, "remote", "add", "origin", "git@github.internal:org/checkout.git")
    monkeypatch.chdir(checkout)

    def never(*args, **kwargs):
        raise AssertionError("sync ran past the base-gate refusal")

    monkeypatch.setattr("masora.cli.run_sync", never)

    code = main(["sync"])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-NOT-A-BASE" in out
    assert (
        "run masora setup --base <url> in this checkout, or pass the base directory explicitly"
        in out
    )
    stray = [path for path in checkout.rglob("*") if path.is_file() and ".git" not in path.parts]
    assert stray == []


def test_sync_plan_mode_prints_pending_set_and_writes_nothing(repo, fake_gh, github_remote, capsys):
    """Without --yes sync is a PLAN: the full gate pipeline runs, the pending set
    is printed in the PR body's rendering, and nothing is written — no branch,
    no push, no PR, no local ref mutation."""
    base, origin = repo
    main_before = git(origin, "rev-parse", "refs/heads/main")
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))

    code = sync_run(base)

    assert code == 3
    out = capsys.readouterr().out
    assert "2 added, 0 unchanged, 0 rewritten, 0 deleted" in out
    assert "masora sync: 1 claim, 1 verification" in out
    assert '- one-line-summary: "One line summary" — llm' in out
    assert '- verified "One line summary" — by llm — 1 evidence item' in out
    assert "plan only: nothing written — re-run with --yes to publish" in out
    assert git(origin, "rev-parse", "refs/heads/main") == main_before
    assert not rev_ok(origin, "refs/heads/masora/masora-test")
    assert not rev_ok(base, "refs/heads/masora/masora-test")
    assert gh_calls(fake_gh) == []


def test_sync_yes_publishes_the_planned_set(repo, fake_gh, github_remote, capsys):
    """The publishing twin of the plan test: --yes executes today's publish path."""
    base, origin = repo
    main_before = git(origin, "rev-parse", "refs/heads/main")
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "1 added, 0 unchanged, 0 rewritten, 0 deleted" in out
    assert "synced: 1 pending event(s)" in out
    pending = git(base, "rev-parse", "refs/heads/masora/masora-test")
    assert pending == git(origin, "rev-parse", "refs/heads/masora/masora-test")
    assert git(base, "rev-parse", "masora/masora-test^") == main_before


def test_sync_drop_plans_the_discard_without_yes(repo, fake_gh, github_remote, monkeypatch, capsys):
    """--drop without --yes only plans: the pending set is listed, exit 3, the
    branch and the PR are untouched."""
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base, yes=True) == 0
    capsys.readouterr()
    monkeypatch.setenv(
        "FAKE_GH_LIST", '[{"number": 42, "url": "https://github.com/acme/base/pull/42"}]'
    )
    pending_before = git(base, "rev-parse", "refs/heads/masora/masora-test")

    code = sync_run(base, drop=True)

    assert code == 3
    out = capsys.readouterr().out
    assert f"dropped: {ULID_L1} claim: One line summary" in out
    assert "would discard 1 pending event(s)" in out
    assert "plan only: nothing written — re-run with --yes to discard" in out
    assert git(base, "rev-parse", "refs/heads/masora/masora-test") == pending_before
    assert rev_ok(origin, "refs/heads/masora/masora-test")
    assert not any(call["args"][:2] == ["pr", "close"] for call in gh_calls(fake_gh))


def test_sync_push_plans_without_yes(repo, capsys):
    """--push is a mode selector, not a confirmation: without --yes the direct
    push is only planned."""
    base, origin = repo
    main_before = git(origin, "rev-parse", "refs/heads/main")
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base, push=True)

    assert code == 3
    out = capsys.readouterr().out
    assert "plan only: nothing written — re-run with --yes to push to origin/main" in out
    assert git(origin, "rev-parse", "refs/heads/main") == main_before
    assert git(base, "rev-parse", "refs/heads/main") == main_before
    assert not rev_ok(base, "refs/heads/masora/masora-test")


def test_sync_no_pending_events_exits_zero_in_plan_mode(repo, capsys):
    base, _origin = repo
    code = sync_run(base)
    assert code == 0
    assert "no pending events: nothing to sync" in capsys.readouterr().out


# --- sync selection: --only / --exclude (TODO.md Phase 2.5) ---

OTHER_REL = "2026-09/y/01J8Z3K0000000000000000006.claim.md"


def test_sync_only_publishes_only_selected_events(repo, fake_gh, github_remote, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, OTHER_REL, make_claim(ULID_L2, summary="Second claim about locking"))

    code = sync_run(base, only=[ULID_L1], yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "--only selection: 1 of 2 pending event(s) will be published" in out
    assert "synced: 1 pending event(s)" in out
    tree = git(origin, "ls-tree", "-r", "--name-only", "masora/masora-test")
    assert CLAIM_REL in tree and OTHER_REL not in tree
    create = gh_calls(fake_gh)[1]
    assert "second-claim-about-locking" not in create["stdin"]


def test_sync_excluded_events_stay_pending_locally(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, OTHER_REL, make_claim(ULID_L2, summary="Second claim about locking"))
    assert sync_run(base, only=[ULID_L1], yes=True) == 0
    capsys.readouterr()

    code = sync_run(base)

    assert code == 3
    out = capsys.readouterr().out
    assert "2 added" in out
    assert "second-claim-about-locking" in out


def test_sync_only_matches_unique_prefix(repo, fake_gh, github_remote, capsys):
    base, origin = repo
    prefixed_ulid = "01J8Z3K1000000000000000000"
    prefixed_rel = "2026-09/z/01J8Z3K1000000000000000000.claim.md"
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, prefixed_rel, make_claim(prefixed_ulid, summary="Prefixed claim"))

    code = sync_run(base, only=["01J8Z3K1"], yes=True)

    assert code == 0
    tree = git(origin, "ls-tree", "-r", "--name-only", "masora/masora-test")
    assert prefixed_rel in tree and CLAIM_REL not in tree


def test_sync_ambiguous_prefix_is_refused_with_candidates(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))

    code = sync_run(base, only=["01J8Z3K0"])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-SYNC-SELECT" in out
    assert "ambiguous" in out
    assert ULID_L1 in out and ULID_V1A in out
    assert not rev_ok(origin, "refs/heads/masora/masora-test")


def test_sync_selector_matching_nothing_is_refused(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base, exclude=[DANGLING])

    assert code == 1
    out = capsys.readouterr().out
    assert "E-SYNC-SELECT" in out
    assert f"no pending event matches --exclude selector '{DANGLING}'" in out
    assert not rev_ok(origin, "refs/heads/masora/masora-test")


def test_sync_only_and_exclude_together_are_refused(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base, only=[ULID_L1], exclude=[ULID_L1])

    assert code == 1
    assert "E-SYNC-SELECT" in capsys.readouterr().out


def test_sync_cli_refuses_only_and_exclude_together(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    with pytest.raises(SystemExit):
        main(["sync", str(base), "--only", ULID_L1, "--exclude", ULID_L1])

    assert "--only and --exclude are mutually exclusive" in capsys.readouterr().err


def test_sync_exclude_plan_lists_the_excluded_ids(repo, fake_gh, github_remote, capsys):
    base, origin = repo
    main_before = git(origin, "rev-parse", "refs/heads/main")
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, OTHER_REL, make_claim(ULID_L2, summary="Second claim about locking"))

    code = sync_run(base, exclude=[ULID_L2])

    assert code == 3
    out = capsys.readouterr().out
    assert "--exclude selection: 1 of 2 pending event(s) excluded from this sync" in out
    assert f"  excluded: {ULID_L2}" in out
    assert '- one-line-summary: "One line summary" — llm' in out
    assert "second-claim-about-locking" not in out
    assert "plan only: nothing written" in out
    assert git(origin, "rev-parse", "refs/heads/main") == main_before
    assert gh_calls(fake_gh) == []


def test_sync_deletions_ride_a_selection(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    seed(base)
    write_event(base, OTHER_REL, make_claim(ULID_L2, summary="Second claim about locking"))
    (base / CLAIM_REL).unlink()
    (base / VERIFY_REL).unlink()
    (base / "deleted.toml").write_text(tombstone(ULID_L1, [ULID_L1, ULID_V1A]), encoding="utf-8")

    code = sync_run(base, only=[ULID_L2], yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "tombstone additions" in out
    tree = git(origin, "ls-tree", "-r", "--name-only", "masora/masora-test")
    assert CLAIM_REL not in tree and VERIFY_REL not in tree
    assert OTHER_REL in tree


def test_sync_gates_run_on_the_filtered_set(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1, statement=STACKED_STATEMENT))
    write_event(base, OTHER_REL, make_claim(ULID_L2, summary="Second claim about locking"))
    assert sync_run(base) == 1
    assert "E-SYNC-STACKED" in capsys.readouterr().out
    capsys.readouterr()

    code = sync_run(base, exclude=[ULID_L1], yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-SYNC-STACKED" not in out
    tree = git(origin, "ls-tree", "-r", "--name-only", "masora/masora-test")
    assert OTHER_REL in tree and CLAIM_REL not in tree


def test_sync_push_preserves_committed_excluded_events(repo, capsys):
    """H2: events already COMMITTED on local main but excluded from the
    selection survive the solo push — on main and in the work tree."""
    base, origin = repo
    other_rel = "2026-09/x/01J8Z3K0000000000000000006.claim.md"
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, other_rel, make_claim(ULID_L2, summary="Second claim about locking"))
    git(base, "add", "-A")
    git(base, "commit", "-m", "two events")

    code = sync_run(base, exclude=[ULID_L2], yes=True, push=True)

    assert code == 0
    origin_tree = git(origin, "ls-tree", "-r", "--name-only", "refs/heads/main")
    assert CLAIM_REL in origin_tree and other_rel not in origin_tree
    main_tree = git(base, "ls-tree", "-r", "--name-only", "refs/heads/main")
    assert other_rel in main_tree
    assert (base / other_rel).is_file()
    assert (base / CLAIM_REL).is_file()


def test_sync_applies_already_published_deletions_from_a_stale_main(repo, tmp_path, capsys):
    """Publication gate: the deletion evidence comes from origin/main AFTER the
    fetch — a stale local main must not resurrect another writer's published
    (gc + tombstone) deletion."""
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    seed(base)
    worker = tmp_path / "worker"
    subprocess.run(
        ["git", "clone", str(origin), str(worker)], capture_output=True, check=True, env=git_env()
    )
    git(worker, "config", "user.name", "Other Author")
    git(worker, "config", "user.email", "other@example.invalid")
    (worker / CLAIM_REL).unlink()
    (worker / "deleted.toml").write_text(tombstone(ULID_L1, [ULID_L1]), encoding="utf-8")
    seed(worker, "gc lineage")
    # The base stays stale: it never pulls, its work tree still has the event.
    assert (base / CLAIM_REL).is_file()

    code = sync_run(base, yes=True, push=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "upstream-published deletion(s) applied" in out
    assert not (base / CLAIM_REL).exists()
    assert ULID_L1 in (base / "deleted.toml").read_text(encoding="utf-8")
    origin_tree = git(origin, "ls-tree", "-r", "--name-only", "refs/heads/main")
    assert CLAIM_REL not in origin_tree


# --- Phase 4: M4 (timeouts + missing-binary diagnostics), gh JSON hygiene ----


def test_git_env_sets_terminal_prompt_off(monkeypatch):
    """M4: a git spawn must never hang waiting for a credential prompt."""
    env = git_env({"PATH": "/usr/bin"})
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "GIT_DIR" not in env


def test_git_timeout_maps_to_the_e_git_diagnostic(monkeypatch):
    """M4: a hung git surfaces as E-GIT (the site's own error family), never
    blocks forever."""
    from masora import sync as sync_mod

    def hung(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=60)

    monkeypatch.setattr(sync_mod.subprocess, "run", hung)
    with pytest.raises(sync_mod.SyncError) as excinfo:
        sync_mod._git(Path("/tmp/nowhere"), "status")
    assert excinfo.value.diag.code == "E-GIT"
    assert "timed out" in excinfo.value.diag.message


def test_missing_git_binary_maps_to_a_diagnostic_not_a_traceback(monkeypatch):
    """LOW: FileNotFoundError from a missing binary is mapped into the same
    error surface as the timeouts."""
    from masora import sync as sync_mod

    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(sync_mod.subprocess, "run", missing)
    with pytest.raises(sync_mod.SyncError) as excinfo:
        sync_mod._git(Path("/tmp/nowhere"), "status")
    assert excinfo.value.diag.code == "E-GIT"
    assert "PATH" in excinfo.value.diag.message


def test_optional_git_reads_stay_optional_on_timeout(monkeypatch):
    """Sites whose contract treats a git failure as 'unavailable' keep that
    contract on a timeout (None, never a raise)."""
    from masora import sync as sync_mod

    def hung(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=60)

    monkeypatch.setattr(sync_mod.subprocess, "run", hung)
    assert sync_mod._optional_rev(Path("/tmp/nowhere"), "HEAD") is None
    assert sync_mod._head_branch(Path("/tmp/nowhere")) is None
    assert sync_mod._git_show_optional(Path("/tmp/nowhere"), "HEAD") is None


def test_gh_pr_list_malformed_json_is_a_note(monkeypatch, capsys):
    """LOW: malformed forge output is caught and reported — no traceback."""
    from masora import sync as sync_mod

    class Fake:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(sync_mod.subprocess, "run", lambda *a, **k: Fake())
    assert sync_mod._gh_pr_list("gh", "org/proj", "masora/pending") is None
    assert "could not parse" in capsys.readouterr().out


def test_gh_timeout_is_a_note(monkeypatch, capsys):
    from masora import sync as sync_mod

    def hung(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=30)

    monkeypatch.setattr(sync_mod.subprocess, "run", hung)
    assert sync_mod._gh_pr_list("gh", "org/proj", "masora/pending") is None
    assert "timed out" in capsys.readouterr().out
    assert sync_mod._gh_run("gh", ["pr", "list"], "body") == ""


# --- Per-author pending branch (masora/<author>) ---


def slug_for(base: Path, name: str) -> str:
    git(base, "config", "user.name", name)
    from masora.sync import pending_branch

    return pending_branch(base)


def test_author_slug_spaces_and_dots_become_dashes(repo):
    base, _origin = repo
    assert slug_for(base, "Masora Test") == "masora/masora-test"
    assert slug_for(base, "Ada B. Lovelace") == "masora/ada-b-lovelace"


def test_author_slug_drops_unicode_and_caps_length(repo):
    base, _origin = repo
    assert slug_for(base, "Sébastien") == "masora/sbastien"
    assert slug_for(
        base, "a-very-long-name-with-many-words-exceeding-the-limit"
    ) == "masora/" + "a-very-long-name-with-many-words"[
        : 24 - len("a-very-long-name-with-many-words")
    ].rstrip("-")


def test_author_slug_is_deterministic(repo):
    base, _origin = repo
    first = slug_for(base, "Alice Oexample")
    second = slug_for(base, "Alice Oexample")
    assert first == second


def test_missing_identity_refuses_with_egit_and_remedy(repo, capsys):
    base, _origin = repo
    git(base, "config", "user.name", "")
    from masora.sync import SyncError, pending_branch

    with pytest.raises(SyncError) as excinfo:
        pending_branch(base)
    assert excinfo.value.diag.code == "E-GIT"
    assert "user.name" in excinfo.value.diag.message


def test_identity_of_only_dropped_characters_refuses(repo):
    base, _origin = repo
    git(base, "config", "user.name", "李明")
    from masora.sync import SyncError, pending_branch

    with pytest.raises(SyncError):
        pending_branch(base)


def test_sync_publishes_on_the_author_branch(repo, fake_gh, github_remote, capsys):
    """End-to-end: branch create, push, PR head and drop cleanup all use
    masora/<author>, derived from the clone's git identity."""
    base, origin = repo
    from masora.sync import pending_branch

    branch = pending_branch(base)
    write_event(
        base,
        CLAIM_REL,
        make_claim(ULID_L1, unanchored=True, anchors=OMIT, unanchored_reason="no anchors"),
    )
    assert sync_run(base, yes=True) == 0
    assert rev_ok(origin, f"refs/heads/{branch}")
    assert rev_ok(base, f"refs/heads/{branch}")
    create = next(call for call in gh_calls(fake_gh) if call["args"][:2] == ["pr", "create"])
    assert branch in create["args"]

    # cleanup: --drop deletes the same per-author branch locally and remotely
    assert sync_run(base, drop=True, yes=True) == 0
    assert not rev_ok(origin, f"refs/heads/{branch}")
    assert not rev_ok(base, f"refs/heads/{branch}")


def test_two_authors_get_two_independent_pending_branches(
    repo, tmp_path, fake_gh, github_remote, capsys
):
    """The multi-writer point of the change: two clones of the same base push
    their pending sets to two different branches — no shared-branch collision."""
    base, origin = repo
    from masora.sync import pending_branch

    worker = tmp_path / "worker"
    subprocess.run(
        ["git", "clone", str(origin), str(worker)], capture_output=True, check=True, env=git_env()
    )
    git(worker, "config", "user.name", "Other Author")
    git(worker, "config", "user.email", "other@example.invalid")

    base_branch = pending_branch(base)
    worker_branch = pending_branch(worker)
    assert base_branch != worker_branch

    write_event(
        base,
        CLAIM_REL,
        make_claim(ULID_L1, unanchored=True, anchors=OMIT, unanchored_reason="no anchors"),
    )
    assert sync_run(base, yes=True) == 0

    worker_rel = "2026-09/x/01J8Z3K0000000000000000006.claim.md"
    write_event(
        worker,
        worker_rel,
        make_claim(ULID_L2, unanchored=True, anchors=OMIT, unanchored_reason="no anchors"),
    )
    assert sync_run(worker, yes=True) == 0

    assert rev_ok(origin, f"refs/heads/{base_branch}")
    assert rev_ok(origin, f"refs/heads/{worker_branch}")
