"""Test helpers: canonical block-style YAML emitter and event builders."""

from __future__ import annotations

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
        identity_keys = parent_key in ("neighbours", "snapshots")
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
            first, sep, rest = text.partition("\n")
            lines.append(f"{pad}- {first[len(child_pad):]}" + (f"\n{rest}" if rest else ""))
        else:
            lines.append(f"{pad}- {scalar(item)}")
    return "\n".join(lines)


def anchor(identity: str = IDENT_MAIN, fingerprint: str = FP, snapshot: dict | None | object = None, **extra) -> dict:
    if snapshot is None:
        snapshot = {"edges": FP, "neighbours": {IDENT_OTHER: FP}}
    result = {"provider": "code", "identity": identity, "fingerprint": fingerprint, "snapshot": snapshot}
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
        "actor": "llm",
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
