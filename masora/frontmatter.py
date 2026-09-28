"""YAML frontmatter loading under FORMAT.md §4 canonicalization rules."""

from __future__ import annotations

import yaml
from yaml.events import AliasEvent

from .diagnostics import (
    CheckFailure,
    Diag,
    E_CANON_ALIAS,
    E_CANON_DUPKEY,
    E_CANON_FLOW,
    E_CANON_KEY,
    E_CANON_QUOTE,
    E_CANON_TAG,
    E_FRONTMATTER,
    E_YAML,
)

_STANDARD_SCALAR_TAGS = {
    "tag:yaml.org,2002:str",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:null",
}
_STANDARD_COLLECTION_TAGS = {"tag:yaml.org,2002:seq", "tag:yaml.org,2002:map"}
_MERGE_TAG = "tag:yaml.org,2002:merge"

_QUOTED_VALUE_KEYS = frozenset(
    {
        "id",
        "lineage",
        "targets",
        "contradicts",
        "fingerprint",
        "edges",
        "commit",
        "graph_commit",
        "provider_version",
        "identity",
        "neighbours",
    }
)
_IDENTITY_KEYED_MAPS = frozenset({"snapshots", "neighbours"})


class _CanonicalLoader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self.alias_seen = False
        self.explicit_tag_seen = False

    def compose_node(self, parent, index):
        if self.check_event(AliasEvent):
            self.alias_seen = True
        else:
            event = self.peek_event()
            if event is not None and event.anchor is not None:
                self.alias_seen = True
            if event is not None and event.tag is not None:
                self.explicit_tag_seen = True
        return super().compose_node(parent, index)


def split_frontmatter(text: str, path: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        raise CheckFailure(Diag("error", E_FRONTMATTER, "file does not start with a '---' frontmatter delimiter", path))
    for end in range(1, len(lines)):
        if lines[end].rstrip() == "---":
            return "\n".join(lines[1:end])
    raise CheckFailure(Diag("error", E_FRONTMATTER, "frontmatter is not terminated by a '---' delimiter", path))


def load_frontmatter(text: str, path: str) -> dict:
    raw = split_frontmatter(text, path)
    loader = _CanonicalLoader(raw)
    try:
        node = loader.get_single_node()
    except yaml.YAMLError as exc:
        raise CheckFailure(Diag("error", E_YAML, f"invalid YAML: {exc}", path)) from exc
    if node is None:
        raise CheckFailure(Diag("error", E_FRONTMATTER, "frontmatter is empty", path))
    if loader.alias_seen:
        raise CheckFailure(Diag("error", E_CANON_ALIAS, "anchors and aliases are rejected", path))
    if loader.explicit_tag_seen:
        raise CheckFailure(Diag("error", E_CANON_TAG, "explicit tags are rejected", path))
    _walk_node(node, "", path, parent_key=None, opaque=False)
    data = loader.construct_document(node)
    if not isinstance(data, dict):
        raise CheckFailure(Diag("error", E_FRONTMATTER, f"frontmatter must be a mapping, got {type(data).__name__}", path))
    return data


def _walk_node(node, where: str, path: str, parent_key: str | None, opaque: bool) -> None:
    if isinstance(node, yaml.MappingNode):
        if node.tag not in _STANDARD_COLLECTION_TAGS:
            _fail(path, E_CANON_TAG, f"custom tag {node.tag!r} is rejected", where)
        if node.flow_style and node.value:
            _fail(path, E_CANON_FLOW, "flow-style mappings are rejected (block style only)", where)
        identity_keyed = not opaque and parent_key in _IDENTITY_KEYED_MAPS
        seen: set[str] = set()
        for key_node, value_node in node.value:
            if not isinstance(key_node, yaml.ScalarNode):
                _fail(path, E_CANON_KEY, "mapping keys must be scalar field names", where)
            if key_node.tag == _MERGE_TAG:
                _fail(path, E_CANON_TAG, "merge keys are rejected", where)
            if key_node.tag != "tag:yaml.org,2002:str":
                _fail(path, E_CANON_KEY, f"mapping key {key_node.value!r} has non-string tag", where)
            if identity_keyed:
                if key_node.style not in ("'", '"'):
                    _fail(path, E_CANON_QUOTE, f"identity key {key_node.value!r} must be a quoted string", where)
            elif not opaque and key_node.style is not None:
                _fail(path, E_CANON_KEY, f"mapping key {key_node.value!r} must be plain style", where)
            key = key_node.value
            if key in seen:
                _fail(path, E_CANON_DUPKEY, f"duplicate key {key!r}", where)
            seen.add(key)
            child_where = f"{where}.{key}" if where else key
            child_parent_key = "neighbours" if parent_key == "neighbours" else key
            _walk_node(value_node, child_where, path, parent_key=child_parent_key, opaque=opaque or key == "args")
        return
    if isinstance(node, yaml.SequenceNode):
        if node.tag not in _STANDARD_COLLECTION_TAGS:
            _fail(path, E_CANON_TAG, f"custom tag {node.tag!r} is rejected", where)
        if node.flow_style and node.value:
            _fail(path, E_CANON_FLOW, "flow-style sequences are rejected (block style only)", where)
        for i, item in enumerate(node.value):
            _walk_node(item, f"{where}[{i}]", path, parent_key=parent_key, opaque=opaque)
        return
    if isinstance(node, yaml.ScalarNode):
        if node.tag not in _STANDARD_SCALAR_TAGS:
            _fail(path, E_CANON_TAG, f"custom tag {node.tag!r} is rejected", where)
        if opaque:
            return
        if parent_key == "value" and where.endswith("expect.value"):
            if node.tag == "tag:yaml.org,2002:str" and node.style not in ("'", '"'):
                _fail(path, E_CANON_QUOTE, f"value of {parent_key!r} must contain quoted strings", where)
        elif parent_key in _QUOTED_VALUE_KEYS:
            if node.tag != "tag:yaml.org,2002:null" and node.style not in ("'", '"'):
                _fail(path, E_CANON_QUOTE, f"value of {parent_key!r} must be a quoted string or null", where)
        return
    _fail(path, E_CANON_TAG, f"unsupported node type {type(node).__name__}", where)


def _fail(path: str, code: str, message: str, where: str) -> None:
    raise CheckFailure(Diag("error", code, f"{message} (at {where})", path))
