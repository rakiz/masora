# Changelog

<!-- Keep a Changelog format (https://keepachangelog.com): one entry per
      version / completed phase, newest first. An entry is added when a
      task/phase is done, never before. Within a version, a section describes
      the current state only (release-notes style); the history of how the
      project got there lives between released versions. -->

## [Unreleased]

### Added

- **Facts contract: batched symbol matching (the injection-surface request)**
  — `masora facts --symbol` is REPEATABLE: one spawn matches N symbols
  (OR-semantics over the verbatim anchor rule, `anchors_matched` accumulating
  deduplicated in call order), contract_version stays 2 and the document
  shape is unchanged. docs/CPPGRAPH_INTEGRATION.md carries the REQUEST to the
  cppgraph side in the contract's own voice (§6: the injection scope gains
  find/outline with one batched spawn per response, budget and visible
  truncation unchanged, plus the presence-hint rule — one capability line
  when masora is present and zero facts rendered; §9: the two new
  diff-able self-check rows). Implementing it is the cppgraph agent's call,
  per the §9 diff ritual — masora owns the contract, not the other repo.
  (+4 tests.)

- **Team life, wave 6b (AUDIT.md proposals 5-6)** — the pending branch is
  PER-AUTHOR (`masora/<author-slug>` from the base clone's git identity,
  deterministic slug ≤ 24 chars, missing identity = E-GIT remedy): two
  writers publish independently, no shared-branch collision, every flow
  step (push with lease, PR head, tracking compare, drop) switched;
  `masora union <base-dir>` rescues a conflicted `deleted.toml` by ROW
  UNION (both sides' `[[deleted]]`/`[[deleted_events]]` rows deduped on
  their natural keys, ours-first order, no row ever dropped — fail-closed
  `E-UNION-*` diagnostics; published only after `check_base` passes on a
  throwaway copy, atomic replace, never runs git); `masora hook install`
  ships the SessionStart freshness hook (background pull + fast-forward
  per base, stale-index rebuild within the §10.1 budget, at most ONE
  summary line, silent failure everywhere, `--ff-only` so it can never
  discard a commit); `masora ci print` ships the reusable base-PR check
  workflow (workflow_call, read-only `masora check`, the union rescue
  documented for maintainers). (+38 tests.)

- **Team life, wave 6a (AUDIT.md proposals 6-7)** — the `unrefute` MCP tool
  (9th tool: targets a refute event ULID, lifts it per FORMAT.md §5.4's fold,
  refuses a lineage id or a never-refuted target, `source: human` stays
  MCP-unwritable); `masora doctor` — report-only health checks (config,
  git identity, per-base clone health + origin match + read-only fetch, gh
  auth as WARN-only, index existence + four-axis staleness, cppgraph graph
  presence + freshness), exit 1 only on FAIL, all spawns under the M4
  timeouts, nothing mutated; `masora reset <base-dir> --from-origin
  [--yes]` — the refoundation acceptance move as plan-then-confirm (plan
  exits 3), refuses a dirty tree and a missing origin/main, lists the
  local-only commits it would discard, callable by NOTHING internal (the
  never-automatic invariant), and neutral on refoundation-vs-attack by
  design (tamper evidence intact); the refoundation runbook
  (docs/REFOUNDATION.md) cross-linked from the E-REWRITE remedies, README
  and ARCHITECTURE; new `E-RESET-*` diagnostics (two-way synced).
  (+29 tests.)

### Changed

- **Robustness/perf sweep (AUDIT.md wave 3)** — anchor fingerprints are
  memoized per index build (one provider call per anchor, was two); the
  write path runs ONE full base parse per note (the post-write validation
  is incremental over the invariants one new event can break); every
  subprocess call carries a timeout and missing binaries map to
  diagnostics instead of tracebacks (`GIT_TERMINAL_PROMPT=0` set
  centrally); the cppgraph handle is closed by `explain`; deep-YAML
  `RecursionError` reports `E-YAML` instead of crashing; index
  directories hash the base path (same-basename bases no longer collide)
  with a unique `.building` tmp per build; `deleted.toml` appends are
  atomic; `auto_base` refuses a matched-but-malformed mapping instead of
  silently falling through to `default_base`; MCP search reuses a
  code-repo-keyed index instead of building a duplicate; stdio is
  reconfigured UTF-8; `explain` on an event ULID resolves to its
  lineage's story; `setup` guards the clone URL and preserves config
  comments; `proof_query` float args round-trip as numbers. (+25 tests.)

### Added

- **Search hardening** — the query is reduced to safe quoted prefix terms
  (`C++`, `a.b`, apostrophes and natural-language shapes return results
  instead of FTS5 syntax errors), results rank by bm25 best-first, and a
  20-hit cap is reported honestly (`... N more`) on CLI and MCP. (`masora/index.py`, `masora/cli.py`, `masora/mcp.py`, tests/test_index.py.)
- **Structural verifications say "proof not replayed"** — a verify recorded
  on a `class: structural` claim carries the explicit qualifier in its
  evidence (the replay is scoped to the cppgraph integration); SPEC.md:16
  amended to the honest two-step. (`masora/mcp.py`, FORMAT.md, SPEC.md, tests/test_mcp.py.)

### Changed

- **`sync --push` preserves locally committed events the selection
  excluded** — a preservation commit replaces the `reset --hard` drop; the
  `--only`/`--exclude` promise now holds for committed events too.
  (`masora/sync.py`, tests/test_sync.py.)
- **The publication gate reads origin/main after the fetch** — a stale
  local main no longer hides already-published deletions; already-published
  tombstones apply cleanly instead of resurrecting. (`masora/sync.py`, tests/test_sync.py.)
- **`source: human` is refused from the MCP surface** (`E-MCP-HUMAN`) — the
  trust label must not be forgeable by a prompt-injected agent; human
  verifications are a local, interactive act. (`masora/mcp.py`,
  `masora/diagnostics.py`, docs/TROUBLESHOOTING.md, tests/test_mcp.py.)
- **gc fetches before judging published-ness** (a stale remote-tracking ref
  resurrected tombstoned lineages at PR merge) and the `E-TOMBSTONED`
  message names the exact remedy. (`masora/gc.py`, `masora/checker.py`,
  docs/TROUBLESHOOTING.md, tests/test_gc.py.)
- **Atomic event writes** (temp + `os.replace`) — a concurrent session can
  no longer see a half-written event or unlink its own valid one.
  (`masora/write.py`, tests/test_write.py.)
- **The secret scan covers `name`, `unanchored_reason` and
  `proof_query.args`/`expect`.** (`masora/write.py`, tests/test_write.py.)
- **The `lines` fork-point stamp captures a FIXED ref set** (HEAD upstream +
  the default branch — the lexicographic first-16 cap is gone) and
  FORMAT.md §4 no longer claims it feeds the off-version guard (nothing
  reads the stamp). **An index built with an unavailable graph stores its
  observed source_commit** (`graph_seen_commit`) — the staleness axis no
  longer cries wolf for "built without a graph". **The ULID wall-clock
  policy is documented** (multi-writer skew: warn + ordering caveat,
  mechanism deferred). (`masora/write.py`, `masora/index.py`, FORMAT.md,
  SPEC.md, MASORA_DESIGN.md §12.16(q), tests/test_write.py,
  tests/test_index.py.)

- **`masora sync --only <ulid…>` / `--exclude <ulid…>`** — publish a SUBSET of
  the pending events: both flags take a list of event ULIDs (full id or unique
  prefix; an ambiguous prefix or a selector matching nothing is refused with
  the candidates — `E-SYNC-SELECT`, nothing mutated), and they are mutually
  exclusive. The selectors filter the pending EVENT ADDITIONS only: deletions
  already decided by `gc` (tombstones) always ride. The gates (stacking audit,
  founder rule, merged-result validation) run on the filtered set, so the PR
  is self-consistent without the excluded events — excluded events stay
  pending locally and a later plain sync publishes them. Plan mode prints the
  filtered set, the counts and one `excluded:` line per id. (`masora/sync.py`,
  `masora/cli.py`, `masora/diagnostics.py`, docs/TROUBLESHOOTING.md, README.md,
  docs/ARCHITECTURE.md, tests/test_sync.py.)

## 0.7.0 — 2026-10-02

### Added

