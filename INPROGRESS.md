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
`masora setup --base <url>[#<path>]` (masora/setup.py, masora/config.py —
partial clone + sparse checkout into ~/.local/share/masora/bases/,
base.toml schema {name, code_remotes}, config.toml write/merge with
normalized [[mappings]], 7 E-SETUP-* diagnostics, 17 setup tests), and
`masora gc --lineage` (masora/gc.py — plan-then-confirm, tombstone writes,
sync acceptance of tombstoned deletions, 12 gc tests — 254 total green).
Next task: the SQLite index (TODO.md).

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

(Remainder of the phase: see TODO.md.)

## Blockers

None.
