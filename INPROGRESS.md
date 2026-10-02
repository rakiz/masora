# INPROGRESS

<!-- Current state of the running phase. Updated as work happens — tick
     [x]/[ ] and record blockers as soon as they appear, not only before
     commit. Resume here after any session interruption.
     Phase done -> entry in CHANGELOG.md, then reset this file with the next
     phase's detail (never empty, never stale). -->

## Current phase

**Working now:** the branch/version context-stamping phase (TODO.md phase 2,
owner-ruled IMPORTANT) — DESIGN CLOSED (round 10). Objective: statuses
qualified by the code state a claim was established against, ONE shared
base served over the release-train branches,
~a large distributed team — recall mostly happens OFF the establishing branch;
the upstream repo squashes PR commits — the establishing commit dies on landing).

**THE FINAL DESIGN (as written in the contracts — SPEC.md:11/16/17/44/46,
MASORA_DESIGN.md §6.1-§6.2 + §12 item 16 (a)-(n), FORMAT.md §4 `lines`):**
- Structured per-anchor outcomes (match/mismatch/not_found/unavailable;
  provider `ambiguous` → unavailable) composed per version — closes
  SPEC's outcome-contract violation (None conflated everything).
- The selection function sel(S, B), TWO tiers: tier 1 = provably on the
  asking line (in_line ancestor-or-equal of HEAD, or ahead = proper
  descendant ALSO ancestor-or-equal of the branch's UPSTREAM ref as present
  locally, never fetched; ahead outranks in_line; then maxima under proper
  ancestry; then ULID), tier 2 = everything else (ULID). Among MATCHES the
  ranking is provenance preference among content-true facts — never
  validity; a non-match can never hide a match (the fallback only fires
  when nothing matches). SCRIPT-PROVEN total: 513,728 brute-force cases,
  0 selection failures; 0 resolution differences vs today's fold when no
  git context is provable.
- `restored` counterfactual via sel (some refuted R: sel(matches ∪ {R}) = R),
  only when something displays, whatever R's own outcome.
- No-match fallback = sel(active versions) — this line's drift never masked
  by a younger off-version; `off-version` flag iff the fallback's own
  outcome is definitive absence AND its relation is PROVABLY out_of_line
  (relation_unknown/in_line/ahead stay stale); suppressed while `unknown`
  shadows.
- Shadow counterfactual and uniform (U shadows iff sel(matches ∪ {U}) = U,
  active only); self-unavailable displayed/fallback = always unknown; the
  displayed version under a shadow is the known match (acknowledged change).
- `context_ordering: exact | degraded` per lineage, counterfactual (an
  unprovable context could change display/shadow/restored); off-version out
  of its scope (its guard needs a PROVABLE relation). Probes memoized per
  SHA pair, one shared build budget, lineage-id order; pairwise failures =
  incomparable, never demoting a proven relation.
- FORMAT.md §4: `recorded_at`/`verified_at` gain the OPTIONAL `lines`
  fork-point map (per known line ref, merge-base at write time — the
  squash-proof context record); tool-captured, never an agent argument,
  never backfilled (absence IS unknown); format_version stays 1, check
  accepts both shapes; CONTEXT ONLY — never a ranking input (rounds 7-8
  proved branch-name stamps and fork-point/merge-base ranking each fail a
  real case).
- Recall: FTS matches all versions; default result filter = displayed hits
  (newest-by-ULID for none lineages); any-version mode = active versions
  with their own context; the negative envelope keeps its
  ULID-newest rule EXPLICITLY (independent of sel); list_stale splits into
  the re-check list and a separate "not applicable here" list.
- Compact keeps EVERY eligible version's closure — active AND refuted
  (the counterfactual restored depends on refuted context).
- Facts contract v2 (Masora-evaluated established_relation
  in_line|ahead|out_of_line|unknown, short presentation-only commits,
  off_version, context_ordering; cppgraph renders, never computes
  ancestry); the rendering rule fires on off_version, non-in_line
  relation or degraded — on squash repos most facts render it (accepted).
- Documented blind spots (owner-ruled): cherry-picks (different SHA,
  provenance only) and the squash twin (a squash-landed note renamed later
  on its own line fires off-version — undecidable from git).

**ROUND 10 — CLOSED.** The bounded deep audit re-encoded sel from the
final §6.2 text and brute-forced **3,629,424 cases** (exhaustive DAGs ≤ 3
commits × versions × HEADs/upstreams incl. detached; 3-commit/3-version
exhaustive; 300k random 4-5-commit DAGs with 10% failed probes + 8%
exhausted budgets; criss-cross): ZERO semantic failures — exactly one
answer per input, a non-match never displays over a match,
restored/shadow/off-version defined everywhere, order-independent, and the
no-git-context reduction matches today's fold exactly. Mutation checks
confirm the harness can fail (4,956 / 16,520 violations when broken). The
audit's 4 wording leftovers (the §12(n) upstream-ref wording, the demote
sentence's unconditional `degraded`, the §12(m)/(i) supersession markers,
the §12(o) F1 record, the FORMAT typo) are applied and grep-verified. The
implementation-phase residual risks (recorded for the stage briefs): the
counterfactual `degraded` needs a defined, under-flagging-averse decision
procedure over unseen objects; legacy `absent` context has no facts-v2
enum value yet (decide at stage 8); the displayed-version change under
`unknown` is COMMON (171k cases) — CHANGELOG + oracle tests at stage 2;
rule 7 is subsumed by rule 6 (merge them, keep a pinning test); the
cross-lineage budget/order/memoization effects are unverified (single-
lineage model); real-git behaviors (upstream resolution, shallow, fetch
staleness) are adapter-stage tests.

