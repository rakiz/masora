import pytest
from helpers import (
    OMIT,
    SHA,
    apply_overrides,
    make_claim,
    make_doubt,
    make_verify,
)

from masora.diagnostics import (
    E_ANCHOR,
    E_FILENAME,
    E_PROOFQUERY,
    E_SCHEMA,
    E_SUMMARY,
    E_TIMESTAMP,
    E_ULID,
    E_VERSION,
    CheckFailure,
)
from masora.schema import validate_event

PROOF_QUERY = {
    "tool": "cppgraph.calls",
    "args": {"symbol": "scip x"},
    "expect": {"op": "count", "value": 3},
    "provider_version": "1.0",
}


def validate(data: dict, kind: str):
    return validate_event(data, kind, "test.md")


def expect_error(data: dict, kind: str, code: str):
    with pytest.raises(CheckFailure) as exc:
        validate(data, kind)
    assert exc.value.diag.code == code, exc.value.diag.message


def test_valid_claim():
    validate(make_claim("01J8Z3K0000000000000000000"), "claim")


def test_valid_unanchored_claim():
    data = make_claim(
        "01J8Z3K0000000000000000000",
        anchors=[],
        unanchored=True,
        unanchored_reason="No stable anchor exists",
        recorded_at={"commit": SHA, "graph_commit": None},
    )
    validate(data, "claim")


def test_valid_structural_claim():
    data = make_claim(
        "01J8Z3K0000000000000000000", **{"class": "structural", "proof_query": PROOF_QUERY}
    )
    validate(data, "claim")


def test_valid_verify_of_unanchored_claim():
    data = make_verify(
        "01J8Z3K0000000000000000001",
        "01J8Z3K0000000000000000000",
        "01J8Z3K0000000000000000000",
        snapshots={},
        verified_at={"commit": SHA, "graph_commit": None},
    )
    validate(data, "verify")


@pytest.mark.parametrize("kind", ["doubt", "undoubt", "refute", "unrefute"])
def test_valid_event_kinds(kind):
    validate(
        make_doubt(
            "01J8Z3K0000000000000000001",
            "01J8Z3K0000000000000000000",
            "01J8Z3K0000000000000000002",
            kind=kind,
        ),
        kind,
    )


def test_missing_format_version():
    expect_error(
        apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"format_version": OMIT}),
        "claim",
        E_VERSION,
    )


def test_unknown_major_version():
    expect_error(
        apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"format_version": 2}),
        "claim",
        E_VERSION,
    )


def test_string_version():
    expect_error(
        apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"format_version": "1"}),
        "claim",
        E_VERSION,
    )


def test_unknown_field():
    expect_error(
        apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"extras": 1}), "claim", E_SCHEMA
    )


@pytest.mark.parametrize("field", ["targets", "actor", "verified_at", "evidence", "snapshots"])
def test_forbidden_field_on_claim(field):
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {field: None})
    expect_error(data, "claim", E_SCHEMA)


@pytest.mark.parametrize(
    "field",
    ["source", "reason", "summary", "anchors", "class", "unanchored", "cost_tokens", "recorded_at"],
)
def test_forbidden_field_on_verify(field):
    data = apply_overrides(
        make_verify(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000"
        ),
        {field: None},
    )
    expect_error(data, "verify", E_SCHEMA)


@pytest.mark.parametrize(
    "field",
    [
        "class",
        "source",
        "summary",
        "statement",
        "recorded_at",
        "unanchored",
        "id",
        "lineage",
        "kind",
    ],
)
def test_missing_required_field_on_claim(field):
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {field: OMIT})
    expect_error(data, "claim", E_SCHEMA)


def test_null_required_field():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"summary": None})
    expect_error(data, "claim", E_SCHEMA)


def test_missing_required_field_on_verify():
    data = apply_overrides(
        make_verify(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000"
        ),
        {"actor": OMIT},
    )
    expect_error(data, "verify", E_SCHEMA)


def test_frontmatter_kind_mismatch():
    expect_error(
        apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"kind": "verify"}),
        "claim",
        E_FILENAME,
    )


def test_bad_kind_value():
    expect_error(
        apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"kind": "Claim"}),
        "claim",
        E_SCHEMA,
    )


def test_bad_ulid_in_id():
    expect_error(
        apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"id": "not-a-ulid"}),
        "claim",
        E_ULID,
    )


