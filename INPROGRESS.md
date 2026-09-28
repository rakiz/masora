# INPROGRESS

<!-- Current state of the running phase. Updated as work happens — tick
     [x]/[ ] and record blockers as soon as they appear, not only before
     commit. Resume here after any session interruption.
     Phase done -> entry in CHANGELOG.md, then reset this file with the next
     phase's detail (never empty, never stale). -->

## Current phase

Phase 1: v0 core (TODO.md). Done so far: pre-flight, FORMAT.md contract
(frozen, 6162bbc), `masora check` MVP (3869b49). Next task: `masora sync`
(runs check, batches local events into one branch + PR; adds the
append-only diff vs merge-base that standalone check defers, §7.9).

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

(Remainder of the phase: see TODO.md.)

## Blockers

None.