**REVIEW LOOP (rounds 1-9):** 1-2 design-review STOP (malformed flag,
structured outcomes, compact not checkout-dependent); 3 NOT CLOSED (2
wording contradictions); 4 cross-vendor NOT CLOSED (3 MAJOR: mixed
relations, no-match shadow hole, compact/rollout stage hazard); 5 deep NOT
CLOSED (11 MAJOR — ranking quantities defined too narrowly); 6 deep NOT
CLOSED (7 MAJOR — script-proven cyclic order + the squash revelation); 7
deep NOT CLOSED (7 MAJOR — script-encoded sel: branch-name stamp hides
corrections on master, merge-base recency shadows under newer trains, the
plan never shipped the stamp); 8 deep NOT CLOSED (7 MAJOR — fork-point
ranking lets a 9.0 note shadow master's landed note, unrestricted ahead,
off-version on relation_unknown, FORMAT/§6.1 contradictions) → the owner's
final simplification ruling; 9 deep BOUNDED NOT CLOSED (6 MAJOR: F1 squash
off-version blind spot — owner-ruled accepted; F2-F6 consistency — ALL
FIXED since). Round 10 = the closure confirmation on this diff.

**Staged implementation (each stage leaves the suite green):**
0. ~~Contract amendments~~ DONE (SPEC.md, MASORA_DESIGN.md §6.2 + §12 item
   16, FORMAT.md §4 `lines`).
1. Structured provider outcomes without changing selection (fixes the
   SPEC outcome-contract violation; the stale→unknown change for
   unreadable sources is a visible status change — CHANGELOG +
   stage brief acknowledge it; needs the raw-case→outcome mapping table).
2. Pure ranked selection in the fold (sel injected; no git context =
   today's ULID order — script-proven equivalence; brute-force oracle
   extended for sel + restored/shadow counterfactuals; check and the
   format know nothing).
3. ~~Git relation adapter + degraded-mode reporting~~ DONE
   (`masora/gitctx.py` + its .md companion: `asking_line` — HEAD/branch/
   upstream/shallow resolved locally, never fetched; memoized budgeted
   `merge-base --is-ancestor` probes per ORDERED sha pair, ONE shared budget
   (PROBE_BUDGET 1024), ascending lineage-id/ULID order; the exact relation
   table in gitctx.md — in_line/ahead/out_of_line/relation_unknown/unprovable;
   the counterfactual `context_ordering` via the pure fold: degraded iff an
   unprovable context could change displayed/shadow/restored, `relation_unknown`
   not counting; real-repo tests in tests/test_gitctx.py — 26: ancestor,
   divergent, ahead-restricted, proper ahead, detached HEAD, shallow, missing
   object, cherry-picked twin, criss-cross, budget exhaustion/determinism,
   memoization, never-fetches, degraded firing only when the result could
   change).
4. ~~Index schema bump~~ DONE (SCHEMA_VERSION "5", rebuild-only per §12.16(p);
   `lineages` gains `off_version` + `context_ordering`, `versions` gains
   `relation`; one `W-CTX-DEGRADED` warning per degraded build (diagnostics.py
   + TROUBLESHOOTING.md in the same change) driving exit 2; `masora status`
   repeats the degraded count per index; public output otherwise unchanged —
   facts v1 shape untouched, off_version only STORED (rendering is stage 8)).
   The §12.16(k) "verifications table" is NOT in this stage — the task's
   column list scoped stage 4 to relation/ordering/off_version.
5. The `lines` fork-point stamp ships (CONTEXT only): schema acceptance
   (both shapes), canonical key order, tool-side capture in the write path
   (merge-base per known line ref, capped, deterministic), §5.1-§5.4
   templates, check's two-way guards, the mixed-version minimum-reader
   note, docs/CPPGRAPH_INTEGRATION.md + docs/ARCHITECTURE.md + the new
   degraded diagnostic (diagnostics.py + TROUBLESHOOTING in the same
   change) — BEFORE any writer emits the field.
6. Compact universal witness (every eligible version's closure — active
   AND refuted; observable_state per version; the equivalence proof stays
   git-free by keeping claim events verbatim; measure compression on the
   real base).
7. Recall surfaces: status qualification, search/explain, list_stale split
   (re-check vs "not applicable here"), any-version mode, agent
   instructions + skill mirrors — the coordinated user-visible release.
8. Facts v2 + cppgraph rollout (cppgraph learns v1+v2 first, flag off;
   Masora flips CONTRACT_VERSION=2 after cppgraph validates; v1 retirement
   scheduled separately).

**Owner rulings (all recorded in §12 item 16):** compact universal;
off-version leaves list_stale; facts v2 NOW (owner owns cppgraph, ships
both sides — "the BEST solution, not the least costly"); filters
displayed-default + active-only any-version (refuted archaeology → future
`history` tool); fold ordering (ruling 5, refined by rounds 6-8 into the
two-tier sel); format changes allowed (test phase, migration accepted);
F1 squash blind spot accepted+documented.