def test_bad_ulid_in_targets():
    data = apply_overrides(
        make_doubt(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000002"
        ),
        {"targets": "01J8Z3K000000000000000000U"},
    )
    expect_error(data, "doubt", E_ULID)


def test_bad_source_enum():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"source": "ci"})
    expect_error(data, "claim", E_SCHEMA)


def test_bad_actor_enum():
    data = apply_overrides(
        make_verify(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000"
        ),
        {"actor": "ci"},
    )
    expect_error(data, "verify", E_SCHEMA)


def test_summary_too_long():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"summary": "x" * 121})
    expect_error(data, "claim", E_SUMMARY)


def test_summary_multiline():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"summary": "line one\nline two"}
    )
    expect_error(data, "claim", E_SUMMARY)


def test_summary_control_characters():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"summary": "tab\there"})
    expect_error(data, "claim", E_SUMMARY)


def test_anchored_claim_requires_anchors():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"anchors": OMIT})
    expect_error(data, "claim", E_ANCHOR)


def test_unanchored_claim_with_null_anchors_equivalent_to_omitted():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"unanchored": True, "unanchored_reason": "why", "anchors": None},
    )
    validate(data, "claim")


def test_unanchored_claim_with_non_empty_anchors_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"unanchored": True, "unanchored_reason": "why"}
    )
    expect_error(data, "claim", E_ANCHOR)


def test_unanchored_claim_requires_reason():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"unanchored": True, "anchors": []}
    )
    expect_error(data, "claim", E_SCHEMA)


def test_anchored_claim_with_reason_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"unanchored_reason": "why"})
    expect_error(data, "claim", E_SCHEMA)


def test_structural_unanchored_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "class": "structural",
            "proof_query": PROOF_QUERY,
            "unanchored": True,
            "unanchored_reason": "why",
            "anchors": [],
        },
    )
    expect_error(data, "claim", E_ANCHOR)


def test_structural_requires_proof_query():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"class": "structural"})
    expect_error(data, "claim", E_PROOFQUERY)


def test_semantic_with_proof_query_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"proof_query": PROOF_QUERY})
    expect_error(data, "claim", E_PROOFQUERY)


def test_v2_claim_requires_reason():
    data = make_claim("01J8Z3K0000000000000000005", lineage="01J8Z3K0000000000000000000")
    expect_error(data, "claim", E_SCHEMA)


def test_v2_claim_with_reason():
    validate(
        make_claim(
            "01J8Z3K0000000000000000005", lineage="01J8Z3K0000000000000000000", reason="why v2"
        ),
        "claim",
    )


def test_contradicts_requires_reason():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"contradicts": "01J8Z3K0000000000000000005"}
    )
    expect_error(data, "claim", E_SCHEMA)


def test_reason_may_exist_without_contradicts():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"reason": "context", "contradicts": None}
    )
    validate(data, "claim")


def test_model_requires_llm_writer():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"source": "human", "model": "glm-5p3-flash"}
    )
    expect_error(data, "claim", E_SCHEMA)


def test_cost_tokens_negative():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"cost_tokens": -1})
    expect_error(data, "claim", E_SCHEMA)


def test_cost_tokens_bool():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"cost_tokens": True})
    expect_error(data, "claim", E_SCHEMA)


def test_cost_tokens_zero_ok():
    validate(apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"cost_tokens": 0}), "claim")


def test_anchor_missing_snapshot():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"anchors": [{"provider": "code", "identity": "x", "fingerprint": "ab"}]},
    )
    expect_error(data, "claim", E_ANCHOR)


def test_anchor_unknown_provider():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "anchors": [
                {
                    "provider": "url",
                    "identity": "x",
                    "fingerprint": "ab",
                    "snapshot": {"edges": "ab", "neighbours": {}},
                }
            ]
        },
    )
    expect_error(data, "claim", E_ANCHOR)


def test_anchor_duplicate_identity():
    a = {
        "provider": "code",
        "identity": "same",
        "fingerprint": "ab",
        "snapshot": {"edges": "ab", "neighbours": {}},
    }
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"anchors": [a, dict(a)]})
    expect_error(data, "claim", E_ANCHOR)


def test_anchor_bad_fingerprint():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "anchors": [
                {
                    "provider": "code",
                    "identity": "x",
                    "fingerprint": "AB",
                    "snapshot": {"edges": "ab", "neighbours": {}},
                }
            ]
        },
    )
    expect_error(data, "claim", E_ANCHOR)


