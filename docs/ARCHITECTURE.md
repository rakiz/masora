# Architecture

How the code implements the FORMAT.md contract. Section references are to
FORMAT.md unless stated otherwise. Data flow: event files on disk →
canonicalization + schema → cross-file validation + fold → status envelopes
(`check`), or → append-only diff + merged-result validation → one branch and
one PR (`sync`).

## Event files and layout (§1)

- A base is a git repo: `YYYY-MM/<lineage-ULID>[-slug]/<ULID>.<kind>.md`,
  plus optional `base.toml` (identity) and `deleted.toml` (tombstone).
- The layout is a collision-avoidance convention only — validation is
  content-based. `checker.py` globs `**/*.md` (skipping `.git`); moving files
  changes nothing.
- Event identity is the ULID (`id` == filename ULID); files are append-only,
  never modified after creation. Whole-lineage deletion is `masora gc`'s job
  (not implemented; `sync` rejects such deletions with `E-GC-UNAVAILABLE`).

## Canonicalization and schema (`masora/frontmatter.py`, `masora/schema.py`)

- `frontmatter.py` splits the `---` block and parses it with a custom
  `SafeLoader` that enforces §4 canonicalization at compose time: no
  aliases/anchors (`E-CANON-ALIAS`), no explicit/custom/merge tags
  (`E-CANON-TAG`), no flow style (`E-CANON-FLOW`), no duplicate keys
  (`E-CANON-DUPKEY`), plain scalar keys (`E-CANON-KEY`), quoted values for
  identities/hashes/SHAs/ULIDs and quoted identity keys in `snapshots`/
  `neighbours` (`E-CANON-QUOTE`). `proof_query.args` subtrees are opaque —
  the walk does not look inside them (provider-documented mapping, §4).
- `schema.py` holds per-kind REQUIRED/OPTIONAL/FORBIDDEN field tables and the
  cross-field rules (§4 "Fields per kind", §5): `format_version` must equal 1
  (`E-VERSION`), `unanchored`/`anchors`/`proof_query`/`contradicts`/`reason`
  coupling, summary ≤ 120 single-line chars (`E-SUMMARY`), timestamp shape
  `{commit, graph_commit}` with full 40-hex SHAs (`E-TIMESTAMP`), anchor and
  snapshot shapes (`E-ANCHOR`), proof-query shape `{tool, args, expect,
  provider_version}` with the `cppgraph.` tool prefix (`E-PROOFQUERY`).
- Every violation raises `CheckFailure` carrying a `Diag` (severity, code,
  message, path) from `diagnostics.py`; parsing never returns a partial
  record. `Diag.render()` is the single output format.

## The fold (`masora/fold.py`, §6)

- **Active event**: not the target of any active refute; a refute is active
  unless targeted by an active unrefute; a doubt unless by an active
  undoubt; dangling events (unresolvable `targets`) are inactive.
- `resolve_activity()` iterates events in **descending lexical ULID order**
  to a fixed point. Backward order is what makes refute-of-refute chains
  resolve (§6 example); on the acyclic reference graph the fixed point is
  unique and order-independent. Non-convergence raises `FoldCycleError` —
  `checker.py` rejects cycles (`E-CYCLE`, topological, clock-free) before
  folding, so the fold only ever runs on the acyclic domain.
- `fold_lineage()` runs **per lineage**: eligible versions are the founder
  (`id == lineage`) and versions whose founder resolves; `displayed` is the
  newest active eligible version (fingerprint matching when a provider is
  available — never in standalone check); non-active versions are refuted.
  Verification shown = newest active verify targeting `displayed` (actors of
  all active verifies are kept); `doubted` = some active doubt targets an
  active verify of `displayed`.
- Status precedence (MASORA_DESIGN.md §6.2): `none` > `unknown` > `current`/`restored` >
  `stale`. Standalone check has no provider, so any lineage with active
  versions reports `unknown` — never a silent `current`.
- The fold rule is proven by an executable spec: `tests/test_fold_bruteforce.py`
  brute-forces all event-graph DAGs at n ≤ 4 against an independent
  topological oracle, plus sampled n = 5 DAGs, across several evaluation
  orders.

## The checker (`masora/checker.py`)

