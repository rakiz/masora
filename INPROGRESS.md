# INPROGRESS

<!-- Current state of the running phase. Updated as work happens — tick
     [x]/[ ] and record blockers as soon as they appear, not only before
     commit. Resume here after any session interruption.
     Phase done -> entry in CHANGELOG.md, then reset this file with the next
     phase's detail (never empty, never stale). -->

## Current phase

**Done:** `masora init` — base bootstrap command (TODO.md, ticked).
`masora/init.py`: `masora init [<base-dir>|--here] --name <name>
[--code-remote <url>]... [--force]` creates a new base locally — refuses an
unusable target (a file, non-empty without `--force`, an existing `base.toml`
even forced: `E-INIT-TARGET`), writes `base.toml` in the exact shape setup
reads (remotes normalized + deduplicated via `config.normalize_remote`),
gates the fresh tree through `check_base` before the first commit
"masora init: base <name>" (`E-INIT-ARG`, `E-INIT-WRITE`, `E-INIT-CHECK`,
`E-INIT-GIT` — e.g. a missing git identity), every git spawn through
`sync.git_env()`, and prints the exact next command
`masora setup --base <path>` plus one line: publishing to a shared repo is
the user's git work. New `E-INIT-*` family in diagnostics.py +
docs/TROUBLESHOOTING.md (two-way guarded). 11 tests in tests/test_init.py;
suite 496 green; ruff clean. Next task: the first rollout (TODO.md — the
real base on the author's `employees/` dir + the Confluence install page).

**Done:** two friction fixes (TODO.md, both ticked). `E-MCP-NO-BASE` remedy:
`masora/write.py` `resolve_base` distinguishes its two causes and remedies
each — an omitted `repo_root` (read tools fall back to the base directory,
which by construction matches no remote) is told "pass repo_root (the
checkout you are asking about) — the base is resolved from that repo's origin
remote"; an unmapped repo is told "run masora setup --base <url> in this
checkout, or pass the base parameter explicitly"; an unknown explicit `base`
names neither remedy. `note` field split: the `masora/mcp.py` inputSchema
description states the contract in one sentence (summary = the injected
one-liner, ≤ 120 characters, what cppgraph surfaces; statement = the full
text, no length constraint; content in English — base event files are pushed
content), the summary/statement field descriptions match, and the write
tools' `reason`/`evidence` descriptions carry the language expectation.
Tests: 2 new + 2 updated in tests/test_mcp.py; suite 485 green; ruff clean.
Next task: the first rollout (TODO.md — the real base on the author's
`employees/` dir + the Confluence install page).

**Done:** two-feature pass (TODO.md, both ticked). Feature A — readable sync
PR: `masora/sync.py` `_pr_body`/`_pr_title` render the PR as a plain-English
changelog of the pending set (title mirrors per-kind counts + tombstone
segment; one line per event with the lineage slug, the resolved target
summary followed along the `targets` chain, the reason truncated to 80
characters, and `name`-else-`source` provenance; tombstone additions render
one removal line); `EventFile` gained `targets`/`source`/`name`/`reason`/
`evidence_count`, the YAML diff on the pending branch stays the audit
surface. Feature B — human-named lineage directories: `masora/write.py`
`lineage_slug` (deterministic lowercase ASCII `[a-z0-9-]` slug of the founder
summary, ≤ 24 chars, word-boundary trimmed, empty → bare lineage ULID) and
`event_relpath(data, base_dir)` — the founder creates
`YYYY-MM/<slug>-<lineage>/` in its month, every extension joins the
lineage's existing directory found by ULID suffix verbatim (no month
re-bucketing, no split; legacy splits resolve to the founder-holding
directory, else sorted-first, never a third dir); `check` stays
path-indifferent. FORMAT.md §1, MASORA_DESIGN §7 and docs/ARCHITECTURE.md
state the single-home rule and the `<slug>-<lineage-ULID>` convention. Tests:
tests/test_write.py (new, 13), 5 new + 1 updated in tests/test_sync.py, 2
updated in tests/test_mcp.py; suite 483 green; ruff clean. Next
task: the first rollout (TODO.md — the real base on the author's `employees/`
dir + the Confluence install page).

