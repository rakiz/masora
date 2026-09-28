import pytest

from helpers import FP, IDENT_MAIN, IDENT_OTHER, apply_overrides, emit, make_claim, make_verify
from masora.diagnostics import (
    CheckFailure,
    E_CANON_ALIAS,
    E_CANON_DUPKEY,
    E_CANON_FLOW,
    E_CANON_KEY,
    E_CANON_QUOTE,
    E_CANON_TAG,
    E_FRONTMATTER,
    E_YAML,
)
from masora.frontmatter import load_frontmatter

import yaml


def parse(text: str) -> dict:
    return load_frontmatter(text, "test.md")


def test_block_style_claim_parses():
    data = make_claim("01J8Z3K0000000000000000000")
    assert parse(f"---\n{emit(data)}\n---\nbody") == data


def test_empty_flow_collections_are_accepted():
    text = "---\n" + emit(apply_overrides(make_claim("01J8Z3K0000000000000000000"), {"anchors": []})) + "\n---\n"
    assert parse(text)["anchors"] == []


def test_unterminated_frontmatter_rejected():
    with pytest.raises(CheckFailure) as exc:
        parse("---\nid: x\n")
    assert exc.value.diag.code == E_FRONTMATTER


def test_missing_opening_delimiter_rejected():
    with pytest.raises(CheckFailure) as exc:
        parse("id: x\n---\n")
    assert exc.value.diag.code == E_FRONTMATTER


def test_non_mapping_frontmatter_rejected():
    with pytest.raises(CheckFailure) as exc:
        parse("---\n- a\n- b\n---\n")
    assert exc.value.diag.code == E_FRONTMATTER


def test_invalid_yaml_rejected():
    with pytest.raises(CheckFailure) as exc:
        parse("---\n: :\n  - :\n---\n")
    assert exc.value.diag.code == E_YAML


def test_flow_mapping_rejected():
    text = '---\nrecorded_at: { commit: "a", graph_commit: "b" }\n---\n'
    with pytest.raises(CheckFailure) as exc:
        parse(text)
    assert exc.value.diag.code == E_CANON_FLOW


def test_flow_sequence_rejected():
    text = '---\nevidence: ["a", "b"]\n---\n'
    with pytest.raises(CheckFailure) as exc:
        parse(text)
    assert exc.value.diag.code == E_CANON_FLOW


def test_duplicate_key_rejected():
    text = '---\nkind: claim\nkind: verify\n---\n'
    with pytest.raises(CheckFailure) as exc:
        parse(text)
    assert exc.value.diag.code == E_CANON_DUPKEY


def test_alias_and_anchor_rejected():
    base = "---\n"
    with pytest.raises(CheckFailure) as exc:
        parse(base + 'summary: &a "x"\nstatement: *a\n---\n')
    assert exc.value.diag.code == E_CANON_ALIAS
    with pytest.raises(CheckFailure) as exc:
        parse(base + 'summary: &a "x"\n---\n')
    assert exc.value.diag.code == E_CANON_ALIAS


def test_merge_key_rejected():
    text = '---\nrecorded_at: &base\n  commit: "a"\n  graph_commit: "b"\nother:\n  <<: *base\n---\n'
    with pytest.raises(CheckFailure) as exc:
        parse(text)
    assert exc.value.diag.code in (E_CANON_TAG, E_CANON_ALIAS)


def test_custom_tag_rejected():
    with pytest.raises(CheckFailure) as exc:
        parse('---\nsummary: !!str "x"\n---\n')
    assert exc.value.diag.code == E_CANON_TAG


def test_implicit_timestamp_scalar_rejected():
    text = "---\nrecorded_at: 2026-09-28\n---\n"
    with pytest.raises(CheckFailure) as exc:
        parse(text)
    assert exc.value.diag.code == E_CANON_TAG


def test_unquoted_ulid_value_rejected():
    text = "---\nid: 01J8Z3K0000000000000000000\n---\n"
    with pytest.raises(CheckFailure) as exc:
        parse(text)
    assert exc.value.diag.code == E_CANON_QUOTE


def test_unquoted_sha_value_rejected():
    text = '---\nrecorded_at:\n  commit: 0123456789abcdef0123456789abcdef01234567\n---\n'
    with pytest.raises(CheckFailure) as exc:
        parse(text)
    assert exc.value.diag.code == E_CANON_QUOTE


def test_quoted_neighbour_hash_accepted():
    data = make_claim("01J8Z3K0000000000000000000")
    data["anchors"][0]["snapshot"]["neighbours"]["scip x"] = "ab" * 8
    text = "---\n" + emit(data) + "\n---\n"
    assert parse(text) == data


def test_unquoted_neighbour_hash_rejected():
    raw = "---\n" + emit(make_claim("01J8Z3K0000000000000000000")) + "\n---\n"
    raw = raw.replace(f'"{IDENT_OTHER}": "{FP}"', f'"{IDENT_OTHER}": {FP}', 1)
    assert f'"{IDENT_OTHER}": {FP}' in raw
    with pytest.raises(CheckFailure) as exc:
        parse(raw)
    assert exc.value.diag.code == E_CANON_QUOTE


def test_unquoted_identity_key_rejected():
    raw = "---\n" + emit(make_claim("01J8Z3K0000000000000000000")) + "\n---\n"
    raw = raw.replace(f'"{IDENT_OTHER}":', f"{IDENT_OTHER}:", 1)
    with pytest.raises(CheckFailure) as exc:
        parse(raw)
    assert exc.value.diag.code == E_CANON_QUOTE


def test_quoted_field_name_rejected():
    text = '---\n"kind": claim\n---\n'
    with pytest.raises(CheckFailure) as exc:
        parse(text)
    assert exc.value.diag.code == E_CANON_KEY


def test_proof_query_args_scalars_are_opaque_to_quoting():
    data = make_claim("01J8Z3K0000000000000000000")
    data["class"] = "structural"
    data["proof_query"] = {
        "tool": "cppgraph.calls",
        "args": {"symbol": "plain is allowed here"},
        "expect": {"op": "count", "value": 3},
        "provider_version": "1.0",
    }
    text = "---\n" + emit(data) + "\n---\n"
    assert parse(text) == data


def test_emitter_output_is_what_pyyaml_roundtrips():
    data = make_claim("01J8Z3K0000000000000000000")
    assert yaml.safe_load(emit(data)) == data
    data = make_verify("01J8Z3K0000000000000000001", "01J8Z3K0000000000000000000", "01J8Z3K0000000000000000000")
    assert yaml.safe_load(emit(data)) == data
