# Architecture

How the code implements the FORMAT.md contract. Section references are to
FORMAT.md unless stated otherwise. Data flow: event files on disk →
canonicalization + schema → cross-file validation + fold → status envelopes
(`check`), or → append-only diff + merged-result validation → one branch and
one PR (`sync`), or → full rebuild of the SQLite index + §6.2 status tuples +
FTS (`index`, searched by `search`).

## Event files and layout (§1)

- A base is a git repo: `YYYY-MM/<slug>-<lineage-ULID>/<ULID>.<kind>.md`
  (the slug is an optional immutable label derived from the founder's summary
  by `write.slugify_summary` — case-boundary split, ≤ 30 chars, `lineage`
  fallback; hand-made trees may use the bare `<lineage-ULID>/` form), plus
  `base.toml` (identity — the one path rule: a root without it is not a base,
  `E-NOT-A-BASE`) and optional `deleted.toml` (tombstone).
- The layout is a collision-avoidance convention only — validation is
  content-based. `checker.py` globs `**/*.md` (skipping `.git`); moving files
  changes nothing. One lineage, one directory: the write path
  (`write.event_relpath`) looks an existing lineage up by ULID suffix and
  joins it; only a founder creates a directory (in its own month).
- Event identity is the ULID (`id` == filename ULID); files are append-only,
  never modified after creation. Whole-lineage deletion is `masora gc`'s job,
  per-event dropping is `masora compact`'s (see the GC and Compact sections
  below).

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
  provider_version}` with the `cppgraph.` tool prefix (`E-PROOFQUERY`), and
  the unified provenance rules — `source` (`human`/`llm`/`graph`) on every
  kind, optional `name`, optional `effort` only when `source: llm`
  (`E-PROVENANCE`).
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
  Verification shown = newest active verify targeting `displayed` (the
  `source`s of all active verifies are kept); `doubted` = some active doubt
  targets an active verify of `displayed`.
- Status precedence (MASORA_DESIGN.md §6.2): `none` > `unknown` > `current`/`restored` >
  `stale`. Standalone check has no provider, so any lineage with active
  versions reports `unknown` — never a silent `current`.
- The fold rule is proven by an executable spec: `tests/test_fold_bruteforce.py`
  brute-forces all event-graph DAGs at n ≤ 4 against an independent
  topological oracle, plus sampled n = 5 DAGs, across several evaluation
  orders.

## The checker (`masora/checker.py`)

`check_base()` validates the whole tree in one pass, in this order:

0. **Base gate**: `base.toml` must exist at the passed root (`E-NOT-A-BASE`)
   — a directory that is not a base refuses up front instead of walking the
   tree into confusing stray-file errors; the gate covers every consumer
   (the CLI commands, the write-path pre/post checks, the compact/gc gates).
   The CLI dispatch for `check`/`sync`/`gc`/`compact`/`index`/`search` runs
   one pre-flight base gate before any work: an omitted `base_dir` resolves
   the base in order — the hinted directory itself when it is a base
   (`base.toml` at its root: the cwd for `check`/`sync`/`gc`/`compact`,
   `--repo` for `index`/`search`/`explain`), then the checkout's masora
   configuration (the `write.auto_base`
   chain — mappings on the normalized `origin` remote, then `default_base`,
   the same resolution the MCP tools perform) — and the command proceeds with
   the resolved directory, while a passed non-base root is refused with the
   smart remedy — the base configured for the current repo's `origin`
   remote, when one resolves (it never auto-corrects, exit 1 stands). For
   `sync` the gate precedes any diff or mutation: a refused run mutates
   nothing.
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

The base directory is resolved (or refused, `E-NOT-A-BASE`) by the CLI's
pre-flight base gate — before this pipeline, before any diff or mutation: a
refused sync mutates nothing.

Pipeline (each step's failures abort with exit 1):

1. **Local check gate**: `check_base()`; errors block, warnings ride along.
2. **Git preconditions**: base dir must be the repository root, `origin`
   remote must exist, fetch, `origin/main` and the merge-base with HEAD
   (`E-GIT`, `E-NO-ORIGIN`, `E-MERGE-BASE`).
3. **Content diff by event id** against the merge-base and `origin/main`
   (§7.9): added / unchanged / rewritten / deleted. Identity is content —
   moves are invisible, squash-merges are harmless.
4. **Tampering**: a rewrite or partial deletion of a known id is
   `E-REWRITE`; a whole-lineage deletion is tampering unless the lineage is
   tombstoned in the local `deleted.toml` (`E-GC-UNAVAILABLE`) — tombstoned
   deletions are `masora gc`'s output and are accepted. A per-event deletion
   whose `(lineage, id)` pair appears in the local `[[deleted_events]]` table
   is `masora compact`'s output and is accepted the same way.
5. **Tombstone**: the local `deleted.toml` must be a content-superset of the
   merge-base's (`E-TOMBSTONE-SHRINK`).
6. **Founder rule**: every added v2+ claim needs its founder in
   `origin/main` or in the pending diff (`E-FOUNDER`, self-contained
   lineages, §7.8).
7. **Merged-result validation**: `origin/main` tree + local overlay +
   **union tombstone** re-validated with `check_base()` — this surfaces
   gc-vs-extension races (a PR extending a lineage another PR deleted)
   before publication, not just the PR diff (§7.10). Accepted gc deletions
   are applied to the merged tree: the tombstoned lineages' event files are
   removed from the origin side before validation.
8. **Publication**: one plumbing commit (merged tree, parent = `origin/main`)
   on `masora/pending`, pushed `--force-with-lease`; PR opened or updated via
   `gh`, or the compare URL printed. Idempotent: when the branch already
   carries the pending set, nothing is pushed.

Between the diff (step 3) and the tampering checks (step 4), the pending CLAIM
events run through the stacking audit (`masora/audit.py`, MASORA_DESIGN.md
§12): conservative heuristics — statement length, anchor count, anchors
spanning several files — decide nothing locally, only publication. Each
flagged lineage is named with its fired signals; `sync` refuses
(`E-SYNC-STACKED`) with the split remedy — split into one atomic note per
fact, remove the unpublished block claim with `masora gc --lineage <id>`
(never published — no tombstone), re-run sync —, mutating nothing.
`--allow-stacked` is the explicit human override: the refusal becomes a
per-lineage `W-SYNC-STACKED` warning riding the PR body and the flow
continues.

Without `--yes` the run is a PLAN: the pipeline executes through merged-result
validation (no step writes anything) and the pending set is printed in the PR
body's rendering — one line per event, the tombstone line, the warnings — then
sync exits 3: no branch, no push, no PR, no local ref mutation. `--yes`
publishes; it is the single confirmation gate of every mutating mode, like
gc's and compact's.

- `--push` (solo base): pushes the merged commit straight to `origin/main`
  and advances the local `main` — a mode selector, not a confirmation:
  `--push --yes` publishes, `--push` alone plans the push.
- `--drop --yes`: closes the PR (`gh` when available), deletes
  `masora/pending` locally and remotely; the local `.md` files of dropped
  events stay on disk. `--drop` without `--yes` only plans the discard
  (exit 3, nothing touched).
- Exit codes: 3 plan printed (nothing written), 0 synced (the "no pending
  events" path keeps exit 0 in plan mode too), 1 errors, 2 synced with
  warnings.

## GC (`masora/gc.py`, §7.9–§7.10, SPEC.md Goals)

`masora gc <base-dir> --lineage <ulid>[…] [--yes]` deletes whole lineages on
explicit, confirmed request; it never suggests candidates (a fully-refuted
lineage is negative knowledge). Sequencing:

1. `--lineage` values must be well-formed ULIDs (`E-GC-ULID`), deduplicated.
2. **Pre-check**: `check_base()`; errors block (schema, tombstone shape, …)
   and nothing is mutated.
3. **Plan**: the lineage's event files (content-scanned — location plays no
   role), its fold status — a lineage with active (non-refuted) versions is
   deleted with `W-GC-ACTIVE` — and already-tombstoned requests as no-ops.
   Published-ness splits the plan: a lineage is PUBLISHED when at least one of
   its event files is in origin/main's tree (one read-only `ls-tree` of
   `refs/remotes/origin/main`; missing origin/main or no origin ⇒ everything
   is unpublished, a git failure is an `E-GIT` error — never a silent guess);
   an UNPUBLISHED lineage is labeled "unpublished — removed locally, no
   tombstone (origin/main never saw it)". Without `--yes` the plan is printed
   and gc exits 3 without writing anything.
4. **Mutation**: one `[[deleted]]` block per published lineage (`ulids` =
   every event ULID of the lineage) is appended to `deleted.toml`
   (append-only by content, §7.10); unpublished lineages' event files are
   unlinked with NO tombstone rows — the ledger records only what the shared
   repo knew. All lineages' event files are unlinked and emptied parent
   directories pruned. gc commits nothing — the deletion is an
   ordinary git commit left to the user, or travels through `masora sync`
   like any pending change.
5. **Post-check**: `check_base()` again; a failure is `E-GC-CHECK` (exit 1).
   Exit 0 deleted, 2 deleted with warnings.

## Compact (`masora/compact.py`, §6, §7.10, MASORA_DESIGN.md §6.2)

`masora compact <base-dir> [--yes]` compresses every lineage to its minimal
live witness set — the event files still contributing to the lineage's
current §6 fold state — dropping pure history (superseded versions, undone
events, inactive verifies) while losing nothing observable. Surviving files
keep their ULIDs and are untouched byte-for-byte, so merges and dedup by id
keep working. Sequencing:

1. **Pre-check**: `check_base()`; errors block and nothing is mutated.
2. **Witness selection** (`select_witness`, pure over fold events): per
   lineage it keeps the founding claim (every eligible version's resolution
   hangs on it), the effective version (the newest active eligible version;
   the newest eligible version when every version is refuted —
   `resolution: none`; the newest existing version when the lineage is
   founderless), every active verify of the effective version (their
   `source`s feed the envelope), every active doubt on a kept verify, every
   active refute of a version when `resolution: none`, and the newest
   version — whose active refutations sustain `restored` — when restored.
   The set is closed over `targets`/`contradicts` (a kept event's references
   must resolve) and over the active refute/unrefute/undoubt events
   targeting kept events (a kept event's activity must not flip); everything
   else is dropped. Correctness over compression: any ambiguity keeps.
3. **The proof**: per lineage, `observable_state(fold_full) ==
   observable_state(fold_witness)` — displayed, restored, resolution,
   verification fields, sources, doubted and the activity state of every
   surviving version. Any divergence refuses the whole run fail-closed with
   `E-COMPACT-DIVERGE` (exit 1, nothing written). The rule is exercised by
   the brute-force suite: every acyclic event DAG at n ≤ 4 exhaustively plus
   sampled n = 5 DAGs must fold identically before and after witness
   selection, and every fixture tree must compact with an unchanged per-lineage
   status (`tests/test_compact.py`).
4. **Tombstones**: an event is tombstoned only if the shared repo knows it —
   its ULID exists on `origin/main` or on the sync merge-base (the same git
   plumbing as sync's diff, no fetch; no remote/merge-base → no tombstones
   at all). Known dropped events land in `deleted.toml`'s `[[deleted_events]]`
   table (`{lineage, ulids}` blocks like gc's, append-only by content,
   union-merged by sync); the lineage itself stays alive, so `check` rejects
   re-added event ids only. Unpublished events (uncommitted or
   committed-but-unpushed, as of the last fetch) are deleted silently —
   nobody ever saw them.
5. **Plan/confirm**: without `--yes` the plan (per-lineage kept/dropped with
   the unpublished count, tombstone total, files before → after, and — with
   `--rehome` — the planned moves) is printed and compact exits 3 without
   writing.
6. **Mutation**: dropped event files are unlinked and emptied parent
   directories pruned (gc's helper); with `--rehome` the surviving files move
   into their canonical homes (below). compact commits nothing — an ordinary
   git commit, or `masora sync` like any pending change.
7. **Post-check**: `check_base()` again — a failure is `E-COMPACT-CHECK` —
   plus a tree-wide re-verification that every surviving lineage's status
   envelope is unchanged (a change is `E-COMPACT-DIVERGE`); both advise
   `git restore` (exit 1). Exit 0 compacted, 2 compacted with warnings.

**`--rehome` (layout migration, FORMAT.md §1)**: moves the surviving files of
every lineage into its canonical single home `YYYY-MM/<slug>-<lineage>` —
the directory holding the founder file (`<lineage>.claim.md`), renamed to
`<slug>-<lineage>` when it is still the bare `<lineage>` form (the slug is
`write.slugify_summary(founder summary)` — never empty), while a directory
that already carries a slug keeps it
verbatim — the slug is an immutable label. Every surviving file of the
lineage living in another month bucket (the pre-`event_relpath` write rule)
moves into that home and the vacated directories are pruned; the fold-proof
machinery does not apply to a pure rehome (no event is dropped, and `check`
is content-based — moves cannot change it — the post-check asserts anyway).
A rehome-only run writes no tombstones: files move, nothing is deleted; a
run that also drops events tombstones the drops per the rules above while
the survivors land in the canonical home. A lineage with no surviving
founder (founderless) has no canonical home to derive and is left untouched.
Already-canonical lineages are untouched, so a second run is a no-op.

Compact folds standalone (no anchor provider, like `check`): the effective
version is the newest active one. An index built with a fingerprint-matching
OLDER version may display that older version; its verifies of
non-displayed versions are dropped, so re-index after compacting a base
whose lineages resolve to older versions.

## Explain (`masora/explain.py`, §6, FORMAT.md §5)

`masora explain <base-dir> <lineage-id> [--repo <path>]` and the `explain`
MCP tool render the complete story of ONE lineage, statuses included — the
canonical door that replaced the improvised rg-over-raw-files (raw event
files carry no status, so a refuted/doubted claim read as valid). The state
is computed FRESH from the lineage's event files (checker's discovery/parse
helpers — content-based; the index is never consulted, a stale index cannot
lie here): `check_base()` gates first (E-NOT-A-BASE, other base errors
refuse), then `resolve_lineage`/`fold_lineage` compute the tuple and the
fold with the providers from `--repo`/`repo_root` (no repo → anchor states
report `unknown`, never a guess). The render: the status tuple, the
effective version's summary/statement/questions, the anchors with their
current match state (matched/changed/not_found/unknown), the full event
chain in ULID order (each event one line: id, kind, writer, what it does
via the targets chain, `[refuted]`/`[inactive]` markers) and the ACTIVE
verify's evidence in full. An unknown id is `E-EXPLAIN-UNKNOWN` (a clean
diagnostic naming the lineage-ULID rule). Nothing is written, ever. This
promotes `explain (evidence-chain trace)` out of the TODO's out-of-scope
list — the remaining advanced tools are `unrefute`, `recheck` and `history`.

## Index and resolution (`masora/index.py`, `masora/resolve.py`, MASORA_DESIGN.md §6.2, §5.4, §8)

The index turns the fold into the **computed status tuple** (`resolution`,
`verification`, flags) that standalone `check` can only report as `unknown`,
and adds FTS5 search. Section references are to MASORA_DESIGN.md.

- **Location** — one index per base × code repo (TODO: rebuild triggers):
  `<masora_home>/indexes/<base-slug>/<repo-slug>-<path-hash12>.db`, where the
  hash is sha256 of the resolved repo path; slugs are the canonical
  `masora/config.py:slug()` shared with `setup` (`masora/config.py:indexes_root()`,
  `MASORA_HOME` relocates it like everything else).
- **Full rebuild only** (§8: disposable, git is the single durable store): the
  build writes a fresh DB (WAL mode) next to the target and `os.replace`s it
  in; a corrupt or foreign-schema existing DB is discarded with `W-IDX-CORRUPT`
  on `index` and refused with `E-IDX-CORRUPT` on `search` (read-only surface —
  rebuild instead). Deleting the DB at any time is always safe; `search`
  without one is `E-IDX-NOINDEX`.
- **Gate**: `build_index` runs `check_base()` first — a base with errors is
  refused (the check's own diagnostics are reported); warnings ride along.
- **Resolution** (`masora/resolve.py`, pure): per lineage it reuses
  `fold.resolve_activity` (fixed point before folding) and `fold.fold_lineage`
  (refute/unrefute/doubt rules, founder-absent exclusion, newest-match-wins)
  and assembles the tuple: `resolution` via `apply_precedence`
  (`none` > `unknown` > `current`/`restored` > `stale`), `verification` as
  `verified(<source>)`/`unverified`, flags `suspect`/`doubted`/`pending`/
  `unknown`/`unanchored`. A founderless-only lineage maps to `unknown` (no
  eligible version to display). Unanchored claims skip fingerprint resolution:
  always surfaced, `current`, flagged `unanchored`.
- **Provider registry** (injectable): `Mapping[kind -> callable | None]`; the
  callable is `(kind, identity) -> fingerprint | None` where a missing/None
  registry entry means the provider is **unavailable** (→ `unknown` shadows)
  and a callable returning None means the anchor is **not_found** (it simply
  fails to match → the version is skipped, older versions still match).
  Edge snapshots are a second registry `(kind, identity) -> {edges,
  neighbours} | None` used by `suspect`.
- **Suspect** (§12.4): the displayed version's newest observation (the newest
  active verify's snapshot, else the claim's write-time snapshot) is compared
  per anchor over the union of recorded and current neighbours — own edge-set
  hash or any neighbour hash added/removed/changed ⇒ `suspect`; composes with
  `stale`. A kind with no edge provider never fires suspect (with only the
  `file` provider it never fires); an edge provider answering `None` (symbol
  gone) does.
- **Pending** (§8): events whose id is not in `origin/main`'s tree (content
  identity like sync, via `git ls-tree`) flag their lineage `pending`;
  computed only when `origin/main` resolves.
- **Providers shipped** (`index.py`): the `file` provider — sha256 of the
  whitespace/comment-normalized content of the repo-relative path in the
  `--repo` checkout, so a reformat does not stale claims (§5.2): terminated
  `/* … */` block comments (inline or spanning lines) removed, then blank
  lines and full-line `//`/`#` comments dropped, whitespace runs collapsed; an
  unterminated `/*` is content. Inline `//` is not stripped (`//` occurs in
  URLs/strings mid-line).