- **Branch/version context stamping — statuses qualified by the code state a
  claim was established against** (TODO.md phase 2; the design closed after a
  10-round review loop whose final round brute-forced 3,629,724 cases with
  zero semantic failures, mutation-checked; every ruling recorded in
  MASORA_DESIGN.md §12 item 16 (a)-(p)):

  - **Structured anchor outcomes** — per anchor `match`/`mismatch`/
    `not_found`/`unavailable` (provider `ambiguous` maps to `unavailable`),
    composed per version; replaces the boolean matcher and the
    unavailable-walk heuristic. A version whose provider is unreadable now
    resolves `unknown` (shadow) instead of a bare `stale` — visible change.
  - **The two-tier selection function sel** — tier 1: provably on the asking
    line (`in_line` ancestor-or-equal of HEAD, `ahead` a proper descendant
    also ancestor-or-equal of the local upstream ref; ahead outranks
    in_line; ancestry maxima; ULID ties), tier 2: everything else by ULID.
    A non-match can never display over a match; the no-match fallback is
    sel over all active versions (this line's drift is never masked by a
    younger off-version), flagged `off-version` only on definitive absence
    with a provably `out_of_line` relation. Counterfactual `restored` and
    shadow: a refuted/unavailable version qualifies when sel would pick it.
    With no provable git context the ranking reduces exactly to the
    previous ULID walk (oracle-proven).
  - **The git relation adapter** (`masora/gitctx.py`) — memoized, budgeted
    merge-base probes (1024 per build), never fetches; the counterfactual
    `degraded` test flags `context_ordering: degraded` when an unprovable
    context could change what displays (`W-CTX-DEGRADED`).
  - **The `lines` fork-point stamp** — `recorded_at`/`verified_at` accept an
    optional `lines` map (line ref → merge-base at write time), captured by
    the write tools from the checkout's branch refs (capped at 16, sorted,
    failures omitted) — never an agent argument, never backfilled, read by
    NOTHING in the resolution (context only). `format_version` stays 1;
    both shapes valid.
  - **Compact universal witness** — every eligible version's closure is
    kept (active AND refuted: anchors, fingerprints, establishing commit),
    the E-COMPACT-DIVERGE proof extended to context assignments
    (standalone, all-in_line, per-refuted ahead promotion), git-free.
  - **Recall surfaces** — `search --any-version` (all active versions with
    their own relation; refuted excluded — a future history tool owns
    archaeology), `list_stale` split into the re-check list and a separate
    "not applicable here" list, `explain` re-deriving git context live
    against the code checkout with `off-version`/`context:` labels.
  - **Facts contract v2** — per-fact `established_relation`
    (`in_line|ahead|out_of_line|unknown`), `established_commit` (short,
    presentation-only), `off_version`, `context_ordering`; v1 retired in
    the same release (beta ruling (p): no dual-version window).
    docs/CPPGRAPH_INTEGRATION.md rewritten to the v2 contract: rendering
    rule (fires on off_version, non-in_line relation or degraded; never as
    validity), non-goals (cppgraph renders, never computes or ranks).
  - **Index schema v6** — per-version relation + establishing commit,
    per-lineage `off_version` + `context_ordering`; rebuild-only (the
    index is a derived cache; beta: no migration — old event files stay
    valid forever, absence IS the unknown value).

### Changed

- **`masora sync` is plan-then-confirm** (owner ruling: the default must not act, it must show) — without `--yes`, sync runs the full gate pipeline (local check, fetch, diff vs `origin/main`, stacked audit, merged-result validation) and prints the readable pending set — the same one-line-per-event rendering the PR body carries, tombstone line and warnings included — then exits 3 with NOTHING written: no branch, no push, no PR, no local ref mutation. `--yes` is the single confirmation gate for every mutating mode: publish = `sync [--push] --yes`, discard = `sync --drop --yes`; `--push` stays a mode selector, not a confirmation (`--push` alone plans the push), and `--drop` without `--yes` plans the discard. `--allow-stacked` is unchanged: the stacked refusal still fires in plan mode (exit 1) — the preview reflects what publish would do. The "no pending events" path keeps exit 0 in plan mode. Exit codes: 3 plan printed (nothing written), 0 synced, 2 synced with warnings, 1 errors. (`masora/sync.py`, `masora/cli.py`, README.md, docs/ARCHITECTURE.md, tests/test_sync.py.)
- **Stacking threshold recalibrated + write-time awareness** — `STATEMENT_MAX` 1024 → 2048 (owner calibration on real-corpus evidence: real-base atomic notes reach ~1560 characters and must not false-positive the stacking audit). The soft publication limit now surfaces at write time so note writers aim tight BEFORE sync: the `note` tool's `statement` descriptions (field + inputSchema, the number derived from the `STATEMENT_MAX` constant) and the skill's "How to note well" statement line (mirrored byte-identically in the agent instructions) state — no hard limit, but keep the statement atomic and tight: above 2048 characters the sync-time stacking audit refuses publication by default (E-SYNC-STACKED). (`masora/audit.py`, `masora/mcp.py`, `masora/skills/masora/SKILL.md`, docs/AGENT_INSTRUCTIONS.md, tests/test_mcp.py, tests/test_docs.py.)

## 0.6.3 — 2026-10-01

### Fixed

- **The /masora correction rule names the search case precisely** — the 0.6.2 template's "correct it once" clause let an agent believe `masora search` always resolves the base from the configuration, when the CLI resolves it only when the base positional is OMITTED (`masora search shard key` correctly refused "shard" as a nonexistent base; the agent then corrected to the explicit-base form instead of the intended one-argument form). The template now states the exact case and fix: a first positional that does not exist as a base directory was user content, not a path — omit it (the configuration resolves the base), quote the remaining words together as the single `search` query (`masora search 'shard key'`), and drop the bad positional for the query-less subcommands. (`masora/skills/masora/COMMAND.md`.)

## 0.6.2 — 2026-10-01

### Added

- **The base directory resolves from the configuration when omitted** — the `base_dir` positional of `masora check`, `sync`, `gc`, `compact` and `index` is optional now (`search` already took it optional): omitted, one pre-flight base gate in the CLI dispatch resolves the base from the checkout's masora configuration (`write.auto_base` — `[[mappings]]` on the normalized `origin` remote, then `default_base`, the same chain the MCP write tools resolve with) and the command proceeds with the resolved directory; a failed resolution refuses with the existing `E-NOT-A-BASE` (no new diagnostic code) and a remedy stating both fixes — pass the base directory explicitly, or run `masora setup --base <url>` in this checkout (the cause-specific wording — not a Git checkout, no readable `origin`, unmapped repo — is kept, detected the same way `masora facts` does). A passed root is unchanged: same refusal, same remedy, same configured-base hint, and an explicit base always wins over the configuration. `sync` is resolved/refused in the same gate before any diff or mutation — a refused sync spawns no git and writes nothing. Rollout friction (twice, second machine via /masora): `masora search shard key` took "shard" as the base, and a bare `masora sync` took "." and refused with `E-NOT-A-BASE`. Owner adjustments: the gate keeps the old `.` default — with the positional omitted, a hinted directory that itself holds `base.toml` (the cwd for check/sync/gc/compact, `--repo` for index/search/explain) IS the base, ahead of the mappings/`default_base` chain (explicit positional still wins); and the dormant `E-SEARCH-NO-BASE` (shipped in 0.6.0, emitted by no path since the shared gate) is retired the same day — removed from `masora/diagnostics.py` and its docs/TROUBLESHOOTING.md row. (`masora/cli.py`, README.md, docs/ARCHITECTURE.md, docs/TROUBLESHOOTING.md, tests/test_base_gate.py, tests/test_sync.py, tests/test_index.py.)


### Fixed