**Done:** 0.7.0 — sync becomes plan-then-confirm + the stacking recalibration
(owner ruling: the default must not act, it must show) — `masora sync` without
`--yes` runs the full gate pipeline (local check, fetch, diff vs origin/main,
stacked audit, merged-result validation) and prints the readable pending set
(the `_pr_title`/`_pr_body` rendering, warnings included), then exits 3 with
NOTHING written (no branch, no push, no PR, no local ref mutation; "no
pending events" keeps exit 0); `--yes` publishes (the previous default);
`--push` stays a mode selector, not a confirmation (`sync --push` plans, `sync
--push --yes` pushes straight to origin/main); `--drop` without `--yes` plans
the discard (same pending-set listing, exit 3), `--drop --yes` discards;
`--allow-stacked` unchanged (the stacked refusal still fires in plan mode —
exit 1). Exit codes: 3 plan printed (nothing written), 0 synced, 2 synced
with warnings, 1 errors. `STATEMENT_MAX` 1024 → 2048 (owner calibration:
real-base atomic notes reach ~1560 chars; audit.py's WHY comment states the
new basis) and the limit surfaces at write time: the `note` `statement`
descriptions (field + inputSchema, the number derived from the
`STATEMENT_MAX` constant) and the skill's "How to note well" statement line
(byte-identical mirror in AGENT_INSTRUCTIONS) state the soft publication
limit — no hard limit, but above 2048 characters the sync-time stacking audit
refuses publication by default (E-SYNC-STACKED). CLI help rewritten
(plan-then-confirm wording, exit codes, the `--yes` gate); README (lifecycle,
quick start, sync variants), ARCHITECTURE's Sync section (the plan paragraph
+ exit codes), MASORA_DESIGN §12 item 15, CHANGELOG 0.7.0. COMMAND.md
references no sync behavior — untouched; FORMAT.md §7.9 untouched (no
contract change); TROUBLESHOOTING's E-SYNC-STACKED row pins no number —
untouched. Tests: 5 new in tests/test_sync.py (plan writes nothing, the
`--yes` twin, drop plan, push plan, no-pending plan), 1 new docs guard
(`test_statement_soft_limit_in_both_docs`); the 0.6.x publishing tests pass
`--yes` now (30 call sites in test_sync.py + 1 each in test_gc.py/
test_compact.py), error-path tests unchanged (exit 1 either way — the
stacked-refusal test now runs in plan mode by default); test_mcp.py's pinned
schema string updated (derives `STATEMENT_MAX`); test_docs.py's
stacked-reflex fragment gains the `--yes` step. 655 tests green; ruff clean.

**Done:** the optional base-dir positionals (0.6.2 item (b)) — `masora
check`/`sync`/`gc`/`compact`/`index` take the base_dir positional optional
(search already did): omitted, ONE shared pre-flight gate in the CLI dispatch
(`_base_gate`) resolves the base from the checkout's masora configuration
(`write.auto_base`: mappings on the normalized origin remote, then
default_base — the same chain the MCP write tools and the E-NOT-A-BASE hint
use) and the command proceeds with the resolved directory; a failed
resolution refuses with the EXISTING `E-NOT-A-BASE` (no new code) and a
remedy stating both fixes (pass the base directory explicitly, or
`masora setup --base <url>` in this checkout — `_unresolved_base_message`
keeps the cause-specific wording, origin detection shared with facts); a
passed root keeps today's refusal, remedy and hint, and an explicit base
always wins. sync resolves/refuses in the same gate BEFORE any diff or
mutation (a refused sync dispatches to nothing — no git spawn, no file
change). search's own omitted-case refusal (`E-SEARCH-NO-BASE`) is
superseded by the shared gate and retired (owner ruling, follow-up: removed
from diagnostics.py + its TROUBLESHOOTING row). Owner follow-up (same
phase): the gate keeps the old `.` default — the hinted directory itself
(cwd for check/sync/gc/compact, `--repo` for index/search/explain) is the
base when it holds `base.toml`, checked BEFORE the configuration chain
(explicit positional still wins); 3 new tests in test_base_gate.py. Tests: 5 new in test_base_gate.py (mapping
resolution, default_base resolution, refusal naming setup, explicit-wins,
gc/compact/index resolution), 2 new in test_sync.py (resolution to an empty
base; refusal with `masora.cli.run_sync` patched + the checkout untouched),
1 updated in test_index.py (search's unmapped-repo refusal → `E-NOT-A-BASE`
on stdout, the shared gate's stream). Docs: README quick-start clause,
ARCHITECTURE (checker's gate item, Sync's gate-order sentence, index/search
CLI bullet), TROUBLESHOOTING's `E-NOT-A-BASE` row (the remedy covers the
omitted-positional case). Suite green; ruff clean.

