"""`masora union`: row-union rescue of a CONFLICTED deleted.toml (FORMAT.md §7.10).

Two concurrent gc/compact PRs both append rows to `deleted.toml`; git cannot
union-merge TOML, so after a conflicted pull/rebase the file carries conflict
markers. This command resolves it by ROW UNION: parse both sides of every
conflict block (plus the common lines), union the `[[deleted]]` and
`[[deleted_events]]` rows deduplicating on each row's natural key (the lineage
for `[[deleted]]`, the event ULID for `[[deleted_events]]`), ours first, write
the merged file and re-validate the tree with `check_base`.

Fail-closed everywhere: a tombstone file WITHOUT conflict markers is refused
(nothing to union — the conflict must be resolved by git's own machinery, not
invented here), a malformed or unparseable row on EITHER side is refused
(a tombstone row is never silently dropped), and the merged file replaces the
original only when the post-union `check_base` passes (write to a validated
temp copy, then `os.replace` — the M10 pattern). The command NEVER runs git:
no commit, no stage — the caller reviews and commits the merged file.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .checker import check_base
from .diagnostics import (
    E_UNION_CHECK,
    E_UNION_NO_MARKERS,
    E_UNION_ROW,
    Diag,
)

OURS = "<<<<<<<"
SEP = "======="
THEIRS = ">>>>>>>"

# The tombstone tables this command unions, in the file's canonical order.
TABLES = ("deleted", "deleted_events")


class UnionError(Exception):
    def __init__(self, diag: Diag):
        super().__init__(diag.message)
        self.diag = diag


@dataclass
class Side:
    """One side of the conflict, as ordered tombstone rows per table.

    `deleted` rows are (lineage, [ulids…]) blocks keyed by lineage;
    `deleted_events` rows are (lineage, ulid) pairs keyed by the event ULID —
    a row is never merged away, only deduplicated by its key.
    """

    rows: dict[str, list] = field(default_factory=dict)


def run(base_dir: Path) -> int:
    print(f"masora union {base_dir}")
    if not base_dir.is_dir():
        print(f"masora union: base directory does not exist: {base_dir}", file=sys.stderr)
        return 1
    tombstone = base_dir / "deleted.toml"
    if not tombstone.is_file():
        print(f"  {Diag('error', E_UNION_NO_MARKERS, f'no deleted.toml at {base_dir}').render()}")
        print("FAILED: 1 error(s)")
        return 1
    try:
        raw = tombstone.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"  {Diag('error', E_UNION_ROW, f'deleted.toml cannot be read: {exc}', 'deleted.toml').render()}"
        )
        print("FAILED: 1 error(s)")
        return 1
    try:
        merged = _union(text)
    except UnionError as exc:
        print(f"  {exc.diag.render()}")
        print("FAILED: 1 error(s)")
        return 1
    merged_text, counts = merged

    # Fail-closed publication: the merged content is validated on a throwaway
    # copy of the tree (the conflicted original still in place here), and the
    # real file is replaced only when the check passes — a failed check leaves
    # the conflicted file exactly as git produced it.
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "tree"
        _copy_tree(base_dir, probe)
        (probe / "deleted.toml").write_text(merged_text, encoding="utf-8")
        result = check_base(probe)
    print(
        f"post-union check: scanned {result.file_count} event file(s),"
        f" {result.lineage_count} lineage(s)"
    )
    for diag in result.diags:
        print(f"  {diag.render()}")
    if result.errors:
        print(
            f"  {Diag('error', E_UNION_CHECK, 'the unioned deleted.toml failed masora check — the original conflicted file is untouched', 'deleted.toml').render()}"
        )
        print(f"FAILED: {len(result.errors)} error(s)")
        return 1
    # The atomic publish (M10): a sibling temp file (same filesystem) then
    # os.replace — a concurrent reader never sees a half-written tombstone.
    staging = tombstone.parent / f".deleted.toml.union-{uuid.uuid4().hex[:8]}"
    try:
        staging.write_text(merged_text, encoding="utf-8")
        os.replace(staging, tombstone)
    except OSError as exc:
        staging.unlink(missing_ok=True)
        print(
            f"  {Diag('error', E_UNION_ROW, f'the merged deleted.toml could not be written: {exc}', 'deleted.toml').render()}"
        )
        print("FAILED: 1 error(s)")
        return 1
    print(
        f"unioned deleted.toml: [[deleted]] {counts['deleted']} row(s),"
        f" [[deleted_events]] {counts['deleted_events']} row(s) — review and commit;"
        " masora union never runs git"
    )
    return 0


def _copy_tree(base_dir: Path, dest: Path) -> None:
    """A minimal check_base-compatible copy: event files, base.toml, deleted.toml."""
    dest.mkdir(parents=True)
    for path in sorted(base_dir.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        rel = path.relative_to(base_dir)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _split_conflicts(text: str) -> tuple[str, str]:
    """Split a conflicted document into ours/theirs full texts: every line
    outside a conflict block is common, inside it belongs to its side.
    Raises E-UNION-NO-MARKERS when the document carries no conflict marker at
    all — a clean file has nothing to union and a markerless invocation is
    almost certainly a mistake (the conflict was already resolved, or the
    wrong file was passed)."""
    ours: list[str] = []
    theirs: list[str] = []
    state = "common"
    found = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if state == "common" and stripped.startswith(OURS):
            state = "ours"
            found = True
        elif state == "ours" and stripped.startswith(SEP):
            state = "theirs"
        elif state == "theirs" and stripped.startswith(THEIRS):
            state = "common"
        elif state == "ours":
            ours.append(line)
        elif state == "theirs":
            theirs.append(line)
        else:
            ours.append(line)
            theirs.append(line)
    if not found:
        raise UnionError(
            Diag(
                "error",
                E_UNION_NO_MARKERS,
                "deleted.toml carries no conflict markers — there is nothing to union;"
                " run `masora check` on it instead, or pass the conflicted file left by"
                " a pull/rebase",
                "deleted.toml",
            )
        )
    if state != "common":
        raise UnionError(
            Diag(
                "error",
                E_UNION_ROW,
                "deleted.toml has an unterminated conflict block (a marker without its"
                " closing counterpart) — resolve the block structure first",
                "deleted.toml",
            )
        )
    return "".join(ours), "".join(theirs)


def _parse_side(text: str) -> Side:
    """Parse one side into ordered rows; ANY malformed row is a refusal — a
    tombstone row is never silently dropped (fail-closed, FORMAT.md §7.10)."""
    try:
        parsed = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise UnionError(
            Diag(
                "error",
                E_UNION_ROW,
                f"one side of the conflicted deleted.toml is not valid TOML: {exc}",
                "deleted.toml",
            )
        ) from exc
    side = Side()
    for table in TABLES:
        blocks = parsed.get(table, [])
        if not isinstance(blocks, list) or any(not isinstance(block, dict) for block in blocks):
            raise UnionError(
                Diag(
                    "error",
                    E_UNION_ROW,
                    f"deleted.toml {table} must be a list of [[{table}]] tables",
                    "deleted.toml",
                )
            )
        rows: list = []
        for block in blocks:
            lineage = block.get("lineage")
            ulids = block.get("ulids")
            if (
                not isinstance(lineage, str)
                or not lineage
                or not isinstance(ulids, list)
                or any(not isinstance(ulid, str) or not ulid for ulid in ulids)
            ):
                raise UnionError(
                    Diag(
                        "error",
                        E_UNION_ROW,
                        f"deleted.toml {table} blocks must have {{lineage, ulids}} string values",
                        "deleted.toml",
                    )
                )
            if table == "deleted":
                rows.append((lineage, list(ulids)))
            else:
                rows.extend((lineage, ulid) for ulid in ulids)
        side.rows[table] = rows
    return side


def _dedupe_rows(ours: list, theirs: list, key) -> list:
    """Union with ours-first order: our rows keep their order and win
    deduplication; their rows are appended only where the key is unseen. Two
    `[[deleted]]` rows for the same lineage merge their ulid lists (same
    key, both sides' tombstones survive)."""
    merged: list = []
    seen: set = set()
    for row in ours:
        row_key = key(row)
        if row_key in seen:
            continue
        seen.add(row_key)
        merged.append(row)
    for row in theirs:
        row_key = key(row)
        if row_key in seen:
            continue
        seen.add(row_key)
        merged.append(row)
    return merged


def _union(text: str) -> tuple[str, dict[str, int]]:
    ours_text, theirs_text = _split_conflicts(text)
    ours = _parse_side(ours_text)
    theirs = _parse_side(theirs_text)

    # [[deleted]]: one row per lineage (its natural key) — same lineage on
    # both sides merges the two ulid lists, ours first.
    deleted = _dedupe_rows(ours.rows["deleted"], theirs.rows["deleted"], lambda row: row[0])
    merged_deleted: list[tuple[str, list[str]]] = []
    for lineage, _ulids in deleted:
        ulids: list[str] = []
        for side_rows in (ours.rows["deleted"], theirs.rows["deleted"]):
            for lin, side_ulids in side_rows:
                if lin == lineage:
                    for ulid in side_ulids:
                        if ulid not in ulids:
                            ulids.append(ulid)
        merged_deleted.append((lineage, ulids))

    # [[deleted_events]]: the event ULID is the natural key — per-event rows
    # union with ours-first order, grouped back into per-lineage blocks.
    events = _dedupe_rows(
        ours.rows["deleted_events"], theirs.rows["deleted_events"], lambda row: row[1]
    )
    merged_events: list[tuple[str, list[str]]] = []
    for lineage, ulid in events:
        for block in merged_events:
            if block[0] == lineage:
                block[1].append(ulid)
                break
        else:
            merged_events.append((lineage, [ulid]))

    lines: list[str] = []
    for lineage, ulids in merged_deleted:
        rendered = ", ".join(f'"{ulid}"' for ulid in ulids)
        lines.append(f'[[deleted]]\nlineage = "{lineage}"\nulids = [{rendered}]\n')
    for lineage, ulids in merged_events:
        rendered = ", ".join(f'"{ulid}"' for ulid in ulids)
        lines.append(f'[[deleted_events]]\nlineage = "{lineage}"\nulids = [{rendered}]\n')
    text_out = "\n".join(lines)
    if text_out:
        text_out += "\n"
    counts = {"deleted": len(merged_deleted), "deleted_events": len(merged_events)}
    return text_out, counts