**Done:** `masora compact <base-dir>` (TODO.md, ticked) — per-lineage
compression to the minimal live witness set. `masora/compact.py`:
`select_witness` (pure, property-tested against the brute-force oracle's
generator over every acyclic DAG at n ≤ 4 exhaustively + sampled n = 5 DAGs),
per-lineage `observable_state` fold-equality proof refusing diverging
lineages fail-closed (E-COMPACT-DIVERGE, nothing written), plan-then-confirm
like gc (plan exits 3, `--yes` executes, pre/post `masora check` —
E-COMPACT-CHECK — plus tree-wide status re-verification). Dropped events
known to the shared repo (on `origin/main` or the sync merge-base, resolved
without fetch; none → no tombstones) are tombstoned per-event in
`deleted.toml`'s new `[[deleted_events]]` table ({lineage, ulids} like
`[[deleted]]`, append-only by content, union-merged by sync, accepted by
sync's deletion diff; `[[deleted]]` keeps its whole-lineage semantics and
gc is untouched); unpublished events drop silently. Survivors keep ULIDs and
bytes. checker.py loads both tables (E-TOMBSTONED by event id for
deleted_events, lineage semantics unchanged); fold.Event carries an inert
`contradicts` field for the closure. Docs updated in the same change:
FORMAT.md §1/§7.10, README quick start + diagnostics, ARCHITECTURE Compact
section, TROUBLESHOOTING (2 new codes, two-way guarded), CONVENTIONS §3
(base event content is English), CHANGELOG [Unreleased]. 19 tests in
tests/test_compact.py; suite 465 green; ruff clean. Next task: the first
rollout (TODO.md — the real base on the author's `employees/` dir + the
Confluence install page).

Phase 1: v0 core (TODO.md). In place: pre-flight; the FORMAT.md contract
(frozen); `masora check` (standalone whole-tree validation + fold, proven by
brute force); `masora sync` (publication: one branch + one PR, append-only
diff, merged-result validation); the project documentation (README.md,
docs/ARCHITECTURE.md, docs/TROUBLESHOOTING.md, AGENTS.md, tests/test_docs.py);
`masora setup --base <url>[#<path>]` (masora/setup.py, masora/config.py);
`masora gc --lineage` (masora/gc.py); the SQLite index + §6.2 resolution + FTS
(masora/resolve.py, masora/index.py — full-rebuild DB at
`<masora_home>/indexes/<base-slug>/<repo-slug>-<hash>.db`, status tuples,
`suspect` per §12.4, file-anchor provider, CLI `index`/`search`); the `code`
anchor provider over a cppgraph graph store (masora/providers.py: definition +
edge-set fingerprints, neighbour snapshots, graph-commit currency policy;
`--cppgraph`/`--no-cppgraph` on the index CLI; W-IDX-GRAPH); the MCP server +
write path (masora/mcp.py: hand-rolled stdio JSON-RPC 2.0, protocol
2025-06-18 negotiated the standard way; masora/write.py: shared write path,
E-MCP-* codes); the cppgraph injection handoff contract
(docs/CPPGRAPH_INTEGRATION.md) and its Masora side —
`masora facts --repo [--symbol]` (masora/facts.py: read-only contract
command, never builds the index; E-FACTS-NO-BASE/E-FACTS-NOINDEX). The
unified-provenance format is in place (MASORA_DESIGN.md §12.10 — `source`
`human|llm|graph` on every event kind, optional `name`/`effort`, fold over
verify sources, `E-PROVENANCE` diagnostic, MCP write tools sign the human
name from the base repo's git config + effort llm-only, `masora facts`
contract 1 exposing per-fact `source`/`name`/`effort`/`anchors`; format
version 1). Three-item hardening pass on top: the credential guard in the
shared write path (masora/write.py: HIGH-CONFIDENCE shapes only — PEM
private-key blocks, AWS ids, `ghp_`/`github_pat_`/`sk-`/`xox` token prefixes,
20+ char mixed-class secret assignments — refused with `E-WRITE-SECRET`
before anything touches disk, password discussion passes); the exact-version
graph-store gate (masora/providers.py: ONLY schema_version 5 accepted —
missing/unparsable/older/newer → store unavailable, `unknown` shadows,
`W-IDX-GRAPH` names the seen version); the trust-rendering matrix pinned in
docs/CPPGRAPH_INTEGRATION.md §6 (verify label always renders; `low-effort`
token only for `verified(llm)` at `effort: low`, never under `verified(human)`;
`verified(graph)` bare;
`unverified` renders nothing); the filesystem-freshness staleness axis
(masora/index.py: `index_stale()` fourth axis — `built_at` from the index
meta against the base tree's newest event-`*.md`/`deleted.toml` mtime,
~2 s tolerance, one walk per read; catches the rollout freeze where an
UNCOMMITTED `note` moves no git HEAD and `masora facts`/`search` silently
missed the just-written claim; the reason flows into `W-IDX-STALE`,
`stale_warning` keeps its boolean shape); 446 tests green. Next task: the
first rollout
(TODO.md — the real base on the author's `employees/` dir + the Confluence
install page). The
`SessionStart`/`UserPromptSubmit` hooks belong to Phase 2 (no client before
non-code knowledge; the graph channel is validated first).

