# INPROGRESS

<!-- Current state of the running phase. Updated as work happens — tick
     [x]/[ ] and record blockers as soon as they appear, not only before
     commit. Resume here after any session interruption.
     Phase done -> entry in CHANGELOG.md, then reset this file with the next
     phase's detail (never empty, never stale). -->

## Current phase

Phase 1: v0 core (TODO.md). Done so far: pre-flight, FORMAT.md contract
(frozen, 6162bbc), `masora check` MVP (3869b49), `masora sync` (be784c0),
the project documentation (README.md, docs/ARCHITECTURE.md,
docs/TROUBLESHOOTING.md, AGENTS.md, tests/test_docs.py),
`masora setup --base <url>[#<path>]` (masora/setup.py, masora/config.py),
`masora gc --lineage` (masora/gc.py), the SQLite index + §6.2
resolution + FTS (masora/resolve.py, masora/index.py — full-rebuild DB at
`<masora_home>/indexes/<base-slug>/<repo-slug>-<hash>.db`, status tuples,
`suspect` per §12.4, file-anchor provider, CLI `index`/`search`), and the
`code` anchor provider over a cppgraph graph store (masora/providers.py:
definition + edge-set fingerprints, neighbour snapshots, graph-commit
currency policy; `--cppgraph`/`--no-cppgraph` on the index CLI; W-IDX-GRAPH;
28 new tests — 344 total green). Next task: MCP tools (`note`,
`verify`, `doubt`, `undoubt`, `refute`, `search`, `list_stale`).

## Steps

- [x] Pre-flight: check name availability — `pip index versions masora`, GitHub, npm (§3).
  → Name kept: **masora**. PyPI free (install channel), crates.io free, GitHub
  username taken (irrelevant — repo uniqueness is per-account), npm holds an
  empty 2020 placeholder (no versions/author; scoped package or transfer if a
  JS port ever happens).
- [x] Claim/verify/doubt/undoubt/refute/unrefute `.md` format + frontmatter
  schema (settled, §12.5) + layout of §7 → **FORMAT.md** (canonical contract).
  YAML clarifications settled: monotonic in-process ULIDs (uniqueness by
  check), `unanchored_reason` distinct field, ambiguous-at-note writes
  nothing.   Pipeline applied: cheap-review (4 MAJOR consistency) → cheap-mech
  → design-review (REWORK: format_version, lineage==target.lineage,
  per-anchor provider-neutral snapshots, per-anchor neighbours) → cheap-mech
  → verification review (0 MAJOR, 8 MINOR fixed) → strong-review systemic
  audit (6 MAJOR: active-event folding, anti-cycle, tombstones, per-kind
  table, baseline) → cross-vendor strong-review-alternative (9 MAJOR, all
  refinements of already-open areas) → cheap-mech → final verification
  (0 MAJOR, 6 MINOR fixed). **Contract frozen** — every lens re-run finds
  zero. Next: `masora check` implements FORMAT.md §7.
- [x] `masora check`: validates event schema and append-only history (local
  command; run by `sync`). Done: `masora/` package (`ulid`, `frontmatter`,
  `schema`, `fold`, `checker`, `cli`) implementing FORMAT.md §7 standalone
  whole-tree validation + §6 active-event folding; fold executable spec
  proven by brute force (all 13,512 DAGs at n≤4 vs an independent
  topological oracle, 4 evaluation orders + 10k sampled 5-event graphs);
  190 tests green. Review pipeline applied (1 MAJOR: neighbour-hash quoting
  in canonicalization; 6 MINOR: ULID time mask, fold lineage scoping,
  python floor 3.13, count ≥ 0, .pytest_cache, negative test) — verified,
  SHIP. Standalone mode only — append-only diff vs merge-base comes with
  `sync` (§7.9). Contract correction folded in: FORMAT.md §6 convergence
  scoped to the acyclic domain (cycles rejected before folding).
- [x] `masora sync`: runs `masora check`, batches local events into one
  branch + PR to the shared base. Done: `masora/sync.py` + CLI subcommand
  (`--drop`, `--push` solo) — local check gate, append-only content diff
  by event-id identity (deletions vs merge-base, rewrites vs both
  baselines, whole-lineage gc-shape detection, tombstone shrink),
  founder rule for new v2+ claims, merged-result validation with union
  tombstone (gc-vs-extension races), pending lifecycle (plumbing commit
  onto `masora/pending`, force-with-lease push, gh PR create/update or
  compare-URL fallback). 27 sync tests, 220 total green (incl.
  tests/test_docs.py). Pipeline:
  impl → review (2 MAJOR: deletions-vs-origin/main false positives,
  solo push not advancing local main; 5 MINOR) → fixes → verified SHIP
  (reviewer briefly hallucinated a re-objection, disproven on disk).
