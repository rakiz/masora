"""Tests for `masora compact` (witness selection, fold-equality proof, tombstones)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import (
    ULID_D1A,
    ULID_L1,
    ULID_L2,
    ULID_L3,
    ULID_R1A,
    ULID_U1A,
    ULID_V1A,
    ULID_V2A,
    make_claim,
    make_doubt,
    make_verify,
    write_event,
)
from test_fold_bruteforce import enumerate_graphs, has_cycle, sample_graphs

from masora.checker import check_base
from masora.cli import main
from masora.compact import _status_tuple, observable_state, select_witness
from masora.compact import run as compact_run
from masora.fold import Event, fold_lineage, resolve_activity
from masora.sync import git_env
from masora.sync import run as sync_run

CLAIM_REL = "2026-09/x/01J8Z3K0000000000000000000.claim.md"
VERIFY_REL = "2026-09/x/01J8Z3K0000000000000000001.verify.md"
DOUBT_REL = "2026-09/x/01J8Z3K0000000000000000002.doubt.md"
UNDOUBT_REL = "2026-09/x/01J8Z3K0000000000000000003.undoubt.md"
V2_REL = "2026-09/x/01J8Z3K0000000000000000005.claim.md"
L2_REL = "2026-09/y/01J8Z3K0000000000000000006.claim.md"
ULID_R2 = "01J8Z3K0000000000000000009"
ULID_C3 = "01J8Z3K000000000000000000A"
ULID_R3 = "01J8Z3K000000000000000000B"
ULID_D2 = "01J8Z3K000000000000000000C"
ULID_U2 = "01J8Z3K000000000000000000D"
C3_REL = "2026-09/x/01J8Z3K000000000000000000A.claim.md"
R1_REL = "2026-09/x/01J8Z3K0000000000000000004.refute.md"
R2_REL = "2026-09/x/01J8Z3K0000000000000000009.refute.md"
R3_REL = "2026-09/x/01J8Z3K000000000000000000B.refute.md"
BARE_HOME = f"2026-09/{ULID_L1}"
CANON_HOME = f"2026-09/one-line-summary-{ULID_L1}"
NEXT_MONTH = f"2026-10/{ULID_L1}"
VERIFY2_REL = f"{NEXT_MONTH}/01J8Z3K0000000000000000005.verify.md"


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


def write_undoubt_pair(base: Path) -> None:
    write_event(base, DOUBT_REL, make_doubt(ULID_D1A, ULID_L1, ULID_V1A))
    write_event(base, UNDOUBT_REL, make_doubt(ULID_U1A, ULID_L1, ULID_D1A, kind="undoubt"))


def deleted_events_tombstone(lineage: str, ulids: list[str]) -> str:
    ulids_text = ", ".join(f'"{ulid}"' for ulid in ulids)
    return f'[[deleted_events]]\nlineage = "{lineage}"\nulids = [{ulids_text}]\n'


def _assert_witness_preserves(events: list[Event]) -> None:
    lineage = events[0].lineage
    claims = [e for e in events if e.kind == "claim"]
    founder_present = any(e.id == lineage for e in claims)
    eligible = [e.id for e in claims if e.id == lineage or founder_present]
    activity = resolve_activity(list(events))
    fold_full = fold_lineage(lineage, list(events), activity, eligible, provider_available=False)
    kept = select_witness(lineage, list(events), eligible, activity)
    witness = [e for e in events if e.id in kept]
    wit_activity = resolve_activity(witness)
    wit_eligible = [v for v in eligible if v in kept]
    fold_wit = fold_lineage(lineage, witness, wit_activity, wit_eligible, provider_available=False)
    kept_versions = [v for v in eligible if v in kept]
    assert observable_state(fold_full, activity, kept_versions) == observable_state(
        fold_wit, wit_activity, kept_versions
    ), (events, kept)


@pytest.mark.parametrize("n", (1, 2, 3, 4))
def test_witness_preserves_the_fold_exhaustively(n):
    checked = 0
    for events in enumerate_graphs(n):
        if has_cycle(list(events)):
            continue
        _assert_witness_preserves(list(events))
        checked += 1
    assert checked > 0


def test_witness_preserves_the_fold_on_sampled_dags():
    for events in sample_graphs(5, 2000):
        _assert_witness_preserves(list(events))


def test_compact_plan_prints_and_writes_nothing(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_undoubt_pair(base)
    before = tree_bytes(base)

    code = compact_run(base)

    assert code == 3
    out = capsys.readouterr().out
    assert f"lineage {ULID_L1}: keep 2 of 4 event file(s), drop 2 (2 unpublished)" in out
    assert f"drop {DOUBT_REL} (doubt)" in out
    assert f"drop {UNDOUBT_REL} (undoubt)" in out
    assert "plan only: nothing written" in out
    assert "tombstone:" not in out
    assert tree_bytes(base) == before
    assert not (base / "deleted.toml").exists()


def test_compact_executes_tombstones_and_keeps_survivors_byte_identical(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_undoubt_pair(base)
    write_event(base, L2_REL, make_claim(ULID_L2))
    seed(base)
    before = tree_bytes(base)

    code = compact_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert f"drop {DOUBT_REL} (doubt)" in out
    assert "compacted: 2 event file(s) removed across 1 lineage(s), 2 tombstoned" in out
    after = tree_bytes(base)
    assert DOUBT_REL not in after and UNDOUBT_REL not in after
    assert not (base / "2026-09/x").exists() or (base / "2026-09/x").is_dir()
    for rel in (CLAIM_REL, VERIFY_REL, L2_REL):
        assert after[rel] == before[rel], rel
    assert (base / "deleted.toml").read_text(encoding="utf-8") == deleted_events_tombstone(
        ULID_L1, [ULID_D1A, ULID_U1A]
    )
    assert check_base(base).errors == []


def test_compact_without_git_drops_unpublished_silently(base, capsys):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_undoubt_pair(base)

    code = compact_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "(2 unpublished)" in out
    assert "tombstone:" not in out
    assert not (base / "deleted.toml").exists()
    assert (base / CLAIM_REL).exists() and (base / VERIFY_REL).exists()
    assert check_base(base).errors == []


def test_compact_tombstones_only_events_known_to_origin(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, DOUBT_REL, make_doubt(ULID_D1A, ULID_L1, ULID_V1A))
    seed(base)
    write_event(base, UNDOUBT_REL, make_doubt(ULID_U1A, ULID_L1, ULID_D1A, kind="undoubt"))

    code = compact_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert f"lineage {ULID_L1}: keep 2 of 4 event file(s), drop 2 (1 unpublished)" in out
    assert (base / "deleted.toml").read_text(encoding="utf-8") == deleted_events_tombstone(
        ULID_L1, [ULID_D1A]
    )
    assert not (base / DOUBT_REL).exists()
    assert not (base / UNDOUBT_REL).exists()
    assert check_base(base).errors == []


def test_compact_all_refuted_lineage_is_negative_knowledge_kept(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, V2_REL, make_claim(ULID_V2A, lineage=ULID_L1, reason="v2 after code change"))
    write_event(base, R1_REL, make_doubt(ULID_R1A, ULID_L1, ULID_L1, kind="refute"))
    write_event(base, R2_REL, make_doubt(ULID_R2, ULID_L1, ULID_V2A, kind="refute"))
    seed(base)

    code = compact_run(base, yes=True)

    assert code == 0
    assert "nothing to compact: every lineage is already at its minimal witness set" in (
        capsys.readouterr().out
    )
    assert not (base / "deleted.toml").exists()
    assert len(tree_bytes(base)) == 5


def test_compact_restored_keeps_only_the_newest_refutation(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, V2_REL, make_claim(ULID_V2A, lineage=ULID_L1, reason="v2 after code change"))
    write_event(base, R1_REL, make_doubt(ULID_R1A, ULID_L1, ULID_V2A, kind="refute"))
    write_event(base, C3_REL, make_claim(ULID_C3, lineage=ULID_L1, reason="v3 after code change"))
    write_event(base, R3_REL, make_doubt(ULID_R3, ULID_L1, ULID_C3, kind="refute"))
    seed(base)
    envelope = next(env for env in check_base(base).envelopes if env["lineage"] == ULID_L1)
    assert envelope["restored"] is True

    code = compact_run(base, yes=True)

    assert code == 0
    assert not (base / V2_REL).exists()
    assert not (base / R2_REL).exists()
    assert (base / CLAIM_REL).exists()
    assert (base / VERIFY_REL).exists()
    assert (base / C3_REL).exists()
    assert (base / R3_REL).exists()
    assert (base / "deleted.toml").read_text(encoding="utf-8") == deleted_events_tombstone(
        ULID_L1, [ULID_R1A, ULID_V2A]
    )
    post = check_base(base)
    assert post.errors == []
    post_envelope = next(env for env in post.envelopes if env["lineage"] == ULID_L1)
    assert _status_tuple(post_envelope) == _status_tuple(envelope)


def test_compact_refuses_diverging_lineage_fail_closed(repo, monkeypatch, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    seed(base)
    before = tree_bytes(base)
    monkeypatch.setattr("masora.compact.select_witness", lambda *args: set())

    code = compact_run(base, yes=True)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-COMPACT-DIVERGE" in out
    assert "nothing written" in out
    assert tree_bytes(base) == before
    assert not (base / "deleted.toml").exists()


def test_compact_post_check_failure_is_reported(repo, monkeypatch, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_undoubt_pair(base)
    seed(base)
    real = check_base
    calls = {"count": 0}

    def fake(base_dir):
        calls["count"] += 1
        result = real(base_dir)
        if calls["count"] == 2:
            from masora.diagnostics import Diag

            result.diags.append(Diag("error", "E-DUP-ID", "synthetic post-check failure"))
        return result

    monkeypatch.setattr("masora.compact.check_base", fake)

    code = compact_run(base, yes=True)

    assert code == 1
    out = capsys.readouterr().out
    assert "E-COMPACT-CHECK" in out
    assert "restore with git restore" in out
    assert not (base / DOUBT_REL).exists()
    assert (base / "deleted.toml").exists()


def test_compact_twice_is_idempotent(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_undoubt_pair(base)
    seed(base)
    assert compact_run(base, yes=True) == 0
    capsys.readouterr()
    tomb_after_first = (base / "deleted.toml").read_bytes()
    files_after_first = tree_bytes(base)

    code = compact_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "nothing to compact" in out
    assert (base / "deleted.toml").read_bytes() == tomb_after_first
    assert tree_bytes(base) == files_after_first


def test_compact_then_sync_accepts_tombstoned_events(repo, capsys):
    base, origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_undoubt_pair(base)
    write_event(base, L2_REL, make_claim(ULID_L2))
    seed(base)

    assert compact_run(base, yes=True) == 0
    code = sync_run(base, yes=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "E-REWRITE" not in out
    assert "2 deleted" in out
    assert "synced: 0 pending event(s) + tombstone additions" in out
    pending = git(origin, "ls-tree", "-r", "--name-only", "refs/heads/masora/pending").splitlines()
    assert DOUBT_REL not in pending and UNDOUBT_REL not in pending
    assert CLAIM_REL in pending and VERIFY_REL in pending and L2_REL in pending
    assert "deleted.toml" in pending
    tombstoned = git(origin, "show", "refs/heads/masora/pending:deleted.toml")
    assert tombstoned.strip() == deleted_events_tombstone(ULID_L1, [ULID_D1A, ULID_U1A]).strip()
    for rel in (CLAIM_REL, VERIFY_REL, L2_REL):
        assert git(origin, "show", f"refs/heads/masora/pending:{rel}").strip() == (
            (base / rel).read_text(encoding="utf-8").strip()
        )


def test_sync_rejects_untombstoned_partial_deletion(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    seed(base)

    (base / VERIFY_REL).unlink()
    code = sync_run(base)

    assert code == 1
    assert "E-REWRITE" in capsys.readouterr().out


def test_deleted_events_reject_readded_event_but_not_the_living_lineage(base):
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, DOUBT_REL, make_doubt(ULID_D1A, ULID_L1, ULID_L1))
    write_event(base, L2_REL, make_claim(ULID_L2))
    write_event(base, L2_REL.replace("y/", "z/"), make_claim(ULID_L3))
    (base / "deleted.toml").write_text(
        deleted_events_tombstone(ULID_L1, [ULID_D1A])
        + f'[[deleted]]\nlineage = "{ULID_L2}"\nulids = ["{ULID_L2}"]\n',
        encoding="utf-8",
    )

    result = check_base(base)

    rejected = {diag.path for diag in result.errors if diag.code == "E-TOMBSTONED"}
    assert rejected == {DOUBT_REL, L2_REL}
    assert all(diag.code != "E-TOMBSTONED" for diag in result.diags if diag.path == CLAIM_REL)


def test_cli_compact_plan_then_confirm(repo, capsys):
    base, _origin = repo
    write_event(base, CLAIM_REL, make_claim(ULID_L1))
    write_event(base, VERIFY_REL, make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_undoubt_pair(base)
    seed(base)
    before = tree_bytes(base)

    assert main(["compact", str(base)]) == 3
    plan_out = capsys.readouterr().out
    assert "plan only: nothing written" in plan_out
    assert f"lineage {ULID_L1}: keep 2 of 4 event file(s), drop 2 (0 unpublished)" in plan_out
    assert tree_bytes(base) == before

    assert main(["compact", str(base), "--yes"]) == 0
    out = capsys.readouterr().out
    assert "compacted: 2 event file(s) removed" in out
    assert not (base / DOUBT_REL).exists()
    assert not (base / UNDOUBT_REL).exists()
    assert (base / "deleted.toml").read_text(encoding="utf-8") == deleted_events_tombstone(
        ULID_L1, [ULID_D1A, ULID_U1A]
    )
    assert check_base(base).errors == []


FIXTURES = sorted(path for path in (Path(__file__).parent / "fixtures").iterdir() if path.is_dir())


def test_compact_over_every_fixture_tree(tmp_path):
    for fixture in FIXTURES:
        work = tmp_path / fixture.name
        shutil.copytree(fixture, work)
        pre = check_base(work)

        code = compact_run(work)

        if code == 1:
            assert pre.errors, fixture.name
            continue
        assert code in (0, 3), (fixture.name, code)
        if code == 0:
            continue
        executed = tmp_path / f"{fixture.name}-yes"
        shutil.copytree(fixture, executed)
        code_yes = compact_run(executed, yes=True)
        assert code_yes in (0, 2), (fixture.name, code_yes)
        post = check_base(executed)
        assert post.errors == [], fixture.name
        before_env = {env["lineage"]: _status_tuple(env) for env in pre.envelopes}
        for env in post.envelopes:
            assert _status_tuple(env) == before_env[env["lineage"]], fixture.name


def test_rehome_plan_prints_and_writes_nothing(repo, capsys):
    base, _origin = repo
    write_event(base, f"{BARE_HOME}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(base, f"{BARE_HOME}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, VERIFY2_REL, make_verify(ULID_V2A, ULID_L1, ULID_L1))
    before = tree_bytes(base)

    assert main(["compact", str(base), "--rehome"]) == 3
    out = capsys.readouterr().out
    assert f"lineage {ULID_L1}: home {CANON_HOME}" in out
    assert f"move 2 file(s): {BARE_HOME} -> {CANON_HOME}" in out
    assert f"move 1 file(s): {NEXT_MONTH} -> {CANON_HOME}" in out
    assert "plan only: nothing written" in out
    assert tree_bytes(base) == before
    assert not (base / "deleted.toml").exists()


def test_rehome_renames_bare_ulid_dir_to_slug_form(repo, capsys):
    base, _origin = repo
    write_event(base, f"{BARE_HOME}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(base, f"{BARE_HOME}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1))
    before = tree_bytes(base)

    code = compact_run(base, yes=True, rehome=True)

    assert code == 0
    assert "rehomed: 2 event file(s) moved into canonical home(s)" in capsys.readouterr().out
    after = tree_bytes(base)
    assert not (base / BARE_HOME).exists()
    for rel, content in before.items():
        moved = rel.replace(BARE_HOME, CANON_HOME)
        assert after[moved] == content, moved


def test_rehome_merges_split_months_into_the_founder_home(repo, capsys):
    base, _origin = repo
    write_event(base, f"{BARE_HOME}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(base, f"{BARE_HOME}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, VERIFY2_REL, make_verify(ULID_V2A, ULID_L1, ULID_L1))
    drifted_bytes = (base / VERIFY2_REL).read_bytes()

    code = compact_run(base, yes=True, rehome=True)

    assert code == 0
    assert not (base / NEXT_MONTH).exists()
    assert not (base / "2026-10").exists()
    assert (base / CANON_HOME / f"{ULID_L1}.claim.md").is_file()
    assert (base / CANON_HOME / f"{ULID_V1A}.verify.md").is_file()
    assert (base / CANON_HOME / f"{ULID_V2A}.verify.md").read_bytes() == drifted_bytes
    assert check_base(base).errors == []
    assert "compacted: " not in capsys.readouterr().out


def test_rehome_already_canonical_is_a_no_op(repo, capsys):
    base, _origin = repo
    write_event(base, f"{CANON_HOME}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(base, f"{CANON_HOME}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1))
    before = tree_bytes(base)

    code = compact_run(base, yes=True, rehome=True)

    assert code == 0
    assert (
        "nothing to rehome: every lineage is at its minimal witness set in its canonical home"
        in capsys.readouterr().out
    )
    assert tree_bytes(base) == before
    assert not (base / "deleted.toml").exists()


def test_rehome_twice_is_idempotent(repo, capsys):
    base, _origin = repo
    write_event(base, f"{BARE_HOME}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(base, f"{BARE_HOME}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, VERIFY2_REL, make_verify(ULID_V2A, ULID_L1, ULID_L1))
    assert compact_run(base, yes=True, rehome=True) == 0
    capsys.readouterr()
    after_first = tree_bytes(base)

    code = compact_run(base, yes=True, rehome=True)

    assert code == 0
    assert "nothing to rehome" in capsys.readouterr().out
    assert tree_bytes(base) == after_first


def test_rehome_and_compact_combined(repo, capsys):
    base, _origin = repo
    write_event(base, f"{BARE_HOME}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(base, f"{BARE_HOME}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, f"{BARE_HOME}/{ULID_D1A}.doubt.md", make_doubt(ULID_D1A, ULID_L1, ULID_V1A))
    write_event(
        base,
        f"{BARE_HOME}/{ULID_U1A}.undoubt.md",
        make_doubt(ULID_U1A, ULID_L1, ULID_D1A, kind="undoubt"),
    )
    seed(base)
    write_event(
        base,
        f"{NEXT_MONTH}/{ULID_V2A}.claim.md",
        make_claim(ULID_V2A, lineage=ULID_L1, reason="v2 after code change"),
    )
    write_event(
        base,
        f"{NEXT_MONTH}/{ULID_R2}.refute.md",
        make_doubt(ULID_R2, ULID_L1, ULID_V2A, kind="refute"),
    )
    write_event(base, f"{NEXT_MONTH}/{ULID_D2}.doubt.md", make_doubt(ULID_D2, ULID_L1, ULID_V1A))
    write_event(
        base,
        f"{NEXT_MONTH}/{ULID_U2}.undoubt.md",
        make_doubt(ULID_U2, ULID_L1, ULID_D2, kind="undoubt"),
    )
    tombstone_before = (base / "deleted.toml").exists()

    code = compact_run(base, yes=True, rehome=True)

    assert code == 0
    out = capsys.readouterr().out
    assert f"drop {BARE_HOME}/{ULID_D1A}.doubt.md (doubt)" in out
    assert f"drop {NEXT_MONTH}/{ULID_D2}.doubt.md (doubt)" in out
    assert f"lineage {ULID_L1}: home {CANON_HOME}" in out
    assert f"move 2 file(s): {BARE_HOME} -> {CANON_HOME}" in out
    assert f"move 2 file(s): {NEXT_MONTH} -> {CANON_HOME}" in out
    assert "compacted: 4 event file(s) removed across 1 lineage(s), 2 tombstoned" in out
    assert not tombstone_before
    survivors = (
        f"{ULID_L1}.claim.md",
        f"{ULID_V1A}.verify.md",
        f"{ULID_V2A}.claim.md",
        f"{ULID_R2}.refute.md",
    )
    for name in survivors:
        assert (base / CANON_HOME / name).is_file(), name
    dropped = (
        f"{ULID_D1A}.doubt.md",
        f"{ULID_U1A}.undoubt.md",
        f"{ULID_D2}.doubt.md",
        f"{ULID_U2}.undoubt.md",
    )
    for name in dropped:
        assert not (base / CANON_HOME / name).exists(), name
    assert not (base / BARE_HOME).exists() and not (base / NEXT_MONTH).exists()
    assert (base / "deleted.toml").read_text(encoding="utf-8") == deleted_events_tombstone(
        ULID_L1, [ULID_D1A, ULID_U1A]
    )
    assert check_base(base).errors == []


def test_rehome_returns_drifted_extension_to_the_founder_month(repo, capsys):
    base, _origin = repo
    write_event(base, f"{CANON_HOME}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(base, f"{CANON_HOME}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1))
    drifted_rel = VERIFY2_REL
    write_event(base, drifted_rel, make_verify(ULID_V2A, ULID_L1, ULID_L1))
    drifted_bytes = (base / drifted_rel).read_bytes()

    code = compact_run(base, yes=True, rehome=True)

    assert code == 0
    assert not (base / NEXT_MONTH).exists()
    assert not (base / "2026-10").exists()
    assert (base / CANON_HOME / f"{ULID_V2A}.verify.md").read_bytes() == drifted_bytes
    assert (base / CANON_HOME / f"{ULID_V1A}.verify.md").is_file()
    assert (base / CANON_HOME / f"{ULID_L1}.claim.md").is_file()
    assert check_base(base).errors == []


def test_rehome_keeps_check_green(repo, capsys):
    base, _origin = repo
    write_event(base, f"{BARE_HOME}/{ULID_L1}.claim.md", make_claim(ULID_L1))
    write_event(base, f"{BARE_HOME}/{ULID_V1A}.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1))
    write_event(base, VERIFY2_REL, make_verify(ULID_V2A, ULID_L1, ULID_L1))
    assert check_base(base).errors == []

    code = compact_run(base, yes=True, rehome=True)

    assert code == 0
    assert check_base(base).errors == []
    assert check_base(base).warnings == []
    assert not (base / "deleted.toml").exists()