## Steps

- [x] Pre-flight: name availability checked against `pip index versions
  masora`, GitHub, npm (§3). Name: **masora** — PyPI free (install channel),
  crates.io free, GitHub username taken (irrelevant — repo uniqueness is
  per-account), npm holds an empty 2020 placeholder (no versions/author; a
  scoped package or transfer if a JS port ever happens).
- [x] Claim/verify/doubt/undoubt/refute/unrefute `.md` format + frontmatter
  schema (settled, §12.5) + layout of §7 → **FORMAT.md** (canonical contract):
  monotonic in-process ULIDs (uniqueness by check), `unanchored_reason` as a
  distinct field, ambiguous-at-note writes nothing.
- [x] `masora check`: validates event schema and append-only history (local
  command; run by `sync`). → `masora/` package (`ulid`, `frontmatter`,
  `schema`, `fold`, `checker`, `cli`) implementing FORMAT.md §7 standalone
  whole-tree validation + §6 active-event folding; fold executable spec
  proven by brute force (all 13,512 DAGs at n≤4 vs an independent
  topological oracle, 4 evaluation orders + 10k sampled 5-event graphs);
  190 tests. Convergence is scoped to the acyclic domain (cycles rejected
  before folding, FORMAT.md §6). Standalone mode only — the append-only diff
  vs merge-base belongs to `sync` (§7.9).
- [x] `masora sync`: runs `masora check`, batches local events into one
  branch + PR to the shared base. → `masora/sync.py` + CLI subcommand
  (`--drop`, `--push` solo) — local check gate, append-only content diff
  by event-id identity (deletions vs merge-base, rewrites vs both
  baselines, whole-lineage gc-shape detection, tombstone shrink),
  founder rule for new v2+ claims, merged-result validation with union
  tombstone (gc-vs-extension races), pending lifecycle (plumbing commit
  onto `masora/pending`, force-with-lease push, gh PR create/update or
  compare-URL fallback). 27 sync tests, 220 total (incl.
  tests/test_docs.py).
- [x] `masora setup --base <url>[#<path>]`: onboarding in one command.
  → `masora/setup.py` + `masora/config.py` + CLI subcommand — partial
  clone (`--filter=blob:none --sparse`) into `~/.local/share/masora/bases/<name>`
  with sparse checkout at `#<path>` (root bases: sparse restriction lifted —
  a bare `--sparse` cone clone checks out root files only, which would hide
  the event tree); `base.toml` schema (`name` + `code_remotes`,
  exactly these keys, docs/ARCHITECTURE.md); `config.toml` written or merged
  (`[bases.<slug>]` from remote/path/clone-HEAD branch, `[[mappings]]` with
  normalized `code_remote` — lowercase host, no scheme/user/port, no
  trailing `.git` — in `masora.config.normalize_remote`; existing entries
  and unknown keys preserved, mapping merge unions `bases`, same-remote
  re-run idempotent, different-remote duplicate refused with
  `E-SETUP-DUPLICATE`); `MASORA_HOME` relocates everything for tests and
  special cases. 7 `E-SETUP-*` codes in diagnostics.py +
  docs/TROUBLESHOOTING.md (two-way guarded by tests/test_docs.py).
  17 setup tests (real git repos via file:// URLs — the local transport
  ignores the blob filter with a warning, clone succeeds: graceful
  degradation).
