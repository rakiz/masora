# union.py — the conflicted deleted.toml row-union rescue

Role: `masora union <base-dir>` resolves the ONE git merge conflict Masora
bases actually hit: two concurrent gc/compact PRs both APPEND rows to
`deleted.toml` (FORMAT.md §7.10), and git cannot union-merge TOML — after a
conflicted pull/rebase the file carries conflict markers.

## Contract

- Input: a `deleted.toml` WITH conflict markers; anything else is
  `E-UNION-NO-MARKERS` (a clean file must go through git's own resolution,
  not a union invented here).
- Parse both sides (common lines + the ours/theirs blocks of every conflict),
  union `[[deleted]]` rows keyed by LINEAGE and `[[deleted_events]]` rows
  keyed by EVENT ULID — ours first, theirs appended only where the key is
  unseen. Same-lineage `[[deleted]]` rows merge their ulid lists (both
  sides' tombstones survive).
- Fail-closed: a malformed row on EITHER side is `E-UNION-ROW` — a tombstone
  row is never silently dropped. The merged file replaces the original ONLY
  when the post-union `check_base` passes (validated on a throwaway copy of
  the tree; the publish is a sibling temp file + `os.replace`, the M10
  pattern) — `E-UNION-CHECK` otherwise, the conflicted file untouched.
- NEVER runs git: no commit, no stage — the caller reviews and commits the
  merged file. CI stays read-only (masora/templates/masora-check.yml's
  comment documents the maintainer-side rescue flow).

## Invariants

- Every tombstone row of both sides appears in the merged file exactly once
  (dedup by natural key), or the command refuses.
- Order preservation: ours rows keep their relative order, theirs interleave
  only at unseen keys.
