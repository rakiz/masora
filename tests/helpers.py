"""Test helpers: canonical block-style YAML emitter, event builders, graph fixture."""

from __future__ import annotations

import sqlite3
from pathlib import Path

OMIT = object()

SHA = "0123456789abcdef0123456789abcdef01234567"
FP = "ab" * 8
FP2 = "cd" * 8
IDENT_MAIN = "scip-clang cxx . . example#foo()."
IDENT_OTHER = "scip-clang cxx . . example#bar()."

ULID_L1 = "01J8Z3K0000000000000000000"
ULID_V1A = "01J8Z3K0000000000000000001"
ULID_D1A = "01J8Z3K0000000000000000002"
ULID_U1A = "01J8Z3K0000000000000000003"
ULID_R1A = "01J8Z3K0000000000000000004"
ULID_V2A = "01J8Z3K0000000000000000005"
ULID_L2 = "01J8Z3K0000000000000000006"
ULID_L3 = "01J8Z3K0000000000000000007"
ULID_V3A = "01J8Z3K0000000000000000008"


def scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def emit(value: object, indent: int = 0, parent_key: str | None = None) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        identity_keys = parent_key in ("neighbours", "snapshots", "lines")
        lines = []
        for key, item in value.items():
            key_text = scalar(key) if identity_keys else str(key)
            if isinstance(item, dict):
                if item:
                    lines.append(f"{pad}{key_text}:")
                    lines.append(emit(item, indent + 1, key))
                else:
                    lines.append(f"{pad}{key_text}: {{}}")
            elif isinstance(item, list):
                if item:
                    lines.append(f"{pad}{key_text}:")
                    lines.append(emit_list(item, indent + 1, key))
                else:
                    lines.append(f"{pad}{key_text}: []")
            else:
                lines.append(f"{pad}{key_text}: {scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        return emit_list(value, indent, parent_key)
    return scalar(value)


def emit_list(items: list, indent: int, parent_key: str | None = None) -> str:
    pad = "  " * indent
    lines = []
    for item in items:
        if isinstance(item, dict):
            text = emit(item, indent + 1, parent_key)
            child_pad = "  " * (indent + 1)
            first, _sep, rest = text.partition("\n")
            lines.append(f"{pad}- {first[len(child_pad) :]}" + (f"\n{rest}" if rest else ""))
        else:
            lines.append(f"{pad}- {scalar(item)}")
    return "\n".join(lines)


def anchor(
    identity: str = IDENT_MAIN,
    fingerprint: str = FP,
    snapshot: dict | None | object = None,
    **extra,
) -> dict:
    if snapshot is None:
        snapshot = {"edges": FP, "neighbours": {IDENT_OTHER: FP}}
    result = {
        "provider": "code",
        "identity": identity,
        "fingerprint": fingerprint,
        "snapshot": snapshot,
    }
    result.update(extra)
    return result


def make_claim(uid: str, lineage: str | None = None, **overrides) -> dict:
    data = {
        "format_version": 1,
        "id": uid,
        "lineage": lineage or uid,
        "kind": "claim",
        "class": "semantic",
        "source": "llm",
        "summary": "One line summary",
        "statement": "Full statement.",
        "anchors": [anchor()],
        "recorded_at": {"commit": SHA, "graph_commit": SHA},
        "unanchored": False,
    }
    return apply_overrides(data, overrides)


def make_verify(uid: str, lineage: str, targets: str, **overrides) -> dict:
    data = {
        "format_version": 1,
        "id": uid,
        "lineage": lineage,
        "kind": "verify",
        "targets": targets,
        "source": "llm",
        "verified_at": {"commit": SHA, "graph_commit": SHA},
        "evidence": ["replay: 3 edges, expected 3"],
        "snapshots": {IDENT_MAIN: {"edges": FP, "neighbours": {IDENT_OTHER: FP}}},
    }
    return apply_overrides(data, overrides)


def make_doubt(uid: str, lineage: str, targets: str, kind: str = "doubt", **overrides) -> dict:
    data = {
        "format_version": 1,
        "id": uid,
        "lineage": lineage,
        "kind": kind,
        "targets": targets,
        "source": "human",
        "recorded_at": {"commit": SHA, "graph_commit": None},
        "reason": "A reason.",
    }
    return apply_overrides(data, overrides)


def apply_overrides(data: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if value is OMIT:
            data.pop(key, None)
        else:
            data[key] = value
    return data


def render_event(data: dict, body: str = "") -> str:
    return f"---\n{emit(data)}\n---\n{body}"


def write_event(base: Path, relpath: str, data: dict) -> Path:
    path = base / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_event(data), encoding="utf-8")
    return path


GRAPH_DDL = """
CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT);
CREATE TABLE symbols (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    display_name TEXT,
    file_id INTEGER,
    line INTEGER,
    end_line INTEGER,
    documentation TEXT,
    scip_kind TEXT,
    signature_documentation TEXT,
    is_out_of_project INTEGER
);
CREATE TABLE edges (
    kind TEXT NOT NULL,
    src_id INTEGER NOT NULL,
    dst_id INTEGER NOT NULL,
    file_id INTEGER,
    line INTEGER
);
CREATE TABLE refs (
    symbol_id INTEGER NOT NULL,
    file_id INTEGER,
    line INTEGER,
    enclosing_id INTEGER,
    roles INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def write_graph_db(
    path: Path,
    *,
    commit: str | None = SHA,
    symbols: dict[str, tuple[str, int, int | None]] | None = None,
    calls: list[tuple[str, str]] | None = None,
) -> Path:
    """Minimal cppgraph store (schema v5: files/symbols/edges/meta, cf. cppgraph store.py).

    `symbols` maps symbol string -> (repo-relative file path, 0-indexed
    definition line, 0-indexed body-extent end line or None); `calls` lists
    (caller, callee) pairs written as `calls` edges. `commit=None` omits
    `source_commit` from meta entirely.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(GRAPH_DDL)
        file_ids: dict[str, int] = {}
        sym_ids: dict[str, int] = {}
        for sid, (symbol, (rel, line, end)) in enumerate((symbols or {}).items()):
            if rel not in file_ids:
                file_ids[rel] = conn.execute(
                    "INSERT INTO files (path) VALUES (?)", (rel,)
                ).lastrowid
            conn.execute(
                "INSERT INTO symbols (id, symbol, display_name, file_id, line, end_line)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (sid, symbol, symbol.rsplit("#", 1)[-1], file_ids[rel], line, end),
            )
            sym_ids[symbol] = sid
        for caller, callee in calls or []:
            conn.execute(
                "INSERT INTO edges (kind, src_id, dst_id) VALUES ('calls', ?, ?)",
                (sym_ids[caller], sym_ids[callee]),
            )
        meta = {"schema_version": "5", "built_at": "2026-01-01T00:00:00+00:00"}
        if commit is not None:
            meta["source_commit"] = commit
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", meta.items())
        conn.commit()
    finally:
        conn.close()
    return path
