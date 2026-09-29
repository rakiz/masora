# Architecture

How the code implements the FORMAT.md contract. Section references are to
FORMAT.md unless stated otherwise. Data flow: event files on disk →
canonicalization + schema → cross-file validation + fold → status envelopes
(`check`), or → append-only diff + merged-result validation → one branch and
one PR (`sync`), or → full rebuild of the SQLite index + §6.2 status tuples +
FTS (`index`, searched by `search`).

## Event files and layout (§1)

- A base is a git repo: `YYYY-MM/<lineage-ULID>[-slug]/<ULID>.<kind>.md`,
  plus optional `base.toml` (identity) and `deleted.toml` (tombstone).
- The layout is a collision-avoidance convention only — validation is
  content-based. `checker.py` globs `**/*.md` (skipping `.git`); moving files
  changes nothing.
- Event identity is the ULID (`id` == filename ULID); files are append-only,
  never modified after creation. Whole-lineage deletion is `masora gc`'s job
  (see the GC section below).

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
   `E-REWRITE`; a whole-lineage deletion is tampering unless the lineage is
   tombstoned in the local `deleted.toml` (`E-GC-UNAVAILABLE`) — tombstoned
   deletions are `masora gc`'s output and are accepted.
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

- `--push` (solo base): pushes the merged commit straight to `origin/main`
  and advances the local `main`.
- `--drop`: closes the PR (`gh` when available), deletes `masora/pending`
  locally and remotely; the local `.md` files of dropped events stay on disk.
- Exit codes: 0 synced, 1 errors, 2 synced with warnings.

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
   Without `--yes` the plan is printed and gc exits 3 without writing
   anything.
4. **Mutation**: one `[[deleted]]` block per lineage (`ulids` = every event
   ULID of the lineage) is appended to `deleted.toml` (append-only by
   content, §7.10), the lineage's event files are unlinked and emptied
   parent directories pruned. gc commits nothing — the deletion is an
   ordinary git commit left to the user, or travels through `masora sync`
   like any pending change.
5. **Post-check**: `check_base()` again; a failure is `E-GC-CHECK` (exit 1).
   Exit 0 deleted, 2 deleted with warnings.

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
  `verified(<actor>)`/`unverified`, flags `suspect`/`doubted`/`pending`/
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
  callers ∪ callees, identity → that neighbour's edge-set hash. **Graph
  currency policy (§5.2)**: the store's `meta.source_commit` must equal the
  `--repo` git HEAD, decided once per index build — on mismatch, missing
  commit/HEAD, unreadable store or one newer than the schema this provider
  reads, ALL code anchors are unavailable (`unknown` shadows; a warning
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
  unicode61 tokenizer → case/accent-insensitive; lineage/version unindexed).
  Tombstoned lineages (and tombstoned event ids) are excluded.
- **Rebuild trigger awareness**: the build stores the base's git HEAD plus
  the code state it fingerprinted (`repo_head`, `graph_commit` in meta);
  `index_stale()` compares all three at search time — base HEAD, the
  `--repo` HEAD and the discovered graph store's indexed commit (unknown
  sides skipped, pre-provider index rows never warn) — and `search` prints
  `W-IDX-STALE` when any drifted (statuses may be outdated — rebuild).
- **CLI**: `masora index <base-dir> [--repo <path>] [--cppgraph <db>]
  [--no-cppgraph]` prints the graph store used, counts by status;
  `masora search <base-dir> <query> [--repo <path>]` runs FTS and renders
  `lineage [resolution verification flags]` + matched versions (MCP tools come
  later). Exit codes: index 0/2 warnings/1 errors; search 0 (results or no
  match) / 1 (no or unusable index) / 2 (invalid query syntax, `E-IDX-QUERY`).

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
   mappings and unknown keys are preserved; a mapping's `bases` list gains
   the new name. Re-running against the same remote (normalized equality)
   updates the entry in place; the same name with a different remote is
   refused (`E-SETUP-DUPLICATE`). The writer re-emits the parsed TOML:
   comments in a hand-edited config are not preserved, and a value the
   writer cannot serialize (e.g. a TOML date) is `E-SETUP-CONFIG`.
