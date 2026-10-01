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

    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "2 added, 0 unchanged, 0 rewritten, 0 deleted" in out
    assert git(origin, "rev-parse", "refs/heads/main") == main_before
    pending = git(base, "rev-parse", "refs/heads/masora/pending")
    assert pending == git(origin, "rev-parse", "refs/heads/masora/pending")
    assert git(base, "rev-parse", "masora/pending^") == main_before
    assert "2026-09/x/01J8Z3K0000000000000000000.claim.md" in git(
        origin, "ls-tree", "-r", "--name-only", "masora/pending"
    )
    calls = gh_calls(fake_gh)
    assert [call["args"][:2] for call in calls] == [["pr", "list"], ["pr", "create"]]
    create = calls[1]
    assert "--head" in create["args"] and "masora/pending" in create["args"]
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

    code = sync_run(base)

    assert code == 0
    calls = gh_calls(fake_gh)
    assert [call["args"][:2] for call in calls] == [["pr", "list"], ["pr", "edit"]]
    assert "42" in calls[1]["args"]
    assert "One line summary" in calls[1]["stdin"]
    assert "updated PR https://github.com/acme/base/pull/42" in capsys.readouterr().out


def test_sync_idempotent_second_run(repo, fake_gh, github_remote, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base) == 0
    capsys.readouterr()
    calls_after_first = gh_calls(fake_gh)

    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "pending set unchanged: masora/pending already carries it" in out
    assert gh_calls(fake_gh) == calls_after_first


