"""`masora mcp`: hand-rolled minimal MCP stdio server (MASORA_DESIGN.md §10.4, §13).

Newline-delimited JSON-RPC 2.0 over stdin/stdout. Exactly four methods:
`initialize` (standard MCP negotiation — the result always carries the pinned
PROTOCOL_VERSION; malformed params are -32602), `notifications/initialized`,
`tools/list` and `tools/call` — no resources/prompts/sampling. Tool failures
are MCP tool results with `isError: true` and diagnostic codes, never protocol
crashes; protocol-level failures are JSON-RPC errors (-32700 parse, -32600
invalid request, -32601 method not found, -32602 invalid params, -32603
internal) and a malformed line never stops the loop (W-MCP-PROTO on stderr).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import providers, schema
from .diagnostics import (
    E_MCP_ANCHOR,
    E_MCP_ARGS,
    E_MCP_DRIFT,
    E_MCP_GRAPH,
    E_MCP_UNKNOWN_ID,
    W_IDX_STALE,
    W_MCP_PROTO,
    CheckFailure,
    Diag,
)
from .index import (
    IndexingError,
    _open_index,
    build_index,
    index_db_path,
    index_stale_reason,
    search_index,
)
from .ulid import new_ulid
from .write import WriteError, envelopes, human_name, records, resolve_base, write_and_check

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "masora"
SERVER_VERSION = "0.1.0"


def _req_str(args: dict, name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value:
        raise WriteError(
            Diag(
                "error",
                E_MCP_ARGS,
                f"missing or invalid required argument {name!r} (non-empty string)",
            )
        )
    return value


def _opt_str(args: dict, name: str) -> str | None:
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise WriteError(Diag("error", E_MCP_ARGS, f"argument {name!r} must be a non-empty string"))
    return value


def _opt_bool(args: dict, name: str) -> bool | None:
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise WriteError(Diag("error", E_MCP_ARGS, f"argument {name!r} must be a boolean"))
    return value


def _opt_int(args: dict, name: str) -> int | None:
    value = args.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WriteError(
            Diag("error", E_MCP_ARGS, f"argument {name!r} must be a non-negative integer")
        )
    return value


def _opt_strlist(args: dict, name: str) -> list[str] | None:
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise WriteError(
            Diag("error", E_MCP_ARGS, f"argument {name!r} must be a list of non-empty strings")
        )
    return value


def _req_strlist(args: dict, name: str) -> list[str]:
    value = _opt_strlist(args, name)
    if not value:
        raise WriteError(
            Diag(
                "error",
                E_MCP_ARGS,
                f"missing or invalid required argument {name!r} (non-empty list of strings)",
            )
        )
    return value


def _opt_enum(args: dict, name: str, values: frozenset[str], default: str) -> str:
    value = args.get(name)
    if value is None:
        return default
    if value not in values:
        raise WriteError(
            Diag(
                "error",
                E_MCP_ARGS,
                f"argument {name!r} must be one of {sorted(values)}, got {value!r}",
            )
        )
    return value


def _require_head(repo_root: Path, kind: str) -> str:
    head = providers.repo_head(repo_root)
    if head is None:
        raise WriteError(
            Diag(
                "error",
                E_MCP_ARGS,
                f"repo_root {repo_root} has no git HEAD — the {kind} commit is mandatory (FORMAT.md §4)",
            )
        )
    return head


def _open_registry(repo_root: Path) -> providers.CppgraphRegistry:
    """A graph registry serving fingerprints, or `E-MCP-GRAPH` (re-index, §5.2)."""
    registry = providers.cppgraph_registry(repo_root)
    if not registry.available:
        reason = registry.reason or (
            f"no cppgraph graph store found under {repo_root}/.cppgraph — re-index with cppgraph"
            " (MASORA_DESIGN.md §5.2)"
        )
        registry.close()
        raise WriteError(Diag("error", E_MCP_GRAPH, reason))
    return registry


def _resolve_anchors(registry: providers.CppgraphRegistry, refs: list[str]) -> list[dict]:
    """Resolve anchor refs to code anchors with write-time fingerprints + snapshots (§10.2)."""
    anchors = []
    for ref in refs:
        resolution = registry.resolve(ref)
        if resolution is None or resolution.status == "not_found":
            raise WriteError(
                Diag(
                    "error",
                    E_MCP_ANCHOR,
                    f"anchor {ref!r} not found in the graph — nothing is written (FORMAT.md §6)",
                )
            )
        if resolution.status == "ambiguous":
            shown = ", ".join(resolution.candidates)
            raise WriteError(
                Diag(
                    "error",
                    E_MCP_ANCHOR,
                    f"anchor {ref!r} is ambiguous — candidates: {shown}; re-invoke with one exact"
                    " identity, nothing is written (FORMAT.md §6)",
                )
            )
        identity = resolution.identity
        fingerprint = registry.fingerprints("code", identity)
        snapshot = registry.edges("code", identity)
        if fingerprint is None or snapshot is None:
            raise WriteError(
                Diag(
                    "error",
                    E_MCP_ANCHOR,
                    f"anchor {ref!r} resolved to {identity} but the graph serves no fingerprint for it",
                )
            )
        anchors.append(
            {
                "provider": "code",
                "identity": identity,
                "fingerprint": fingerprint,
                "snapshot": snapshot,
            }
        )
    return anchors


def _resolve_target(
    base_dir: Path, parsed: dict, id_str: str, tool: str, wants: str
) -> tuple[str, str]:
    """Event id or lineage → (target ULID, lineage); lineage rides the fold (FORMAT.md §6).

    A lineage id — including the founding claim's, whose id equals the
    lineage — resolves to the lineage's DISPLAYED version for verify/refute,
    and to the active verify of that version for doubt. A non-lineage event id
    must be the kind the tool targets (claim for verify, verify for doubt,
    doubt for undoubt, any for refute).
    """
    if any(pe.record.lineage == id_str for pe in parsed.values()):
        envelope = envelopes(base_dir).get(id_str)
        if envelope is None:
            raise WriteError(
                Diag(
                    "error",
                    E_MCP_UNKNOWN_ID,
                    f"{tool}: lineage {id_str} resolves to no fold envelope in this base",
                )
            )
        if wants == "verify":
            verification = envelope["verification"]
            if verification["status"] != "verified" or verification["id"] is None:
                raise WriteError(
                    Diag(
                        "error",
                        E_MCP_UNKNOWN_ID,
                        f"lineage {id_str} has no active verify to {tool}",
                    )
                )
            return verification["id"], id_str
        if wants == "doubt":
            raise WriteError(
                Diag(
                    "error",
                    E_MCP_ARGS,
                    f"{tool} targets a doubt event ULID; pass the doubt's id (no lineage form for {tool})",
                )
            )
        displayed = envelope["displayed"]
        if displayed is None:
            raise WriteError(
                Diag(
                    "error",
                    E_MCP_UNKNOWN_ID,
                    f"lineage {id_str} has no displayed version to {tool}",
                )
            )
        return displayed, id_str
    record = parsed.get(id_str)
    if record is not None:
        kind = record.record.kind
        if wants == "any" or kind == wants:
            return record.record.id, record.record.lineage
        raise WriteError(
            Diag("error", E_MCP_ARGS, f"{tool} targets a {wants} event, got {kind}: {id_str}")
        )
    raise WriteError(
        Diag(
            "error",
            E_MCP_UNKNOWN_ID,
            f"{tool}: {id_str} resolves to no event id or lineage in this base",
        )
    )


def _tool_note(args: dict) -> str:
    statement = _req_str(args, "statement")
    summary = _req_str(args, "summary")
    repo_root = Path(_req_str(args, "repo_root"))
    base_dir = resolve_base(repo_root, _opt_str(args, "base"))
    head = _require_head(repo_root, "recorded_at")
    claim_class = _opt_enum(args, "class", schema.CLAIM_CLASS_VALUES, "semantic")
    source = _opt_enum(args, "source", schema.WRITABLE_SOURCE_VALUES, "llm")
    name = _opt_str(args, "name")
    cost_tokens = _opt_int(args, "cost_tokens")
    proof_query = args.get("proof_query")
    unanchored = _opt_bool(args, "unanchored") or False
    unanchored_reason = _opt_str(args, "unanchored_reason")
    anchor_refs = _opt_strlist(args, "anchors")

    graph_commit = None
    if anchor_refs and unanchored:
        raise WriteError(
            Diag("error", E_MCP_ARGS, "anchors and unanchored: true are mutually exclusive")
        )
    if anchor_refs:
        registry = _open_registry(repo_root)
        try:
            anchors = _resolve_anchors(registry, anchor_refs)
            graph_commit = registry.graph_commit
        finally:
            registry.close()
    elif unanchored:
        if not unanchored_reason:
            raise WriteError(
                Diag(
                    "error",
                    E_MCP_ARGS,
                    "unanchored: true requires unanchored_reason (FORMAT.md §5.1)",
                )
            )
        anchors = []
    else:
        raise WriteError(
            Diag(
                "error",
                E_MCP_ARGS,
                "note needs anchors, or unanchored: true with unanchored_reason (FORMAT.md §5.1)",
            )
        )
    if claim_class == "structural":
        if not isinstance(proof_query, dict) or not proof_query:
            raise WriteError(
                Diag(
                    "error",
                    E_MCP_ARGS,
                    "class: structural requires a proof_query object (FORMAT.md §4)",
                )
            )
    elif proof_query is not None:
        raise WriteError(
            Diag("error", E_MCP_ARGS, "proof_query requires class: structural (FORMAT.md §5.1)")
        )

    uid = new_ulid()
    data: dict = {
        "format_version": schema.SUPPORTED_FORMAT_VERSION,
        "id": uid,
        "lineage": uid,
        "kind": "claim",
        "class": claim_class,
        "source": source,
    }
    _apply_provenance(data, base_dir, source, name, args.get("effort"))
    data["summary"] = summary
    data["statement"] = statement
    data["anchors"] = anchors
    data["recorded_at"] = {"commit": head, "graph_commit": graph_commit}
    data["unanchored"] = unanchored
    if unanchored:
        data["unanchored_reason"] = unanchored_reason
    if claim_class == "structural":
        data["proof_query"] = proof_query
    if cost_tokens is not None:
        data["cost_tokens"] = cost_tokens

    rel, warnings = write_and_check(base_dir, data)
    lines = [f"wrote {rel}", f"id {uid}", f"lineage {uid}", f"anchors {len(anchors)}"]
    lines.extend(f"warning {diag.render()}" for diag in warnings)
    return "\n".join(lines)


def _apply_provenance(
    data: dict, base_dir: Path, source: str, name: str | None, effort: object
) -> None:
    """Fill `name`/`effort` on an event dict (MASORA_DESIGN.md §12.10).

    llm: the caller passes the model string as `name`; human: the name is
    self-signed from the base repo's `git config user.name` (null when unset).
    `effort` is passed through untouched whenever present — `validate_event`
    refuses a bad enum or effort on a non-llm writer with `E-PROVENANCE`.
    """
    if effort is not None:
        data["effort"] = effort
    if source == "human":
        derived = human_name(base_dir)
        if derived:
            data["name"] = derived
    elif name:
        data["name"] = name


def _tool_verify(args: dict) -> str:
    target_id = _req_str(args, "id")
    evidence = _req_strlist(args, "evidence")
    repo_root = Path(_req_str(args, "repo_root"))
    base_dir = resolve_base(repo_root, _opt_str(args, "base"))
    head = _require_head(repo_root, "verified_at")
    source = _opt_enum(args, "source", schema.WRITABLE_SOURCE_VALUES, "llm")
    name = _opt_str(args, "name")

    parsed = records(base_dir)
    target, lineage = _resolve_target(base_dir, parsed, target_id, "verify", "claim")
    claim = parsed[target]

    snapshots: dict = {}
    graph_commit = None
    if not claim.record.unanchored:
        registry = _open_registry(repo_root)
        try:
            for anchor in claim.anchors:
                current = registry.fingerprints("code", anchor.identity)
                snapshot = registry.edges("code", anchor.identity)
                if current is None or snapshot is None:
                    raise WriteError(
                        Diag(
                            "error",
                            E_MCP_DRIFT,
                            f"anchor {anchor.identity} no longer matches the graph — write a new"
                            " claim version instead (MASORA_DESIGN.md §6.3)",
                        )
                    )
                if current != anchor.fingerprint:
                    raise WriteError(
                        Diag(
                            "error",
                            E_MCP_DRIFT,
                            f"anchor {anchor.identity} fingerprint changed since the claim was"
                            " written — write a new claim version instead (MASORA_DESIGN.md §6.3)",
                        )
                    )
                snapshots[anchor.identity] = snapshot
            graph_commit = registry.graph_commit
        finally:
            registry.close()

    uid = new_ulid()
    data: dict = {
        "format_version": schema.SUPPORTED_FORMAT_VERSION,
        "id": uid,
        "lineage": lineage,
        "kind": "verify",
        "targets": target,
        "source": source,
    }
    _apply_provenance(data, base_dir, source, name, args.get("effort"))
    data["verified_at"] = {"commit": head, "graph_commit": graph_commit}
    data["evidence"] = evidence
    data["snapshots"] = snapshots

    rel, warnings = write_and_check(base_dir, data)
    lines = [
        f"wrote {rel}",
        f"id {uid}",
        f"lineage {lineage}",
        f"target {target}",
        f"source {source}",
        f"snapshots {len(snapshots)}",
    ]
    lines.extend(f"warning {diag.render()}" for diag in warnings)
    return "\n".join(lines)


def _tool_targeted(kind: str, args: dict) -> str:
    target_id = _req_str(args, "id")
    reason = _req_str(args, "reason")
    repo_root = Path(_req_str(args, "repo_root"))
    base_dir = resolve_base(repo_root, _opt_str(args, "base"))
    head = _require_head(repo_root, "recorded_at")
    source = _opt_enum(args, "source", schema.WRITABLE_SOURCE_VALUES, "llm")
    evidence = _opt_strlist(args, "evidence")
    name = _opt_str(args, "name")

    parsed = records(base_dir)
    wants = {"doubt": "verify", "undoubt": "doubt", "refute": "any"}[kind]
    target, lineage = _resolve_target(base_dir, parsed, target_id, kind, wants)

    graph_commit = None
    registry = providers.cppgraph_registry(repo_root)
    try:
        graph_commit = registry.graph_commit if registry.available else None
    finally:
        registry.close()

    uid = new_ulid()
    data: dict = {
        "format_version": schema.SUPPORTED_FORMAT_VERSION,
        "id": uid,
        "lineage": lineage,
        "kind": kind,
        "targets": target,
        "source": source,
        "reason": reason,
    }
    _apply_provenance(data, base_dir, source, name, args.get("effort"))
    data["recorded_at"] = {"commit": head, "graph_commit": graph_commit}
    if evidence:
        data["evidence"] = evidence

    rel, warnings = write_and_check(base_dir, data)
    lines = [f"wrote {rel}", f"id {uid}", f"lineage {lineage}", f"target {target}"]
    lines.extend(f"warning {diag.render()}" for diag in warnings)
    return "\n".join(lines)


def _tool_doubt(args: dict) -> str:
    return _tool_targeted("doubt", args)


def _tool_undoubt(args: dict) -> str:
    return _tool_targeted("undoubt", args)


def _tool_refute(args: dict) -> str:
    return _tool_targeted("refute", args)


def _resolve_read_context(args: dict) -> tuple[Path, Path]:
    base = _opt_str(args, "base")
    repo_value = _opt_str(args, "repo_root")
    repo_root = Path(repo_value) if repo_value else None
    base_dir = resolve_base(repo_root, base)
    return base_dir, repo_root if repo_root is not None else base_dir


def _ensure_index(base_dir: Path, repo: Path) -> Path:
    """Auto-build when missing (staleness is never auto-rebuilt — the hook owns freshness)."""
    db = index_db_path(base_dir, repo)
    if not db.is_file():
        result = build_index(base_dir, repo)
        if result.errors:
            raise WriteError(*result.errors)
    return db


def _tool_search(args: dict) -> str:
    query = _req_str(args, "query")
    base_dir, repo = _resolve_read_context(args)
    db = _ensure_index(base_dir, repo)
    try:
        hits = search_index(db, query)
    except IndexingError as exc:
        raise WriteError(exc.diag) from exc
    lines = []
    stale_reason = index_stale_reason(db, base_dir, repo)
    if stale_reason is not None:
        lines.append(Diag("warning", W_IDX_STALE, f"{stale_reason} — rerun masora index").render())
    if not hits:
        return "\n".join([*lines, "no results"])
    grouped: dict[str, list] = {}
    for hit in hits:
        grouped.setdefault(hit.lineage, []).append(hit)
    lines.append(f"{len(hits)} match(es) in {len(grouped)} lineage(s)")
    for lineage, group in grouped.items():
        first = group[0]
        lines.append(f"{lineage} [{first.resolution} {first.verification} flags: {first.flags}]")
        for hit in group:
            lines.append(f"  {hit.version} {hit.summary}")
    return "\n".join(lines)


def _tool_list_stale(args: dict) -> str:
    base_dir, repo = _resolve_read_context(args)
    db = _ensure_index(base_dir, repo)
    conn = _open_index(db)
    try:
        rows = conn.execute(
            "SELECT lineage, displayed, resolution, verification, suspect, doubted, pending,"
            " unknown, unanchored FROM lineages WHERE resolution NOT IN ('current', 'none')"
            " ORDER BY lineage"
        ).fetchall()
        heads = {}
        for row in rows:
            if row[1] is not None:
                found = conn.execute(
                    "SELECT summary FROM versions WHERE version = ?", (row[1],)
                ).fetchone()
                heads[row[0]] = found[0][:60] if found and found[0] else ""
    finally:
        conn.close()
    if not rows:
        return "no stale lineages"
    lines = [f"{len(rows)} stale lineage(s)"]
    for (
        lineage,
        displayed,
        resolution,
        verification,
        suspect,
        doubted,
        pending,
        unknown,
        unanchored,
    ) in rows:
        flags = (
            ",".join(
                name
                for name, value in (
                    ("suspect", suspect),
                    ("doubted", doubted),
                    ("pending", pending),
                    ("unknown", unknown),
                    ("unanchored", unanchored),
                )
                if value
            )
            or "-"
        )
        head = heads.get(lineage, "")
        lines.append(
            f"{lineage} [{resolution} {verification} flags: {flags}] {displayed or '-'} {head}".rstrip()
        )
    return "\n".join(lines)


def _str(**kwargs) -> dict:
    return {"type": "string", **kwargs}


def _schema(properties: dict, required: list[str], description: str | None = None) -> dict:
    schema: dict = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    if description is not None:
        schema["description"] = description
    return schema


_BASE_PROPS = {
    "base": _str(
        description="path to the Masora base directory (overrides the mapping/default_base resolution)"
    ),
    "repo_root": _str(
        description="path to the code repo checkout (the client passes repo context per call)"
    ),
}

TOOLS = [
    {
        "name": "note",
        "description": (
            "Create a lineage: write a v1 claim event (FORMAT.md §5.1). Code anchors are resolved"
            " via the cppgraph provider and fingerprinted + snapshotted at write time; refuses a"
            " graph behind HEAD (E-MCP-GRAPH), ambiguous or unknown anchor refs (E-MCP-ANCHOR,"
            " nothing written)."
        ),
        "inputSchema": _schema(
            {
                "statement": _str(
                    description="the full text: no length constraint, the detailed explanation"
                ),
                "summary": _str(
                    description="the injected one-liner: <= 120 characters, this is what cppgraph"
                    " surfaces"
                ),
                "repo_root": _str(description="path to the code repo checkout"),
                **_BASE_PROPS,
                "anchors": {
                    "type": "array",
                    "items": _str(description="exact SCIP symbol or a resolvable ref"),
                    "description": "code anchor refs resolved via the graph; omit only with unanchored: true",
                },
                "unanchored": {
                    "type": "boolean",
                    "description": "explicit unanchored claim (FORMAT.md §5.1)",
                },
                "unanchored_reason": _str(description="required when unanchored: true"),
                "class": {
                    "type": "string",
                    "enum": ["structural", "semantic"],
                    "description": "default semantic",
                },
                "proof_query": {
                    "type": "object",
                    "description": "required for class: structural (FORMAT.md §4)",
                },
                "source": {
                    "type": "string",
                    "enum": ["human", "llm"],
                    "description": "provenance of this event; default llm (graph is reserved for deriving tools, not writable here)",
                },
                "name": _str(
                    description="free string when source is llm: the model name; when source is human the name is self-signed from the base repo's git config"
                ),
                "effort": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "declared strength of the writing analysis, only when source is llm",
                },
                "cost_tokens": {
                    "type": "integer",
                    "description": "integer >= 0, read against name",
                },
            },
            ["statement", "summary", "repo_root"],
            description=(
                "summary is the injected one-liner (<= 120 characters, this is what cppgraph"
                " surfaces) and statement is the full text (no length constraint, the detailed"
                " explanation); content is written in English (base event files are pushed"
                " content)."
            ),
        ),
    },
    {
        "name": "verify",
        "description": (
            "Record a .verify event targeting a claim version (id or lineage → displayed version;"
            " FORMAT.md §5.2). Re-fingerprints the claim's immutable anchor set at verify time and"
            " refuses drift (E-MCP-DRIFT: write a new claim version instead)."
        ),
        "inputSchema": _schema(
            {
                "id": _str(description="claim version ULID or lineage ULID"),
                "evidence": {
                    "type": "array",
                    "items": _str(),
                    "description": "proof: graph replay, file ranges, tests, URLs (in English)",
                },
                "repo_root": _str(description="path to the code repo checkout"),
                **_BASE_PROPS,
                "source": {
                    "type": "string",
                    "enum": ["human", "llm"],
                    "description": "who ran the verification; default llm",
                },
                "name": _str(
                    description="free string when source is llm: the model name; when source is human the name is self-signed from the base repo's git config"
                ),
                "effort": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "declared strength of the verification analysis, only when source is llm",
                },
            },
            ["id", "evidence", "repo_root"],
        ),
    },
    {
        "name": "doubt",
        "description": (
            "Record a .doubt event: disagreement with a verification, without claiming it is wrong"
            " (FORMAT.md §5.3). Targets a .verify ULID, or a lineage → the active verify of the"
            " displayed version."
        ),
        "inputSchema": _schema(
            {
                "id": _str(description="verify ULID, or lineage ULID"),
                "reason": _str(description="why the verification is doubted (in English)"),
                "repo_root": _str(description="path to the code repo checkout"),
                **_BASE_PROPS,
                "source": {
                    "type": "string",
                    "enum": ["human", "llm"],
                    "description": "default llm",
                },
                "evidence": {
                    "type": "array",
                    "items": _str(),
                    "description": "proof items (in English)",
                },
                "name": _str(description="free string when source is llm: the model name"),
                "effort": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "only when source is llm",
                },
            },
            ["id", "reason", "repo_root"],
        ),
    },
    {
        "name": "undoubt",
        "description": "Record an .undoubt event lifting a doubt; targets the doubt event's ULID (FORMAT.md §5.3).",
        "inputSchema": _schema(
            {
                "id": _str(description="the doubt event's ULID"),
                "reason": _str(description="why the doubt is lifted (in English)"),
                "repo_root": _str(description="path to the code repo checkout"),
                **_BASE_PROPS,
                "source": {
                    "type": "string",
                    "enum": ["human", "llm"],
                    "description": "default llm",
                },
                "evidence": {
                    "type": "array",
                    "items": _str(),
                    "description": "proof items (in English)",
                },
                "name": _str(description="free string when source is llm: the model name"),
                "effort": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "only when source is llm",
                },
            },
            ["id", "reason", "repo_root"],
        ),
    },
    {
        "name": "refute",
        "description": (
            "Record a .refute event: the target is provably wrong (FORMAT.md §5.4). Targets any"
            " event ULID, or a lineage → its displayed version."
        ),
        "inputSchema": _schema(
            {
                "id": _str(description="event ULID, or lineage ULID"),
                "reason": _str(description="what contradicts the target (in English)"),
                "repo_root": _str(description="path to the code repo checkout"),
                **_BASE_PROPS,
                "source": {
                    "type": "string",
                    "enum": ["human", "llm"],
                    "description": "default llm",
                },
                "evidence": {
                    "type": "array",
                    "items": _str(),
                    "description": "proof items (in English)",
                },
                "name": _str(description="free string when source is llm: the model name"),
                "effort": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "only when source is llm",
                },
            },
            ["id", "reason", "repo_root"],
        ),
    },
    {
        "name": "search",
        "description": (
            "FTS query over the base index (MASORA_DESIGN.md §6.2); auto-builds a missing index,"
            " surfaces W-IDX-STALE without rebuilding (the SessionStart hook owns freshness)."
        ),
        "inputSchema": _schema(
            {
                "query": _str(description="FTS5 MATCH query over summaries and statements"),
                **{k: v for k, v in _BASE_PROPS.items() if k != "repo_root"},
                "repo_root": _str(
                    description="path to the code repo the index is keyed on (default: the base dir)"
                ),
            },
            ["query"],
        ),
    },
    {
        "name": "list_stale",
        "description": "List lineages whose resolution is not current/none (stale, restored, unknown), from the index (auto-built when missing).",
        "inputSchema": _schema(
            {
                **{k: v for k, v in _BASE_PROPS.items() if k != "repo_root"},
                "repo_root": _str(
                    description="path to the code repo the index is keyed on (default: the base dir)"
                ),
            },
            [],
        ),
    },
]

_TOOL_BY_NAME = {
    "note": _tool_note,
    "verify": _tool_verify,
    "doubt": _tool_doubt,
    "undoubt": _tool_undoubt,
    "refute": _tool_refute,
    "search": _tool_search,
    "list_stale": _tool_list_stale,
}


def _error_response(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _result(msg_id, text: str, *, is_error: bool = False) -> dict:
    result: dict = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _note_proto(detail: str) -> None:
    print(Diag("warning", W_MCP_PROTO, detail).render(), file=sys.stderr)


def _initialize(params: dict, msg_id) -> dict | None:
    requested = params.get("protocolVersion")
    if requested is None or not isinstance(requested, str):
        return _error_response(
            msg_id,
            -32602,
            f"params.protocolVersion is required and must be a string, got {requested!r}",
        )
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    }


def _tools_call(params: dict, msg_id) -> dict:
    name = params.get("name")
    tool = _TOOL_BY_NAME.get(name)
    if tool is None:
        return _error_response(msg_id, -32602, f"Unknown tool: {name!r}")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        return _error_response(msg_id, -32602, "params.arguments must be an object")
    try:
        text = tool(arguments)
    except WriteError as exc:
        return _result(msg_id, "\n".join(diag.render() for diag in exc.diags), is_error=True)
    except (IndexingError, CheckFailure) as exc:
        return _result(msg_id, exc.diag.render(), is_error=True)
    except Exception as exc:  # noqa: BLE001 — the server must survive any tool crash
        return _error_response(msg_id, -32603, f"Internal error: {exc!r}")
    return _result(msg_id, text)


def _dispatch(message: dict) -> dict | None:
    method = message.get("method")
    if not isinstance(method, str):
        return _error_response(
            message.get("id"), -32600, "Invalid Request: expected a 'method' member"
        )
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}
    has_id = "id" in message
    msg_id = message.get("id")
    if method == "initialize":
        return _initialize(params, msg_id) if has_id else None
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        if not has_id:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        if not has_id:
            return None
        return _tools_call(params, msg_id)
    if has_id:
        return _error_response(msg_id, -32601, f"Method not found: {method}")
    return None


def _handle_line(line: str) -> dict | None:
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        _note_proto(f"malformed JSON discarded: {exc}")
        return _error_response(None, -32700, f"Parse error: {exc}")
    if not isinstance(message, dict):
        _note_proto("message is not a JSON object")
        return _error_response(None, -32600, "Invalid Request: expected a JSON-RPC message object")
    return _dispatch(message)


def serve(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout, until EOF."""
    stream_in = stdin if stdin is not None else sys.stdin
    stream_out = stdout if stdout is not None else sys.stdout
    for raw in stream_in:
        line = raw.strip()
        if not line:
            continue
        response = _handle_line(line)
        if response is not None:
            stream_out.write(json.dumps(response) + "\n")
            stream_out.flush()
    return 0
