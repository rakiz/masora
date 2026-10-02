import pytest
from helpers import (
    OMIT,
    SHA,
    ULID_L1,
    apply_overrides,
    make_claim,
    make_doubt,
    make_verify,
)

from masora.diagnostics import (
    E_ANCHOR,
    E_FILENAME,
    E_KEYWORDS,
    E_PROOFQUERY,
    E_PROVENANCE,
    E_QUESTIONS,
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
        apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"format_version": 3}),
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


@pytest.mark.parametrize(
    "field", ["targets", "actor", "model", "verified_at", "evidence", "snapshots"]
)
def test_forbidden_field_on_claim(field):
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {field: None})
    expect_error(data, "claim", E_SCHEMA)


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "model",
        "reason",
        "summary",
        "anchors",
        "class",
        "unanchored",
        "cost_tokens",
        "recorded_at",
    ],
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
        {"source": OMIT},
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


def test_bad_verify_source_enum():
    data = apply_overrides(
        make_verify(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000"
        ),
        {"source": "ci"},
    )
    expect_error(data, "verify", E_SCHEMA)


def test_bad_effort_enum():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"source": "llm", "effort": "extreme"}
    )
    expect_error(data, "claim", E_PROVENANCE)


def test_effort_on_human_claim_refused():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"source": "human", "effort": "high"}
    )
    expect_error(data, "claim", E_PROVENANCE)


def test_effort_on_llm_claim_ok():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"source": "llm", "effort": "high"}
    )
    validate(data, "claim")


def test_effort_on_verify_llm_ok():
    data = apply_overrides(
        make_verify(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000"
        ),
        {"source": "llm", "effort": "medium"},
    )
    validate(data, "verify")


def test_effort_on_verify_human_refused():
    data = apply_overrides(
        make_verify(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000"
        ),
        {"source": "human", "effort": "low"},
    )
    expect_error(data, "verify", E_PROVENANCE)


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_effort_enum_values_ok(effort):
    data = apply_overrides(
        make_doubt(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000002"
        ),
        {"source": "llm", "effort": effort},
    )
    validate(data, "doubt")


def test_effort_on_targeted_human_refused():
    data = apply_overrides(
        make_doubt(
            "01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000002"
        ),
        {"source": "human", "effort": "low"},
    )
    expect_error(data, "doubt", E_PROVENANCE)


def test_bad_name_type():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"source": "llm", "name": 42})
    expect_error(data, "claim", E_PROVENANCE)


def test_name_on_llm_claim_ok():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"source": "llm", "name": "glm-5p3-flash"}
    )
    validate(data, "claim")


def test_name_on_human_claim_ok():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"source": "human", "name": "Sebastien"}
    )
    validate(data, "claim")


def test_name_on_graph_source_ok():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"source": "graph", "name": OMIT}
    )
    validate(data, "claim")


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


def test_cost_tokens_read_against_name():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"source": "llm", "name": "glm-5p3-flash", "cost_tokens": 48000},
    )
    validate(data, "claim")


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


def test_questions_absent_is_valid():
    validate(make_claim("01J8Z3K0000000000000000000"), "claim")


def test_questions_one_and_five_items_valid():
    one = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"questions": ["Where does resume-token invalidation happen?"]},
    )
    assert validate(one, "claim").questions == ("Where does resume-token invalidation happen?",)
    five = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"questions": [f"Question number {i} about the behaviour?" for i in range(1, 6)]},
    )
    assert len(validate(five, "claim").questions) == 5


def test_questions_empty_list_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"questions": []})
    expect_error(data, "claim", E_QUESTIONS)


def test_questions_six_items_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"questions": [f"Question {i}?" for i in range(6)]},
    )
    expect_error(data, "claim", E_QUESTIONS)


def test_questions_empty_string_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"questions": [""]})
    expect_error(data, "claim", E_QUESTIONS)


def test_questions_multiline_or_control_char_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"questions": ["line one\nline two"]}
    )
    expect_error(data, "claim", E_QUESTIONS)


def test_questions_non_string_item_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"questions": [42]})
    expect_error(data, "claim", E_QUESTIONS)


def test_questions_not_a_list_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"questions": "why?"})
    expect_error(data, "claim", E_QUESTIONS)


def test_questions_exact_duplicates_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"questions": ["Why does it split?", "Why does it split?"]},
    )
    expect_error(data, "claim", E_QUESTIONS)


def test_questions_forbidden_on_targeted_kinds():
    for maker, kind in (
        (make_verify, "verify"),
        (make_doubt, "doubt"),
    ):
        data = apply_overrides(
            maker("01J8Z3K0000000000000000001", ULID_L1, ULID_L1), {"questions": ["Why?"]}
        )
        expect_error(data, kind, E_SCHEMA)
    refute = apply_overrides(
        make_doubt("01J8Z3K0000000000000000002", ULID_L1, ULID_L1, kind="refute"),
        {"questions": ["Why?"]},
    )
    expect_error(refute, "refute", E_SCHEMA)


def test_keywords_absent_is_valid():
    validate(make_claim("01J8Z3K0000000000000000000"), "claim")


def test_keywords_one_and_ten_items_valid():
    one = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"keywords": ["CSFLE"]})
    assert validate(one, "claim").keywords == ("CSFLE",)
    ten = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"keywords": [f"term {i}" for i in range(1, 11)]},
    )
    assert len(validate(ten, "claim").keywords) == 10


