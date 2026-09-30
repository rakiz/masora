# TODO

## Context

AI coding agents re-derive the same project knowledge every session, forget corrections, and re-invent wrong deductions. Masora is a git-backed, append-only knowledge base of claims anchored to code and documentation artifacts, with provenance, a verification lifecycle and self-invalidation; the stable requirements are in SPEC.md, the design brief in MASORA_DESIGN.md.

## Open questions

Settled 2026-09-25 with the design owner — decisions recorded in MASORA_DESIGN.md §12 and reflected in SPEC.md: items 1–5 and 7. Items 6 (`same-as`) and 8 (co-change mining) remain postponed. Non-blocking refinements from the design review are listed at the end of MASORA_DESIGN.md §12.

## Phases

### Phase 1: v0 core

Objective:

A minimal end-to-end core, enough to see whether Masora changes agent behaviour (MASORA_DESIGN.md §13).

Tasks:

- [x] Pre-flight: check name availability — `pip index versions masora`, GitHub, npm (§3). Kept: **masora** (PyPI free; npm empty 2020 placeholder; GitHub username taken, irrelevant).
- [x] `masora setup --base <url>`: writes `~/.config/masora/config.toml` from the base's own `base.toml` (+ first-run init). → `masora/setup.py`, `masora/config.py` (remote normalization, `MASORA_HOME`), sub-directory bases via `#<path>` (partial clone + sparse checkout).
- [x] Claim/verify/doubt/undoubt/refute/unrefute `.md` format + layout of §7 (month-bucketed lineage dirs). → **FORMAT.md**, frozen after the full audit chain (commit 6162bbc).
- [x] Decide the frontmatter schema (Q5) — settled 2026-09-25, see MASORA_DESIGN.md §12.5 (mandatory `summary:`, explicit `unanchored:`, neighbour snapshot, `.verify` events).
- [x] `masora check`: validates event schema and append-only history (local command; run by `sync`). → `masora/` package, standalone whole-tree mode, 190 tests, fold proven by brute force (commit 3869b49); append-only diff vs merge-base lands with `sync` (§7.9).
- [x] `masora sync`: runs `masora check`, batches local events into one branch + PR to the shared base.
- [x] Documentation: human-readable README (what/why, the Masoretes story, event lifecycle write→check→sync→PR→merge→recall, quick start) + troubleshooting table for every `E-*`/`W-*` diagnostic code (cause + remedy, generated from `masora/diagnostics.py` so it cannot diverge) + `AGENTS.md` for AI sessions pointing at the canonical contracts (FORMAT.md, SPEC.md) instead of re-deriving from code. → README.md, docs/ARCHITECTURE.md, docs/TROUBLESHOOTING.md (33-code table), AGENTS.md, tests/test_docs.py two-way sync guard.
- [x] `masora gc`: deletes whole lineages on explicit, confirmed request (`--lineage`); no auto-suggestions in v1. → `masora/gc.py` (plan-then-confirm: plan exits 3, `--yes` executes; pre/post `masora check`; tombstone appended to `deleted.toml`, event files removed; `sync` accepts tombstoned whole-lineage deletions and applies them to the merged tree).
- [x] SQLite index + resolution algorithm of §6.2 + FTS. → `masora/index.py` (full-rebuild SQLite+WAL DB at `<masora_home>/indexes/<base-slug>/<repo-slug>-<hash>.db`, FTS5, tombstone exclusion, base-HEAD staleness) + `masora/resolve.py` (pure §6.2 status tuple over `masora/fold.py`, injectable provider registries, `suspect` per §12.4) + CLI `index`/`search` (E-IDX-*/W-IDX-* diagnostics); `code` anchors report `unknown` until the cppgraph provider.
- [x] MCP tools: `note`, `verify`, `doubt`, `undoubt`, `refute`, `search`, `list_stale`. → `masora/mcp.py` (hand-rolled MCP stdio server: newline-delimited JSON-RPC 2.0, protocol version pinned `2025-06-18` and negotiated the standard way — the initialize result always carries it, `initialize`/`notifications/initialized`/`tools/list`/`tools/call` only, parse-error resilience with W-MCP-PROTO) + `masora/write.py` (one event-writing path: base resolution explicit `base` param → mapping match → `default_base` → `E-MCP-NO-BASE`, shared `check_base` pre-check + post-write `check_base` with unlink-on-failure atomicity, write-time anchor resolution + fingerprints + snapshots via `masora/providers.py`, canonical block-style emission with control-char escaping, `E-MCP-GRAPH` behind-HEAD refusal per §5.2, verify drift refusal `E-MCP-DRIFT` per §7.7; lineage ids ride the fold to the displayed version; `search`/`list_stale` auto-build a missing index, surface `W-IDX-STALE` without rebuilding).
- [x] Write path rejects credential-shaped content. → The shared write path (`masora/write.py`, single pipeline → covers all MCP write tools and future CLI writes) scans `summary`/`statement`/`reason`/`evidence` for HIGH-CONFIDENCE shapes only — PEM private-key blocks, AWS `AKIA…` ids, token prefixes (`ghp_`, `github_pat_`, `sk-`, `xoxb/bp/app`), and `password=`/`token=`/`secret=`-style assignments with 20+ char mixed-class values — and refuses with `E-WRITE-SECRET`, nothing written (FORMAT.md §6). Discussing passwords passes (deterministic regexes, no dependency; documented in docs/TROUBLESHOOTING.md).
- [x] Code anchor provider via cppgraph with per-symbol definition fingerprint.
- [x] Edge-set fingerprint per symbol (hash of outgoing edges) — input to the settled `suspect` rule (§12.4).
- [x] Neighbour snapshot (per-anchor snapshot: each anchor's own edge-set hash plus its direct neighbours, identity → edge-set hash) recorded at write time and in `.verify` events — baseline for `suspect` comparison. (Provider-side computation: `masora/providers.py` answers both for the index; the write path records at write/verify time.)
- [x] `masora compact <base-dir>`: compress every lineage to its minimal live
  witness set — the event files still contributing to the lineage's current §6
  fold state — dropping pure history (superseded versions, undone events,
  inactive verifies) while losing nothing observable; same ULIDs kept for
  surviving files (byte-identical, merge-safe). Plan-then-confirm like gc
  (plan exits 3, `--yes` executes); per-lineage fold-equality proof refuses
  diverging lineages fail-closed (`E-COMPACT-DIVERGE`); dropped events known
  to the shared repo (present on `origin/main` or the sync merge-base) are
  tombstoned per-event, unpublished events are dropped silently. →
  `masora/compact.py`, `[[deleted_events]]` tombstone table (FORMAT.md §7.10),
  sync acceptance of tombstoned per-event deletions, tests/test_compact.py.
- [x] `masora compact <base-dir> --rehome`: layout migration without history
  compression — rename every lineage directory to its canonical
  `YYYY-MM/<slug>-<lineage>` form (founder's month; an existing slug is kept
  verbatim, only bare `<lineage>` dirs get one prepended) and merge split
  month buckets into that one home, moving files (same ULIDs, same bytes),
  never deleting; combined with compaction the dropped events follow the
  compact tombstone rules and the survivors land in the canonical home. →
  `masora/compact.py` (`RehomePlan`, `_rehome_plan` over the surviving
  records, `_execute_rehome` with gc's prune helper; plan exits 3 without
  `--yes`; pre/post `check_base` green; already-canonical and founderless
  lineages untouched — a second run is a no-op), `masora/cli.py` `--rehome`
  flag, tests/test_compact.py (8 rehome tests).
- [x] `masora status` sub-directory-base fix (v0.2.1): status resolved the
  indexes directory from the CONFIG KEY while index/facts/MCP route through
  `index_db_path` (base-dir basename) — any sub-directory base showed "no
  index" forever; the base dir itself was joined by hand instead of via
  `write.base_dir_for_name`. → `masora/index.py:index_dir_for()` (one source
  of truth, `index_db_path` uses it), `masora/status.py` (base dir via
  `base_dir_for_name`, indexes listed under `index_dir_for(base_dir)`),
  tests/test_status.py regression, pyproject 0.2.1.
- [x] `masora status [--force]`: one readable screen, exit 0 always — tool
  versions (installed version, supported format_version, facts
  contract_version, index schema_version), the configured bases (clone path
  with exists/missing, the clone's origin remote, event + tombstone counts,
  per index DB the repo mapping and the four-axis staleness reason or "no
  index"), and the cached release check (GitHub releases API, 24 h TTL in
  `$MASORA_HOME/update-check.json`, `--force` refetch, offline is a quiet
  one-liner, injectable fetcher); `--version` on the root parser. →
  `masora/status.py`, `masora/config.py:update_check_path()`,
  `masora/cli.py`, tests/test_status.py.
- [x] Injection of known facts into cppgraph responses (requires changes in the separate cppgraph repo). → shipped in the cppgraph repo (v0.4.5): opt-in CPPGRAPH_MASORA injection on explain/who_calls/what_it_calls, MCP `masora` field + CLI lines, rendering per the pinned §6 trust matrix (docs/CPPGRAPH_INTEGRATION.md is the contract).
- [x] `masora facts --repo [--symbol]`: versioned JSON contract for the cppgraph injection (docs/CPPGRAPH_INTEGRATION.md). → `masora/facts.py` (strictly read-only: base resolved via the config mappings/default_base for `--repo`, existing index read and never built — missing/unusable = exit 1 with `E-FACTS-NOINDEX`/`E-IDX-CORRUPT` on stderr, nothing on stdout; one compact JSON document `{contract_version, repo_head, graph_commit, stale_warning, facts[]}`; `--symbol` matches the displayed version's anchors verbatim, or the newest version for `resolution: none`/founderless lineages where `displayed` is null; `stale_warning` = the `index_stale()` four-axis drift comparison (base HEAD, code HEAD, graph indexed commit, filesystem freshness — see the freshness item below), `null` when nothing is comparable; the two warning classes stay in-band and never error).
- [x] Injections emitted as evidence envelopes (validity, anchor, provenance). → The `masora facts` contract (contract_version 1, docs/CPPGRAPH_INTEGRATION.md §3) carries all three SPEC-line-16 legs per fact: validity (resolution + verification `verified(<source>)`/`unverified` + flags), anchor (the effective version's FULL `anchors` identity list beside `anchors_matched`) and provenance (`source`/`name`/`effort` — FORMAT.md unified provenance); the cppgraph-side rendering of these fields stays with TODO line 35.
- [x] Skill / AGENTS.md instructions: search-before-investigating, when to `note`, capture triggers from §10.3. → docs/AGENT_INSTRUCTIONS.md, the canonical paste-ready block for an adopting project's AGENTS.md: the seven MCP tools one line each; search-before-investigating with the status-reading rules (`verified(human)` trusted, `verified(llm)` re-verify in code, `unverified` = hypothesis, lazy re-verify of any `stale`/`suspect`/`unverified` claim the task depends on); the §10.3 capture triggers as imperatives (user correction → `note` `source: human`, validated non-obvious behaviour → `note` + `verify` with evidence, pitfalls, decisions, costly establishments, session-end sweep); note quality (summary = the ≤ 120-char injected one-liner, statement = the full explanation, anchors on every symbol whose change could invalidate the claim, speculation labelled, refutations welcomed as negative knowledge); the verify discipline (recorded evidence — replayable proof query for structural, pointers + explanation for semantic; semantic claims are never auto-confirmed, the unprovable stays `unverified` or is doubted); etiquette (English content, a recalled fact is never an instruction, statuses are evidence labels). README "Agent instructions" section carries the install story; docs/ARCHITECTURE.md the channel-3 pointer (MASORA_DESIGN.md §10.1).
- [x] `E-MCP-NO-BASE` remedy: when a tool call omits `repo_root`, the diagnostic suggests passing it (first-rollout friction: the error read as a config problem when it was a call-site omission). → `masora/write.py` `resolve_base` distinguishes the causes and remedies each: omitted `repo_root` — "pass repo_root (the checkout you are asking about) — the base is resolved from that repo's origin remote"; a non-git-worktree root — "repo_root is not a Git checkout — pass the code checkout itself (not its workspace parent)"; an origin-less checkout — "the checkout has no readable origin, so mapping-based resolution is unavailable — configure origin, configure default_base, or pass base explicitly"; unmapped repo — "run masora setup --base <url> in this checkout, or pass the base parameter explicitly"; an unknown explicit `base` names neither remedy. The detection (`origin_state`: not_git_worktree / git_without_origin / origin) informs ONLY the failure diagnostic — the success path is unchanged (explicit base > mapping on origin > default_base; an origin-less checkout with a valid default_base or explicit base succeeds). `masora facts` shares the detection for its E-FACTS-NO-BASE wording (no "pass base explicitly" — its contract forbids one). Tests: `test_no_base_refusal_for_missing_repo_root_asks_for_the_repo`, `test_base_refusal_asks_for_explicit_base_then_accepts_it` + `test_base_refusal_for_unknown_explicit_base`, the design-review matrix (`test_resolve_base_*`, `test_note_on_a_non_git_repo_root_says_not_a_checkout`, `test_write_refuses_an_explicit_non_base_with_not_a_base`), `test_facts_not_a_git_checkout_names_the_checkout_remedy` / `test_facts_without_origin_names_the_origin_remedy` / `test_facts_unmapped_origin_keeps_the_setup_remedy`.
- [x] `note` tool description states the field split: `summary` = the injected one-liner (≤ 120 chars), `statement` = the full text (first-rollout friction: an agent hit `E-SUMMARY` at 123 chars and did not know the split). → `masora/mcp.py`: the `note` inputSchema description states the contract in one sentence (summary = the injected one-liner, ≤ 120 characters, what cppgraph surfaces; statement = the full text, no length constraint, the detailed explanation; content in English — base event files are pushed content), the summary/statement field descriptions match the split, and the write tools' `reason`/`evidence` descriptions carry the language expectation. Test: `test_note_schema_states_the_summary_statement_split` (`tests/test_mcp.py`).
- [x] Readable sync PR: `masora sync` renders the PR title and body in plain English — one line per pending event with the lineage slug, the RESOLVED target and summary for non-claim events (today they render "(no summary)"), the reason for doubt/refute, and the writer provenance (first-rollout friction: a pending diff of ULID-named YAML files is hard to review). → `masora/sync.py` (`_pr_body`/`_pr_title`: title mirrors the per-kind counts, `EventFile` gained `targets`/`source`/`name`/`reason`/`evidence_count` so the diff resolves targets along the `targets` chain; reason truncated to 80 characters), `tests/test_sync.py` (5 new tests).
- [x] Human-named lineage directories: one directory per lineage, `<slug>-<lineage-ULID>` (stable slug derived from the founder's summary, treated as an immutable historical label), ALL events of the lineage join that single directory — extensions look up the existing lineage directory instead of re-bucketing by the current month (kills the month-splitting of one story; layout is convention-only in FORMAT.md §1, wording to update). → `masora/write.py` (`lineage_slug` — lowercase ASCII `[a-z0-9-]`, ≤ 24 chars, word-boundary trimmed; `event_relpath(data, base_dir)` — founder creates `YYYY-MM/<slug>-<lineage>/` in its month, extensions join the lineage's existing directory found by ULID suffix verbatim, legacy splits resolve to the founder-holding directory else sorted-first, never a third dir), FORMAT.md §1 + MASORA_DESIGN §7 + docs/ARCHITECTURE.md wording, `tests/test_write.py` (new, 13 tests) + `test_mcp.py`.
- [x] Slug derivation replaced by the owner-validated `slugify_summary`
  (supersedes the stop-word skip, which never shipped): camelCase and
  acronym runs split at case boundaries (`changeStreamSplitLargeEvent` →
  `change-stream-split-large-event…`, `XMLParser` → `xml-parser`), leading
  article stripped, word-boundary cut under 30 chars, no-alphanumeric
  summaries fall back to `lineage`; validated byte-identical on the
  92-lineage production base already migrated on disk. →
  `masora/write.py` (`slugify_summary`, used by `event_relpath`),
  `masora/compact.py` `_rehome_plan` (bare homes derive, existing slugs kept
  verbatim), `masora/sync.py` `_lineage_label` (PR display), FORMAT.md §1,
  docs/ARCHITECTURE.md, tests/test_write.py.
- [x] Base gate: every base-dir-taking command (`check`, `gc`, `compact`, `index`, `search`) refuses up front when `base.toml` is absent at the passed root — new diagnostic `E-NOT-A-BASE` with a smart remedy naming the base configured for the current repo's remote, if one resolves (rollout lesson: an agent passed the checkout root instead of the base directory; gc then wrote tombstones one level too high and the check error read as "invalid file" instead of "not a base"). → `masora/checker.py` gate (one gate for every consumer: CLI, write-path pre/post checks, compact/gc), `masora/cli.py` dispatch (`_base_gate` + `_configured_base_hint` via `write.auto_base`), `masora/diagnostics.py` + docs/TROUBLESHOOTING.md, FORMAT.md §1/§7, docs/ARCHITECTURE.md, `tests/test_base_gate.py` (10 tests).
- [x] Index freshness on uncommitted writes (rollout friction: a `note` wrote an event file but the SQLite index stayed frozen — `masora facts`/`search` silently missed the just-written claim, because the staleness axes compare git HEADs and an uncommitted write moves none). → `masora/index.py`: `index_stale()` gained a FOURTH axis — filesystem freshness: the build moment (`built_at` in the index meta, UTC ISO) against the newest mtime across the base tree's event `*.md` + `deleted.toml` (one cheap walk per read, no caching, ~2 s tolerance); fires with reason "events written since the index build (uncommitted or unsynced writes move no git HEAD)" — the reason text flows into the `W-IDX-STALE` message (CLI + MCP `search`), `masora facts` keeps the bare `stale_warning` boolean (no contract shape change); a rebuild makes the index fresh again. Tests: `test_uncommitted_write_fires_freshness_axis`, `test_freshness_tolerance_respected`, `test_freshness_axis_ignores_non_event_files_but_walks_deleted_toml` (test_index.py), `test_facts_stale_warning_true_after_uncommitted_note` (test_facts.py), `test_search_freshness_axis_catches_uncommitted_note` (test_mcp.py).
- [x] `masora init` — base bootstrap command (git init + `base.toml` scaffold + first commit): today the first base is hand-made inside the shared repo; friction observed during the first rollout. → `masora/init.py` + CLI subcommand — `masora init [<base-dir>|--here] --name <name> [--code-remote <url>]… [--force]`: refuses an unusable target (non-empty without `--force`, an existing `base.toml` even forced — `E-INIT-TARGET`), writes `base.toml` in the exact shape `setup` reads (remotes normalized + deduplicated via `config.normalize_remote`), gates the fresh tree through `check_base` before the first commit "masora init: base <name>" (`E-INIT-CHECK`; `E-INIT-WRITE`, `E-INIT-GIT` — e.g. a missing git identity — `E-INIT-ARG`), every git spawn through `sync.git_env()`, prints the exact next command `masora setup --base <path>` (publishing to a shared repo is the user's git work). tests/test_init.py (11 tests); README quick start, docs/ARCHITECTURE.md Init section, docs/TROUBLESHOOTING.md (5 `E-INIT-*` codes, two-way guarded).
- [x] The optional `questions` field on claims (design-review ruling): 1–5
  non-empty single-line reader queries a claim answers (specific, never
  generic; exact duplicates rejected), claim-only, additive-optional
  (format_version stays 1), no fold/anchor/lineage semantics; the secret
  scan covers the items; `note` accepts + persists the field; the index
  carries a PER-QUESTION FTS table (schema v3 — disposable rebuild) and
  search unions content hits with question hits, surfacing the matched
  question per hit; the facts contract is untouched. → `masora/schema.py`
  (`E-QUESTIONS`), `masora/write.py`, `masora/mcp.py`, `masora/index.py`
  (`SearchHit.matched_questions`), `masora/cli.py`, FORMAT.md §4,
  docs/AGENT_INSTRUCTIONS.md, docs/ARCHITECTURE.md, README,
  docs/TROUBLESHOOTING.md, tests (schema/mcp/index/facts).
- [x] The masora skill (design review): docs/skills/masora/SKILL.md — the
  installable form of the canonical agent instructions. Frontmatter triggers
  on PROJECT-KNOWLEDGE questions only (repository-specific behaviour,
  architecture, product semantics, past decisions, trade-offs, conventions —
  not general programming); the body is conditional by design: never claims
  a repo is served; the ritual tries `search` when available, reads
  E-MCP-NO-BASE as a resolution/config matter (never as evidence of no
  knowledge), never inspects the checkout for masora markers, never re-runs
  setup, continues normally; then the canonical rules (search before
  investigating, status reading, when to note, note quality incl. questions,
  verify discipline, etiquette). A doc-sync test asserts the skill carries
  every AGENT_INSTRUCTIONS.md header (single source of truth). setup/init
  print the install hint (copy — masora never writes into a code repo);
  README offers both routes. → docs/skills/masora/SKILL.md,
  tests/test_docs.py, tests/test_setup.py, tests/test_init.py,
  masora/setup.py, masora/init.py, README, docs/ARCHITECTURE.md.
- [x] Graph-first anchor discipline (rollout lesson: an agent delegated
  note-research to sub-agents with rg-as-entry-point briefs — the sub-agents
  followed the imposed method, never the graph; cppgraph IS the
  symbol-discovery tool and it sat unused). The "How to note well" rules:
  locate symbols with the code graph (cppgraph `find`/`explain`), never by
  text-grep guessing — exact identities or name fragments,
  ambiguous/not_found returns candidates; verify structure/behaviour claims
  against the graph before writing; when delegating research, hand the
  graph entry points IN THE BRIEF. The `note` inputSchema description
  carries the same sentence. → docs/AGENT_INSTRUCTIONS.md,
  docs/skills/masora/SKILL.md (the copies track), masora/mcp.py,
  tests/test_docs.py, tests/test_mcp.py.
- [x] Atomic-claims authoring guidance (the owner's rule: one claim = one
  verifiable fact — a big block is refused as a whole when one detail fails
  verification; split so validation, staleness and refutation work at the
  grain of the fact). The "How to note well" imperative + the skill's copied
  section + the `note` inputSchema clause ("prefer atomic claims — split
  multi-part knowledge into several notes"). → docs/AGENT_INSTRUCTIONS.md,
  docs/skills/masora/SKILL.md, masora/mcp.py, tests/test_docs.py,
  tests/test_mcp.py.
- [x] The "Completeness check" section (docs/AGENT_INSTRUCTIONS.md + the
  skill's copy, after "How to note well"): the two-part checklist — the
  tool-enforced half (format_version, provenance, summary ≤ 120, anchors
  via graph or explicit unanchored + reason, credential refusal,
  duplicate-questions rejection) and the authoring half the tools cannot
  judge (self-contained summary, statement with context/mechanism/pointers,
  EVERY invalidating symbol anchored, the 1–5 questions, one claim = one
  fact) — closing line: a note missing an authoring-side item is not done —
  finish it or split it. The header-sync guard covers the new section
  automatically; the closing line pinned in both files by test. →
  docs/AGENT_INSTRUCTIONS.md, docs/skills/masora/SKILL.md,
  tests/test_docs.py.
- [x] The evidence ritual before compacting (rollout evidence): compaction
  keeps the live state and may drop superseded verifies — when a base's
  verifies carry replayable evidence you may need later, FIRST write a
  terminal verify per lineage whose evidence is self-contained (report the
  replayable bullets); compact keeps the live state, not the archives.
  Documented as "Before compacting" in the agent instructions + the skill;
  a `compact --preserve-evidence` option stays the candidate if the need
  recurs. → docs/AGENT_INSTRUCTIONS.md, docs/skills/masora/SKILL.md,
  tests/test_docs.py.
- [x] Standing orders + search before memory (rollout evidence: an agent
  described itself as "I only write when told; I don't consult actively; the
  facts come to me via the graph"): the "When to note" opening reframed as
  STANDING ORDERS — note when a trigger fires, without being asked, without
  asking permission; proactive capture is safe because everything is born
  `source: llm`, `unverified` (review is the trust path); waiting loses the
  moment and the knowledge. "Search before investigating" gains the
  before-memory rule: product-semantics/architecture/decision questions
  `search` the base BEFORE answering from memory or external docs — web/doc
  confirmation is the fallback, not the default. → docs/AGENT_INSTRUCTIONS.md,
  docs/skills/masora/SKILL.md, tests/test_docs.py.
- [x] The CHANGELOG-invariant guard (the miss: two stacked `## [Unreleased]`
  headers survived several doc passes and a release sed converted BOTH into
  duplicated `## 0.3.2` sections — every pass diff looked fine in
  isolation). tests/test_docs.py gains three guards over the GLOBAL
  structure: no duplicated `## <version>` header; at most one
  `## [Unreleased]`; version sections sort newest-first (monotonic
  non-increasing semver) — failures name the offending header(s) and their
  line numbers; HTML comments are stripped first so the entry template's
  `## [X.Y.Z]` line cannot trip them. → tests/test_docs.py.
- [x] User-friendly skill installation (the curl runbook dies): the skill
  MOVES into the package (`masora/skills/masora/SKILL.md` — hatchling ships
  the package tree; one canonical copy, the docs/skills copy deleted; the
  test_docs sync guards read it via importlib.resources — the source of
  truth stays docs/AGENT_INSTRUCTIONS.md). NEW `masora skill install`
  (writes the packaged SKILL.md into every DETECTED agent-framework skills
  dir — ~/.claude, ~/.config/opencode, others skipped silently; creates the
  target dirs; overwrites on re-run = the update path;
  `installed:`/`updated:` per target; nothing found → the message points at
  `masora skill print`; exit 0) + `masora skill print` (the content to
  stdout for any other mechanism); the framework roots derive from
  Path.home() (tests inject the home). setup/init print `masora skill
  install`. README's story: uv tool install → setup → skill install (no
  curl). → masora/skill.py, masora/cli.py, masora/setup.py, masora/init.py,
  pyproject (no change needed — the package tree carries it),
  tests/test_skill.py, tests/test_docs.py, README, docs/ARCHITECTURE.md.
- [x] `masora explain <base-dir> <lineage-id> [--repo]` + the `explain` MCP
  tool (PROMOTED out of out-of-scope — the rollout lesson: an agent wanting
  one lineage's full story improvised a massive rg over masora's directories
  and read RAW event files, which carry NO status, so a refuted/doubted
  claim looked valid): the fresh fold status (never the index), the
  effective version's summary/statement/questions, the anchors with their
  current match state (matched/changed/not_found via the providers with a
  repo; unknown otherwise), the full event chain in ULID order and the
  active verify's evidence in full; unknown id → `E-EXPLAIN-UNKNOWN`; the
  base gate applies; nothing written, ever. → `masora/explain.py`,
  `masora/mcp.py`, `masora/cli.py` (BASE_COMMANDS gains explain),
  `masora/diagnostics.py` + docs/TROUBLESHOOTING.md, README,
  docs/ARCHITECTURE.md, tests/test_explain.py + tests/test_mcp.py,
  docs/AGENT_INSTRUCTIONS.md + the skill (the tools list now eight).
- [x] The `keywords` field (the questions' sibling): claim-only, optional,
  1–10 non-empty single-line alternate-vocabulary strings (synonyms, domain
  terms, event/test/component names), exact duplicates rejected, no
  fold/anchor/lineage semantics, format_version stays 1; `E-KEYWORDS` (the
  diagnostics two-way row); the secret scan covers the items; `note` accepts
  + persists (minItems 1, maxItems 10; the four-part description); the
  `keywords` FTS table — SCHEMA_VERSION "4" (disposable rebuild,
  E-IDX-CORRUPT for foreign versions) — and the THREE-source search union
  (content + questions + keywords) with matched keywords rendered; the
  facts contract untouched (asserted). → masora/schema.py, masora/write.py,
  masora/mcp.py, masora/index.py, FORMAT.md §4,
  docs/TROUBLESHOOTING.md, tests.
- [x] Search discoverability: every hit group (CLI + MCP) ends with
  `details: masora explain <lineage>` — the door to the full story. →
  masora/cli.py, masora/mcp.py, tests.
- [x] The retrieval-budget skill pass (rollout lesson: rg-as-entry-point
  sub-agent briefs bypassed the graph): a `## Retrieval budget` section —
  the ORDER (masora search, retry ONCE with alternate words → `explain`
  before relying → cppgraph for C++ structure → ONE narrow text search ONLY
  outside the graph's index (comments, doc-comments, non-C++ tests,
  configs, prose), never repo-wide, never silently broadened); the
  anti-grep rule in "How to note well" is now two-sided (graph for symbols/
  structure; targeted text search legitimate for what the graph does not
  index); the tests-as-evidence rule in "Verify discipline". →
  docs/AGENT_INSTRUCTIONS.md, docs/skills/masora/SKILL.md,
  tests/test_docs.py.
- [x] The cppgraph-side input hygiene + the configurable fact budget:
  docs/CPPGRAPH_INTEGRATION.md gains `## Input hygiene (cppgraph side)`
  (unknown parameters REJECTED — a typo'd param silently returns unfiltered
  results; an absent path/filter target = an explicit error, never a silent
  whole-repo broadening; strict-argument tests required) and §6's fact
  count is configurable (default 2 — e.g. CPPGRAPH_MASORA_MAX_FACTS; the
  ≤ 60-token guidance stands). MASORA_DESIGN §12 gains the OPEN
  cross-analysis tests×code idea (item 11). →
  docs/CPPGRAPH_INTEGRATION.md, MASORA_DESIGN.md §12.
- [ ] First rollout: create the base on the author's `employees/` dir + Confluence install page (install, `masora setup --base <url>`, usage); migration to a dedicated repo if adopted.
- [ ] Agent-graded evaluation of the phase objective — the protocol is
  WRITTEN (docs/EVALUATION.md, pre-registered: paired A/B over ~20 tasks —
  8 templates grounded in the rollout base's recorded summaries + ≥ 4
  control tasks to detect false help; the repeated-wrong-deduction rubric
  with the claim list as the grader's reference; tool-call, total-token and
  injected-token accounting; seed-check, randomized task × condition order,
  the recording sheet; the verdict rule: strictly fewer repeated wrong
  deductions AND no token-cost regression beyond the injected tokens — the
  numbers decide adoption). REMAINS: the RUN — bind the task list to the
  real recorded summaries at the seed-check, execute the batch, fill the
  sheet, apply the verdict rule.

Clarifications to settle as each task starts (final audit 2026-09-25):

- `check` append-only baseline: diff against `origin/main` by file content; distinguish a `gc` whole-lineage deletion from tampering; tolerate dangling events across PRs (index warns and ignores).
- Index location and scope: one index per base × code repo; rebuild triggers (write, pull, HEAD change, cppgraph reindex); full rebuild (disposable).
- Contract for cppgraph reading the index: path discovery, schema version, concurrent readers, which checkout the statuses were computed for.
- Neighbour-snapshot cap for hub symbols (deterministic truncation + `truncated` flag).
- Credential-shaped content: detector (gitleaks-style patterns + entropy), scanned fields, reject-with-error at `note`.
- YAML details: monotonic ULID generation; `unanchored` reason field name (distinct from `reason`); `ambiguous` outcome at `note` returns candidates and writes nothing.
- MCP transport (stdio) and the envelope JSON shape (cap + omitted-count fields).
- Envelopes always show `source` (+ `name`/`effort` when present — FORMAT.md unified provenance; solo-base loophole: nothing prevents self-verifying Stop-hook extractions; review is the trust path).
- `cost_tokens` is passed by the agent when it knows it (skill guidance); the tool never invents it.

Out of scope:

- Non-code anchor providers (`file`, `url`).
- Advanced MCP tools: `unrefute`, `recheck`, `history` (`explain` is PROMOTED to the checklist above — the evidence-chain surface now exists).
- CI pipeline wiring (publication is PR-based; `masora check` runs locally in `sync`).
- Duplicate-lineage handling (`same-as`).

### Phase 2 — beyond cppgraph

Deferred — a spec seed recorded on 2026-09-29; reopen when non-code knowledge
is wanted, without cppgraph.

- [ ] Agent hooks (an injection channel without cppgraph):
  - `SessionStart`: background pull of the base with silent failure, plus a summary of stale lineages;
  - `UserPromptSubmit`: FTS over the prompt, injection of 2-3 claims;
  - strict caps (summary ≈ 100 tokens, 2-3 claims per prompt);
  - FTS thresholds (minimum prompt length, minimum score — search is lexical, false positives are a risk);
  - injected-token accounting in the evaluation protocol;
  - purpose = non-code knowledge, without cppgraph.

- [ ] Symbol-addressed search fallback: exercise the base via CLI/MCP `search` by symbol on machines without cppgraph (the anchors table exists; the FTS covers summary + statement only).

<!-- Block template to duplicate per phase:

### Phase N: <name>

Objective:

Tasks:
- [ ] ...

Out of scope:

-->
