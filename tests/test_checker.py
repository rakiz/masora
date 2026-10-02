from pathlib import Path

import pytest
from helpers import (
    FP,
    IDENT_MAIN,
    SHA,
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

from masora.checker import check_base

FIXTURES = Path(__file__).parent / "fixtures"


def codes(result):
    return {d.code for d in result.diags}


def test_valid_fixture_is_clean():
    result = check_base(FIXTURES / "valid")
    assert result.exit_code() == 0
    assert result.errors == [] and result.warnings == []
    assert result.file_count == 7


def test_valid_fixture_envelope():
    result = check_base(FIXTURES / "valid")
    envelope = next(e for e in result.envelopes if e["lineage"] == ULID_L1)
    assert envelope["displayed"] == ULID_L1
    assert envelope["status"] == "unknown"
    # Standalone check wires no provider: no match can display, so the
    # counterfactual restored (§6.2 rule 4) cannot fire — the unknown shadow
    # covers the lineage instead.
    assert envelope["restored"] is False
    assert envelope["versions"] == [
        {"id": ULID_V2A, "refuted": True},
        {"id": ULID_L1, "refuted": False},
    ]
    assert envelope["verification"]["status"] == "verified"
    assert envelope["verification"]["source"] == "llm"
    assert envelope["verification"]["id"] == ULID_V1A
    assert envelope["sources"] == ["llm"]
    assert envelope["doubted"] is False
    assert envelope["recorded_at"]["commit"] == SHA
    unanchored = next(e for e in result.envelopes if e["lineage"] == ULID_L2)
    assert unanchored["displayed"] == ULID_L2
    assert unanchored["verification"]["status"] == "unverified"


def test_structural_fixture_replay_unknown_warning():
    result = check_base(FIXTURES / "structural")
    assert result.exit_code() == 2
    assert codes(result) == {"W-REPLAY"}
    envelope = result.envelopes[0]
    assert envelope["proof_replay"] == "unknown"
    assert envelope["verification"]["source"] == "llm"


@pytest.mark.parametrize(
    "tree,expected_code",
    [
        ("dangling", "W-DANGLING"),
        ("founderless", "W-FOUNDER"),
        ("skew", "W-SKEW"),
        ("filename-kind-mismatch", "E-FILENAME"),
        ("id-filename-mismatch", "E-FILENAME"),
        ("duplicate-id", "E-DUP-ID"),
        ("cycle", "E-CYCLE"),
        ("target-kind", "E-TARGET-KIND"),
        ("lineage-mismatch", "E-LINEAGE"),
        ("snapshot-keys", "E-ANCHOR"),
        ("tombstoned", "E-TOMBSTONED"),
        ("tombstone-shape", "E-TOMBSTONE-SHAPE"),
        ("stray-md", "E-FILENAME"),
    ],
)
def test_fixture_tree_diagnostic(tree, expected_code):
    result = check_base(FIXTURES / tree)
    assert expected_code in codes(result), [d.render() for d in result.diags]


@pytest.mark.parametrize(
    "tree,expected_exit",
    [
        ("dangling", 2),
        ("founderless", 2),
        ("skew", 2),
        ("filename-kind-mismatch", 1),
        ("id-filename-mismatch", 1),
        ("duplicate-id", 1),
        ("cycle", 1),
        ("target-kind", 1),
        ("lineage-mismatch", 1),
        ("snapshot-keys", 1),
        ("tombstoned", 1),
        ("tombstone-shape", 1),
        ("stray-md", 1),
    ],
)
def test_fixture_tree_exit_codes(tree, expected_exit):
    assert check_base(FIXTURES / tree).exit_code() == expected_exit


def test_founderless_version_excluded_from_resolution():
    result = check_base(FIXTURES / "founderless")
    envelope = result.envelopes[0]
    assert envelope["displayed"] is None
    assert envelope["versions"] == [{"id": ULID_V2A, "refuted": False}]


def test_dangling_refute_does_not_refute():
    result = check_base(FIXTURES / "dangling")
    envelope = result.envelopes[0]
    assert envelope["verification"]["status"] == "unverified"


def test_tombstoned_lineage_detected_via_lineage_field():
    base = FIXTURES / "tombstoned"
    tombstone = base / "deleted.toml"
    tombstone.write_text(f'[[deleted]]\nlineage = "{ULID_L1}"\nulids = ["{ULID_V1A}"]\n')
    result = check_base(base)
    assert "E-TOMBSTONED" in codes(result)


def test_tombstone_absent_ulids_are_fine(single_claim_base):
    (single_claim_base / "deleted.toml").write_text(
        f'[[deleted]]\nlineage = "{ULID_L2}"\nulids = ["{ULID_L2}"]\n'
    )
    result = check_base(single_claim_base)
    assert result.exit_code() == 0


def test_tombstone_block_missing_ulids_field(base):
    write_event(base, "x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    (base / "deleted.toml").write_text(f'[[deleted]]\nlineage = "{ULID_L1}"\n')
    result = check_base(base)
    assert "E-TOMBSTONE-SHAPE" in codes(result)


def test_tombstone_ulid_syntax_validated(base):
    (base / "deleted.toml").write_text('[[deleted]]\nlineage = "not-a-ulid"\nulids = []\n')
    result = check_base(base)
    assert "E-TOMBSTONE-SHAPE" in codes(result)


def test_self_target_is_a_cycle(single_claim_base):
    write_event(
        single_claim_base,
        "x/01J8Z3K0000000000000000004.refute.md",
        make_doubt(ULID_R1A, ULID_L1, ULID_R1A, kind="refute"),
    )
    result = check_base(single_claim_base)
    assert "E-CYCLE" in codes(result)


def test_verify_of_v2_claim_snapshots_match_version_anchors(base):
    other_identity = "scip-clang cxx . . example#v2()."
    write_event(base, "x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    write_event(
        base,
        "x/01J8Z3K0000000000000000005.claim.md",
        make_claim(
            ULID_V2A,
            lineage=ULID_L1,
            reason="v2",
            anchors=[
                {
                    "provider": "code",
                    "identity": other_identity,
                    "fingerprint": FP,
                    "snapshot": {"edges": FP, "neighbours": {}},
                }
            ],
        ),
    )
    write_event(
        base,
        "x/01J8Z3K0000000000000000008.verify.md",
        make_verify(
            ULID_V3A, ULID_L1, ULID_V2A, snapshots={other_identity: {"edges": FP, "neighbours": {}}}
        ),
    )
    result = check_base(base)
    assert result.exit_code() == 0, [d.render() for d in result.diags]
    assert result.envelopes[0]["displayed"] == ULID_V2A


def test_verify_missing_one_anchor_snapshot(base):
    write_event(
        base,
        "x/01J8Z3K0000000000000000000.claim.md",
        make_claim(
            ULID_L1,
            anchors=[
                {
                    "provider": "code",
                    "identity": IDENT_MAIN,
                    "fingerprint": FP,
                    "snapshot": {"edges": FP, "neighbours": {}},
                },
                {
                    "provider": "code",
                    "identity": "scip-clang cxx . . example#second().",
                    "fingerprint": FP,
                    "snapshot": {"edges": FP, "neighbours": {}},
                },
            ],
        ),
    )
    write_event(
        base,
        "x/01J8Z3K0000000000000000001.verify.md",
        make_verify(
            ULID_V1A, ULID_L1, ULID_L1, snapshots={IDENT_MAIN: {"edges": FP, "neighbours": {}}}
        ),
    )
    result = check_base(base)
    assert "E-ANCHOR" in codes(result)


def test_contradicts_to_other_lineage_rejected(base):
    write_event(base, "a/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    write_event(
        base,
        "b/01J8Z3K0000000000000000006.claim.md",
        make_claim(ULID_L2, contradicts=ULID_L1, reason="because"),
    )
    result = check_base(base)
    assert "E-LINEAGE" in codes(result)


def test_contradicts_to_same_lineage_ok(base):
    write_event(base, "a/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    write_event(
        base,
        "a/01J8Z3K0000000000000000005.claim.md",
        make_claim(ULID_V2A, lineage=ULID_L1, reason="v2", contradicts=ULID_L1),
    )
    result = check_base(base)
    assert result.exit_code() == 0, [d.render() for d in result.diags]


def test_contradicts_dangling_warns(base):
    write_event(
        base,
        "a/01J8Z3K0000000000000000000.claim.md",
        make_claim(ULID_L1, contradicts="01J8Z3K0000000000000000009", reason="because"),
    )
    result = check_base(base)
    assert "W-DANGLING" in codes(result)
    assert result.exit_code() == 2


def test_two_verifies_newest_shown(base):
    write_event(base, "x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    write_event(
        base,
        "x/01J8Z3K0000000000000000001.verify.md",
        make_verify(ULID_V1A, ULID_L1, ULID_L1, source="human"),
    )
    write_event(
        base,
        "x/01J8Z3K0000000000000000005.verify.md",
        make_verify(ULID_V2A, ULID_L1, ULID_L1, source="llm"),
    )
    result = check_base(base)
    envelope = result.envelopes[0]
    assert envelope["verification"]["id"] == ULID_V2A
    assert envelope["sources"] == ["human", "llm"]


def test_all_refuted_status_none(base):
    write_event(base, "x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    write_event(
        base,
        "x/01J8Z3K0000000000000000001.refute.md",
        make_doubt(ULID_V1A, ULID_L1, ULID_L1, kind="refute"),
    )
    result = check_base(base)
    envelope = result.envelopes[0]
    assert envelope["status"] == "none"
    assert envelope["displayed"] is None
    assert result.exit_code() == 0


def test_doubted_flag(base):
    write_event(base, "x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    write_event(
        base, "x/01J8Z3K0000000000000000001.verify.md", make_verify(ULID_V1A, ULID_L1, ULID_L1)
    )
    write_event(
        base,
        "x/01J8Z3K0000000000000000002.doubt.md",
        make_doubt(ULID_D1A, ULID_L1, ULID_V1A, kind="doubt"),
    )
    result = check_base(base)
    envelope = result.envelopes[0]
    assert envelope["doubted"] is True
    assert envelope["verification"]["status"] == "verified"
    assert result.exit_code() == 0


def test_location_does_not_matter(single_claim_base):
    moved = single_claim_base / "somewhere" / "else"
    moved.mkdir(parents=True)
    for path in single_claim_base.rglob("*.md"):
        path.rename(moved / path.name)
    result = check_base(single_claim_base)
    assert result.exit_code() == 0


def test_base_toml_and_git_ignored(base):
    write_event(base, "x/01J8Z3K0000000000000000000.claim.md", make_claim(ULID_L1))
    (base / "base.toml").write_text('name = "test"\n')
    git_dir = base / ".git"
    git_dir.mkdir()
    (git_dir / "01J8Z3K0000000000000000000.claim.md").write_text("garbage")
    result = check_base(base)
    assert result.exit_code() == 0
