"""Real-repo tests for the git relation adapter (masora/gitctx.py, §6.2).

Hermetic: every test builds throwaway git repos in tmp_path and drives the
adapter over subprocess `git` — the adapter itself never fetches and never
touches the network. Integration tests run the full `build_index` against a
real code checkout and pin the stamped relations and the degraded reporting.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
from helpers import OMIT, ULID_L1, ULID_L2, ULID_V1A, ULID_V2A, make_claim, write_event

from masora import gitctx
from masora.fold import Event, VersionContext
from masora.index import build_index
from masora.sync import git_env

CLAIM_REL = "2026-09/x/01J8Z3K0000000000000000000.claim.md"
V2_REL = "2026-09/x/01J8Z3K0000000000000000005.claim.md"
L2_REL = "2026-09/x/01J8Z3K0000000000000000006.claim.md"
MISSING_SHA = "ffffffffffffffffffffffffffffffffffffffff"


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


@pytest.fixture
def code_repo(tmp_path):
    path = tmp_path / "code"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Masora Test")
    git(path, "config", "user.email", "masora@example.invalid")
    return path


@pytest.fixture
def base(tmp_path):
    path = tmp_path / "base"
    path.mkdir()
    (path / "base.toml").write_text('name = "test-base"\ncode_remotes = []\n', encoding="utf-8")
    return path


def commit_file(repo: Path, name: str, content: str = "change\n") -> str:
    """Commit one file and return the new HEAD sha."""
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def tracked(code_repo: Path, tmp_path: Path) -> Path:
    """Give the code repo an `origin` bare remote with `main` tracking set up."""
    empty = subprocess.run(
        ["git", "-C", str(code_repo), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        check=False,
        env=git_env(),
    ).returncode
    if empty != 0:
        commit_file(code_repo, "init.txt")
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    git(code_repo, "remote", "add", "origin", str(origin))
    git(code_repo, "push", "-u", "origin", "main")
    return code_repo


def advance_origin(origin_remote: Path, name: str, content: str = "ahead\n") -> str:
    """Land a commit on the remote's main via a throwaway clone (the adapter
    never fetches — the TEST moves the remote, the local repo fetches)."""
    work = origin_remote.parent / f"push-{name}"
    subprocess.run(
        ["git", "clone", "--quiet", str(origin_remote), str(work)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    git(work, "config", "user.name", "Masora Test")
    git(work, "config", "user.email", "masora@example.invalid")
    (work / name).write_text(content, encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-m", name)
    git(work, "push", "origin", "main")
    return git(work, "rev-parse", "HEAD")


def note(uid: str, lineage: str, sha: str, **overrides) -> dict:
    """An unanchored claim established at `sha` (unanchored versions always
    match, so the selection is driven by the git context alone). v2+ claims
    (id != lineage) require a reason; v1 tolerates one."""
    return make_claim(
        uid,
        lineage,
        anchors=OMIT,
        unanchored=True,
        unanchored_reason="gitctx test note",
        reason="gitctx test note",
        recorded_at={"commit": sha, "graph_commit": None},
        **overrides,
    )


def relations(db: Path) -> list[tuple[str, str | None, str]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT version, relation, context_ordering FROM versions"
            " JOIN lineages USING (lineage) ORDER BY version"
        ).fetchall()
    finally:
        conn.close()


# --- the relation decision table ---------------------------------------------


def test_ancestor_and_head_equal_commits_are_in_line(code_repo):
    first = commit_file(code_repo, "a.txt")
    head = commit_file(code_repo, "b.txt")
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    contexts = prober.lineage_contexts({"v_old": first, "v_head": head})
    assert contexts["v_old"].relation == "in_line"
    assert contexts["v_head"].relation == "in_line"  # HEAD-equal counts
    # two primary probes plus ONE ancestry-pair question (the reverse
    # direction is a memo hit)
    assert prober.probe_count == 3


def test_divergent_commit_is_out_of_line(code_repo):
    commit_file(code_repo, "a.txt")
    git(code_repo, "checkout", "-b", "side")
    side = commit_file(code_repo, "side.txt")
    git(code_repo, "checkout", "main")
    commit_file(code_repo, "b.txt")  # main diverges from side
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    assert prober.lineage_contexts({"v": side})["v"].relation == "out_of_line"


def test_proper_ahead(code_repo, tmp_path):
    tracked(code_repo, tmp_path)
    local_head = git(code_repo, "rev-parse", "HEAD")
    ahead_sha = advance_origin(code_repo / ".." / "origin.git", "remote-work")
    git(code_repo, "fetch", "origin")  # the test fetches; the adapter never does
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    assert prober.line.upstream == ahead_sha  # the ref as present locally
    contexts = prober.lineage_contexts({"v_remote": ahead_sha, "v_local": local_head})
    # the remote commit is a proper descendant of HEAD below the upstream ref;
    # the local HEAD commit is an ancestor-or-equal of HEAD
    assert contexts["v_remote"].relation == "ahead"
    assert contexts["v_local"].relation == "in_line"
    assert prober.probe_count == 4  # ahead costs 3 probes, in_line 1, memo free


def test_ahead_restricted_to_the_upstream_ref(code_repo):
    # a proper descendant of HEAD whose upstream is missing: NOT ahead
    head = commit_file(code_repo, "a.txt")
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    assert prober.line.upstream is None  # no remote configured at all
    descendant = commit_file(code_repo, "child.txt")
    contexts = prober.lineage_contexts({"v_child": descendant, "v_head": head})
    assert contexts["v_child"].relation == "out_of_line"
    assert contexts["v_head"].relation == "in_line"


def test_descendant_beyond_the_upstream_is_out_of_line(code_repo, tmp_path):
    tracked(code_repo, tmp_path)
    remote_sha = advance_origin(code_repo / ".." / "origin.git", "remote-work")
    git(code_repo, "fetch", "origin")
    git(code_repo, "checkout", "-b", "local")
    local_sha = commit_file(code_repo, "local.txt")  # unpushed sibling of remote_sha
    git(code_repo, "checkout", "main")  # HEAD stays below both descendants
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    contexts = prober.lineage_contexts({"v_local": local_sha, "v_remote": remote_sha})
    # both are proper descendants of HEAD; only the one below the upstream ref is ahead
    assert contexts["v_local"].relation == "out_of_line"
    assert contexts["v_remote"].relation == "ahead"


def test_detached_head_allows_in_line_but_never_ahead(code_repo, tmp_path):
    tracked(code_repo, tmp_path)
    base_sha = git(code_repo, "rev-parse", "HEAD")
    remote_sha = advance_origin(code_repo / ".." / "origin.git", "remote-work")
    git(code_repo, "fetch", "origin")
    git(code_repo, "checkout", "--detach", base_sha)  # detached: no branch, no upstream
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    assert prober.line.branch is None and prober.line.upstream is None
    contexts = prober.lineage_contexts({"v_base": base_sha, "v_remote": remote_sha})
    assert contexts["v_base"].relation == "in_line"
    assert contexts["v_remote"].relation == "out_of_line"  # proper descendant, no ahead


def test_shallow_clone_is_unprovable(code_repo, tmp_path):
    commit_file(code_repo, "a.txt")
    tip = commit_file(code_repo, "b.txt")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", f"file://{code_repo}", str(shallow)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    prober = gitctx.RelationProber(shallow, gitctx.asking_line(shallow))
    assert prober.line.shallow
    # even the tip commit (present, HEAD-equal) is unprovable: a shallow
    # clone's answers are untrustworthy, nothing is probed
    contexts = prober.lineage_contexts({"v_tip": tip})
    assert contexts["v_tip"].relation is None
    assert prober.probe_count == 0


def test_missing_object_is_unprovable(code_repo):
    commit_file(code_repo, "a.txt")
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    contexts = prober.lineage_contexts({"v_ghost": MISSING_SHA})
    assert contexts["v_ghost"].relation is None


def test_cherry_picked_twin_is_out_of_line(code_repo):
    first = commit_file(code_repo, "a.txt")
    git(code_repo, "checkout", "-b", "original")
    original = commit_file(code_repo, "orig.txt", "the knowledge\n")
    git(code_repo, "checkout", "main")
    commit_file(code_repo, "b.txt")  # main diverges, so the replay gets a new parent
    git(code_repo, "cherry-pick", original)
    twin = git(code_repo, "rev-parse", "HEAD")
    assert twin != original  # the twin is a different sha (same patch, new parent)
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    contexts = prober.lineage_contexts({"v_original": original, "v_first": first})
    assert contexts["v_original"].relation == "out_of_line"
    assert contexts["v_first"].relation == "in_line"


def test_criss_cross_merges_keep_ancestors_in_line(code_repo):
    commit_file(code_repo, "a.txt")
    git(code_repo, "checkout", "-b", "side")
    side = commit_file(code_repo, "side.txt")
    git(code_repo, "checkout", "main")
    main_commit = commit_file(code_repo, "main.txt")
    git(code_repo, "merge", "--no-edit", "side")  # main merges side...
    git(code_repo, "checkout", "side")
    git(code_repo, "merge", "--no-edit", main_commit)  # ...and side merges main
    git(code_repo, "checkout", "main")
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    contexts = prober.lineage_contexts({"v_side": side, "v_main": main_commit})
    # both establishing commits are ancestors of the merged HEAD, whatever the
    # DAG shape; mutually incomparable — both stay maxima with no ancestry edge
    assert contexts["v_side"].relation == "in_line"
    assert contexts["v_main"].relation == "in_line"
    assert contexts["v_side"].ancestors == frozenset()
    assert contexts["v_main"].ancestors == frozenset()


def test_ancestry_maxima_among_tier1_candidates(code_repo):
    first = commit_file(code_repo, "a.txt")
    second = commit_file(code_repo, "b.txt")
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    contexts = prober.lineage_contexts({"v_first": first, "v_second": second})
    assert contexts["v_second"].ancestors == frozenset({"v_first"})
    assert contexts["v_first"].ancestors == frozenset()


def test_blocked_ancestry_probe_never_demotes_a_proven_relation(code_repo):
    first = commit_file(code_repo, "a.txt")
    second = commit_file(code_repo, "b.txt")
    commit_file(code_repo, "c.txt")  # HEAD beyond both: the (first, second) pair is unasked
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo), budget=2)
    contexts = prober.lineage_contexts({"v_first": first, "v_second": second})
    # both primary probes exhaust the budget; the ancestry pair is BLOCKED —
    # read as incomparable, the proven in_line relations stand
    assert contexts["v_first"].relation == "in_line"
    assert contexts["v_second"].relation == "in_line"
    assert contexts["v_second"].ancestors == frozenset()
    assert contexts["v_first"].ancestors == frozenset()


# --- memoization and the shared budget ----------------------------------------


def test_probes_are_memoized_per_ordered_pair(code_repo):
    tip = commit_file(code_repo, "a.txt")
    head = commit_file(code_repo, "b.txt")  # distinct from tip: the reverse pair is real
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    prober.lineage_contexts({"v1": tip})
    assert prober.probe_count == 1
    # the same question again — from the same or another lineage — is free
    prober.lineage_contexts({"v2": tip})
    assert prober.probe_count == 1
    # the REVERSE pair is a different key and spawns once — and answers NO:
    # the asking head is a DESCENDANT of the earlier tip, never its ancestor
    assert prober.is_ancestor(head, tip) is gitctx.Answer.NO
    assert prober.probe_count == 2


def test_budget_exhaustion_leaves_remaining_versions_unprovable(code_repo):
    first = commit_file(code_repo, "a.txt")
    second = commit_file(code_repo, "b.txt")
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo), budget=1)
    contexts = prober.lineage_contexts({"v_first": first, "v_second": second})
    # ascending key order probes v_first first; the budget dies after it
    assert contexts["v_first"].relation == "in_line"
    assert contexts["v_second"].relation is None


def test_budget_is_deterministic(code_repo):
    first = commit_file(code_repo, "a.txt")
    second = commit_file(code_repo, "b.txt")
    establishing = {"v_first": first, "v_second": second}
    one = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo), budget=3)
    two = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo), budget=3)
    assert one.lineage_contexts(establishing) == two.lineage_contexts(establishing)


def test_adapter_never_fetches_or_mutates_refs(code_repo, tmp_path):
    tracked(code_repo, tmp_path)
    before = git(code_repo, "for-each-ref")
    prober = gitctx.RelationProber(code_repo, gitctx.asking_line(code_repo))
    prober.lineage_contexts({"v": git(code_repo, "rev-parse", "HEAD")})
    assert git(code_repo, "for-each-ref") == before


# --- the counterfactual degraded test ------------------------------------------


def test_degraded_fires_when_a_promotion_could_change_the_display():
    # two matching versions: the older is provably in_line, the newer ULID is
    # unprovable — promoting the unprovable version to in_line/ahead makes it
    # the tier-1 maximum and changes what displays
    ordering = gitctx.context_ordering(
        lineage=ULID_L1,
        events=[Event(id=ULID_L1, kind="claim", lineage=ULID_L1)],
        activity={ULID_L1: True, ULID_V2A: True},
        eligible=[ULID_L1, ULID_V2A],
        outcomes={ULID_L1: "match", ULID_V2A: "match"},
        contexts={
            ULID_L1: VersionContext(ULID_L1, "in_line"),
            ULID_V2A: VersionContext(ULID_V2A, None),
        },
    )
    assert ordering == "degraded"


def test_exact_when_the_unprovable_version_cannot_win_under_any_hypothetical():
    # the proven-ahead version holds the NEWER ULID: promoting the unprovable
    # older version to in_line loses to ahead, promoting it to ahead ties on
    # maxima and loses the ULID break — the result cannot change: exact
    ordering = gitctx.context_ordering(
        lineage=ULID_L1,
        events=[Event(id=ULID_V1A, kind="claim", lineage=ULID_L1)],
        activity={ULID_V1A: True, ULID_V2A: True},
        eligible=[ULID_V1A, ULID_V2A],
        outcomes={ULID_V1A: "match", ULID_V2A: "match"},
        contexts={
            ULID_V1A: VersionContext(ULID_V1A, None),
            ULID_V2A: VersionContext(ULID_V2A, "ahead"),
        },
    )
    assert ordering == "exact"


def test_relation_unknown_does_not_count_for_degraded():
    # a relation_unknown version's not-in_line knowledge is proven; the brief
    # pins that it does NOT feed the degraded counterfactual
    ordering = gitctx.context_ordering(
        lineage=ULID_L1,
        events=[Event(id=ULID_L1, kind="claim", lineage=ULID_L1)],
        activity={ULID_L1: True, ULID_V2A: True},
        eligible=[ULID_L1, ULID_V2A],
        outcomes={ULID_L1: "match", ULID_V2A: "match"},
        contexts={
            ULID_L1: VersionContext(ULID_L1, "in_line"),
            ULID_V2A: VersionContext(ULID_V2A, "relation_unknown"),
        },
    )
    assert ordering == "exact"


def test_degraded_fires_when_a_refuted_version_could_be_restored():
    # the refuted R is unprovable; promoting it to ahead would make it win sel
    # over the in_line match — the restored decision changes: degraded
    ordering = gitctx.context_ordering(
        lineage=ULID_L1,
        events=[
            Event(id=ULID_L1, kind="claim", lineage=ULID_L1),
            Event(id=ULID_V2A, kind="claim", lineage=ULID_L1),
            Event(
                id="01J8Z3K0000000000000000006",
                kind="refute",
                lineage=ULID_L1,
                targets=ULID_V2A,
            ),
        ],
        activity={ULID_L1: True, ULID_V2A: False},
        eligible=[ULID_L1, ULID_V2A],
        outcomes={ULID_L1: "match", ULID_V2A: "match"},
        contexts={
            ULID_L1: VersionContext(ULID_L1, "in_line"),
            ULID_V2A: VersionContext(ULID_V2A, None),
        },
    )
    assert ordering == "degraded"


# --- integration: the index build stamps the context ---------------------------


def test_build_stamps_relations_and_exact_ordering(code_repo, base):
    ancestor = commit_file(code_repo, "a.txt")
    commit_file(code_repo, "b.txt")
    write_event(base, CLAIM_REL, note(ULID_L1, ULID_L1, ancestor))
    result = build_index(base, code_repo)
    assert result.errors == [] and result.warnings == []
    assert relations(result.db_path) == [(ULID_L1, "in_line", "exact")]
    conn = sqlite3.connect(f"file:{result.db_path}?mode=ro", uri=True)
    try:
        off = conn.execute("SELECT off_version FROM lineages").fetchone()[0]
    finally:
        conn.close()
    assert off == 0


def test_build_reports_degraded_and_stamps_none(code_repo, base):
    ancestor = commit_file(code_repo, "a.txt")
    commit_file(code_repo, "b.txt")
    # the newest version's establishing commit is missing from the repo
    write_event(base, CLAIM_REL, note(ULID_L1, ULID_L1, ancestor))
    write_event(base, V2_REL, note(ULID_V2A, ULID_L1, MISSING_SHA))
    result = build_index(base, code_repo)
    assert [d.code for d in result.warnings] == ["W-CTX-DEGRADED"]
    assert result.exit_code() == 2
    assert relations(result.db_path) == [
        (ULID_L1, "in_line", "degraded"),
        (ULID_V2A, None, "degraded"),
    ]


def test_build_exact_when_the_unprovable_context_cannot_change_the_result(
    code_repo, base, tmp_path
):
    tracked(code_repo, tmp_path)
    ahead_sha = advance_origin(code_repo / ".." / "origin.git", "remote-work")
    git(code_repo, "fetch", "origin")
    # the proven-ahead version holds the NEWER ULID: the unprovable older
    # version can never win, even promoted — exact, no warning
    write_event(base, CLAIM_REL, note(ULID_L1, ULID_L1, MISSING_SHA))
    write_event(base, V2_REL, note(ULID_V2A, ULID_L1, ahead_sha))
    result = build_index(base, code_repo)
    assert result.warnings == []
    assert relations(result.db_path) == [
        (ULID_L1, None, "exact"),
        (ULID_V2A, "ahead", "exact"),
    ]


def test_build_selection_follows_the_relation(code_repo, base):
    ancestor = commit_file(code_repo, "a.txt")
    commit_file(code_repo, "b.txt")
    # the in_line version carries the OLDER ULID and still wins the display
    write_event(base, CLAIM_REL, note(ULID_L1, ULID_L1, ancestor))
    write_event(base, V2_REL, note(ULID_V2A, ULID_L1, MISSING_SHA))
    result = build_index(base, code_repo)
    assert result.statuses[0].displayed == ULID_L1
    assert result.statuses[0].resolution == "current"


def test_build_against_a_shallow_clone_is_unprovable_but_exact_for_one_version(
    code_repo, base, tmp_path
):
    tip = commit_file(code_repo, "a.txt")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", f"file://{code_repo}", str(shallow)],
        capture_output=True,
        check=True,
        env=git_env(),
    )
    write_event(base, CLAIM_REL, note(ULID_L1, ULID_L1, tip))
    result = build_index(base, shallow)
    assert result.warnings == []  # one version: no hypothetical can change it
    assert relations(result.db_path) == [(ULID_L1, None, "exact")]


def test_unrelated_lineages_share_the_prober_and_stay_exact(code_repo, base):
    ancestor = commit_file(code_repo, "a.txt")
    commit_file(code_repo, "b.txt")
    write_event(base, CLAIM_REL, note(ULID_L1, ULID_L1, ancestor))
    write_event(base, L2_REL, note(ULID_L2, ULID_L2, ancestor))
    result = build_index(base, code_repo)
    assert result.warnings == []
    assert relations(result.db_path) == [
        (ULID_L1, "in_line", "exact"),
        (ULID_L2, "in_line", "exact"),
    ]