**Done:** the four owner directives — (1) `STATEMENT_MAX` 900 → 1024 (owner
calibration, power of two; tests/test_sync.py's literal 1000-char fixtures
now derive from the constant); (2) the verify discipline gains the
delegation rule (a sub-agent verifier re-checks the anchors against the
graph, the brief carries them as cppgraph entry points) — mirrored
byte-identically in AGENT_INSTRUCTIONS + the packaged skill; (3) signing =
the exact model id, never an agent/orchestrator alias (instructions + skill
+ all five MCP write tools' `name` descriptions + FORMAT.md §4 wording);
(4) the opencode command file reclassified a FIX of 0.5.0's omission — new
0.6.1 Fixed section, out of 0.6.0's Added, pyproject 0.6.1. Tests: 3 new in
test_skill.py; 639 green; ruff clean. Next task: the first rollout (TODO.md).

**Done:** the opencode /masora slash command (rollout friction, second
machine: opencode never surfaces an installed skill as a typed /command —
only Claude Code does) — `masora skill install` now also writes
`~/.config/opencode/commands/masora.md` from the new packaged template
`masora/skills/masora/COMMAND.md` (routes $ARGUMENTS to the installed
`masora` CLI, interpret-the-output body), same overwrite-as-update policy;
Claude Code homes get NO command file (the skill already surfaces there, a
same-named command would shadow it); `masora skill print` stays skill-only;
CLI help + README carry one clause each. Tests: 3 new in test_skill.py
(installed == packaged, absent without the marker home, absent with no
homes). 639 tests green; ruff clean. Next task: the first rollout (TODO.md).

**Done:** the gc unpublished-lineage exception + the stacked reflex (TODO.md,
ticked) — gc splits its plan by PUBLISHED-NESS: per requested lineage, one
read-only `ls-tree` of origin/main's tree (rev-parse probe first; missing
origin/main or no origin ⇒ unpublished; git failure ⇒ `E-GIT`, never silent)
decides — published lineages keep today's `[[deleted]]` append (FORMAT.md
rule 10 amended: the ledger records only what the shared repo knew; dead-born
ULIDs never reach it), unpublished ones are removed locally with the plan
label "unpublished — removed locally, no tombstone (origin/main never saw
it)", the summary carries the unpublished count, and an unpublished-only run
creates no deleted.toml at all. The E-SYNC-STACKED remedy names the exact
loop (split into one atomic note per fact, `masora gc --lineage <id>` the
unpublished block claim, re-run sync — or --allow-stacked); the agent
instructions + skill gain the standing-order reflex at the end of "When to
note" (## Tools→EOF tails still byte-identical; new flat-substring guard in
both docs). MASORA_DESIGN §12 item 14 (gc's "no git spawn" narrows to "no git
mutation — one read-only origin/main ls-tree"); ARCHITECTURE's GC + Sync
sections. Tests: 5 gc tests seeded (the tombstone path needs the lineage on
origin/main now) + 4 new (`test_gc_unpublished_lineage_removes_files_without_
tombstone`, `test_gc_published_lineage_still_tombstones`,
`test_gc_mixed_request_splits_published_and_unpublished`,
`test_gc_unpublished_lineage_without_origin_deletes_locally`), the stacked
refusal test asserts the gc remedy. 636 tests green; ruff clean. Next task:
the first rollout (TODO.md).

**Done:** the sync-time stacked-note audit (TODO.md, ticked) — the
publication gate audits the pending set (`masora/audit.py`: pure
`stacking_signals`/`audit_pending` over the parsed pending CLAIM events;
verify/doubt/refute skipped) on three conservative thresholds — statement
> 900 chars, > 8 anchors, anchors spanning > 3 distinct files (the SCIP
source-unit token of the identity; `.` = no file) — constants pending
calibration on the real base (132 lineages: 7 block claims must fire, 125
clean must pass). Flagged lineages named one per line with their signals +
the split remedy; refusal `E-SYNC-STACKED` exit 1, nothing mutated, only
ADDED events audited (a block claim already on origin/main never blocks a
later sync). `--allow-stacked` = the explicit human override: per-lineage
`W-SYNC-STACKED` warning rides the PR body, flow continues. Both codes
documented the same change (two-way guarded); MASORA_DESIGN §12 item 13;
ARCHITECTURE's Sync section states the gate order (after the diff, before
any mutation). Tests: tests/test_audit.py (10), 4 new in tests/test_sync.py
(refusal, override, clean pass, pending-scope). Suite green; ruff clean.

**Done:** the anti-grep-the-base rule (TODO.md, ticked) — the `## Retrieval
budget` section names the masora base itself as off-limits to text search:
step 1 gains the enumeration route (`search '*'` lists every indexed lineage
with its status tuple — the way to audit or check for an existing claim
before writing), step 2's prohibition is explicit and covers grep — never
read or grep the base's raw event files (`*.md` under the base directory),
they carry no status: a refuted/doubted claim read raw looks valid; audit
through search/explain only. Mirrored byte-identical into the skill (the
## Tools→EOF tail stays identical, diff-verified); guards:
`test_retrieval_budget_names_the_match_all_sentinel` +
`test_retrieval_budget_forbids_grepping_the_base` (whitespace-normalized
substrings in BOTH docs). Docs-only: no code changes. 616 tests green; ruff
clean. Next task: the sync-time stacked-note audit (TODO.md).

**Done:** `masora search <query>` — the base-dir positional is optional
(TODO.md, ticked): omitted, the base resolves like `masora facts` and the MCP
tools (`write.auto_base`: mappings on the normalized `origin` remote, then
`default_base`) and the header prints the resolved base; an explicit base_dir
keeps winning and the base gate is unchanged (skipped when None — resolution
produces its own refusal). New `E-SEARCH-NO-BASE` refuses exit 1 on stderr
with the cause-specific remedy (not a Git checkout / no readable origin /
unmapped repo with no default_base / broken mapping or config), documented in
docs/TROUBLESHOOTING.md the same change; MASORA_DESIGN.md §12 records the
owner's single-base-per-project decision (multi-base config stays latent,
internal-docs only). Tests: 3 new (mapping resolution, default_base,
unmapped-repo refusal). 610 tests green; ruff clean. Next task: the first
rollout (TODO.md).

**Done:** the cppgraph-side self-check inventory (TODO.md, ticked) —
docs/CPPGRAPH_INTEGRATION.md `## 9`: the DIFF-able checklist of the full
shipped contract, each row = requirement + verification shape (injection
scope, binary detection, the flag, the spawn hardening, the fail-closed
parser, the rendering/trust matrix, repo_root semantics, the PENDING
input-hygiene + max-facts items marked implement-next, the read-only
invariants). The doc-sync guards don't cover this file (the cppgraph
contract lives outside tests/test_docs.py's diagnostics sync) — the suite +
ruff ran anyway: 607 green; ruff clean. Next task: the first rollout
(TODO.md).

