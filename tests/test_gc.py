"""Tests for `masora gc` (plan/confirm flow, tombstone writing, sync acceptance)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from helpers import (
    ULID_L1,
    ULID_L2,
    ULID_L3,
    ULID_R1A,
    ULID_V1A,
    make_claim,
    make_doubt,
    make_verify,
    write_event,
)

from masora.checker import check_base
from masora.cli import main
from masora.diagnostics import Diag
from masora.gc import run as gc_run
from masora.sync import git_env
from masora.sync import run as sync_run

CLAIM_REL = "2026-09/x/01J8Z3K0000000000000000000.claim.md"
VERIFY_REL = "2026-09/x/01J8Z3K0000000000000000001.verify.md"
REFUTE_REL = "2026-09/x/01J8Z3K0000000000000000004.refute.md"
L2_REL = "2026-09/y/01J8Z3K0000000000000000006.claim.md"
L3_REL = "2026-09/z/01J8Z3K0000000000000000007.claim.md"


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


def seed(base: Path, message: str = "seed") -> None:
    git(base, "add", "-A")
    git(base, "commit", "-m", message)
    git(base, "push", "origin", "main")


def tombstone(lineage: str, ulids: list[str]) -> str:
    ulids_text = ", ".join(f'"{ulid}"' for ulid in ulids)
    return f'[[deleted]]\nlineage = "{lineage}"\nulids = [{ulids_text}]\n'


def tree_bytes(base: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(base)): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


@pytest.fixture
def repo(tmp_path) -> tuple[Path, Path]:
    tmp = tmp_path
    base = tmp / "base"
    base.mkdir()
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


def test_gc_plan_prints_files_and_mutates_nothing(base, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, L2_REL, make_claim(ULID_L2))
    before = tree_bytes(base)

    code = gc_run(base, [ULID_L1])

    assert code == 3
    out = capsys.readouterr().out
    assert f"lineage {ULID_L1}: 2 event file(s)" in out
    assert f"delete {CLAIM_REL} (claim)" in out
    assert f"delete {VERIFY_REL} (verify)" in out
    assert "plan only: nothing written" in out
    assert ULID_L2 not in out
    assert tree_bytes(base) == before
    assert not (base / "deleted.toml").exists()


def test_gc_happy_path_deletes_files_and_tombstones(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, L2_REL, make_claim(ULID_L2))
    seed(base)

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 2
    out = capsys.readouterr().out
    assert "W-GC-ACTIVE" in out
    assert not (base / CLAIM_REL).exists()
    assert not (base / VERIFY_REL).exists()
    assert not (base / "2026-09/x").exists()
    assert (base / L2_REL).exists()
    assert (base / "deleted.toml").read_text(encoding="utf-8") == tombstone(
        ULID_L1, [ULID_L1, ULID_V1A]
    )
    assert check_base(base).errors == []


def test_gc_fully_refuted_lineage_exits_clean(base, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, REFUTE_REL, make_doubt(ULID_R1A, ULID_L1, ULID_L1, kind="refute"))

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "W-GC-ACTIVE" not in out
    assert "collected: 1 lineage(s), 2 event file(s) removed" in out
    assert not (base / CLAIM_REL).exists()
    assert not (base / REFUTE_REL).exists()
    assert check_base(base).errors == []


def test_gc_appends_to_existing_tombstone(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    seed(base)
    (base / "deleted.toml").write_text(tombstone(ULID_L2, [ULID_L2]), encoding="utf-8")
    existing = (base / "deleted.toml").read_text(encoding="utf-8")

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 2
    content = (base / "deleted.toml").read_text(encoding="utf-8")
    assert content.startswith(existing)
    assert f'lineage = "{ULID_L1}"' in content
    assert check_base(base).errors == []


def test_gc_twice_is_idempotent(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    seed(base)
    assert gc_run(base, [ULID_L1], yes=True) == 2
    capsys.readouterr()
    tomb_after_first = (base / "deleted.toml").read_bytes()
    files_after_first = tree_bytes(base)

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "already tombstoned" in out
    assert "nothing to collect" in out
    assert (base / "deleted.toml").read_bytes() == tomb_after_first
    assert tree_bytes(base) == files_after_first


def test_gc_multiple_lineages_in_one_run(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, L2_REL, make_claim(ULID_L2))
    write_event(base, L3_REL, make_claim(ULID_L3))
    seed(base)

    code = gc_run(base, [ULID_L1, ULID_L2], yes=True)

    assert code == 2
    assert not (base / CLAIM_REL).exists()
    assert not (base / L2_REL).exists()
    assert (base / L3_REL).exists()
    content = (base / "deleted.toml").read_text(encoding="utf-8")
    assert content.count("[[deleted]]") == 2
    assert check_base(base).errors == []


def test_gc_unknown_lineage_is_rejected(base, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = gc_run(base, [ULID_L3], yes=True)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-GC-UNKNOWN" in out
    assert not (base / "deleted.toml").exists()
    assert (base / CLAIM_REL).exists()


def test_gc_malformed_ulid_is_rejected(base, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))

    code = gc_run(base, ["01J8Z3K00000000000000000"], yes=True)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-GC-ULID" in out
    assert not (base / "deleted.toml").exists()
    assert (base / CLAIM_REL).exists()


def test_gc_event_ulid_is_not_a_lineage(base, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))

    code = gc_run(base, [ULID_V1A], yes=True)

    assert code == 1
    assert "E-GC-UNKNOWN" in capsys.readouterr().out
    assert (base / VERIFY_REL).exists()


def test_gc_pre_check_errors_block_mutation(base, capsys):
    event = base / CLAIM_REL
    event.parent.mkdir(parents=True)
    event.write_text("---\n^ invalid: [\n---\n", encoding="utf-8")

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "pre-check" in out
    assert not (base / "deleted.toml").exists()


def test_gc_post_check_failure_is_reported(repo, monkeypatch, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    seed(base)
    real = check_base
    calls = {"count": 0}

    def fake(base_dir):
        calls["count"] += 1
        result = real(base_dir)
        if calls["count"] == 2:
            result.diags.append(Diag("error", "E-DUP-ID", "synthetic post-check failure"))
        return result

    monkeypatch.setattr("masora.gc.check_base", fake)

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-GC-CHECK" in out
    assert "post-check" in out
    assert not (base / CLAIM_REL).exists()
    assert (base / "deleted.toml").exists()


def test_cli_gc_plan_then_confirm(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, REFUTE_REL, make_doubt(ULID_R1A, ULID_L1, ULID_L1, kind="refute"))
    seed(base)
    before = tree_bytes(base)

    assert main(["gc", str(base), "--lineage", ULID_L1]) == 3
    plan_out = capsys.readouterr().out
    assert "plan only: nothing written" in plan_out
    assert f"lineage {ULID_L1}: 2 event file(s)" in plan_out
    assert tree_bytes(base) == before
    assert not (base / "deleted.toml").exists()

    assert main(["gc", str(base), "--lineage", ULID_L1, "--yes"]) == 0
    out = capsys.readouterr().out
    assert "collected: 1 lineage(s), 2 event file(s) removed" in out
    assert not (base / CLAIM_REL).exists()
    assert not (base / REFUTE_REL).exists()
    assert (base / "deleted.toml").read_text(encoding="utf-8") == tombstone(
        ULID_L1, [ULID_L1, ULID_R1A]
    )
    assert check_base(base).errors == []


def test_gc_then_sync_accepts_tombstoned_lineage(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, L2_REL, make_claim(ULID_L2))
    seed(base)

    assert gc_run(base, [ULID_L1], yes=True) == 2
    code = sync_run(base)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-GC-UNAVAILABLE" not in out
    assert "2 deleted" in out
    assert "synced: 0 pending event(s) + tombstone additions" in out
    pending = git(origin, "ls-tree", "-r", "--name-only", "refs/heads/masora/pending").splitlines()
    assert CLAIM_REL not in pending and VERIFY_REL not in pending
    assert L2_REL in pending and "deleted.toml" in pending
    tombstoned = git(origin, "show", "refs/heads/masora/pending:deleted.toml")
    assert tombstoned.strip() == tombstone(ULID_L1, [ULID_L1, ULID_V1A]).strip()


UNPUBLISHED_LABEL = "unpublished — removed locally, no tombstone (origin/main never saw it)"


def test_gc_unpublished_lineage_removes_files_without_tombstone(repo, capsys):
    base, _origin = repo
    # The events were never pushed: origin/main's tree holds base.toml only.
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, REFUTE_REL, make_doubt(ULID_R1A, ULID_L1, ULID_L1, kind="refute"))
    origin_main_before = git(base, "rev-parse", "refs/remotes/origin/main")

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert UNPUBLISHED_LABEL in out
    assert "tombstone:" not in out
    assert "collected: 1 lineage(s), 2 event file(s) removed, 1 unpublished (no tombstone)" in out
    assert not (base / CLAIM_REL).exists()
    assert not (base / REFUTE_REL).exists()
    assert not (base / "deleted.toml").exists()
    assert check_base(base).errors == []
    assert git(base, "rev-parse", "refs/remotes/origin/main") == origin_main_before


def test_gc_published_lineage_still_tombstones(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, REFUTE_REL, make_doubt(ULID_R1A, ULID_L1, ULID_L1, kind="refute"))
    seed(base)

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert UNPUBLISHED_LABEL not in out
    assert "tombstone: append 1 [[deleted]] block(s) to deleted.toml" in out
    assert not (base / CLAIM_REL).exists()
    assert not (base / REFUTE_REL).exists()
    assert (base / "deleted.toml").read_text(encoding="utf-8") == tombstone(
        ULID_L1, [ULID_L1, ULID_R1A]
    )
    assert check_base(base).errors == []


def test_gc_mixed_request_splits_published_and_unpublished(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    seed(base)
    write_event(base, L2_REL, make_claim(ULID_L2))

    code = gc_run(base, [ULID_L1, ULID_L2], yes=True)

    assert code == 2
    out = capsys.readouterr().out
    assert f"lineage {ULID_L2}: 1 event file(s)" in out
    assert UNPUBLISHED_LABEL in out
    assert "tombstone: append 1 [[deleted]] block(s) to deleted.toml" in out
    assert not (base / CLAIM_REL).exists()
    assert not (base / L2_REL).exists()
    assert (base / "deleted.toml").read_text(encoding="utf-8") == tombstone(
        ULID_L1, [ULID_L1, ULID_V1A]
    )
    assert check_base(base).errors == []


def test_gc_unpublished_lineage_without_origin_deletes_locally(tmp_path, capsys):
    base = tmp_path / "solo-base"
    base.mkdir()
    git(base, "init", "-b", "main")
    git(base, "config", "user.name", "Masora Test")
    git(base, "config", "user.email", "masora@example.invalid")
    (base / "base.toml").write_text('name = "test-base"\n', encoding="utf-8")
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, REFUTE_REL, make_doubt(ULID_R1A, ULID_L1, ULID_L1, kind="refute"))

    code = gc_run(base, [ULID_L1], yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert UNPUBLISHED_LABEL in out
    assert not (base / CLAIM_REL).exists()
    assert not (base / REFUTE_REL).exists()
    assert not (base / "deleted.toml").exists()
    assert check_base(base).errors == []