def test_sync_squash_merged_content_is_not_tampering(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    assert sync_run(base) == 0
    capsys.readouterr()
    main_before = git(origin, "rev-parse", "refs/heads/main")
    pending_tree = git(base, "rev-parse", "refs/heads/masora/pending^{tree}")
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
    assert not rev_ok(origin, "refs/heads/masora/pending")


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

    code = sync_run(base)

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
    assert sync_run(base) == 0
    capsys.readouterr()
    monkeypatch.setenv(
        "FAKE_GH_LIST", '[{"number": 42, "url": "https://github.com/acme/base/pull/42"}]'
    )

    code = sync_run(base, drop=True)

    assert code == 0
    out = capsys.readouterr().out
    assert f"dropped: {ULID_L1} claim: One line summary" in out
    assert "dropped 1 pending event(s)" in out
    calls = gh_calls(fake_gh)
    assert any(call["args"][:2] == ["pr", "close"] and "42" in call["args"] for call in calls)
    assert not rev_ok(origin, "refs/heads/masora/pending")
    assert not rev_ok(base, "refs/heads/masora/pending")


def test_sync_drop_without_forge_cli_still_deletes_remote_branch(repo, monkeypatch, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base) == 0
    capsys.readouterr()
    monkeypatch.setattr("masora.sync._gh_on_path", lambda: None)

    code = sync_run(base, drop=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "forge CLI (gh) not available" in out
    assert not rev_ok(origin, "refs/heads/masora/pending")
    assert not rev_ok(base, "refs/heads/masora/pending")


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

    code = sync_run(base, push=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "solo mode" in out
    assert not rev_ok(base, "refs/heads/masora/pending")
    assert not rev_ok(origin, "refs/heads/masora/pending")
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

    code = sync_run(base)

    assert code == 2
    out = capsys.readouterr().out
    assert "W-DANGLING" in out
    assert "synced with warnings: 2 warning(s)" in out
    assert rev_ok(origin, "refs/heads/masora/pending")


def test_sync_pr_body_unresolvable_target_falls_back_to_ulid(repo, fake_gh, github_remote):
    base, _origin = repo
    write_event(
        base,
        "2026-09/x/01J8Z3K0000000000000000002.doubt.md",
        make_doubt(ULID_D1A, ULID_L1, DANGLING),
    )

    code = sync_run(base)

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
    assert not rev_ok(origin, "refs/heads/masora/pending")


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

    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "https://github.com/acme/base/compare/main...masora/pending?expand=1" in out
    assert rev_ok(origin, "refs/heads/masora/pending")


def test_sync_non_github_remote_prints_manual_instruction(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "open the pull request from masora/pending to main" in out
    assert str(origin) in out
    assert rev_ok(origin, "refs/heads/masora/pending")


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
    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-REWRITE" not in out
    assert "E-GC-UNAVAILABLE" not in out
    assert "1 added" in out
    pending_files = git(
        base, "ls-tree", "-r", "--name-only", "refs/heads/masora/pending"
    ).splitlines()
    assert collab_rel in pending_files and CLAIM_REL in pending_files


def test_sync_up_to_date_requires_matching_remote_tracking_ref(
    repo, fake_gh, github_remote, capsys
):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base) == 0
    capsys.readouterr()
    calls_after_first = gh_calls(fake_gh)
    main_sha = git(origin, "rev-parse", "refs/heads/main")
    git(base, "push", "origin", f"{main_sha}:refs/heads/masora/pending", "--force")

    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "pending set unchanged" not in out
    assert "pushed branch masora/pending" in out
    assert len(gh_calls(fake_gh)) == len(calls_after_first) + 2
    pending = git(base, "rev-parse", "refs/heads/masora/pending")
    assert pending == git(origin, "rev-parse", "refs/heads/masora/pending")


def test_sync_drop_is_idempotent(repo, fake_gh, github_remote, monkeypatch, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    assert sync_run(base) == 0
    capsys.readouterr()
    monkeypatch.setenv(
        "FAKE_GH_LIST", '[{"number": 42, "url": "https://github.com/acme/base/pull/42"}]'
    )
    assert sync_run(base, drop=True) == 0
    calls_after_drop = gh_calls(fake_gh)
    assert any(call["args"][:2] == ["pr", "close"] for call in calls_after_drop)

    code = sync_run(base, drop=True)

    assert code == 0
    assert "nothing to drop" in capsys.readouterr().out
    assert gh_calls(fake_gh) == calls_after_drop
    assert not rev_ok(base, "refs/heads/masora/pending")
    assert not rev_ok(origin, "refs/heads/masora/pending")


def test_sync_pending_commit_excludes_stray_files(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    (base / "caches").mkdir()
    (base / "caches/data.bin").write_text("junk\n", encoding="utf-8")
    (base / ".venv").mkdir()
    (base / ".venv/lib.py").write_text("junk\n", encoding="utf-8")
    (base / "base.toml").write_text('name = "edited"\n', encoding="utf-8")

    code = sync_run(base)

    assert code == 0
    files = git(base, "ls-tree", "-r", "--name-only", "refs/heads/masora/pending").splitlines()
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

    assert sync_run(base) == 0

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

    assert sync_run(base) == 0

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

    assert sync_run(base) == 0

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


STACKED_STATEMENT = "x" * 1000


def test_sync_stacked_claim_refuses_publication(repo, capsys):
    base, origin = repo
    main_before = git(origin, "rev-parse", "refs/heads/main")
    write_event(base, CLAIM_REL, make_claim(ULID_L1, statement=STACKED_STATEMENT))

    code = sync_run(base)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-SYNC-STACKED" in out
    assert "one-line-summary" in out
    assert "statement is 1000 chars" in out
    assert "split into atomic notes" in out
    assert not rev_ok(origin, "refs/heads/masora/pending")
    assert git(origin, "rev-parse", "refs/heads/main") == main_before


def test_sync_allow_stacked_warns_and_publishes(repo, fake_gh, github_remote, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1, statement=STACKED_STATEMENT))

    code = sync_run(base, allow_stacked=True)

    assert code == 2
    out = capsys.readouterr().out
    assert "W-SYNC-STACKED" in out
    assert "one-line-summary" in out
    assert "statement is 1000 chars" in out
    assert "synced with warnings: 1 warning(s)" in out
    assert rev_ok(origin, "refs/heads/masora/pending")
    create = gh_calls(fake_gh)[1]
    assert "W-SYNC-STACKED" in create["stdin"]
    assert "one-line-summary" in create["stdin"]


def test_sync_clean_claim_passes_the_stacking_audit(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = sync_run(base)

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

    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-SYNC-STACKED" not in out
    assert "W-SYNC-STACKED" not in out
    assert "synced: 1 pending event(s)" in out