**Done:** the skill trigger fixed (TODO.md, ticked) — the live-rollout
diagnosis (the shard-key question answered without masora; two verified
claims missed) lands as: the frontmatter description names the question type
("repository-specific behavior — including 'what happens when X' questions —
architecture, …"; the exclusion stays), the "Search before investigating"
section opens with the TRIAGE rule (a "what happens when X" question is a
knowledge question, not code-navigation — search the base even when code
pointers are requested; the claims carry verified consequences a fresh code
read under-weights), the skill's canonical tail mirrors it (byte-identical),
and the guards assert the new frontmatter + triage substrings. Tests:
`test_skill_frontmatter_triggers_on_project_knowledge_only` (updated) +
`test_standing_orders_before_memory_and_before_compacting_in_both_docs`
(extended with the triage fragment). 576 tests green; ruff clean. Next
task: the first rollout (TODO.md).

**Done:** the owner-validated batch (TODO.md, five items ticked) — (1) the
`keywords` field: claim-only/optional/1–10 alternate-vocabulary strings,
`E-KEYWORDS`, the secret scan over the items, `note` pass-through (maxItems
10, the four-part description), the `keywords` FTS table + SCHEMA_VERSION
"4" (disposable rebuild), the THREE-source search union (content + questions
+ keywords) with `matched_keywords` rendered as `matched keyword:` lines,
the facts contract untouched (asserted); (2) every search hit group ends
with `details: masora explain <lineage>` (CLI + MCP); (3) the retrieval-
budget pass: the `## Retrieval budget` section (search → explain → cppgraph
→ ONE narrow text search; the two-sided anti-grep rule; the tests-as-
evidence rule) in AGENT_INSTRUCTIONS + the skill (byte-identical tails);
(4) CPPGRAPH_INTEGRATION's `## Input hygiene` + the configurable fact
budget (CPPGRAPH_MASORA_MAX_FACTS, default 2); (5) MASORA_DESIGN §12 item
11: the OPEN cross-analysis tests×code idea. Tests: 8 schema, 3 mcp, 5
index (incl. the v3-refused+rebuilt and the details-line rendering), 1
facts shape; 598 tests green; ruff clean. Next task: the first rollout
(TODO.md).

**Done:** match-all search (TODO.md, ticked) — `*` is the enumeration
sentinel: `search_index` bypasses FTS and returns one hit per indexed
lineage — its displayed version (newest when none is displayed, the
`masora facts` effective-version rule) — with empty matched
questions/keywords, rendered exactly like normal hits (status tuple +
`details:` tail, CLI + MCP); tombstoned exclusion, E-IDX-NOINDEX/CORRUPT
and W-IDX-STALE unchanged. The `*` cases left the invalid-query-syntax
test loops (the sentinel reclassifies them). Tests: 3 index
(`test_search_star_enumerates_every_lineage`,
`test_search_star_renders_details_line_and_statuses`,
`test_search_star_on_empty_base_prints_no_results`) + 1 mcp
(`test_mcp_search_star_enumerates`). 614 tests green; ruff clean. Next
task: the first rollout (TODO.md).

**Working now:** nothing — the atomicity-audit batch is complete; next task: the first rollout (TODO.md). Threshold calibration on the real base (7 must fire / 125 must pass) happens at the next sync.

**Done:** the explain surface (TODO.md — the item PROMOTED out of
out-of-scope, ticked) — `masora/explain.py` (the fresh one-lineage story:
check_base gate → the lineage's event files via checker's discovery/parse →
resolve_lineage + fold_lineage with the providers from repo/none → the
render: status tuple, effective version's summary/statement/questions,
anchor match states, the event chain in ULID order with [refuted]/[inactive]
markers, the active verify's evidence in full; E-EXPLAIN-UNKNOWN for an
unknown id; nothing written). MCP tool `explain` (base resolution exactly
like the other tools — the v0.2.3 cause texts; the same text back) + CLI
`masora explain <base-dir> <lineage-id> [--repo]` (BASE_COMMANDS gains it —
the gate + parity). Tests: tests/test_explain.py (4) + tests/test_mcp.py
(3: the tool story, the unknown tool error, MCP/CLI parity) — the tools
list is EIGHT now (AGENT_INSTRUCTIONS + the skill updated, the tools-list
test pinned). TROUBLESHOOTING's E-EXPLAIN-UNKNOWN row; README command list;
ARCHITECTURE's Explain section + the out-of-scope promotion. CHANGELOG
[Unreleased] Added bullet. 590 tests green; ruff clean. Next task: the
first rollout (TODO.md).

**Done:** user-friendly skill installation (TODO.md, ticked) — the skill
lives INSIDE the package now (masora/skills/masora/SKILL.md, hatchling
ships the package tree; the docs/skills copy deleted; the test_docs sync
guards read it via importlib.resources — the source of truth stays
docs/AGENT_INSTRUCTIONS.md). `masora skill install` writes the packaged
SKILL.md into every DETECTED agent-framework skills dir (~/.claude,
~/.config/opencode — present-marker detection under the injected home;
others skipped silently; target dirs created; overwrite on re-run = the
update path; installed:/updated: per target; nothing found → the message
points at `masora skill print`; exit 0) and `masora skill print` pipes the
content to stdout. setup/init print `masora skill install`. README: uv tool
install → setup → skill install (no curl); ARCHITECTURE documents the
packaged skill + install command + the guards' resources read. Tests:
tests/test_skill.py (7: both homes, absent-framework skip, overwrite
updated:, print == packaged, the nothing-found message, the CLI wiring via
monkeypatched HOME, the wheel-carries-it resources read) + the setup/init
hint tests updated to the new substring. 583 tests green; ruff clean. Next
task: the first rollout (TODO.md).

**Done:** the CHANGELOG-invariant guard (TODO.md, ticked) — three tests in
tests/test_docs.py over the file's GLOBAL structure (the miss: stacked
`## [Unreleased]` headers survived every per-pass diff and a release sed
duplicated the release section): `test_changelog_version_headers_are_unique`,
`test_changelog_has_at_most_one_unreleased`,
`test_changelog_versions_sort_newest_first` — headers parsed after HTML
comments are stripped (the entry template's `## [X.Y.Z]` line lives in one;
comment content is replaced with its newlines so line numbers stay true);
failures name the header(s) + line numbers; the pre-commit hook's suite run
refuses the stacked/duplicated shapes at commit time. Verified against all
three failure modes by self-test. CHANGELOG [Unreleased] Added bullet. 576
tests green; ruff clean. Next task: the first rollout (TODO.md).