- [x] `masora gc --lineage`: whole-lineage deletion on explicit, confirmed
  request. → `masora/gc.py` + CLI subcommand — `--lineage` repeatable,
  plan-then-confirm (plan prints the files/warnings and exits 3 with
  nothing written; `--yes` executes), `masora check` run before
  (errors block) and after (failure = `E-GC-CHECK`) the mutation; one
  `[[deleted]]` block per lineage appended to `deleted.toml` (append-only
  by content), event files removed, emptied dirs pruned; no git spawn and
  no commit — the deletion is an ordinary git commit left to the user, or
  travels through `masora sync` like any pending change; gc never suggests
  lineages (deleting a still-active lineage warns `W-GC-ACTIVE`,
  fully-refuted lineages exit clean). `masora/sync.py` accepts
  whole-lineage deletions whose lineage is tombstoned locally
  (`E-GC-UNAVAILABLE` fires only for tombstone-less deletions = tampering)
  and applies accepted deletions to the merged tree before merged-result
  validation. Codes E-GC-ULID, E-GC-UNKNOWN, E-GC-CHECK, W-GC-ACTIVE
  documented in docs/TROUBLESHOOTING.md (two-way guarded). 12 gc tests
  (incl. the keystone: sync accepts a gc'd base).
- [x] SQLite index + resolution algorithm of §6.2 + FTS. →
  `masora/resolve.py` (pure §6.2 status tuple — wraps `fold.py`'s fixed
  point + fold_lineage + precedence; injectable provider registries:
  fingerprints `(kind, identity) -> fp | None`, missing/None entry =
  unavailable → `unknown` shadows, callable None = not_found fails to
  match; edge-snapshot registry for `suspect` §12.4 over the union of
  recorded/current neighbours; `pending` via injected not-in-origin/main
  ids; founder-absent exclusion; unanchored always surfaced) and
  `masora/index.py` (full-rebuild SQLite DB, WAL, atomic os.replace,
  disposable; location `<masora_home>/indexes/<base-slug>/<repo-slug>-<path-hash12>.db`
  via `config.indexes_root()`; check gate blocks on errors; tombstoned
  lineages excluded; schema meta/lineages/versions/anchors + FTS5 search
  (summary+statement, unicode61 → case/accent-insensitive); stored base
  HEAD → `index_stale()` + `W-IDX-STALE` on search; `file`-anchor provider
  hashing whitespace/comment-normalized content of the `--repo` checkout —
  a reformat does not stale; `code` anchors report `unknown` until the
  cppgraph provider answers; corrupt DB: discarded+rebuilt with
  `W-IDX-CORRUPT` on index, refused with `E-IDX-CORRUPT` on search).
  CLI `masora index <base> [--repo]` (counts by status, exit 0/2/1) and
  `masora search <base> <query> [--repo]` (status-tuple rendering, exit
  0/1, 2 = `E-IDX-QUERY` arg-level error). 5 E-IDX-* + 2 W-IDX-* codes
  documented in docs/TROUBLESHOOTING.md (two-way guarded); 32 matrix
  tests + 26 index tests.
- [x] Code anchor provider via cppgraph (per-symbol definition fingerprint +
  edge-set fingerprint + neighbour snapshot). →
  `masora/providers.py` — the `code` registry entries for both provider
  registries read a cppgraph graph store (schema v5 learned from the
  cppgraph source: `files`/`symbols`/`edges`/`meta`, `meta.source_commit`)
  read-only; the FORMAT.md §4 anchor identity is matched verbatim against
  `symbols.symbol`; definition fingerprint = sha256 of the
  whitespace/comment-normalized source of `symbols.line`..`end_line`
  (0-indexed; single line on stores without body extents), edge-set
  fingerprint = sha256 of the sorted distinct callee SCIP strings of
  `calls` edges, neighbour snapshot = 1-hop callers ∪ callees → their
  edge-set hashes. Currency policy (§5.2): `meta.source_commit` must equal
  the `--repo` HEAD, decided once per build — mismatch/unverifiable → ALL
  code anchors unavailable (`unknown` shadows, §6.2) + `W-IDX-GRAPH` when
  code anchors exist; missing graph store silent (cppgraph optional).
  `masora index` takes `--cppgraph <db>` / `--no-cppgraph`; the used graph
  commit is exposed on `IndexResult` and in index meta. 17 provider tests +
  7 index-path tests (incl. suspect firing on neighbour and own-edge drift
  between two hand-crafted graph builds) — plus W-IDX-STALE covering code
  drift (stored repo_head/graph_commit vs current --repo HEAD and discovered
  graph source_commit at search time, 4 tests). W-IDX-GRAPH
  documented in docs/TROUBLESHOOTING.md (two-way guarded).
- [x] MCP tools: `note`, `verify`, `doubt`, `undoubt`, `refute`, `search`,
  `list_stale`. → `masora/mcp.py` (hand-rolled minimal MCP stdio server —
  newline-delimited JSON-RPC 2.0, protocol version pinned `2025-06-18` and
  negotiated the standard MCP way (the initialize result always carries it;
  malformed initialize params are -32602), methods initialize /
  notifications/initialized / tools/list / tools/call only, JSON-RPC error
  mapping -32700/-32600/-32601/-32602/-32603, parse-error resilience:
  malformed lines never stop the loop, reported via W-MCP-PROTO on stderr)
  and `masora/write.py` (the ONE event-writing path for all five write tools:
  base resolution — explicit `base` parameter first, then mapping match on
  the normalized `origin` remote →
  `default_base` → `E-MCP-NO-BASE`, never guessed —,
  write-time anchor resolution (exact SCIP match, else case-insensitive
  substring; ambiguous/not_found → `E-MCP-ANCHOR`, nothing written, FORMAT
  §6), write-time fingerprints + snapshots via `masora/providers.py` (§11
  `resolve` available there), `E-MCP-GRAPH` when the graph is behind HEAD or
  absent (§5.2, message: re-index), canonical block-style emission with
  JSON-style control-char escaping (multi-line statements round-trip) +
  pre-validation behind a shared `check_base` pre-check (nothing is written
  onto an invalid base) + post-write `check_base` with unlink-on-failure (a
  tool never returns success on an invalid tree); timestamps always carry
  `graph_commit` (explicit null without a graph, FORMAT §4); lineage ids
  (including the founding claim's, whose id equals the lineage) ride the
  fold to the lineage's DISPLAYED version for verify/refute and to the
  active verify for doubt; verify re-fingerprints the immutable set with
  `E-MCP-DRIFT` refusal (FORMAT §7.7 → new claim version, MASORA_DESIGN
  §6.3); undoubt targets the doubt's ULID only;
  `search`/`list_stale` resolve the base the
  same way, auto-build a missing index and surface `W-IDX-STALE` in the
  result text without rebuilding (the SessionStart hook owns freshness)).
  CLI `masora mcp` (stdio server). Codes E-MCP-ARGS, E-MCP-NO-BASE,
  E-MCP-GRAPH, E-MCP-UNKNOWN-ID, E-MCP-ANCHOR, E-MCP-DRIFT, W-MCP-PROTO
  documented in docs/TROUBLESHOOTING.md (two-way guarded); ARCHITECTURE.md
  carries the MCP section, README the register-the-server line,
  MASORA_DESIGN §12.9 the settled transport decision. 39 MCP
  tests (subprocess-driven server, hermetic MASORA_HOME, graph fixture,
  rapid-consecutive-note ULID monotonicity).

(Remainder of the phase: see TODO.md.)

## Blockers

None.