def test_keywords_empty_list_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"keywords": []})
    expect_error(data, "claim", E_KEYWORDS)


def test_keywords_eleven_items_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"keywords": [f"term {i}" for i in range(1, 12)]},
    )
    expect_error(data, "claim", E_KEYWORDS)


def test_keywords_empty_string_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"keywords": [""]})
    expect_error(data, "claim", E_KEYWORDS)


def test_keywords_non_string_item_rejected():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"keywords": [7]})
    expect_error(data, "claim", E_KEYWORDS)


def test_keywords_exact_duplicates_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"), {"keywords": ["CSFLE", "CSFLE"]}
    )
    expect_error(data, "claim", E_KEYWORDS)


def test_keywords_forbidden_on_targeted_kinds():
    data = apply_overrides(
        make_verify("01J8Z3K0000000000000000001", ULID_L1, ULID_L1), {"keywords": ["k"]}
    )
    expect_error(data, "verify", E_SCHEMA)
    doubt = apply_overrides(
        make_doubt("01J8Z3K0000000000000000002", ULID_L1, "01J8Z3K0000000000000000001"),
        {"keywords": ["k"]},
    )
    expect_error(doubt, "doubt", E_SCHEMA)


# --- the optional `lines` fork-point stamp (FORMAT.md §4) -------------------


LINES = {"8.0": SHA, "master": SHA}


def test_lines_stamp_absent_is_valid_everywhere():
    validate(make_claim("01J8Z3K0000000000000000000"), "claim")
    validate(make_verify("01J8Z3K0000000000000000001", ULID_L1, ULID_L1), "verify")


def test_lines_stamp_accepted_on_both_timestamp_fields():
    claim = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"recorded_at": {"commit": SHA, "graph_commit": SHA, "lines": LINES}},
    )
    validate(claim, "claim")
    verify = apply_overrides(
        make_verify("01J8Z3K0000000000000000001", ULID_L1, ULID_L1),
        {"verified_at": {"commit": SHA, "graph_commit": SHA, "lines": LINES}},
    )
    validate(verify, "verify")


@pytest.mark.parametrize("kind", ["doubt", "undoubt", "refute", "unrefute"])
def test_lines_stamp_accepted_on_targeted_kinds(kind):
    data = apply_overrides(
        make_doubt("01J8Z3K0000000000000000002", ULID_L1, "01J8Z3K0000000000000000001", kind=kind),
        {"recorded_at": {"commit": SHA, "graph_commit": None, "lines": LINES}},
    )
    validate(data, kind)


def test_lines_stamp_null_and_empty_accepted():
    null = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"recorded_at": {"commit": SHA, "graph_commit": SHA, "lines": None}},
    )
    validate(null, "claim")
    empty = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"recorded_at": {"commit": SHA, "graph_commit": SHA, "lines": {}}},
    )
    validate(empty, "claim")


@pytest.mark.parametrize(
    "sha",
    [
        "0123456789abcdef0123456789abcdef0123456",  # 39 hex
        "0123456789ABCDEF0123456789ABCDEF01234567",  # uppercase
        "nothex",  # not hex
        "0123456789abcdef0123456789abcdef012345678",  # 41 hex
        123,  # not a string
        True,  # not a string
    ],
)
def test_lines_stamp_bad_sha_rejected(sha):
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"recorded_at": {"commit": SHA, "graph_commit": SHA, "lines": {"master": sha}}},
    )
    expect_error(data, "claim", E_TIMESTAMP)


@pytest.mark.parametrize("ref", ["", 42, True])
def test_lines_stamp_bad_key_rejected(ref):
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"recorded_at": {"commit": SHA, "graph_commit": SHA, "lines": {ref: SHA}}},
    )
    expect_error(data, "claim", E_TIMESTAMP)


@pytest.mark.parametrize("lines", [["master"], "master", 42])
def test_lines_stamp_not_a_mapping_rejected(lines):
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {"recorded_at": {"commit": SHA, "graph_commit": SHA, "lines": lines}},
    )
    expect_error(data, "claim", E_TIMESTAMP)


def test_lines_stamp_unsorted_keys_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "recorded_at": {
                "commit": SHA,
                "graph_commit": SHA,
                "lines": {"master": SHA, "8.0": SHA},
            }
        },
    )
    expect_error(data, "claim", E_TIMESTAMP)


def test_lines_stamp_unknown_sibling_field_rejected():
    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "recorded_at": {
                "commit": SHA,
                "graph_commit": SHA,
                "lines": LINES,
                "fork": SHA,
            }
        },
    )
    expect_error(data, "claim", E_TIMESTAMP)


def test_lines_top_level_field_is_unknown():
    data = apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"lines": LINES})
    expect_error(data, "claim", E_SCHEMA)


def test_lines_stamp_canonical_reserialization_is_stable():
    """The rewrite guard: a stamped event re-emitted from its parsed form is
    byte-identical — the append-only diff (FORMAT.md §7.9) can never see a
    tool-written stamp churn."""
    from masora.frontmatter import load_frontmatter
    from masora.write import render_event

    data = apply_overrides(
        make_claim("01J8Z3K0000000000000000000"),
        {
            "recorded_at": {
                "commit": SHA,
                "graph_commit": SHA,
                "lines": {"8.0": SHA, "master": SHA},
            }
        },
    )
    text = render_event(data)
    reparsed = load_frontmatter(text, "test.md")
    assert render_event(reparsed) == text
