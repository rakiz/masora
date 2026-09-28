"""Per-kind frontmatter schema validation (FORMAT.md §4, §5)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .diagnostics import (
    E_ANCHOR,
    E_FILENAME,
    E_PROOFQUERY,
    E_SCHEMA,
    E_SUMMARY,
    E_TIMESTAMP,
    E_ULID,
    E_VERSION,
    CheckFailure,
    Diag,
)
from .ulid import UlidError, validate_ulid

KINDS = frozenset({"claim", "verify", "doubt", "undoubt", "refute", "unrefute"})
CLAIM_CLASS_VALUES = frozenset({"structural", "semantic"})
SOURCE_VALUES = frozenset({"human", "llm", "derived_from_graph"})
ACTOR_VALUES = frozenset({"human", "llm"})
PROVIDER_VALUES = frozenset({"code"})
EXPECT_OPS = frozenset({"set-equality", "count", "superset"})
SUPPORTED_FORMAT_VERSION = 1

FORBIDDEN = {
    "claim": frozenset({"targets", "actor", "verified_at", "evidence", "snapshots"}),
    "verify": frozenset(
        {
            "source",
            "reason",
            "contradicts",
            "summary",
            "statement",
            "anchors",
            "class",
            "unanchored",
            "cost_tokens",
            "recorded_at",
        }
    ),
    "doubt": frozenset(
        {
            "actor",
            "verified_at",
            "snapshots",
            "anchors",
            "summary",
            "statement",
            "class",
            "contradicts",
            "cost_tokens",
        }
    ),
    "undoubt": frozenset(
        {
            "actor",
            "verified_at",
            "snapshots",
            "anchors",
            "summary",
            "statement",
            "class",
            "contradicts",
            "cost_tokens",
        }
    ),
    "refute": frozenset(
        {
            "actor",
            "verified_at",
            "snapshots",
            "anchors",
            "summary",
            "statement",
            "class",
            "contradicts",
            "cost_tokens",
        }
    ),
    "unrefute": frozenset(
        {
            "actor",
            "verified_at",
            "snapshots",
            "anchors",
            "summary",
            "statement",
            "class",
            "contradicts",
            "cost_tokens",
        }
    ),
}
REQUIRED = {
    "claim": frozenset({"class", "source", "summary", "statement", "recorded_at", "unanchored"}),
    "verify": frozenset({"targets", "actor", "verified_at", "evidence", "snapshots"}),
    "doubt": frozenset({"targets", "source", "reason", "recorded_at"}),
    "undoubt": frozenset({"targets", "source", "reason", "recorded_at"}),
    "refute": frozenset({"targets", "source", "reason", "recorded_at"}),
    "unrefute": frozenset({"targets", "source", "reason", "recorded_at"}),
}
OPTIONAL = {
    "claim": frozenset(
        {
            "model",
            "cost_tokens",
            "contradicts",
            "anchors",
            "unanchored_reason",
            "proof_query",
            "reason",
        }
    ),
    "verify": frozenset({"model"}),
    "doubt": frozenset({"model", "evidence"}),
    "undoubt": frozenset({"model", "evidence"}),
    "refute": frozenset({"model", "evidence"}),
    "unrefute": frozenset({"model", "evidence"}),
}
HEX_RE = re.compile(r"^[0-9a-f]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PROOF_TOOL_RE = re.compile(r"^cppgraph\.[A-Za-z0-9_.-]+$")
SHARED_REQUIRED = frozenset({"format_version", "id", "lineage", "kind"})
for _kind in KINDS:
    REQUIRED[_kind] = frozenset(REQUIRED[_kind] | SHARED_REQUIRED)


@dataclass
class EventRecord:
    path: str
    id: str
    lineage: str
    kind: str
    targets: str | None
    contradicts: str | None
    source: str | None
    actor: str | None
    model: str | None
    cost_tokens: int | None
    claim_class: str | None
    unanchored: bool
    anchor_identities: tuple[str, ...]
    snapshot_keys: tuple[str, ...]
    proof_query: dict | None
    summary: str | None
    timestamp_field: str
    timestamp_commit: str
    timestamp_graph_commit: str | None
    evidence_count: int | None


def validate_event(data: dict, kind: str, path: str) -> EventRecord:
    _check_version(data, path)
    if "kind" not in data or data["kind"] is None:
        raise CheckFailure(
            Diag("error", E_SCHEMA, f"required field 'kind' missing or null on kind {kind!r}", path)
        )
    frontmatter_kind = data["kind"]
    if frontmatter_kind not in KINDS:
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                f"kind must be one of {sorted(KINDS)}, got {frontmatter_kind!r}",
                path,
            )
        )
    if frontmatter_kind != kind:
        raise CheckFailure(
            Diag(
                "error",
                E_FILENAME,
                f"frontmatter kind {frontmatter_kind!r} does not equal filename kind {kind!r}",
                path,
            )
        )
    for key in data:
        if key not in REQUIRED[kind] and key not in OPTIONAL[kind] and key not in FORBIDDEN[kind]:
            raise CheckFailure(
                Diag("error", E_SCHEMA, f"unknown field {key!r} for kind {kind!r}", path)
            )
    for key in FORBIDDEN[kind]:
        if key in data:
            raise CheckFailure(
                Diag(
                    "error",
                    E_SCHEMA,
                    f"forbidden field {key!r} on kind {kind!r} (present even as null)",
                    path,
                )
            )
    for key in REQUIRED[kind]:
        if key not in data or data[key] is None:
            raise CheckFailure(
                Diag(
                    "error",
                    E_SCHEMA,
                    f"required field {key!r} missing or null on kind {kind!r}",
                    path,
                )
            )

    event_id = _ulid(data["id"], "id", path)
    lineage = _ulid(data["lineage"], "lineage", path)
    if kind == "claim":
        return _validate_claim(data, event_id, lineage, path)
    return _validate_targeted(data, event_id, lineage, kind, path)


def _ulid(value: object, what: str, path: str) -> str:
    try:
        return validate_ulid(value, what=what)
    except UlidError as exc:
        raise CheckFailure(Diag("error", E_ULID, str(exc), path)) from exc


def _check_version(data: dict, path: str) -> None:
    version = data.get("format_version")
    if version is None:
        raise CheckFailure(
            Diag("error", E_VERSION, "required field 'format_version' missing or null", path)
        )
    if isinstance(version, bool) or not isinstance(version, int):
        raise CheckFailure(
            Diag(
                "error",
                E_VERSION,
                f"format_version must be an integer, got {type(version).__name__}",
                path,
            )
        )
    if version != SUPPORTED_FORMAT_VERSION:
        raise CheckFailure(
            Diag(
                "error",
                E_VERSION,
                f"unsupported format_version {version} (supported major: {SUPPORTED_FORMAT_VERSION})",
                path,
            )
        )


def _validate_claim(data: dict, event_id: str, lineage: str, path: str) -> EventRecord:
    claim_class = data["class"]
    if claim_class not in CLAIM_CLASS_VALUES:
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                f"class must be one of {sorted(CLAIM_CLASS_VALUES)}, got {claim_class!r}",
                path,
            )
        )
    source = data["source"]
    if source not in SOURCE_VALUES:
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                f"source must be one of {sorted(SOURCE_VALUES)}, got {source!r}",
                path,
            )
        )
    unanchored = data["unanchored"]
    if not isinstance(unanchored, bool):
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                f"unanchored must be a boolean, got {type(unanchored).__name__}",
                path,
            )
        )
    summary = _check_summary(data["summary"], path)
    statement = data["statement"]
    if not isinstance(statement, str):
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                f"statement must be a string, got {type(statement).__name__}",
                path,
            )
        )

    anchors = data.get("anchors")
    if unanchored:
        if anchors is not None and anchors != []:
            raise CheckFailure(
                Diag("error", E_ANCHOR, "unanchored: true requires anchors: [] (or omitted)", path)
            )
        anchor_identities: tuple[str, ...] = ()
    else:
        if not isinstance(anchors, list) or len(anchors) == 0:
            raise CheckFailure(
                Diag(
                    "error",
                    E_ANCHOR,
                    "anchors must be a non-empty list when unanchored: false",
                    path,
                )
            )
        anchor_identities = _validate_anchors(anchors, path)
    if claim_class == "structural" and unanchored:
        raise CheckFailure(
            Diag(
                "error",
                E_ANCHOR,
                "class: structural with unanchored: true is rejected (a structural claim must anchor)",
                path,
            )
        )

    unanchored_reason = data.get("unanchored_reason")
    if unanchored:
        if not isinstance(unanchored_reason, str) or not unanchored_reason:
            raise CheckFailure(
                Diag(
                    "error",
                    E_SCHEMA,
                    "unanchored_reason must be a non-empty string when unanchored: true",
                    path,
                )
            )
    elif unanchored_reason is not None:
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                "unanchored_reason must be null or omitted when unanchored: false",
                path,
            )
        )

    proof_query = data.get("proof_query")
    if claim_class == "structural":
        if proof_query is None:
            raise CheckFailure(
                Diag(
                    "error", E_PROOFQUERY, "class: structural requires a non-null proof_query", path
                )
            )
        _validate_proof_query(proof_query, path)
    elif proof_query is not None:
        raise CheckFailure(
            Diag(
                "error",
                E_PROOFQUERY,
                "proof_query must be null or omitted for class: semantic",
                path,
            )
        )

    contradicts = data.get("contradicts")
    if contradicts is not None:
        _ulid(contradicts, "contradicts", path)
        if data.get("reason") is None:
            raise CheckFailure(
                Diag("error", E_SCHEMA, "reason is required when contradicts is set", path)
            )
    reason = data.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise CheckFailure(
            Diag("error", E_SCHEMA, f"reason must be a string, got {type(reason).__name__}", path)
        )
    if event_id != lineage and reason is None:
        raise CheckFailure(
            Diag("error", E_SCHEMA, "reason is required for v2+ claims (id != lineage)", path)
        )

    model = _check_model(data.get("model"), source, path)
    cost_tokens = data.get("cost_tokens")
    if cost_tokens is not None and (
        isinstance(cost_tokens, bool) or not isinstance(cost_tokens, int) or cost_tokens < 0
    ):
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                f"cost_tokens must be an integer >= 0, got {cost_tokens!r}",
                path,
            )
        )

    commit, graph_commit = _validate_timestamp(
        data["recorded_at"], "recorded_at", require_graph=not unanchored, path=path
    )

    return EventRecord(
        path=path,
        id=event_id,
        lineage=lineage,
        kind="claim",
        targets=None,
        contradicts=contradicts,
        source=source,
        actor=None,
        model=model,
        cost_tokens=cost_tokens,
        claim_class=claim_class,
        unanchored=unanchored,
        anchor_identities=anchor_identities,
        snapshot_keys=(),
        proof_query=proof_query if claim_class == "structural" else None,
        summary=summary,
        timestamp_field="recorded_at",
        timestamp_commit=commit,
        timestamp_graph_commit=graph_commit,
        evidence_count=None,
    )


def _validate_targeted(
    data: dict, event_id: str, lineage: str, kind: str, path: str
) -> EventRecord:
    source = data.get("source")
    if source is not None and source not in SOURCE_VALUES:
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                f"source must be one of {sorted(SOURCE_VALUES)}, got {source!r}",
                path,
            )
        )
    actor = None
    evidence_count = None
    if kind == "verify":
        actor = data["actor"]
        if actor not in ACTOR_VALUES:
            raise CheckFailure(
                Diag(
                    "error",
                    E_SCHEMA,
                    f"actor must be one of {sorted(ACTOR_VALUES)}, got {actor!r}",
                    path,
                )
            )
        evidence = data["evidence"]
        if not isinstance(evidence, list) or len(evidence) == 0:
            raise CheckFailure(
                Diag("error", E_SCHEMA, "evidence must be a non-empty list on .verify", path)
            )
        for item in evidence:
            if not isinstance(item, str):
                raise CheckFailure(
                    Diag(
                        "error",
                        E_SCHEMA,
                        f"evidence items must be strings, got {type(item).__name__}",
                        path,
                    )
                )
        evidence_count = len(evidence)
        snapshots = data["snapshots"]
        _validate_snapshots(snapshots, path)
        commit, graph_commit = _validate_timestamp(
            data["verified_at"], "verified_at", require_graph=len(snapshots) > 0, path=path
        )
        model = _check_model(data.get("model"), actor, path)
    else:
        reason = data["reason"]
        if not isinstance(reason, str):
            raise CheckFailure(
                Diag(
                    "error", E_SCHEMA, f"reason must be a string, got {type(reason).__name__}", path
                )
            )
        commit, graph_commit = _validate_timestamp(
            data["recorded_at"], "recorded_at", require_graph=False, path=path
        )
        evidence = data.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, list):
                raise CheckFailure(
                    Diag(
                        "error",
                        E_SCHEMA,
                        f"evidence must be a list, got {type(evidence).__name__}",
                        path,
                    )
                )
            for item in evidence:
                if not isinstance(item, str):
                    raise CheckFailure(
                        Diag(
                            "error",
                            E_SCHEMA,
                            f"evidence items must be strings, got {type(item).__name__}",
                            path,
                        )
                    )
            evidence_count = len(evidence)
        model = _check_model(data.get("model"), source, path)
    return EventRecord(
        path=path,
        id=event_id,
        lineage=lineage,
        kind=kind,
        targets=_ulid(data["targets"], "targets", path),
        contradicts=None,
        source=source,
        actor=actor,
        model=model,
        cost_tokens=None,
        claim_class=None,
        unanchored=False,
        anchor_identities=(),
        snapshot_keys=tuple(data["snapshots"]) if kind == "verify" else (),
        proof_query=None,
        summary=None,
        timestamp_field="verified_at" if kind == "verify" else "recorded_at",
        timestamp_commit=commit,
        timestamp_graph_commit=graph_commit,
        evidence_count=evidence_count,
    )


def _check_summary(summary: object, path: str) -> str:
    if not isinstance(summary, str):
        raise CheckFailure(
            Diag(
                "error", E_SUMMARY, f"summary must be a string, got {type(summary).__name__}", path
            )
        )
    if summary == "" or "\n" in summary or any(ord(c) < 32 or ord(c) == 127 for c in summary):
        raise CheckFailure(
            Diag(
                "error",
                E_SUMMARY,
                "summary must be a single non-empty line without control characters",
                path,
            )
        )
    if len(summary) > 120:
        raise CheckFailure(
            Diag("error", E_SUMMARY, f"summary exceeds 120 characters ({len(summary)})", path)
        )
    return summary


def _check_model(model: object, writer: str | None, path: str) -> str | None:
    if model is None:
        return None
    if not isinstance(model, str) or not model:
        raise CheckFailure(
            Diag("error", E_SCHEMA, f"model must be a non-empty string, got {model!r}", path)
        )
    if writer != "llm":
        raise CheckFailure(
            Diag(
                "error",
                E_SCHEMA,
                f"model is only recorded when the writer is an LLM (writer: {writer!r})",
                path,
            )
        )
    return model


def _validate_anchors(anchors: list, path: str) -> tuple[str, ...]:
    identities: list[str] = []
    for i, anchor in enumerate(anchors):
        where = f"anchors[{i}]"
        if not isinstance(anchor, dict):
            raise CheckFailure(
                Diag(
                    "error",
                    E_ANCHOR,
                    f"{where} must be a mapping, got {type(anchor).__name__}",
                    path,
                )
            )
        expected = {"provider", "identity", "fingerprint", "snapshot"}
        if set(anchor) != expected:
            raise CheckFailure(
                Diag(
                    "error",
                    E_ANCHOR,
                    f"{where} must have exactly the fields {sorted(expected)}, got {sorted(anchor)}",
                    path,
                )
            )
        if anchor["provider"] not in PROVIDER_VALUES:
            raise CheckFailure(
                Diag(
                    "error",
                    E_ANCHOR,
                    f"{where}.provider must be one of {sorted(PROVIDER_VALUES)} in format_version 1, got {anchor['provider']!r}",
                    path,
                )
            )
        identity = anchor["identity"]
        if not isinstance(identity, str) or not identity:
            raise CheckFailure(
                Diag("error", E_ANCHOR, f"{where}.identity must be a non-empty string", path)
            )
        if not isinstance(anchor["fingerprint"], str) or not HEX_RE.match(anchor["fingerprint"]):
            raise CheckFailure(
                Diag(
                    "error",
                    E_ANCHOR,
                    f"{where}.fingerprint must be a non-empty lowercase-hex string",
                    path,
                )
            )
        _validate_snapshot(anchor["snapshot"], where, path, required=True)
        identities.append(identity)
    if len(set(identities)) != len(identities):
        raise CheckFailure(
            Diag("error", E_ANCHOR, "anchor identities must be unique within a claim", path)
        )
    return tuple(identities)


def _validate_snapshot(snapshot: object, where: str, path: str, required: bool) -> None:
    if snapshot is None:
        if required:
            raise CheckFailure(
                Diag("error", E_ANCHOR, f"{where}.snapshot is required for code anchors", path)
            )
        return
    _validate_snapshot_shape(snapshot, where, path)


def _validate_snapshots(snapshots: object, path: str) -> None:
    if not isinstance(snapshots, dict):
        raise CheckFailure(
            Diag(
                "error",
                E_ANCHOR,
                f"snapshots must be a mapping, got {type(snapshots).__name__}",
                path,
            )
        )
    for identity, snapshot in snapshots.items():
        _validate_snapshot_shape(snapshot, f"snapshots[{identity!r}]", path)


def _validate_snapshot_shape(snapshot: object, where: str, path: str) -> None:
    if not isinstance(snapshot, dict):
        raise CheckFailure(
            Diag(
                "error",
                E_ANCHOR,
                f"{where} must be a mapping {{edges, neighbours}}, got {type(snapshot).__name__}",
                path,
            )
        )
    if set(snapshot) != {"edges", "neighbours"}:
        raise CheckFailure(
            Diag(
                "error",
                E_ANCHOR,
                f"{where} must have exactly the fields [edges, neighbours], got {sorted(snapshot)}",
                path,
            )
        )
    if not isinstance(snapshot["edges"], str) or not HEX_RE.match(snapshot["edges"]):
        raise CheckFailure(
            Diag("error", E_ANCHOR, f"{where}.edges must be a non-empty lowercase-hex string", path)
        )
    neighbours = snapshot["neighbours"]
    if not isinstance(neighbours, dict):
        raise CheckFailure(
            Diag(
                "error",
                E_ANCHOR,
                f"{where}.neighbours must be a mapping, got {type(neighbours).__name__}",
                path,
            )
        )
    for neighbour_identity, neighbour_hash in neighbours.items():
        if not isinstance(neighbour_hash, str) or not HEX_RE.match(neighbour_hash):
            raise CheckFailure(
                Diag(
                    "error",
                    E_ANCHOR,
                    f"{where}.neighbours[{neighbour_identity!r}] must be a non-empty lowercase-hex string",
                    path,
                )
            )


def _validate_timestamp(
    timestamp: object, field: str, *, require_graph: bool, path: str
) -> tuple[str, str | None]:
    where = f"{field} (at {path})"
    if not isinstance(timestamp, dict):
        raise CheckFailure(
            Diag(
                "error",
                E_TIMESTAMP,
                f"{where} must be a mapping {{commit, graph_commit}}, got {type(timestamp).__name__}",
                path,
            )
        )
    if set(timestamp) - {"commit", "graph_commit"}:
        raise CheckFailure(
            Diag(
                "error",
                E_TIMESTAMP,
                f"{where} has unknown fields {sorted(set(timestamp) - {'commit', 'graph_commit'})}",
                path,
            )
        )
    commit = timestamp.get("commit")
    if not isinstance(commit, str) or not SHA_RE.match(commit):
        raise CheckFailure(
            Diag("error", E_TIMESTAMP, f"{where}.commit must be a full 40-hex SHA", path)
        )
    graph_commit = timestamp.get("graph_commit")
    if graph_commit is not None:
        if not isinstance(graph_commit, str) or not SHA_RE.match(graph_commit):
            raise CheckFailure(
                Diag(
                    "error",
                    E_TIMESTAMP,
                    f"{where}.graph_commit must be a full 40-hex SHA or null",
                    path,
                )
            )
    elif require_graph:
        raise CheckFailure(
            Diag(
                "error",
                E_TIMESTAMP,
                f"{where}.graph_commit is mandatory when code anchors or snapshots are present",
                path,
            )
        )
    return commit, graph_commit


def _validate_proof_query(proof_query: object, path: str) -> None:
    where = f"proof_query (at {path})"
    if not isinstance(proof_query, dict):
        raise CheckFailure(
            Diag(
                "error",
                E_PROOFQUERY,
                f"{where} must be a mapping {{tool, args, expect, provider_version}}, got {type(proof_query).__name__}",
                path,
            )
        )
    if set(proof_query) != {"tool", "args", "expect", "provider_version"}:
        raise CheckFailure(
            Diag(
                "error",
                E_PROOFQUERY,
                f"{where} must have exactly the fields [tool, args, expect, provider_version], got {sorted(proof_query)}",
                path,
            )
        )
    tool = proof_query["tool"]
    if not isinstance(tool, str) or not PROOF_TOOL_RE.match(tool):
        raise CheckFailure(
            Diag(
                "error",
                E_PROOFQUERY,
                f"{where}.tool must use a registered prefix (cppgraph.<query>), got {tool!r}",
                path,
            )
        )
    args = proof_query["args"]
    if not isinstance(args, dict) or not args:
        raise CheckFailure(
            Diag("error", E_PROOFQUERY, f"{where}.args must be a non-empty mapping", path)
        )
    provider_version = proof_query["provider_version"]
    if not isinstance(provider_version, str) or not provider_version.strip():
        raise CheckFailure(
            Diag(
                "error",
                E_PROOFQUERY,
                f"{where}.provider_version must be a non-empty quoted string",
                path,
            )
        )
    expect = proof_query["expect"]
    if not isinstance(expect, dict):
        raise CheckFailure(
            Diag("error", E_PROOFQUERY, f"{where}.expect must be a mapping {{op, value}}", path)
        )
    if set(expect) != {"op", "value"}:
        raise CheckFailure(
            Diag(
                "error",
                E_PROOFQUERY,
                f"{where}.expect must have exactly the fields [op, value], got {sorted(expect)}",
                path,
            )
        )
    op = expect["op"]
    if op not in EXPECT_OPS:
        raise CheckFailure(
            Diag(
                "error",
                E_PROOFQUERY,
                f"{where}.expect.op must be one of {sorted(EXPECT_OPS)}, got {op!r}",
                path,
            )
        )
    value = expect["value"]
    if op == "count":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CheckFailure(
                Diag(
                    "error",
                    E_PROOFQUERY,
                    f"{where}.expect.value must be a non-negative integer when op is count, got {value!r}",
                    path,
                )
            )
    elif not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CheckFailure(
            Diag(
                "error",
                E_PROOFQUERY,
                f"{where}.expect.value must be a list of strings when op is {op}, got {value!r}",
                path,
            )
        )