def test_snapshot_extra_field():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "anchors": [
                {
                    "provider": "code",
                    "identity": "x",
                    "fingerprint": "ab",
                    "snapshot": {"edges": "ab", "neighbours": {}, "extra": "ab"},
                }
            ]
        },
    )
    expect_error(data, "claim", E_ANCHOR)


def test_verify_empty_evidence():
    data = apply_overrides(
        make_verify(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000"
        ),
        {"evidence": []},
    )
    expect_error(data, "verify", E_SCHEMA)


def test_verify_missing_graph_commit_with_snapshots():
    data = apply_overrides(
        make_verify(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000"
        ),
        {"verified_at": {"commit": SHA, "graph_commit": None}},
    )
    expect_error(data, "verify", E_TIMESTAMP)


def test_timestamp_bad_sha():
    data = apply_overrides(
        make_doubt(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000002"
        ),
        {"recorded_at": {"commit": "nothex", "graph_commit": None}},
    )
    expect_error(data, "doubt", E_TIMESTAMP)


def test_timestamp_uppercase_sha():
    data = apply_overrides(
        make_doubt(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000002"
        ),
        {"recorded_at": {"commit": SHA.upper(), "graph_commit": None}},
    )
    expect_error(data, "doubt", E_TIMESTAMP)


def test_timestamp_extra_field():
    data = apply_overrides(
        make_doubt(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000002"
        ),
        {"recorded_at": {"commit": SHA, "graph_commit": None, "at": "x"}},
    )
    expect_error(data, "doubt", E_TIMESTAMP)


def test_both_timestamps_rejected():
    data = apply_overrides(
        make_doubt(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000002"
        ),
        {"verified_at": {"commit": SHA, "graph_commit": None}},
    )
    expect_error(data, "doubt", E_SCHEMA)


def test_graph_commit_optional_without_anchors():
    data = apply_overrides(
        make_doubt(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000002"
        ),
        {"recorded_at": {"commit": SHA}},
    )
    validate(data, "doubt")


@pytest.mark.parametrize(
    "tool",
    ["cppgraph.calls", "cppgraph.who_calls", "cppgraph.x.y"],
)
def test_proof_query_tools(tool):
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"class": "structural", "proof_query": {**PROOF_QUERY, "tool": tool}},
    )
    validate(data, "claim")


@pytest.mark.parametrize("tool", ["calls", "graph.calls", "masora.calls", "cppgraph."])
def test_proof_query_unknown_tool(tool):
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"class": "structural", "proof_query": {**PROOF_QUERY, "tool": tool}},
    )
    expect_error(data, "claim", E_PROOFQUERY)


def test_proof_query_empty_args():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"class": "structural", "proof_query": {**PROOF_QUERY, "args": {}}},
    )
    expect_error(data, "claim", E_PROOFQUERY)


def test_proof_query_free_text_expect():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"class": "structural", "proof_query": {**PROOF_QUERY, "expect": "3 edges"}},
    )
    expect_error(data, "claim", E_PROOFQUERY)


def test_proof_query_bad_op():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "class": "structural",
            "proof_query": {**PROOF_QUERY, "expect": {"op": "equals", "value": 3}},
        },
    )
    expect_error(data, "claim", E_PROOFQUERY)


def test_proof_query_count_with_string_value():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "class": "structural",
            "proof_query": {**PROOF_QUERY, "expect": {"op": "count", "value": ["a"]}},
        },
    )
    expect_error(data, "claim", E_PROOFQUERY)


def test_proof_query_count_negative_value():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "class": "structural",
            "proof_query": {**PROOF_QUERY, "expect": {"op": "count", "value": -1}},
        },
    )
    expect_error(data, "claim", E_PROOFQUERY)


def test_proof_query_set_equality_with_strings():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "class": "structural",
            "proof_query": {
                **PROOF_QUERY,
                "expect": {"op": "set-equality", "value": ["scip a", "scip b"]},
            },
        },
    )
    validate(data, "claim")


def test_proof_query_missing_provider_version():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "class": "structural",
            "proof_query": {
                "tool": "cppgraph.calls",
                "args": {"s": "x"},
                "expect": {"op": "count", "value": 0},
            },
        },
    )
    expect_error(data, "claim", E_PROOFQUERY)