**Done:** standing orders + before-memory + the before-compacting ritual
(TODO.md, two items ticked) — all three live-rollout readings land in
docs/AGENT_INSTRUCTIONS.md and are mirrored into the skill (the sections
stay BYTE-IDENTICAL from ## Tools to EOF, verified): "When to note" opens
with the STANDING ORDERS framing + the anti-fear justification (everything
is born `source: llm`, `unverified` — review is the trust path; waiting
loses the moment and the knowledge); "Search before investigating" gains the
before-memory rule (product-semantics/architecture/decision questions
`search` the base FIRST — web/doc confirmation is the fallback, not the
default); the new "Before compacting" section (after Completeness check):
write a terminal verify per lineage whose evidence is self-contained before
compacting — compact keeps the live state, not the archives (a
`compact --preserve-evidence` option stays the candidate if the need
recurs). Substance guards assert all three in BOTH files (whitespace-
normalized). CHANGELOG [Unreleased] Added bullet. 573 tests green; ruff
clean. Next task: the first rollout (TODO.md).

**Done:** the "Completeness check" section (TODO.md, ticked) — the two-part
note-done checklist in docs/AGENT_INSTRUCTIONS.md + the skill's copy (after
"How to note well", before "Verify discipline"): the tool-enforced half
(format_version, provenance, summary ≤ 120, graph-resolved anchors or
explicit unanchored + reason, credential refusal, duplicate-questions
rejection) and the authoring half (self-contained summary; statement with
context/mechanism/pointers; EVERY invalidating symbol anchored; the 1–5
questions; one claim = one fact) — closing line: a note missing an
authoring-side item is not done — finish it or split it. The header-sync
guard covers the new section automatically (no test change); the closing
line + the section header pinned in both files by
`test_completeness_check_closing_line_in_both_docs`. CHANGELOG [Unreleased]
Added bullet. 572 tests green; ruff clean. Next task: the first rollout
(TODO.md).

**Done:** atomic-claims authoring guidance (TODO.md, ticked) — the owner's
rule lands as the FIRST "How to note well" imperative ("One claim = one
fact. If you wrote 'and' twice, that is several claims: split them; each
fact gets its own anchors and its own verification — a block claim is
all-or-nothing to verify, to stale and to refute."), mirrored in the skill's
copied section (header sync green) and in the `note` inputSchema description
("prefer atomic claims — split multi-part knowledge into several notes").
Tests: `test_agent_instructions_carry_the_atomic_claims_rule`
(whitespace-normalized substring in BOTH docs — robust to re-wrapping) and
the note-schema split test extended with the clause. CHANGELOG [Unreleased]
Added bullet. 570 tests green; ruff format/check clean. Next task: the first
rollout (TODO.md).

**Done:** graph-first anchor discipline (TODO.md, ticked) — the rollout
lesson (sub-agents followed rg-as-entry-point briefs, never the graph) lands
as three state-form rules in AGENT_INSTRUCTIONS' "How to note well" (locate
via cppgraph find/explain, never text-grep guessing; verify structure/
behaviour against the graph before writing; hand sub-agents the graph entry
points IN THE BRIEF), mirrored into the skill's copied section (the header
sync stays green — no new headers); the `note` inputSchema description
carries the same sentence (asserted by substring in test_mcp.py's split
test) and test_docs.py asserts the delegate-the-method rule in both docs.
`ruff format .` applied (test_init.py was the flagged file). 569 tests
green; ruff clean. Next task: the first rollout (TODO.md).

**Done:** the masora skill (TODO.md, ticked) — docs/skills/masora/SKILL.md:
frontmatter (name: masora; the project-knowledge-only trigger description
verbatim from the review, "Not for general programming tasks"), the
conditional body (MAY be served, never is-served; the ritual: try `search`
when available → on E-MCP-NO-BASE it is a resolution/config matter, NOT
evidence of no knowledge → never inspect the checkout for markers → never
re-run setup → continue normally) + the canonical rule sections copied from
docs/AGENT_INSTRUCTIONS.md (tools, search-before-investigating, when/how to
note incl. questions, verify discipline, etiquette). Doc-sync test:
test_docs.py asserts the skill carries every canonical `#`/`##` header
(single source of truth; +2 tests: frontmatter trigger words, the
conditional ritual lines with the "This repository is served" absence
pinned pre-Tools). setup.py prints the two-line install hint on success and
init.py one line ("after setup, install the agent skill"); tests assert the
substring + that NOTHING lands in any checkout (origin status porcelain
unchanged, no docs/ dir). README's Agent-instructions section offers both
routes (skill + paste block, no universal-path claims); ARCHITECTURE's
channel-3 section documents the skill + the sync test; CHANGELOG
[Unreleased] Added bullet. 539 tests green; ruff clean. Next task: the
first rollout (TODO.md).

**Done:** the optional `questions` field on claims (TODO.md, ticked) —