5. `MASORA_HOME` relocates everything for special cases
   (`$MASORA_HOME/config.toml`, `$MASORA_HOME/bases/<name>`); unset, the
   default paths above apply.

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
| `note` | `statement`, `summary`, `repo_root`; optional `base`, `anchors[]`, `unanchored`, `unanchored_reason`, `class`, `proof_query`, `source`, `model`, `cost_tokens` | Writes the lineage's v1 claim. Anchor refs resolve via the graph provider (exact SCIP match, else case-insensitive substring; `ambiguous`/`not_found` → `E-MCP-ANCHOR`, nothing written — FORMAT.md §6). Fingerprints + snapshots are recorded at write time (`providers.py`); a graph behind HEAD or absent → `E-MCP-GRAPH` (§5.2). Without anchors only an explicit `unanchored: true` + reason writes. |
| `verify` | `id`, `evidence[]`, `repo_root`; optional `base`, `actor`, `model` | Targets the claim version (a lineage id rides the fold to its displayed version; unknown → `E-MCP-UNKNOWN-ID`). Re-fingerprints the claim's immutable anchor set at verify time — drift → `E-MCP-DRIFT` ("write a new claim version", §6.3); records fresh per-anchor snapshots and `verified_at {commit, graph_commit}`. |
| `doubt` | `id`, `reason`, `repo_root`; optional `base`, `source`, `evidence[]`, `model` | Targets a `.verify` ULID, or a lineage → the active verify of its displayed version; none → `E-MCP-UNKNOWN-ID`. |
| `undoubt` | same params as `doubt` | Targets the doubt event's ULID only (no lineage form). |
| `refute` | same params as `doubt` | Targets any event ULID, or a lineage → its displayed version. |
| `search` | `query`; optional `base`, `repo_root` | FTS over the index (auto-**built when missing**, never rebuilt when merely stale — the SessionStart hook owns freshness); `W-IDX-STALE` is surfaced in the result text; statuses rendered per lineage. |
| `list_stale` | optional `base`, `repo_root` | Lineages whose resolution is not `current`/`none` (stale, restored, unknown), as `lineage [resolution verification flags] displayed: summary head`. |

The write path (`masora/write.py`) is shared by all five write tools:
`resolve_base()` honours an explicit `base` parameter first (a caller-provided
base always wins), then matches the code repo's `origin` remote (normalized via
`config.normalize_remote`) against the user config's `[[mappings]]`, then
`default_base` — otherwise `E-MCP-NO-BASE` asks for an explicit base (§9: it
never guesses); ULIDs come from
`ulid.new_ulid()` (monotonic in-process); the event dict is pre-validated with
`schema.validate_event`, emitted in the canonical block style (plain keys,
quoted identity/hash values, JSON-style control-char escaping —
`emit_event()`), written to
`<YYYY-MM>/<lineage>/<id>.<kind>.md` after a shared `check_base` pre-check
(nothing is written onto an invalid base), and followed by a full post-write
`check_base` — a post-check failure unlinks the just-written file and reports
the diagnostics, so a tool never returns success on an invalid tree (FORMAT.md
§6 atomicity). Every git spawn goes through `sync.git_env()`; `MASORA_HOME`
relocates config, bases and indexes as everywhere else.

## Not built yet

All listed in TODO.md — statements below are facts, not plans in code:

- Credential-shaped content rejection at `note`, `SessionStart` hook,
  unrefute/recheck/history MCP tools; injection of facts into cppgraph
  responses — its wire contract is pinned in
  [docs/CPPGRAPH_INTEGRATION.md](CPPGRAPH_INTEGRATION.md) and the Masora-side
  `masora facts --repo [--symbol]` command is delivery pending (TODO.md). (The
  MCP write path itself is built: `masora/mcp.py` + `masora/write.py` — the
  code anchor snapshots are recorded at note/verify time.)