- **`code` provider** (`masora/providers.py`): fingerprints code anchors
  against a cppgraph graph store — the newest `<repo>/.cppgraph/*.graph.db`
  (store schema v5: `files`/`symbols`/`edges`/`meta`), opened read-only;
  `--cppgraph <db>` points elsewhere, `--no-cppgraph` forces file-only. The
  anchor identity is the SCIP symbol string recorded per FORMAT.md §4 —
  opaque-but-structured, matched verbatim against `symbols.symbol`. Definition
  fingerprint (§5.4): sha256 of the whitespace/comment-normalized source of
  the definition range `symbols.line`..`symbols.end_line` inclusive
  (0-indexed, read from the `--repo` checkout); a store without body extents
  (`end_line`, #504-built binaries only) hashes the single definition line. An
  unknown symbol or unreadable/escaping definition file is `not_found` (fails
  to match). Edge-set fingerprint (§5.4): sha256 of the sorted distinct callee
  SCIP strings from `calls` edges only. Neighbour snapshot (§12.4): 1-hop
  callers ∪ callees, identity → that neighbour's edge-set hash. **Store
  schema-version gate**: ONLY the exact store schema the reader was learned
  against is accepted — a missing, unparsable, older or newer
  `schema_version` meta row makes the store unavailable (`unknown` shadows +
  `W-IDX-GRAPH` naming the seen version). **Graph
  currency policy (§5.2)**: the store's `meta.source_commit` must equal the
  `--repo` git HEAD, decided once per index build — on mismatch, missing
  commit/HEAD, or an unreadable store, ALL code anchors are unavailable (`unknown` shadows; a warning
  `W-IDX-GRAPH` states why when code anchors exist) — never per-anchor, since
  the registry contract has no per-anchor availability channel (callable None
  = `not_found`) and §5.2 refuses fingerprints from a stale graph wholesale.
  A missing graph store is silent `unknown` (cppgraph is optional, SPEC.md);
  the used graph commit is exposed as `result.graph_commit` and in the index
  meta (`graph_commit`, `graph_db`). The registry feeds both the fingerprint
  registry and the edge-snapshot registry, so `suspect` (§12.4) fires for real
  on call-neighbourhood drift.
- **Schema**: `meta` (schema_version, base_path, repo_path, base_head,
  graph_commit, graph_db, built_at), `lineages` (status-tuple columns),
  `versions` (refuted flag +
  summary/statement per claim version), `anchors` (provider/identity/
  fingerprint per version), FTS5 virtual table `search` (summary + statement;
  unicode61 tokenizer → case/accent-insensitive; lineage/version unindexed) and
  the per-question FTS5 table `questions` (question; version + question_ordinal
  unindexed) — one row per claim question (FORMAT.md §4), and the
  per-keyword FTS5 table `keywords` (keyword; version + keyword_ordinal
  unindexed) — one row per claim keyword (the alternate vocabulary, FORMAT.md
  §4), so the matched question/keyword text can be surfaced. Schema version 4
  (a foreign-version DB is
  refused with `E-IDX-CORRUPT` and `masora index` rebuilds — the index is
  disposable; bases without questions/keywords rebuild cleanly).
  Tombstoned lineages (and tombstoned event ids) are excluded.
- **Search union**: `search_index` runs the content MATCH (summary +
  statement only — questions/keywords never dilute it) plus the questions
  and keywords MATCHes, and unions the hits by version; each `SearchHit`
  carries `matched_questions` and `matched_keywords` (the distinct matched
  texts, ordinal order) — a question/keyword-only hit surfaces its version's
   content row; the CLI and MCP `search` render a `matched question:` /
   `matched keyword:` line per match and every hit group ends with
   `details: masora explain <lineage>` (the door to the full story). The
   `*` query is the match-all sentinel: it bypasses FTS and returns one hit
   per indexed lineage — its displayed version (its newest version when none
   is displayed) — with empty matched questions/keywords. `masora
   facts` is untouched: the contract version stays 1 and the JSON shape
   carries no questions/keywords.
- **Rebuild trigger awareness**: the build stores the base's git HEAD plus
  the code state it fingerprinted (`repo_head`, `graph_commit` in meta) and
  the build moment (`built_at`, UTC ISO); `index_stale()` compares four axes
  at read time — base HEAD, the `--repo` HEAD, the discovered graph store's
  indexed commit (unknown sides skipped, pre-provider index rows never warn),
  and filesystem freshness: the newest mtime across the base tree's event
  files and `deleted.toml` against `built_at` (~2 s tolerance) — which is
  what catches UNCOMMITTED `note` writes that move no git HEAD (an index can
  otherwise stay frozen while `masora facts`/`search` silently miss the
  just-written claim). `search` (CLI and MCP) renders the axis's reason in
  `W-IDX-STALE`; one walk of the base tree per read, no caching.
- **CLI**: `masora index <base-dir> [--repo <path>] [--cppgraph <db>]
  [--no-cppgraph]` prints the graph store used, counts by status;
  `masora search [<base-dir>] <query> [--repo <path>]` runs FTS and renders
  `lineage [resolution verification flags]` + matched versions (MCP tools come
   later). When `base_dir` is omitted the base is resolved by the shared
   gate's order — the hinted directory itself when it holds `base.toml`
   (`--repo`, else the cwd), then like `masora facts` (mappings on the
   normalized origin remote, then `default_base`); an
   unresolvable checkout refuses with `E-NOT-A-BASE` and the cause-specific
   remedy — the same pre-flight gate every base-taking CLI command runs.
  Exit codes: index
  0/2 warnings/1 errors; search 0 (results or no match) / 1 (no or unusable
  index) / 2 (invalid query syntax, `E-IDX-QUERY`).

## Setup and user configuration (`masora/setup.py`, `masora/config.py`, MASORA_DESIGN.md §9)

`masora setup --base <url>[#<path>]` onboards a base in one command:

1. Parse the spec: `#<path>` marks a base living in a sub-directory of a
   shared repo; the fragment must be a relative path inside the repo
   (`E-SETUP-ARG`). The base name (`[bases.<name>]` key) is derived from the
   remote's last path segment, sanitized to `[a-z0-9_-]`.
2. Clone into `~/.local/share/masora/bases/<name>` — never inside a code
   repo — with a partial clone
   (`git clone --filter=blob:none --sparse`), then, when a path is given,
   `git -C <dest> sparse-checkout set <path>` (the base directory is the
   sparse-checkout root), otherwise the sparse restriction is lifted
   (`sparse-checkout disable`) so the whole event tree is checked out. An existing clone of the same remote (compared
   after normalization) is reused, making a re-run idempotent
   (`E-SETUP-CLONE`, `E-SETUP-DUPLICATE`). Every git spawn goes through
   `masora.sync.git_env()` — no inherited repo-location `GIT_*` variables.
3. Read the base's self-description, `base.toml` at the base directory's
   root (`E-SETUP-NO-TOML`):

   ```toml
   name = "Team Query"                     # display name, non-empty string
   code_remotes = ["github.com/org/repo"]  # git remotes this base serves
   ```

   Both keys are mandatory and no other key is accepted (`E-SETUP-SCHEMA`).
4. Write `~/.config/masora/config.toml` (`E-SETUP-WRITE`) or merge into it:
   the `[bases.<name>]` entry `{remote, path?, branch}` (`branch` read from
   the clone's HEAD) plus one `[[mappings]]` block per `code_remotes` entry,
   `code_remote` stored in normalized form. Remotes are matched after
   normalization (`masora.config.normalize_remote`: lowercase host, no
   scheme, no user/port prefix, no trailing `.git`). Existing entries,
   mappings and unknown keys are preserved; a merge adds the new name to the
   mapping's `bases` list. Re-running against the same remote (normalized
   equality) updates the entry in place; the same name with a different
   remote is refused (`E-SETUP-DUPLICATE`). The writer re-emits the parsed
   TOML:
   comments in a hand-edited config are not preserved, and a value the
   writer cannot serialize (e.g. a TOML date) is `E-SETUP-CONFIG`.
5. `MASORA_HOME` relocates everything for special cases
   (`$MASORA_HOME/config.toml`, `$MASORA_HOME/bases/<name>`); unset, the
   default paths above apply.

## Init (`masora/init.py`, MASORA_DESIGN.md §9)

`masora init [<base-dir>|--here] --name <name> [--code-remote <url>]… [--force]`
creates a new base locally in one command: a self-contained git repo whose
`main` is ready to hold the event tree. Target refusals (`E-INIT-TARGET`): the path exists as a
file, is non-empty without `--force`, or already holds `base.toml` — an
existing base is never overwritten, `--force` or not. It writes `base.toml`
in exactly the shape `setup` reads (`name` + `code_remotes`, each
`--code-remote` stored normalized via `config.normalize_remote` and
deduplicated, `E-INIT-ARG` when a value does not look like a git remote),
gates the fresh tree through `check_base()` before anything is committed
(`E-INIT-CHECK` — a forced directory must not hold stray event files or a
`deleted.toml`), then runs `git init -b main` + first commit
("masora init: base <name>"); `E-INIT-GIT` surfaces git failures cleanly
(most often a missing git identity). Every git spawn goes through
`sync.git_env()`. It prints the exact next command,
`masora setup --base <path>`, plus one line of framing: init works locally;
publishing the base to a shared repo is the user's git work, and
`masora setup --base <url>` is the onboarding step once the URL exists.
Slug interplay: none — lineage directories come from writes (FORMAT.md §1).

## MCP server and write path (`masora/mcp.py`, `masora/write.py`, MASORA_DESIGN.md §10.4, §13)

`masora mcp` runs a **hand-rolled minimal MCP server** over stdio — no SDK, no
new runtime dependency (MASORA_DESIGN.md §12.9). Transport: newline-delimited
JSON-RPC 2.0 (one message per line in, one response line out), stdin/stdout,
nothing else on the stream; protocol anomalies go to stderr as `W-MCP-PROTO`.
Protocol version is pinned to `2025-06-18`, negotiated the standard MCP way:
the `initialize` result always carries it (a client advertising another
version decides whether to keep talking to it); malformed `initialize` params
are `-32602`.
The method surface is exactly `initialize`, `notifications/initialized`,
`tools/list` and `tools/call` — no resources/prompts/sampling. Error mapping:
malformed JSON → `-32700` (id `null`) and the loop **continues**; a parseable
non-request → `-32600`; unknown method → `-32601`; unknown tool / bad
`arguments` → `-32602`; an unexpected tool crash → `-32603` (the server
survives). Tool-level failures are MCP tool results with `isError: true` and
the diagnostic code in the text — never protocol crashes.

Tools (all results are terse deterministic text; the client passes repo
context per call — the server does no repo discovery):

| Tool | Params | Behaviour |
|---|---|---|
| `note` | `statement`, `summary`, `repo_root`; optional `base`, `anchors[]`, `unanchored`, `unanchored_reason`, `class`, `proof_query`, `source` (`human`\|`llm` — `graph` is not writable via MCP), `name`, `effort` (llm only), `cost_tokens` | Writes the lineage's v1 claim. Anchor refs resolve via the graph provider (exact SCIP match, else case-insensitive substring; `ambiguous`/`not_found` → `E-MCP-ANCHOR`, nothing written — FORMAT.md §6). Fingerprints + snapshots are recorded at write time (`providers.py`); a graph behind HEAD or absent → `E-MCP-GRAPH` (§5.2). Without anchors only an explicit `unanchored: true` + reason writes. `source: human` self-signs `name` from the base repo's `git config user.name` (absent when unset); llm takes `name`/`effort` from the tool params; effort on a non-llm source → `E-PROVENANCE`. |
| `verify` | `id`, `evidence[]`, `repo_root`; optional `base`, `source`, `name`, `effort` | Targets the claim version (a lineage id rides the fold to its displayed version; unknown → `E-MCP-UNKNOWN-ID`). Re-fingerprints the claim's immutable anchor set at verify time — drift → `E-MCP-DRIFT` ("write a new claim version", §6.3); records fresh per-anchor snapshots and `verified_at {commit, graph_commit}`. |
| `doubt` | `id`, `reason`, `repo_root`; optional `base`, `source`, `evidence[]`, `name`, `effort` | Targets a `.verify` ULID, or a lineage → the active verify of its displayed version; none → `E-MCP-UNKNOWN-ID`. |
| `undoubt` | same params as `doubt` | Targets the doubt event's ULID only (no lineage form). |
| `refute` | same params as `doubt` | Targets any event ULID, or a lineage → its displayed version. |
| `search` | `query`; optional `base`, `repo_root` | FTS over the index (auto-**built when missing**, never rebuilt when merely stale — the SessionStart hook owns freshness); `W-IDX-STALE` is surfaced in the result text; statuses rendered per lineage. |
| `list_stale` | optional `base`, `repo_root` | Lineages whose resolution is not `current`/`none` (stale, restored, unknown), as `lineage [resolution verification flags] displayed: summary head`. |

The write path (`masora/write.py`) is shared by all five write tools:
`resolve_base()` honours an explicit `base` parameter first (a caller-provided
base always wins), then matches the code repo's `origin` remote (normalized via
`config.normalize_remote`) against the user config's `[[mappings]]`, then
`default_base` — otherwise `E-MCP-NO-BASE` refuses with the remedy for its
cause: an omitted `repo_root` is told to pass the repo (the base resolves from
that repo's origin remote), an unmapped repo is told to run
`masora setup --base <url>` in the checkout or pass an explicit `base` (§9: it
never guesses); ULIDs come from
`ulid.new_ulid()` (monotonic in-process); the event dict is pre-validated with
`schema.validate_event` and secret-scanned — high-confidence credential shapes
in `summary`/`statement`/`reason`/`evidence` are refused with
`E-WRITE-SECRET`, nothing written (discussing passwords passes: naming
fields, short or single-class values) —, then emitted in the canonical block
style (plain keys,
quoted identity/hash values, JSON-style control-char escaping —
`emit_event()`), written to
`<YYYY-MM>/<slug>-<lineage>/<id>.<kind>.md` — extensions join the lineage's
existing directory, founders create it in their month — after a shared
`check_base` pre-check
(nothing is written onto an invalid base), and followed by a full post-write
`check_base` — a post-check failure unlinks the just-written file and reports
the diagnostics, so a tool never returns success on an invalid tree (FORMAT.md
§6 atomicity). Every git spawn goes through `sync.git_env()`; `MASORA_HOME`
relocates config, bases and indexes as everywhere else.

## Facts command (`masora/facts.py`, docs/CPPGRAPH_INTEGRATION.md)

`masora facts --repo <path> [--symbol <scip-string>]` is the Masora side of
the cppgraph injection contract: strictly read-only (no index build, no git
network access), it resolves the base via `write.auto_base()` (mappings on
the normalized `origin` remote, then `default_base` — the same chain the MCP
write tools use, minus the explicit parameter the contract forbids), reads
the existing index and prints ONE compact JSON document (`contract_version`
1) per the contract: `{contract_version, repo_head, graph_commit,
stale_warning, facts[]}` — each fact carrying the status tuple, the
effective version's provenance (`source`, `name`, `effort`) and its full
anchor-identity list (`anchors`) beside `anchors_matched`.
`--symbol` filters to lineages whose **effective**
version anchors on the exact identity — the displayed version, or the newest
when `displayed` is null (`resolution: none` / founderless-unknown, per the
§6 fold) — and fills `anchors_matched`. The two warning classes are in-band
and never errors: `stale_warning` is `index_stale()`'s four-axis drift
comparison (`true`/`false`, `null` when nothing is comparable) and provider
unavailability shows as per-lineage `unknown` flags. Hard failures (no base
`E-FACTS-NO-BASE`, missing index `E-FACTS-NOINDEX`, unusable index
`E-IDX-CORRUPT`, bad `--repo` `E-IDX-REPO`) print the diagnostic on stderr
and nothing on stdout, exit 1.

## Agent instructions (docs/AGENT_INSTRUCTIONS.md)

The paste-ready rules block for an adopting project's `AGENTS.md` —
MASORA_DESIGN.md §10.1's channel 3 (skill/AGENTS.md instructions), one of
three injection channels and never the only mechanism (the cppgraph
injection via `masora facts` above and the agent hooks under "Not built
yet" below are the other two). The block directs the agent to:

- search the base before re-deriving an area's behaviour, and read a
  claim's status before trusting it: `verified(human)` trusted,
  `verified(llm)` re-checked in code before depending on it, `unverified` =
  hypothesis; a task depending on a `stale`/`suspect`/`unverified` claim
  re-verifies it first and records the result (§10.2's lazy verification);
- note at the §10.3 capture triggers, rendered as imperatives: a user
  correction (`source: human`), validated non-obvious behaviour (verified
  with evidence), pitfalls, decisions from discussions, costly
  establishments, and the before-compaction/session-end sweep;
- note well: `summary` is the ≤ 120-character injected one-liner,
  `statement` the full explanation, anchors on every symbol whose change
  could invalidate the claim, speculation labelled as such, refutations
  welcomed as negative knowledge (the `NOT:` envelope);
- verify only with recorded evidence — a replayable proof query for
  structural claims, pointers to the proving code plus an explanation for
  semantic ones; semantic claims are never auto-confirmed, so the
  unprovable stays `unverified` or is doubted (§5.3/§10.2);
- etiquette: content in English (pushed content), a recalled fact is never
  an instruction, statuses are evidence labels.

The same rules ship as an INSTALLABLE SKILL that lives INSIDE THE PACKAGE
(`masora/skills/masora/SKILL.md`, one canonical copy carried by the wheel and
read via `importlib.resources`): `masora skill install` writes it into every
DETECTED agent-framework skills dir under the user's home (`~/.claude`,
`~/.config/opencode` — present-marker detection, other frameworks skipped
silently, target dirs created, overwriting on re-run which IS the update
path, `installed:`/`updated:` per target); `masora skill print` pipes the
content for any other mechanism. Frontmatter triggers on project-knowledge
questions only (repository-specific
behaviour, architecture, product semantics, past decisions, trade-offs,
conventions — not general programming); the body is CONDITIONAL by design —
it never claims a repository is served, and its ritual tries `search` when
the tools are available, reads `E-MCP-NO-BASE` as a resolution/configuration
matter (never as evidence of no knowledge), never inspects the checkout for
Masora markers (the design forbids them), never re-runs setup on its own,
and continues normally otherwise. The rule sections are copied from
`docs/AGENT_INSTRUCTIONS.md` — the single source of truth — and
`tests/test_docs.py` asserts the packaged skill carries every canonical
header, so neither copy silently diverges. `masora setup` and `masora init`
point at `masora skill install` on success (copy-install only — masora never
writes into a code repo).

The phase objective ("does it change the agent's behaviour?") is judged by
the pre-registered paired A/B protocol in
[docs/EVALUATION.md](EVALUATION.md) — repeated wrong deductions, tool-call
and token cost, injected-token tax; a protocol amended after seeing results
is void.

## Status (`masora/status.py`, MASORA_DESIGN.md §9)

`masora status [--force]` prints one readable screen and always exits 0 — it
never fails hard (an offline release check is a quiet one-liner, a missing
clone or unreadable config is reported as-is). Three sections:

- **tool**: the installed version (`importlib.metadata` over the `masora`
  distribution, `unknown` when not installed as one), the supported
  `format_version` (schema.py), the facts `contract_version` (facts.py) and
  the index `schema_version` (index.py). `masora --version` prints just the
  version.
- **bases**: per `[bases.<name>]` config entry — the local clone path
  (`bases_root()/slug(name)`, exists/missing), the clone's `origin` remote
  (git query, falling back to the configured entry), the event file count and
  the `deleted.toml` tombstone-block count (one cheap walk, `.git` skipped),
  and per `*.db` under `indexes_root()/slug(name)`: the repo it was built for
  (stored meta) plus the `index_stale_reason()` four-axis wording, `fresh`
  when nothing drifted, `no index` when no database exists, `unreadable` for
  a DB without usable meta.
- **update check**: the latest release from
  `https://api.github.com/repos/rakiz/masora/releases/latest` (stdlib
  urllib, 2 s timeout), compared against the installed version by numeric
  semver triplet — `up to date`, or `update available: vX.Y.Z — <release url>`
  with the `uv tool install --force git+https://github.com/rakiz/masora`
  hint. The response is cached in `~/.local/share/masora/update-check.json`
  (`$MASORA_HOME` relocates it) for 24 hours — the cache records the
  checked-at instant, the tag and the url — and `--force` refetches now.
  Offline, HTTP and malformed answers print
  `update check unavailable (offline)` and never raise; the fetcher
  (`status.fetch_latest_release`) is an injectable module-level callable so
  the tests stay hermetic.

## Not built yet

All listed in TODO.md — statements below are facts, not plans in code:

- Credential-shaped content rejection at `note`, `SessionStart` hook,
  unrefute/recheck/history MCP tools; the cppgraph side of the injection
  (its wire contract is implemented: `masora facts`, pinned in
  [docs/CPPGRAPH_INTEGRATION.md](CPPGRAPH_INTEGRATION.md)). (The
  MCP write path itself is built: `masora/mcp.py` + `masora/write.py` — the
  code anchor snapshots are recorded at note/verify time.)