- **The opencode /masora command template** — fixes the 0.6.1 template's `!`-injection pre-execution: the installed command spliced the invocation into the shell line, which mangled `$ARGUMENTS` and dropped stderr on the user's machine (both traces on the second machine) — the agent never saw the request intact nor the failures. The template now has the agent run `masora $ARGUMENTS` itself and capture BOTH stdout and stderr, state whether the operation succeeded or failed, explain any `E-*`/`W-*` diagnostic code with the concrete fix (applying the masora skill's rules), and correct a malformed invocation at most once — never loop. (`masora/skills/masora/COMMAND.md`.)


## 0.6.1 — 2026-10-01

### Fixed

- **The opencode /masora slash command** — fixes the 0.5.0 omission: `masora skill install` shipped the agent skill but no slash command, and opencode (unlike Claude Code) never surfaces an installed skill as a typed /command, so an opencode user could never actually type /masora. The installer now also writes an opencode command file (`~/.config/opencode/commands/masora.md`, packaged as `masora/skills/masora/COMMAND.md`): the template routes `$ARGUMENTS` to the installed `masora` CLI and has the agent interpret the output — success/failure stated, diagnostic codes explained with the concrete fix, applying the masora skill's knowledge-base rules. Same overwrite-as-update policy as the skill; Claude Code homes get NO command file (the skill already surfaces there, and a same-named command would shadow it); `masora skill print` stays skill-only. (`masora/skill.py`, `masora/cli.py`, `masora/skills/masora/COMMAND.md`, README.md, tests/test_skill.py.)

### Changed

- **Stacking threshold recalibrated** — `STATEMENT_MAX` 900 → 1024 (owner's call: a slightly larger tolerated statement, powers of two preferred); tests/test_sync.py's stacked fixtures now derive from the constant instead of pinning literal 1000-char statements, so future recalibrations touch one line. (`masora/audit.py`, tests/test_sync.py.)
- **Verify delegation goes through the graph** — the verify discipline gains the delegation rule: when a sub-agent is asked to verify a claim, the brief carries the claim's anchors as cppgraph entry points, and the verifier re-checks them against the graph (definitions, callers, behaviour) — verifying by restating the claim's prose is not verifying. Mirrored byte-identically in the agent instructions and the packaged skill (guard-tested). (docs/AGENT_INSTRUCTIONS.md, `masora/skills/masora/SKILL.md`.)
- **Signing: the model id, never an alias** — `name` on `source: llm` events is the exact model id that produced the verdict, never an agent or orchestrator alias (`cheap-review` tells the reader nothing about which model verified). Stated in the verify discipline (instructions + skill, mirrored), the `name` parameter description of all five MCP write tools, and FORMAT.md §4's `name` row. (docs/AGENT_INSTRUCTIONS.md, `masora/skills/masora/SKILL.md`, `masora/mcp.py`, FORMAT.md.)


## 0.6.0 — 2026-10-01

### Added


- **The gc unpublished-lineage exception + the stacked-note reflex** — `masora gc` now splits its plan by PUBLISHED-NESS: a lineage with at least one event file in origin/main's tree keeps today's behavior (one append-only `[[deleted]]` block per lineage in `deleted.toml`), while a lineage origin/main never saw is removed locally WITHOUT tombstone rows — the shared ledger records only what the shared repo knew, so a dead-born ULID (a block claim written and gc'd before any sync) never reaches it (FORMAT.md rule 10 amended in the rule's voice; MASORA_DESIGN.md §12 item 14 records the decision and narrows gc's "no git spawn" property to "no git mutation — one read-only origin/main ls-tree for published-ness": missing origin/main or no origin ⇒ everything is unpublished, a git failure is an `E-GIT` error, never a silent guess). The plan labels unpublished lineages ("unpublished — removed locally, no tombstone (origin/main never saw it)") and the final summary carries the split. This completes the stacked-note flow: when `sync` refuses with `E-SYNC-STACKED`, the remedy now names the exact loop — split into one atomic note per fact, remove the unpublished block claim with `masora gc --lineage <id>` (never published — no tombstone), then re-run sync — and the agent instructions + skill gain the standing-order reflex ("Never publish a stacked note by default", mirrored byte-identical, pinned in both docs by test). (`masora/gc.py`, `masora/audit.py`, `masora/cli.py`, `masora/skills/masora/SKILL.md`, `docs/AGENT_INSTRUCTIONS.md`, FORMAT.md, MASORA_DESIGN.md §12, docs/ARCHITECTURE.md, tests/test_gc.py, tests/test_sync.py, tests/test_docs.py.)

- **The sync-time stacked-note audit** — `masora sync` audits its pending set with stacking heuristics and refuses to publish a claim that looks like a block claim (owner's ruling: a multi-fact note is tolerated locally but must not reach the shared base — a block claim is all-or-nothing to verify, to stale and to refute). The audit (`masora/audit.py`, pure functions over the parsed pending CLAIM events — verify/doubt/refute are structurally small and skipped) fires on three conservative thresholds — `STATEMENT_MAX` 900 chars, `ANCHORS_MAX` 8 anchors, `ANCHOR_FILES_MAX` 3 distinct files per anchors' SCIP source units — constants pending calibration on the real base (the 132-lineage audit: the 7 known block claims must fire, the 125 clean ones must pass). Flagged lineages are named one per line with their fired signals and the split remedy ("split into atomic notes: corrections are new events, never edits — or pass --allow-stacked to publish anyway"); the refusal (`E-SYNC-STACKED`, exit 1) mutates nothing, and only added events are audited — a block claim already on origin/main never blocks a later sync. `--allow-stacked` is the explicit human override: the refusal becomes a per-lineage `W-SYNC-STACKED` warning riding the PR body and the flow continues. Both codes documented in docs/TROUBLESHOOTING.md the same change (two-way guarded); MASORA_DESIGN.md §12 records the decision; docs/ARCHITECTURE.md's Sync section states the gate order (after the diff, before any mutation). (`masora/audit.py`, `masora/sync.py`, `masora/cli.py`, `masora/diagnostics.py`, docs/TROUBLESHOOTING.md, MASORA_DESIGN.md §12, docs/ARCHITECTURE.md, tests/test_audit.py, tests/test_sync.py.)

- **The anti-grep-the-base retrieval rule** — the `## Retrieval budget` section names the masora base itself as off-limits to text search: step 1 gains the enumeration route (`search '*'` lists every indexed lineage with its status tuple — the way to audit or check for an existing claim before writing) and step 2's raw-file prohibition is explicit and covers grep — never read or grep the base's raw event files (`*.md` under the base directory), they carry no status: a refuted/doubted claim read raw looks valid; audit through search/explain only. Rollout lesson: an agent whose `masora search '*'` failed (before the match-all sentinel existed) fell back to `grep -rl` over the base's RAW event files, bypassing everything masora computes (the fold, the status tuples, the refutations). Mirrored byte-identical into the skill; both clauses pinned in both docs by test. (`docs/AGENT_INSTRUCTIONS.md`, `masora/skills/masora/SKILL.md`, `tests/test_docs.py`.)

- **The `*` match-all search sentinel** — `masora search '*'` (CLI and the MCP `search` tool) now enumerates EVERY indexed lineage instead of dying with `E-IDX-QUERY`: each lineage appears once, as its displayed version (its newest version when none is displayed — the `masora facts` effective-version rule), rendered exactly like a normal hit (status tuple, the `details: masora explain <lineage>` tail), with no matched questions/keywords; tombstoned lineages stay excluded and `W-IDX-STALE` is unchanged. Rollout lesson: an agent auditing a base fell back to grepping the RAW event files, bypassing the statuses. (`masora/index.py`, `masora/cli.py`, `masora/mcp.py`, README, docs/ARCHITECTURE.md, tests/test_index.py, tests/test_mcp.py.)

- **The cppgraph-side self-check inventory** (docs/CPPGRAPH_INTEGRATION.md `## 9. cppgraph-side requirements — self-check inventory`): the DIFF-able checklist of everything the cppgraph side must have implemented, written so the cppgraph agent can diff it against its own code and implement the missing items — each row pairs the requirement with its verification shape (a behavior or a test): the injection scope (explain/who_calls/what_it_calls only), binary detection (instant silent skip), the `CPPGRAPH_MASORA` flag checked before any spawn, the spawn's hardening (2 s timeout, detached stdin, process-tree kill, stdout cap, failure = no injection never an error), the fail-closed parser (strict integer contract_version, whole-document rejection on a wrong type, additive-optional enrichment tolerated, unknown enums inert, summary ≤ 120 + printable), the rendering rules (the budget, the visible truncation, the trust matrix, the NOT envelope, the stale note only alongside facts, dedup, no caching), the repo_root semantics (a recorded-but-missing root skips; legacy graphs fall back to cwd), the PENDING items called out explicitly (input hygiene + the configurable `CPPGRAPH_MASORA_MAX_FACTS` fact count — implement next, not yet evidenced there) and the read-only invariants. Docs-only change.

### Changed

- **`masora search <query>` — the base directory is now optional**: omitted, it resolves like `masora facts` and the MCP tools (mappings on the normalized `origin` remote, then `default_base` — MASORA_DESIGN.md §9) and the header prints the resolved base; an explicit base_dir keeps winning and the base gate is unchanged. When nothing resolves, the refusal carries the new `E-SEARCH-NO-BASE` (documented in docs/TROUBLESHOOTING.md the same change) with the cause-specific remedy — not a Git checkout, no readable `origin`, unmapped repo with no `default_base`, or a broken mapping/config. MASORA_DESIGN.md §12 records the owner's decision this implements around: single base per project is the expected usage; the multi-base config stays a latent capability documented only in internal docs. (`masora/cli.py`, `masora/diagnostics.py`, docs/TROUBLESHOOTING.md, docs/ARCHITECTURE.md, MASORA_DESIGN.md §12, tests/test_index.py.)

## 0.5.1 — 2026-09-30

### Changed

- **The masora skill's trigger names behavior questions** (live-rollout diagnosis: a "what happens when one updates the shard key" question was triaged as code-navigation and answered WITHOUT masora — the categorical description plus the "not for general programming tasks" exclusion pushed behavior questions out of the trigger, and nothing named "what happens when X" — the base's core content; the two verified claims it missed: delete/insert ordering not guaranteed, updateLookup inapplicable). The frontmatter description now reads: "Use when answering or investigating repository-specific behavior — including 'what happens when X' questions — architecture, product semantics, past decisions, trade-offs, or non-obvious conventions in a repository that may be served by a Masora base. Not for general programming tasks." (the exclusion stays — behavior questions are not general programming, and the description now says why they belong). The "Search before investigating" section gains the TRIAGE rule, first bullet: a "what happens when X" question is a knowledge question, not a code-navigation task — search the base before answering, even when code pointers are requested; the recorded claims carry verified consequences (ordering guarantees, edge cases) that a fresh code read under-weights. The skill's canonical tail mirrors it (byte-identical); the frontmatter and substance guards assert the new substrings. (`masora/skills/masora/SKILL.md`, `docs/AGENT_INSTRUCTIONS.md`, `tests/test_docs.py`.)

## 0.5.0 — 2026-09-30

### Added

- **The optional `keywords` field on claims** (FORMAT.md §4, the questions' sibling with the same mechanics) — 1–10 non-empty single-line strings: the ALTERNATE VOCABULARY a reader might query with (synonyms, domain terms, event/test/component names); exact duplicates rejected (`E-KEYWORDS`, the dedicated diagnostic documented the same change); claim-only — the targeted kinds reject the field; additive-optional (`format_version` stays 1), no fold/anchor/lineage semantics. The write path secret-scans every keyword item; the `note` tool accepts `keywords` (minItems 1, maxItems 10) and persists them, with the description now stating the four-part split: summary = the title, statement = the explanation, questions = the reader queries, keywords = the alternate vocabulary. **The per-keyword index**: the schema gains a `keywords` FTS5 table (keyword, version, keyword_ordinal) — SCHEMA_VERSION "4", the disposable-rebuild path (a foreign-version DB refused with `E-IDX-CORRUPT`, old bases rebuild cleanly) — and the search union becomes THREE sources (content summary/statement + questions + keywords), each hit carrying `matched_keywords` beside `matched_questions` and the render showing `matched keyword:` lines; the `masora facts` contract is untouched (version 1, no shape change — asserted). (`masora/schema.py`, `masora/write.py`, `masora/mcp.py`, `masora/index.py`, FORMAT.md §4, docs/TROUBLESHOOTING.md, tests.)

- **Search discoverability** — every search hit group (CLI and MCP render) now ends with `details: masora explain <lineage>` (the lineage id verbatim): the door from a search hit to the fresh full story. (`masora/cli.py`, `masora/mcp.py`, `tests/test_index.py`, `tests/test_mcp.py`.)

- **The retrieval-budget skill pass** (docs/AGENT_INSTRUCTIONS.md + the skill mirror, byte-identical sections): a new `## Retrieval budget` section pins the ORDER — search masora (a zero-result retries ONCE with alternate domain words or a reader-style question: summaries and questions/keywords may use different vocabulary) → `explain` each relevant lineage before relying on it (search is the short index; explain is the fresh fold, full statement, anchors, evidence — never read raw masora event files) → cppgraph for C++ structure/symbol identity → ONE narrow text/file search ONLY when the answer may live outside the graph (comments, doc-comments, non-C++ tests such as jstests, test names, configs, prose), constrained to the known directory/pattern — never start with a repository-wide grep, never silently broaden a search (an absent path/filter is fixed, not widened). The anti-grep rule in "How to note well" is now two-sided: graph for symbols/structure; targeted text search is legitimate for comments, tests, configs and prose (the graph does not index them). "Verify discipline" gains the tests-as-evidence rule: a proof may live in a test — locate it with the file tools and record it in the evidence.

- **The cppgraph-side input hygiene** (docs/CPPGRAPH_INTEGRATION.md, new `## Input hygiene (cppgraph side)`): unknown parameters are REJECTED, never ignored (the typo'd-param class silently returns unfiltered results); an absent path/filter target is an EXPLICIT error, never a silent whole-repo broadening; strict-argument tests required on the cppgraph side. §6's fact budget is configurable (default 2 — e.g. a `CPPGRAPH_MASORA_MAX_FACTS` value; higher allowed); the ≤ 60-token guidance stands.

- **The cross-analysis tests×code idea** (MASORA_DESIGN.md §12 item 11, marked OPEN, not scheduled): cppgraph + masora could correlate tests with the code — and the claims — they exercise, to surface untested behaviours, detect claims whose evidence cites no test, and propose test extensions.

- **`masora explain <base-dir> <lineage-id> [--repo]` + the `explain` MCP tool** — the complete story of ONE lineage, statuses included (promoted out of the out-of-scope list; the rollout justification: an agent wanting one lineage's full story improvised a massive rg over masora's directories and read RAW event files — which carry NO status, so a refuted/doubted claim looked valid). The state is computed FRESH from the lineage's event files (checker's discovery/parse helpers, content-based; the index is never consulted — a stale index cannot lie here) after the base gate (`E-NOT-A-BASE`, other base errors refuse); the render is one readable block: the status tuple (resolution / `verified(<source>)`/`unverified` / flags), the effective version's summary, statement and questions, the anchors with their CURRENT match state (`matched`/`changed`/`not_found` via the providers when a repo is available — `unknown` otherwise, never a guess), the full event chain in ULID order (id, kind, writer, one-line what-it-does via the targets chain, `[refuted]`/`[inactive]` markers) and the ACTIVE verify's evidence in full. An unknown id is a clean `E-EXPLAIN-UNKNOWN` diagnostic (documented in docs/TROUBLESHOOTING.md the same change); nothing is written, ever; the MCP and CLI surfaces render the same text. (`masora/explain.py`, `masora/mcp.py`, `masora/cli.py`, `masora/diagnostics.py`, `tests/test_explain.py`, `tests/test_mcp.py`, README, docs/ARCHITECTURE.md, docs/AGENT_INSTRUCTIONS.md + the skill's tools list.)

## 0.4.0 — 2026-09-30

### Added

- **`masora skill install` / `masora skill print`** — user-friendly skill installation (the curl runbook dies): the agent skill now lives INSIDE the package (`masora/skills/masora/SKILL.md` — one canonical copy carried by the wheel; the `docs/skills` copy is deleted and the sync guards in `tests/test_docs.py` read the packaged file via `importlib.resources`, with docs/AGENT_INSTRUCTIONS.md staying the source of truth). `masora skill install` writes the packaged SKILL.md into every DETECTED agent-framework skills dir under the user's home — `~/.claude/skills/masora/` when `~/.claude` exists, `~/.config/opencode/skills/masora/` when `~/.config/opencode` exists, other frameworks skipped silently — creating the target dirs and OVERWRITING on re-run (that is the update path), printing `installed: <path>` / `updated: <path>` per target; when no framework dir is found it says so and points at `masora skill print`, which pipes the packaged content to stdout for any other mechanism; exit 0 either way. `masora setup` and `masora init` now print `masora skill install` on success (replacing the copy-path hint). README's install story becomes: `uv tool install` → `masora setup` → `masora skill install` — no curl. (`masora/skill.py`, `masora/cli.py`, `masora/setup.py`, `masora/init.py`, `tests/test_skill.py`, `tests/test_docs.py`, `tests/test_setup.py`, `tests/test_init.py`, README, docs/ARCHITECTURE.md.)

## 0.3.3 — 2026-09-30

### Added

- **The CHANGELOG-invariant guard** (tests/test_docs.py): three structural checks over the file's `## ` section headers, with HTML comments stripped first (the entry template at the bottom lives in one — its `## [X.Y.Z]` line must not trip the guards): no duplicated version header, at most one `## 0.4.0 — 2026-09-30`, and version sections sorted newest-first (a monotonic non-increasing semver ordering). Violations fail with the offending header(s) and their line numbers; the suite runs in the pre-commit hook, so a pass creating a second `[Unreleased]` — or a release sed converting stacked headers into duplicated version sections — is refused at commit time.

## 0.3.2 — 2026-09-30

### Added

- **The "Completeness check" section** in the agent instructions (docs/AGENT_INSTRUCTIONS.md) and the installable skill's copy (docs/skills/masora/SKILL.md), placed after "How to note well": the checklist an agent runs to consider a note done, in two parts — the tool-enforced half (a violation refuses the write: `format_version` set, provenance complete, `summary` ≤ 120, anchors resolved through the graph or an explicit `unanchored` + reason, credential-shaped content refused, exact-duplicate questions rejected) and the authoring half the tools cannot judge (a self-contained summary; the statement carries context, mechanism and pointers; EVERY symbol whose change would invalidate the claim is anchored; the questions name the reader queries; one claim = one fact) — closing line: a note missing an authoring-side item is not done — finish it or split it. The header-sync guard covers the new section automatically and the closing line is pinned in both files by test. Docs-only change.

- **Standing orders, search before memory, and the before-compacting evidence ritual** in the agent instructions (docs/AGENT_INSTRUCTIONS.md) and the skill's copy (docs/skills/masora/SKILL.md — sections stay byte-identical; live-rollout evidence: an agent there described itself as "I only write when told; I don't consult actively; the facts come to me via the graph"). "When to note" is reframed as STANDING ORDERS: when a trigger fires, the agent notes — without being asked and without asking permission — and the anti-fear justification is explicit: proactive capture is safe because everything is born `source: llm`, `unverified` (review is the trust path); waiting for the user's order loses the moment and the knowledge. "Search before investigating" gains the before-memory rule: before answering a product-semantics, architecture or decision question from memory or external docs, `search` the base first — it may already hold (or contradict) the answer; web/doc confirmation remains the fallback, not the default. A new "Before compacting" section (after "Completeness check"): compaction keeps the live state and may drop superseded verifies — when a base's verifies carry replayable evidence you may need later, FIRST write a terminal verify per lineage whose evidence is self-contained (report the replayable bullets); compact keeps the live state, not the archives (a `compact --preserve-evidence` option stays the candidate if the need recurs). The substance guards assert all three in both files. Docs-only change.

## 0.3.1 — 2026-09-30

### Added

- **Atomic-claims authoring guidance** — the owner's rule, one claim = one verifiable fact: "If you wrote 'and' twice, that is several claims: split them; each fact gets its own anchors and its own verification — a block claim is all-or-nothing to verify, to stale and to refute." The imperative opens the "How to note well" rules in docs/AGENT_INSTRUCTIONS.md, the installable skill's copied section tracks it (the header-sync guard stays green), and the `note` inputSchema description carries the clause ("prefer atomic claims — split multi-part knowledge into several notes"), asserted by substring tests in both guard files. (`docs/AGENT_INSTRUCTIONS.md`, `docs/skills/masora/SKILL.md`, `masora/mcp.py`, `tests/test_docs.py`, `tests/test_mcp.py`.)

## 0.3.0 — 2026-09-30

### Changed

- **Graph-first anchor discipline in the agent instructions** — the "How to note well" rules gain three state-form imperatives (rollout lesson: an agent delegated note-research to sub-agents with rg-as-entry-point briefs — the sub-agents followed the imposed method, never the graph, and cppgraph sat unused): locate symbols with the code graph (cppgraph `find`/`explain`), never by text-grep guessing — pass exact identities or name fragments, `ambiguous`/`not_found` returns candidates; verify structure/behaviour claims against the graph (callers/callees/definitions) before writing — a note is anchored to what the graph confirms; when delegating research to sub-agents, hand them the graph entry points IN THE BRIEF — they follow the method the brief imposes, not the tools you would use. The `note` inputSchema description carries the same sentence, and the installable skill's copied section tracks the rules (the header-sync guard stays green). (`docs/AGENT_INSTRUCTIONS.md`, `docs/skills/masora/SKILL.md`, `masora/mcp.py`, `tests/test_docs.py`, `tests/test_mcp.py`.)

### Added

- **The masora skill** (docs/skills/masora/SKILL.md) — the installable form of the canonical agent instructions, per the design review: the frontmatter triggers on PROJECT-KNOWLEDGE questions only ("repository-specific behavior, architecture, product semantics, past decisions, trade-offs, or non-obvious conventions in a repository that may be served by a Masora base" — not general programming), and the body is conditional by design: it never claims a repository IS served; the ritual tries the `search` MCP tool when it is available, reads `E-MCP-NO-BASE` as a resolution/configuration/context matter — never as evidence that the project has no knowledge — never inspects the checkout for Masora markers (the design forbids them), never re-runs `masora setup` on its own, and continues normally otherwise; the rule sections (search before investigating, status reading, when to note, note quality with the `questions` field, verify discipline, etiquette) are copied from docs/AGENT_INSTRUCTIONS.md — the single source of truth — and `tests/test_docs.py` asserts the skill carries every canonical header so neither copy silently diverges. `masora setup` and `masora init` print the install hint on success (the skill file's location in the masora checkout; copy-install — masora never writes into a code repo, asserted by test); README's Agent-instructions section offers both routes (the skill and the paste block) with no universal-path claims.

- **The optional `questions` field on claims** (FORMAT.md §4) — 1–5 non-empty single-line strings, each phrased as the READER QUESTION the claim answers (concept names, behaviours, decisions — specific, never generic like "How does this work?"); exact-duplicate strings are rejected within a list (`E-QUESTIONS`, the dedicated diagnostic); claim-only — every other kind rejects the field; additive-optional like `name`/`effort` (`format_version` stays 1) and with no semantics in the fold, the anchors or lineage identity. The write path secret-scans every question item (the same `E-WRITE-SECRET` protection as summary/statement/reason/evidence) and the `note` tool accepts `questions` (minItems 1, maxItems 5) and persists them. **The per-question index**: the SQLite index gains a separate FTS5 table `questions` (one row per question: question, version, question_ordinal) — schema version 3, disposable-rebuild as always (a foreign-version DB is refused with `E-IDX-CORRUPT`; old bases without questions rebuild cleanly) — and the search flow unions the content hits (summary + statement only; questions never dilute the main table) with the question hits, surfacing the distinct MATCHED question texts per hit (`SearchHit.matched_questions`; a question-only hit surfaces its version's content row); the CLI and MCP `search` render a `matched question:` line per matched question. The `masora facts` contract is untouched: `CONTRACT_VERSION` stays 1 and the JSON shape carries no questions (questions serve matching, not the envelope — asserted by test). (`masora/schema.py`, `masora/write.py`, `masora/mcp.py`, `masora/index.py`, `masora/cli.py`, FORMAT.md §4, docs/AGENT_INSTRUCTIONS.md, docs/ARCHITECTURE.md, README, docs/TROUBLESHOOTING.md.)

## 0.2.3 — 2026-09-30

### Changed

- **The no-base diagnostic tells the truth about WHY** — `E-MCP-NO-BASE` stays the single code and the TEXT now carries the cause, from a structured detection (`write.origin_state`) used only for the failure diagnostic, never for resolution: `not_git_worktree` (the path is not inside a git worktree — the live rollout shape: a workspace parent passed as `repo_root`) reads "repo_root is not a Git checkout — pass the code checkout itself (not its workspace parent), or pass base explicitly"; `git_without_origin` (a worktree whose origin is missing/unreadable) reads "the checkout has no readable origin, so mapping-based resolution is unavailable — configure origin, configure default_base, or pass base explicitly"; a readable-but-unmapped origin keeps the "run masora setup" remedy, and an omitted `repo_root` keeps its ask-for-the-repo text. The resolution success path is unchanged — explicit base > mapping on origin > `default_base`; an origin-less checkout with a valid `default_base` or explicit base succeeds exactly as before, and an explicit base pointing at a non-base directory refuses with `E-NOT-A-BASE`, not the new texts. `masora facts` shares the detection for its `E-FACTS-NO-BASE` wording (same causes, adapted remedies — no "pass base explicitly", its contract forbids one; exit 1 and empty stdout unchanged). (`masora/write.py`, `masora/facts.py`, `tests/test_mcp.py`, `tests/test_facts.py`, docs/TROUBLESHOOTING.md.)

### Added

- **The evaluation protocol** (docs/EVALUATION.md) — the pre-registered paired A/B protocol for judging whether Masora changes agent behaviour (MASORA_DESIGN.md §13's phase objective): each of ~20 routine tasks runs twice with the same agent, model and fresh sessions — WITHOUT (no MCP, no injection) vs WITH (`masora mcp` + the `CPPGRAPH_MASORA=1` injection); the corpus is grounded in the live base's recorded summaries (8 example templates: resume-token invalidation, the change-event split threshold, bring-up order, the refuted resume-reopen claim, commitShard's lock, SBE slot choice, plus ≥ 4 control tasks the base cannot inform — false help counts against Masora); scoring counts repeated wrong deductions (a confident assertion a recorded claim contradicts — graded by a human with the task's claim list), tool calls, total tokens and injected tokens (the §6 rendering budget bounds the tax at ≤ ~60 tokens per response); the procedure pins a seed-check (`masora check` clean + a fresh index immediately before the batch), a seeded-random task × condition order and a one-row-per-run recording sheet; the verdict rule: strictly fewer repeated wrong deductions AND no token-cost regression beyond the injected tokens (`sum(c_WITH − d_WITH) ≤ sum(c_WITHOUT)` and no tool-call regression) — the numbers decide adoption, a failed verdict is acted on, not narrated away; the honest limits (single-author bias, small n, lexical recall misses, prevention-only measurement) are part of the protocol. A protocol amended after seeing results is void: rule changes discard every number scored under the old one. Docs-only change.

- **The base gate** — `check_base()` refuses up front with `E-NOT-A-BASE` ("not a base: no base.toml at <dir>") when the passed root has no `base.toml`, instead of walking the tree into confusing stray-file errors; one gate covers every consumer (the CLI commands, the write-path pre/post checks, the compact/gc gates). The CLI dispatch for `check`/`gc`/`compact`/`index`/`search` adds the smart remedy on refusal: the origin remote of the current working directory resolved through the config mappings (`write.auto_base`, failure-tolerant) prints a second line, "the base configured for this repo: <path>", when one resolves — the commands still exit 1, the gate refuses and never auto-corrects. Rollout lesson: an agent passed the checkout root instead of the base directory; gc then wrote tombstones one level too high and the check error read as "invalid file" instead of "not a base". Test bases gain their `base.toml` (init and setup always created it). (`masora/checker.py`, `masora/cli.py`, `masora/diagnostics.py`, `tests/test_base_gate.py`, docs/TROUBLESHOOTING.md, FORMAT.md §1/§7, docs/ARCHITECTURE.md.)

## 0.2.2 — 2026-09-30

### Changed

- **Directory slugs derive from `slugify_summary`** (`write.slugify_summary`, one shared function for the lineage-home creation, `compact --rehome`'s bare-home derivation and sync's PR display): camelCase and acronym runs split at case boundaries (`$changeStreamSplitLargeEvent` → `change-stream-split-large…`, `XMLParser` → `xml-parser`, `honorMaxTimeMSDuringBatch` → `honor-max-time-ms-during-batch`), non-alphanumeric runs collapsed to `-`, lowercased, the leading article (`a`/`an`/`the`) stripped, cut at the word boundary under 30 characters (single tokens hard-cut), and a summary with no alphanumeric content falls back to `lineage` (the caller appends `-{ULID}`; the function never handles collisions). Existing directories keep their slugs (the label is immutable — `--rehome` derives only bare `<ULID>` homes and keeps an existing slug verbatim), event-file format and ULIDs are untouched and `check` stays path-indifferent. (`masora/write.py`, `masora/compact.py`, `masora/sync.py`, `tests/test_write.py`, `tests/test_mcp.py`, `tests/test_sync.py`, FORMAT.md §1, docs/ARCHITECTURE.md.)

## 0.2.1 — 2026-09-30

### Fixed

- **`masora status` showed "no index" for every sub-directory base** — status resolved the indexes directory from the base's CONFIG KEY (`config.indexes_root() / config.slug(name)`), while `masora index`/`search`/`facts`/the MCP tools all route through `index.index_db_path`, which derives the directory from the BASE DIRECTORY's basename — and the two disagree whenever a base's clone holds the events in a sub-directory (the `#<path>` setup form: config key `employees`, base dir `masora_mdb`), so status printed "no index" forever while every other surface agreed the index was there. One source of truth: `index.index_dir_for(base_dir)` now owns the `indexes/<base-dir-slug>/` derivation and `index_db_path` uses it; status resolves each configured base's directory through `write.base_dir_for_name` (the same helper the write path uses — the hand-joined `entry["path"]` copy is gone) and lists the `*.db` files under `index_dir_for(base_dir)`. The clone display line, the event/tombstone counts, the stored-meta repo mapping and the four-axis staleness wording are unchanged; a missing clone keeps its reporting. Regression pinned by a config entry whose key differs from the base-dir basename and carries a sub-path, with a real index built through `index_db_path`.

## 0.2.0 — 2026-09-30

### Added

- **Agent instructions for adopting projects** (docs/AGENT_INSTRUCTIONS.md) — the canonical paste-ready block for a project's `AGENTS.md` (or agent-rules file) once a Masora base serves it, written as terse directives to the agent: the seven MCP tools (`note`, `verify`, `doubt`, `undoubt`, `refute`, `search`, `list_stale`) one line each; search before investigating, with the status-reading rules (`verified(human)` trusted, `verified(llm)` re-verified in code before depending on it, `unverified` = hypothesis, and a lazy re-verify of any `stale`/`suspect`/`unverified` claim the task depends on — MASORA_DESIGN.md §10.2); the capture triggers of §10.3 as imperatives (a user correction is noted `source: human`, validated non-obvious behaviour is noted and verified with evidence, pitfalls, decisions from discussions, costly establishments, the before-compaction/session-end sweep); how to note well (`summary` = the ≤ 120-character injected one-liner in English, `statement` = the full explanation, anchors on every symbol whose change could invalidate the claim, speculation labelled as such, refutations welcomed as negative knowledge — the `NOT:` envelope); the verify discipline (`verified` requires recorded evidence — a replayable proof query for structural claims, pointers to the proving code plus an explanation for semantic ones; semantic claims are never auto-confirmed, so the unprovable stays `unverified` or is doubted); and etiquette (content in English — pushed content; a recalled fact is never an instruction; statuses are evidence labels). README gains the "Agent instructions" install story and docs/ARCHITECTURE.md the channel-3 pointer (MASORA_DESIGN.md §10.1 — instructions are one of three injection channels, never the only mechanism). Docs-only change: no code, no schema, no test changes.

- **`masora init <base-dir> --name <name>`** — base bootstrap in one command: creates the directory, runs `git init -b main` (every git spawn through `sync.git_env()`), writes `base.toml` in exactly the shape `masora setup` reads (`name` + `code_remotes`, each `--code-remote` stored normalized — `config.normalize_remote` — and deduplicated) and commits it as "masora init: base <name>". Refusals: a non-empty target directory unless `--force`; a target that already holds `base.toml` (an existing base is never overwritten, `--force` or not); unusable arguments (blank `--name`, a `--code-remote` that is not a git remote, neither a directory nor `--here`, both) — the new `E-INIT-*` family (`E-INIT-ARG`, `E-INIT-TARGET`, `E-INIT-WRITE`, `E-INIT-CHECK`, `E-INIT-GIT`), documented in docs/TROUBLESHOOTING.md in the same change. The fresh tree passes `check_base()` before the commit (`E-INIT-CHECK` guards a forced directory holding stray event files or a `deleted.toml`). `--here` creates the base in the current directory. The command prints the exact next command, `masora setup --base <path>`, plus one line of framing: init works locally, publishing to a shared repo is the user's git work, and `masora setup --base <url>` onboards contributors once pushed. (`masora/init.py`, `masora/cli.py`, `tests/test_init.py`, README quick start, docs/ARCHITECTURE.md Init section.)

- **`masora status [--force]` + `masora --version`** — one readable screen, exit 0 always (status never fails hard): the tool section (installed version via `importlib.metadata` with an `unknown` fallback when not installed as a distribution, the supported `format_version`, the facts `contract_version`, the index `schema_version`); the bases section (per `[bases.<name>]` config entry — the local clone path with exists/missing, the clone's `origin` remote resolved from git with the configured entry as fallback, an event file + `deleted.toml` tombstone-block count over one cheap walk, and per index database under the base's indexes directory the repo it was built for plus the `index_stale_reason()` four-axis wording, `fresh`/`no index`/`unreadable` as applicable); and the update check — the latest release from `https://api.github.com/repos/rakiz/masora/releases/latest` (stdlib urllib, 2 s timeout) compared by numeric semver triplet, `up to date` or `update available: vX.Y.Z — <url>` with the `uv tool install --force git+https://github.com/rakiz/masora` hint, cached for 24 hours in `~/.local/share/masora/update-check.json` (`$MASORA_HOME` relocates it — `config.update_check_path()`), `--force` refetching now, and offline/HTTP/malformed answers printing `update check unavailable (offline)` and never raising; the fetcher is an injectable module-level callable, tests stay hermetic. (`masora/status.py`, `masora/config.py`, `masora/cli.py`, `tests/test_status.py`, README Status section, docs/ARCHITECTURE.md Status section.)

- **`masora compact <base-dir> --rehome`** — layout migration without history compression: every surviving file moves into its lineage's canonical single home `YYYY-MM/<slug>-<lineage>` (FORMAT.md §1) — the directory holding the founder file, renamed from the bare `<lineage>` form by prepending `write.lineage_slug(founder summary)` (an existing slug is kept verbatim as the immutable label; a summary yielding no slug keeps the bare form) — and a lineage split over several month buckets merges into the founder's home, vacated directories pruned. Moved files keep their ULIDs and bytes (merge-safe, dedup by id); nothing is deleted by rehoming, so a rehome-only run writes no tombstones; a run that also drops events tombstones the drops per the compact rules while the survivors land in the canonical home. Plan-then-confirm (`--rehome` plan prints each lineage's home and its `from → to, N file(s)` moves, exits 3 without `--yes`); pre/post `check_base` green (`check` is content-based — moves cannot change it — asserted anyway); already-canonical lineages are untouched, founderless lineages have no canonical home to derive and stay untouched, so a second run is a no-op. (`masora/compact.py`, `masora/cli.py`, `tests/test_compact.py`.)

- **`masora compact <base-dir>`** — per-lineage compression to the minimal live witness set: the event files still contributing to the lineage's current §6 fold state survive (same ULIDs, byte-identical, merge-safe by id); pure history — superseded versions, undone events, inactive verifies — is dropped. The witness (founder claim, effective version, its active verifies with their sources, active doubts on kept verifies, all version refutes under `resolution: none`, the newest version's refutation under `restored`) is closed over `targets`/`contradicts` and over the active refute/unrefute/undoubt events targeting kept events, and carries a per-lineage proof: the witness fold must equal the full fold — any divergence refuses the whole run fail-closed (`E-COMPACT-DIVERGE`, nothing written); the rule is brute-forced over every acyclic event DAG at n ≤ 4 plus sampled n = 5 DAGs and every fixture tree. Plan-then-confirm like gc (plan exits 3, `--yes` executes, pre/post `masora check` with `E-COMPACT-CHECK` on post-check failure plus a tree-wide status re-verification). Dropped events known to the shared repo (present on `origin/main` or the sync merge-base — the same git plumbing as sync's diff, no fetch; no remote/merge-base → no tombstones) are tombstoned per-event in `deleted.toml`'s new `[[deleted_events]]` table (same `{lineage, ulids}` block shape, append-only by content, union-merged by sync, which accepts tombstoned per-event deletions alongside gc's whole-lineage ones); unpublished events are deleted silently.

### Changed

- **Clearer `E-MCP-NO-BASE` remedy and `note` field-split contract** — the no-base diagnostic states the remedy for its cause: a call that omits `repo_root` (the read tools then fall back to the base directory, which by construction matches no remote) is told "pass repo_root (the checkout you are asking about) — the base is resolved from that repo's origin remote"; a code repo matching no `[[mappings]]` entry with no `default_base` configured is told "run masora setup --base <url> in this checkout, or pass the base parameter explicitly"; an unknown explicit `base` names neither remedy. The `note` inputSchema description states the field contract in one sentence — `summary` is the injected one-liner (≤ 120 characters, what cppgraph surfaces), `statement` the full text (no length constraint, the detailed explanation) — and that content is written in English (base event files are pushed content); the summary/statement field descriptions match the split and the write tools' `reason`/`evidence` descriptions carry the language expectation. (`masora/write.py`, `masora/mcp.py`, `tests/test_mcp.py`; the diagnostic's docs/TROUBLESHOOTING.md row and docs/ARCHITECTURE.md wording state the two causes.)

- **Readable sync PR** — `masora sync` renders the pull request as a plain-English changelog of the pending set: the title mirrors the counts (`masora sync: 2 claims, 1 verification, 1 doubt`, plus a `N tombstoned` segment when compact/gc removals ride along) and the body lists one line per pending event — claims as `<lineage slug or ULID>: "<summary>" — <name or source>`; verifies as `verified "<summary of the resolved target claim>" — by <name or source> — N evidence item(s)`; doubt/refute/undoubt/unrefute as `<doubted/refuted/undoubted/unrefuted> "<resolved target's summary>" — <reason truncated to 80 characters> — by <name or source>`; tombstone additions as one `N events removed by compact/gc` line. Target resolution follows the `targets` chain over the scanned event tree (a doubt on a verify resolves to the verified claim's summary) and falls back to the target ULID when unresolvable; the lineage slug is the founder-summary slug of the human-named-directory convention. The YAML diff on the pending branch stays the machine-audit surface. (`masora/sync.py`: `EventFile` carries `targets`/`source`/`name`/`reason`/`evidence_count`; `tests/test_sync.py`.)

- **Human-named lineage directories** — the write path lays each lineage out as one single directory `YYYY-MM/<slug>-<lineage-ULID>/` (FORMAT.md §1): the slug is a deterministic lowercase ASCII form of the founder claim's summary (`[a-z0-9-]`, at most 24 characters, word-boundary trimmed; a summary with no ASCII word falls back to the bare lineage ULID), created with the founder in the founder's month and immutable thereafter. Every later event of the lineage — verify, doubt, refute, new versions — looks the lineage up in the base tree by ULID suffix and joins the existing directory verbatim, whatever its slug or month bucket; extensions are never re-bucketed by the current month. A legacy split (one lineage spread over several month buckets) resolves deterministically to the directory holding the founder file, else the sorted-first match, and never creates a third directory. `masora check` stays path-indifferent (it globs `**/*.md` and validates content only), so moving or renaming lineage directories changes nothing; the layout wording in FORMAT.md §1, MASORA_DESIGN §7 and docs/ARCHITECTURE.md states the single-home rule. (`masora/write.py`: `lineage_slug`, `event_relpath(data, base_dir)`; `tests/test_write.py`.)

## 0.1.0 — 2026-09-29

Grouped by capability — what this version ships. The full suite is 441 tests green.

### Added

- **`masora check`** — standalone whole-tree validation of a base against FORMAT.md §7: per-kind schemas, YAML canonicalization (§4), cross-file references, cycle rejection (topological, clock-free), founder resolution, `deleted.toml` tombstones, plus the §6 fold producing a per-claim status envelope (exit 0 clean / 1 errors / 2 warnings only). The fold rule is proven by an executable spec: brute force over all 13,512 event-graph DAGs at n ≤ 4 against an independent topological oracle (order-independence across 4 evaluation orders) plus 10,000 sampled 5-event DAGs (`tests/test_fold_bruteforce.py`).

- **`masora sync`** — publication: a local `check` gate, the append-only content diff by event-id identity against the merge-base and `origin/main` (rewrites and deletions are tampering; tombstoned whole-lineage deletions are accepted and applied to the merged tree), the founder rule for new v2+ claims (self-contained lineages), and merged-result validation on `origin/main` + pending overlay with a union tombstone so gc-vs-extension races surface before publication. Publication is one `masora/pending` plumbing commit pushed `--force-with-lease` and one PR opened or updated (`gh` when available, compare-URL fallback); `--push` merges directly for a solo base, `--drop` discards the pending set. Every git spawn goes through `masora.sync.git_env()`, isolating inherited repo-location `GIT_*` variables.

- **`masora setup --base <url>[#<path>]`** — onboarding in one command: partial clone + sparse checkout of the base into `~/.local/share/masora/bases/<name>` (a sub-directory base is the sparse-checkout root; root bases widen to the full tree); a base declares itself via `base.toml` (name + served code remotes) at its repo root; the local `~/.config/masora/config.toml` is written or merged (`[bases.<slug>]` + one `[[mappings]]` block per served code remote, `code_remote` stored normalized — lowercase host, no scheme, no user/port prefix, no trailing `.git` — via `masora/config.py`). Same-remote re-runs update in place; a different remote under the same name is refused. The default story is one shared base per team (the multi-base config stays a capability); `MASORA_HOME` relocates config and clones for tests and special cases.

- **`masora gc --lineage`** — whole-lineage deletion on explicit, confirmed request, never suggested (a fully-refuted lineage is negative knowledge): plan-then-confirm CLI (`--lineage` repeatable, plan exits 3 without writing, `--yes` executes), `masora check` before and after the mutation, one append-only-by-content `[[deleted]]` block per lineage in `deleted.toml`, event files removed and emptied parent directories pruned. gc commits nothing — the deletion is an ordinary git commit, or travels through `masora sync` like any pending change.

- **`masora index` / `masora search`** — a full-rebuild-only SQLite index (WAL, atomic replace, safe to delete anytime) at `<masora_home>/indexes/<base-slug>/<repo-slug>-<path-hash>.db`, one per base × code repo: §6.2 status tuples per lineage (resolution `current`/`stale`/`restored`/`none` × verification `verified(<source>)`/`unverified` × flags `suspect`/`doubted`/`pending`/`unknown`/`unanchored`) as pure functions over the fold, injectable anchor-provider registries (an unavailable provider yields `unknown` shadowing the resolution, never a guess), FTS5 search over summary + statement (case/accent-insensitive), and the four-axis drift warning `W-IDX-STALE` (base HEAD / repo HEAD / graph indexed commit vs recorded, plus filesystem freshness). The shipped `file` provider hashes whitespace/comment-normalized checkout content — a reformat does not stale claims. **Filesystem-freshness staleness axis**: the index meta records the build moment (`built_at`, UTC ISO — stored since the index shipped, now read back); `index_stale()` walks the base tree (event `*.md` + `deleted.toml`, one cheap walk per read, no caching) and fires the fourth axis when any file is newer than `built_at` (~2 s tolerance) with reason "events written since the index build (uncommitted or unsynced writes move no git HEAD)" — an UNCOMMITTED `note` moves no HEAD, so the three git axes stay quiet while `masora facts`/`search` would silently miss the just-written claim; the reason text flows into the `W-IDX-STALE` message (CLI and MCP `search`), `masora facts` keeps the bare `stale_warning` boolean (no contract shape change), and a rebuild makes the index fresh again.

- **`code` anchor provider over a cppgraph graph store** (`masora/providers.py`): the newest `<repo>/.cppgraph/*.graph.db` (store schema v5: `files`/`symbols`/`edges`/`meta`) is opened read-only and the FORMAT.md §4 anchor identity (the SCIP symbol string, opaque-but-structured) is matched verbatim against `symbols.symbol`. Definition fingerprint: sha256 of the whitespace/comment-normalized source of the definition range (`symbols.line`..`end_line`, 0-indexed; a single definition line on stores without body extents). Edge-set fingerprint: sha256 of the sorted distinct callee SCIP strings of `calls` edges only (§5.4). Neighbour snapshot: 1-hop callers ∪ callees mapped to their edge-set hashes (§12.4) — `suspect` fires on call-neighbourhood drift. Store schema-version gate: ONLY the exact store schema the reader was learned against (v5) is accepted — a missing, unparsable, older or newer `schema_version` meta row makes the store unavailable (`unknown` shadows the resolution, never a guess) and `W-IDX-GRAPH` fires naming the seen version. Currency policy (§5.2): the store's `meta.source_commit` must equal the `--repo` git HEAD, decided once per index build for all code anchors (the registry contract has no per-anchor availability channel); mismatch/unverifiable → `unknown` shadows + `W-IDX-GRAPH` stating why; a missing graph store stays silent `unknown` (cppgraph is optional). `masora index` takes `--cppgraph <db>` (explicit store) and `--no-cppgraph` (file-only); the used graph commit is exposed on the result and in the index meta (`graph_commit`, `graph_db`).

- **`masora mcp` — MCP server + write path** (`masora/mcp.py`, `masora/write.py`): a hand-rolled minimal MCP stdio server — newline-delimited JSON-RPC 2.0, no SDK and no runtime dependency beyond pyyaml (MASORA_DESIGN.md §12.9), protocol version pinned to `2025-06-18` and negotiated the standard MCP way (the initialize result always carries it; malformed initialize params are -32602), methods `initialize` / `notifications/initialized` / `tools/list` / `tools/call` only, JSON-RPC errors mapped (-32700 parse with resilience — a malformed line never stops the loop, reported as `W-MCP-PROTO` on stderr — -32600 invalid request, -32601 method not found, -32602 invalid params/unknown tool, -32603 internal); tool failures are MCP results with `isError: true` carrying diagnostic codes, never protocol crashes. Tools: `note`, `verify`, `doubt`, `undoubt`, `refute`, `search`, `list_stale`. The five write tools share ONE event-writing path (`masora/write.py`): base resolution honours an explicit `base` parameter first, then matches the code repo's normalized `origin` remote against the config `[[mappings]]`, then `default_base`, else `E-MCP-NO-BASE` asks for one (§9 — no guessing); `note` resolves anchor refs through the graph provider (exact SCIP match, else case-insensitive substring; `ambiguous`/`not_found` → `E-MCP-ANCHOR` with candidates, nothing written, FORMAT §6), records write-time fingerprints + edge/neighbour snapshots via `masora/providers.py` (§11 `resolve(ref)`), and refuses a graph behind HEAD or absent with `E-MCP-GRAPH` (§5.2) — without anchors only an explicit `unanchored: true` + reason writes; events are pre-validated (`schema.validate_event`) behind a shared `check_base` pre-check (nothing is written onto an invalid base), emitted in canonical block-style YAML with JSON-style control-char escaping (multi-line statements round-trip), written to `<YYYY-MM>/<lineage>/<id>.<kind>.md`, and followed by a full post-write `check_base` whose failure unlinks the just-written file — a tool never returns success on an invalid tree; timestamps always carry `graph_commit` (explicit null when no graph is available, FORMAT §4); `verify` targets a claim version, `doubt` a verify, `refute` any event — a lineage id (including the founding claim's, whose id equals the lineage) rides the fold to the lineage's displayed version (or its active verify for doubt), and `verify` re-fingerprints the immutable anchor set, refusing drift with `E-MCP-DRIFT` (the correction is a new claim version, §6.3) while recording fresh per-anchor snapshots; `undoubt` targets the doubt's ULID only. `search` runs FTS over the index and `list_stale` lists lineages whose resolution is not current/none — both resolve the base the same way, auto-build a missing index, and surface `W-IDX-STALE` in the result text without rebuilding (the SessionStart hook owns freshness).

- **`masora facts --repo [--symbol]` — the Masora side of the cppgraph injection contract** (`masora/facts.py`, docs/CPPGRAPH_INTEGRATION.md §3): strictly read-only (never builds the index, never touches the network); it resolves the base from the user config for `--repo` (mappings on the normalized `origin` remote, then `default_base` — `write.auto_base()`, shared with the MCP write tools; no base parameter per contract §4), reads the existing per-checkout index and prints ONE compact JSON document `{contract_version: 1, repo_head, graph_commit, stale_warning, facts[]}` on stdout. `--symbol` (exact SCIP identity, matched verbatim) filters to lineages whose effective version anchors on it — the displayed version, or the newest version for `resolution: none` / founderless-unknown lineages where `displayed` is null — and fills `anchors_matched`; without it every lineage is returned with `anchors_matched: []`. The two warning classes are in-band and never errors: `stale_warning` (the `index_stale()` four-axis drift comparison — base HEAD, code HEAD, graph indexed commit, filesystem freshness; `null` when nothing is comparable) and provider unavailability as per-lineage `unknown` flags. Hard failures exit 1 with the diagnostic on stderr and nothing on stdout (contract §5): `E-FACTS-NO-BASE` (no base resolved, broken mapping/default_base, unreadable config), `E-FACTS-NOINDEX` (no index for the base × repo pair — build with `masora index`), plus `E-IDX-CORRUPT` and `E-IDX-REPO`.

- **The cppgraph injection handoff contract** (docs/CPPGRAPH_INTEGRATION.md): versioned JSON (`contract_version: 1`) with per-fact status tuples, provenance (`source`/`name`/`effort`) and full anchor-identity lists; discovery via the user config only — cppgraph passes `--repo` and never locates bases; the two warning classes in-band and never errors; rendering rules with the negative-knowledge `NOT:` envelope and a ≤ 2-facts / ≤ 60-token budget, plus the pinned trust-rendering matrix for the verification axis — a verify's label always renders, `verified(llm)` with `effort: low` is the ONLY interpretive token (`low-effort`; it never renders under `verified(human)` — a human verification answers for the content, the writer's effort is secondary), `verified(graph)` renders bare (currency is the resolution axis's job), `unverified` renders nothing; the explicit opt-out `CPPGRAPH_MASORA=0`; feature-flagged rollout pinned to `explain`/`callers`/`callees`; read-only / no-SQL-parsing invariants; fail-closed malformed facts; a cppgraph-side rollout checklist (§8).

- **The canonical event contract** (FORMAT.md): six block-style templates (`claim`, `verify`, `doubt`, `undoubt`, `refute`, `unrefute`), the per-kind required/optional/forbidden table, YAML canonicalization, monotonic Crockford-base32 ULIDs with clock-free cycle rejection, per-anchor provider-neutral snapshots (code: edge set + per-anchor neighbours), active-event folding as a backward descending-ULID fixed point, `deleted.toml` tombstones, standalone-check vs sync baseline rules. Verification is a `.verify` event — no `.md` file is ever modified after creation, promotion and re-verification append files, and a version's fingerprint set is immutable; refutations are reversible events; a refuted `.verify` is ignored when folding; `.doubt`/`.undoubt` record human disagreement with a verified version (disputed, not provably wrong); computed status is a tuple (resolution × verification × flags); negative knowledge travels as the `NOT: <summary> — refuted: <reason>` envelope; proof queries are `{tool, args, expect, provider_version}` replayed at verify/check time (never in bulk at reindex), set-equality over a tool whitelist; ULIDs are the ordering; `gc` is manual-only; MCP and CLI surfaces are harmonized. Claims record their source version `recorded_at {commit, graph_commit}` — commits qualify, fingerprints decide — and their write-time edge-set hash per anchor (`edges`); `unanchored` claims have an explicit resolution rule (no fingerprint resolution, always surfaced, the flag is the validity signal); `cost_tokens` is agent-provided, never invented by the tool.

- **Project documentation**: README.md (what/why, the Masoretes story, event lifecycle, quick start), docs/ARCHITECTURE.md (per-module walkthrough with FORMAT.md section references, including what is not built), docs/TROUBLESHOOTING.md (one row per diagnostic code: meaning, cause, remedy), AGENTS.md (AI-session read-order and invariants), and tests/test_docs.py, which pins the troubleshooting table to `masora/diagnostics.py` in both directions so they cannot diverge. scripts/docs_check.sh runs a docs-freshness agent check on demand (manual step before proposing a commit; kept out of the pre-commit hook to avoid concurrent git access).

- **Credential guard in the write path** (`masora/write.py`, covers every MCP write tool and any future CLI write): before any event touches disk, the content fields (`summary`, `statement`, `reason`, `evidence`) are scanned for HIGH-CONFIDENCE credential shapes — PEM private-key blocks (`-----BEGIN … PRIVATE KEY-----`), AWS access key ids (`AKIA` + 16 chars), known token prefixes (`ghp_`, `github_pat_`, `sk-`, `xoxb/bp/app`), and assignment to a secret name (`password=`/`token=`/`secret=`/`api_key=`/`access_token=`) followed by a 20+ char value mixing at least three character classes — and refused with `E-WRITE-SECRET`, nothing written (FORMAT.md §6 atomicity). Discussing passwords passes: naming fields ("we hash the password field with bcrypt"), short or single-class values, and ordinary words ("token bucket") are never flagged. Deterministic regexes, no dependency; secrets belong in a secret manager, never in a Masora base. The diagnostic is documented in docs/TROUBLESHOOTING.md in the same change (two-way guarded).

### Changed

- **Unified provenance on every event**: `source` (`human | llm | graph`) — the writer's nature, declarative, writer-asserted; OPTIONAL `name` — a free string self-signed by the writer: the git `user.name` when human (read from the BASE repo's git config via the write path, absent when unset — human identity is the base repo's git history), the model name when llm (the verifying session may sign its own, distinct from the claim writer's), empty/absent for graph today (a later deriving tool may sign e.g. `cppgraph@0.4`); OPTIONAL `effort` (`low | medium | high`, ONLY when `source: llm`) — the declared strength of the writing analysis, calibrating doubt-escalation: `effort` is the trust dial, `cost_tokens` stays economics-only and is read against `name`. No credential system: git history + PR review remain the trust path. The fold keeps the set of `source`s of the active verifies and resolution renders `verified(<source>)`/`unverified`. Checker and fold handle ONLY `format_version` 1 (strict MAJOR rejection of anything else). Diagnostic `E-PROVENANCE` (bad `name` type, bad `effort` enum, effort on a non-llm source), documented in docs/TROUBLESHOOTING.md (two-way guarded). MCP write tools take `source` limited to `human|llm` (`graph` is not writable via MCP — reserved for deriving tools) and `name`/`effort` params (effort refused on a non-llm source with `E-PROVENANCE`, nothing written). `masora facts` exposes per fact `source`, `name`, `effort` and the effective version's FULL `anchors` identity list beside `anchors_matched` — the anchor leg of the SPEC evidence envelope (unknown major contract versions render nothing). The index DB is at schema_version 2 (disposable — a full rebuild always regenerates it).

<!-- Entry template to copy:

## [X.Y.Z] - YYYY-MM-DD

### Added

### Changed

### Fixed

-->