`check_base()` validates the whole tree in one pass, in this order:

1. Discover `**/*.md`.
2. Parse each file: filename regex + ULID, frontmatter canonicalization,
   per-kind schema; `id`/`kind` must equal the filename's (`E-FILENAME`).
3. Base-wide `id` uniqueness (`E-DUP-ID`, §7.11).
4. `deleted.toml` shape (`E-TOMBSTONE-SHAPE`) and membership
   (`E-TOMBSTONED`, §7.10).
5. References per event: resolvable `targets`/`contradicts` must match the
   allowed target kind (`E-TARGET-KIND`) and lineage (`E-LINEAGE`); a
   verify's `snapshots` keys must equal the target claim's anchor-identity
   set (`E-ANCHOR`). Unresolvable references are `W-DANGLING` (tolerated
   across PRs); a `targets` ULID greater than the event's `id` is
   `W-SKEW` (§7.5–§7.7).
6. Cycle rejection over resolvable `targets` (`E-CYCLE`, §7.5).
7. `W-REPLAY` when structural claims exist and no provider is wired.
8. Activity fixed point, then per-lineage fold; a v2+ version without a
   founder is warned (`W-FOUNDER`) and excluded from resolution (§7.8).
9. Result: sorted diagnostics + one status envelope per lineage; exit 0
   clean, 1 errors, 2 warnings only.

Standalone `check` does no anchor resolution and no append-only diff — both
need git/provider context and belong to `sync`.

## Sync (`masora/sync.py`, §7.8–§7.10, MASORA_DESIGN.md §8)

Pipeline (each step's failures abort with exit 1):

1. **Local check gate**: `check_base()`; errors block, warnings ride along.
2. **Git preconditions**: base dir must be the repository root, `origin`
   remote must exist, fetch, `origin/main` and the merge-base with HEAD
   (`E-GIT`, `E-NO-ORIGIN`, `E-MERGE-BASE`).
3. **Content diff by event id** against the merge-base and `origin/main`
   (§7.9): added / unchanged / rewritten / deleted. Identity is content —
   moves are invisible, squash-merges are harmless.
4. **Tampering**: a rewrite or partial deletion of a known id is
   `E-REWRITE`; a whole-lineage deletion is `E-GC-UNAVAILABLE` (gc is
   unimplemented).
5. **Tombstone**: the local `deleted.toml` must be a content-superset of the
   merge-base's (`E-TOMBSTONE-SHRINK`).
6. **Founder rule**: every added v2+ claim needs its founder in
   `origin/main` or in the pending diff (`E-FOUNDER`, self-contained
   lineages, §7.8).
7. **Merged-result validation**: `origin/main` tree + local overlay +
   **union tombstone** re-validated with `check_base()` — this surfaces
   gc-vs-extension races (a PR extending a lineage another PR deleted)
   before publication, not just the PR diff (§7.10).
8. **Publication**: one plumbing commit (merged tree, parent = `origin/main`)
   on `masora/pending`, pushed `--force-with-lease`; PR opened or updated via
   `gh`, or the compare URL printed. Idempotent: when the branch already
   carries the pending set, nothing is pushed.

- `--push` (solo base): pushes the merged commit straight to `origin/main`
  and advances the local `main`.
- `--drop`: closes the PR (`gh` when available), deletes `masora/pending`
  locally and remotely; the local `.md` files of dropped events stay on disk.
- Exit codes: 0 synced, 1 errors, 2 synced with warnings.

## Not built yet

All listed in TODO.md — statements below are facts, not plans in code:

- `masora setup --base <url>` and `masora gc --lineage` (deletions are
  currently rejected, see `E-GC-UNAVAILABLE`).
- SQLite index, §6.2 resolution algorithm and FTS — today a base is read as
  plain files; folding cannot compute `current`/`stale` without an anchor
  provider (statuses report `unknown`).
- MCP tools (`note`, `verify`, `doubt`, `undoubt`, `refute`, `search`,
  `list_stale`) — events are written by hand/agent following FORMAT.md §5.
- Code anchor provider via cppgraph, credential-shaped-content rejection,
  `SessionStart` hook, edge-set/neighbour-snapshot capture at write time.