- [x] `masora setup --base <url>[#<path>]`: onboarding in one command.
  Done: `masora/setup.py` + `masora/config.py` + CLI subcommand — partial
  clone (`--filter=blob:none --sparse`) into `~/.local/share/masora/bases/<name>`
  with sparse checkout at `#<path>` (root bases: sparse restriction lifted —
  a bare `--sparse` cone clone checks out root files only, which would hide
  the event tree); `base.toml` schema settled (`name` + `code_remotes`,
  exactly these keys, docs/ARCHITECTURE.md); `config.toml` written or merged
  (`[bases.<slug>]` from remote/path/clone-HEAD branch, `[[mappings]]` with
  normalized `code_remote` — lowercase host, no scheme/user/port, no
  trailing `.git` — in `masora.config.normalize_remote`; existing entries
  and unknown keys preserved, mapping merge unions `bases`, same-remote
  re-run idempotent, different-remote duplicate refused with
  `E-SETUP-DUPLICATE`); `MASORA_HOME` relocates everything for tests and
  special cases. 7 new `E-SETUP-*` codes in diagnostics.py +
  docs/TROUBLESHOOTING.md in the same change (two-way sync guarded by
  tests/test_docs.py). 17 setup tests (real git repos via file:// URLs —
  local transport ignores the blob filter with a warning, clone succeeds:
  graceful degradation), 238 total green.
- [x] `masora gc --lineage`: whole-lineage deletion on explicit, confirmed
  request. Done: `masora/gc.py` + CLI subcommand — `--lineage` repeatable,
  plan-then-confirm (plan prints the files/warnings and exits 3 with
  nothing written; `--yes` executes), `masora check` run before
  (errors block) and after (failure = `E-GC-CHECK`) the mutation; one
  `[[deleted]]` block per lineage appended to `deleted.toml` (append-only
  by content), event files removed, emptied dirs pruned; no git spawn and
  no commit — the deletion is an ordinary git commit left to the user, or
  travels through `masora sync` like any pending change; gc never suggests
  lineages (deleting a still-active lineage warns `W-GC-ACTIVE`,
  fully-refuted lineages exit clean). `masora/sync.py` now accepts
  whole-lineage deletions whose lineage is tombstoned locally (the
  former unconditional `E-GC-UNAVAILABLE` fires only for tombstone-less
  deletions = tampering) and applies accepted deletions to the merged
  tree before merged-result validation. New codes E-GC-ULID, E-GC-UNKNOWN,
  E-GC-CHECK, W-GC-ACTIVE documented in the same change. 12 gc tests
  (incl. the keystone: sync accepts a gc'd base), 254 total green.
- [x] SQLite index + resolution algorithm of §6.2 + FTS. Done:
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
  a reformat does not stale; `code` anchors have no provider yet →
  `unknown`, never guessed; corrupt DB: discarded+rebuilt with
  `W-IDX-CORRUPT` on index, refused with `E-IDX-CORRUPT` on search).
  CLI `masora index <base> [--repo]` (counts by status, exit 0/2/1) and
  `masora search <base> <query> [--repo]` (status-tuple rendering, exit
0/1, 2 = `E-IDX-QUERY` arg-level error). 5 E-IDX-* + 2 W-IDX-* codes
documented in docs/TROUBLESHOOTING.md in the same change; 32 matrix
tests + 26 index tests, 313 total green.
- [x] Code anchor provider via cppgraph (TODO: per-symbol definition
  fingerprint + edge-set fingerprint + neighbour snapshot). Done:
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
  `masora index` gains `--cppgraph <db>` / `--no-cppgraph`; the used graph
  commit is exposed on `IndexResult` and in index meta. 17 provider tests +
  7 index-path tests (incl. suspect firing on neighbour and own-edge drift
  between two hand-crafted graph builds) — plus W-IDX-STALE extended to code
  drift (stored repo_head/graph_commit vs current --repo HEAD and discovered
  graph source_commit at search time, 4 tests) — 344 total green. W-IDX-GRAPH
  documented in docs/TROUBLESHOOTING.md in the same change.

(Remainder of the phase: see TODO.md.)

## Blockers

None.