**Done:** the optional `questions` field on claims (TODO.md, ticked) —
FORMAT §4: claim-only, optional, 1–5 non-empty single-line reader queries
(specific, never generic; exact duplicates rejected); additive-optional
(format_version stays 1); no fold/anchor/lineage semantics. `E-QUESTIONS`
(the dedicated diagnostic, TROUBLESHOOTING row same change). write.py: the
secret scan covers question items; the emission is the generic list
emitter. mcp.py: `note` accepts `questions` (minItems 1, maxItems 5) and
persists; the tool description carries the summary/statement/questions
split. index.py: the per-question FTS5 table `questions` (version +
question_ordinal unindexed), SCHEMA_VERSION "3" (disposable rebuild,
E-IDX-CORRUPT refusal for foreign versions), the search flow unions content
hits with question hits, `SearchHit.matched_questions` (distinct, ordinal
order; a question-only hit surfaces the version's content row), the CLI +
MCP search render "matched question:" lines; the facts contract untouched
(version 1, shape asserted unchanged). Tests: 10 schema, 3 mcp (pass-through,
violations, secret-in-question), 6 index (question-only match, several
questions, content-only, v2-refuse+rebuild, old-base rebuild, CLI
rendering), 1 facts shape. AGENT_INSTRUCTIONS: the note-quality questions
clause + the targeted-only coverage audit. 554 tests green; ruff clean.
Next task: the first rollout (TODO.md).

**Done:** the no-base diagnostic tells the truth about WHY (design review

**Done:** the no-base diagnostic tells the truth about WHY (design review
ruling; TODO.md line-80 item amended) — `write.origin_state(repo)` returns
(kind, remote): `not_git_worktree` (git rev-parse --git-dir fails),
`git_without_origin` (a worktree whose origin is missing/unreadable) or
`origin` (readable) — used ONLY for the final failure diagnostic; the
success path is untouched (explicit base > mapping on origin > default_base;
an origin-less checkout with default_base/explicit base succeeds —
regression-guarded). `resolve_base` raises the three cause texts (omitted
repo_root unchanged); facts.py shares the detection for E-FACTS-NO-BASE
(adapted remedies, no "pass base explicitly"; exit 1 + empty stdout
unchanged). E-MCP-NO-BASE stays the single code. Tests: the design-review
matrix — 7 new resolve/write/note tests in tests/test_mcp.py + 3 facts
tests (code_repo gained a realistic origin; matrix test's redundant remote
add dropped). TROUBLESHOOTING's E-MCP-NO-BASE/E-FACTS-NO-BASE rows cover
the four causes with their remedies. CHANGELOG [Unreleased] Changed bullet.
537 tests green; ruff clean. Next task: the first rollout (TODO.md).

**Done:** the evaluation protocol (TODO.md "Agent-graded evaluation" amended:

**Done:** the evaluation protocol (TODO.md "Agent-graded evaluation" amended:
protocol written, the RUN remains) — docs/EVALUATION.md, pre-registered:
the question + success criteria (fewer repeated wrong deductions AND lower
cost per task; the injected-token tax as the secondary read), the paired
A/B design (same agent/model, fresh session per run, neutral prompts, blind
scoring keyed by run id), the ~20-task corpus grounded in the live base's
recorded summaries (8 example templates from the §6 real summary lines +
≥ 4 control tasks to detect false help; binding to real ULIDs at the
seed-check), the rubric (repeated wrong deductions against the claim list,
tool calls, total tokens, injected tokens per the §6 budget), the procedure
(seed-check: masora check clean + fresh index; seeded-random task ×
condition order; the recording sheet) and the verdict rule (strictly fewer
repeated wrong deductions AND no token-cost regression beyond the injected
tokens — the numbers decide adoption), with the honest limits in the doc
(single-author bias, small n, lexical recall, prevention-only measurement).
README Documentation list + docs/ARCHITECTURE.md (Agent-instructions
section) point at it; CHANGELOG [Unreleased] Added bullet. Docs-only: no
code changes, suite untouched (534 green). Next task: the RUN (the protocol's
second half) + the first rollout (TODO.md).

**Done:** base gate (TODO.md, ticked) — `check_base` refuses up front with
`E-NOT-A-BASE` ("not a base: no base.toml at <dir>") when the passed root
has no `base.toml`: one gate for every consumer (CLI commands, write-path
pre/post checks, compact/gc gates) instead of walking the tree into
confusing stray-file errors. The CLI dispatch for check/gc/compact/index/
search adds the smart remedy on refusal: the CWD's origin remote →
`write.auto_base` (failure-tolerant) → "the base configured for this repo:
<path>" when resolvable, silent otherwise; commands still exit 1, never
auto-correct. Test bases gained their `base.toml` (the conftest base
fixture, the static fixtures, the sync/index/facts/status/mcp fixtures —
init and setup always created it; FORMAT §1/§7 + ARCHITECTURE state the
one path rule). Tests: tests/test_base_gate.py, 10 tests (per command on a
git repo root without base.toml — nothing written; remedy present/absent;
init's fresh base passes; write-path precheck refuses). TROUBLESHOOTING row
(two-way guarded). CHANGELOG [Unreleased] Added bullet. 534 tests green;
ruff clean. Next task: the first rollout (TODO.md — the real base on the
author's `employees/` dir + the Confluence install page).

**Done:** slug derivation replaced (TODO.md, ticked) — the owner-validated
`write.slugify_summary` (byte-identical on the real 92-lineage base already
migrated on disk) supersedes and removes the uncommitted stop-word-skip
`lineage_slug`: camelCase and acronym runs split at case boundaries
(`changeStreamSplitLargeEvent` → `change-stream-split-large…`, `XMLParser` →
`xml-parser`), non-alphanumeric runs collapsed, lowercased, leading article
stripped, word-boundary cut under `SLUG_MAXLEN` 30 (single tokens hard-cut),
no-alphanumeric → "lineage". One shared function, three call sites:
`write.event_relpath` (founder home — a slugless summary now derives
`lineage-<ULID>` instead of the bare form), `compact._rehome_plan` (bare
homes derive, existing slugs kept verbatim — unchanged rule), `sync.
_lineage_label` (PR display). Event-file format, ULIDs and the path-
indifferent checker untouched; the caller appends `-{ULID}`, no collision
handling. Tests: 8 derivation tests in tests/test_write.py (owner's list;
the stop-word + unicode-fold tests superseded and removed), test_mcp.py +
test_sync.py expected strings adapted to the 30-char budget (one word packs
more). FORMAT.md §1 + docs/ARCHITECTURE.md reworded; CHANGELOG [Unreleased]
Changed bullet replaces the never-shipped stop-word entry. 524 tests green;
ruff clean. Next task: the first rollout (TODO.md — the real base on the
author's `employees/` dir + the Confluence install page).

**Done:** v0.2.1 bug fix (live-rollout report, sub-directory base) —
`masora status` computed the indexes directory from the CONFIG KEY
(`config.indexes_root() / config.slug(name)`) while `index.index_db_path`
derives it from the BASE DIRECTORY's basename — they disagree for ANY
sub-directory base (config key "employees" vs base dir "masora_mdb"): status
printed "no index" forever while index/facts/MCP agreed. One source of
truth: `masora/index.py:index_dir_for(base_dir)` owns the
`indexes/<base-dir-slug>/` derivation (index_db_path uses it);
`masora/status.py` resolves each configured base's directory through
`write.base_dir_for_name` (the hand-joined `entry["path"]` copy is gone) and
lists the `*.db` files under `index_dir_for(base_dir)`; clone display line,
counts, stored-meta repo mapping and four-axis staleness wording unchanged.
Tests: `test_status_lists_subdir_base_indexes` (regression: config key ≠
base-dir basename + sub-path, real index via `index_db_path` shows, no "no
index"), `test_status_missing_clone_with_index_states_the_rebuild`,
missing-clone test now rides a sub-path entry (16 in tests/test_status.py).
Release: pyproject 0.2.1, CHANGELOG 0.2.1 Fixed bullet. 520 tests green;
ruff clean. Next task: the first rollout (TODO.md — the real base on the
author's `employees/` dir + the Confluence install page).

**Done:** `masora status [--force]` (TODO.md, ticked) — one readable screen,
exit 0 always (masora/status.py: never fails hard — offline release check is
a quiet one-liner, missing clone/unreadable config reported as-is). Tool
section: installed version (importlib.metadata, "unknown" fallback),
format_version, facts contract_version, index schema_version. Bases section:
per `[bases.<name>]` entry — clone path (exists/missing), the clone's origin
remote (git, configured entry as fallback), event + tombstone-block counts
(cheap walk), per index DB the repo mapping + `index_stale_reason()` four-axis
wording / fresh / no index / unreadable. Update check: GitHub releases API
(urllib, 2 s timeout), numeric semver-triplet compare, `up to date` /
`update available: vX.Y.Z — <url>` + the install hint, cached 24 h in
`~/.local/share/masora/update-check.json` (`$MASORA_HOME` relocates it,
`config.update_check_path()`), `--force` refetch, injectable module-level
fetcher (`status.fetch_latest_release`) for hermetic tests. Root `--version`
flag (argparse version action, exit 0). Tests: tests/test_status.py, 14
hermetic tests (no network). README Status section; ARCHITECTURE Status
section; CHANGELOG [Unreleased] bullet. 504 tests green; ruff clean. Next
task: the first rollout (TODO.md — the real base on the author's `employees/`
dir + the Confluence install page).

**Done:** `masora compact --rehome` (TODO.md, ticked) — layout migration
without history compression on top of `masora/compact.py`: `_rehome_plan`
derives per lineage the canonical single home from the surviving founder file
(its directory, renamed `<slug>-<lineage>` via `write.lineage_slug(founder
summary)` when bare; an existing slug kept verbatim; founderless lineages
untouched) and plans every surviving file outside that home as a move;
`_execute_rehome` moves files (same ULIDs, same bytes), prunes vacated dirs
with gc's helper. `--rehome` composes with compaction: drops follow the
compact tombstone rules (known-to-origin only), survivors land canonically;
the fold proof is vacuous for pure rehome runs (no event dropped, `check`
content-based, post-check asserts anyway). Plan exits 3 without `--yes`;
pre/post `check_base` green; already-canonical lineages untouched → a second
run is a no-op. CLI `--rehome` flag; FORMAT.md §1 names the migration tool;
README quick start + docs/ARCHITECTURE.md Compact section state the rule;
CHANGELOG [Unreleased] bullet. 8 new tests (27 in test_compact.py); 504
tests green; ruff clean. Next task: the first rollout (TODO.md — the real
base on the author's `employees/` dir + the Confluence install page).

**Done:** Agent instructions (TODO.md, ticked). docs/AGENT_INSTRUCTIONS.md —
the canonical paste-ready block for an adopting project's `AGENTS.md`
(MASORA_DESIGN.md §10.1 channel 3): the seven MCP tools one line each;
search-before-investigating + status reading (`verified(human)` trusted,
`verified(llm)` re-verify in code, `unverified` = hypothesis, lazy
re-verify when the task depends on a `stale`/`suspect`/`unverified` claim);
the §10.3 capture triggers as imperatives (user corrections `source: human`,
validated non-obvious behaviour verified with evidence, pitfalls, decisions,
costly establishments, session-end sweep); note quality (summary ≤ 120-char
injected one-liner, statement = full explanation, anchors on every symbol
whose change could invalidate, speculation labelled, refutations welcomed as
negative knowledge); the verify discipline (recorded evidence — replayable
proof query for structural, pointers + explanation for semantic; semantic
claims are never auto-confirmed); etiquette (English content, facts never
instructions, statuses are evidence labels). README "Agent instructions"
section (install story) + Documentation list entry; docs/ARCHITECTURE.md
channel-3 section. Docs-only: no code changes, suite untouched. Next task:
the first rollout (TODO.md — the real base on the author's `employees/` dir
+ the Confluence install page).

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
